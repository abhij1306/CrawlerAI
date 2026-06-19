from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any
import asyncio
import logging

from app.acquisition import cookie_store
from app.acquisition.browser_background_tasks import await_without_cancelling
from app.acquisition.browser_pool_spec import persist_context_storage_state
from app.acquisition.browser_proxy_config import normalized_proxy_value
from app.acquisition.browser_storage_state import (
    DOMAIN_STORAGE_PERSIST_ATTR,
    RUN_STORAGE_PERSIST_ATTR,
)
from app.core.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def runtime_page(
    runtime: Any,
    *,
    proxy: str | None = None,
    run_id: int | None = None,
    domain: str | None = None,
    locality_profile: dict[str, object] | None = None,
    allow_storage_state: bool = True,
    phase_timings_ms: dict[str, int] | None = None,
):
    normalized_proxy = normalized_proxy_value(proxy)
    if runtime.launch_proxy is None:
        if normalized_proxy is not None:
            raise RuntimeError("Proxied browser pages require a launch-owned browser runtime")
    elif normalized_proxy not in {None, runtime.launch_proxy}:
        raise RuntimeError("Browser runtime proxy does not match requested proxy")
    runtime.touch()
    slot_acquired = False
    try:
        await runtime._acquire_context_slot(phase_timings_ms=phase_timings_ms)
        slot_acquired = True
        await runtime._ensure_with_timing(phase_timings_ms=phase_timings_ms)
    except BaseException:
        if slot_acquired:
            runtime._semaphore.release()
        raise
    runtime._update_active_contexts(1)
    if runtime._browser is None:
        runtime._update_active_contexts(-1)
        runtime._semaphore.release()
        raise RuntimeError("Browser runtime failed to initialize")

    context = None
    context_release_deferred = False

    def _release_context_capacity_when_closed(task: asyncio.Task[Any]) -> None:
        nonlocal context_release_deferred
        context_release_deferred = True
        task.add_done_callback(lambda _task: runtime._release_context_capacity())

    try:
        context_options = dict(
            runtime._build_context_spec(
                run_id=run_id,
                locality_profile=locality_profile,
            ).context_options
        )
        allow_domain_storage_state = bool(
            allow_storage_state
            and (
                runtime.launch_proxy is None
                or bool(crawler_runtime_settings.browser_proxy_domain_storage_enabled)
            )
        )
        if allow_storage_state:
            await _load_storage_state(
                context_options,
                run_id=run_id,
                domain=domain,
                browser_engine=runtime.browser_engine,
                allow_domain_storage_state=allow_domain_storage_state,
                phase_timings_ms=phase_timings_ms,
            )
        context_open_started_at = time.perf_counter()
        try:
            context, page = await runtime._open_context_page(
                context_options=context_options,
            )
        finally:
            _record_timing(phase_timings_ms, "context_open_ms", context_open_started_at)
        yield page
    finally:
        try:
            if context is not None:
                await _persist_and_close_context(
                    context,
                    run_id=run_id,
                    domain=domain,
                    browser_engine=runtime.browser_engine,
                    allow_domain_storage_state=allow_domain_storage_state,
                    phase_timings_ms=phase_timings_ms,
                    on_pending_done=_release_context_capacity_when_closed,
                )
        finally:
            if not context_release_deferred:
                runtime._release_context_capacity()


async def _load_storage_state(
    context_options: dict[str, Any],
    *,
    run_id: int | None,
    domain: str | None,
    browser_engine: str,
    allow_domain_storage_state: bool,
    phase_timings_ms: dict[str, int] | None,
) -> None:
    started_at = time.perf_counter()
    storage_state = await cookie_store.load_storage_state_for_run(
        run_id,
        browser_engine=browser_engine,
    )
    if not storage_state and allow_domain_storage_state:
        storage_state = await cookie_store.load_storage_state_for_domain(
            domain,
            browser_engine=browser_engine,
        )
    if storage_state:
        context_options["storage_state"] = storage_state
    _record_timing(phase_timings_ms, "storage_state_load_ms", started_at)


async def _persist_and_close_context(
    context: Any,
    *,
    run_id: int | None,
    domain: str | None,
    browser_engine: str,
    allow_domain_storage_state: bool,
    phase_timings_ms: dict[str, int] | None,
    on_pending_done,
) -> None:
    try:
        started_at = time.perf_counter()
        try:
            await persist_context_storage_state(
                context,
                run_id=run_id,
                domain=domain,
                browser_engine=browser_engine,
                persist_run_storage_state=bool(
                    getattr(context, RUN_STORAGE_PERSIST_ATTR, True)
                ),
                persist_domain_storage_state=bool(
                    allow_domain_storage_state
                    and bool(getattr(context, DOMAIN_STORAGE_PERSIST_ATTR, True))
                ),
                timeout_seconds=_browser_context_timeout_seconds(),
            )
        finally:
            _record_timing(phase_timings_ms, "storage_state_persist_ms", started_at)
    finally:
        started_at = time.perf_counter()
        await _close_browser_context_safely(
            context,
            on_pending_done=on_pending_done,
        )
        _record_timing(phase_timings_ms, "context_close_ms", started_at)


async def _close_browser_context_safely(context: Any, *, on_pending_done=None) -> None:
    close_coro = context.close()
    closed = await await_without_cancelling(
        close_coro,
        timeout_seconds=_browser_context_timeout_seconds(),
        on_pending_done=on_pending_done,
    )
    if closed:
        return
    logger.warning(
        "Timed out closing browser context after %.1fs; observing close in background",
        _browser_context_timeout_seconds(),
    )


def _browser_context_timeout_seconds() -> float:
    return max(0.1, float(crawler_runtime_settings.browser_context_timeout_ms) / 1000)


def _record_timing(
    phase_timings_ms: dict[str, int] | None,
    key: str,
    started_at: float,
) -> None:
    if phase_timings_ms is None:
        return
    phase_timings_ms[key] = int(max(0.0, time.perf_counter() - started_at) * 1000)
