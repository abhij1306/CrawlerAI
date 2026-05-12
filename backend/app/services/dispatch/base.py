from __future__ import annotations

from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRun


@runtime_checkable
class RunDispatcher(Protocol):
    """Protocol for run dispatchers.

    Implementations persist a task_id on the run, enqueue or start execution,
    and return the refreshed CrawlRun instance. The session is used for DB
    persistence within the dispatch transaction.
    """

    async def dispatch(self, session: AsyncSession, run: CrawlRun) -> CrawlRun: ...
