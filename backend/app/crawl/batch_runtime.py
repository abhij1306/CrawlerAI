from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import UTC, datetime

from app.core.config import settings
from app.core.database import SessionLocal
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.models.crawl_run import CrawlRun
from app.crawl.state import (
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    TERMINAL_STATUSES,
    CrawlStatus,
    get_control_request,
    set_control_request,
    update_run_status,
)
from app.crawl.sitemap_resolver import resolve_category_urls_with_site_links
from app.crawl.utils import normalize_target_url, parse_csv_urls_async
from app.core.config.sitemap import (
    SITEMAP_DEFAULT_FILTER_KEYWORD,
    SITEMAP_DEFAULT_MAX_URLS,
)
from app.core.config.runtime_settings import (
    BROWSER_CONCURRENCY_EXEMPT_FETCH_MODES,
    crawler_runtime_settings,
)
from app.core.domain_utils import normalize_domain
from app.crawl.pipeline.extraction_loop import process_single_url
from app.crawl.pipeline.run_complete_callbacks import on_run_complete
from app.crawl.pipeline.run_progress import BatchRunProgressState
from app.crawl.pipeline.runtime_helpers import (
    STAGE_ACQUIRE,
    STAGE_PERSIST,
    log_event,
    mark_run_failed,
    set_stage,
)
from app.crawl.pipeline.types import URLProcessingResult
from app.crawl.pipeline.url_failure_recovery import rollback_url_session
from app.crawl.pipeline.url_worker import (
    process_url_in_owned_session,
    url_metric,
)
from app.persistence.publish import VERDICT_ERROR, aggregate_verdict
from app.persistence.run_summary import as_int
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


_DEFAULT_URL_CONCURRENCY = 1


async def _prewarm_browser_pool() -> None:
    return None


def _parallel_url_concurrency(total_urls: int, settings_view) -> int:
    if not bool(settings.celery_dispatch_enabled):
        return _DEFAULT_URL_CONCURRENCY
    try:
        system_limit = int(
            getattr(settings, "system_max_concurrent_urls", _DEFAULT_URL_CONCURRENCY)
        )
    except (AttributeError, TypeError, ValueError):
        system_limit = _DEFAULT_URL_CONCURRENCY
    try:
        url_batch_concurrency = getattr(settings_view, "url_batch_concurrency", None)
        raw_batch_limit = (
            url_batch_concurrency()
            if callable(url_batch_concurrency)
            else url_batch_concurrency
        )
        if raw_batch_limit is None:
            raw_batch_limit = _DEFAULT_URL_CONCURRENCY
        batch_limit = int(raw_batch_limit)
    except (AttributeError, TypeError, ValueError):
        batch_limit = _DEFAULT_URL_CONCURRENCY
    limits = [total_urls, system_limit, batch_limit]
    browser_capacity_limit = _browser_capacity_limit(settings_view)
    if browser_capacity_limit is not None:
        limits.append(browser_capacity_limit)
    return max(1, min(limits))


def _browser_capacity_limit(settings_view) -> int | None:
    fetch_mode = _settings_fetch_mode(settings_view)
    if fetch_mode in BROWSER_CONCURRENCY_EXEMPT_FETCH_MODES:
        return None
    try:
        return max(1, int(crawler_runtime_settings.browser_runtime_context_capacity))
    except (AttributeError, TypeError, ValueError):
        return _DEFAULT_URL_CONCURRENCY


def _settings_fetch_mode(settings_view) -> str:
    fetch_profile = None
    try:
        fetch_profile_attr = getattr(settings_view, "fetch_profile", None)
        fetch_profile = (
            fetch_profile_attr()
            if callable(fetch_profile_attr)
            else fetch_profile_attr
        )
    except (AttributeError, TypeError, ValueError):
        fetch_profile = None
    if fetch_profile is None:
        getter = getattr(settings_view, "get", None)
        if callable(getter):
            fetch_profile = getter("fetch_profile")
    if not isinstance(fetch_profile, dict):
        return ""
    return str(fetch_profile.get("fetch_mode") or "").strip().lower()


def _parallel_worker_record_limit(max_records: int, concurrency: int) -> int:
    total_budget = max(1, int(max_records or 1))
    worker_count = max(1, int(concurrency or 1))
    return max(1, (total_budget + worker_count - 1) // worker_count)


def _safe_sitemap_max_urls(value: object) -> int:
    try:
        candidate = value if value not in (None, "") else SITEMAP_DEFAULT_MAX_URLS
        return int(str(candidate))
    except (TypeError, ValueError):
        return SITEMAP_DEFAULT_MAX_URLS


def _allow_sitemap_homepage_fallback(run: CrawlRun, settings_view) -> bool:
    return False


async def _resolve_run_urls(run: CrawlRun, settings_view) -> list[str]:
    urls = settings_view.urls()
    if run.run_type == "batch" and urls:
        url_list = urls
    elif run.run_type == "csv" and settings_view.get("csv_content"):
        url_list = await parse_csv_urls_async(settings_view.get("csv_content"))
    elif settings_view.get("sitemap_domain"):
        url_list = await resolve_category_urls_from_sitemap(
            domain=settings_view.get("sitemap_domain"),
            filter_keyword=settings_view.get("sitemap_filter_keyword")
            or SITEMAP_DEFAULT_FILTER_KEYWORD,
            max_urls=_safe_sitemap_max_urls(settings_view.get("sitemap_max_urls")),
            allow_homepage_fallback=_allow_sitemap_homepage_fallback(
                run, settings_view
            ),
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


def _touch_run_heartbeat(run: CrawlRun) -> None:
    run.last_heartbeat_at = datetime.now(UTC)


def _url_timeout_seconds(settings_view) -> float:
    configured_timeout = settings_view.get("url_timeout_seconds")
    if configured_timeout not in (None, ""):
        return settings_view.url_timeout_seconds()
    base_timeout = crawler_runtime_settings.default_url_process_timeout_seconds()
    # Extend timeout when traversal is active — pagination/scroll can take
    # significantly longer than a single-page fetch+extract cycle.
    traversal_mode = settings_view.traversal_mode()
    if traversal_mode:
        raw_max_pages = settings_view.max_pages()
        raw_max_scrolls = settings_view.max_scrolls()
        max_pages = int(raw_max_pages) if raw_max_pages is not None else 1
        max_scrolls = int(raw_max_scrolls) if raw_max_scrolls is not None else 1
        traversal_pages = max(max_pages, max_scrolls)
        # Allow ~30s per traversal page on top of the base timeout, capped at max.
        traversal_budget = traversal_pages * 30.0
        extended = base_timeout + traversal_budget
        return min(
            extended, float(crawler_runtime_settings.max_url_process_timeout_seconds)
        )
    return base_timeout


async def _persist_url_failure_log(
    session: AsyncSession,
    *,
    run_id: int,
    url: str,
    exc: BaseException,
    log_message: str,
) -> CrawlRun:
    run = await session.get(CrawlRun, run_id, populate_existing=True)
    if run is None:
        raise RuntimeError(f"Run {run_id} disappeared after URL failure") from exc
    logger.warning(
        "URL processing failed for run=%s url=%s", run_id, url, exc_info=True
    )
    event_message = log_message
    if not event_message.startswith("[url:"):
        event_message = f"[url:{url}] {event_message}"
    await log_event(session, run.id, "warning", event_message)
    await session.commit()
    return run


async def _cancel_pending_tasks(tasks: list[asyncio.Task]) -> None:
    for t in tasks:
        if not t.done():
            t.cancel()
    with suppress(BaseException):
        await asyncio.gather(*tasks, return_exceptions=True)


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
) -> tuple[str, int]:
    verdict = str(url_result.verdict or VERDICT_ERROR)
    records_count = _url_result_record_count(url_result)
    progress_state.record_url_result(
        idx=idx - 1,
        records_count=records_count,
        verdict=verdict,
        url_metrics=url_result.url_metrics,
    )
    _touch_run_heartbeat(run)
    run.update_summary(
        **progress_state.build_progress_patch(
            current_url=url,
            current_url_index=idx,
        ),
        duration_ms=_current_duration_ms(run),
    )
    await session.commit()
    return verdict, records_count


async def _drain_completed_parallel_tasks(
    pending: set[asyncio.Task],
    *,
    record_task_result,
) -> None:
    completed = [task for task in pending if task.done()]
    for task in completed:
        pending.remove(task)
        await record_task_result(task)


async def _apply_control_checkpoint(
    session: AsyncSession,
    run: CrawlRun,
    control_request: str | None,
) -> bool:
    if control_request not in (CONTROL_REQUEST_PAUSE, CONTROL_REQUEST_KILL):
        return False
    new_status = (
        CrawlStatus.PAUSED
        if control_request == CONTROL_REQUEST_PAUSE
        else CrawlStatus.KILLED
    )
    update_run_status(run, new_status)
    set_control_request(run, None)
    signal_word = "paused" if control_request == CONTROL_REQUEST_PAUSE else "killed"
    await log_event(session, run.id, "warning", f"Run {signal_word} at checkpoint")
    await session.commit()
    return True


async def _process_urls_in_parallel(
    session: AsyncSession,
    *,
    run: CrawlRun,
    settings_view,
    url_list: list[str],
    progress_state: BatchRunProgressState,
    max_records: int,
    url_timeout_seconds: float,
) -> tuple[list[str], int]:
    total_urls = len(url_list)
    concurrency = _parallel_url_concurrency(total_urls, settings_view)
    record_limit = _parallel_worker_record_limit(max_records, concurrency)
    await log_event(
        session, run.id, "info", f"Processing {total_urls} URL(s) with concurrency={concurrency}"
    )
    await session.commit()
    semaphore = asyncio.Semaphore(concurrency)
    run_id = int(run.id)

    async def _guarded(idx: int, url: str, record_limit: int) -> tuple[int, str, URLProcessingResult]:
        async with semaphore:
            return await process_url_in_owned_session(
                session_factory=SessionLocal,
                persist_failure_log=_persist_url_failure_log,
                processor=process_single_url,
                run_id=run_id,
                idx=idx,
                total_urls=total_urls,
                url=url,
                max_records=record_limit,
                url_timeout_seconds=url_timeout_seconds,
            )

    tasks = [
        asyncio.create_task(
            _guarded(idx, url, record_limit), name=f"crawl-run-{run_id}-url-{idx}"
        )
        for idx, url in enumerate(url_list, start=1)
    ]
    verdicts: list[str] = []
    record_count = as_int(run.get_summary("record_count", 0))

    async def _record_task_result(task: asyncio.Task) -> tuple[int, str]:
        nonlocal record_count
        idx, url, url_result = await task
        verdict, records_count = await _record_url_result(
            session,
            run=run,
            progress_state=progress_state,
            idx=idx,
            url=url,
            url_result=url_result,
        )
        verdicts.append(verdict)
        record_count += records_count
        return idx, url

    try:
        pending = set(tasks)
        while pending:
            done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await _record_task_result(task)

            await session.refresh(run)

            control_request = get_control_request(run)
            if control_request in (CONTROL_REQUEST_PAUSE, CONTROL_REQUEST_KILL):
                await _drain_completed_parallel_tasks(
                    pending,
                    record_task_result=_record_task_result,
                )
                await _cancel_pending_tasks(list(pending))
                await _apply_control_checkpoint(session, run, control_request)
                return verdicts, record_count

            if record_count >= max_records:
                await _drain_completed_parallel_tasks(
                    pending,
                    record_task_result=_record_task_result,
                )
                await _cancel_pending_tasks(list(pending))
                await log_event(
                    session,
                    run.id,
                    "info",
                    f"Stopped after reaching max_records={max_records}",
                )
                await session.commit()
                pending.clear()
                break

    except BaseException:
        await _cancel_pending_tasks(tasks)
        raise
    return verdicts, record_count


async def _log_sequential_url_start(
    session: AsyncSession,
    *,
    run: CrawlRun,
    idx: int,
    total_urls: int,
    url: str,
) -> None:
    if idx == 1:
        await log_event(session, run.id, "info", f"Starting crawl run for {url}")
        await log_event(
            session,
            run.id,
            "info",
            f"Resolved {total_urls} seed URL(s), domain policy: standard",
        )
        return
    await log_event(session, run.id, "info", f"Starting crawl run for {url} ({idx}/{total_urls})")


async def _process_urls_sequential(
    session: AsyncSession,
    *,
    run: CrawlRun,
    url_list: list[str],
    progress_state: BatchRunProgressState,
    max_records: int,
    sleep_ms: int,
    url_timeout_seconds: float,
    run_span,
) -> tuple[list[str], int]:
    total_urls = len(url_list)
    verdicts: list[str] = []
    record_count = as_int(run.get_summary("record_count", 0))
    for idx, url in enumerate(url_list, start=1):
        await session.refresh(run)
        _touch_run_heartbeat(run)
        if await _apply_control_checkpoint(session, run, get_control_request(run)):
            return verdicts, record_count
        await _log_sequential_url_start(
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
            persist_failure_log=_persist_url_failure_log,
            processor=process_single_url,
            run_id=run.id,
            idx=idx,
            total_urls=total_urls,
            url=url,
            max_records=max(max_records - record_count, 1),
            url_timeout_seconds=url_timeout_seconds,
            log_start=False,
        )
        await session.refresh(run)
        verdict, records_count = await _record_url_result(
            session,
            run=run,
            progress_state=progress_state,
            idx=idx,
            url=url,
            url_result=url_result,
        )
        verdicts.append(verdict)
        record_count += records_count
        set_logfire_attributes(
            run_span,
            record_count=record_count,
            last_url_verdict=verdict,
        )
        if record_count >= max_records:
            await log_event(
                session,
                run.id,
                "info",
                f"Stopped after reaching max_records={max_records}",
            )
            await session.commit()
            break
        if sleep_ms > 0 and idx < total_urls:
            await asyncio.sleep(sleep_ms / 1000)
    return verdicts, record_count


async def _finalize_completed_run(
    session: AsyncSession,
    *,
    run: CrawlRun,
    run_span,
    verdicts: list[str],
    record_count: int,
    progress_state: BatchRunProgressState,
) -> None:
    await session.refresh(run)
    if run.status_value in TERMINAL_STATUSES:
        return
    aggregate_verdict_value = aggregate_verdict(verdicts)
    set_logfire_attributes(
        run_span,
        verdict=aggregate_verdict_value,
        record_count=record_count,
    )
    update_run_status(run, CrawlStatus.COMPLETED)
    _touch_run_heartbeat(run)
    run.update_summary(
        **progress_state.build_final_patch(aggregate_verdict_value),
        current_stage=STAGE_PERSIST,
        duration_ms=_current_duration_ms(run),
    )
    await log_event(
        session,
        run.id,
        "info",
        f"Pipeline finished. {record_count} records. verdict={aggregate_verdict_value}",
    )
    await session.commit()
    try:
        await on_run_complete(run.id)
    except Exception as exc:
        logger.exception("Run-complete callback failed for run=%s", run.id)
        try:
            await log_event(session, run.id, "error", f"on_run_complete failure: {exc}")
        except Exception:
            logger.debug("Failed to log on_run_complete failure to DB", exc_info=True)
            await rollback_url_session(session, context="failed complete log recovery")


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
        if run is None or run.status_value in TERMINAL_STATUSES:
            return
        await session.refresh(run)
        set_logfire_attributes(
            run_span,
            surface=run.surface,
            run_type=run.run_type,
            llm_enabled=run.settings_view.llm_enabled(),
        )
        if run.status_value == CrawlStatus.PAUSED:
            return
        if run.status_value == CrawlStatus.PENDING:
            update_run_status(run, CrawlStatus.RUNNING)

        _touch_run_heartbeat(run)
        await session.commit()
        settings_view = run.settings_view
        url_list = await _resolve_run_urls(run, settings_view)
        total_urls = len(url_list)
        if total_urls == 0:
            raise ValueError("No URL provided")
        await _prewarm_browser_pool()
        set_logfire_attributes(
            run_span,
            url_count=total_urls,
            domain=normalize_domain(url_list[0]) if url_list else "",
        )

        max_records = settings_view.max_records()
        sleep_ms = settings_view.sleep_ms()
        url_timeout_seconds = _url_timeout_seconds(settings_view)

        progress_state = BatchRunProgressState(
            total_urls=total_urls,
            url_domain=normalize_domain(url_list[0]) if url_list else "",
            persisted_record_count=as_int(run.get_summary("record_count", 0)),
        )
        run.update_summary(
            **progress_state.build_progress_patch(
                current_url=url_list[0] if url_list else "",
                current_url_index=0,
            ),
            current_stage=STAGE_ACQUIRE,
            resolved_url_list=url_list,
        )
        await session.commit()

        if total_urls > 1 and _parallel_url_concurrency(total_urls, settings_view) > 1:
            verdicts, record_count = await _process_urls_in_parallel(
                session,
                run=run,
                settings_view=settings_view,
                url_list=url_list,
                progress_state=progress_state,
                max_records=max_records,
                url_timeout_seconds=url_timeout_seconds,
            )
        else:
            verdicts, record_count = await _process_urls_sequential(
                session,
                run=run,
                url_list=url_list,
                progress_state=progress_state,
                max_records=max_records,
                sleep_ms=sleep_ms,
                url_timeout_seconds=url_timeout_seconds,
                run_span=run_span,
            )
        await _finalize_completed_run(
            session,
            run=run,
            run_span=run_span,
            verdicts=verdicts,
            record_count=record_count,
            progress_state=progress_state,
        )
    except (RuntimeError, ValueError, TypeError, SQLAlchemyError) as exc:
        logger.exception("Run-level failure for run=%s", run_id)
        await rollback_url_session(session, context="run failure marking")
        await mark_run_failed(session, run_id, f"{type(exc).__name__}: {exc}")
