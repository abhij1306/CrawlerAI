from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

from app.acquisition.browser_capture import PlaywrightError, PlaywrightTimeoutError
from app.acquisition.traversal_card_counting import (
    is_marginal_card_gain,
    page_snapshot,
    snapshot_progressed,
    target_record_limit_reached,
)
from app.acquisition.traversal_helpers import (
    append_html_fragment,
    is_same_origin,
    page_matches_block_challenge,
    remaining_timeout_ms,
    settle_after_action,
    wait_for_transition,
)
from app.acquisition.events import AcquisitionEvent, emit_acquisition_event
from app.acquisition.traversal_recovery import (
    click_with_retry,
    find_actionable_locator,
)
from app.acquisition.traversal_types import TraversalResult
from app.core.config.runtime_settings import crawler_runtime_settings


@dataclass(slots=True)
class TraversalGainState:
    best_card_gain: int = 0
    marginal_gain_streak: int = 0
    weak_progress_streak: int = 0

    def record_progress(self, *, card_gain: int, current_count: int) -> None:
        if card_gain > 0:
            self.best_card_gain = max(self.best_card_gain, card_gain)
        self.weak_progress_streak = 0
        if is_marginal_card_gain(
            card_gain=card_gain,
            best_gain=self.best_card_gain,
            current_count=current_count,
        ):
            self.marginal_gain_streak += 1
        else:
            self.marginal_gain_streak = 0

    def record_no_progress(self) -> None:
        self.weak_progress_streak += 1
        self.marginal_gain_streak = 0


@dataclass(slots=True)
class TraversalStep:
    status: str
    snapshot: dict[str, Any] | None = None


def effective_scroll_limit(max_scrolls: int) -> int:
    cap = int(crawler_runtime_settings.traversal_max_iterations_cap)
    try:
        requested = int(max_scrolls)
    except (TypeError, ValueError):
        requested = 0
    return min(cap, requested) if requested > 0 else cap


async def run_scroll_step(
    page,
    *,
    surface: str,
    deadline_at: float | None,
) -> TraversalStep:
    await page.evaluate(
        """() => {
          const root = document.scrollingElement || document.documentElement || document.body;
          root.scrollTo({ top: root.scrollHeight, behavior: "auto" });
        }"""
    )
    wait_ms = remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.scroll_wait_min_ms),
    )
    if wait_ms <= 0:
        return TraversalStep("budget_exceeded")
    await settle_after_action(page, deadline_at=deadline_at, timeout_ms=wait_ms)
    return TraversalStep("ok", await page_snapshot(page, surface=surface))


async def wait_for_load_more_card_gain(
    page,
    *,
    previous: dict[str, Any],
    surface: str,
    max_records: int | None,
    deadline_at: float | None,
) -> dict[str, Any] | None:
    previous_count = int(previous.get("card_count", 0))
    timeout_ms = remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
    )
    if timeout_ms <= 0:
        return None
    poll_ms = max(1, int(crawler_runtime_settings.pagination_post_click_poll_ms))
    waited_ms = 0
    best: dict[str, Any] | None = None
    while waited_ms < timeout_ms:
        step_ms = min(poll_ms, max(1, timeout_ms - waited_ms))
        await page.wait_for_timeout(step_ms)
        waited_ms += step_ms
        current = await page_snapshot(page, surface=surface)
        current_count = int(current.get("card_count", 0))
        if current_count > previous_count and (
            best is None or current_count > int(best.get("card_count", 0))
        ):
            best = current
            if target_record_limit_reached(
                max_records=max_records,
                current_count=current_count,
            ):
                return best
    return best


async def advance_load_more(
    page,
    *,
    previous: dict[str, Any],
    surface: str,
    max_records: int | None,
    result: TraversalResult,
    deadline_at: float | None,
) -> TraversalStep:
    locator = await find_actionable_locator(page, "load_more")
    if locator is None:
        settled = await wait_for_load_more_card_gain(
            page,
            previous=previous,
            surface=surface,
            max_records=max_records,
            deadline_at=deadline_at,
        )
        return TraversalStep("load_more_not_found", settled)
    result.iterations += 1
    result.load_more_clicks += 1
    current_url = page.url
    if not await click_with_retry(
        page,
        locator,
        result=result,
        deadline_at=deadline_at,
    ):
        return TraversalStep("load_more_click_failed")
    wait_ms = remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.load_more_wait_min_ms),
    )
    if wait_ms <= 0:
        return TraversalStep("budget_exceeded")
    await wait_for_transition(
        page,
        previous_url=current_url,
        deadline_at=deadline_at,
        timeout_ms=wait_ms,
    )
    current = await page_snapshot(page, surface=surface)
    if not snapshot_progressed(previous, current):
        progressed = await wait_for_load_more_card_gain(
            page,
            previous=previous,
            surface=surface,
            max_records=max_records,
            deadline_at=deadline_at,
        )
        if progressed is not None:
            current = progressed
    return TraversalStep("ok", current)


async def _resolve_paginate_target(
    locator,
    *,
    current_url: str,
    visited_urls: set[str],
) -> tuple[str, str | None]:
    href = await locator.get_attribute("href")
    normalized_href = str(href or "").strip().lower()
    if not href or normalized_href.startswith(("#", "javascript:")):
        return "click", None
    next_url = urljoin(current_url, href)
    if not is_same_origin(current_url, next_url):
        return "paginate_off_domain", None
    if next_url in visited_urls:
        return "paginate_cycle_detected", None
    return "navigate", next_url


def _resolved_paginate_cycle(
    *,
    resolved_url: str,
    current_url: str,
    intended_url: str | None,
    visited_urls: set[str],
) -> bool:
    if resolved_url not in visited_urls:
        return False
    if intended_url is not None:
        return resolved_url != intended_url
    return resolved_url != current_url


async def settle_thin_initial_listing(
    page,
    *,
    previous: dict[str, Any],
    result: TraversalResult,
    surface: str,
    deadline_at: float | None,
    on_event,
) -> dict[str, Any] | None:
    if result.progress_events > 0 or result.iterations > 0:
        return None
    current_count = int(previous.get("card_count", 0))
    if current_count >= max(6, int(crawler_runtime_settings.listing_min_items) * 3):
        return None
    await settle_after_action(
        page,
        deadline_at=deadline_at,
        timeout_ms=int(
            crawler_runtime_settings.traversal_settle_networkidle_timeout_ms
        ),
    )
    current = await page_snapshot(page, surface=surface)
    if not snapshot_progressed(previous, current):
        return None
    await append_html_fragment(page, result, surface=surface)
    result.progress_events += 1
    message = (
        "Initial listing settled - "
        f"{previous.get('card_count', 0)} -> {current.get('card_count', 0)} records"
    )
    result.events.append(("info", message))
    await emit_acquisition_event(
        on_event,
        AcquisitionEvent.traversal_settled(
            previous_card_count=int(previous.get("card_count", 0)),
            current_card_count=int(current.get("card_count", 0)),
        ),
    )
    return current


async def advance_paginate(
    page,
    *,
    previous: dict[str, Any],
    result: TraversalResult,
    surface: str,
    deadline_at: float | None,
    on_event,
    visited_urls: set[str],
) -> TraversalStep:
    locator = await find_actionable_locator(page, "next_page")
    if locator is None:
        settled = await settle_thin_initial_listing(
            page,
            previous=previous,
            result=result,
            surface=surface,
            deadline_at=deadline_at,
            on_event=on_event,
        )
        return TraversalStep("settled" if settled else "next_page_not_found", settled)
    result.iterations += 1
    current_url = page.url
    action, intended_url = await _resolve_paginate_target(
        locator,
        current_url=current_url,
        visited_urls=visited_urls,
    )
    if action not in {"navigate", "click"}:
        return TraversalStep(action)
    if action == "navigate" and intended_url is not None:
        timeout_ms = remaining_timeout_ms(
            deadline_at,
            int(crawler_runtime_settings.pagination_navigation_timeout_ms),
            min_ms=5000,
        )
        if timeout_ms <= 0:
            return TraversalStep("budget_exceeded")
        try:
            await page.goto(
                intended_url,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
        except (PlaywrightError, PlaywrightTimeoutError):
            return TraversalStep("paginate_navigation_failed")
        try:
            await wait_for_transition(
                page,
                previous_url=current_url,
                navigation_expected=True,
                deadline_at=deadline_at,
            )
        except (PlaywrightError, PlaywrightTimeoutError):
            return TraversalStep("paginate_transition_timeout")
    else:
        if not await click_with_retry(
            page,
            locator,
            result=result,
            deadline_at=deadline_at,
        ):
            return TraversalStep("paginate_click_failed")
        await wait_for_transition(
            page,
            previous_url=current_url,
            deadline_at=deadline_at,
            timeout_ms=int(
                crawler_runtime_settings.traversal_settle_networkidle_timeout_ms
            ),
        )
    if await page_matches_block_challenge(page):
        return TraversalStep("paginate_blocked")
    resolved_url = page.url
    if _resolved_paginate_cycle(
        resolved_url=resolved_url,
        current_url=current_url,
        intended_url=intended_url,
        visited_urls=visited_urls,
    ):
        return TraversalStep("paginate_cycle_detected")
    visited_urls.add(resolved_url)
    return TraversalStep("ok", await page_snapshot(page, surface=surface))


__all__ = [
    "TraversalGainState",
    "TraversalStep",
    "advance_load_more",
    "advance_paginate",
    "effective_scroll_limit",
    "run_scroll_step",
    "settle_thin_initial_listing",
    "wait_for_load_more_card_gain",
]
