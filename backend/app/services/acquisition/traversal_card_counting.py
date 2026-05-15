"""Card-counting and progress-snapshot helpers for traversal.

Owns the pure measurement concern: how many listing cards are currently on the
page, how identity-unique they are, and whether two consecutive snapshots show
progress. `traversal.py` imports these to drive its pagination / scroll /
load-more loops and stays focused on orchestration.
"""

from __future__ import annotations

import hashlib
import logging
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import urljoin, urlsplit

from selectolax.lexbor import LexborHTMLParser
from selectolax.lexbor import LexborNode as _SelectolaxNode

try:
    from patchright.async_api import Error as PlaywrightError
    from patchright.async_api import Page
except ImportError:  # pragma: no cover
    class PlaywrightError(Exception):  # type: ignore[no-redef]
        pass
    Page = Any  # type: ignore[assignment,misc]

from app.services.acquisition.dom_runtime import get_page_html
from app.services.config.extraction_rules import LISTING_CARD_URL_ATTRS
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.config.selectors import CARD_SELECTORS
from app.services.extract.listing_card_fragments import (
    heuristic_listing_card_count_from_html,
    listing_node_attr,
    listing_node_css,
    listing_selector_is_weak,
    select_listing_fragment_nodes,
)

if TYPE_CHECKING:
    from app.services.acquisition.traversal import TraversalResult

logger = logging.getLogger(__name__)


async def count_listing_cards(
    page: Page, *, surface: str, allow_heuristic: bool = True
) -> int:
    selector_group = "jobs" if str(surface or "").strip().lower().startswith("job_") else "ecommerce"
    selectors = CARD_SELECTORS.get(selector_group) if isinstance(CARD_SELECTORS, dict) else []
    normalized_selectors = [
        str(selector).strip() for selector in list(selectors or []) if str(selector).strip()
    ]
    if not normalized_selectors:
        return await _heuristic_card_count(page, surface=surface) if allow_heuristic else 0
    try:
        selector_counts = await page.evaluate(
            """
            (selectors) => {
              const counts = {};
              for (const selector of selectors) {
                try {
                  counts[selector] = document.querySelectorAll(selector).length;
                } catch (error) {
                  continue;
                }
              }
              return counts;
            }
            """,
            normalized_selectors,
        )
    except PlaywrightError:
        raise
    except Exception:
        logger.debug(
            "Traversal card counting via evaluate failed for surface=%s; falling back to locator counts",
            surface,
            exc_info=True,
        )
        highest = 0
        for selector in normalized_selectors:
            try:
                highest = max(highest, await page.locator(selector).count())
            except PlaywrightError:
                raise
            except Exception:
                logger.debug(
                    "Traversal locator fallback failed for surface=%s selector=%s",
                    surface,
                    selector,
                    exc_info=True,
                )
                continue
        return highest
    if isinstance(selector_counts, dict):
        strong_count = 0
        weak_count = 0
        for selector, raw_count in selector_counts.items():
            try:
                count = max(0, int(raw_count or 0))
            except (TypeError, ValueError):
                count = 0
            if listing_selector_is_weak(str(selector or "")):
                weak_count = max(weak_count, count)
            else:
                strong_count = max(strong_count, count)
        if strong_count > 0:
            if allow_heuristic and strong_count < max(
                3,
                int(crawler_runtime_settings.listing_min_items) + 1,
            ):
                heuristic_count = await _heuristic_card_count(page, surface=surface)
                if heuristic_count <= 0:
                    return 0
                return max(strong_count, heuristic_count)
            return strong_count
        if weak_count > 0 and allow_heuristic:
            return await _heuristic_card_count(page, surface=surface)
        resolved = weak_count
    else:
        try:
            resolved = max(0, int(selector_counts or 0))
        except (TypeError, ValueError):
            resolved = 0
    if resolved > 0:
        return resolved
    if allow_heuristic:
        return await _heuristic_card_count(page, surface=surface)
    return 0


async def _heuristic_card_count(page: Page, *, surface: str) -> int:
    return heuristic_listing_card_count_from_html(
        await get_page_html(page, flatten_shadow=False),
        surface=surface,
    )


def _unique_listing_card_identity_count_from_html(
    html: str,
    *,
    page_url: str,
    surface: str,
) -> int:
    if not html:
        return 0
    parser = LexborHTMLParser(html)
    identities: set[str] = set()
    for card in select_listing_fragment_nodes(
        parser,
        surface=surface,
        limit=max(1, int(crawler_runtime_settings.listing_fallback_fragment_limit)),
    ):
        identity = _listing_card_identity(cast(_SelectolaxNode, card), page_url=page_url)
        if identity:
            identities.add(identity)
    return len(identities)


def _listing_card_identity(card: _SelectolaxNode, *, page_url: str) -> str:
    selectors = ",".join(f"[{attr_name}]" for attr_name in LISTING_CARD_URL_ATTRS)
    candidates = [card, *listing_node_css(card, selectors)]
    page_path = str(urlsplit(page_url).path or "").rstrip("/").lower()
    for candidate in candidates:
        for attr_name in LISTING_CARD_URL_ATTRS:
            raw_value = listing_node_attr(candidate, str(attr_name))
            if not raw_value:
                continue
            resolved = urljoin(page_url, raw_value)
            parsed = urlsplit(resolved)
            scheme = str(parsed.scheme or "").lower()
            path = str(parsed.path or "").rstrip("/").lower()
            if scheme not in {"http", "https"} or path in {"", "/"}:
                continue
            if page_path and path == page_path:
                continue
            host = str(parsed.hostname or "").lower()
            if not host:
                continue
            return f"{host}{path}"
    return ""


async def page_snapshot(page: Page, *, surface: str) -> dict[str, Any]:
    snapshot = await page.evaluate(
        """
        () => {
          const root = document.scrollingElement || document.documentElement || document.body;
          const normalize = (text, limit) =>
            String(text || '')
              .replace(/\\s+/g, ' ')
              .trim()
              .slice(0, limit);
          const visibleText = normalize(document.body?.innerText || '', 1600);
          const anchorSummary = Array.from(
            document.querySelectorAll('main a[href], article a[href], li a[href], tr a[href], section a[href], [role=\"row\"] a[href]')
          )
            .slice(0, 24)
            .map((node) =>
              `${normalize(node.getAttribute('href'), 140)}|${normalize(node.textContent, 80)}`
            )
            .join('||');
          const overflowContainers = Array.from(document.querySelectorAll('*')).filter((node) => {
            const style = window.getComputedStyle(node);
            return ['auto', 'scroll'].includes(style.overflowY) && node.scrollHeight - node.clientHeight > 150;
          }).length;
          return {
            scroll_height: Number(root?.scrollHeight || 0),
            client_height: Number(root?.clientHeight || window.innerHeight || 0),
            overflow_containers: overflowContainers,
            content_signature_source: `${location.href}::${visibleText}::${anchorSummary}`,
          };
        }
        """
    )
    if not isinstance(snapshot, dict):
        snapshot = {}
    raw_card_count = await count_listing_cards(page, surface=surface)
    try:
        html = await get_page_html(page, flatten_shadow=False)
    except AttributeError:
        html = ""
    unique_card_count = _unique_listing_card_identity_count_from_html(
        html,
        page_url=str(getattr(page, "url", "") or ""),
        surface=surface,
    )
    card_count = (
        unique_card_count
        if unique_card_count >= int(crawler_runtime_settings.listing_min_items)
        and unique_card_count < raw_card_count
        else raw_card_count
    )
    return {
        "card_count": card_count,
        "content_signature": _content_signature(snapshot.pop("content_signature_source", "")),
        **snapshot,
    }


def snapshot_progressed(
    previous: dict[str, Any], current: dict[str, Any]
) -> bool:
    if int(current.get("card_count", 0)) > int(previous.get("card_count", 0)):
        return True
    if str(current.get("content_signature") or "") != str(
        previous.get("content_signature") or ""
    ):
        return True
    if int(current.get("scroll_height", 0)) >= int(previous.get("scroll_height", 0)) + int(
        crawler_runtime_settings.traversal_force_probe_min_advance_px
    ):
        return True
    return False


def paginate_snapshot_progressed(
    previous: dict[str, Any], current: dict[str, Any]
) -> bool:
    previous_count = int(previous.get("card_count", 0))
    current_count = int(current.get("card_count", 0))
    if current_count > previous_count:
        return True
    if previous_count <= 0 and current_count <= 0:
        return False
    return snapshot_progressed(previous, current)


def is_marginal_card_gain(*, card_gain: int, best_gain: int, current_count: int) -> bool:
    if card_gain <= 0:
        return False
    if current_count < max(6, int(crawler_runtime_settings.listing_min_items) * 3):
        return False
    if best_gain < max(2, int(crawler_runtime_settings.listing_min_items) * 2):
        return False
    return card_gain <= max(1, best_gain // 5)


def paginate_fragment_budget_reached(
    result: "TraversalResult",
    *,
    target_records: int | None = None,
    current_count: int | None = None,
) -> bool:
    if int(result.pages_advanced or 0) < 1:
        return False
    if target_records is not None:
        try:
            target = int(target_records)
        except (TypeError, ValueError):
            target = 0
        if target > 0 and int(current_count if current_count is not None else result.card_count) < target:
            return False
    fragment_budget = max(
        8_192,
        int(crawler_runtime_settings.traversal_fragment_max_bytes),
    )
    return result.html_bytes() >= fragment_budget


def target_record_limit_reached(*, max_records: int | None, current_count: int) -> bool:
    try:
        target = int(max_records or 0)
    except (TypeError, ValueError):
        return False
    return target > 0 and int(current_count) >= target


def _content_signature(html: str) -> str:
    text = str(html or "").strip()
    if not text:
        return ""
    return hashlib.sha1(
        text.encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()


__all__ = [
    "count_listing_cards",
    "is_marginal_card_gain",
    "page_snapshot",
    "paginate_fragment_budget_reached",
    "paginate_snapshot_progressed",
    "snapshot_progressed",
    "target_record_limit_reached",
]
