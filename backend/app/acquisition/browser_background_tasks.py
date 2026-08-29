from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine
from typing import Any

from app.core.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

_popup_guard_tasks: set[asyncio.Task[Any]] = set()
_eviction_cleanup_tasks: set[asyncio.Task[Any]] = set()
_bounded_cleanup_tasks: set[asyncio.Task[Any]] = set()
_runtime_close_tasks: set[asyncio.Task[Any]] = set()


def register_popup_guard_task(task: asyncio.Task[Any]) -> None:
    _popup_guard_tasks.add(task)
    task.add_done_callback(_consume_popup_guard_task)


def register_eviction_cleanup_task(task: asyncio.Task[Any]) -> None:
    _eviction_cleanup_tasks.add(task)
    task.add_done_callback(_eviction_cleanup_tasks.discard)
    task.add_done_callback(consume_task_exception)


def _register_cleanup_task(task: asyncio.Task[Any], *, preserve: bool) -> None:
    tasks = _runtime_close_tasks if preserve else _bounded_cleanup_tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)
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
        await asyncio.gather(*eviction_tasks, return_exceptions=True)

    bounded_tasks = list(_bounded_cleanup_tasks)
    _bounded_cleanup_tasks.clear()
    for task in bounded_tasks:
        if not task.done():
            task.cancel()
    if bounded_tasks:
        await asyncio.gather(*bounded_tasks, return_exceptions=True)

    runtime_close_tasks = list(_runtime_close_tasks)
    _runtime_close_tasks.clear()
    if runtime_close_tasks:
        timeout_seconds = max(
            0.001,
            float(crawler_runtime_settings.browser_close_timeout_ms) / 1000.0,
        )
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        _done, pending = await asyncio.wait(
            runtime_close_tasks,
            timeout=timeout_seconds,
        )
        for task in pending:
            task.cancel()
        if pending:
            remaining = max(0.0, deadline - asyncio.get_running_loop().time())
            if remaining:
                _done, pending = await asyncio.wait(pending, timeout=remaining)
            else:
                await asyncio.sleep(0)
                pending = {task for task in pending if not task.done()}
        if pending:
            _runtime_close_tasks.update(pending)
            logger.warning(
                "%d browser runtime close task(s) ignored cancellation",
                len(pending),
            )


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
    preserve_pending: bool = False,
) -> bool:
    task: asyncio.Task[Any] = asyncio.create_task(awaitable)
    try:
        done, _pending = await asyncio.wait({task}, timeout=timeout_seconds)
    except asyncio.CancelledError:
        if task.done():
            consume_task_exception(task)
        else:
            _register_cleanup_task(task, preserve=preserve_pending)
            if on_pending_done is not None:
                on_pending_done(task)
        raise
    if not done:
        _register_cleanup_task(task, preserve=preserve_pending)
        if on_pending_done is not None:
            on_pending_done(task)
        return False
    if task.cancelled():
        return False
    try:
        task.result()
    except Exception:  # noqa: BLE001 - task result may contain any driver failure
        consume_task_exception(task)
        return False
    return True


def _consume_popup_guard_task(task: asyncio.Task[Any]) -> None:
    _popup_guard_tasks.discard(task)
    consume_task_exception(task)
