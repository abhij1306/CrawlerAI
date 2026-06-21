from __future__ import annotations

import logging

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
        )
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
                        url_timeout_seconds=url_timeout_seconds,
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
        except Exception as exc:
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
