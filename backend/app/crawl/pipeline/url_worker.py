from __future__ import annotations

import logging

from app.core.config import settings
from app.core.config.runtime_settings import (
    BROWSER_CONCURRENCY_EXEMPT_FETCH_MODES,
    crawler_runtime_settings,
)
from app.core.domain_utils import normalize_domain
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.models.crawl_run import CrawlRun
from app.crawl.pipeline.runtime_helpers import log_event
from app.crawl.pipeline.types import URLProcessingConfig, URLProcessingResult
from app.crawl.pipeline.url_failure_recovery import (
    URLProcessingDeadlineExceeded,
    recover_url_failure,
    run_url_processing_with_timeout,
)
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger(__name__)
_DEFAULT_URL_CONCURRENCY = 1


def _settings_fetch_mode(settings_view) -> str:
    fetch_profile = None
    try:
        fetch_profile_attr = getattr(settings_view, "fetch_profile", None)
        fetch_profile = (
            fetch_profile_attr() if callable(fetch_profile_attr) else fetch_profile_attr
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


def _browser_capacity_limit(settings_view) -> int | None:
    if _settings_fetch_mode(settings_view) in BROWSER_CONCURRENCY_EXEMPT_FETCH_MODES:
        return None
    try:
        return max(1, int(crawler_runtime_settings.browser_runtime_context_capacity))
    except (AttributeError, TypeError, ValueError):
        return _DEFAULT_URL_CONCURRENCY


def parallel_url_concurrency(total_urls: int, settings_view) -> int:
    if not bool(settings.celery_dispatch_enabled):
        return _DEFAULT_URL_CONCURRENCY
    try:
        system_limit = int(
            getattr(settings, "system_max_concurrent_urls", _DEFAULT_URL_CONCURRENCY)
        )
    except (AttributeError, TypeError, ValueError):
        system_limit = _DEFAULT_URL_CONCURRENCY
    try:
        batch_limit_value = getattr(settings_view, "url_batch_concurrency", None)
        raw_batch_limit = (
            batch_limit_value() if callable(batch_limit_value) else batch_limit_value
        )
        batch_limit = int(raw_batch_limit or _DEFAULT_URL_CONCURRENCY)
    except (AttributeError, TypeError, ValueError):
        batch_limit = _DEFAULT_URL_CONCURRENCY
    limits = [total_urls, system_limit, batch_limit]
    browser_capacity_limit = _browser_capacity_limit(settings_view)
    if browser_capacity_limit is not None:
        limits.append(browser_capacity_limit)
    return max(1, min(limits))


def parallel_worker_record_limit(max_records: int, concurrency: int) -> int:
    total_budget = max(1, int(max_records or 1))
    worker_count = max(1, int(concurrency or 1))
    return max(1, (total_budget + worker_count - 1) // worker_count)


def url_metric(
    url_result: URLProcessingResult,
    key: str,
    default: object | None = None,
) -> object | None:
    metrics = url_result.url_metrics if isinstance(url_result.url_metrics, dict) else {}
    return metrics.get(key, default)


def url_start_message(*, url: str, idx: int, total_urls: int) -> str:
    if idx == 1:
        return f"Starting crawl run for {url}"
    return f"Starting crawl run for {url} ({idx}/{total_urls})"


async def process_url_in_owned_session(
    *,
    session_factory: async_sessionmaker,
    persist_failure_log,
    processor,
    run_id: int,
    idx: int,
    total_urls: int,
    url: str,
    max_records: int,
    url_timeout_seconds: float,
    log_start: bool = True,
) -> tuple[int, str, URLProcessingResult]:
    async with session_factory() as url_session:
        run = await url_session.get(CrawlRun, run_id, populate_existing=True)
        if run is None:
            raise RuntimeError(f"Run {run_id} disappeared before URL processing")
        if log_start:
            await log_event(
                url_session,
                run.id,
                "info",
                url_start_message(url=url, idx=idx, total_urls=total_urls),
            )
            await url_session.commit()
        url_config = URLProcessingConfig.from_acquisition_plan(
            run.settings_view.acquisition_plan(
                surface=run.surface,
                max_records=max(1, max_records),
            ),
            update_run_state=False,
            persist_logs=True,
            url_timeout_seconds=url_timeout_seconds,
        )
        if not log_start:
            await url_session.commit()
        try:
            with logfire_span(
                "pipeline.url",
                run_id=run.id,
                url_index=idx,
                url_count=total_urls,
                domain=normalize_domain(url),
                surface=run.surface,
                max_records=max_records,
                timeout_seconds=url_timeout_seconds,
            ) as url_span:
                url_result = await run_url_processing_with_timeout(
                    processor(
                        session=url_session,
                        run=run,
                        url=url,
                        config=url_config,
                    ),
                    url_timeout_seconds,
                )
                if not isinstance(url_result, URLProcessingResult):
                    raise TypeError(f"Unexpected URL result type: {type(url_result)!r}")
                set_logfire_attributes(
                    url_span,
                    verdict=url_result.verdict,
                    record_count=url_metric(
                        url_result,
                        "record_count",
                        len(url_result.records),
                    ),
                    method=url_metric(url_result, "method"),
                    blocked=url_metric(url_result, "blocked"),
                )
            await url_session.commit()
        except URLProcessingDeadlineExceeded as exc:
            logger.warning("URL processing timed out for run=%s url=%s", run.id, url)
            run, url_result = await recover_url_failure(
                url_session,
                session_factory=session_factory,
                persist_failure_log=persist_failure_log,
                run=run,
                run_id=run.id,
                url=url,
                exc=exc,
                log_message=(
                    f"URL processing timed out for {url} "
                    f"(timeout_seconds={url_timeout_seconds})"
                ),
            )
            url_result.url_metrics["error"] = (
                f"TimeoutError: url exceeded timeout_seconds={url_timeout_seconds}"
            )
        except Exception as exc:  # noqa: BLE001 - URL isolation boundary must recover all failures
            run, url_result = await recover_url_failure(
                url_session,
                session_factory=session_factory,
                persist_failure_log=persist_failure_log,
                run=run,
                run_id=run.id,
                url=url,
                exc=exc,
                log_message=f"URL processing failed for {url}: {type(exc).__name__}: {exc}",
            )
        return idx, url, url_result
