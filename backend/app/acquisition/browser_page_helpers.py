from __future__ import annotations

import asyncio
from typing import Any

from app.acquisition.dom_runtime import get_page_html
from app.acquisition.browser_interstitial import (
    dismiss_safe_location_interstitial as _interstitial_dismiss,
    location_interstitial_detected as _interstitial_detected,
    page_might_have_location_interstitial as _interstitial_page_probe,
)
from app.core.config.extraction_rules import ECOMMERCE_DETAIL_SURFACE
from app.core.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.config.url_path_markers import detail_path_markers
from app.core.records.css_extractability import requested_content_extractability
from app.extraction.documents import HtmlAnalysis, HtmlDocument

def _object_int(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    try:
        return int(str(default if value is None else value))
    except (TypeError, ValueError):
        return default

async def page_might_have_location_interstitial(page: Any) -> bool:
    return await _interstitial_page_probe(page)

async def dismiss_safe_location_interstitial(page: Any) -> dict[str, object]:
    return await _interstitial_dismiss(page)

def location_interstitial_detected(
    html: str,
    *,
    analysis: HtmlAnalysis | None = None,
) -> bool:
    return _interstitial_detected(html, analysis=analysis)

def _select_primary_browser_html(
    *,
    surface: str | None,
    traversal_result,
    traversal_analysis: HtmlAnalysis,
    rendered_analysis: HtmlAnalysis,
    listing_min_items: int,
) -> tuple[str, HtmlAnalysis]:
    traversal_html = traversal_analysis.html
    rendered_html = rendered_analysis.html
    if traversal_result is None or not getattr(traversal_result, "activated", False):
        selected = traversal_analysis if traversal_html else rendered_analysis
        return selected.html, selected
    if "listing" not in str(surface or "").strip().lower():
        selected = traversal_analysis if traversal_html else rendered_analysis
        return selected.html, selected
    if not str(rendered_html or "").strip():
        return traversal_html, traversal_analysis
    if not str(traversal_html or "").strip():
        return rendered_html, rendered_analysis
    progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
    card_count = int(getattr(traversal_result, "card_count", 0) or 0)
    stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
    rendered_signal_count = _listing_html_detail_anchor_count(
        rendered_analysis.document,
        surface=surface,
    )
    traversal_signal_count = _listing_html_detail_anchor_count(
        traversal_analysis.document,
        surface=surface,
    )
    if rendered_signal_count > traversal_signal_count:
        return rendered_html, rendered_analysis
    if progress_events > 0 and (
        card_count >= max(1, int(listing_min_items))
        or traversal_signal_count >= max(2, rendered_signal_count)
    ):
        return traversal_html, traversal_analysis
    if card_count >= max(1, int(listing_min_items)):
        return rendered_html, rendered_analysis
    if stop_reason.endswith("_blocked") and traversal_signal_count >= max(
        2,
        int(listing_min_items),
    ):
        return traversal_html, traversal_analysis
    if stop_reason.endswith(
        ("_not_found", "_no_progress", "_click_failed", "_blocked")
    ):
        return rendered_html, rendered_analysis
    return traversal_html, traversal_analysis

def _listing_html_detail_anchor_count(
    document: HtmlDocument,
    *,
    surface: str | None,
) -> int:
    detail_markers = tuple(
        str(marker or "").strip().lower()
        for marker in detail_path_markers(surface or "")
        if str(marker or "").strip()
    )
    count = 0
    for anchor in document.css("a[href]"):
        href = str(anchor.attribute("href") or "").strip().lower()
        if any(marker in href for marker in detail_markers):
            count += 1
    return count


async def _select_traversal_snapshot(
    *,
    surface: str | None,
    traversal_result,
    traversal_html: str,
    rendered_html: str,
) -> tuple[str, HtmlAnalysis]:
    rendered_analysis = await asyncio.to_thread(HtmlAnalysis.from_html, rendered_html)
    traversal_analysis = (
        rendered_analysis
        if rendered_analysis.matches_html(traversal_html)
        else await asyncio.to_thread(HtmlAnalysis.from_html, traversal_html)
    )
    return _select_primary_browser_html(
        surface=surface,
        traversal_result=traversal_result,
        traversal_analysis=traversal_analysis,
        rendered_analysis=rendered_analysis,
        listing_min_items=int(crawler_runtime_settings.listing_min_items),
    )


async def _resolve_rendered_snapshot(
    page: Any,
    *,
    prefetched_html: str | None,
    prefetched_analysis: HtmlAnalysis | None,
    flatten_shadow: bool,
) -> tuple[str, str, HtmlAnalysis]:
    html = str(prefetched_html or "")
    if not html.strip() and prefetched_analysis is not None:
        html = prefetched_analysis.html
    if not html.strip():
        html = await get_page_html(page, flatten_shadow=flatten_shadow)
    analysis = (
        prefetched_analysis
        if prefetched_analysis is not None
        and prefetched_analysis.matches_html(html)
        else await asyncio.to_thread(HtmlAnalysis.from_html, html)
    )
    return html, html, analysis

def _normalize_listing_recovery_mode(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.endswith("_retry"):
        normalized = normalized[: -len("_retry")]
    return normalized or None

def _detail_expansion_extractability(
    *,
    document: HtmlDocument | None,
    surface: str,
    requested_fields: list[str] | None,
    requested_content_extractability_impl=requested_content_extractability,
) -> dict[str, object]:
    if document is None or not document.html().strip():
        return {
            "verified": False,
            "matched_requested_fields": [],
            "extractable_fields": [],
            "section_fields": [],
        }
    return requested_content_extractability_impl(
        document,
        surface=surface,
        requested_fields=requested_fields,
        probe_fields=_detail_expansion_probe_fields(
            surface=surface,
            requested_fields=requested_fields,
        ),
    )

def _detail_expansion_probe_fields(
    *,
    surface: str,
    requested_fields: list[str] | None,
) -> list[str] | None:
    if requested_fields:
        return sorted({str(field_name).strip() for field_name in requested_fields if str(field_name).strip()}) or None
    normalized_surface = str(surface or "").strip().lower()
    probe_fields = {
        *set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ()),
        *set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ()),
    }
    return sorted(probe_fields) or None

def _detail_expansion_can_skip(
    extractability: dict[str, object],
    *,
    surface: str | None,
    requested_fields: list[str] | None,
    readiness_probe: dict[str, object] | None = None,
) -> tuple[bool, str | None]:
    if list(requested_fields or []):
        can_skip = bool(extractability.get("verified")) and bool(
            extractability.get("matched_requested_fields")
        )
        return (
            can_skip,
            "requested_content_already_extractable" if can_skip else None,
        )
    normalized_surface = str(surface or "").strip().lower()
    if normalized_surface == ECOMMERCE_DETAIL_SURFACE and bool(
        (readiness_probe or {}).get("is_ready")
    ):
        if not list(requested_fields or []) and _ready_probe_has_detail_content(
            readiness_probe
        ):
            return True, "canonical_detail_already_ready"
        can_skip = bool(extractability.get("verified"))
        return can_skip, "canonical_detail_already_ready" if can_skip else None
    if not bool(extractability.get("verified")):
        return False, None
    can_skip = "ecommerce" not in normalized_surface
    return can_skip, "requested_content_already_extractable" if can_skip else None


def _ready_probe_has_detail_content(
    readiness_probe: dict[str, object] | None,
) -> bool:
    probe = readiness_probe if isinstance(readiness_probe, dict) else {}
    visible_text_length = _object_int(probe.get("visible_text_length"))
    visible_text_min = int(crawler_runtime_settings.browser_readiness_visible_text_min)
    if bool(probe.get("structured_data_present")) and visible_text_length >= visible_text_min:
        return True
    detail_hint_count = _object_int(probe.get("detail_hint_count"))
    if (
        detail_hint_count >= int(crawler_runtime_settings.detail_field_signal_min_count)
        and visible_text_length >= visible_text_min
    ):
        return True
    return bool(probe.get("h1_present")) and visible_text_length >= visible_text_min

async def _capture_listing_visual_elements(
    page: Any,
    *,
    surface: str | None,
) -> list[dict[str, object]]:
    from app.acquisition.browser_listing_visual import (
        capture_listing_visual_elements,
    )

    return await capture_listing_visual_elements(page, surface=surface)


object_int = _object_int
select_primary_browser_html = _select_primary_browser_html
select_traversal_snapshot = _select_traversal_snapshot
resolve_rendered_snapshot = _resolve_rendered_snapshot
normalize_listing_recovery_mode = _normalize_listing_recovery_mode
detail_expansion_extractability = _detail_expansion_extractability
detail_expansion_can_skip = _detail_expansion_can_skip
capture_listing_visual_elements = _capture_listing_visual_elements
