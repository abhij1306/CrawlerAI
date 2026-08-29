from __future__ import annotations

import asyncio
import logging
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.db_utils import mapping_or_empty
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.models.crawl_run import (
    TERMINAL_STATUS_VALUES,
    CrawlRun,
    RunClaimLostError,
    checkpoint_status_stops_run,
    claim_run,
    release_run_lease,
    renew_run_lease,
    run_dispatch_token,
)
from app.crawl.state import (
    CONTROL_REQUEST_KEY,
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    set_control_request,
    update_run_status,
)
from app.crawl.sitemap_resolver import resolve_category_urls_with_site_links
from app.crawl.utils import normalize_target_url
from app.core.config.sitemap import (
    SITEMAP_DEFAULT_FILTER_KEYWORD,
    SITEMAP_DEFAULT_MAX_URLS,
)
from app.core.config.runtime_settings import (
    crawler_runtime_settings,
)
from app.core.config.run_events import RunEventKind
from app.core.domain_utils import normalize_domain
from app.crawl.pipeline.extraction_loop import process_single_url
from app.crawl.pipeline.run_complete_callbacks import on_run_complete
from app.crawl.pipeline.run_progress import (
    BatchRunProgressState,
    ProgressCommitGate,
    load_completed_url_entries,
    seed_progress_from_completed_entries,
)
from app.crawl.pipeline.runtime_helpers import (
    STAGE_ACQUIRE,
    STAGE_PERSIST,
    mark_run_failed,
    set_stage,
)
from app.crawl.run_events import RunEventFact, run_event_timeline, url_scope_id
from app.crawl.pipeline.types import URLProcessingResult
from app.crawl.pipeline.url_failure_recovery import (
    URLProcessingDeadlineExceeded,
    rollback_url_session,
)
from app.crawl.pipeline.url_worker import (
    parallel_url_concurrency,
    parallel_worker_record_limit,
    process_url_in_owned_session,
    should_process_urls_in_parallel,
    url_metric,
)
from app.persistence.publish import VERDICT_ERROR, aggregate_verdict
from app.core.shared.run_summary import as_int
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def resolve_category_urls_from_sitemap(
    domain: str,
    filter_keyword: str,
    max_urls: int,
    allow_homepage_fallback: bool = False,
) -> list[str]:
    result = await resolve_category_urls_with_site_links(
        domain=domain,
        filter_keyword=filter_keyword,
        max_urls=max_urls,
        allow_homepage_fallback=allow_homepage_fallback,
        category_only=True,
    )
    return result.urls


type URLResultItem = tuple[int, str, URLProcessingResult]


def _safe_sitemap_max_urls(value: object) -> int:
    try:
        candidate = value if value not in (None, "") else SITEMAP_DEFAULT_MAX_URLS
        return int(str(candidate))
    except (TypeError, ValueError):
        return SITEMAP_DEFAULT_MAX_URLS


async def _resolve_run_urls(run: CrawlRun, settings_view) -> list[str]:
    urls = settings_view.urls()
    if run.run_type in ("batch", "csv") and urls:
        # CSV ingestion persists parsed URLs, so CSV and batch runs resolve alike.
        url_list = urls
    elif settings_view.get("sitemap_domain"):
        url_list = await resolve_category_urls_from_sitemap(
            domain=settings_view.get("sitemap_domain"),
            filter_keyword=settings_view.get("sitemap_filter_keyword")
            or SITEMAP_DEFAULT_FILTER_KEYWORD,
            max_urls=_safe_sitemap_max_urls(settings_view.get("sitemap_max_urls")),
            allow_homepage_fallback=False,
        )
    elif run.url:
        url_list = [run.url]
    else:
        raise ValueError("No URL provided")
    return [
        value for value in (normalize_target_url(item) for item in url_list) if value
    ]


def _current_duration_ms(run: CrawlRun) -> int:
    if not isinstance(run.created_at, datetime):
        return 0
    return max(0, int((datetime.now(UTC) - run.created_at).total_seconds() * 1000))


async def _run_control_checkpoint(run_id: int) -> tuple[str | None, str | None]:
    """Read (status, control_request) via a short dedicated transaction.

    Replaces per-URL session.refresh(run): only two small values cross the
    wire, and the parent session never sits idle-in-transaction (nor gets its
    ORM state expired by checkpoint rollbacks) across the awaits that follow.
    """
    control_column = CrawlRun.result_summary[CONTROL_REQUEST_KEY].astext
    async with SessionLocal() as checkpoint_session:
        result = await checkpoint_session.execute(
            select(CrawlRun.status, control_column).where(CrawlRun.id == run_id)
        )
        row = result.first()
    if row is None:
        return None, None
    status_value = str(row[0] or "").strip().lower() or None
    control_request = str(row[1] or "").strip().lower() or None
    return status_value, control_request


def _url_timeout_seconds(settings_view) -> float:
    configured_timeout = settings_view.get("url_timeout_seconds")
    if configured_timeout not in (None, ""):
        base_timeout = settings_view.url_timeout_seconds()
        acquisition_timeout = max(
            0.0, float(crawler_runtime_settings.acquisition_attempt_timeout_seconds)
        )
        buffer_seconds = max(
            0.0, float(crawler_runtime_settings.url_process_timeout_buffer_seconds)
        )
        return min(
            base_timeout + acquisition_timeout + buffer_seconds,
            float(crawler_runtime_settings.max_url_process_timeout_seconds),
        )
    base_timeout = crawler_runtime_settings.default_url_process_timeout_seconds()
    # Traversal needs more time than a single-page fetch and extraction.
    traversal_mode = settings_view.traversal_mode()
    if traversal_mode:
        raw_max_pages = settings_view.max_pages()
        raw_max_scrolls = settings_view.max_scrolls()
        max_pages = int(raw_max_pages) if raw_max_pages is not None else 1
        max_scrolls = int(raw_max_scrolls) if raw_max_scrolls is not None else 1
        traversal_pages = max(max_pages, max_scrolls)
        traversal_budget = traversal_pages * 30.0
        extended = base_timeout + traversal_budget
        return min(
            extended, float(crawler_runtime_settings.max_url_process_timeout_seconds)
        )
    return base_timeout


async def _persist_url_failure_event(
    session: AsyncSession,
    *,
    run_id: int,
    url: str,
    url_scope_id: str,
    timeout_seconds: float,
    exc: BaseException,
) -> CrawlRun:
    run = await session.get(CrawlRun, run_id, populate_existing=True)
    if run is None:
        raise RuntimeError(f"Run {run_id} disappeared after URL failure") from exc
    logger.warning(
        "URL processing failed for run=%s url=%s", run_id, url, exc_info=True
    )
    reason_code = (
        "timeout" if isinstance(exc, URLProcessingDeadlineExceeded) else "exception"
    )
    facts: dict[str, str | float] = {"exception_type": type(exc).__name__}
    if reason_code == "timeout":
        facts["timeout_seconds"] = float(timeout_seconds)
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.URL_FAILED,
            url=url,
            url_scope_id=url_scope_id,
            reason_code=reason_code,
            facts=facts,
        ),
    )
    return run


def _url_result_record_count(url_result: URLProcessingResult) -> int:
    return as_int(url_metric(url_result, "record_count", len(url_result.records)))


async def _record_url_result(
    session: AsyncSession,
    *,
    run: CrawlRun,
    progress_state: BatchRunProgressState,
    idx: int,
    url: str,
    url_result: URLProcessingResult,
    owner: str,
    commit_gate: ProgressCommitGate,
) -> tuple[str, int]:
    verdict = str(url_result.verdict or VERDICT_ERROR)
    records_count = _url_result_record_count(url_result)
    final_url = str(url_metric(url_result, "final_url", "") or "").strip()
    completion_facts: dict[str, str | int] = {
        "record_count": records_count,
        "verdict": verdict,
    }
    if final_url:
        completion_facts["final_url"] = final_url
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.URL_COMPLETED,
            url=url,
            url_scope_id=url_scope_id(idx),
            facts=completion_facts,
        ),
    )
    progress_state.record_url_result(
        idx=idx - 1,
        records_count=records_count,
        verdict=verdict,
        url_metrics=url_result.url_metrics,
    )
    if not commit_gate.due():
        # URL session already committed the outcome; summary waits for the next gate.
        return verdict, records_count
    await renew_run_lease(session, run_id=int(run.id), owner=owner)
    # Reload the small summary column to avoid clobbering newer control requests.
    await session.refresh(run, attribute_names=["result_summary"])
    run.update_summary(
        **progress_state.build_progress_patch(
            current_url=url,
            current_url_index=idx,
        ),
        duration_ms=_current_duration_ms(run),
    )
    await session.commit()
    commit_gate.mark_committed()
    return verdict, records_count


async def _apply_control_checkpoint(
    session: AsyncSession,
    run: CrawlRun,
    control_request: str | None,
    *,
    owner: str | None = None,
) -> bool:
    if control_request not in (CONTROL_REQUEST_PAUSE, CONTROL_REQUEST_KILL):
        return False
    if owner is not None and not await release_run_lease(
        session, run_id=int(run.id), owner=owner
    ):
        raise RunClaimLostError(f"Run {int(run.id)} claim lost before checkpoint")
    await session.refresh(
        run, attribute_names=["status", "result_summary", "completed_at"]
    )
    new_status = (
        CrawlStatus.PAUSED
        if control_request == CONTROL_REQUEST_PAUSE
        else CrawlStatus.KILLED
    )
    update_run_status(run, new_status)
    set_control_request(run, None)
    signal_word = "paused" if control_request == CONTROL_REQUEST_PAUSE else "killed"
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.RUN_CONTROL_APPLIED,
            reason_code=signal_word,
        ),
        session=session,
    )
    await session.commit()
    return True


@dataclass(slots=True)
class _ParallelRunState:
    session: AsyncSession
    run: CrawlRun
    pending_items: list[tuple[int, str]]
    total_urls: int
    progress_state: BatchRunProgressState
    max_records: int
    record_limit: int
    url_timeout_seconds: float
    owner: str
    concurrency: int
    commit_gate: ProgressCommitGate
    stop_event: asyncio.Event = field(default_factory=asyncio.Event)
    verdicts: list[str] = field(default_factory=list)
    workers: list[asyncio.Task[None]] = field(default_factory=list)
    record_count: int = 0
    result_queue: asyncio.Queue[URLResultItem] = field(init=False)
    work_iter: Iterator[tuple[int, str]] = field(init=False)

    def __post_init__(self) -> None:
        self.record_count = self.progress_state.persisted_record_count
        size_factor = max(1, crawler_runtime_settings.parallel_result_queue_size_factor)
        self.result_queue = asyncio.Queue(maxsize=self.concurrency * size_factor)
        self.work_iter = iter(self.pending_items)

    def start_workers(self) -> None:
        self.workers = [
            asyncio.create_task(
                self._worker(), name=f"crawl-run-{self.run.id}-worker-{index}"
            )
            for index in range(self.concurrency)
        ]

    async def _worker(self) -> None:
        while not self.stop_event.is_set():
            try:
                idx, url = next(self.work_iter)
            except StopIteration:
                return
            result = await process_url_in_owned_session(
                session_factory=SessionLocal,
                persist_failure_event=_persist_url_failure_event,
                processor=process_single_url,
                run_id=int(self.run.id),
                idx=idx,
                total_urls=self.total_urls,
                url=url,
                max_records=self.record_limit,
                url_timeout_seconds=self.url_timeout_seconds,
            )
            await self.result_queue.put(result)

    async def record_result(self, item: URLResultItem) -> None:
        idx, url, url_result = item
        verdict, records_count = await _record_url_result(
            self.session,
            run=self.run,
            progress_state=self.progress_state,
            idx=idx,
            url=url,
            url_result=url_result,
            owner=self.owner,
            commit_gate=self.commit_gate,
        )
        self.verdicts.append(verdict)
        self.record_count += records_count

    async def drain_results(self) -> None:
        while not self.result_queue.empty():
            await self.record_result(self.result_queue.get_nowait())

    async def stop_and_join(self) -> None:
        self.stop_event.set()
        await self.drain_results()
        await self.cancel_workers()
        await self.drain_results()

    async def cancel_workers(self) -> None:
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)

    def raise_worker_error(self) -> None:
        error = next(
            (
                worker.exception()
                for worker in self.workers
                if worker.done() and not worker.cancelled() and worker.exception()
            ),
            None,
        )
        if error is not None:
            raise error

    async def checkpoint_stops_run(self) -> bool:
        status_value, control_request = await _run_control_checkpoint(int(self.run.id))
        if control_request in (CONTROL_REQUEST_PAUSE, CONTROL_REQUEST_KILL):
            await self.stop_and_join()
            await _apply_control_checkpoint(
                self.session, self.run, control_request, owner=self.owner
            )
            return True
        if checkpoint_status_stops_run(status_value):
            await self.stop_and_join()
            return True
        return False

    async def stop_at_record_limit(self) -> bool:
        if self.record_count < self.max_records:
            return False
        await self.stop_and_join()
        await run_event_timeline.record(
            run_id=self.run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_LIMIT_REACHED,
                facts={"limit_name": "max_records", "limit_value": self.max_records},
            ),
        )
        return True

    async def execute(self) -> tuple[list[str], int]:
        self.start_workers()
        tick_seconds = max(0.05, crawler_runtime_settings.parallel_control_tick_seconds)
        try:
            while not (
                all(worker.done() for worker in self.workers)
                and self.result_queue.empty()
            ):
                try:
                    await self.record_result(
                        await asyncio.wait_for(self.result_queue.get(), tick_seconds)
                    )
                    await self.drain_results()
                except TimeoutError:
                    pass
                self.raise_worker_error()
                if (
                    await self.checkpoint_stops_run()
                    or await self.stop_at_record_limit()
                ):
                    return self.verdicts, self.record_count
        except BaseException:
            self.stop_event.set()
            await self.cancel_workers()
            raise
        self.raise_worker_error()
        return self.verdicts, self.record_count


async def _process_urls_in_parallel(
    session: AsyncSession,
    *,
    run: CrawlRun,
    settings_view,
    pending_items: list[tuple[int, str]],
    total_urls: int,
    progress_state: BatchRunProgressState,
    max_records: int,
    url_timeout_seconds: float,
    owner: str,
) -> tuple[list[str], int]:
    concurrency = parallel_url_concurrency(total_urls, settings_view)
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.RUN_CONCURRENCY_SELECTED,
            facts={"url_count": total_urls, "concurrency": concurrency},
        ),
    )
    return await _ParallelRunState(
        session=session,
        run=run,
        pending_items=pending_items,
        total_urls=total_urls,
        progress_state=progress_state,
        max_records=max_records,
        record_limit=parallel_worker_record_limit(max_records, concurrency),
        url_timeout_seconds=url_timeout_seconds,
        owner=owner,
        concurrency=concurrency,
        commit_gate=ProgressCommitGate(settings.run_progress_commit_interval_seconds),
    ).execute()


async def _record_sequential_url_start(
    session: AsyncSession,
    *,
    run: CrawlRun,
    idx: int,
    total_urls: int,
    url: str,
) -> None:
    del session
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.URL_STARTED,
            url=url,
            url_scope_id=url_scope_id(idx),
            facts={"index": idx, "total": total_urls},
        ),
    )


async def _process_urls_sequential(
    session: AsyncSession,
    *,
    run: CrawlRun,
    pending_items: list[tuple[int, str]],
    total_urls: int,
    progress_state: BatchRunProgressState,
    max_records: int,
    sleep_ms: int,
    url_timeout_seconds: float,
    run_span,
    owner: str,
) -> tuple[list[str], int]:
    verdicts: list[str] = []
    record_count = progress_state.persisted_record_count
    commit_gate = ProgressCommitGate(settings.run_progress_commit_interval_seconds)
    last_pending_idx = pending_items[-1][0] if pending_items else 0
    for idx, url in pending_items:
        status_value, control_request = await _run_control_checkpoint(int(run.id))
        if checkpoint_status_stops_run(status_value):
            return verdicts, record_count
        if await _apply_control_checkpoint(session, run, control_request, owner=owner):
            return verdicts, record_count
        await _record_sequential_url_start(
            session,
            run=run,
            idx=idx,
            total_urls=total_urls,
            url=url,
        )
        await set_stage(
            session,
            run,
            STAGE_ACQUIRE,
            current_url=url,
            current_url_index=idx,
            total_urls=total_urls,
        )
        await session.commit()
        _, _, url_result = await process_url_in_owned_session(
            session_factory=SessionLocal,
            persist_failure_event=_persist_url_failure_event,
            processor=process_single_url,
            run_id=run.id,
            idx=idx,
            total_urls=total_urls,
            url=url,
            max_records=max(max_records - record_count, 1),
            url_timeout_seconds=url_timeout_seconds,
            log_start=False,
        )
        verdict, records_count = await _record_url_result(
            session,
            run=run,
            progress_state=progress_state,
            idx=idx,
            url=url,
            url_result=url_result,
            owner=owner,
            commit_gate=commit_gate,
        )
        verdicts.append(verdict)
        record_count += records_count
        set_logfire_attributes(
            run_span,
            record_count=record_count,
            last_url_verdict=verdict,
        )
        if record_count >= max_records:
            await run_event_timeline.record(
                run_id=run.id,
                fact=RunEventFact(
                    kind=RunEventKind.RUN_LIMIT_REACHED,
                    facts={"limit_name": "max_records", "limit_value": max_records},
                ),
            )
            break
        if sleep_ms > 0 and idx < last_pending_idx:
            await asyncio.sleep(sleep_ms / 1000)
    return verdicts, record_count


async def _finalize_completed_run(
    session: AsyncSession,
    *,
    run: CrawlRun,
    run_span,
    record_count: int,
    progress_state: BatchRunProgressState,
    owner: str,
) -> None:
    status_value, _ = await _run_control_checkpoint(int(run.id))
    if status_value is None or status_value in TERMINAL_STATUS_VALUES:
        return
    final_verdict = aggregate_verdict(progress_state.url_verdicts)
    set_logfire_attributes(run_span, verdict=final_verdict, record_count=record_count)
    # Lease release and terminal write commit atomically; a newer claim owner finalizes instead.
    if not await release_run_lease(session, run_id=int(run.id), owner=owner):
        logger.warning("Run %s lost queue claim before finalization", run.id)
        await session.rollback()
        return
    await session.refresh(run, attribute_names=["status", "result_summary"])
    update_run_status(run, CrawlStatus.COMPLETED)
    run.update_summary(
        **progress_state.build_final_patch(final_verdict),
        current_stage=STAGE_PERSIST,
        duration_ms=_current_duration_ms(run),
    )
    try:
        callback_failure_types = await on_run_complete(run.id)
    except Exception as exc:
        logger.exception("Run-complete callback dispatch failed for run=%s", run.id)
        callback_failure_types = (type(exc).__name__,)
    for exception_type in callback_failure_types:
        callback_failure_event = await run_event_timeline.record(
            run_id=run.id,
            fact=RunEventFact(
                kind=RunEventKind.RUN_CALLBACK_FAILED,
                facts={"exception_type": exception_type},
            ),
            session=session,
        )
        if callback_failure_event is None:
            raise RuntimeError("Run callback failure event could not be persisted")
    completed_event = await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.RUN_COMPLETED,
            facts={"record_count": record_count, "verdict": final_verdict},
        ),
        session=session,
    )
    if completed_event is None:
        raise RuntimeError("Run completion event could not be persisted")
    await session.commit()


async def process_run(session: AsyncSession, run_id: int) -> None:
    with logfire_span("pipeline.run", run_id=run_id) as run_span:
        await _process_run_with_span(session, run_id, run_span)


async def _process_run_with_span(
    session: AsyncSession,
    run_id: int,
    run_span,
) -> None:
    try:
        run = await session.get(CrawlRun, run_id, populate_existing=True)
        if run is None or run.status_value in TERMINAL_STATUS_VALUES:
            return
        set_logfire_attributes(
            run_span,
            surface=run.surface,
            run_type=run.run_type,
            llm_enabled=run.settings_view.llm_enabled(),
        )
        if run.status_value == CrawlStatus.PAUSED:
            return
        # Claim before any work: a redelivery matching a live owner's token is
        # refused; a stale/dead owner's lease may be taken over.
        owner = run_dispatch_token(run)
        if not await claim_run(session, run_id=int(run.id), owner=owner):
            logger.info(
                "Skipping duplicate execution for run=%s: claimed by a live owner",
                run_id,
            )
            await session.rollback()
            return
        if run.status_value == CrawlStatus.PENDING:
            update_run_status(run, CrawlStatus.RUNNING)
        await session.commit()
        settings_view = run.settings_view
        url_list = await _resolve_run_urls(run, settings_view)
        total_urls = len(url_list)
        if total_urls == 0:
            raise ValueError("No URL provided")
        run_domain = normalize_domain(url_list[0]) if url_list else ""
        set_logfire_attributes(run_span, url_count=total_urls, domain=run_domain)

        max_records = settings_view.max_records()
        sleep_ms = settings_view.sleep_ms()
        url_timeout_seconds = _url_timeout_seconds(settings_view)

        progress_state = BatchRunProgressState(
            total_urls=total_urls, url_domain=run_domain
        )
        completed_entries = await load_completed_url_entries(session, run_id)
        pending_items = seed_progress_from_completed_entries(
            progress_state, url_list, completed_entries
        )
        if completed_entries:
            # Re-entry: keep the bounded aggregate summaries from the previous executor.
            progress_state.acquisition_summary = mapping_or_empty(
                run.get_summary("acquisition_summary")
            )
            progress_state.quality_summary = mapping_or_empty(
                run.get_summary("quality_summary")
            )
            logger.info(
                "Resuming run=%s: %s/%s URL(s) already completed",
                run_id,
                progress_state.completed_count,
                total_urls,
            )

        first_pending = pending_items[0] if pending_items else (0, "")
        first_pending_idx, first_pending_url = first_pending
        # Merge into a freshly read summary so externally written control keys are preserved.
        await session.refresh(run, attribute_names=["result_summary"])
        initial_patch = progress_state.build_progress_patch(
            current_url=first_pending_url, current_url_index=first_pending_idx
        )
        run.update_summary(**initial_patch, current_stage=STAGE_ACQUIRE)
        await session.commit()

        if not completed_entries:
            await run_event_timeline.record(
                run_id=run.id,
                fact=RunEventFact(
                    kind=RunEventKind.RUN_STARTED,
                    facts={"seed_url_count": total_urls},
                ),
            )
            await run_event_timeline.record(
                run_id=run.id,
                fact=RunEventFact(
                    kind=RunEventKind.RUN_SEED_URLS_RESOLVED,
                    facts={
                        "seed_url_count": total_urls,
                        "domain_policy": "standard",
                    },
                ),
            )

        if pending_items:
            if should_process_urls_in_parallel(total_urls, settings_view):
                await _process_urls_in_parallel(
                    session,
                    run=run,
                    settings_view=settings_view,
                    pending_items=pending_items,
                    total_urls=total_urls,
                    progress_state=progress_state,
                    max_records=max_records,
                    url_timeout_seconds=url_timeout_seconds,
                    owner=owner,
                )
            else:
                await _process_urls_sequential(
                    session,
                    run=run,
                    pending_items=pending_items,
                    total_urls=total_urls,
                    progress_state=progress_state,
                    max_records=max_records,
                    sleep_ms=sleep_ms,
                    url_timeout_seconds=url_timeout_seconds,
                    run_span=run_span,
                    owner=owner,
                )
        await _finalize_completed_run(
            session,
            run=run,
            run_span=run_span,
            record_count=progress_state.persisted_record_count,
            progress_state=progress_state,
            owner=owner,
        )
    except RunClaimLostError:
        logger.warning(
            "Run=%s lost its queue claim to a newer owner; stopping this execution",
            run_id,
        )
        await rollback_url_session(session, context="run claim lost")
    except (RuntimeError, ValueError, TypeError, SQLAlchemyError) as exc:
        logger.exception("Run-level failure for run=%s", run_id)
        await rollback_url_session(session, context="run failure marking")
        error_msg = f"{type(exc).__name__}: {exc}"
        await mark_run_failed(
            session, run_id, error_msg, exception_type=type(exc).__name__
        )
