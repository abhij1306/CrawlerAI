from __future__ import annotations

import asyncio

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.product_intelligence import (
    CRAWL_RUN_FINAL_STATUSES,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT,
    product_intelligence_settings,
)
from app.intelligence.service_support import (
    _score_candidate_if_ready,
    _update_job_summary,
)
from app.models.crawl_run import CrawlRun
from app.models.product_intelligence import (
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
)


async def poll_candidates_and_score(
    session: AsyncSession,
    job: ProductIntelligenceJob,
    candidates: list[ProductIntelligenceCandidate],
    *,
    prompt_task_runner=None,
) -> None:
    job_id = int(job.id)
    pending = _pending_candidate_runs(candidates)
    if not pending:
        return
    loop = asyncio.get_running_loop()
    deadline = loop.time() + (
        product_intelligence_settings.candidate_poll_seconds * max(1, len(pending))
    )
    interval = product_intelligence_settings.candidate_poll_interval_seconds
    while pending and loop.time() <= deadline:
        statuses = await _pending_run_statuses(session, pending)
        progressed = await _score_poll_round(
            session,
            job_id=job_id,
            pending=pending,
            status_by_run_id=statuses,
            prompt_task_runner=prompt_task_runner,
        )
        if session.in_transaction():
            await session.commit()
        if progressed:
            await _update_job_summary(session, job)
            await session.commit()
        if pending and loop.time() <= deadline:
            await asyncio.sleep(interval)
    if pending:
        await _mark_pending_candidates_timed_out(
            session, job_id=job_id, candidate_ids=pending
        )


def _pending_candidate_runs(
    candidates: list[ProductIntelligenceCandidate],
) -> dict[int, int | None]:
    return {
        int(candidate.id): (
            int(candidate.candidate_crawl_run_id)
            if candidate.candidate_crawl_run_id is not None
            else None
        )
        for candidate in candidates
    }


async def _pending_run_statuses(
    session: AsyncSession, pending: dict[int, int | None]
) -> dict[int, str]:
    run_ids = [run_id for run_id in pending.values() if run_id is not None]
    if not run_ids:
        return {}
    return {
        int(run_id): str(run_status)
        for run_id, run_status in (
            await session.execute(
                select(CrawlRun.id, CrawlRun.status).where(CrawlRun.id.in_(run_ids))
            )
        ).all()
    }


async def _score_poll_round(
    session: AsyncSession,
    *,
    job_id: int,
    pending: dict[int, int | None],
    status_by_run_id: dict[int, str],
    prompt_task_runner=None,
) -> bool:
    progressed = False
    for candidate_id, run_id in list(pending.items()):
        if run_id is None:
            continue
        run_status = status_by_run_id.get(run_id)
        if run_status is not None and run_status not in CRAWL_RUN_FINAL_STATUSES:
            continue
        await session.get(CrawlRun, run_id, populate_existing=True)
        job = await session.get(ProductIntelligenceJob, job_id)
        candidate = await session.get(ProductIntelligenceCandidate, candidate_id)
        if job is None or candidate is None:
            pending.pop(candidate_id, None)
            continue
        if await _score_candidate_if_ready(
            session,
            job,
            candidate,
            prompt_task_runner=prompt_task_runner,
        ):
            progressed = True
            pending.pop(candidate_id, None)
    return progressed


async def _mark_pending_candidates_timed_out(
    session: AsyncSession, *, job_id: int, candidate_ids: dict[int, int | None]
) -> None:
    job = await session.get(ProductIntelligenceJob, job_id)
    for candidate_id in candidate_ids:
        candidate = await session.get(ProductIntelligenceCandidate, candidate_id)
        if candidate is not None:
            candidate.status = PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT
    if job is not None:
        await _update_job_summary(session, job)
    await session.commit()
