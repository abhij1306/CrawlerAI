from __future__ import annotations

import asyncio
import logging
import signal
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from types import FrameType
from typing import Iterator

from app.core.celery_app import celery_app, worker_process_init, worker_process_shutdown
from app.core.database import SessionLocal
from app.core.telemetry import install_asyncio_exception_filter
from app.services.acquisition import shutdown_browser_runtime_sync
from app.services.crawl.batch_runtime import process_run as process_run_async
from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)
_SignalHandler = Callable[[int, FrameType | None], object]
_SignalPreviousHandler = _SignalHandler | int | None


@dataclass
class _WorkerTaskState:
    active_task_loop: asyncio.AbstractEventLoop | None = None
    active_run_task: asyncio.Task[None] | None = None
    termination_requested: bool = False


_WORKER_TASK_STATE = _WorkerTaskState()


def _crawl_task_time_limits() -> dict[str, int]:
    hard_limit = max(1, int(crawler_runtime_settings.job_max_wall_seconds))
    soft_limit = max(1, hard_limit - 60) if hard_limit > 60 else hard_limit
    return {"time_limit": hard_limit, "soft_time_limit": soft_limit}


@worker_process_init.connect
def _worker_process_init(**_kwargs) -> None:
    return None


@worker_process_shutdown.connect
def _worker_process_shutdown(**_kwargs) -> None:
    shutdown_browser_runtime_sync()


async def _run_with_session(run_id: int) -> None:
    from app.services.monitor_change_detection import ensure_monitor_change_detection_registered
    from app.services.observability.run_audit import ensure_run_audit_registered

    ensure_monitor_change_detection_registered()
    ensure_run_audit_registered()
    async with SessionLocal() as session:
        await process_run_async(session, run_id)


def _task_termination_handler(signum: int, _frame: FrameType | None) -> None:
    _WORKER_TASK_STATE.termination_requested = True
    logger.warning(
        "Received signal %s while processing crawl task; cancelling async run", signum
    )
    loop = _WORKER_TASK_STATE.active_task_loop
    task = _WORKER_TASK_STATE.active_run_task
    if loop is None or task is None or loop.is_closed() or task.done():
        return
    loop.call_soon_threadsafe(task.cancel)


@contextmanager
def _install_task_signal_handlers() -> Iterator[dict[int, _SignalPreviousHandler]]:
    previous_handlers: dict[int, _SignalPreviousHandler] = {}
    for signame in ("SIGTERM", "SIGINT"):
        signum = getattr(signal, signame, None)
        if signum is None:
            continue
        previous_handlers[int(signum)] = signal.getsignal(signum)
        signal.signal(signum, _task_termination_handler)
    try:
        yield previous_handlers
    finally:
        for signum, previous in previous_handlers.items():
            signal.signal(signum, signal.SIG_DFL if previous is None else previous)


def _run_task_in_worker_loop(run_id: int) -> None:
    _WORKER_TASK_STATE.termination_requested = False
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    install_asyncio_exception_filter(loop)
    task = loop.create_task(_run_with_session(run_id), name=f"crawl-run-{run_id}")
    _WORKER_TASK_STATE.active_task_loop = loop
    _WORKER_TASK_STATE.active_run_task = task
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        if _WORKER_TASK_STATE.termination_requested:
            shutdown_browser_runtime_sync()
            raise SystemExit(0) from None
        raise
    finally:
        _WORKER_TASK_STATE.active_run_task = None
        _WORKER_TASK_STATE.active_task_loop = None
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            try:
                loop.run_until_complete(loop.shutdown_default_executor())
            except RuntimeError:
                logger.warning("Failed to shutdown default executor", exc_info=True)
            finally:
                asyncio.set_event_loop(None)
                loop.close()


@celery_app.task(name="crawl.process_run", **_crawl_task_time_limits())
def process_run_task(run_id: int) -> None:
    with _install_task_signal_handlers():
        _run_task_in_worker_loop(run_id)


async def _run_monitor_check_due_jobs() -> None:
    from app.services.monitor_scheduler_service import MonitorSchedulerService

    await MonitorSchedulerService().check_due_jobs()


async def _run_monitor_purge_expired() -> None:
    from app.services.monitor_retention import MonitorRetentionService

    await MonitorRetentionService().purge_expired()


@celery_app.task(name="monitor.check_due_jobs")
def celery_check_due_jobs() -> None:
    asyncio.run(_run_monitor_check_due_jobs())


@celery_app.task(name="monitor.purge_expired_snapshots")
def celery_purge_expired() -> None:
    asyncio.run(_run_monitor_purge_expired())
