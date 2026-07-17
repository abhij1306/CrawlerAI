from __future__ import annotations

import asyncio
from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import Any
from urllib.parse import urlparse

from app.acquisition.dom_runtime import get_page_html
from app.acquisition.listing_cards import card_diagnostics_from_html
from app.core.config.extraction_rules import (
    ACTION_BUY_NOW,
    BROWSER_DETAIL_READINESS_HINTS,
    CONTENT_DETAIL_MIN_BODY_TEXT_LENGTH,
    CONTENT_SURFACE_FORUM_BODY_SELECTORS,
    CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS,
    DETAIL_SHELL_FRAMEWORK_TOKENS,
    DETAIL_SHELL_PRODUCT_DATA_TOKENS,
    DETAIL_SHELL_STATE_TOKENS,
    JS_REQUIRED_PLACEHOLDER_PHRASES,
    LISTING_CLIENT_RENDERED_SHELL_HINTS,
    LISTING_DETAIL_URL_MARKERS,
    LISTING_SHELL_FRAMEWORK_TOKENS,
    LOW_CONTENT_SHELL_PHRASES,
    LOW_CONTENT_TERMINAL_SHELL_PHRASES,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.shared.field_coerce import clean_text, coerce_int as _coerce_int
from app.core.shared.text_coerce import slug_tokens
from app.extraction.documents import HtmlAnalysis, HtmlDocument
from app.extraction.surfaces import surface_spec


_STRUCTURED_SHELL_TOKENS = (
    "application/ld+json",
    "__next_data__",
    "__nuxt__",
    "shopifyanalytics.meta",
)
_DETAIL_READINESS_HINTS: dict[str, tuple[str, ...]] = {
    str(key): tuple(map(str, value or ()))
    for key, value in (BROWSER_DETAIL_READINESS_HINTS or {}).items()
}


@dataclass(frozen=True, slots=True)
class ExtractableContentSignals:
    detail: bool
    listing: bool
    meaningful_detail: bool
    js_shell: bool
    listing_shell: bool


def analyze_html(html: str) -> HtmlAnalysis:
    return HtmlAnalysis.from_html(html)


def analyze_extractable_content(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
    url: str = "",
    status_code: int = 0,
) -> ExtractableContentSignals:
    parsed = analysis or analyze_html(html)
    placeholder = _is_js_required_placeholder(parsed)
    structured_detail, structured_listing, typed_count, state_content = (
        _structured_content_signals(parsed.document)
    )
    meaningful_detail = _has_meaningful_detail_dom(parsed)
    dom_detail = _has_detail_dom_signals(parsed)
    app_only = any(
        phrase in parsed.normalized_text.lower()
        for phrase in ("load in the app", "loads in the app")
    )
    token_detail = any(
        token in parsed.lowered_html for token in DETAIL_SHELL_STATE_TOKENS
    ) or (
        any(token in parsed.lowered_html for token in DETAIL_SHELL_FRAMEWORK_TOKENS)
        and any(
            token in parsed.lowered_html for token in DETAIL_SHELL_PRODUCT_DATA_TOKENS
        )
    )
    detail = bool(
        parsed.html
        and not placeholder
        and (
            structured_detail
            or state_content
            or dom_detail
            or meaningful_detail
            or (token_detail and not app_only)
        )
    )
    listing = bool(
        parsed.html
        and not placeholder
        and (
            structured_listing
            or typed_count >= max(2, int(crawler_runtime_settings.listing_min_items))
            or _detail_like_anchor_count(parsed.document) >= 3
        )
    )
    root_present = any(
        re.search(r"root|app|__next", node.attribute("id") or "", re.I)
        for node in parsed.document.safe_css("[id]")
    )
    script_count = len(parsed.document.safe_css("script"))
    js_shell = placeholder or bool(
        len(parsed.visible_text) <= 120 and root_present and script_count >= 3
    )
    listing_shell = (
        placeholder
        or "#/" in str(url or "").strip().lower()
        or int(status_code or 0) == 202
    )
    if not listing_shell and len(parsed.visible_text) > 400:
        listing_shell = any(
            token in parsed.lowered_html
            for token in LISTING_CLIENT_RENDERED_SHELL_HINTS
        )
    elif not listing_shell and (root_present or script_count >= 3):
        listing_shell = any(
            token in parsed.lowered_html for token in LISTING_SHELL_FRAMEWORK_TOKENS
        )
    return ExtractableContentSignals(
        detail=detail,
        listing=listing,
        meaningful_detail=meaningful_detail,
        js_shell=js_shell,
        listing_shell=listing_shell,
    )


def _structured_content_signals(
    document: HtmlDocument,
) -> tuple[bool, bool, int, bool]:
    detail = listing = state_content = False
    typed_count = 0
    for script in document.safe_css('script[type*="ld+json"]'):
        payload = script.json()
        rows = payload if isinstance(payload, list) else [payload]
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw_type = row.get("@type")
            normalized = (
                " ".join(map(str, raw_type))
                if isinstance(raw_type, list)
                else str(raw_type or "")
            ).lower()
            detail |= any(
                token in normalized
                for token in ("product", "productgroup", "jobposting")
            )
            listing |= any(token in normalized for token in ("itemlist", "listitem"))
            typed_count += int(
                any(token in normalized for token in ("product", "jobposting"))
            )
    for script in document.safe_css(
        'script[type="application/json"], script#__NEXT_DATA__',
    ):
        state_content |= _state_payload_has_content(script.json())
    return detail, listing, typed_count, state_content


def _state_payload_has_content(payload: Any) -> bool:
    if isinstance(payload, dict):
        meaningful = any(
            value not in (None, "", [], {})
            and str(key or "").strip().lower() not in {"config", "env", "locale"}
            for key, value in payload.items()
        )
        return meaningful or any(
            _state_payload_has_content(value) for value in payload.values()
        )
    if isinstance(payload, list):
        return any(_state_payload_has_content(item) for item in payload[:10])
    return payload not in (None, "")


def _has_detail_dom_signals(analysis: HtmlAnalysis) -> bool:
    if not analysis.h1_present:
        return False
    lowered_text = analysis.normalized_text.lower()
    hint_count = detail_readiness_hint_count("ecommerce_detail", lowered_text)
    hint_count += int(ACTION_BUY_NOW.strip().lower() in lowered_text)
    product_anchor = any(
        re.search(r"og:type", node.attribute("property") or "", re.I)
        and re.search(r"\bproduct\b", node.attribute("content") or "", re.I)
        for node in analysis.document.safe_css("[property][content]")
    )
    price_pattern = re.compile(
        r"(?:[$€£₹]\s*)?\d{1,3}(?:,\d{3})*(?:[.,]\d{1,2})?"
        r"|(?:[$€£₹]\s*)?\d+(?:[.,]\d{1,2})?",
        re.I,
    )
    price_anchor = bool(
        any(
            re.search(r"(?:product:)?price", node.attribute("property") or "", re.I)
            and price_pattern.search(node.attribute("content") or "")
            for node in analysis.document.safe_css("[property][content]")
        )
        or any(
            re.search(r"price", node.attribute("itemprop") or "", re.I)
            for node in analysis.document.safe_css("[itemprop]")
        )
        or re.search(
            r"(?:[$€£₹]\s*)\d+(?:[.,]\d{2})?",
            analysis.normalized_text,
        )
    )
    app_only = any(
        phrase in lowered_text for phrase in ("load in the app", "loads in the app")
    )
    if app_only and not (product_anchor or price_anchor):
        return False
    if hint_count >= int(crawler_runtime_settings.detail_field_signal_min_count):
        return bool(
            analysis.document.css_first("main h1, article h1, [role='main'] h1")
            or product_anchor
            or price_anchor
        )
    return hint_count > 0 and product_anchor


def _has_meaningful_detail_dom(analysis: HtmlAnalysis) -> bool:
    heading = analysis.document.css_first("main h1, article h1, [role='main'] h1, h1")
    heading_text = clean_text(heading.text()) if heading else ""
    if not heading_text:
        return False
    selectors = (
        *CONTENT_SURFACE_FORUM_BODY_SELECTORS,
        *CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS,
    )
    for selector in selectors:
        try:
            nodes = analysis.document.css(selector)
        except Exception:
            nodes = ()
        for node in nodes:
            body = clean_text(
                re.sub(
                    re.escape(heading_text),
                    " ",
                    clean_text(node.text()),
                    flags=re.I,
                )
            )
            if not body or any(
                phrase in body.lower()
                for phrase in ("load in the app", "loads in the app")
            ):
                continue
            descendants = node.css_first("p, div, li, article, section, span")
            if (
                descendants is not None
                or len(body) >= CONTENT_DETAIL_MIN_BODY_TEXT_LENGTH
            ):
                return True
    return False


def _is_js_required_placeholder(analysis: HtmlAnalysis) -> bool:
    combined = clean_text(f"{analysis.title_text} {analysis.visible_text}").lower()
    return bool(
        combined
        and any(phrase in combined for phrase in JS_REQUIRED_PLACEHOLDER_PHRASES)
        and (
            analysis.document.css_first("noscript") is not None
            or len(analysis.visible_text) <= 400
        )
    )


def _detail_like_anchor_count(document: HtmlDocument) -> int:
    return sum(
        any(
            marker in (anchor.attribute("href") or "").lower()
            for marker in LISTING_DETAIL_URL_MARKERS
        )
        for anchor in document.safe_css("a[href]")
    )


async def wait_for_listing_readiness(
    page: Any,
    page_url: str,
    *,
    override: dict[str, object] | None = None,
) -> dict[str, object]:
    from patchright.async_api import TimeoutError as PlaywrightTimeoutError
    from app.acquisition.platform_policy import resolve_listing_readiness_override

    override = override or resolve_listing_readiness_override(page_url)
    if not override:
        return {}
    raw_selectors = override.get("selectors")
    if not isinstance(raw_selectors, Iterable) or isinstance(
        raw_selectors, (str, bytes)
    ):
        return {}
    selectors = [
        str(selector or "").strip()
        for selector in raw_selectors
        if str(selector or "").strip()
    ]
    if not selectors:
        return {}
    max_wait_value = override.get("max_wait_ms")
    safe_fallback = _coerce_int(
        crawler_runtime_settings.listing_readiness_max_wait_ms,
        default=0,
    )
    max_wait_ms = _coerce_int(
        max_wait_value,
        default=safe_fallback,
    )
    if max_wait_ms <= 0:
        return {}
    combined_selector = ", ".join(selectors)
    try:
        await page.wait_for_selector(
            combined_selector,
            state="attached",
            timeout=max_wait_ms,
        )
    except asyncio.CancelledError:
        raise
    except PlaywrightTimeoutError as exc:
        return {
            "platform": str(override.get("platform") or ""),
            "max_wait_ms": max_wait_ms,
            "status": "timed_out",
            "terminal_state": "timed_out",
            "is_ready": False,
            "attempted_selectors": selectors,
            "failures": [f"{combined_selector}:{type(exc).__name__}"],
        }
    matched_selector = None
    for selector in selectors:
        if await page.locator(selector).count():
            matched_selector = selector
            break
    return {
        "platform": str(override.get("platform") or ""),
        "combined_selector": combined_selector,
        "max_wait_ms": max_wait_ms,
        "matched_selector": matched_selector or combined_selector,
        "status": "matched",
        "terminal_state": "observing",
        "is_ready": False,
    }


def _card_count(diagnostics: dict[str, object]) -> int:
    raw = diagnostics.get("card_count")
    return raw if isinstance(raw, int) else 0


async def _rendered_fragment_card_diagnostics(
    page: Any, *, url: str, surface: str
) -> dict[str, object]:
    """Card diagnostics over the rendered fragments extraction also reads.

    Uses the same capture as ``LISTING_HTML_ARTIFACT_IDS``'s rendered-fragment
    artifact so a shadow-DOM/JS board that only materializes cards in the
    fragment capture is counted identically by readiness and extraction.
    """

    from app.acquisition.browser_recovery import capture_rendered_listing_fragments

    try:
        fragments = await capture_rendered_listing_fragments(
            page,
            surface=surface,
            limit=int(crawler_runtime_settings.rendered_listing_card_capture_limit),
        )
    except Exception:
        return {}
    if not fragments:
        return {}
    return card_diagnostics_from_html(
        "<main>" + "\n".join(fragments) + "</main>",
        page_url=str(getattr(page, "url", "") or url),
        surface=surface,
    )


async def _listing_discovery_signals(
    page: Any,
    *,
    url: str,
    surface: str,
    html_text: str,
    listing_override: dict[str, object] | None,
) -> tuple[dict[str, object], int, int]:
    """Card diagnostics, card count, and override-selector matches for listings."""

    listing_card_diagnostics = card_diagnostics_from_html(
        html_text,
        page_url=str(getattr(page, "url", "") or url),
        surface=surface,
    )
    listing_card_count = _card_count(listing_card_diagnostics)
    if listing_card_count == 0:
        # Coordinate with extraction's artifact set: a JS/shadow-DOM board
        # can render its cards only in the fragments extraction later reads
        # through LISTING_HTML_ARTIFACT_IDS. Count the same rendered
        # fragments here so readiness and extraction agree.
        fragment_diagnostics = await _rendered_fragment_card_diagnostics(
            page, url=url, surface=surface
        )
        fragment_count = _card_count(fragment_diagnostics)
        if fragment_count > 0:
            listing_card_diagnostics = fragment_diagnostics
            listing_card_count = fragment_count
    raw_override_selectors = (
        listing_override.get("selectors")
        if isinstance(listing_override, dict)
        else None
    )
    selectors = (
        [
            str(selector or "").strip()
            for selector in raw_override_selectors
            if str(selector or "").strip()
        ]
        if isinstance(raw_override_selectors, Iterable)
        and not isinstance(raw_override_selectors, (str, bytes))
        else []
    )
    matched_listing_selectors = await count_matching_selectors(
        page, selectors=selectors
    )
    return listing_card_diagnostics, listing_card_count, matched_listing_selectors


def _listing_readiness_verdict(
    analysis: HtmlAnalysis, spec: Any, listing_card_count: int
) -> tuple[bool, bool, bool, str]:
    """(is_ready, ready_empty, shell_detected, terminal_state) for listings."""

    normalized_visible_text = analysis.normalized_text.casefold()
    no_results_detected = any(
        re.search(pattern, normalized_visible_text, re.I)
        for pattern in spec.readiness_no_results_patterns
    )
    shell_detected = any(
        re.search(pattern, normalized_visible_text, re.I)
        for pattern in spec.readiness_shell_patterns
    )
    repeated_cards = listing_card_count >= max(
        1, int(spec.readiness_min_repeated_records)
    )
    # Shell evidence overrides a broad no-results match: a hydrating SPA with
    # stale "no results" copy must keep observing, not fast-finalize as empty.
    ready_empty = bool(
        not repeated_cards and no_results_detected and not shell_detected
    )
    is_ready = bool(repeated_cards or ready_empty)
    if repeated_cards:
        terminal_state = "ready"
    elif ready_empty:
        terminal_state = "ready_empty"
    elif shell_detected:
        terminal_state = "shell_rejected"
    else:
        terminal_state = "observing"
    return is_ready, ready_empty, shell_detected, terminal_state


def _detail_readiness_verdict(
    analysis: HtmlAnalysis,
    *,
    visible_text_length: int,
    structured_data_present: bool,
    detail_like: bool,
    detail_hints: int,
    detail_title_matches_url: bool,
) -> bool:
    enough_text = visible_text_length >= int(
        crawler_runtime_settings.browser_readiness_visible_text_min
    )
    has_identity = bool(
        analysis.h1_present
        or detail_hints >= int(crawler_runtime_settings.detail_field_signal_min_count)
        or detail_title_matches_url
    )
    return bool(
        (structured_data_present and enough_text)
        or (detail_like and has_identity and enough_text)
    )


async def probe_browser_readiness(
    page: Any,
    *,
    url: str,
    surface: str,
    listing_override: dict[str, object] | None = None,
    html: str | None = None,
    analysis: HtmlAnalysis | None = None,
) -> dict[str, object]:
    html_text = html if html is not None else await get_page_html(page)
    if analysis is None or not analysis.matches_html(html_text or ""):
        analysis = await asyncio.to_thread(analyze_html, html_text or "")
    if analysis is None:
        raise RuntimeError("browser readiness analysis was not produced")
    visible_text_length = len(analysis.normalized_text)
    spec = surface_spec(surface)
    is_detail = spec.cardinality == "one"
    is_listing = spec.cardinality == "many"
    has_shell_token = any(
        token in analysis.lowered_html for token in _STRUCTURED_SHELL_TOKENS
    )
    has_detail_token = bool(
        re.search(r'"@type"\s*:\s*"(product|jobposting)"', analysis.lowered_html)
    )
    structured_data_present = has_detail_token or (not is_detail and has_shell_token)
    detail_hints = detail_readiness_hint_count(surface, analysis.visible_text.lower())
    detail_title_matches_url = _detail_title_matches_url(
        url,
        analysis.title_text,
        min_matches=int(
            crawler_runtime_settings.browser_detail_title_url_token_min_count
        ),
    )
    detail_like = (
        analysis.h1_present
        or structured_data_present
        or detail_hints > 0
        or detail_title_matches_url
    )
    listing_card_count = 0
    matched_listing_selectors = 0
    listing_card_diagnostics: dict[str, object] = {}
    readiness_terminal_state = "observing"
    ready_empty = False
    shell_detected = False
    if is_listing:
        (
            listing_card_diagnostics,
            listing_card_count,
            matched_listing_selectors,
        ) = await _listing_discovery_signals(
            page,
            url=url,
            surface=surface,
            html_text=html_text or "",
            listing_override=listing_override,
        )
        (
            is_ready,
            ready_empty,
            shell_detected,
            readiness_terminal_state,
        ) = _listing_readiness_verdict(analysis, spec, listing_card_count)
    elif is_detail:
        is_ready = _detail_readiness_verdict(
            analysis,
            visible_text_length=visible_text_length,
            structured_data_present=structured_data_present,
            detail_like=detail_like,
            detail_hints=detail_hints,
            detail_title_matches_url=detail_title_matches_url,
        )
    else:
        is_ready = visible_text_length >= int(
            crawler_runtime_settings.browser_readiness_visible_text_min
        )
    return {
        "url": url,
        "surface": surface,
        "is_ready": is_ready,
        "detail_like": detail_like,
        "structured_data_present": structured_data_present,
        "visible_text_length": visible_text_length,
        "detail_hint_count": detail_hints,
        "detail_title_matches_url": detail_title_matches_url,
        "listing_card_count": listing_card_count,
        "matched_listing_selectors": matched_listing_selectors,
        "listing_card_diagnostics": listing_card_diagnostics,
        "readiness_terminal_state": readiness_terminal_state,
        "ready_empty": ready_empty,
        "shell_detected": shell_detected,
        "h1_present": analysis.h1_present,
    }


def _detail_title_matches_url(
    url: str,
    title: str,
    *,
    min_matches: int,
) -> bool:
    if min_matches <= 0:
        return False
    parsed = urlparse(str(url or ""))
    title_tokens = {
        token for token in slug_tokens(title) if len(token) >= 3 and not token.isdigit()
    }
    if not title_tokens:
        return False
    for segment in reversed([part for part in parsed.path.split("/") if part]):
        segment_tokens = [
            token
            for token in slug_tokens(segment)
            if len(token) >= 3 and not token.isdigit()
        ]
        if not segment_tokens:
            continue
        if len(set(segment_tokens) & title_tokens) >= min_matches:
            return True
    return False


async def count_matching_selectors(page: Any, *, selectors: list[str]) -> int:
    from patchright.async_api import Error as PlaywrightError
    from patchright.async_api import TimeoutError as PlaywrightTimeoutError

    matches = 0
    for selector in selectors:
        normalized = str(selector or "").strip()
        if not normalized:
            continue
        try:
            matches += int(await page.locator(normalized).count())
        except PlaywrightTimeoutError:
            continue
        except PlaywrightError:
            raise
        except (TypeError, ValueError):
            continue
    return matches


def classify_browser_outcome(
    *,
    html: str,
    html_bytes: int,
    blocked: bool,
    block_classification: Any = None,
    traversal_result: Any = None,
    analysis: HtmlAnalysis | None = None,
    readiness_probes: list[dict[str, object]] | None = None,
) -> str:
    if blocked or bool(getattr(block_classification, "blocked", False)):
        return "challenge_page"
    if (
        bool(getattr(block_classification, "active_provider_hits", ()))
        and readiness_probes
        and not any(bool(probe.get("is_ready")) for probe in readiness_probes)
    ):
        return "challenge_page"
    low_content_shell = looks_like_low_content_shell(
        html,
        html_bytes=html_bytes,
        analysis=analysis,
    )
    if traversal_result is not None and bool(
        getattr(traversal_result, "activated", False)
    ):
        progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
        card_count = int(getattr(traversal_result, "card_count", 0) or 0)
        stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
        if (
            progress_events == 0
            and card_count < int(crawler_runtime_settings.listing_min_items)
            and stop_reason.endswith(("_not_found", "_no_progress"))
            and low_content_shell
        ):
            return "traversal_failed"
    if low_content_shell:
        return "low_content_shell"
    return "usable_content"


def classify_low_content_reason(
    html: str,
    *,
    html_bytes: int,
    analysis: HtmlAnalysis | None = None,
) -> str | None:
    analysis = (
        analysis
        if analysis is not None and analysis.matches_html(html)
        else analyze_html(html)
    )
    if not analysis.html.strip():
        return "empty_html"
    title_text = analysis.title_text.lower()
    if any(
        phrase in title_text
        for phrase in (*LOW_CONTENT_SHELL_PHRASES, *LOW_CONTENT_TERMINAL_SHELL_PHRASES)
    ):
        return "empty_terminal_page"
    lowered_text = analysis.normalized_text.lower()
    has_product_evidence = analyze_extractable_content(
        html,
        analysis=analysis,
    ).detail
    if not has_product_evidence and any(
        phrase in lowered_text for phrase in LOW_CONTENT_TERMINAL_SHELL_PHRASES
    ):
        return "empty_terminal_page"
    if len(analysis.visible_text.strip()) >= 120:
        return None
    if any(
        token in analysis.lowered_html
        for token in (
            "product",
            "jobposting",
            "__next_data__",
            "__nuxt__",
            "application/ld+json",
        )
    ):
        return None
    if any(phrase in lowered_text for phrase in LOW_CONTENT_SHELL_PHRASES):
        return "empty_terminal_page"
    if html_bytes <= 8_000:
        return "low_visible_text"
    return None


def detail_readiness_hint_count(surface: str, visible_text: str) -> int:
    lowered_surface = str(surface or "").strip().lower()
    if "ecommerce" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS.get("ecommerce", ())
    elif "job" in lowered_surface:
        hints = _DETAIL_READINESS_HINTS.get("job", ())
    else:
        hints = ()
    return sum(1 for hint in hints if hint in visible_text)


def looks_like_low_content_shell(
    html: str,
    *,
    html_bytes: int,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    return (
        classify_low_content_reason(
            html,
            html_bytes=html_bytes,
            analysis=analysis,
        )
        is not None
    )
