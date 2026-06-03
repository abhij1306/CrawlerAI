from __future__ import annotations

import logging
import time
from urllib.parse import urljoin

from app.services.acquisition.dom_runtime import (
    get_page_html,
    wait_for_dom_mutation_settle,
)
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.acquisition.traversal_types import TraversalResult

from app.services.acquisition.traversal_card_counting import (
    count_listing_cards as count_listing_cards,
    is_marginal_card_gain as _is_marginal_card_gain,
    page_snapshot as _page_snapshot,
    paginate_fragment_budget_reached as _paginate_fragment_budget_reached,
    paginate_snapshot_progressed as _paginate_snapshot_progressed,
    snapshot_progressed as _snapshot_progressed,
    target_record_limit_reached as _target_record_limit_reached,
)
from app.services.acquisition.traversal_helpers import (
    append_html_fragment as _append_html_fragment,
    deadline_reached as _deadline_reached,
    emit_event as _emit_event,
    is_same_origin,
    looks_like_paginate_control,
    page_matches_block_challenge as _page_matches_block_challenge,
    remaining_timeout_ms as _remaining_timeout_ms,
    settle_after_action as _settle_after_action,
    wait_for_transition as _wait_for_transition,
)
from app.services.acquisition.traversal_recovery import (
    PlaywrightError,
    _find_actionable_locator,
    click_with_retry,
    dismiss_overlays_if_needed,
    locator_still_resolves,
)

__all__ = [
    "TraversalResult",
    "PlaywrightError",
    "click_with_retry",
    "count_listing_cards",
    "dismiss_overlays_if_needed",
    "execute_listing_traversal",
    "locator_still_resolves",
    "looks_like_paginate_control",
    "wait_for_dom_mutation_settle",
    "wait_for_load_more_card_gain",
]

logger = logging.getLogger(__name__)

def _format_traversal_detection_message(
    *,
    mode: str,
    max_iterations: int,
    max_records: int | None,
) -> str:
    target_suffix = f", target_records={int(max_records)}" if max_records is not None else ""
    safety_suffix = f", safety_cap={max_iterations}"
    return f"Detected listing layout, traversal={mode}{target_suffix}{safety_suffix}"


def _format_traversal_progress_message(
    *,
    label: str,
    step: int,
    step_limit: int,
    previous_count: int,
    current_count: int,
    max_records: int | None,
) -> str:
    _ = step_limit
    target_suffix = f", target_records={int(max_records)}" if max_records is not None else ""
    return (
        f"{label} {step} - "
        f"page_cards={current_count} (prev_page_cards={previous_count})"
        f"{target_suffix}"
    )


def _set_stop_reason(
    result: TraversalResult,
    reason: str,
    *,
    surface: str,
    traversal_mode: str | None = None,
) -> None:
    result.stop_reason = reason
    logger.info(
        "Traversal stop_reason=%s surface=%s requested_mode=%s selected_mode=%s iterations=%s progress_events=%s",
        reason,
        surface,
        traversal_mode or result.requested_mode,
        result.selected_mode,
        result.iterations,
        result.progress_events,
    )


def should_run_traversal(surface: str | None, traversal_mode: str | None) -> bool:
    _ = surface
    normalized_mode = str(traversal_mode or "").strip().lower()
    return normalized_mode in {"scroll", "load_more", "paginate"}


async def execute_listing_traversal(
    page,
    *,
    surface: str,
    traversal_mode: str,
    max_pages: int,
    max_scrolls: int,
    max_records: int | None = None,
    timeout_seconds: float | None = None,
    on_event=None,
) -> TraversalResult:
    normalized_mode = str(traversal_mode or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    result = TraversalResult(requested_mode=normalized_mode)
    if not should_run_traversal(surface, normalized_mode):
        _set_stop_reason(
            result,
            (
                "unsupported_mode"
                if "listing" in normalized_surface and normalized_mode
                else "not_listing_or_disabled"
            ),
            surface=surface,
            traversal_mode=normalized_mode,
        )
        result.html_fragments = [
            (await get_page_html(page, flatten_shadow=False), True)
        ]
        return result

    selected_mode = normalized_mode
    result.selected_mode = selected_mode

    timeout_value: float | None = None
    if timeout_seconds is not None:
        try:
            timeout_value = float(timeout_seconds)
        except (TypeError, ValueError):
            timeout_value = None
    deadline_at = (
        time.monotonic() + timeout_value
        if timeout_value is not None and timeout_value > 0
        else None
    )
    result.activated = True
    if selected_mode == "scroll":
        await _run_scroll_traversal(
            page,
            surface=surface,
            max_scrolls=max_scrolls,
            max_records=max_records,
            result=result,
            deadline_at=deadline_at,
            on_event=on_event,
        )
    elif selected_mode == "load_more":
        await _run_load_more_traversal(
            page,
            surface=surface,
            max_clicks=max(1, int(max_pages)),
            max_records=max_records,
            result=result,
            deadline_at=deadline_at,
            on_event=on_event,
        )
    elif selected_mode == "paginate":
        await _run_paginate_traversal(
            page,
            surface=surface,
            max_pages=max_pages,
            max_records=max_records,
            result=result,
            deadline_at=deadline_at,
            on_event=on_event,
        )
    else:
        _set_stop_reason(result, "unsupported_mode", surface=surface, traversal_mode=normalized_mode)

    if not result.html_fragments:
        await _append_html_fragment(page, result, surface=surface)
    return result


async def _run_scroll_traversal(
    page,
    *,
    surface: str,
    max_scrolls: int,
    max_records: int | None,
    result: TraversalResult,
    deadline_at: float | None,
    on_event,
) -> None:
    max_iterations = int(crawler_runtime_settings.traversal_max_iterations_cap)
    effective_max = max_iterations
    try:
        local_max_scrolls = int(max_scrolls)
    except (TypeError, ValueError):
        local_max_scrolls = 0
    if local_max_scrolls > 0:
        effective_max = min(max_iterations, local_max_scrolls)
    weak_progress_streak = 0
    best_card_gain = 0
    marginal_gain_streak = 0
    await _append_html_fragment(page, result, surface=surface)
    previous = await _page_snapshot(page, surface=surface)
    result.card_count = int(previous.get("card_count", 0))
    await _emit_event(
        on_event,
        "info",
        _format_traversal_detection_message(
            mode="scroll",
            max_iterations=max_iterations,
            max_records=max_records,
        ),
    )
    if _target_record_limit_reached(max_records=max_records, current_count=result.card_count):
        _set_stop_reason(result, "target_records_reached", surface=surface)
        return
    for _ in range(effective_max):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        result.iterations += 1
        result.scroll_iterations += 1
        await page.evaluate(
            """
            () => {
              const root = document.scrollingElement || document.documentElement || document.body;
              root.scrollTo({ top: root.scrollHeight, behavior: "auto" });
            }
            """
        )
        wait_ms = _remaining_timeout_ms(
            deadline_at,
            int(crawler_runtime_settings.scroll_wait_min_ms),
        )
        if wait_ms <= 0:
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        await _settle_after_action(page, deadline_at=deadline_at, timeout_ms=wait_ms)
        current = await _page_snapshot(page, surface=surface)
        current_count = int(current.get("card_count", 0))
        previous_count = int(previous.get("card_count", 0))
        card_gain = max(
            0,
            current_count - previous_count,
        )
        if card_gain > 0:
            best_card_gain = max(best_card_gain, card_gain)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            message = _format_traversal_progress_message(
                label="Scroll",
                step=result.iterations,
                step_limit=effective_max,
                previous_count=previous_count,
                current_count=current_count,
                max_records=max_records,
            )
            result.events.append(("info", message))
            await _emit_event(on_event, "info", message)
            await _append_html_fragment(page, result, surface=surface)
            weak_progress_streak = 0
            if _is_marginal_card_gain(
                card_gain=card_gain,
                best_gain=best_card_gain,
                current_count=int(current.get("card_count", 0)),
            ):
                marginal_gain_streak += 1
            else:
                marginal_gain_streak = 0
        else:
            weak_progress_streak += 1
            marginal_gain_streak = 0
        previous = current
        result.card_count = current["card_count"]
        if _target_record_limit_reached(max_records=max_records, current_count=result.card_count):
            _set_stop_reason(result, "target_records_reached", surface=surface)
            break
        if marginal_gain_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
            _set_stop_reason(result, "marginal_scroll_gain", surface=surface)
            break
        if weak_progress_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
            _set_stop_reason(result, "no_scroll_progress", surface=surface)
            break
    else:
        _set_stop_reason(result, "scroll_limit_reached", surface=surface)
    result.card_count = previous["card_count"]


async def _run_load_more_traversal(
    page,
    *,
    surface: str,
    max_clicks: int,
    max_records: int | None,
    result: TraversalResult,
    deadline_at: float | None,
    on_event,
) -> None:
    _ = max_clicks
    max_iterations = int(crawler_runtime_settings.traversal_max_iterations_cap)
    best_card_gain = 0
    marginal_gain_streak = 0
    await _append_html_fragment(page, result, surface=surface)
    previous = await _page_snapshot(page, surface=surface)
    result.card_count = int(previous.get("card_count", 0))
    await _emit_event(
        on_event,
        "info",
        _format_traversal_detection_message(
            mode="load_more",
            max_iterations=max_iterations,
            max_records=max_records,
        ),
    )
    if _target_record_limit_reached(max_records=max_records, current_count=result.card_count):
        _set_stop_reason(result, "target_records_reached", surface=surface)
        return
    for _ in range(max_iterations):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        locator = await _find_actionable_locator(page, "load_more")
        if locator is None:
            settled = await wait_for_load_more_card_gain(
                page,
                previous=previous,
                surface=surface,
                max_records=max_records,
                deadline_at=deadline_at,
            )
            if settled is not None:
                previous = settled
                result.card_count = int(settled.get("card_count", result.card_count))
                await _append_html_fragment(page, result, surface=surface)
                if _target_record_limit_reached(
                    max_records=max_records,
                    current_count=result.card_count,
                ):
                    _set_stop_reason(result, "target_records_reached", surface=surface)
                    break
            _set_stop_reason(result, "load_more_not_found", surface=surface)
            break
        result.iterations += 1
        result.load_more_clicks += 1
        current_url = page.url
        clicked = await click_with_retry(
            page,
            locator,
            result=result,
            deadline_at=deadline_at,
        )
        if not clicked:
            _set_stop_reason(result, "load_more_click_failed", surface=surface)
            break
        wait_ms = _remaining_timeout_ms(
            deadline_at,
            int(crawler_runtime_settings.load_more_wait_min_ms),
        )
        if wait_ms <= 0:
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        await _wait_for_transition(
            page,
            previous_url=current_url,
            deadline_at=deadline_at,
            timeout_ms=wait_ms,
        )
        current = await _page_snapshot(page, surface=surface)
        if not _snapshot_progressed(previous, current):
            progressed = await wait_for_load_more_card_gain(
                page,
                previous=previous,
                surface=surface,
                max_records=max_records,
                deadline_at=deadline_at,
            )
            if progressed is not None:
                current = progressed
        current_count = int(current.get("card_count", 0))
        previous_count = int(previous.get("card_count", 0))
        card_gain = max(
            0,
            current_count - previous_count,
        )
        if card_gain > 0:
            best_card_gain = max(best_card_gain, card_gain)
        if _snapshot_progressed(previous, current):
            result.progress_events += 1
            message = _format_traversal_progress_message(
                label="Load more",
                step=result.iterations,
                step_limit=max_iterations,
                previous_count=previous_count,
                current_count=current_count,
                max_records=max_records,
            )
            result.events.append(("info", message))
            await _emit_event(on_event, "info", message)
            await _append_html_fragment(page, result, surface=surface)
            if _target_record_limit_reached(
                max_records=max_records,
                current_count=current_count,
            ):
                _set_stop_reason(result, "target_records_reached", surface=surface)
                previous = current
                break
            if _is_marginal_card_gain(
                card_gain=card_gain,
                best_gain=best_card_gain,
                current_count=current_count,
            ):
                marginal_gain_streak += 1
            else:
                marginal_gain_streak = 0
                previous = current
                continue
            if marginal_gain_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
                _set_stop_reason(result, "marginal_load_more_gain", surface=surface)
                previous = current
                break
            previous = current
            continue
        _set_stop_reason(result, "load_more_no_progress", surface=surface)
        previous = current
        break
    else:
        _set_stop_reason(result, "load_more_limit_reached", surface=surface)
    result.card_count = previous["card_count"]


async def wait_for_load_more_card_gain(
    page,
    *,
    previous: dict[str, int],
    surface: str,
    max_records: int | None,
    deadline_at: float | None,
) -> dict[str, int] | None:
    previous_count = int(previous.get("card_count", 0))
    timeout_ms = _remaining_timeout_ms(
        deadline_at,
        int(crawler_runtime_settings.browser_navigation_domcontentloaded_timeout_ms),
    )
    if timeout_ms <= 0:
        return None
    poll_ms = max(1, int(crawler_runtime_settings.pagination_post_click_poll_ms))
    waited_ms = 0
    best: dict[str, int] | None = None
    while waited_ms < timeout_ms:
        step_ms = min(poll_ms, max(1, timeout_ms - waited_ms))
        await page.wait_for_timeout(step_ms)
        waited_ms += step_ms
        current = await _page_snapshot(page, surface=surface)
        current_count = int(current.get("card_count", 0))
        if current_count > previous_count and (
            best is None
            or current_count > int(best.get("card_count", 0))
        ):
            best = current
            if _target_record_limit_reached(
                max_records=max_records,
                current_count=current_count,
            ):
                return best
    return best


async def _run_paginate_traversal(
    page,
    *,
    surface: str,
    max_pages: int,
    max_records: int | None,
    result: TraversalResult,
    deadline_at: float | None,
    on_event,
) -> None:
    _ = max_pages
    previous = await _page_snapshot(page, surface=surface)
    best_card_gain = 0
    marginal_gain_streak = 0
    page_limit = int(crawler_runtime_settings.traversal_max_iterations_cap)
    result.card_count = int(previous["card_count"])
    await _append_html_fragment(page, result, surface=surface)
    await _emit_event(
        on_event,
        "info",
        _format_traversal_detection_message(
            mode="paginate",
            max_iterations=page_limit,
            max_records=max_records,
        ),
    )
    visited_urls: set[str] = {page.url}
    if _target_record_limit_reached(max_records=max_records, current_count=result.card_count):
        _set_stop_reason(result, "target_records_reached", surface=surface)
        return
    for _ in range(max(0, page_limit - 1)):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        locator = await _find_actionable_locator(page, "next_page")
        if locator is None:
            settled = await _settle_thin_initial_listing(
                page,
                previous=previous,
                result=result,
                surface=surface,
                deadline_at=deadline_at,
                on_event=on_event,
            )
            if settled:
                previous = settled
                result.card_count = int(settled.get("card_count", result.card_count))
                continue
            _set_stop_reason(result, "next_page_not_found", surface=surface)
            break
        result.iterations += 1
        current_url = page.url
        intended_url: str | None = None
        href = await locator.get_attribute("href")
        normalized_href = str(href or "").strip().lower()
        if href and not normalized_href.startswith(("#", "javascript:")):
            next_url = urljoin(current_url, href)
            if not is_same_origin(current_url, next_url):
                _set_stop_reason(result, "paginate_off_domain", surface=surface)
                break
            if next_url in visited_urls:
                _set_stop_reason(result, "paginate_cycle_detected", surface=surface)
                break
            intended_url = next_url
            goto_timeout_ms = _remaining_timeout_ms(
                deadline_at,
                int(crawler_runtime_settings.pagination_navigation_timeout_ms),
                min_ms=5000,
            )
            if goto_timeout_ms <= 0:
                _set_stop_reason(result, "budget_exceeded", surface=surface)
                break
            await page.goto(
                next_url,
                wait_until="domcontentloaded",
                timeout=goto_timeout_ms,
            )
            await _wait_for_transition(
                page,
                previous_url=current_url,
                navigation_expected=True,
                deadline_at=deadline_at,
            )
        else:
            clicked = await click_with_retry(
                page,
                locator,
                result=result,
                deadline_at=deadline_at,
            )
            if not clicked:
                _set_stop_reason(result, "paginate_click_failed", surface=surface)
                break
            await _wait_for_transition(
                page,
                previous_url=current_url,
                deadline_at=deadline_at,
                timeout_ms=int(crawler_runtime_settings.traversal_settle_networkidle_timeout_ms),
            )
        if await _page_matches_block_challenge(page):
            _set_stop_reason(result, "paginate_blocked", surface=surface)
            break
        resolved_url = page.url
        # Cycle detection: if the resolved URL is already visited, we've looped.
        # For href-based nav: a server redirect may send us back to a visited URL
        # (resolved_url != intended_url signals the redirect happened).
        # For click-based nav: only flag if the URL actually changed to a visited one
        # (SPAs often keep the same URL, which is not a cycle).
        if resolved_url in visited_urls:
            if intended_url is not None and resolved_url != intended_url:
                _set_stop_reason(result, "paginate_cycle_detected", surface=surface)
                break
            if intended_url is None and resolved_url != current_url:
                _set_stop_reason(result, "paginate_cycle_detected", surface=surface)
                break
        visited_urls.add(resolved_url)
        current = await _page_snapshot(page, surface=surface)
        current_count = int(current.get("card_count", 0))
        previous_count = int(previous.get("card_count", 0))
        card_gain = max(0, current_count - previous_count)
        if card_gain > 0:
            best_card_gain = max(best_card_gain, card_gain)
        if _paginate_snapshot_progressed(previous, current):
            await _append_html_fragment(page, result, surface=surface)
            result.progress_events += 1
            message = _format_traversal_progress_message(
                label="Page",
                step=result.iterations + 1,
                step_limit=page_limit,
                previous_count=previous_count,
                current_count=current_count,
                max_records=max_records,
            )
            result.events.append(("info", message))
            await _emit_event(on_event, "info", message)
            result.pages_advanced += 1
            if _is_marginal_card_gain(
                card_gain=card_gain,
                best_gain=best_card_gain,
                current_count=current_count,
            ):
                marginal_gain_streak += 1
            else:
                marginal_gain_streak = 0
            previous = current
            result.card_count += current_count
            if _target_record_limit_reached(max_records=max_records, current_count=result.card_count):
                _set_stop_reason(result, "target_records_reached", surface=surface)
                break
            if _paginate_fragment_budget_reached(
                result,
                target_records=max_records,
                current_count=result.card_count,
            ):
                _set_stop_reason(
                    result,
                    "paginate_fragment_budget_reached",
                    surface=surface,
                )
                break
            if marginal_gain_streak > int(crawler_runtime_settings.traversal_weak_progress_streak_max):
                _set_stop_reason(result, "marginal_paginate_gain", surface=surface)
                break
            continue
        _set_stop_reason(result, "paginate_no_progress", surface=surface)
        break
    else:
        _set_stop_reason(result, "paginate_limit_reached", surface=surface)

async def _settle_thin_initial_listing(
    page,
    *,
    previous: dict[str, int],
    result: TraversalResult,
    surface: str,
    deadline_at: float | None,
    on_event,
) -> dict[str, int] | None:
    if result.progress_events > 0 or result.iterations > 0:
        return None
    current_count = int(previous.get("card_count", 0))
    if current_count >= max(6, int(crawler_runtime_settings.listing_min_items) * 3):
        return None
    await _settle_after_action(
        page,
        deadline_at=deadline_at,
        timeout_ms=int(crawler_runtime_settings.traversal_settle_networkidle_timeout_ms),
    )
    current = await _page_snapshot(page, surface=surface)
    if not _snapshot_progressed(previous, current):
        return None
    await _append_html_fragment(page, result, surface=surface)
    result.progress_events += 1
    message = (
        "Initial listing settled - "
        f"{previous.get('card_count', 0)} -> {current.get('card_count', 0)} records"
    )
    result.events.append(("info", message))
    await _emit_event(on_event, "info", message)
    return current
