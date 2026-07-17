"""Card-counting and progress-snapshot helpers for traversal.

Owns the pure measurement concern: how many listing cards are currently on the
page, how identity-unique they are, and whether two consecutive snapshots show
progress. `traversal.py` imports these to drive its pagination / scroll /
load-more loops and stays focused on orchestration.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Any

try:
    from patchright.async_api import Page
except ImportError:  # pragma: no cover
    Page = Any  # type: ignore[assignment,misc]

from app.acquisition.dom_runtime import get_page_html
from app.acquisition.listing_cards import (
    card_identities_from_html,
    count_listing_cards,
)
from app.core.config.runtime_settings import crawler_runtime_settings

if TYPE_CHECKING:
    from app.acquisition.traversal_types import TraversalResult


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
    try:
        html = await get_page_html(page, flatten_shadow=False)
    except AttributeError:
        html = ""
    identities = card_identities_from_html(
        html, page_url=str(getattr(page, "url", "") or ""), surface=surface
    )
    return {
        "card_count": len(identities),
        "card_identities": identities,
        "content_signature": _content_signature(
            snapshot.pop("content_signature_source", "")
        ),
        **snapshot,
    }


def snapshot_progressed(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if int(current.get("card_count", 0)) > int(previous.get("card_count", 0)):
        return True
    if str(current.get("content_signature") or "") != str(
        previous.get("content_signature") or ""
    ):
        return True
    if int(current.get("scroll_height", 0)) >= int(
        previous.get("scroll_height", 0)
    ) + int(crawler_runtime_settings.traversal_force_probe_min_advance_px):
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


def is_marginal_card_gain(
    *, card_gain: int, best_gain: int, current_count: int
) -> bool:
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
        if (
            target > 0
            and int(current_count if current_count is not None else result.card_count)
            < target
        ):
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
