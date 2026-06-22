from __future__ import annotations

import asyncio
from html import escape
import logging
import re
from typing import Any, TypedDict

from patchright.async_api import Error as PlaywrightError
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.acquisition.browser_capture import is_response_closed_error
from app.core.config.extraction_rules import (
    LISTING_BRAND_SELECTORS,
    LISTING_UTILITY_URL_TOKENS,
    LISTING_VISUAL_PRICE_REGEX_PATTERN,
)
from app.core.config.selectors import (
    ANCHOR_SELECTOR,
    LISTING_CAPTURE_STRUCTURAL_ANCESTOR_SELECTORS,
    LISTING_VISUAL_CANDIDATE_CONTAINER_SELECTORS,
    LISTING_VISUAL_CAPTURE_SELECTORS,
)
from app.core.config.url_path_markers import detail_path_markers

logger = logging.getLogger(__name__)


class ListingVisualElement(TypedDict):
    tag: str
    text: str
    href: str
    src: str
    alt: str
    ariaLabel: str
    title: str
    x: int
    y: int
    width: int
    height: int
    score: int


LISTING_VISUAL_CAPTURE_SCRIPT = """(args) => {
    const anchorSelector = String(args?.anchorSelector || '');
    const detailUrlHints = Array.isArray(args?.detailUrlHints) ? args.detailUrlHints : [];
    const utilityUrlTokens = Array.isArray(args?.utilityUrlTokens) ? args.utilityUrlTokens : [];
    const brandSelectors = Array.isArray(args?.brandSelectors) ? args.brandSelectors : [];
    const selectors = [...(Array.isArray(args?.captureSelectors) ? args.captureSelectors : []), ...brandSelectors];
    const structuralAncestorSelectors = Array.isArray(args?.structuralAncestorSelectors) ? args.structuralAncestorSelectors : [];
    const candidateContainerSelectors = Array.isArray(args?.candidateContainerSelectors) ? args.candidateContainerSelectors : [];
    const seenNodes = new Set();
    const rows = [];
    const priceRegex = new RegExp(String(args?.priceRegexPattern || ''), 'i');
    const isDataImage = (value) => /^data:/i.test(String(value || ''));
    const toAbsolute = (value) => {
        if (!value || /^(#|javascript:)/i.test(value)) return '';
        try { return new URL(value, location.href).href; } catch { return ''; }
    };
    const normalizedText = (value) => String(value || '').replace(/\\s+/g, ' ').trim();
    for (const selector of selectors) {
        for (const node of document.querySelectorAll(selector)) {
            if (!(node instanceof HTMLElement) || !node.isConnected || seenNodes.has(node)) continue;
            seenNodes.add(node);
            const rect = node.getBoundingClientRect();
            if (rect.width <= 0 || rect.height <= 0) continue;
            const style = window.getComputedStyle(node);
            if (style.display === 'none' || style.visibility === 'hidden' || style.pointerEvents === 'none') continue;
            if (structuralAncestorSelectors.some((item) => node.closest(item))) continue;
            const text = normalizedText(node.innerText || node.textContent || '').slice(0, 240);
            const alt = normalizedText(node.getAttribute('alt') || '').slice(0, 240);
            const ariaLabel = normalizedText(node.getAttribute('aria-label') || '').slice(0, 240);
            const title = normalizedText(node.getAttribute('title') || '').slice(0, 240);
            const src = toAbsolute(node.getAttribute('src') || '');
            const directHref = toAbsolute(node.getAttribute('href') || '');
            const closestAnchor = anchorSelector ? node.closest(anchorSelector) : null;
            let href = directHref || toAbsolute(closestAnchor?.getAttribute('href') || '');
            if (!href) {
                const containerSelector = candidateContainerSelectors.join(',');
                const container = containerSelector ? node.closest(containerSelector) : node;
                const hintedAnchor = anchorSelector ? Array.from(container?.querySelectorAll?.(anchorSelector) || []).find((candidate) => {
                    const candidateHref = String(candidate?.getAttribute?.('href') || '').toLowerCase();
                    return detailUrlHints.some((hint) => candidateHref.includes(hint));
                }) : null;
                href = toAbsolute(hintedAnchor?.getAttribute('href') || '');
            }
            const loweredHref = href.toLowerCase();
            const isDetailHref = detailUrlHints.some((hint) => loweredHref.includes(hint));
            const isUtilityHref = utilityUrlTokens.some((token) => loweredHref.includes(token));
            if (isUtilityHref && !isDetailHref) continue;
            if (href && !isDetailHref && /^https?:\\/\\/[^/]+\\/?$/i.test(href)) continue;
            const combinedText = normalizedText([text, alt, ariaLabel, title].filter(Boolean).join(' '));
            const hasPriceSignal = priceRegex.test(combinedText);
            const titleLike = combinedText.length >= 6 && combinedText.length <= 180 && !hasPriceSignal && !/^(skip to|sign in|shop now|learn more|view all)$/i.test(combinedText);
            const largeImage = node.tagName.toLowerCase() === 'img' && Boolean(src) && !isDataImage(src) && rect.width >= 120 && rect.height >= 120;
            const genericImageLabel = /^(?:product|products?|logo|icon|image)$/i.test(combinedText);
            if (!(isDetailHref || hasPriceSignal || titleLike || largeImage)) continue;
            if (!href && !hasPriceSignal) continue;
            if (genericImageLabel && !isDetailHref && !hasPriceSignal) continue;
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
                tag: node.tagName.toLowerCase(), text, href, src, alt, ariaLabel, title,
                x: Math.round(rect.x), y: Math.round(rect.y),
                width: Math.round(rect.width), height: Math.round(rect.height), score,
            });
        }
    }
    rows.sort((left, right) => {
        const scoreDelta = Number(right.score || 0) - Number(left.score || 0);
        if (scoreDelta !== 0) return scoreDelta;
        const yDelta = Number(left.y || 0) - Number(right.y || 0);
        return yDelta !== 0 ? yDelta : Number(left.x || 0) - Number(right.x || 0);
    });
    return rows.slice(0, 300);
}"""


def _capture_args() -> dict[str, object]:
    return {
        "detailUrlHints": [
            hint.lower() for hint in detail_path_markers("ecommerce_detail")
        ],
        "utilityUrlTokens": [token.lower() for token in LISTING_UTILITY_URL_TOKENS],
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
    }


def listing_visual_elements_html(snapshot: object) -> str:
    groups: dict[str, list[dict[str, object]]] = {}
    if isinstance(snapshot, list):
        for item in snapshot:
            if isinstance(item, dict) and (
                href := " ".join(str(item.get("href") or "").split())
            ):
                groups.setdefault(href, []).append(item)
    cards: list[str] = []
    for index, (href, items) in enumerate(groups.items()):
        labels: list[str] = []
        images: list[str] = []
        prices: list[str] = []
        for item in items:
            for key in ("title", "ariaLabel", "alt", "text"):
                value = " ".join(str(item.get(key) or "").split())
                prices.extend(
                    price
                    for price in re.findall(
                        LISTING_VISUAL_PRICE_REGEX_PATTERN, value, re.I
                    )
                    if price not in prices
                )
                label = re.sub(
                    LISTING_VISUAL_PRICE_REGEX_PATTERN, " ", value, flags=re.I
                ).strip(" |-–—")
                if label and label not in labels:
                    labels.append(label)
            src = " ".join(str(item.get("src") or "").split())
            if src and src not in images:
                images.append(src)
        if not labels:
            continue
        escaped_href = escape(href, quote=True)
        links = "".join(
            f'<a href="{escaped_href}" title="{escape(label, quote=True)}">{escape(label)}</a>'
            for label in labels
        )
        image_html = "".join(f'<img src="{escape(src, quote=True)}">' for src in images)
        price_html = "".join(
            f'<span class="price">{escape(price)}</span>' for price in prices
        )
        cards.append(
            f'<article data-product-id="visual-{index}">{links}{image_html}{price_html}</article>'
        )
    return f"<main>{''.join(cards)}</main>" if cards else ""


def _normalize_snapshot(snapshot: object) -> list[ListingVisualElement]:
    if not isinstance(snapshot, list):
        return []
    rows: list[ListingVisualElement] = []
    for item in snapshot[:300]:
        if not isinstance(item, dict):
            continue
        rows.append(
            ListingVisualElement(
                tag=str(item.get("tag") or ""),
                text=str(item.get("text") or ""),
                href=str(item.get("href") or ""),
                src=str(item.get("src") or ""),
                alt=str(item.get("alt") or ""),
                ariaLabel=str(item.get("ariaLabel") or ""),
                title=str(item.get("title") or ""),
                x=int(item.get("x") or 0),
                y=int(item.get("y") or 0),
                width=int(item.get("width") or 0),
                height=int(item.get("height") or 0),
                score=int(item.get("score") or 0),
            )
        )
    return rows


async def capture_listing_visual_elements(
    page: Any,
    *,
    surface: str | None,
) -> list[dict[str, object]]:
    if "listing" not in str(surface or "").strip().lower():
        return []
    try:
        snapshot = await page.evaluate(LISTING_VISUAL_CAPTURE_SCRIPT, _capture_args())
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
    return [dict(item) for item in _normalize_snapshot(snapshot)]


__all__ = [
    "ListingVisualElement",
    "capture_listing_visual_elements",
    "listing_visual_elements_html",
]
