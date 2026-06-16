from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

_popup_guard_tasks: set[asyncio.Task[Any]] = set()
_eviction_cleanup_tasks: set[asyncio.Task[Any]] = set()


def register_popup_guard_task(task: asyncio.Task[Any]) -> None:
    _popup_guard_tasks.add(task)
    task.add_done_callback(_consume_popup_guard_task)


def register_eviction_cleanup_task(task: asyncio.Task[Any]) -> None:
    _eviction_cleanup_tasks.add(task)
    task.add_done_callback(_eviction_cleanup_tasks.discard)
    task.add_done_callback(consume_task_exception)


async def drain_browser_background_tasks() -> None:
    popup_tasks = list(_popup_guard_tasks)
    _popup_guard_tasks.clear()
    for task in popup_tasks:
        if not task.done():
            task.cancel()
    if popup_tasks:
        await asyncio.gather(*popup_tasks, return_exceptions=True)

    eviction_tasks = list(_eviction_cleanup_tasks)
    _eviction_cleanup_tasks.clear()
    if eviction_tasks:
        _done, pending = await asyncio.wait(
            eviction_tasks,
            timeout=max(
                0.1,
                float(crawler_runtime_settings.browser_close_timeout_ms) / 1000,
            ),
        )
        for task in pending:
            task.cancel()
        await asyncio.gather(*eviction_tasks, return_exceptions=True)


def consume_task_exception(task: asyncio.Task[Any]) -> None:
    if task.cancelled():
        return
    try:
        error = task.exception()
    except Exception:
        logger.debug("Browser background task failed", exc_info=True)
        return
    if error is not None:
        logger.debug("Browser background task failed: %s", error, exc_info=error)


async def await_without_cancelling(
    awaitable: Coroutine[Any, Any, Any],
    *,
    timeout_seconds: float,
    on_pending_done: Callable[[asyncio.Task[Any]], None] | None = None,
) -> bool:
    task: asyncio.Task[Any] = asyncio.create_task(awaitable)
    done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
    if not done:
        register_eviction_cleanup_task(task)
        if on_pending_done is not None:
            on_pending_done(task)
        return False
    if task.cancelled():
        return False
    try:
        task.result()
    except Exception:
        consume_task_exception(task)
        return False
    return True


def _consume_popup_guard_task(task: asyncio.Task[Any]) -> None:
    _popup_guard_tasks.discard(task)
    consume_task_exception(task)
