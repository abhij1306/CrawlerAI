"""Browser context lifecycle for ``SharedBrowserRuntime`` (slots/open/release).

Extracted from ``app.acquisition.browser_pool`` as a cohesive collaborator; the
runtime class keeps thin delegates for the entry points that callers and tests
reference (``_acquire_context_slot``, ``_ensure_with_timing``,
``_open_context_page``, ``_release_context_capacity``,
``_update_active_contexts``). Module-level helpers are resolved through the
``browser_pool`` module object at call time so existing monkeypatch-based tests
keep working against the same module namespace as before the extraction.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Any, cast

from app.acquisition import browser_runtime_lifecycle
from app.acquisition.browser_diagnostics import (
    browser_failure_kind as _browser_failure_kind,
)

if TYPE_CHECKING:
    from patchright.async_api import BrowserContext
    from types import ModuleType

    from app.acquisition.browser_pool import SharedBrowserRuntime

logger = logging.getLogger(__name__)


def _browser_pool() -> ModuleType:
    """Resolve ``browser_pool`` lazily at call time.

    Attributes are looked up on the live module object so monkeypatch-based
    tests keep working, while avoiding a module-level import cycle:
    ``browser_pool`` imports this module at module level.
    """
    from app.acquisition import browser_pool

    return browser_pool


async def open_context_page(
    runtime: SharedBrowserRuntime,
    *,
    context_options: dict[str, Any],
) -> tuple[BrowserContext, Any]:
    last_error: Exception | None = None
    for attempt in range(2):
        if runtime._browser is None:
            raise RuntimeError("Browser runtime failed to initialize")
        context: BrowserContext | None = None
        try:
            context = await _browser_pool()._wait_for_browser_step(
                runtime._browser.new_context(**cast(Any, context_options)),
                timeout_seconds=_browser_pool()._browser_context_timeout_seconds(),
                message="Timed out opening browser context",
            )
            runtime._total_contexts_created += 1
            page = await _browser_pool()._wait_for_browser_step(
                context.new_page(),
                timeout_seconds=_browser_pool()._browser_new_page_timeout_seconds(),
                message="Timed out opening browser page",
            )
            return context, page
        except Exception as exc:
            last_error = exc
            if context is not None:
                await _browser_pool()._close_browser_context_safely(context)
            if attempt >= 1 or _browser_failure_kind(exc) not in {
                "browser_driver_closed",
                "page_closed",
            }:
                raise
            logger.warning(
                "Browser runtime disconnected during context bootstrap; recycling runtime"
            )
            await browser_runtime_lifecycle.recycle_after_driver_disconnect(runtime)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Browser runtime failed to create page context")


async def acquire_context_slot(
    runtime: SharedBrowserRuntime,
    *,
    phase_timings_ms: dict[str, int] | None,
) -> None:
    update_queue_count(runtime, 1)
    slot_timeout_seconds = _browser_pool()._browser_context_slot_timeout_seconds()
    slot_wait_started_at = time.perf_counter()
    slot_deadline = time.monotonic() + slot_timeout_seconds
    slot_acquired = False
    try:
        await asyncio.wait_for(
            runtime._semaphore.acquire(),
            timeout=slot_timeout_seconds,
        )
        slot_acquired = True
        await runtime._yield_slot_until_recycle_window(
            max(0.0, slot_deadline - time.monotonic())
        )
        _browser_pool()._record_timing(
            phase_timings_ms,
            "context_slot_wait_ms",
            slot_wait_started_at,
        )
    except asyncio.TimeoutError as exc:
        _browser_pool()._record_timing(
            phase_timings_ms,
            "context_slot_wait_ms",
            slot_wait_started_at,
        )
        raise asyncio.TimeoutError(
            "Timed out waiting for browser context slot "
            f"after {slot_timeout_seconds:.1f}s"
        ) from exc
    except BaseException:
        if slot_acquired:
            runtime._semaphore.release()
        raise
    finally:
        update_queue_count(runtime, -1)


async def ensure_with_timing(
    runtime: SharedBrowserRuntime,
    *,
    phase_timings_ms: dict[str, int] | None,
) -> None:
    should_time_browser_start = (
        runtime._browser is None
        or browser_runtime_lifecycle.should_recycle_browser(runtime)
    )
    browser_start_started_at = time.perf_counter()
    await browser_runtime_lifecycle.ensure_browser_runtime(runtime)
    if should_time_browser_start:
        _browser_pool()._record_timing(
            phase_timings_ms,
            "browser_start_ms",
            browser_start_started_at,
        )


def release_context_capacity(runtime: SharedBrowserRuntime) -> None:
    update_active_contexts(runtime, -1)
    runtime._semaphore.release()


def update_active_contexts(runtime: SharedBrowserRuntime, delta: int) -> None:
    runtime._active_contexts = max(0, runtime._active_contexts + delta)


def update_queue_count(runtime: SharedBrowserRuntime, delta: int) -> None:
    runtime._queued_count = max(0, runtime._queued_count + delta)
