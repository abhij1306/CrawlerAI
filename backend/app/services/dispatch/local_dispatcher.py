from __future__ import annotations

import asyncio
import logging
import weakref
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SessionLocal
from app.models.crawl_run import CrawlRun
from app.services._batch_runtime import process_run as _batch_process_run
from app.services.config.runtime_settings import CELERY_TASK_ID_KEY
from app.services.crawl_state import CrawlStatus
from app.services.pipeline.runtime_helpers import mark_run_failed

logger = logging.getLogger(__name__)

_local_run_tasks: weakref.WeakValueDictionary[int, asyncio.Task[None]] = (
    weakref.WeakValueDictionary()
)


def _new_task_id(run_id: int) -> str:
    return f"crawl-run-{run_id}-{uuid4().hex}"


def _set_task_id(run: CrawlRun, task_id: str | None) -> None:
    if task_id:
        run.update_summary(**{CELERY_TASK_ID_KEY: task_id})
    else:
        run.remove_summary_keys(CELERY_TASK_ID_KEY)


def get_live_local_run_task(run_id: int) -> asyncio.Task[None] | None:
    task = _local_run_tasks.get(run_id)
    if task is None:
        return None
    if task.done():
        _local_run_tasks.pop(run_id, None)
        return None
    return task


def clear_local_run_task(
    run_id: int, *, expected_task: asyncio.Task[None] | None = None
) -> None:
    task = _local_run_tasks.get(run_id)
    if task is None:
        return
    if expected_task is not None and task is not expected_task:
        return
    _local_run_tasks.pop(run_id, None)
    if not task.done():
        task.cancel()


async def _run_with_local_session(run_id: int) -> None:
    async with SessionLocal() as session:
        try:
            await _batch_process_run(session, run_id)
        except Exception as exc:
            logger.error(
                "Local crawl task failed for run %s",
                run_id,
                exc_info=(type(exc), exc, exc.__traceback__),
            )
            try:
                await mark_run_failed(session, run_id, f"{type(exc).__name__}: {exc}")
            except Exception:
                logger.exception(
                    "Failed to persist failed status for run %s after process_run error",
                    run_id,
                )
            raise


def track_local_run_task(run_id: int) -> asyncio.Task[None]:
    clear_local_run_task(run_id)
    task = asyncio.create_task(_run_with_local_session(run_id))
    _local_run_tasks[run_id] = task

    def _cleanup(completed_task: asyncio.Task[None]) -> None:
        try:
            exc = completed_task.exception()
        except asyncio.CancelledError:
            exc = None
        except Exception:
            logger.exception(
                "Failed to inspect local crawl task completion for run %s", run_id
            )
            exc = None
        if exc is not None:
            logger.debug(
                "Local crawl task failure already persisted for run %s", run_id
            )
        clear_local_run_task(run_id, expected_task=completed_task)

    task.add_done_callback(_cleanup)
    return task


async def _load_run_with_normalized_status(
    session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    return run, run.status_value


class LocalRunDispatcher:
    """Dispatches crawl runs as in-process asyncio tasks."""

    async def dispatch(self, session: AsyncSession, run: CrawlRun) -> CrawlRun:
        from app.services.crawl_service import recover_stale_local_runs

        await recover_stale_local_runs(session)
        run_id = int(run.id)
        loaded_run, current = await _load_run_with_normalized_status(
            session, run_id
        )
        if current not in {CrawlStatus.PENDING, CrawlStatus.RUNNING}:
            raise ValueError(f"Cannot dispatch run in state: {current.value}")
        task_id = _new_task_id(run_id)
        _set_task_id(loaded_run, task_id)
        await session.commit()
        await session.refresh(loaded_run)
        track_local_run_task(run_id)
        return loaded_run
