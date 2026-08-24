from __future__ import annotations

import gzip
import socket

import httpx
import pytest

from app.core import url_safety
from app.core.config.security_rules import (
    BLOCKED_HOSTNAMES,
    BLOCKED_IPS,
    CGNAT_NETWORK,
)


@pytest.fixture(autouse=True)
def _stub_public_dns_resolution():
    # Shadows the global DNS stub so this module can exercise url_safety resolution.
    yield


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_host_ips_falls_back_to_ipv4_after_unspec_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[int] = []

    def _fake_getaddrinfo(hostname: str, port: int, family: int, socktype: int):
        del hostname, port, socktype
        calls.append(family)
        if family == socket.AF_UNSPEC:
            raise socket.gaierror(11001, "getaddrinfo failed")
        return [
            (
                socket.AF_INET,
                socket.SOCK_STREAM,
                6,
                "",
                ("93.184.216.34", 443),
            )
        ]

    monkeypatch.setattr(
        "app.core.url_safety.socket.getaddrinfo",
        _fake_getaddrinfo,
    )
    monkeypatch.setattr(
        "app.core.url_safety.dns_resolution_families",
        lambda: (socket.AF_UNSPEC, socket.AF_INET),
    )

    resolved = await url_safety._resolve_host_ips("example.com", 443)

    assert resolved == ["93.184.216.34"]
    assert calls == [socket.AF_UNSPEC, socket.AF_INET]


@pytest.mark.asyncio
@pytest.mark.component
async def test_validate_public_target_rejects_configured_blocked_hostname() -> None:
    blocked_hostname = sorted(BLOCKED_HOSTNAMES)[0]

    with pytest.raises(url_safety.SecurityError, match="Target host is not allowed"):
        await url_safety.validate_public_target(f"https://{blocked_hostname}/")


@pytest.mark.component
def test_raise_if_non_public_ip_rejects_configured_blocked_ip() -> None:
    blocked_ip = sorted(BLOCKED_IPS)[0]

    with pytest.raises(
        url_safety.SecurityError,
        match="Target host resolves to a blocked platform IP address",
    ):
        url_safety._raise_if_non_public_ip(blocked_ip, "blocked.example", "Target")


@pytest.mark.component
def test_raise_if_non_public_ip_rejects_cgnat_range() -> None:
    ip_value = CGNAT_NETWORK.network_address + 1

    with pytest.raises(
        url_safety.SecurityError,
        match="Target host resolves to a non-public IP address",
    ):
        url_safety._raise_if_non_public_ip(ip_value, "cgnat.example", "Target")


@pytest.mark.component
def test_rebuild_url_preserves_explicit_ipv6_port() -> None:
    target = url_safety.ValidatedTarget(
        hostname="::1",
        scheme="http",
        port=8080,
        resolved_ips=("::1",),
    )

    assert (
        url_safety._rebuild_url("[::1]:8080/products", target)
        == "http://[::1]:8080/products"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_validate_proxy_endpoint_uses_proxy_resolution_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _always_fail_getaddrinfo(hostname: str, port: int, family: int, socktype: int):
        del hostname, port, family, socktype
        raise socket.gaierror(11001, "getaddrinfo failed")

    monkeypatch.setattr(
        "app.core.url_safety.socket.getaddrinfo",
        _always_fail_getaddrinfo,
    )
    monkeypatch.setattr(
        "app.core.url_safety.dns_resolution_families",
        lambda: (socket.AF_UNSPEC,),
    )

    with pytest.raises(ValueError, match="Proxy host could not be resolved"):
        await url_safety.validate_proxy_endpoint("http://proxy.example:8080")


@pytest.mark.asyncio
@pytest.mark.component
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://169.254.169.254/latest/meta-data",
        "http://169.254.1.1/",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
    ],
)
async def test_validate_public_target_rejects_private_and_metadata_ranges(
    url: str,
) -> None:
    with pytest.raises(url_safety.SecurityError):
        await url_safety.validate_public_target(url)


@pytest.mark.asyncio
@pytest.mark.component
async def test_validate_public_target_rejects_mixed_public_private_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _mixed_answers(*_args, **_kwargs) -> list[str]:
        return ["93.184.216.34", "10.0.0.5"]

    monkeypatch.setattr(url_safety, "_resolve_host_ips", _mixed_answers)

    with pytest.raises(url_safety.SecurityError, match="non-public"):
        await url_safety.validate_public_target("https://mixed.example/path")


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_target_transport_pins_ip_and_preserves_host_and_sni(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _CaptureTransport(httpx.AsyncBaseTransport):
        def __init__(self) -> None:
            self.request: httpx.Request | None = None

        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            self.request = request
            return httpx.Response(200, content=b"ok")

    async def _public_answer(*_args, **_kwargs) -> list[str]:
        return ["93.184.216.34"]

    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_answer)
    inner = _CaptureTransport()
    transport = url_safety.PublicTargetAsyncTransport(inner, pin_direct=False)
    request = httpx.Request("GET", "https://shop.example:8443/products/1")

    response = await transport.handle_async_request(request)

    assert response.status_code == 200
    assert inner.request is not None
    assert inner.request.url.host == "shop.example"
    assert inner.request.headers["host"] == "shop.example:8443"
    assert inner.request.extensions["sni_hostname"] == "shop.example"


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_target_network_backend_connects_to_validated_ip() -> None:
    class _CaptureBackend:
        host = ""

        async def connect_tcp(self, host, port, **kwargs):
            del port, kwargs
            self.host = host
            return object()

    inner = _CaptureBackend()
    backend = url_safety._PinnedAsyncNetworkBackend(inner)
    token = url_safety._PINNED_TARGET.set(("shop.example", "93.184.216.34"))
    try:
        await backend.connect_tcp("shop.example", 443)
    finally:
        url_safety._PINNED_TARGET.reset(token)

    assert inner.host == "93.184.216.34"


class _ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


async def _public_dns(*_args, **_kwargs) -> list[str]:
    return ["93.184.216.34"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_limited_response_rejects_advertised_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-length": "101"},
            stream=_ChunkStream([b"ok"]),
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(url_safety.ResponseBodyTooLarge, match="Content-Length"):
            await url_safety.get_with_validated_redirects(
                client, "https://example.com", max_response_bytes=100
            )


@pytest.mark.asyncio
@pytest.mark.component
async def test_limited_response_rejects_chunked_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            stream=_ChunkStream([b"abc", b"def"]),
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(url_safety.ResponseBodyTooLarge):
            await url_safety.get_with_validated_redirects(
                client, "https://example.com", max_response_bytes=5
            )


@pytest.mark.asyncio
@pytest.mark.component
async def test_limited_response_rejects_compressed_decoded_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)
    compressed = gzip.compress(b"x" * 1000)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=_ChunkStream([compressed]),
            request=request,
        )
    )
    async with httpx.AsyncClient(transport=transport) as client:
        with pytest.raises(url_safety.ResponseBodyTooLarge):
            await url_safety.get_with_validated_redirects(
                client, "https://example.com", max_response_bytes=100
            )


@pytest.mark.asyncio
@pytest.mark.component
async def test_limited_response_preserves_legitimate_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(url_safety, "_resolve_host_ips", _public_dns)
    transport = httpx.MockTransport(
        lambda request: httpx.Response(200, content=b"hello", request=request)
    )
    async with httpx.AsyncClient(transport=transport) as client:
        response = await url_safety.get_with_validated_redirects(
            client, "https://example.com", max_response_bytes=5
        )

    assert response.text == "hello"
