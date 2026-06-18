from __future__ import annotations

import logging
from threading import Lock
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRun
from app.services.config.runtime_settings import CELERY_TASK_ID_KEY
from app.services.crawl.state import CrawlStatus

logger = logging.getLogger(__name__)
process_run_task = None
_process_run_task_lock = Lock()


def _new_task_id(run_id: int) -> str:
    return f"crawl-run-{run_id}-{uuid4().hex}"


def _set_task_id(run: CrawlRun, task_id: str | None) -> None:
    if task_id:
        run.update_summary(**{CELERY_TASK_ID_KEY: task_id})
    else:
        run.remove_summary_keys(CELERY_TASK_ID_KEY)


async def _clear_task_id(session: AsyncSession, run: CrawlRun) -> None:
    """Clear a persisted task_id and commit so the run is safe to re-dispatch."""
    _set_task_id(run, None)
    await session.commit()


async def _load_run_with_normalized_status(
    session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    return run, run.status_value


def _process_run_task():
    global process_run_task
    if process_run_task is not None:
        return process_run_task
    with _process_run_task_lock:
        if process_run_task is None:
            from app.tasks import process_run_task as imported_task

            process_run_task = imported_task
    return process_run_task


class CeleryRunDispatcher:
    """Dispatch crawl runs via Celery."""

    async def dispatch(self, session: AsyncSession, run: CrawlRun) -> CrawlRun:
        loaded_run, current = await _load_run_with_normalized_status(
            session, int(run.id)
        )
        if current not in {CrawlStatus.PENDING, CrawlStatus.RUNNING}:
            raise ValueError(f"Cannot dispatch run in state: {loaded_run.status}")
        task_id = _new_task_id(int(loaded_run.id))
        _set_task_id(loaded_run, task_id)
        await session.commit()
        try:
            _process_run_task().apply_async(args=[loaded_run.id], task_id=task_id)
        except Exception:
            await _clear_task_id(session, loaded_run)
            logger.exception("Celery enqueue failed for run %s", loaded_run.id)
            raise
        await session.refresh(loaded_run)
        return loaded_run
