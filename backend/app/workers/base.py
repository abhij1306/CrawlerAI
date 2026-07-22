from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.runtime_settings import CELERY_TASK_ID_KEY
from app.crawl.state import CrawlStatus
from app.models.crawl_run import CrawlRun


def set_task_id(run: CrawlRun, task_id: str | None) -> None:
    """Persist or clear the dispatcher task id on the run summary."""
    if task_id:
        run.update_summary(**{CELERY_TASK_ID_KEY: task_id})
    else:
        run.remove_summary_keys(CELERY_TASK_ID_KEY)


async def load_run_with_normalized_status(
    session: AsyncSession, run_id: int
) -> tuple[CrawlRun, CrawlStatus]:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        raise ValueError(f"Run not found: {run_id}")
    return run, run.status_value


@runtime_checkable
class RunDispatcher(Protocol):
    """Protocol for run dispatchers.

    Implementations persist a task_id on the run, enqueue or start execution,
    and return the refreshed CrawlRun instance.

    Transaction semantics: the caller provides the session; implementations
    commit within dispatch to persist the task_id before enqueuing. On failure,
    implementations must roll back or clear the task_id before re-raising.

    Return value: a refreshed CrawlRun instance tied to the same DB row.

    Error behavior: raises ValueError for invalid state (run not found, wrong
    status). Other exceptions indicate infrastructure failures (broker down,
    task creation failed).
    """

    async def dispatch(self, session: AsyncSession, run: CrawlRun) -> CrawlRun:
        raise NotImplementedError
