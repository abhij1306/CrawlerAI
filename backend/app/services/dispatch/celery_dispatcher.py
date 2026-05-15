from __future__ import annotations

import logging
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.crawl_run import CrawlRun
from app.services.config.runtime_settings import CELERY_TASK_ID_KEY
from app.services.crawl_state import CrawlStatus
from app.services.dispatch.local_dispatcher import track_local_run_task
from app.tasks import process_run_task

logger = logging.getLogger(__name__)


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


class CeleryRunDispatcher:
    """Dispatches crawl runs via Celery. Falls back to local if configured."""

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
            process_run_task.apply_async(args=[loaded_run.id], task_id=task_id)
        except Exception as exc:
            if not settings.legacy_inprocess_runner_enabled:
                await _clear_task_id(session, loaded_run)
                raise
            logger.warning(
                "Celery enqueue failed for run %s; falling back to in-process execution: %s",
                loaded_run.id,
                exc,
            )
            await _clear_task_id(session, loaded_run)
            track_local_run_task(int(loaded_run.id))
        await session.refresh(loaded_run)
        return loaded_run
