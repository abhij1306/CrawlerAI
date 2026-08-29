from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.core.config import settings
from app.models.crawl_run import CrawlRun
from app.acquisition.browser_runtime import shutdown_browser_runtime
from app.core.config.runtime_settings import (
    CELERY_TASK_ID_KEY,
    crawler_runtime_settings,
)
from app.core.config.run_events import RunEventKind
from app.crawl.state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    set_control_request,
    update_run_status,
)
from app.crawl.run_events import RunEventFact, run_event_timeline
from app.persistence.publish import (
    VERDICT_BLOCKED,
    VERDICT_ERROR,
)
from app.workers.base import (
    load_run_with_normalized_status as _load_run_with_normalized_status,
)
from app.workers.base import set_task_id as _set_task_id
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)
_shutdown_after_kill_lock = asyncio.Lock()
_shutdown_after_kill_in_progress = False


def _get_task_id(run: CrawlRun) -> str | None:
    task_id = str(run.get_summary(CELERY_TASK_ID_KEY) or "").strip()
    return task_id or None


def _as_utc_datetime(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _heartbeat_checkpoint(
    *,
    last_heartbeat_at: datetime | None,
    updated_at: datetime | None,
    created_at: datetime | None,
) -> datetime | None:
    return (
        _as_utc_datetime(last_heartbeat_at)
        or _as_utc_datetime(updated_at)
        or _as_utc_datetime(created_at)
    )


def _summary_task_id(summary: object) -> str | None:
    if not isinstance(summary, dict):
        return None
    task_id = str(summary.get(CELERY_TASK_ID_KEY) or "").strip()
    return task_id or None


async def _shutdown_browser_runtime_after_kill() -> None:
    global _shutdown_after_kill_in_progress
    async with _shutdown_after_kill_lock:
        if _shutdown_after_kill_in_progress:
            logger.debug("Browser runtime shutdown after kill already in progress")
            return
        _shutdown_after_kill_in_progress = True
    try:
        await shutdown_browser_runtime()
    except Exception:
        logger.exception("Browser runtime shutdown failed after hard kill")
    finally:
        async with _shutdown_after_kill_lock:
            _shutdown_after_kill_in_progress = False


def _should_recover_stale_run(
    *,
    status: CrawlStatus,
    summary: object,
    last_heartbeat_at: datetime | None,
    updated_at: datetime | None,
    created_at: datetime | None,
    now: datetime | None = None,
) -> bool:
    if status == CrawlStatus.PENDING and _summary_task_id(summary):
        return True
    reference_time = _heartbeat_checkpoint(
        last_heartbeat_at=last_heartbeat_at,
        updated_at=updated_at,
        created_at=created_at,
    )
    if reference_time is None:
        return True
    current_time = now or datetime.now(UTC)
    return (
        current_time - reference_time
    ).total_seconds() >= crawler_runtime_settings.stalled_run_threshold_seconds


async def _recover_stale_local_run(
    session: AsyncSession,
    run_id: int,
    *,
    target_status: CrawlStatus,
    error_message: str,
    extraction_verdict: str,
    reason_code: str,
) -> bool:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return False
    if run.status_value in TERMINAL_STATUSES:
        if _get_task_id(run) is None:
            return False
        _set_task_id(run, None)
        await session.commit()
        return False
    if run.status_value != CrawlStatus.PENDING and target_status == CrawlStatus.KILLED:
        return False
    if run.status_value != CrawlStatus.RUNNING and target_status == CrawlStatus.FAILED:
        return False
    _set_task_id(run, None)
    run.update_summary(
        error=error_message,
        extraction_verdict=extraction_verdict,
    )
    update_run_status(run, target_status)
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.RUN_STALE_RECOVERED,
            reason_code=reason_code,
            facts={"status": target_status.value},
        ),
        session=session,
    )
    await session.commit()
    return True


async def _run_control_update(
    session: AsyncSession,
    run: CrawlRun,
    operation: Callable[[AsyncSession, CrawlRun, CrawlStatus], Awaitable[None]],
) -> CrawlRun:
    run_id = int(run.id)
    loaded_run, current = await _load_run_with_normalized_status(session, run_id)
    await operation(session, loaded_run, current)
    await session.commit()
    await session.refresh(run)
    return run


async def dispatch_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    from app.core.dependencies import get_run_dispatcher

    if not settings.celery_dispatch_enabled:
        await recover_stale_local_runs(session)
    dispatcher = get_run_dispatcher()
    return await dispatcher.dispatch(session, run)


async def pause_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    run_id = int(run.id)
    from app.workers.local_dispatcher import get_live_local_run_task

    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.RUNNING:
            raise ValueError(f"Cannot pause run in state: {retry_run.status}")
        await run_event_timeline.record(
            run_id=retry_run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CONTROL_REQUESTED,
                reason_code="pause",
            ),
            session=retry_session,
        )
        task_id = _get_task_id(retry_run)
        local_task = get_live_local_run_task(run_id)
        if local_task is not None:
            set_control_request(retry_run, CONTROL_REQUEST_PAUSE)
            return
        else:
            if task_id is None:
                raise ValueError("Cannot pause run without an active Celery task id")
            from app.tasks import process_run_task

            process_run_task.app.control.revoke(task_id, terminate=True)
        update_run_status(retry_run, CrawlStatus.PAUSED)
        _set_task_id(retry_run, None)
        await run_event_timeline.record(
            run_id=retry_run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CONTROL_APPLIED,
                reason_code="paused",
            ),
            session=retry_session,
        )

    return await _run_control_update(session, run, _operation)


async def resume_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current != CrawlStatus.PAUSED:
            raise ValueError(f"Cannot resume run in state: {retry_run.status}")
        await run_event_timeline.record(
            run_id=retry_run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CONTROL_REQUESTED,
                reason_code="resume",
            ),
            session=retry_session,
        )
        update_run_status(retry_run, CrawlStatus.RUNNING)
        set_control_request(retry_run, None)
        _set_task_id(retry_run, None)
        await run_event_timeline.record(
            run_id=retry_run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CONTROL_APPLIED,
                reason_code="resumed",
            ),
            session=retry_session,
        )

    updated = await _run_control_update(session, run, _operation)
    return await dispatch_run(session, updated)


async def kill_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    run_id = int(run.id)
    from app.workers.local_dispatcher import (
        clear_local_run_task,
        get_live_local_run_task,
        live_local_run_task_count,
    )

    async def _operation(
        retry_session: AsyncSession, retry_run: CrawlRun, current: CrawlStatus
    ) -> None:
        if current in TERMINAL_STATUSES:
            raise ValueError(f"Cannot kill run in terminal state: {retry_run.status}")
        await run_event_timeline.record(
            run_id=retry_run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CONTROL_REQUESTED,
                reason_code="kill",
            ),
            session=retry_session,
        )
        task_id = _get_task_id(retry_run)
        local_task = get_live_local_run_task(run_id)
        if local_task is not None:
            set_control_request(retry_run, CONTROL_REQUEST_KILL)
            clear_local_run_task(run_id, expected_task=local_task)

            update_run_status(retry_run, CrawlStatus.KILLED)
            _set_task_id(retry_run, None)
            if live_local_run_task_count() == 0:
                await _shutdown_browser_runtime_after_kill()
            await run_event_timeline.record(
                run_id=retry_run.id,
                fact=RunEventFact(
                    kind=RunEventKind.RUN_CONTROL_APPLIED,
                    reason_code="killed",
                ),
                session=retry_session,
            )
            return
        elif task_id:
            from app.tasks import process_run_task

            process_run_task.app.control.revoke(task_id, terminate=True)
        update_run_status(retry_run, CrawlStatus.KILLED)
        _set_task_id(retry_run, None)
        await run_event_timeline.record(
            run_id=retry_run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CONTROL_APPLIED,
                reason_code="killed",
            ),
            session=retry_session,
        )

    return await _run_control_update(session, run, _operation)


async def cancel_run(session: AsyncSession, run: CrawlRun) -> CrawlRun:
    return await kill_run(session, run)


async def recover_stale_local_runs(session: AsyncSession) -> int:
    if settings.celery_dispatch_enabled:
        return 0
    from app.workers.local_dispatcher import clear_local_run_task

    result = await session.execute(
        select(
            CrawlRun.id,
            CrawlRun.status,
            CrawlRun.result_summary,
            CrawlRun.last_heartbeat_at,
            CrawlRun.updated_at,
            CrawlRun.created_at,
        ).where(
            CrawlRun.status.in_(
                [
                    CrawlStatus.PENDING.value,
                    CrawlStatus.RUNNING.value,
                ]
            )
        )
    )
    recovered = 0
    for (
        run_id,
        status_value,
        result_summary,
        last_heartbeat_at,
        updated_at,
        created_at,
    ) in result.all():
        status = CrawlStatus(str(status_value or "").strip().lower())
        if not _should_recover_stale_run(
            status=status,
            summary=result_summary,
            last_heartbeat_at=last_heartbeat_at,
            updated_at=updated_at,
            created_at=created_at,
        ):
            continue
        clear_local_run_task(int(run_id))
        if status == CrawlStatus.PENDING:
            recovered += int(
                await _recover_stale_local_run(
                    session,
                    int(run_id),
                    target_status=CrawlStatus.KILLED,
                    error_message="Local dev runner was interrupted before processing began",
                    extraction_verdict=VERDICT_BLOCKED,
                    reason_code="interrupted_before_start",
                )
            )
            continue
        recovered += int(
            await _recover_stale_local_run(
                session,
                int(run_id),
                target_status=CrawlStatus.FAILED,
                error_message="Local dev runner was interrupted by backend restart or process termination",
                extraction_verdict=VERDICT_ERROR,
                reason_code="interrupted_during_run",
            )
        )
    return recovered
