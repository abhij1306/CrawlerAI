from __future__ import annotations

import asyncio
import inspect
from collections.abc import Mapping
from dataclasses import dataclass, field
import logging
import re
from typing import Any

import httpx

from app.acquisition.browser_readiness import (
    analyze_extractable_content,
    analyze_html,
)
from app.core.config import settings
from app.core.config.block_signatures import BLOCK_SIGNATURES
from app.core.config.content_types import HTML_CONTENT_TYPE
from app.core.config.extraction_rules._detail import DETAIL_SHELL_TITLE_KEYS
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.db_utils import mapping_or_empty
from app.core.shared.text_coerce import slug_tokens
from app.core.records.network_resolution import (
    address_family_preference,
    build_async_http_client,
    default_request_headers,
)
from app.extraction.documents import HtmlAnalysis, HtmlDocument
from app.acquisition.platform_policy import resolve_platform_runtime_policy

logger = logging.getLogger(__name__)

_SHARED_HTTP_CLIENTS: dict[tuple[str | None, str], httpx.AsyncClient] = {}
_SHARED_HTTP_CLIENT_LOCK = asyncio.Lock()


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


@dataclass(frozen=True, slots=True)
class BlockPageClassification:
    blocked: bool
    outcome: str
    evidence: list[str] = field(default_factory=list)
    provider_hits: list[str] = field(default_factory=list)
    active_provider_hits: list[str] = field(default_factory=list)
    strong_hits: list[str] = field(default_factory=list)
    weak_hits: list[str] = field(default_factory=list)
    title_matches: list[str] = field(default_factory=list)
    challenge_element_hits: list[str] = field(default_factory=list)


_BOT_VENDOR_HEADER_MARKERS: tuple[tuple[str, str, str], ...] = (
    ("x-datadome", "", "datadome"),
    ("x-datadome-cid", "", "datadome"),
    ("server", "datadome", "datadome"),
    ("cf-mitigated", "challenge", "cloudflare"),  # only when value = "challenge"
    ("x-sucuri-id", "", "sucuri"),
    ("x-sucuri-cache", "", "sucuri"),
    ("x-akamai-transformed", "", "akamai"),
    ("akamai-grn", "", "akamai"),
    ("x-px-block", "", "perimeterx"),
)


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
        return None
    normalized: dict[str, str] = {}
    for key, value in items:
        normalized[str(key or "").strip().lower()] = str(value or "").strip().lower()
    for header_name, must_contain, vendor in _BOT_VENDOR_HEADER_MARKERS:
        value = normalized.get(header_name)
        if value is None:
            continue
        if must_contain and must_contain not in value:
            continue
        return vendor
    return None


def classify_blocked_page(
    html: str,
    status_code: int,
    *,
    analysis: HtmlAnalysis | None = None,
) -> BlockPageClassification:
    code = int(status_code or 0)
    forced_blocked = False
    forced_outcome = ""
    base_evidence: list[str] = []
    if code == 401:
        return BlockPageClassification(
            blocked=False,
            outcome="auth_wall",
            evidence=[f"http_status:{code}"],
        )
    if code == 429:
        forced_blocked = True
        forced_outcome = "rate_limited"
        base_evidence.append(f"http_status:{code}")
    if code == 403:
        forced_blocked = True
        forced_outcome = "challenge_page"
        base_evidence.append(f"http_status:{code}")
    lowered = str(html or "").lower()
    if not lowered.strip():
        if forced_blocked:
            return BlockPageClassification(
                blocked=True,
                outcome=forced_outcome,
                evidence=base_evidence,
            )
        return BlockPageClassification(blocked=False, outcome="empty")

    analysis = analysis or analyze_html(html)
    document = analysis.document
    visible_text = analysis.visible_text.lower()
    title_text = analysis.title_text.lower()
    normalized_title = " ".join(slug_tokens(title_text))
    shell_title = normalized_title if normalized_title in DETAIL_SHELL_TITLE_KEYS else ""
    content_signals = analyze_extractable_content(
        html,
        analysis=analysis,
    )
    has_extractable_content = content_signals.detail or content_signals.listing

    title_patterns = _string_sequence(BLOCK_SIGNATURES.get("title_regexes"))
    title_matches: list[str] = []
    for pattern in title_patterns:
        raw_pattern = str(pattern or "").strip()
        if not raw_pattern:
            continue
        try:
            if re.search(raw_pattern, title_text, re.IGNORECASE):
                title_matches.append(raw_pattern)
        except re.error as exc:
            logger.warning(
                "Skipping invalid block signature title regex %r: %s",
                raw_pattern,
                exc,
            )
    if shell_title and shell_title not in title_matches:
        title_matches.append(shell_title)

    strong_markers = [
        str(marker or "").strip().lower()
        for marker in mapping_or_empty(
            BLOCK_SIGNATURES.get("browser_challenge_strong_markers")
        ).keys()
        if str(marker or "").strip()
    ]
    weak_markers = [
        str(marker or "").strip().lower()
        for marker in mapping_or_empty(
            BLOCK_SIGNATURES.get("browser_challenge_weak_markers")
        ).keys()
        if str(marker or "").strip()
    ]
    content_tolerant_strong_markers = {
        str(marker or "").strip().lower()
        for marker in _string_sequence(
            BLOCK_SIGNATURES.get("content_tolerant_strong_markers")
        )
        if str(marker or "").strip()
    }
    provider_markers = [
        str(marker or "").strip().lower()
        for marker in _string_sequence(BLOCK_SIGNATURES.get("provider_markers"))
        if str(marker or "").strip()
    ]

    strong_hits = {
        marker
        for marker in strong_markers
        if marker in visible_text or marker in title_text
    }
    weak_hits = {
        marker
        for marker in weak_markers
        if marker in visible_text or marker in title_text
    }
    provider_hits = {marker for marker in provider_markers if marker in lowered}
    active_provider_hits = {
        str(item.get("marker") or "").strip().lower()
        for item in _mapping_sequence(BLOCK_SIGNATURES.get("active_provider_markers"))
        if str(item.get("marker") or "").strip()
        and str(item.get("marker") or "").strip().lower() in lowered
    }
    challenge_element_hits = set(_challenge_element_hits(document, lowered))
    hard_strong_hits = strong_hits - content_tolerant_strong_markers
    evidence = [
        *base_evidence,
        *sorted(f"title:{pattern}" for pattern in title_matches),
        *sorted(f"strong:{marker}" for marker in strong_hits),
        *sorted(f"weak:{marker}" for marker in weak_hits),
        *sorted(f"provider:{marker}" for marker in provider_hits),
        *sorted(f"active_provider:{marker}" for marker in active_provider_hits),
        *sorted(f"challenge_element:{marker}" for marker in challenge_element_hits),
    ]

    blocked = forced_blocked or bool(
        len(hard_strong_hits) >= 2
        or (
            hard_strong_hits
            and (
                provider_hits
                or active_provider_hits
                or challenge_element_hits
                or title_matches
            )
        )
        or (shell_title and not has_extractable_content)
        or "access denied" in strong_hits
        or (
            "just a moment" in strong_hits
            and (
                "cloudflare" in provider_hits
                or "cf-challenge" in provider_hits
                or "cf-browser-verification" in active_provider_hits
            )
        )
        or (challenge_element_hits and (provider_hits or active_provider_hits))
        or (title_matches and challenge_element_hits)
        or (hard_strong_hits and weak_hits and provider_hits)
        or (
            "captcha" in strong_hits
            and provider_hits
            and (not has_extractable_content or bool(title_matches))
        )
    )
    if (
        blocked
        and has_extractable_content
        and not title_matches
        and (not hard_strong_hits or hard_strong_hits <= {"captcha"})
    ):
        blocked = False
    return BlockPageClassification(
        blocked=blocked,
        outcome=(
            forced_outcome
            if blocked and forced_blocked
            else "challenge_page"
            if blocked
            else "ok"
        ),
        evidence=evidence,
        provider_hits=sorted(provider_hits),
        active_provider_hits=sorted(active_provider_hits),
        strong_hits=sorted(strong_hits),
        weak_hits=sorted(weak_hits),
        title_matches=title_matches,
        challenge_element_hits=sorted(challenge_element_hits),
    )


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
) -> bool:
    analysis = analyze_html(html)
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
            client = build_async_http_client(
                follow_redirects=True,
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
    response = await client.get(url, timeout=timeout_seconds)
    html = response.text or ""
    headers = copy_headers(response.headers)
    blocked_result = blocked_html_checker(html, response.status_code)
    if inspect.isawaitable(blocked_result):
        blocked_result = await blocked_result
    blocked = bool(blocked_result) or _content_aware_http_blocked(
        headers,
        html,
        response.status_code,
    )
    runtime_policy = resolve_platform_runtime_policy(str(response.url), html)
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
    )


async def curl_fetch(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    cookie_header: str | None = None,
) -> PageFetchResult:
    return await asyncio.to_thread(
        _curl_fetch_sync,
        url,
        timeout_seconds,
        proxy=proxy,
        cookie_header=cookie_header,
    )


def copy_headers(headers: Any) -> httpx.Headers:
    if isinstance(headers, httpx.Headers):
        return httpx.Headers(list(headers.multi_items()))
    if hasattr(headers, "multi_items"):
        return httpx.Headers(list(headers.multi_items()))
    if isinstance(headers, dict):
        return httpx.Headers(headers)
    return httpx.Headers(list(getattr(headers, "items", lambda: [])()))


def _curl_fetch_sync(
    url: str,
    timeout_seconds: float,
    *,
    proxy: str | None = None,
    cookie_header: str | None = None,
) -> PageFetchResult:
    from curl_cffi import requests as curl_requests

    raw_impersonate_target = str(
        ""
        if crawler_runtime_settings.curl_impersonate_target is None
        else crawler_runtime_settings.curl_impersonate_target
    ).strip()
    impersonate_target = raw_impersonate_target or None
    request_headers = default_request_headers()
    normalized_cookie_header = str(cookie_header or "").strip()
    if normalized_cookie_header:
        request_headers["Cookie"] = normalized_cookie_header
    response = curl_requests.get(
        url,
        impersonate=impersonate_target,
        allow_redirects=True,
        timeout=timeout_seconds,
        proxy=proxy,
        headers=request_headers,
    )
    html = response.text or ""
    response_headers = copy_headers(response.headers)
    blocked = _content_aware_http_blocked(
        response_headers,
        html,
        response.status_code,
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
    )

def _mapping_sequence(value: object) -> list[dict[object, object]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _string_sequence(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value]


def _challenge_element_hits(
    document: HtmlDocument,
    lowered_html: str,
) -> list[str]:
    challenge_elements = mapping_or_empty(BLOCK_SIGNATURES.get("challenge_elements"))
    iframe_src_markers = _marker_map_from_config(
        challenge_elements, "iframe_src_markers"
    )
    iframe_title_markers = _marker_map_from_config(
        challenge_elements,
        "iframe_title_markers",
    )
    script_src_markers = _marker_map_from_config(
        challenge_elements, "script_src_markers"
    )
    html_markers = _marker_map_from_config(challenge_elements, "html_markers")
    hits: list[str] = []
    for iframe in document.css("iframe"):
        src = str(iframe.attribute("src") or "").strip().lower()
        title = str(iframe.attribute("title") or "").strip().lower()
        for marker, hit in iframe_src_markers.items():
            if marker in src:
                hits.append(hit)
        for marker, hit in iframe_title_markers.items():
            if marker in title:
                hits.append(hit)
    for script in document.css("script"):
        src = str(script.attribute("src") or "").strip().lower()
        for marker, hit in script_src_markers.items():
            if marker in src:
                hits.append(hit)
    for marker, hit in html_markers.items():
        if marker in lowered_html:
            hits.append(hit)
    return hits


def _marker_map_from_config(
    source: Mapping[str, object],
    key: str,
) -> dict[str, str]:
    return {
        str(marker or "").strip().lower(): str(hit or "").strip()
        for marker, hit in mapping_or_empty(source.get(key)).items()
        if str(marker or "").strip() and str(hit or "").strip()
    }


__all__ = [
    "BlockPageClassification",
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
