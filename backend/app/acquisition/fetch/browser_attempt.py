from __future__ import annotations

import asyncio
from collections.abc import Callable, Coroutine
from contextlib import suppress
from typing import Any

from app.acquisition.runtime import PageFetchResult
from app.acquisition.browser_fetch_support import BrowserFetchRequest
from app.core.config.runtime_settings import crawler_runtime_settings


def browser_fetch_request(
    context: Any,
    *,
    proxy: str | None,
    browser_engine: str,
    reason: str,
    escalation_lane: str | None,
    host_policy_snapshot: dict[str, object] | None,
    requested_fields: list[str],
    recovery_mode: str | None,
    capture_screenshot: bool,
) -> BrowserFetchRequest:
    return BrowserFetchRequest(
        url=context.url,
        timeout_seconds=0.0,
        run_id=context.run_id,
        proxy=proxy,
        browser_engine=browser_engine,
        browser_reason=reason,
        escalation_lane=escalation_lane,
        host_policy_snapshot=host_policy_snapshot,
        proxy_profile=context.proxy_profile,
        locality_profile=context.locality_profile,
        surface=context.surface,
        traversal_mode=context.traversal_mode,
        requested_fields=requested_fields,
        listing_recovery_mode=recovery_mode,
        capture_screenshot=capture_screenshot,
        max_pages=context.max_pages,
        max_scrolls=context.max_scrolls,
        max_records=context.max_records,
        on_event=context.on_event,
    )


async def browser_fetch_with_wall_clock_timeout(
    fetcher: Callable[..., Coroutine[Any, Any, PageFetchResult]],
    request: BrowserFetchRequest,
    *,
    browser_engine: str,
) -> PageFetchResult:
    bounded_timeout = max(0.001, float(request.timeout_seconds))
    task: asyncio.Task[PageFetchResult] = asyncio.create_task(fetcher(request))
    done, _pending = await asyncio.wait(
        {task},
        timeout=bounded_timeout,
        return_when=asyncio.FIRST_COMPLETED,
    )
    if task in done:
        return task.result()

    task.cancel()
    cleanup_timeout = max(
        0.1,
        float(crawler_runtime_settings.browser_close_timeout_ms) / 1000,
    )
    with suppress(asyncio.CancelledError, Exception):
        await asyncio.wait_for(asyncio.shield(task), timeout=cleanup_timeout)
    timeout_exc = TimeoutError(
        f"Browser {browser_engine} attempt exceeded timeout_seconds={bounded_timeout:.2f}"
    )
    setattr(timeout_exc, "browser_failure_stage", "attempt")
    raise timeout_exc
