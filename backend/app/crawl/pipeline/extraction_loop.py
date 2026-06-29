from __future__ import annotations

import asyncio
import logging
from typing import Literal, cast

from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.models.crawl_run import CrawlRun
from app.acquisition.acquirer import PageAcquisitionResult
from app.acquisition.acquirer import acquire as _acquire
from app.acquisition.browser_fetch_support import browser_page_load_elapsed_ms
from app.acquisition.browser_runtime import real_chrome_browser_available
from app.acquisition.host_protection_memory import note_host_hard_block
from app.core.db_utils import mapping_or_empty
from app.crawl.domain_memory_service import load_domain_selector_rules
from app.core.domain_utils import normalize_domain
from app.acquisition.platform_policy import detect_platform_family
from app.persistence.publish import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_LISTING_FAILED,
    build_url_metrics,
    compute_verdict,
    finalize_url_metrics,
)
from app.crawl.robots_policy import (
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    check_url_crawlability,
)
from sqlalchemy.ext.asyncio import AsyncSession

from .retry import build_acquisition_request, retry_extraction_request_with_browser
from .persistence import persist_extracted_records
from app.persistence.url_results import upsert_url_result
from app.persistence.url_result_artifacts import publish_url_result_artifacts
from app.persistence.projection import project_extraction_result
from app.persistence.knowledge_graph import lock_site_version
from .record_extraction_stage import (
    extract_records_for_acquisition,
    update_acquisition_contract_memory,
)
from .runtime_helpers import (
    STAGE_ACQUIRE,
    STAGE_EXTRACT,
    STAGE_NORMALIZE,
    STAGE_PERSIST,
    browser_attempted as _browser_attempted,
    browser_launch_log_message as _browser_launch_log_message,
    browser_outcome as _browser_outcome,
    effective_blocked as _effective_blocked,
    mark_run_failed,
    record_detail_expansion_extraction_outcome as _record_detail_expansion_extraction_outcome,
    suppress_empty_downstream_record_logs as _suppress_empty_downstream_record_logs,
    log_pipeline_event as _log_pipeline_event,
    set_stage,
)
from .types import URLProcessingConfig, URLProcessingResult
from .url_processing_context import (
    ExtractedURLStage as _ExtractedURLStage,
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
    build_url_processing_context as _build_url_processing_context,
    resolved_url_processing_config as _resolved_url_processing_config,
)

UrlVerdict = Literal[
    "success",
    "partial",
    "review",
    "invalid",
    "empty",
    "blocked",
    "error",
    "wrong_surface",
    "listing_failed",
]

__all__ = [
    "STAGE_ACQUIRE",
    "STAGE_EXTRACT",
    "STAGE_NORMALIZE",
    "STAGE_PERSIST",
    "URLProcessingContext",
    "detect_platform_family",
    "load_domain_selector_rules",
    "mark_run_failed",
    "note_host_hard_block",
    "process_single_url",
    "real_chrome_browser_available",
    "resolved_url_processing_config",
]

acquire = _acquire
logger = logging.getLogger(__name__)


async def process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    url_timeout_seconds: float | None = None,
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int | None = None,
    max_scrolls: int | None = None,
    max_records: int | None = None,
    sleep_ms: int | None = None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition: PageAcquisitionResult | None = None,
) -> URLProcessingResult:
    settings_view = run.settings_view
    context = _build_url_processing_context(
        session=session,
        run=run,
        url=url,
        config=config,
        url_timeout_seconds=url_timeout_seconds,
        proxy_list=proxy_list,
        traversal_mode=traversal_mode,
        max_pages=max_pages,
        max_scrolls=max_scrolls,
        max_records=max_records,
        sleep_ms=sleep_ms,
        update_run_state=update_run_state,
        persist_logs=persist_logs,
    )
    with logfire_span(
        "pipeline.url.process",
        run_id=run.id,
        domain=normalize_domain(url),
        surface=run.surface,
        llm_enabled=settings_view.llm_enabled(),
        traversal_mode=context.config.traversal_mode or "",
        max_records=context.config.max_records,
    ) as span:
        await _enter_stage(context, STAGE_ACQUIRE)
        robots_result = await _run_robots_gate(context)
        if robots_result is not None:
            set_logfire_attributes(
                span,
                verdict=robots_result.verdict,
                blocked=True,
                stage="robots",
            )
            return robots_result
        fetched = await _run_acquisition_stage(
            context,
            prefetched_acquisition=prefetched_acquisition,
        )
        if context.config.prefetch_only:
            result = _build_prefetch_only_result(context, fetched)
            set_logfire_attributes(span, verdict=result.verdict, prefetch_only=True)
            return result
        await _enter_stage(context, STAGE_EXTRACT)
        extracted = await _run_extraction_stage(context, fetched)
        await _enter_stage(context, STAGE_NORMALIZE)
        result = await _run_persistence_stage(context, extracted)
        result_metrics = mapping_or_empty(result.url_metrics)
        set_logfire_attributes(
            span,
            verdict=result.verdict,
            record_count=result_metrics.get("record_count"),
            method=result_metrics.get("method"),
            blocked=result_metrics.get("blocked"),
        )
        return result


async def _enter_stage(
    context: _URLProcessingContext,
    stage_name: str,
) -> None:
    if context.config.update_run_state:
        await set_stage(
            context.session,
            context.run,
            stage_name,
            current_url=context.url,
        )
        await context.session.commit()


async def _run_robots_gate(
    context: _URLProcessingContext,
) -> URLProcessingResult | None:
    if context.run.settings_view.respect_robots_txt():
        robots_result = await check_url_crawlability(context.url)
        if not robots_result.allowed:
            await _log_pipeline_event(
                context,
                "warning",
                f"[ROBOTS] Blocked by robots.txt: {context.url}",
            )
            return URLProcessingResult(
                records=[],
                verdict=VERDICT_BLOCKED,
                url_metrics=finalize_url_metrics(
                    {
                        "blocked": True,
                        "final_url": context.url,
                        "method": "",
                        "requested_fields": list(context.requested_fields),
                        "robots": {
                            "allowed": False,
                            "outcome": robots_result.outcome,
                            "robots_url": robots_result.robots_url,
                        },
                    },
                    record_count=0,
                ),
            )
        if robots_result.outcome == ROBOTS_MISSING:
            await _log_pipeline_event(
                context,
                "info",
                f"[ROBOTS] No robots.txt found for {context.url}; continuing",
            )
        if robots_result.outcome == ROBOTS_FETCH_FAILURE:
            await _log_pipeline_event(
                context,
                "warning",
                f"[ROBOTS] robots.txt check failed for {context.url}; continuing",
            )
        return None
    return None


def _pipeline_acquisition_event_logger(
    context: _URLProcessingContext,
):
    async def _log(level: str, message: str) -> None:
        await _log_pipeline_event(context, level, message)

    return _log


async def _run_acquisition_stage(
    context: _URLProcessingContext,
    *,
    prefetched_acquisition: PageAcquisitionResult | None,
) -> _FetchedURLStage:
    with logfire_span(
        "pipeline.acquire",
        run_id=context.run.id,
        domain=normalize_domain(context.url),
        surface=context.surface,
        prefetched=bool(prefetched_acquisition),
    ) as span:
        acquisition_request = await build_acquisition_request(context)
        acquisition_result = prefetched_acquisition or await acquire(
            acquisition_request
        )
        diagnostics = mapping_or_empty(
            getattr(acquisition_result, "browser_diagnostics", {})
        )
        timings = mapping_or_empty(diagnostics.get("phase_timings_ms", {}))
        set_logfire_attributes(
            span,
            method=getattr(acquisition_result, "method", "unknown"),
            status_code=getattr(acquisition_result, "status_code", None),
            blocked=bool(getattr(acquisition_result, "blocked", False)),
            browser_attempted=_browser_attempted(acquisition_result),
            browser_outcome=_browser_outcome(acquisition_result),
            browser_engine=diagnostics.get("browser_engine"),
            total_ms=timings.get("total"),
            navigation_ms=timings.get("navigation"),
            final_domain=normalize_domain(
                str(getattr(acquisition_result, "final_url", "") or context.url)
            ),
        )
    method = getattr(acquisition_result, "method", "unknown")
    if method == "browser":
        if getattr(acquisition_request, "on_event", None) is None:
            diagnostics = mapping_or_empty(
                getattr(acquisition_result, "browser_diagnostics", {})
            )
            timings = mapping_or_empty(diagnostics.get("phase_timings_ms", {}))
            load_ms = browser_page_load_elapsed_ms(timings) or timings.get("total", 0)
            await _log_pipeline_event(
                context,
                "info",
                _browser_launch_log_message(acquisition_result),
            )
            await _log_pipeline_event(
                context,
                "info",
                f"Page loaded in {load_ms}ms",
            )
    else:
        status = getattr(acquisition_result, "status_code", 0)
        await _log_pipeline_event(
            context,
            "info",
            f"Acquired payload via {method} (status={status})",
        )

    browser_attempted = _browser_attempted(acquisition_result)
    if _effective_blocked(acquisition_result) and not browser_attempted:
        await _log_pipeline_event(
            context,
            "warning",
            f"Acquisition detected rate limiting or bot protection for {context.url}",
        )

    return _FetchedURLStage(
        context=context,
        acquisition_result=acquisition_result,
        url_metrics=build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        ),
    )


def _build_prefetch_only_result(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> URLProcessingResult:
    verdict = compute_verdict(
        is_listing="listing" in context.surface,
        blocked=_effective_blocked(fetched.acquisition_result),
        record_count=1 if fetched.acquisition_result.html else 0,
    )
    return URLProcessingResult(
        records=[],
        verdict=verdict,
        url_metrics=finalize_url_metrics(fetched.url_metrics, record_count=0),
    )


async def _run_extraction_stage(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> _ExtractedURLStage:
    with logfire_span(
        "pipeline.extract",
        run_id=context.run.id,
        domain=normalize_domain(context.url),
        surface=context.surface,
        method=getattr(fetched.acquisition_result, "method", ""),
    ) as span:
        return await _run_extraction_stage_observed(context, fetched, span)


async def _run_extraction_stage_observed(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    span,
) -> _ExtractedURLStage:
    acquisition_result = fetched.acquisition_result
    result, selector_rules = await extract_records_for_acquisition(
        context,
        fetched,
    )
    set_logfire_attributes(
        span,
        initial_record_count=len(result.records),
        selector_rule_count=len(selector_rules),
        adapter=getattr(acquisition_result, "adapter_name", None),
        platform=getattr(acquisition_result, "platform_family", None),
        verdict=result.verdict,
    )
    _record_detail_expansion_extraction_outcome(
        acquisition_result,
        [_public_record_payload(record, context.surface) for record in result.records],
        requested_fields=list(context.requested_fields),
    )
    result = await retry_extraction_request_with_browser(
        context,
        fetched,
        result=result,
    )
    set_logfire_attributes(
        span,
        final_record_count=len(result.records),
        verdict=result.verdict,
    )
    return _ExtractedURLStage(fetched=fetched, result=result)


def _public_record_payload(record, surface: str) -> dict[str, object]:
    return record.model_dump(
        mode="json",
        exclude_none=surface != "ecommerce_detail",
    )


# skipcq: PY-R1000
async def _run_persistence_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> URLProcessingResult:
    acquisition_result = extracted.fetched.acquisition_result
    extraction_result = extracted.result
    extracted_records = [
        _public_record_payload(record, context.surface)
        for record in extraction_result.records
    ]
    with logfire_span(
        "pipeline.persist",
        run_id=context.run.id,
        domain=normalize_domain(str(acquisition_result.final_url or context.url)),
        surface=context.surface,
        input_record_count=len(extracted_records),
    ) as span:
        await _enter_stage(context, STAGE_PERSIST)
        url_result = await upsert_url_result(
            context.session,
            run=context.run,
            requested_url=context.url,
            acquisition_result=acquisition_result,
            extraction_result=extraction_result,
            record_count=0,
        )
        persisted_batch = await persist_extracted_records(
            context.session,
            context.run,
            extracted_records,
            acquisition_result=acquisition_result,
            url_result_id=url_result.id,
        )
        persisted_count = persisted_batch.record_count
        url_result.record_count = persisted_count
        set_logfire_attributes(
            span,
            persisted_count=persisted_count,
        )
    verdict = cast(UrlVerdict, extraction_result.verdict)
    if not _suppress_empty_downstream_record_logs(
        acquisition_result,
        extracted_records,
    ):
        await _log_pipeline_event(
            context,
            "info",
            f"Persisted {persisted_count} record(s) for {acquisition_result.final_url}",
            commit=False,
        )
    if (
        verdict == VERDICT_EMPTY
        and "listing" in context.surface
        and persisted_count == 0
    ):
        verdict = cast(UrlVerdict, VERDICT_LISTING_FAILED)
    await _publish_url_result_artifacts(
        context,
        extracted,
        url_result=url_result,
        record_count=persisted_count,
        record_provenance=persisted_batch.provenance,
        verdict=verdict,
    )
    await update_acquisition_contract_memory(
        context,
        acquisition_result=acquisition_result,
        records=extracted_records,
        persisted_count=persisted_count,
        verdict=verdict,
    )
    await _project_knowledge_graph(context, extracted)
    return URLProcessingResult(
        records=extracted_records,
        verdict=verdict,
        url_metrics=finalize_url_metrics(
            mapping_or_empty(extracted.fetched.url_metrics),
            record_count=persisted_count,
        ),
    )


async def _publish_url_result_artifacts(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
    *,
    url_result,
    record_count: int,
    record_provenance,
    verdict: str,
) -> None:
    acquisition_result = extracted.fetched.acquisition_result
    published = await asyncio.to_thread(
        publish_url_result_artifacts,
        run_id=context.run.id,
        url_result_id=url_result.id,
        acquisition_result=acquisition_result,
        extraction_result=extracted.result,
        record_count=record_count,
        record_provenance=record_provenance,
    )
    # The result-root path *is* the artifact contract: the reader opens
    # page.html / record.json / diagnose.json by fixed name beneath it.
    url_result.manifest_uri = published.result_root
    url_result.bundle_id = published.bundle_id
    url_result.verdict = verdict
    await context.session.flush()


async def _project_knowledge_graph(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> None:
    projection_url = str(
        getattr(extracted.fetched.acquisition_result, "final_url", "") or context.url
    )
    try:
        async with context.session.begin_nested():
            await project_extraction_result(
                context.session,
                run_id=context.run.id,
                url=projection_url,
                result=extracted.result,
            )
    except Exception as exc:
        try:
            async with context.session.begin_nested():
                site_version = await lock_site_version(
                    context.session,
                    normalize_domain(projection_url),
                )
                site_version.projection_status = "failed"
        except Exception:
            logger.debug("Failed to mark Knowledge Graph projection failure", exc_info=True)
        await _log_pipeline_event(
            context,
            "error",
            f"Knowledge Graph projection failed without changing crawl verdict: {type(exc).__name__}: {exc}",
            commit=False,
        )


URLProcessingContext = _URLProcessingContext
resolved_url_processing_config = _resolved_url_processing_config
