from __future__ import annotations

import asyncio
import logging
from typing import Any

from bs4 import BeautifulSoup
from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.services.acquisition.browser_capture import is_response_closed_error
from app.services.acquisition.browser_interstitial import (
    dismiss_safe_location_interstitial as _interstitial_dismiss,
    location_interstitial_detected as _interstitial_detected,
    page_might_have_location_interstitial as _interstitial_page_probe,
)
from app.services.acquisition.browser_readiness import HtmlAnalysis
from app.services.config.extraction_rules import (
    ECOMMERCE_DETAIL_SURFACE,
    HTML_PARSER,
    LISTING_BRAND_SELECTORS,
    LISTING_UTILITY_URL_TOKENS,
    LISTING_VISUAL_PRICE_REGEX_PATTERN,
)
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
)
from app.services.config.selectors import (
    ANCHOR_SELECTOR,
    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS,
    LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS,
    LISTING_VISUAL_CAPTURE_SELECTORS,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.surface_hints import detail_path_hints
from app.services.dom.selector_engine import requested_content_extractability

logger = logging.getLogger(__name__)

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
    traversal_html: str,
    rendered_html: str,
    listing_min_items: int,
) -> str:
    if traversal_result is None or not getattr(traversal_result, "activated", False):
        return traversal_html or rendered_html
    if "listing" not in str(surface or "").strip().lower():
        return traversal_html or rendered_html
    if not str(rendered_html or "").strip():
        return traversal_html
    if not str(traversal_html or "").strip():
        return rendered_html
    progress_events = int(getattr(traversal_result, "progress_events", 0) or 0)
    card_count = int(getattr(traversal_result, "card_count", 0) or 0)
    stop_reason = str(getattr(traversal_result, "stop_reason", "") or "").strip()
    rendered_signal_count = _listing_html_detail_anchor_count(
        rendered_html,
        surface=surface,
    )
    traversal_signal_count = _listing_html_detail_anchor_count(
        traversal_html,
        surface=surface,
    )
    if rendered_signal_count > traversal_signal_count:
        return rendered_html
    if progress_events > 0 and (
        card_count >= max(1, int(listing_min_items))
        or traversal_signal_count >= max(2, rendered_signal_count)
    ):
        return traversal_html
    if card_count >= max(1, int(listing_min_items)):
        return rendered_html
    if stop_reason.endswith("_blocked") and traversal_signal_count >= max(
        2,
        int(listing_min_items),
    ):
        return traversal_html
    if stop_reason.endswith(
        ("_not_found", "_no_progress", "_click_failed", "_blocked")
    ):
        return rendered_html
    return traversal_html

def _listing_html_detail_anchor_count(
    html: str,
    *,
    surface: str | None,
) -> int:
    soup = BeautifulSoup(str(html or ""), HTML_PARSER)
    detail_markers = tuple(
        str(marker or "").strip().lower()
        for marker in detail_path_hints(surface)
        if str(marker or "").strip()
    )
    count = 0
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "").strip().lower()
        if any(marker in href for marker in detail_markers):
            count += 1
    return count

def _normalize_listing_recovery_mode(value: object) -> str | None:
    normalized = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized.endswith("_retry"):
        normalized = normalized[: -len("_retry")]
    return normalized or None

def _detail_expansion_extractability(
    *,
    html: str,
    soup: BeautifulSoup | None = None,
    surface: str,
    requested_fields: list[str] | None,
    requested_content_extractability_impl=requested_content_extractability,
    beautiful_soup_factory=BeautifulSoup,
) -> dict[str, object]:
    if soup is None and not str(html or "").strip():
        return {
            "verified": False,
            "matched_requested_fields": [],
            "extractable_fields": [],
            "section_fields": [],
        }
    if soup is None:
        soup = beautiful_soup_factory(str(html or ""), HTML_PARSER)
    return requested_content_extractability_impl(
        soup,
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
    if "listing" not in str(surface or "").strip().lower():
        return []
    try:
        snapshot = await page.evaluate(
            """(args) => {
                const anchorSelector = String(args?.anchorSelector || '');
                const detailUrlHints = Array.isArray(args?.detailUrlHints) ? args.detailUrlHints : [];
                const utilityUrlTokens = Array.isArray(args?.utilityUrlTokens) ? args.utilityUrlTokens : [];
                const brandSelectors = Array.isArray(args?.brandSelectors) ? args.brandSelectors : [];
                const selectors = [...(Array.isArray(args?.captureSelectors) ? args.captureSelectors : []), ...brandSelectors];
                const structuralAncestorSelectors = Array.isArray(args?.structuralAncestorSelectors) ? args.structuralAncestorSelectors : [];
                const candidateContainerSelectors = Array.isArray(args?.candidateContainerSelectors) ? args.candidateContainerSelectors : [];
                const seenNodes = new Set();
                const rows = [];
                // Extend currencies in LISTING_VISUAL_PRICE_REGEX_PATTERN.
                const priceRegex = new RegExp(String(args?.priceRegexPattern || ''), 'i');
                const isDataImage = (value) => /^data:/i.test(String(value || ''));
                for (const selector of selectors) {
                    for (const node of document.querySelectorAll(selector)) {
                        if (!(node instanceof HTMLElement) || !node.isConnected) {
                            continue;
                        }
                        if (seenNodes.has(node)) {
                            continue;
                        }
                        seenNodes.add(node);
                        const rect = node.getBoundingClientRect();
                        if (rect.width <= 0 || rect.height <= 0) {
                            continue;
                        }
                        const style = window.getComputedStyle(node);
                        if (
                            style.display === 'none' ||
                            style.visibility === 'hidden' ||
                            style.pointerEvents === 'none'
                        ) {
                            continue;
                        }
                        if (structuralAncestorSelectors.some((selector) => node.closest(selector))) {
                            continue;
                        }
                        const toAbsolute = (value) => {
                            if (!value || /^(#|javascript:)/i.test(value)) return '';
                            try { return new URL(value, location.href).href; } catch { return ''; }
                        };
                        const normalizedText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
                        const text = normalizedText(node.innerText || node.textContent || '').slice(0, 240);
                        const alt = normalizedText(node.getAttribute('alt') || '').slice(0, 240);
                        const ariaLabel = normalizedText(node.getAttribute('aria-label') || '').slice(0, 240);
                        const title = normalizedText(node.getAttribute('title') || '').slice(0, 240);
                        const src = toAbsolute(node.getAttribute('src') || '');
                        const directHref = toAbsolute(node.getAttribute('href') || '');
                        const closestAnchor = anchorSelector ? node.closest(anchorSelector) : null;
                        let href = directHref || toAbsolute(closestAnchor?.getAttribute('href') || '');
                        if (!href) {
                            const candidateContainerSelector = candidateContainerSelectors.join(',');
                            const container = candidateContainerSelector ? node.closest(candidateContainerSelector) : node;
                            const hintedAnchor = anchorSelector ? Array.from(container?.querySelectorAll?.(anchorSelector) || []).find((candidate) => {
                                const candidateHref = String(candidate?.getAttribute?.('href') || '').toLowerCase();
                                return detailUrlHints.some((hint) => candidateHref.includes(hint));
                            }) : null;
                            href = toAbsolute(hintedAnchor?.getAttribute('href') || '');
                        }
                        const loweredHref = href.toLowerCase();
                        const isDetailHref = detailUrlHints.some((hint) => loweredHref.includes(hint));
                        const isUtilityHref = utilityUrlTokens.some((token) => loweredHref.includes(token));
                        if (isUtilityHref && !isDetailHref) {
                            continue;
                        }
                        if (
                            href &&
                            !isDetailHref &&
                            /^https?:\\/\\/[^/]+\\/?$/i.test(href)
                        ) {
                            continue;
                        }
                        const combinedText = normalizedText([text, alt, ariaLabel, title].filter(Boolean).join(' '));
                        const hasPriceSignal = priceRegex.test(combinedText);
                        const titleLike =
                            combinedText.length >= 6 &&
                            combinedText.length <= 180 &&
                            !hasPriceSignal &&
                            !/^(skip to|sign in|shop now|learn more|view all)$/i.test(combinedText);
                        const largeImage = node.tagName.toLowerCase() === 'img' && Boolean(src) && !isDataImage(src) && rect.width >= 120 && rect.height >= 120;
                        const genericImageLabel = /^(?:product|products?|logo|icon|image)$/i.test(combinedText);
                        const likelyMerchandise = isDetailHref || hasPriceSignal || titleLike || largeImage;
                        if (!likelyMerchandise) {
                            continue;
                        }
                        if (!href && !hasPriceSignal) {
                            continue;
                        }
                        if (genericImageLabel && !isDetailHref && !hasPriceSignal) {
                            continue;
                        }
                        let score = 0;
                        if (isDetailHref) score += 14;
                        if (hasPriceSignal) score += 10;
                        if (titleLike) score += 7;
                        if (largeImage) score += 6;
                        if (href) score += 2;
                        if (node.tagName.toLowerCase() === 'a') score += 1;
                        if (combinedText.length >= 12 && combinedText.length <= 120) score += 2;
                        score -= Math.max(0, Math.floor(Math.max(0, rect.y) / 450));
                        rows.push({
                            tag: node.tagName.toLowerCase(),
                            text,
                            href,
                            src,
                            alt,
                            ariaLabel,
                            title,
                            x: Math.round(rect.x),
                            y: Math.round(rect.y),
                            width: Math.round(rect.width),
                            height: Math.round(rect.height),
                            score,
                        });
                    }
                }
                rows.sort((left, right) => {
                    const scoreDelta = Number(right.score || 0) - Number(left.score || 0);
                    if (scoreDelta !== 0) return scoreDelta;
                    const yDelta = Number(left.y || 0) - Number(right.y || 0);
                    if (yDelta !== 0) return yDelta;
                    return Number(left.x || 0) - Number(right.x || 0);
                });
                return rows.slice(0, 300);
            }""",
            {
                "detailUrlHints": [
                    hint.lower() for hint in detail_path_hints("ecommerce_detail")
                ],
                "utilityUrlTokens": [
                    token.lower() for token in LISTING_UTILITY_URL_TOKENS
                ],
                "brandSelectors": list(LISTING_BRAND_SELECTORS),
                "anchorSelector": ANCHOR_SELECTOR,
                "captureSelectors": list(LISTING_VISUAL_CAPTURE_SELECTORS),
                "candidateContainerSelectors": list(
                    LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS
                ),
                "structuralAncestorSelectors": list(
                    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS
                ),
                "priceRegexPattern": LISTING_VISUAL_PRICE_REGEX_PATTERN,
            },
        )
    except asyncio.CancelledError:
        raise
    except PlaywrightTimeoutError:
        logger.warning("Timed out while capturing listing visual elements")
        return []
    except PlaywrightError as exc:
        logger.debug(
            "Failed to capture listing visual elements status=%s",
            "closed" if is_response_closed_error(exc) else "playwright_error",
            exc_info=True,
        )
        return []
    except Exception:
        logger.exception("Failed to capture listing visual elements unexpectedly")
        return []
    if not isinstance(snapshot, list):
        return []
    rows: list[dict[str, object]] = []
    for item in snapshot[:300]:
        if not isinstance(item, dict):
            continue
        rows.append(dict(item))
    return rows


object_int = _object_int
select_primary_browser_html = _select_primary_browser_html
normalize_listing_recovery_mode = _normalize_listing_recovery_mode
detail_expansion_extractability = _detail_expansion_extractability
detail_expansion_can_skip = _detail_expansion_can_skip
capture_listing_visual_elements = _capture_listing_visual_elements
