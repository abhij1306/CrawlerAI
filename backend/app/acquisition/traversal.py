from __future__ import annotations

import logging
import time
from typing import Any

from app.acquisition.dom_runtime import (
    get_page_html,
    wait_for_dom_mutation_settle,
)
from app.core.config.runtime_settings import crawler_runtime_settings
from app.acquisition.traversal_types import TraversalResult

from app.acquisition.traversal_card_counting import (
    count_listing_cards as count_listing_cards,
    page_snapshot as _page_snapshot,
    paginate_fragment_budget_reached as _paginate_fragment_budget_reached,
    paginate_snapshot_progressed as _paginate_snapshot_progressed,
    snapshot_progressed as _snapshot_progressed,
    target_record_limit_reached as _target_record_limit_reached,
)
from app.acquisition.traversal_helpers import (
    append_html_fragment as _append_html_fragment,
    deadline_reached as _deadline_reached,
    emit_event as _emit_event,
    looks_like_paginate_control,
)
from app.acquisition.traversal_recovery import (
    PlaywrightError,
    click_with_retry,
    dismiss_overlays_if_needed,
    locator_still_resolves,
)
from app.acquisition.traversal_steps import (
    TraversalGainState as _TraversalGainState,
    advance_load_more as _advance_load_more,
    advance_paginate as _advance_paginate,
    effective_scroll_limit as _effective_scroll_limit,
    run_scroll_step as _run_scroll_step,
    wait_for_load_more_card_gain,
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


def _observe_unique_cards(
    result: TraversalResult,
    snapshot: dict[str, Any],
    *,
    additive_fallback: bool = False,
) -> dict[str, Any]:
    """Convert a page snapshot into total unique cards observed by traversal."""

    observed = dict(snapshot)
    identities = {
        str(identity or "").strip()
        for identity in observed.get("card_identities", ()) or ()
        if str(identity or "").strip()
    }
    if identities:
        result._seen_card_identities.update(identities)
        total = len(result._seen_card_identities)
    elif additive_fallback:
        total = result.card_count + max(0, int(observed.get("card_count", 0)))
    else:
        total = max(result.card_count, int(observed.get("card_count", 0)))
    result.card_count = total
    observed["card_count"] = total
    return observed


def _format_traversal_detection_message(
    *,
    mode: str,
    max_iterations: int,
    max_records: int | None,
) -> str:
    target_suffix = (
        f", target_records={int(max_records)}" if max_records is not None else ""
    )
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
    target_suffix = (
        f", target_records={int(max_records)}" if max_records is not None else ""
    )
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
        _set_stop_reason(
            result, "unsupported_mode", surface=surface, traversal_mode=normalized_mode
        )

    if not result.html_fragments:
        await _append_html_fragment(page, result, surface=surface)
    return result


async def _record_traversal_progress(
    page,
    *,
    result: TraversalResult,
    surface: str,
    on_event,
    label: str,
    step: int,
    step_limit: int,
    previous: dict[str, Any],
    current: dict[str, Any],
    max_records: int | None,
) -> int:
    previous_count = int(previous.get("card_count", 0))
    current_count = int(current.get("card_count", 0))
    result.progress_events += 1
    message = _format_traversal_progress_message(
        label=label,
        step=step,
        step_limit=step_limit,
        previous_count=previous_count,
        current_count=current_count,
        max_records=max_records,
    )
    result.events.append(("info", message))
    await _emit_event(on_event, "info", message)
    await _append_html_fragment(page, result, surface=surface)
    return max(0, current_count - previous_count)


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
    effective_max = _effective_scroll_limit(max_scrolls)
    gain_state = _TraversalGainState()
    await _append_html_fragment(page, result, surface=surface)
    previous = _observe_unique_cards(
        result, await _page_snapshot(page, surface=surface)
    )
    await _emit_event(
        on_event,
        "info",
        _format_traversal_detection_message(
            mode="scroll",
            max_iterations=max_iterations,
            max_records=max_records,
        ),
    )
    if _target_record_limit_reached(
        max_records=max_records, current_count=result.card_count
    ):
        _set_stop_reason(result, "target_records_reached", surface=surface)
        return
    for _ in range(effective_max):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        result.iterations += 1
        result.scroll_iterations += 1
        step = await _run_scroll_step(
            page,
            surface=surface,
            deadline_at=deadline_at,
        )
        if step.status != "ok" or step.snapshot is None:
            _set_stop_reason(result, step.status, surface=surface)
            break
        current = _observe_unique_cards(result, step.snapshot)
        if _snapshot_progressed(previous, current):
            card_gain = await _record_traversal_progress(
                page,
                result=result,
                surface=surface,
                on_event=on_event,
                label="Scroll",
                step=result.iterations,
                step_limit=effective_max,
                previous=previous,
                current=current,
                max_records=max_records,
            )
            gain_state.record_progress(
                card_gain=card_gain,
                current_count=int(current.get("card_count", 0)),
            )
        else:
            gain_state.record_no_progress()
        previous = current
        if _target_record_limit_reached(
            max_records=max_records, current_count=result.card_count
        ):
            _set_stop_reason(result, "target_records_reached", surface=surface)
            break
        weak_limit = int(crawler_runtime_settings.traversal_weak_progress_streak_max)
        if gain_state.marginal_gain_streak > weak_limit:
            _set_stop_reason(result, "marginal_scroll_gain", surface=surface)
            break
        if gain_state.weak_progress_streak > weak_limit:
            _set_stop_reason(result, "no_scroll_progress", surface=surface)
            break
    else:
        _set_stop_reason(result, "scroll_limit_reached", surface=surface)
    result.card_count = int(previous.get("card_count", result.card_count))


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
    del max_clicks
    max_iterations = int(crawler_runtime_settings.traversal_max_iterations_cap)
    gain_state = _TraversalGainState()
    await _append_html_fragment(page, result, surface=surface)
    previous = _observe_unique_cards(
        result, await _page_snapshot(page, surface=surface)
    )
    await _emit_event(
        on_event,
        "info",
        _format_traversal_detection_message(
            mode="load_more",
            max_iterations=max_iterations,
            max_records=max_records,
        ),
    )
    if _target_record_limit_reached(
        max_records=max_records, current_count=result.card_count
    ):
        _set_stop_reason(result, "target_records_reached", surface=surface)
        return
    for _ in range(max_iterations):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        step = await _advance_load_more(
            page,
            previous=previous,
            surface=surface,
            max_records=max_records,
            result=result,
            deadline_at=deadline_at,
        )
        if step.status != "ok" or step.snapshot is None:
            if step.snapshot is not None:
                previous = _observe_unique_cards(result, step.snapshot)
                await _append_html_fragment(page, result, surface=surface)
                if _target_record_limit_reached(
                    max_records=max_records,
                    current_count=result.card_count,
                ):
                    _set_stop_reason(result, "target_records_reached", surface=surface)
                    break
            _set_stop_reason(result, step.status, surface=surface)
            break
        current = _observe_unique_cards(result, step.snapshot)
        if not _snapshot_progressed(previous, current):
            _set_stop_reason(result, "load_more_no_progress", surface=surface)
            previous = current
            break
        card_gain = await _record_traversal_progress(
            page,
            result=result,
            surface=surface,
            on_event=on_event,
            label="Load more",
            step=result.iterations,
            step_limit=max_iterations,
            previous=previous,
            current=current,
            max_records=max_records,
        )
        current_count = int(current.get("card_count", 0))
        gain_state.record_progress(card_gain=card_gain, current_count=current_count)
        previous = current
        if _target_record_limit_reached(
            max_records=max_records, current_count=current_count
        ):
            _set_stop_reason(result, "target_records_reached", surface=surface)
            break
        if gain_state.marginal_gain_streak > int(
            crawler_runtime_settings.traversal_weak_progress_streak_max
        ):
            _set_stop_reason(result, "marginal_load_more_gain", surface=surface)
            break
    else:
        _set_stop_reason(result, "load_more_limit_reached", surface=surface)
    result.card_count = int(previous.get("card_count", result.card_count))


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
    del max_pages
    previous = _observe_unique_cards(
        result, await _page_snapshot(page, surface=surface)
    )
    gain_state = _TraversalGainState()
    page_limit = int(crawler_runtime_settings.traversal_max_iterations_cap)
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
    if _target_record_limit_reached(
        max_records=max_records, current_count=result.card_count
    ):
        _set_stop_reason(result, "target_records_reached", surface=surface)
        return
    for _ in range(max(0, page_limit - 1)):
        if _deadline_reached(deadline_at):
            _set_stop_reason(result, "budget_exceeded", surface=surface)
            break
        step = await _advance_paginate(
            page,
            previous=previous,
            result=result,
            surface=surface,
            deadline_at=deadline_at,
            on_event=on_event,
            visited_urls=visited_urls,
        )
        if step.status == "settled" and step.snapshot is not None:
            previous = _observe_unique_cards(result, step.snapshot)
            continue
        if step.status != "ok" or step.snapshot is None:
            _set_stop_reason(result, step.status, surface=surface)
            break
        current = _observe_unique_cards(result, step.snapshot, additive_fallback=True)
        if not _paginate_snapshot_progressed(previous, current):
            _set_stop_reason(result, "paginate_no_progress", surface=surface)
            break
        card_gain = await _record_traversal_progress(
            page,
            result=result,
            surface=surface,
            on_event=on_event,
            label="Page",
            step=result.iterations + 1,
            step_limit=page_limit,
            previous=previous,
            current=current,
            max_records=max_records,
        )
        current_count = int(current.get("card_count", 0))
        gain_state.record_progress(card_gain=card_gain, current_count=current_count)
        result.pages_advanced += 1
        previous = current
        if _target_record_limit_reached(
            max_records=max_records, current_count=result.card_count
        ):
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
        if gain_state.marginal_gain_streak > int(
            crawler_runtime_settings.traversal_weak_progress_streak_max
        ):
            _set_stop_reason(result, "marginal_paginate_gain", surface=surface)
            break
    else:
        _set_stop_reason(result, "paginate_limit_reached", surface=surface)
