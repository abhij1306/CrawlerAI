from __future__ import annotations

import asyncio
import ipaddress
import socket
from collections.abc import Iterable
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import ParseResult, urljoin, urlparse

import httpx

from app.core.config.block_signatures import (
    MAX_VALIDATED_REDIRECTS,
    REDIRECT_FOLLOW_STATUS_CODES,
)
from app.core.config.security_rules import (
    ALLOWED_PROXY_SCHEMES,
    ALLOWED_TARGET_SCHEMES,
    BLOCKED_HOSTNAMES,
    BLOCKED_HOST_SUFFIXES,
    BLOCKED_IPS,
    CGNAT_NETWORK,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.records.network_resolution import dns_resolution_families


class SecurityError(ValueError):
    """Raised when a URL is rejected for security policy reasons (SSRF guard,
    blocked hostname/IP, non-public resolution). Subclasses ValueError so
    existing `except ValueError` callers continue to work; security-aware
    callers can catch SecurityError specifically to distinguish SSRF
    rejections from generic input-validation failures."""


class ResponseBodyTooLarge(ValueError):
    """Raised before an untrusted upstream body exceeds its byte budget."""


@dataclass(frozen=True)
class ValidatedTarget:
    hostname: str
    scheme: str
    port: int
    resolved_ips: tuple[str, ...]
    dns_resolved: bool = True


_PINNED_TARGET: ContextVar[tuple[str, str] | None] = ContextVar(
    "public_target_pin",
    default=None,
)


class _PinnedAsyncNetworkBackend:
    def __init__(self, backend: Any) -> None:
        self._backend = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Any = None,
    ) -> Any:
        pin = _PINNED_TARGET.get()
        connect_host = pin[1] if pin is not None and host == pin[0] else host
        return await self._backend.connect_tcp(
            host=connect_host,
            port=port,
            timeout=timeout,
            local_address=local_address,
            socket_options=socket_options,
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Any = None,
    ) -> Any:
        return await self._backend.connect_unix_socket(
            path=path,
            timeout=timeout,
            socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class PublicTargetAsyncTransport(httpx.AsyncBaseTransport):
    """Bind an HTTPX connection to the IP approved by URL validation."""

    def __init__(
        self,
        transport: httpx.AsyncBaseTransport,
        *,
        pin_direct: bool = True,
    ) -> None:
        self._transport = transport
        self._pin_direct = pin_direct
        if pin_direct:
            pool: Any = getattr(transport, "_pool", None)
            backend = getattr(pool, "_network_backend", None)
            if not callable(getattr(backend, "connect_tcp", None)):
                raise TypeError(
                    "Public target pinning requires an HTTPX network backend"
                )
            pool._network_backend = _PinnedAsyncNetworkBackend(backend)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        target = await validate_public_target(str(request.url))
        headers = httpx.Headers(request.headers)
        headers["Host"] = _http_host_header(target)
        extensions = dict(request.extensions)
        extensions["sni_hostname"] = target.hostname
        pinned_request = httpx.Request(
            method=request.method,
            url=request.url,
            headers=headers,
            stream=request.stream,
            extensions=extensions,
        )
        if not self._pin_direct:
            return await self._transport.handle_async_request(pinned_request)
        token = _PINNED_TARGET.set(
            (request.url.raw_host.decode("ascii"), target.resolved_ips[0])
        )
        try:
            return await self._transport.handle_async_request(pinned_request)
        finally:
            _PINNED_TARGET.reset(token)

    async def aclose(self) -> None:
        await self._transport.aclose()


def wrap_public_target_transport(
    transport: httpx.AsyncBaseTransport,
    *,
    pin_direct: bool = True,
) -> httpx.AsyncBaseTransport:
    return PublicTargetAsyncTransport(transport, pin_direct=pin_direct)


async def ensure_public_crawl_targets(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_url in urls:
        candidate = str(raw_url or "").strip()
        if not candidate:
            continue
        result = await validate_public_target(candidate)
        normalized_url = _rebuild_url(candidate, result)
        if normalized_url in seen:
            continue
        seen.add(normalized_url)
        normalized.append(normalized_url)
    return normalized


async def validate_public_target(url: str) -> ValidatedTarget:
    raw = str(url or "").strip()
    parsed = urlparse(raw)
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ALLOWED_TARGET_SCHEMES:
        if not scheme and raw and not raw.startswith(("/", "#")):
            raw = f"https://{raw}"
            parsed = urlparse(raw)
            scheme = "https"
        else:
            raise ValueError("Only http:// and https:// targets are allowed")

    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Target URL must include a hostname")
    return await _validate_endpoint_host(
        hostname=hostname,
        scheme=scheme,
        port=_target_port(parsed),
        label="Target",
        unresolved_detail="Target host could not be resolved to a valid IP address",
        wrap_resolution_error=True,
    )


def _parse_proxy_endpoint(proxy_url: str) -> ParseResult:
    """Structural proxy validation: allowed scheme + hostname present."""
    parsed = urlparse(str(proxy_url or "").strip())
    scheme = str(parsed.scheme or "").lower()
    if scheme not in ALLOWED_PROXY_SCHEMES:
        raise ValueError(
            "Only http://, https://, socks5://, and socks5h:// proxy endpoints are allowed"
        )
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        raise ValueError("Proxy URL must include a hostname")
    return parsed


async def validate_proxy_endpoint(proxy_url: str) -> ValidatedTarget:
    parsed = _parse_proxy_endpoint(proxy_url)
    return await _validate_endpoint_host(
        hostname=str(parsed.hostname or "").strip().lower(),
        scheme=str(parsed.scheme or "").lower(),
        port=_target_port(parsed),
        label="Proxy",
        unresolved_detail="Proxy host could not be resolved to a valid IP address",
        wrap_resolution_error=False,
    )


async def ensure_valid_proxy_endpoints(proxy_urls: Iterable[str]) -> None:
    """Validate run proxy endpoints at creation.

    Structural errors (scheme, hostname) always reject. The DNS/public-IP
    host guard only runs while proxy_endpoint_validation_enabled is on;
    operators routing through internal proxies can opt out of that half.
    """
    validate_hosts = bool(crawler_runtime_settings.proxy_endpoint_validation_enabled)
    for raw_url in proxy_urls:
        candidate = str(raw_url or "").strip()
        if not candidate:
            continue
        if validate_hosts:
            await validate_proxy_endpoint(candidate)
        else:
            _parse_proxy_endpoint(candidate)


def validate_public_url_host(url: str) -> None:
    """Synchronous host-level SSRF check for contexts where DNS resolution is
    not feasible (browser route interception runs per request and cannot stall
    on resolver I/O). Blocks literal non-public IPs and configured internal /
    blocked hostnames. Regular hostnames pass here and are fully validated
    (with DNS resolution) at the fetch / post-navigation boundary instead.
    Non-http(s) URLs are out of scope and pass through."""
    parsed = urlparse(str(url or "").strip())
    if str(parsed.scheme or "").lower() not in ALLOWED_TARGET_SCHEMES:
        return
    hostname = str(parsed.hostname or "").strip().lower()
    if not hostname:
        return
    _raise_if_blocked_hostname(hostname, "Target")
    literal_ip = _parse_ip(hostname)
    if literal_ip is not None:
        _raise_if_non_public_ip(literal_ip, hostname, "Target")


def get_redirect_location(response: Any) -> str | None:
    """Return the redirect Location for a 3xx response, else None."""
    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code not in REDIRECT_FOLLOW_STATUS_CODES:
        return None
    headers = getattr(response, "headers", None)
    get_header = getattr(headers, "get", None)
    if get_header is None:
        return None
    location = str(get_header("location", "") or "").strip()
    return location or None


async def get_with_validated_redirects(
    client: Any,
    url: str,
    *,
    max_redirects: int = MAX_VALIDATED_REDIRECTS,
    max_response_bytes: int | None = None,
    **request_kwargs: Any,
) -> Any:
    """Issue a GET against ``client`` following redirects manually.

    Every request target — the initial URL and each 3xx ``Location`` — is
    validated with :func:`validate_public_target` immediately BEFORE the
    request is issued, so a validated public URL cannot bounce the fetcher
    into loopback / link-local / RFC1918 / metadata address space via a
    redirect. The production HTTPX client also uses
    :class:`PublicTargetAsyncTransport`, which binds the connection to the
    approved IP while retaining the original Host header and TLS SNI.

    ``client`` must be built with ``follow_redirects=False``; each hop is a
    plain ``client.get(current_url, **request_kwargs)`` call.

    Cookies set during the chain are held in a jar owned by this call and
    re-matched (domain/path/Secure) against each hop's URL, rather than on
    the client. The acquisition client is shared across runs and users, so a
    client-level jar would replay one run's cookies on another run's
    requests; a per-call jar keeps the normal redirect-chain behavior without
    that bleed. Callers that manage cookies themselves (a ``cookies`` kwarg
    or their own ``Cookie`` header) are left untouched.
    """
    current_url = str(url or "").strip()
    redirect_count = 0
    cookies: httpx.Cookies | None = None
    if "cookies" not in request_kwargs and not _has_cookie_header(request_kwargs):
        cookies = httpx.Cookies()
    while True:
        await validate_public_target(current_url)
        response = await _get_limited_response(
            client,
            current_url,
            max_response_bytes=max_response_bytes,
            request_kwargs=_hop_request_kwargs(request_kwargs, cookies, current_url),
        )
        location = get_redirect_location(response)
        if location is None:
            return response
        redirect_count += 1
        if redirect_count > max(0, int(max_redirects)):
            raise ValueError(
                f"Too many redirects while fetching {url} "
                f"(limit {max(0, int(max_redirects))})"
            )
        if cookies is not None and isinstance(response, httpx.Response):
            cookies.extract_cookies(response)
        current_url = urljoin(current_url, location)


def _has_cookie_header(request_kwargs: dict[str, Any]) -> bool:
    return "cookie" in httpx.Headers(request_kwargs.get("headers"))


def _hop_request_kwargs(
    request_kwargs: dict[str, Any],
    cookies: httpx.Cookies | None,
    url: str,
) -> dict[str, Any]:
    if cookies is None:
        return request_kwargs
    cookie_value = cookie_header_for_url(cookies, url)
    if not cookie_value:
        return request_kwargs
    headers = httpx.Headers(request_kwargs.get("headers"))
    headers["Cookie"] = cookie_value
    return {**request_kwargs, "headers": headers}


def cookie_header_for_url(cookies: httpx.Cookies, url: str) -> str:
    """Return the ``Cookie`` header value ``cookies`` allows for ``url``.

    Matching is delegated to the stdlib cookie jar, so domain, path and
    Secure are all honoured for the specific hop being requested.
    """

    request = httpx.Request("GET", url)
    cookies.set_cookie_header(request)
    return str(request.headers.get("Cookie", "") or "")


async def _get_limited_response(
    client: Any,
    url: str,
    *,
    max_response_bytes: int | None,
    request_kwargs: dict[str, Any],
) -> Any:
    if max_response_bytes is None or not callable(getattr(client, "stream", None)):
        response = await client.get(url, **request_kwargs)
        _check_loaded_response_size(response, max_response_bytes)
        return response
    limit = max(1, int(max_response_bytes))
    async with client.stream("GET", url, **request_kwargs) as response:
        advertised = _advertised_content_length(response)
        if advertised is not None and advertised > limit:
            raise ResponseBodyTooLarge(
                f"Upstream response Content-Length {advertised} exceeds {limit} bytes"
            )
        chunks: list[bytes] = []
        decoded_bytes = 0
        async for chunk in response.aiter_bytes():
            decoded_bytes += len(chunk)
            downloaded = int(getattr(response, "num_bytes_downloaded", 0) or 0)
            if decoded_bytes > limit or downloaded > limit:
                raise ResponseBodyTooLarge(f"Upstream response exceeds {limit} bytes")
            chunks.append(chunk)
        response._content = b"".join(chunks)
        return response


def _check_loaded_response_size(response: Any, limit: int | None) -> None:
    if limit is None:
        return
    maximum = max(1, int(limit))
    advertised = _advertised_content_length(response)
    if advertised is not None and advertised > maximum:
        raise ResponseBodyTooLarge(
            f"Upstream response Content-Length {advertised} exceeds {maximum} bytes"
        )
    content = bytes(getattr(response, "content", b"") or b"")
    if len(content) > maximum:
        raise ResponseBodyTooLarge(f"Upstream response exceeds {maximum} bytes")


def _advertised_content_length(response: Any) -> int | None:
    headers = getattr(response, "headers", None)
    getter = getattr(headers, "get", None)
    if not callable(getter):
        return None
    raw_value = getter("content-length")
    if raw_value is None:
        return None
    try:
        return max(0, int(raw_value))
    except (TypeError, ValueError):
        return None


async def _validate_endpoint_host(
    *,
    hostname: str,
    scheme: str,
    port: int,
    label: str,
    unresolved_detail: str,
    wrap_resolution_error: bool,
) -> ValidatedTarget:
    _raise_if_blocked_hostname(hostname, label)
    literal_ip = _parse_ip(hostname)
    if literal_ip is not None:
        _raise_if_non_public_ip(literal_ip, hostname, label)
        return ValidatedTarget(
            hostname=hostname,
            scheme=scheme,
            port=port,
            resolved_ips=(hostname,),
            dns_resolved=False,
        )

    try:
        resolved_ips = await _resolve_host_ips(hostname, port, label=label)
    except ValueError as exc:
        if not wrap_resolution_error:
            raise
        raise ValueError(f"{unresolved_detail}: {hostname}") from exc
    validated_ips: list[str] = []
    for ip_text in resolved_ips:
        ip_value = _parse_ip(ip_text)
        if ip_value is None:
            continue
        _raise_if_non_public_ip(ip_value, hostname, label)
        validated_ips.append(ip_text)
    if not validated_ips:
        raise ValueError(f"{unresolved_detail}: {hostname}")
    return ValidatedTarget(
        hostname=hostname,
        scheme=scheme,
        port=port,
        resolved_ips=tuple(validated_ips),
    )


async def _resolve_host_ips(
    hostname: str, port: int, *, label: str = "Target"
) -> list[str]:
    attempts = max(1, int(crawler_runtime_settings.dns_resolution_retries) + 1)
    families = dns_resolution_families()
    records: (
        list[
            tuple[
                socket.AddressFamily,
                socket.SocketKind,
                int,
                str,
                tuple[str, int] | tuple[str, int, int, int],
            ]
        ]
        | None
    ) = None
    last_error: socket.gaierror | None = None
    for attempt in range(1, attempts + 1):
        for family in families:
            try:
                raw_records = await asyncio.to_thread(
                    socket.getaddrinfo,
                    hostname,
                    port,
                    family,
                    socket.SOCK_STREAM,
                )
                records = cast(
                    list[
                        tuple[
                            socket.AddressFamily,
                            socket.SocketKind,
                            int,
                            str,
                            tuple[str, int] | tuple[str, int, int, int],
                        ]
                    ],
                    raw_records,
                )
                break
            except socket.gaierror as exc:
                last_error = exc
                continue
        if records is not None:
            break
        if attempt < attempts:
            await asyncio.sleep(
                max(0, crawler_runtime_settings.dns_resolution_retry_delay_ms) / 1000
            )
            continue
        raise ValueError(
            f"{label} host could not be resolved: {hostname}"
        ) from last_error

    resolved: list[str] = []
    seen: set[str] = set()
    if records is None:
        return resolved
    for record in records:
        sockaddr = record[4]
        ip_text = str(sockaddr[0] or "").strip()
        if not ip_text or ip_text in seen:
            continue
        seen.add(ip_text)
        resolved.append(ip_text)
    return resolved


def _parse_ip(value: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    try:
        return ipaddress.ip_address(value)
    except ValueError:
        return None


def _raise_if_blocked_hostname(hostname: str, label: str) -> None:
    if hostname in BLOCKED_HOSTNAMES or any(
        hostname.endswith(suffix) for suffix in BLOCKED_HOST_SUFFIXES
    ):
        raise SecurityError(f"{label} host is not allowed: {hostname}")


def _raise_if_non_public_ip(
    ip_value: ipaddress.IPv4Address | ipaddress.IPv6Address,
    host_label: str,
    label: str,
) -> None:
    if ip_value in BLOCKED_IPS:
        raise SecurityError(
            f"{label} host resolves to a blocked platform IP address: {host_label} -> {ip_value}"
        )
    if (
        ip_value.is_private
        or ip_value.is_loopback
        or ip_value.is_link_local
        or ip_value.is_reserved
        or (isinstance(ip_value, ipaddress.IPv4Address) and ip_value in CGNAT_NETWORK)
        or not ip_value.is_global
    ):
        raise SecurityError(
            f"{label} host resolves to a non-public IP address: {host_label} -> {ip_value}"
        )


def _rebuild_url(original: str, target: ValidatedTarget) -> str:
    parsed = urlparse(original)
    if parsed.scheme:
        return original
    reconstructed = f"{target.scheme}://{original}"
    reparsed = urlparse(reconstructed)
    port_suffix = ""
    if reparsed.port is None and target.port != _default_port(target.scheme):
        port_suffix = f":{target.port}"
    if reparsed.port is not None:
        netloc = reparsed.netloc
    else:
        hostname = reparsed.hostname or ""
        if ":" in hostname:  # IPv6 address
            hostname = f"[{hostname}]"
        netloc = hostname + port_suffix
    return reparsed._replace(scheme=target.scheme, netloc=netloc).geturl()


def _target_port(parsed: ParseResult) -> int:
    return int(parsed.port or _default_port(parsed.scheme))


def _default_port(scheme: str) -> int:
    normalized = str(scheme or "").lower()
    if normalized in {"socks5", "socks5h"}:
        return 1080
    return 443 if normalized == "https" else 80


def _http_host_header(target: ValidatedTarget) -> str:
    hostname = target.hostname
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    if target.port == _default_port(target.scheme):
        return hostname
    return f"{hostname}:{target.port}"
