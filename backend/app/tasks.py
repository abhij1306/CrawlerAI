from __future__ import annotations
# pylint: disable=missing-function-docstring

import asyncio
import logging
from typing import Any
import signal
from collections.abc import Callable, Coroutine
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from types import FrameType
from typing import Iterator

from sqlalchemy import select

from app.core.celery_app import celery_app, worker_process_init, worker_process_shutdown
from app.core.config import settings
from app.core.database import SessionLocal, dispose_engine
from app.core.telemetry import install_asyncio_exception_filter
from app.acquisition.browser_runtime import (
    shutdown_browser_runtime,
    shutdown_browser_runtime_sync,
)
from app.crawl.batch_runtime import process_run
from app.core.config.runtime_settings import crawler_runtime_settings
from app.models.crawl_run import TERMINAL_STATUS_VALUES, CrawlRun
from app.persistence.artifacts import ArtifactRepository

logger = logging.getLogger(__name__)
_SignalHandler = Callable[[int, FrameType | None], object]
_SignalPreviousHandler = _SignalHandler | int | None


# Valid when Celery runs with --pool=solo, one active task per worker process.
@dataclass
class _WorkerTaskState:
    worker_loop: asyncio.AbstractEventLoop | None = None
    active_task_loop: asyncio.AbstractEventLoop | None = None
    active_run_task: asyncio.Task[None] | None = None
    termination_requested: bool = False


_WORKER_TASK_STATE = _WorkerTaskState()


def _run_worker_shutdown_step(name: str, action: Callable[[], object]) -> None:
    try:
        action()
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception("Worker shutdown step failed: %s", name)


def _crawl_task_time_limits() -> dict[str, int]:
    hard_limit = max(1, int(crawler_runtime_settings.job_max_wall_seconds))
    soft_limit = max(1, hard_limit - 60) if hard_limit > 60 else hard_limit
    return {"time_limit": hard_limit, "soft_time_limit": soft_limit}


@worker_process_init.connect
def _worker_process_init(**_kwargs) -> None:
    from app.observability.run_report import ensure_run_report_registered

    ensure_run_report_registered()


@worker_process_shutdown.connect
def _worker_process_shutdown(**_kwargs) -> None:
    loop = _WORKER_TASK_STATE.worker_loop
    if loop is None or loop.is_closed():
        _run_worker_shutdown_step("browser runtime", shutdown_browser_runtime_sync)
        return
    _run_worker_shutdown_step(
        "browser runtime", lambda: loop.run_until_complete(shutdown_browser_runtime())
    )
    _run_worker_shutdown_step(
        "database engine", lambda: loop.run_until_complete(dispose_engine())
    )
    _run_worker_shutdown_step(
        "async generators", lambda: loop.run_until_complete(loop.shutdown_asyncgens())
    )
    _run_worker_shutdown_step(
        "default executor",
        lambda: loop.run_until_complete(loop.shutdown_default_executor()),
    )
    asyncio.set_event_loop(None)
    loop.close()
    _WORKER_TASK_STATE.worker_loop = None


async def _run_with_session(run_id: int) -> None:
    async with SessionLocal() as session:
        await process_run(session, run_id)


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


def _shutdown_browser_runtime_before_task_exit(
    loop: asyncio.AbstractEventLoop,
) -> None:
    _run_worker_shutdown_step(
        "browser runtime", lambda: loop.run_until_complete(shutdown_browser_runtime())
    )


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


def _run_coro_in_worker_loop(
    task_name: str, coro_factory: Callable[[], Coroutine[None, None, None]]
) -> None:
    _WORKER_TASK_STATE.termination_requested = False
    loop = _WORKER_TASK_STATE.worker_loop
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _WORKER_TASK_STATE.worker_loop = loop
    asyncio.set_event_loop(loop)
    install_asyncio_exception_filter(loop)
    task = loop.create_task(coro_factory(), name=task_name)
    _WORKER_TASK_STATE.active_task_loop = loop
    _WORKER_TASK_STATE.active_run_task = task
    try:
        loop.run_until_complete(task)
    except asyncio.CancelledError:
        if _WORKER_TASK_STATE.termination_requested:
            _shutdown_browser_runtime_before_task_exit(loop)
            raise SystemExit(0) from None
        raise
    finally:
        _WORKER_TASK_STATE.active_run_task = None
        _WORKER_TASK_STATE.active_task_loop = None


def _run_task_in_worker_loop(run_id: int) -> None:
    _run_coro_in_worker_loop(f"crawl-run-{run_id}", lambda: _run_with_session(run_id))


@celery_app.task(name="crawl.process_run", **_crawl_task_time_limits())
def process_run_task(run_id: int) -> None:
    with _install_task_signal_handlers():
        _run_task_in_worker_loop(run_id)


# Product Intelligence / Data Enrichment jobs run on workers so they survive API
# restarts. No time limits: job wall time is bounded by discovery + the
# candidate poll window / per-product enrichment, not by the crawl wall clock.
# With task_acks_late a worker loss redelivers the task; the service entry
# detects the redelivery of an interrupted run and fails the job cleanly.
@celery_app.task(name="product_intelligence.run_job", bind=True)
def product_intelligence_run_job_task(self, job_id: int) -> None:
    from app.intelligence.service import run_product_intelligence_job

    _run_coro_in_worker_loop(
        f"product-intelligence-job-{job_id}",
        lambda: run_product_intelligence_job(job_id, task_id=self.request.id),
    )


@celery_app.task(name="data_enrichment.run_job", bind=True)
def data_enrichment_run_job_task(self, job_id: int) -> None:
    from app.enrichment.service import run_data_enrichment_job

    _run_coro_in_worker_loop(
        f"data-enrichment-job-{job_id}",
        lambda: run_data_enrichment_job(job_id, task_id=self.request.id),
    )


async def _sweep_run_artifacts() -> None:
    """2.14 retention sweep of runs/{run_id}/ artifact trees.

    Deletes trees whose crawl_runs row is missing, or whose run is terminal
    with updated_at older than the retention window. Non-terminal runs are
    never touched. run_artifacts_retention_days=0 disables the sweep.
    """
    retention_days = int(settings.run_artifacts_retention_days or 0)
    if retention_days <= 0:
        return
    repository = ArtifactRepository(root_dir=settings.artifacts_dir)
    runs_root = repository.root_dir / "runs"
    if not runs_root.is_dir():
        return
    candidate_ids = sorted(
        int(child.name)
        for child in runs_root.iterdir()
        if child.is_dir() and child.name.isdigit()
    )
    if not candidate_ids:
        return
    async with SessionLocal() as session:
        rows = (
            await session.execute(
                select(CrawlRun.id, CrawlRun.status, CrawlRun.updated_at).where(
                    CrawlRun.id.in_(candidate_ids)
                )
            )
        ).all()
    cutoff = datetime.now(UTC) - timedelta(days=retention_days)
    runs_by_id = {int(row[0]): row for row in rows}
    for run_id in candidate_ids:
        if not _artifact_tree_expired(runs_by_id.get(run_id), cutoff=cutoff):
            continue
        await asyncio.to_thread(repository.remove_run_tree, run_id)
        logger.info("Swept artifact tree for run=%s", run_id)


def _artifact_tree_expired(row: Any, *, cutoff: datetime) -> bool:
    if row is None:
        return True
    if str(row[1] or "").strip().lower() not in TERMINAL_STATUS_VALUES:
        return False
    updated_at = row[2]
    if updated_at is not None and updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=UTC)
    return updated_at is not None and updated_at < cutoff


@celery_app.task(name="maintenance.sweep_run_artifacts")
def sweep_run_artifacts_task() -> None:
    _run_coro_in_worker_loop("sweep-run-artifacts", _sweep_run_artifacts)
