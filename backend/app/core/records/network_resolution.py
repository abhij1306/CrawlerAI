from __future__ import annotations

import re
import socket
from collections.abc import Callable
from typing import Literal

import httpx

from app.core.config.runtime_settings import crawler_runtime_settings

AddressFamilyPreference = Literal["auto", "ipv4", "ipv6"]

_IPV4_LOCAL_ADDRESS = "0.0.0.0"  # nosec B104
_IPV6_LOCAL_ADDRESS = "::"  # nosec B104
_CHROME_MAJOR_VERSION_RE = re.compile(r"Chrome/(\d+)\.")


def address_family_preference() -> AddressFamilyPreference:
    value = (
        str(
            getattr(
                crawler_runtime_settings,
                "network_address_family_preference",
                "auto",
            )
            or "auto"
        )
        .strip()
        .lower()
    )
    if value == "ipv4":
        return "ipv4"
    if value == "ipv6":
        return "ipv6"
    return "auto"


def dns_resolution_families() -> tuple[int, ...]:
    preference = address_family_preference()
    if preference == "ipv4":
        return (socket.AF_INET,)
    if preference == "ipv6":
        return (socket.AF_INET6,)
    return (socket.AF_UNSPEC, socket.AF_INET)


class NonPersistentCookies(httpx.Cookies):
    """Cookie jar that never stores response cookies on the client.

    ``httpx.AsyncClient`` persists ``Set-Cookie`` values on the client jar and
    replays them on later requests to matching hosts. That is the wrong
    behavior for a client shared across runs and users: one run's cookies
    would ride along on another run's requests. Clients built with
    ``persist_cookies=False`` get this jar instead, and per-request cookie
    state is kept by the caller (see
    ``app.core.url_safety.get_with_validated_redirects``).
    """

    def extract_cookies(self, response: httpx.Response) -> None:
        return None


def build_async_http_client(
    *,
    follow_redirects: bool,
    timeout: float | httpx.Timeout,
    proxy: str | None = None,
    limits: httpx.Limits | None = None,
    force_ipv4: bool = False,
    headers: dict[str, str] | None = None,
    persist_cookies: bool = True,
    transport_wrapper: Callable[[httpx.AsyncBaseTransport], httpx.AsyncBaseTransport]
    | None = None,
) -> httpx.AsyncClient:
    transport: httpx.AsyncBaseTransport | None = _build_async_http_transport(
        proxy=proxy,
        limits=limits,
        force_ipv4=force_ipv4,
    )
    merged_headers = default_request_headers(headers=headers)
    if transport_wrapper is not None:
        transport = transport_wrapper(transport or httpx.AsyncHTTPTransport())
    if transport is not None:
        client = httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=timeout,
            headers=merged_headers,
            transport=transport,
        )
    else:
        client = httpx.AsyncClient(
            follow_redirects=follow_redirects,
            timeout=timeout,
            headers=merged_headers,
        )
    if not persist_cookies:
        # The public `cookies` setter re-wraps the value in a plain
        # httpx.Cookies, so the non-persisting jar has to be installed
        # directly.
        client._cookies = NonPersistentCookies()
    return client


def default_request_headers(
    *,
    headers: dict[str, str] | None = None,
) -> dict[str, str]:
    user_agent = crawler_runtime_settings.http_user_agent
    merged_headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": accept_language_for_locale("en-US"),
        "Upgrade-Insecure-Requests": "1",
    }
    merged_headers.update(
        _browser_client_hint_headers(
            user_agent,
            platform=_platform_label_from_user_agent(user_agent),
            mobile=False,
        )
    )
    if headers:
        merged_headers.update({str(k): str(v) for k, v in headers.items()})
    return merged_headers


def _browser_client_hint_headers(
    user_agent: str,
    *,
    platform: str,
    mobile: bool,
) -> dict[str, str]:
    major_version = _chrome_major_version(user_agent)
    if major_version is None:
        return {}
    return {
        "sec-ch-ua": (
            f'"Not:A-Brand";v="99", "Google Chrome";v="{major_version}", '
            f'"Chromium";v="{major_version}"'
        ),
        "sec-ch-ua-mobile": "?1" if mobile else "?0",
        "sec-ch-ua-platform": f'"{platform}"',
    }


def _chrome_major_version(user_agent: str) -> int | None:
    match = _CHROME_MAJOR_VERSION_RE.search(str(user_agent or ""))
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _platform_label_from_user_agent(user_agent: str) -> str:
    lowered = str(user_agent or "").lower()
    if "macintosh" in lowered or "mac os x" in lowered:
        return "macOS"
    if "linux" in lowered:
        return "Linux"
    return "Windows"


def accept_language_for_locale(locale: str) -> str:
    normalized = str(locale or "").strip()
    if not normalized:
        return "en-US,en;q=0.9"
    language = normalized.split("-", 1)[0].strip()
    if not language or language.lower() == normalized.lower():
        return normalized
    return f"{normalized},{language};q=0.9"


def _build_async_http_transport(
    *,
    proxy: str | None,
    limits: httpx.Limits | None,
    force_ipv4: bool,
) -> httpx.AsyncHTTPTransport | None:
    local_address = _local_address_for_http(force_ipv4=force_ipv4)
    if local_address is None and proxy is None and limits is None:
        return None
    return httpx.AsyncHTTPTransport(
        proxy=proxy,
        limits=limits or httpx.Limits(),
        local_address=local_address,
    )


def _local_address_for_http(*, force_ipv4: bool) -> str | None:
    if force_ipv4:
        return _IPV4_LOCAL_ADDRESS
    preference = address_family_preference()
    if preference == "ipv4":
        return _IPV4_LOCAL_ADDRESS
    if preference == "ipv6":
        return _IPV6_LOCAL_ADDRESS
    return None
