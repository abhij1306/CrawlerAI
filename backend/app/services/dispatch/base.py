from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRun


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

    async def dispatch(self, session: AsyncSession, run: CrawlRun) -> CrawlRun: ...
