from __future__ import annotations

import asyncio
from collections.abc import Iterable
import logging
import re
from typing import Any
from urllib.parse import urlparse

from app.acquisition.dom_runtime import get_page_html
from app.acquisition.browser_content_signals import (
    STRUCTURED_SHELL_TOKENS,
    analyze_extractable_content,
    analyze_html,
    detail_readiness_hint_count,
)
from app.acquisition.listing_cards import card_diagnostics_from_html
from app.core.config.extraction_rules import (
    LOW_CONTENT_SHELL_PHRASES,
    LOW_CONTENT_TERMINAL_SHELL_PHRASES,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.shared.field_coerce import coerce_int as _coerce_int
from app.core.shared.text_coerce import slug_tokens
from app.extraction.documents import HtmlAnalysis
from app.extraction.surfaces import surface_spec


logger = logging.getLogger(__name__)


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
    selectors = _normalized_selectors(raw_selectors)
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


def _normalized_selectors(selectors: Iterable[object]) -> list[str]:
    return [
        normalized
        for selector in selectors
        if (normalized := str(selector or "").strip())
    ]


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
        logger.debug(
            "Rendered-fragment card capture failed for %s; readiness proceeds "
            "without fragment diagnostics",
            url,
            exc_info=True,
        )
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
        token in analysis.lowered_html for token in STRUCTURED_SHELL_TOKENS
    )
    has_detail_token = bool(
        re.search(r'"@type"\s*:\s*"(product|jobposting)"', analysis.lowered_html)
    )
    structured_data_present = any(
        (has_detail_token, all((not is_detail, has_shell_token)))
    )
    detail_hints = detail_readiness_hint_count(surface, analysis.visible_text.lower())
    detail_title_matches_url = _detail_title_matches_url(
        url,
        analysis.title_text,
        min_matches=int(
            crawler_runtime_settings.browser_detail_title_url_token_min_count
        ),
    )
    detail_like = any(
        (
            analysis.h1_present,
            structured_data_present,
            detail_hints > 0,
            detail_title_matches_url,
        )
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
        if is_ready:
            readiness_terminal_state = "ready"
    else:
        is_ready = visible_text_length >= int(
            crawler_runtime_settings.browser_readiness_visible_text_min
        )
        if is_ready:
            readiness_terminal_state = "ready"
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
    if any((blocked, bool(getattr(block_classification, "blocked", False)))):
        return "challenge_page"
    if all(
        (
            bool(getattr(block_classification, "active_provider_hits", ())),
            readiness_probes,
            not any(bool(probe.get("is_ready")) for probe in readiness_probes or []),
        )
    ):
        return "challenge_page"
    low_content_shell = looks_like_low_content_shell(
        html,
        html_bytes=html_bytes,
        analysis=analysis,
    )
    if all(
        (
            traversal_result is not None,
            bool(getattr(traversal_result, "activated", False)),
        )
    ):
        progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
        card_count = int(getattr(traversal_result, "card_count", 0) or 0)
        stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
        if all(
            (
                progress_events == 0,
                card_count < int(crawler_runtime_settings.listing_min_items),
                stop_reason.endswith(("_not_found", "_no_progress")),
                low_content_shell,
            )
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
