from __future__ import annotations

import functools
from types import SimpleNamespace

import httpx
import pytest

from app.acquisition import runtime as acquisition_runtime
from app.acquisition import browser_fetch_runner
from app.acquisition.browser_page_flow import _ensure_public_landed_url
from app.acquisition.browser_route_blocking import block_unneeded_route
from app.core.url_safety import (
    SecurityError,
    get_with_validated_redirects,
    validate_public_url_host,
)


def _as_async(func):
    @functools.wraps(func)
    async def _wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return _wrapper


class _FakeGetClient:
    """Minimal httpx.AsyncClient stand-in: records requested URLs and serves
    canned responses keyed by URL."""

    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    async def get(self, url: str, **_kwargs: object) -> object:
        self.requested_urls.append(url)
        return self._responses[url]


def _redirect_response(
    url: str, location: str, status_code: int = 302
) -> httpx.Response:
    return httpx.Response(
        status_code,
        headers={"location": location},
        request=httpx.Request("GET", url),
    )


def _ok_response(
    url: str, text: str = "<html><body>ok</body></html>"
) -> httpx.Response:
    return httpx.Response(
        200,
        text=text,
        request=httpx.Request("GET", url),
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_redirect_to_private_ip_is_blocked_before_request() -> None:
    start_url = "https://example.com/start"
    private_url = "http://169.254.169.254/latest/meta-data"
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, private_url),
        }
    )

    with pytest.raises(SecurityError, match="non-public|blocked platform"):
        await get_with_validated_redirects(client, start_url)

    assert client.requested_urls == [start_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_redirect_to_loopback_is_blocked_before_request() -> None:
    start_url = "https://example.com/start"
    loopback_url = "http://127.0.0.1:6379/"
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, loopback_url),
        }
    )

    with pytest.raises(SecurityError):
        await get_with_validated_redirects(client, start_url)

    assert client.requested_urls == [start_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_redirect_to_public_url_is_followed() -> None:
    start_url = "https://example.com/start"
    final_url = "https://public.example/final"
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, final_url),
            final_url: _ok_response(final_url),
        }
    )

    response = await get_with_validated_redirects(client, start_url)

    assert response.status_code == 200
    assert client.requested_urls == [start_url, final_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_relative_redirect_location_is_resolved_and_followed() -> None:
    start_url = "https://example.com/start"
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, "/moved"),
            "https://example.com/moved": _ok_response("https://example.com/moved"),
        }
    )

    response = await get_with_validated_redirects(client, start_url)

    assert response.status_code == 200
    assert client.requested_urls == [start_url, "https://example.com/moved"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_redirect_chain_is_capped() -> None:
    hop_urls = [f"https://example.com/hop-{index}" for index in range(8)]
    responses = {
        url: _redirect_response(url, hop_urls[index + 1])
        for index, url in enumerate(hop_urls[:-1])
    }
    responses[hop_urls[-1]] = _ok_response(hop_urls[-1])
    client = _FakeGetClient(responses)

    with pytest.raises(ValueError, match="Too many redirects"):
        await get_with_validated_redirects(client, hop_urls[0], max_redirects=5)

    # Initial request plus the 5 allowed redirect hops, never a 7th request.
    assert client.requested_urls == hop_urls[:6]


@pytest.mark.asyncio
@pytest.mark.component
async def test_initial_url_is_validated_before_first_request() -> None:
    client = _FakeGetClient({})

    with pytest.raises(SecurityError):
        await get_with_validated_redirects(client, "http://169.254.169.254/")

    assert client.requested_urls == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_redirect_to_hostname_resolving_private_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_url = "https://example.com/start"
    internal_url = "https://internal.example/secret"

    async def _resolve(hostname: str, _port: int, **_kwargs: object) -> list[str]:
        if hostname == "internal.example":
            return ["10.0.0.5"]
        return ["93.184.216.34"]

    monkeypatch.setattr("app.core.url_safety._resolve_host_ips", _resolve)
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, internal_url),
            internal_url: _ok_response(internal_url),
        }
    )

    with pytest.raises(SecurityError, match="non-public"):
        await get_with_validated_redirects(client, start_url)

    assert client.requested_urls == [start_url]


@pytest.mark.component
def test_validate_public_url_host_blocks_literal_private_targets() -> None:
    for url in (
        "http://169.254.169.254/latest/meta-data",
        "http://127.0.0.1:8001/api/metrics",
        "http://10.1.2.3/internal",
        "http://[::1]/",
        "http://localhost/admin",
        "http://printer.local/status",
    ):
        with pytest.raises(SecurityError):
            validate_public_url_host(url)


@pytest.mark.component
def test_validate_public_url_host_allows_public_and_non_http_targets() -> None:
    for url in (
        "https://example.com/products/1",
        "http://93.184.216.34/index.html",
        "data:text/html,<html></html>",
        "about:blank",
        "",
    ):
        validate_public_url_host(url)


class _FakeRoute:
    def __init__(self, url: str, resource_type: str = "document") -> None:
        self.request = SimpleNamespace(url=url, resource_type=resource_type)
        self.aborted = False
        self.continued = False

    async def abort(self) -> None:
        self.aborted = True

    async def continue_(self) -> None:
        self.continued = True


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_route_aborts_private_ip_document_request() -> None:
    route = _FakeRoute("http://169.254.169.254/latest/meta-data")

    await block_unneeded_route(route)

    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_route_aborts_internal_hostname_subresource() -> None:
    route = _FakeRoute("http://localhost:8001/api/metrics", resource_type="xhr")

    await block_unneeded_route(route)

    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_route_does_not_continue_private_target_when_abort_fails() -> (
    None
):
    route = _FakeRoute("http://169.254.169.254/latest/meta-data")

    async def fail_abort() -> None:
        raise RuntimeError("abort failed")

    route.abort = fail_abort

    await block_unneeded_route(route)

    assert route.continued is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_route_aborts_hostname_with_mixed_dns_answers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _mixed_answers(*_args, **_kwargs) -> list[str]:
        return ["93.184.216.34", "10.0.0.5"]

    monkeypatch.setattr("app.core.url_safety._resolve_host_ips", _mixed_answers)
    route = _FakeRoute("https://cdn.example/app.js", resource_type="script")

    await block_unneeded_route(route)

    assert route.aborted is True
    assert route.continued is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_route_continues_public_document_request() -> None:
    route = _FakeRoute("https://example.com/products/shoe")

    await block_unneeded_route(route)

    assert route.aborted is False
    assert route.continued is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_landed_url_validation_rejects_private_final_url() -> None:
    page = SimpleNamespace(url="http://169.254.169.254/latest/meta-data")
    response = SimpleNamespace(url="http://169.254.169.254/latest/meta-data")

    with pytest.raises(SecurityError):
        await _ensure_public_landed_url(page, response)


@pytest.mark.asyncio
@pytest.mark.component
async def test_landed_url_validation_allows_public_final_url() -> None:
    page = SimpleNamespace(url="https://example.com/products/1")
    response = SimpleNamespace(url="https://example.com/products/1")

    await _ensure_public_landed_url(page, response)


@pytest.mark.asyncio
@pytest.mark.component
async def test_landed_url_validation_skips_non_http_pages() -> None:
    page = SimpleNamespace(url="about:blank")

    await _ensure_public_landed_url(page, None)


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_fetch_blocks_redirect_to_private_ip() -> None:
    start_url = "https://example.com/products/1"
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, "http://169.254.169.254/"),
        }
    )

    @_as_async
    def _fake_get_client(*, proxy: str | None = None):
        del proxy
        return client

    @_as_async
    def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    with pytest.raises(SecurityError):
        await acquisition_runtime.http_fetch(
            start_url,
            5,
            get_client=_fake_get_client,
            blocked_html_checker=_not_blocked,
        )

    assert client.requested_urls == [start_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_fetch_follows_redirect_to_public_url() -> None:
    start_url = "https://example.com/products/1"
    final_url = "https://shop.example/products/1"
    client = _FakeGetClient(
        {
            start_url: _redirect_response(start_url, final_url),
            final_url: _ok_response(final_url),
        }
    )

    @_as_async
    def _fake_get_client(*, proxy: str | None = None):
        del proxy
        return client

    @_as_async
    def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    result = await acquisition_runtime.http_fetch(
        start_url,
        5,
        get_client=_fake_get_client,
        blocked_html_checker=_not_blocked,
    )

    assert result.final_url == final_url
    assert result.status_code == 200
    assert client.requested_urls == [start_url, final_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_blocks_redirect_to_private_ip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_url = "https://example.com/products/1"
    requested_urls: list[str] = []

    def _fake_curl_get_once(
        curl_requests,
        url,
        timeout_seconds,
        *,
        proxy=None,
        cookie_header=None,
        validated_target=None,
    ):
        del curl_requests, timeout_seconds, proxy, cookie_header, validated_target
        requested_urls.append(url)
        return SimpleNamespace(
            text="",
            headers={"location": "http://169.254.169.254/"},
            status_code=302,
            url=url,
        )

    monkeypatch.setattr(
        "app.acquisition.runtime._curl_get_once",
        _fake_curl_get_once,
    )

    with pytest.raises(SecurityError):
        await acquisition_runtime.curl_fetch(start_url, 5)

    assert requested_urls == [start_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_follows_redirect_to_public_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_url = "https://example.com/products/1"
    final_url = "https://shop.example/products/1"
    requested_urls: list[str] = []
    responses = {
        start_url: SimpleNamespace(
            text="",
            headers={"location": final_url},
            status_code=302,
            url=start_url,
        ),
        final_url: SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url=final_url,
        ),
    }

    def _fake_curl_get_once(
        curl_requests,
        url,
        timeout_seconds,
        *,
        proxy=None,
        cookie_header=None,
        validated_target=None,
    ):
        del curl_requests, timeout_seconds, proxy, cookie_header, validated_target
        requested_urls.append(url)
        return responses[url]

    monkeypatch.setattr(
        "app.acquisition.runtime._curl_get_once",
        _fake_curl_get_once,
    )

    result = await acquisition_runtime.curl_fetch(start_url, 5)

    assert result.final_url == final_url
    assert result.status_code == 200
    assert requested_urls == [start_url, final_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_redirect_chain_is_capped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested_urls: list[str] = []

    def _fake_curl_get_once(
        curl_requests,
        url,
        timeout_seconds,
        *,
        proxy=None,
        cookie_header=None,
        validated_target=None,
    ):
        del curl_requests, timeout_seconds, proxy, cookie_header, validated_target
        requested_urls.append(url)
        next_url = f"https://example.com/hop-{len(requested_urls)}"
        return SimpleNamespace(
            text="",
            headers={"location": next_url},
            status_code=302,
            url=url,
        )

    monkeypatch.setattr(
        "app.acquisition.runtime._curl_get_once",
        _fake_curl_get_once,
    )

    with pytest.raises(ValueError, match="Too many redirects"):
        await acquisition_runtime.curl_fetch("https://example.com/start", 30)

    assert len(requested_urls) == 6


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_forwards_redirect_cookies_to_next_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_url = "https://example.com/start"
    final_url = "https://example.com/final"
    seen_cookie_headers: list[str] = []
    responses = {
        start_url: SimpleNamespace(
            text="",
            headers={
                "location": final_url,
                "set-cookie": "session=abc; Path=/; HttpOnly",
            },
            status_code=302,
            url=start_url,
        ),
        final_url: SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url=final_url,
        ),
    }

    def _fake_curl_get_once(
        curl_requests,
        url,
        timeout_seconds,
        *,
        proxy=None,
        cookie_header=None,
        validated_target=None,
    ):
        del curl_requests, timeout_seconds, proxy, validated_target
        seen_cookie_headers.append(str(cookie_header or ""))
        return responses[url]

    monkeypatch.setattr(
        "app.acquisition.runtime._curl_get_once",
        _fake_curl_get_once,
    )

    result = await acquisition_runtime.curl_fetch(
        start_url,
        5,
        cookie_header="pref=dark",
    )

    assert result.status_code == 200
    assert seen_cookie_headers == ["pref=dark", "pref=dark; session=abc"]


def test_shared_http_client_does_not_auto_follow_redirects() -> None:
    # Regression guard for the SSRF fix: the shared acquisition client must
    # never auto-follow; redirects are followed manually with per-hop
    # validation.
    import inspect as _inspect

    source = _inspect.getsource(acquisition_runtime.get_shared_http_client)
    assert "follow_redirects=False" in source
    assert "follow_redirects=True" not in source


@pytest.mark.component
def test_curl_resolve_entry_pins_validated_ipv4_and_ipv6_targets() -> None:
    assert (
        acquisition_runtime._curl_resolve_entry(
            SimpleNamespace(
                hostname="shop.example",
                port=443,
                resolved_ips=("93.184.216.34",),
            )
        )
        == "shop.example:443:93.184.216.34"
    )
    assert (
        acquisition_runtime._curl_resolve_entry(
            SimpleNamespace(
                hostname="shop.example",
                port=443,
                resolved_ips=("2606:2800:220:1:248:1893:25c8:1946",),
            )
        )
        == "shop.example:443:[2606:2800:220:1:248:1893:25c8:1946]"
    )


@pytest.mark.component
def test_curl_body_writer_stops_before_oversize_buffer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        acquisition_runtime.crawler_runtime_settings,
        "http_response_max_bytes",
        5,
    )
    body = bytearray()
    writer = acquisition_runtime._bounded_curl_body_writer(body)

    writer(b"abc")
    with pytest.raises(ValueError, match="exceeds 5 bytes"):
        writer(b"def")

    assert body == b"abc"


@pytest.mark.asyncio
@pytest.mark.component
async def test_screenshot_mode_still_installs_browser_ssrf_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PayloadCapture:
        def attach(self, _page: object) -> None:
            return None

    class _Page:
        def __init__(self) -> None:
            self.routes: list[tuple[str, object]] = []

        async def route(self, pattern: str, handler: object) -> None:
            self.routes.append((pattern, handler))

    monkeypatch.setattr(
        browser_fetch_runner,
        "_build_payload_capture",
        lambda _surface: _PayloadCapture(),
    )
    monkeypatch.setattr(
        browser_fetch_runner,
        "resolve_browser_fetch_policy",
        lambda **_kwargs: (False, {}, None),
    )
    page = _Page()
    state = SimpleNamespace(
        request=SimpleNamespace(
            capture_screenshot=True,
            url="https://example.com",
            traversal_mode=None,
        ),
        normalized_surface="test",
    )

    await browser_fetch_runner._configure_page(page, state)

    assert page.routes == [("**/*", block_unneeded_route)]


@pytest.mark.asyncio
@pytest.mark.component
async def test_browser_fetch_aborts_when_ssrf_route_installation_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _PayloadCapture:
        def attach(self, _page: object) -> None:
            return None

    class _Page:
        async def route(self, _pattern: str, _handler: object) -> None:
            raise RuntimeError("route install failed")

    monkeypatch.setattr(
        browser_fetch_runner,
        "_build_payload_capture",
        lambda _surface: _PayloadCapture(),
    )
    state = SimpleNamespace(
        request=SimpleNamespace(
            url="https://example.com",
            traversal_mode=None,
        ),
        normalized_surface="test",
    )

    with pytest.raises(RuntimeError, match="route install failed"):
        await browser_fetch_runner._configure_page(_Page(), state)
