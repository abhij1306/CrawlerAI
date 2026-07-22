from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, cast
from urllib.parse import urljoin

import httpx

from app.acquisition.browser_block_detection import (
    BlockPageClassification,
    classify_blocked_page as _classify_blocked_page,
)
from app.acquisition.browser_readiness import analyze_extractable_content, analyze_html
from app.core.config import settings
from app.core.config.block_signatures import (
    BLOCK_SIGNATURES,
    BOT_VENDOR_HEADER_MARKERS,
    MAX_VALIDATED_REDIRECTS,
)
from app.core.config.content_types import HTML_CONTENT_TYPE
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.records.network_resolution import (
    address_family_preference,
    build_async_http_client,
    default_request_headers,
)
from app.core.url_safety import (
    get_redirect_location,
    get_with_validated_redirects,
    validate_public_target,
)
from app.extraction.documents import HtmlAnalysis, HtmlDocument
from app.acquisition.platform_policy import resolve_platform_runtime_policy

logger = logging.getLogger(__name__)

_SHARED_HTTP_CLIENTS: dict[tuple[str | None, str], httpx.AsyncClient] = {}
_SHARED_HTTP_CLIENT_LOCK = asyncio.Lock()


def classify_blocked_page(
    html: str,
    status_code: int,
    *,
    analysis: HtmlAnalysis | None = None,
) -> BlockPageClassification:
    return _classify_blocked_page(
        html,
        status_code,
        analysis=analysis,
        signatures=BLOCK_SIGNATURES,
    )


@dataclass(slots=True)
class PageFetchResult:
    url: str
    final_url: str
    html: str
    status_code: int
    method: str
    content_type: str = HTML_CONTENT_TYPE
    blocked: bool = False
    platform_family: str | None = None
    headers: httpx.Headers = field(default_factory=httpx.Headers)
    network_payloads: list[dict[str, object]] = field(default_factory=list)
    browser_diagnostics: dict[str, object] = field(default_factory=dict)
    artifacts: dict[str, object] = field(default_factory=dict)
    acquisition_diagnostics: dict[str, object] = field(default_factory=dict)
    html_document: HtmlDocument | None = None


@dataclass(frozen=True, slots=True)
class NetworkPayloadReadResult:
    body: bytes | None
    outcome: str
    error: str | None = None


def is_retryable_http_status(status_code: int) -> bool:
    code = int(status_code or 0)
    configured_retry_statuses = {
        int(item)
        for item in list(crawler_runtime_settings.http_retry_status_codes or [])
    }
    return code in configured_retry_statuses or 500 <= code <= 599


def is_non_retryable_http_status(status_code: int) -> bool:
    code = int(status_code or 0)
    if code == 401:
        return True
    configured_retry_statuses = {
        int(item)
        for item in list(crawler_runtime_settings.http_retry_status_codes or [])
    }
    return 400 <= code <= 499 and code not in configured_retry_statuses


def is_browser_recoverable_http_status(
    status_code: int,
    *,
    surface: str | None,
) -> bool:
    if "detail" not in str(surface or "").strip().lower():
        return False
    configured_statuses = {
        int(item)
        for item in list(
            crawler_runtime_settings.browser_recoverable_detail_status_codes or []
        )
    }
    return int(status_code or 0) in configured_statuses


def is_blocked_html(html: str, status_code: int) -> bool:
    return classify_blocked_page(html, status_code).blocked


def classify_block_from_headers(headers: Any) -> str | None:
    if not headers:
        return None
    try:
        items = list(headers.items()) if hasattr(headers, "items") else list(headers)
    except Exception:
        logger.debug(
            "Unusable headers object for block classification; skipping header "
            "markers",
            exc_info=True,
        )
        return None
    normalized: dict[str, str] = {}
    for key, value in items:
        normalized[str(key or "").strip().lower()] = str(value or "").strip().lower()
    for header_name, must_contain, vendor in BOT_VENDOR_HEADER_MARKERS:
        value = normalized.get(header_name)
        if value is None:
            continue
        if must_contain and must_contain not in value:
            continue
        return vendor
    return None


def _http_content_is_extractable(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    signals = analyze_extractable_content(
        html,
        analysis=analysis,
    )
    return signals.detail or signals.listing


def _content_aware_http_blocked(
    headers: Any,
    html: str,
    status_code: int,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    analysis = analysis or analyze_html(html)
    blocked_page = classify_blocked_page(
        html,
        status_code,
        analysis=analysis,
    )
    if blocked_page.blocked:
        return True
    if not classify_block_from_headers(headers):
        return False
    return not _http_content_is_extractable(
        html,
        analysis=analysis,
    )


def should_escalate_to_browser(
    result: PageFetchResult,
    *,
    surface: str | None = None,
    runtime_policy: Mapping[str, Any] | None = None,
) -> bool:
    non_retryable_http_status = is_non_retryable_http_status(result.status_code)
    if result.blocked or is_retryable_http_status(result.status_code):
        return True
    if is_browser_recoverable_http_status(result.status_code, surface=surface):
        return True
    if non_retryable_http_status:
        return False
    resolved_policy = (
        runtime_policy
        if runtime_policy is not None
        else resolve_platform_runtime_policy(
            result.final_url or result.url,
            result.html,
            surface=surface,
        )
    )
    escalation_policy = resolved_policy.get("http_browser_escalation")
    if not isinstance(escalation_policy, Mapping):
        escalation_policy = {}
    analysis = analyze_html(result.html)
    content_signals = analyze_extractable_content(
        result.html,
        analysis=analysis,
        url=result.final_url or result.url,
        status_code=result.status_code,
    )
    has_detail_signals = content_signals.detail
    has_listing_signals = content_signals.listing
    if (
        bool(escalation_policy.get("js_shell_without_detail_signals", True))
        and content_signals.js_shell
        and not has_detail_signals
    ):
        return True
    if (
        bool(escalation_policy.get("listing_shell_without_listing_signals"))
        and not has_listing_signals
        and content_signals.listing_shell
    ):
        return True
    if bool(escalation_policy.get("missing_detail_signals")) and not has_detail_signals:
        return True
    return False


async def is_blocked_html_async(html: str, status_code: int) -> bool:
    return await asyncio.to_thread(is_blocked_html, html, status_code)


async def classify_blocked_page_async(
    html: str,
    status_code: int,
    *,
    analysis: HtmlAnalysis | None = None,
) -> BlockPageClassification:
    return await asyncio.to_thread(
        classify_blocked_page,
        html,
        status_code,
        analysis=analysis,
    )


async def should_escalate_to_browser_async(
    result: PageFetchResult,
    *,
    surface: str | None = None,
    runtime_policy: Mapping[str, Any] | None = None,
) -> bool:
    return await asyncio.to_thread(
        should_escalate_to_browser,
        result,
        surface=surface,
        runtime_policy=runtime_policy,
    )


async def get_shared_http_client(
    *,
    proxy: str | None = None,
) -> httpx.AsyncClient:
    family_preference = address_family_preference()
    key = (str(proxy or "").strip() or None, family_preference)
    client = _SHARED_HTTP_CLIENTS.get(key)
    if client is not None and not client.is_closed:
        return client
    async with _SHARED_HTTP_CLIENT_LOCK:
        client = _SHARED_HTTP_CLIENTS.get(key)
        if client is None or client.is_closed:
            # Redirects are followed manually per request with each Location
            # target re-validated against the SSRF guard (see
            # get_with_validated_redirects); never auto-follow here.
            client = build_async_http_client(
                follow_redirects=False,
                timeout=crawler_runtime_settings.http_timeout_seconds,
                limits=httpx.Limits(
                    max_connections=settings.http_max_connections,
                    max_keepalive_connections=settings.http_max_keepalive_connections,
                ),
                proxy=key[0],
            )
            _SHARED_HTTP_CLIENTS[key] = client
        return client


async def close_shared_http_client() -> None:
    async with _SHARED_HTTP_CLIENT_LOCK:
        clients = list(_SHARED_HTTP_CLIENTS.values())
        _SHARED_HTTP_CLIENTS.clear()
    for client in clients:
        if client is not None and not client.is_closed:
            await client.aclose()


async def http_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    get_client=get_shared_http_client,
    client_builder=None,
    blocked_html_checker=is_blocked_html_async,
) -> PageFetchResult:
    if client_builder is not None:
        get_client = client_builder
    client = await get_client(proxy=proxy)
    # Manual redirect following: every hop target (including the initial URL)
    # is re-validated against the SSRF guard immediately before the request.
    response = await get_with_validated_redirects(
        client,
        url,
        max_redirects=MAX_VALIDATED_REDIRECTS,
        timeout=timeout_seconds,
    )
    html = response.text or ""
    headers = copy_headers(response.headers)
    # CPU-heavy HTML analysis runs off the event loop (same pattern as
    # should_escalate_to_browser_async / the browser result builder).
    analysis = await asyncio.to_thread(analyze_html, html)
    blocked_result = blocked_html_checker(html, response.status_code)
    if inspect.isawaitable(blocked_result):
        blocked_result = await blocked_result
    blocked = bool(blocked_result) or await asyncio.to_thread(
        _content_aware_http_blocked,
        headers,
        html,
        response.status_code,
        analysis=analysis,
    )
    runtime_policy = await asyncio.to_thread(
        resolve_platform_runtime_policy,
        str(response.url),
        html,
    )
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="httpx",
        content_type=response.headers.get("content-type", HTML_CONTENT_TYPE),
        blocked=blocked,
        platform_family=runtime_policy.get("family"),
        headers=headers,
        html_document=analysis.document,
    )


async def curl_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    cookie_header: str | None = None,
) -> PageFetchResult:
    # Manual redirect following: each hop runs in a worker thread (sync
    # curl_cffi), and every hop target — including the initial URL — is
    # re-validated against the SSRF guard on the event loop immediately
    # before the request is issued. Set-Cookie values from intermediate hops
    # are forwarded into the next request, preserving the cookie behavior
    # curl applies when it follows a redirect chain natively.
    from curl_cffi import requests as curl_requests

    deadline = time.monotonic() + max(0.001, float(timeout_seconds))
    current_url = str(url or "").strip()
    merged_cookie_header = str(cookie_header or "").strip()
    redirect_count = 0
    while True:
        await validate_public_target(current_url)
        remaining_seconds = deadline - time.monotonic()
        if remaining_seconds <= 0:
            raise TimeoutError(
                f"curl fetch timed out following redirects for {url}"
            )
        response = await asyncio.to_thread(
            _curl_get_once,
            curl_requests,
            current_url,
            remaining_seconds,
            proxy=proxy,
            cookie_header=merged_cookie_header,
        )
        location = get_redirect_location(response)
        if location is None:
            break
        redirect_count += 1
        if redirect_count > MAX_VALIDATED_REDIRECTS:
            raise ValueError(
                f"Too many redirects while fetching {url} "
                f"(limit {MAX_VALIDATED_REDIRECTS})"
            )
        merged_cookie_header = _merge_cookie_header(
            merged_cookie_header,
            _response_set_cookie_values(getattr(response, "headers", None)),
        )
        current_url = urljoin(current_url, location)
    return await asyncio.to_thread(
        _curl_response_to_fetch_result,
        url,
        response,
    )


def _response_set_cookie_values(headers: Any) -> list[str]:
    if headers is None:
        return []
    get_list = getattr(headers, "get_list", None)
    if callable(get_list):
        return [str(value or "") for value in get_list("set-cookie")]
    multi_items = getattr(headers, "multi_items", None)
    if callable(multi_items):
        return [
            str(value or "")
            for key, value in multi_items()
            if str(key or "").lower() == "set-cookie"
        ]
    get_header = getattr(headers, "get", None)
    if callable(get_header):
        value = get_header("set-cookie")
        return [str(value)] if value else []
    return []


def _merge_cookie_header(existing: str, set_cookie_values: list[str]) -> str:
    pairs: dict[str, str] = {}
    order: list[str] = []

    def _add(pair: str) -> None:
        name, _, value = pair.partition("=")
        name = name.strip()
        if not name:
            return
        if name not in pairs:
            order.append(name)
        pairs[name] = f"{name}={value.strip()}"

    for chunk in existing.split(";"):
        if chunk.strip():
            _add(chunk.strip())
    for header in set_cookie_values:
        first_pair = header.split(";", 1)[0].strip()
        if first_pair:
            _add(first_pair)
    return "; ".join(pairs[name] for name in order)


def copy_headers(headers: Any) -> httpx.Headers:
    if isinstance(headers, httpx.Headers):
        return httpx.Headers(list(headers.multi_items()))
    if hasattr(headers, "multi_items"):
        return httpx.Headers(list(headers.multi_items()))
    if isinstance(headers, dict):
        return httpx.Headers(headers)
    return httpx.Headers(list(getattr(headers, "items", lambda: [])()))


def _curl_get_once(
    curl_requests: Any,
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    cookie_header: str | None = None,
) -> Any:
    raw_impersonate_target = str(
        ""
        if crawler_runtime_settings.curl_impersonate_target is None
        else crawler_runtime_settings.curl_impersonate_target
    ).strip()
    impersonate_target = cast(Any, raw_impersonate_target or None)
    request_headers = default_request_headers()
    normalized_cookie_header = str(cookie_header or "").strip()
    if normalized_cookie_header:
        request_headers["Cookie"] = normalized_cookie_header
    return curl_requests.get(
        url,
        impersonate=impersonate_target,
        allow_redirects=False,
        timeout=timeout_seconds,
        proxy=proxy,
        headers=request_headers,
    )


def _curl_response_to_fetch_result(url: str, response: Any) -> PageFetchResult:
    html = response.text or ""
    response_headers = copy_headers(response.headers)
    analysis = analyze_html(html)
    blocked = _content_aware_http_blocked(
        response_headers,
        html,
        response.status_code,
        analysis=analysis,
    )
    runtime_policy = resolve_platform_runtime_policy(str(response.url), html)
    return PageFetchResult(
        url=url,
        final_url=str(response.url),
        html=html,
        status_code=response.status_code,
        method="curl_cffi",
        content_type=response.headers.get("content-type", HTML_CONTENT_TYPE),
        blocked=blocked,
        platform_family=runtime_policy.get("family"),
        headers=response_headers,
        html_document=analysis.document,
    )


__all__ = [
    "BlockPageClassification",
    "BLOCK_SIGNATURES",
    "NetworkPayloadReadResult",
    "classify_block_from_headers",
    "classify_blocked_page",
    "classify_blocked_page_async",
    "PageFetchResult",
    "close_shared_http_client",
    "copy_headers",
    "curl_fetch",
    "get_shared_http_client",
    "http_fetch",
    "is_blocked_html",
    "is_blocked_html_async",
    "is_non_retryable_http_status",
    "is_browser_recoverable_http_status",
    "is_retryable_http_status",
    "should_escalate_to_browser",
    "should_escalate_to_browser_async",
]
