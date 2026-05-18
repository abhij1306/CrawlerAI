from __future__ import annotations

import asyncio
import logging
import time

from app.models.crawl_run import CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.acquisition.host_protection_memory import note_host_hard_block
from app.services.adapters.registry import run_adapter
from app.services.acquisition.browser_runtime import real_chrome_browser_available
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.domain_memory_service import load_domain_selector_rules
from app.services.pipeline.extract_records import extract_records
from app.services.extract.detail.assembly.record_assembly import (
    detail_record_rejection_reason,
    infer_detail_failure_reason,
)
from app.services.platform_policy import detect_platform_family
from app.services.pipeline.extraction_retry_stage import (
    remaining_url_budget_seconds as _remaining_url_budget_seconds,
)
from app.services.db_utils import mapping_or_empty
from app.services.domain_utils import normalize_domain
from app.services.crawl.profile import (
    apply_acquisition_contract_to_profile,
)
from app.services.shared.field_coerce import validate_record_for_surface
from app.services.llm.config_service import resolve_run_config
from app.services.llm.runtime import (
    extract_records_directly as extract_records_directly_with_llm,
)
from app.services.pipeline.direct_record_fallback import (
    apply_direct_record_llm_fallback as apply_direct_record_llm_fallback_impl,
    apply_llm_fallback,
)
from app.services.publish import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_LISTING_FAILED,
    build_url_metrics,
    compute_verdict,
    finalize_url_metrics,
)
from app.services.robots_policy import (
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    check_url_crawlability,
)
from app.services.selector_self_heal import apply_selector_self_heal
from sqlalchemy.ext.asyncio import AsyncSession

from .extraction_retry_decision import (
    annotate_field_repair as _annotate_field_repair,
    empty_extraction_browser_retry_decision as _empty_extraction_browser_retry_decision,
    low_quality_extraction_browser_retry_decision as _low_quality_extraction_browser_retry_decision,
)
from .extraction_retry_stage import (
    _apply_detail_rejection_guard,
    _build_acquisition_request,
    _log_extraction_outcome,
    _retry_detail_challenge_shell_with_real_chrome,
    _retry_empty_extraction_with_browser,
    _retry_listing_integrity_with_stronger_tier,
    _retry_low_quality_extraction_with_browser,
    _retry_patchright_detail_shell_with_real_chrome,
)
from .persistence import persist_acquisition_artifacts, persist_extracted_records
from .record_extraction_stage import (
    _best_adapter_result,
    _extract_records_for_acquisition,
    _update_acquisition_contract_memory,
)
from .runtime_helpers import (
    STAGE_ACQUIRE,
    STAGE_EXTRACT,
    STAGE_NORMALIZE,
    STAGE_PERSIST,
    browser_attempted as _browser_attempted,
    browser_launch_log_message as _browser_launch_log_message,
    browser_outcome as _browser_outcome,
    browser_result_is_extractable as _browser_result_is_extractable,
    effective_blocked as _effective_blocked,
    mark_run_failed,
    merge_browser_diagnostics as _merge_browser_diagnostics,
    record_detail_expansion_extraction_outcome as _record_detail_expansion_extraction_outcome,
    screenshot_required as _screenshot_required,
    suppress_empty_downstream_record_logs as _suppress_empty_downstream_record_logs,
    log_event,
    set_stage,
)
from .types import URLProcessingConfig, URLProcessingResult
from .url_processing_context import (
    ExtractedURLStage as _ExtractedURLStage,
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
    resolved_url_processing_config as _resolved_url_processing_config,
)

logger = logging.getLogger(__name__)
__all__ = [
    "STAGE_ACQUIRE",
    "STAGE_EXTRACT",
    "STAGE_NORMALIZE",
    "STAGE_PERSIST",
    "URLProcessingContext",
    "best_adapter_result",
    "empty_extraction_browser_retry_decision",
    "mark_run_failed",
    "process_single_url",
    "resolved_url_processing_config",
]

acquire = _acquire


async def process_single_url(
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig | None = None,
    *,
    proxy_list: list[str] | None = None,
    traversal_mode: str | None = None,
    max_pages: int | None = None,
    max_scrolls: int | None = None,
    max_records: int | None = None,
    sleep_ms: int | None = None,
    checkpoint=None,
    update_run_state: bool = True,
    persist_logs: bool = True,
    prefetched_acquisition: AcquisitionResult | None = None,
) -> URLProcessingResult:
    del checkpoint
    settings_view = run.settings_view
    url_timeout_seconds = (
        settings_view.url_timeout_seconds()
        if settings_view.get("url_timeout_seconds") not in (None, "")
        else crawler_runtime_settings.default_url_process_timeout_seconds()
    )
    context = _URLProcessingContext(
        session=session,
        run=run,
        url=url,
        config=_resolved_url_processing_config(
            config,
            surface=run.surface,
            proxy_list=proxy_list
            if proxy_list is not None
            else settings_view.proxy_list(),
            traversal_mode=traversal_mode
            if traversal_mode is not None
            else settings_view.traversal_mode(),
            max_pages=max_pages if max_pages is not None else settings_view.max_pages(),
            max_scrolls=max_scrolls
            if max_scrolls is not None
            else settings_view.max_scrolls(),
            max_records=max_records
            if max_records is not None
            else settings_view.max_records(),
            sleep_ms=sleep_ms if sleep_ms is not None else settings_view.sleep_ms(),
            update_run_state=update_run_state,
            persist_logs=persist_logs,
        ),
        url_timeout_seconds=float(url_timeout_seconds),
        started_at_monotonic=time.monotonic(),
        requested_fields=list(run.requested_fields or []),
        surface=run.surface,
    )
    await _enter_stage(context, STAGE_ACQUIRE)
    robots_result = await _run_robots_gate(context)
    if robots_result is not None:
        return robots_result
    fetched = await _run_acquisition_stage(
        context,
        prefetched_acquisition=prefetched_acquisition,
    )
    if context.config.prefetch_only:
        return _build_prefetch_only_result(context, fetched)
    await _enter_stage(context, STAGE_EXTRACT)
    extracted = await _run_extraction_stage(context, fetched)
    extracted = await _run_normalization_stage(context, extracted)
    return await _run_persistence_stage(context, extracted)


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


async def _log_pipeline_event(
    context: _URLProcessingContext,
    level: str,
    message: str,
    *,
    commit: bool = True,
) -> None:
    if not context.config.persist_logs:
        return
    await log_event(context.session, context.run.id, level, message)
    if commit:
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
    prefetched_acquisition: AcquisitionResult | None,
) -> _FetchedURLStage:
    acquisition_request = await _build_acquisition_request(context)
    acquisition_result = prefetched_acquisition or await acquire(acquisition_request)
    method = getattr(acquisition_result, "method", "unknown")
    if method == "browser":
        if getattr(acquisition_request, "on_event", None) is None:
            diagnostics = mapping_or_empty(
                getattr(acquisition_result, "browser_diagnostics", {})
            )
            timings = mapping_or_empty(diagnostics.get("phase_timings_ms", {}))
            load_ms = timings.get("navigation", 0) or timings.get("total", 0)
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
    acquisition_result = fetched.acquisition_result
    records, selector_rules = await _extract_records_for_acquisition(
        context,
        fetched,
    )
    _record_detail_expansion_extraction_outcome(
        acquisition_result,
        records,
        requested_fields=list(context.requested_fields),
    )
    records, selector_rules = await _retry_empty_extraction_with_browser(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    records, selector_rules = await _retry_low_quality_extraction_with_browser(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    records, selector_rules = await _retry_listing_integrity_with_stronger_tier(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    acquisition_result = fetched.acquisition_result
    records, selector_rules = await _apply_extraction_post_processing(
        context,
        acquisition_result=acquisition_result,
        records=records,
        selector_rules=selector_rules,
    )
    records, rejection_reason = _apply_detail_rejection_guard(
        context,
        fetched,
        records=records,
        selector_rules=selector_rules,
    )
    retry_stage = await _retry_detail_challenge_shell_with_real_chrome(
        context,
        fetched,
        rejection_reason=rejection_reason,
    )
    if retry_stage is None:
        retry_stage = await _retry_patchright_detail_shell_with_real_chrome(
            context,
            fetched,
            rejection_reason=rejection_reason,
        )
    if retry_stage is not None:
        return retry_stage
    await _log_extraction_outcome(context, acquisition_result, records)
    if rejection_reason:
        guidance = (
            "; URL looks like a listing/search seed. Use ecommerce_listing."
            if rejection_reason == "non_detail_seed"
            else ""
        )
        await _log_pipeline_event(
            context,
            "warning",
            f"Rejected detail extraction for {context.url}: {rejection_reason}{guidance}",
        )
    return _ExtractedURLStage(fetched=fetched, records=records)










async def _run_normalization_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> _ExtractedURLStage:
    await _enter_stage(context, STAGE_NORMALIZE)
    acquisition_result = extracted.fetched.acquisition_result
    normalized_records: list[dict[str, object]] = []
    for index, record in enumerate(extracted.records, start=1):
        normalized_record, validation_errors = validate_record_for_surface(
            dict(record),
            context.surface,
            requested_fields=context.requested_fields,
            strict_types=True,
        )
        normalized_records.append(normalized_record)
        if validation_errors:
            await _log_pipeline_event(
                context,
                "warning",
                "Schema validation cleaned record "
                f"{index} for {context.url}: {'; '.join(validation_errors)}",
            )
    if not _suppress_empty_downstream_record_logs(
        acquisition_result,
        normalized_records,
    ):
        await _log_pipeline_event(
            context,
            "info",
            f"Normalized {len(normalized_records)} record(s) for persistence",
        )
    return _ExtractedURLStage(fetched=extracted.fetched, records=normalized_records)
























async def _apply_extraction_post_processing(
    context: _URLProcessingContext,
    *,
    acquisition_result,
    records: list[dict[str, object]],
    selector_rules: list[dict[str, object]],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    if "detail" in context.surface and records:
        records, selector_rules = await apply_selector_self_heal(
            context.session,
            run=context.run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
            adapter_records=acquisition_result.adapter_records,
            network_payloads=acquisition_result.network_payloads,
            selector_rules=selector_rules,
        )
    if not _browser_result_is_extractable(acquisition_result):
        return records, selector_rules
    if not context.run.settings_view.llm_enabled():
        _annotate_field_repair(
            records,
            surface=context.surface,
            requested_fields=list(context.requested_fields),
            llm_enabled=False,
            action="skipped",
            reason="llm_disabled",
        )
        return records, selector_rules
    records = await apply_direct_record_llm_fallback_impl(
        context.session,
        run=context.run,
        page_url=acquisition_result.final_url,
        html=acquisition_result.html,
        records=records,
        resolve_run_config_fn=resolve_run_config,
        extract_records_fn=extract_records_directly_with_llm,
    )
    if "detail" in context.surface and records:
        records = await apply_llm_fallback(
            context.session,
            run=context.run,
            page_url=acquisition_result.final_url,
            html=acquisition_result.html,
            records=records,
        )
    _annotate_field_repair(
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
        llm_enabled=True,
        action="checked",
        reason=None,
    )
    return records, selector_rules






















async def _run_persistence_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> URLProcessingResult:
    acquisition_result = extracted.fetched.acquisition_result
    raw_html_path = await persist_acquisition_artifacts(
        run_id=context.run.id,
        acquisition_result=acquisition_result,
        browser_attempted=_browser_attempted(acquisition_result),
        screenshot_required=_screenshot_required(_browser_outcome(acquisition_result)),
    )
    await _enter_stage(context, STAGE_PERSIST)
    persisted_count = await persist_extracted_records(
        context.session,
        context.run,
        extracted.records,
        acquisition_result=acquisition_result,
        raw_html_path=raw_html_path,
    )
    verdict = compute_verdict(
        is_listing="listing" in context.surface,
        blocked=_effective_blocked(acquisition_result),
        record_count=persisted_count,
    )
    if not _suppress_empty_downstream_record_logs(
        acquisition_result,
        extracted.records,
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
        verdict = VERDICT_LISTING_FAILED
    await _update_acquisition_contract_memory(
        context,
        acquisition_result=acquisition_result,
        records=extracted.records,
        persisted_count=persisted_count,
        verdict=verdict,
    )
    result_records = []
    for record in extracted.records:
        next_record = dict(record)
        next_record.pop("_field_repair", None)
        result_records.append(next_record)
    return URLProcessingResult(
        records=result_records,
        verdict=verdict,
        url_metrics=finalize_url_metrics(
            extracted.fetched.url_metrics,
            record_count=persisted_count,
        ),
    )




URLProcessingContext = _URLProcessingContext
best_adapter_result = _best_adapter_result
empty_extraction_browser_retry_decision = _empty_extraction_browser_retry_decision
resolved_url_processing_config = _resolved_url_processing_config
