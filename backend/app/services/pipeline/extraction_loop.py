from __future__ import annotations

import time

from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.models.crawl_run import CrawlRun
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition.acquirer import acquire as _acquire
from app.services.acquisition.browser_runtime import real_chrome_browser_available
from app.services.acquisition.host_protection_memory import note_host_hard_block
from app.services.acquisition.runtime import is_non_retryable_http_status
from app.services.config import observability as obs_config
from app.services.config.pipeline_reasons import NON_RETRYABLE_HTTP_STATUS_REASON
from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.db_utils import mapping_or_empty
from app.services.shared.field_coerce import object_list as _object_list
from app.services.domain_memory_service import load_domain_selector_rules
from app.services.domain_utils import normalize_domain
from app.services.shared.field_coerce import validate_record_for_surface
from app.services.llm.config_service import resolve_run_config
from app.services.llm.runtime import (
    extract_records_directly as extract_records_directly_with_llm,
)
from app.services.adapters.registry import run_adapter
from app.services.extract.detail.assembly.record_assembly import (
    detail_record_rejection_reason,
    infer_detail_failure_reason,
)
from app.services.extract.content_surface_extractor import CONTENT_DETAIL_SURFACES
from app.services.platform_policy import detect_platform_family
from app.services.pipeline.extract_records import extract_records
from app.services.pipeline.direct_record_fallback import (
    apply_direct_record_llm_fallback as apply_direct_record_llm_fallback_impl,
    apply_llm_fallback,
)
from app.services.publish import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_ERROR,
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
from app.services.selector_auto_learn import auto_save_dom_observed_selectors
from app.services.selector_self_heal import apply_selector_self_heal
from sqlalchemy.ext.asyncio import AsyncSession

from .extraction_retry_decision import (
    annotate_field_repair as _annotate_field_repair,
    empty_extraction_browser_retry_decision as _empty_extraction_browser_retry_decision,
)
from .retry import (
    apply_detail_rejection_guard as _apply_detail_rejection_guard,
    build_acquisition_request as _build_acquisition_request,
    log_extraction_outcome as _log_extraction_outcome,
    remaining_url_budget_seconds as _remaining_url_budget_seconds,
    retry_detail_challenge_shell_with_real_chrome as _retry_detail_challenge_shell_with_real_chrome,
    retry_empty_extraction_with_browser as _retry_empty_extraction_with_browser,
    retry_listing_integrity_with_stronger_tier as _retry_listing_integrity_with_stronger_tier,
    retry_low_quality_extraction_with_browser as _retry_low_quality_extraction_with_browser,
    retry_patchright_detail_rejection_with_real_chrome as _retry_patchright_detail_rejection_with_real_chrome,
)
from .persistence import (
    persist_acquisition_artifacts,
    persist_extracted_records,
    persist_run_trace,
)
from .record_extraction_stage import (
    best_adapter_result,
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
    browser_result_is_extractable as _browser_result_is_extractable,
    effective_blocked as _effective_blocked,
    mark_run_failed,
    record_detail_expansion_extraction_outcome as _record_detail_expansion_extraction_outcome,
    screenshot_required as _screenshot_required,
    suppress_empty_downstream_record_logs as _suppress_empty_downstream_record_logs,
    log_pipeline_event as _log_pipeline_event,
    set_stage,
)
from .types import URLProcessingConfig, URLProcessingResult
from .url_processing_context import (
    ExtractedURLStage as _ExtractedURLStage,
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
    resolved_url_processing_config as _resolved_url_processing_config,
)

__all__ = [
    "STAGE_ACQUIRE",
    "STAGE_EXTRACT",
    "STAGE_NORMALIZE",
    "STAGE_PERSIST",
    "URLProcessingContext",
    "_remaining_url_budget_seconds",
    "best_adapter_result",
    "detail_record_rejection_reason",
    "detect_platform_family",
    "empty_extraction_browser_retry_decision",
    "extract_records",
    "infer_detail_failure_reason",
    "load_domain_selector_rules",
    "mark_run_failed",
    "note_host_hard_block",
    "process_single_url",
    "real_chrome_browser_available",
    "resolved_url_processing_config",
    "run_adapter",
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
        extracted = await _run_normalization_stage(context, extracted)
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
    prefetched_acquisition: AcquisitionResult | None,
) -> _FetchedURLStage:
    with logfire_span(
        "pipeline.acquire",
        run_id=context.run.id,
        domain=normalize_domain(context.url),
        surface=context.surface,
        prefetched=bool(prefetched_acquisition),
    ) as span:
        acquisition_request = await _build_acquisition_request(context)
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

    _record_acquire_timeline(context, acquisition_result)

    return _FetchedURLStage(
        context=context,
        acquisition_result=acquisition_result,
        url_metrics=build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        ),
    )


def _record_acquire_timeline(
    context: _URLProcessingContext,
    acquisition_result,
) -> None:
    """Project acquisition diagnostics into the ordered RunTrace acquire timeline.

    Closes the launch -> rendered blackhole: navigation strategy, each readiness
    probe, interstitial action, policy decisions, and escalation become ordered
    events instead of only summed phase timings. No-op when tracing is disabled.
    """
    trace = context.trace
    if trace is None:
        return
    method = str(getattr(acquisition_result, "method", "") or "")
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    timings = mapping_or_empty(diagnostics.get("phase_timings_ms"))

    for decision in _object_list(diagnostics.get("policy_decisions")):
        if isinstance(decision, dict):
            trace.record_acquire_event(
                obs_config.ACQUIRE_EVENT_POLICY_DECISION,
                detail={
                    "action": decision.get("action"),
                    "reason": decision.get("reason"),
                    "stage": decision.get("stage"),
                },
            )

    host_outcome = mapping_or_empty(diagnostics.get("host_outcome"))
    if host_outcome:
        trace.record_host_outcome(host_outcome)

    if method != "browser":
        trace.record_acquire_event(
            obs_config.ACQUIRE_EVENT_HTTP_FETCH,
            detail={
                "method": method,
                "status_code": getattr(acquisition_result, "status_code", None),
                "blocked": bool(getattr(acquisition_result, "blocked", False)),
            },
        )
        return

    if method == "browser":
        trace.record_acquire_event(
            obs_config.ACQUIRE_EVENT_NAVIGATION,
            detail={
                "engine": diagnostics.get("browser_engine"),
                "strategy": diagnostics.get("navigation_strategy"),
                "reason": diagnostics.get("browser_reason"),
            },
            duration_ms=_as_int(timings.get("navigation")),
        )
        for probe in _object_list(diagnostics.get("readiness_probes")):
            if isinstance(probe, dict):
                trace.record_acquire_event(
                    obs_config.ACQUIRE_EVENT_READINESS_PROBE,
                    detail={
                        "stage": probe.get("stage"),
                        "is_ready": probe.get("is_ready"),
                        "visible_text_length": probe.get("visible_text_length"),
                        "detail_like": probe.get("detail_like"),
                        "listing_card_count": probe.get("listing_card_count"),
                    },
                )
        interstitial = mapping_or_empty(diagnostics.get("interstitial"))
        if interstitial:
            interstitial_status = str(interstitial.get("status") or "").strip().lower()
            interstitial_timing_key = (
                obs_config.INTERSTITIAL_DISMISSAL_TIMING_KEY
                if interstitial_status == "dismissed"
                else obs_config.INTERSTITIAL_PROBE_TIMING_KEY
            )
            trace.record_acquire_event(
                obs_config.ACQUIRE_EVENT_INTERSTITIAL,
                detail={"status": interstitial.get("status")},
                duration_ms=_as_int(timings.get(interstitial_timing_key)),
            )
        challenge_wait = _as_int(timings.get("challenge_wait"))
        if challenge_wait:
            trace.record_acquire_event(
                obs_config.ACQUIRE_EVENT_CHALLENGE,
                detail={"outcome": diagnostics.get("browser_outcome")},
                duration_ms=challenge_wait,
            )
        escalation_lane = diagnostics.get("escalation_lane")
        if escalation_lane:
            trace.record_acquire_event(
                obs_config.ACQUIRE_EVENT_ESCALATION,
                detail={
                    "lane": escalation_lane,
                    "engine": diagnostics.get("browser_engine"),
                },
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
    records, selector_rules = await extract_records_for_acquisition(
        context,
        fetched,
    )
    set_logfire_attributes(
        span,
        initial_record_count=len(records),
        selector_rule_count=len(selector_rules),
        adapter=getattr(acquisition_result, "adapter_name", None),
        platform=getattr(acquisition_result, "platform_family", None),
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
    if _is_content_detail_surface(context.surface):
        await _log_extraction_outcome(context, acquisition_result, records)
        _record_extraction_trace(context, records)
        set_logfire_attributes(span, final_record_count=len(records))
        return _ExtractedURLStage(fetched=fetched, records=records)
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
    if retry_stage is not None:
        set_logfire_attributes(span, retry="real_chrome_challenge")
        return retry_stage
    if rejection_reason != "challenge_shell":
        retry_stage = await _retry_patchright_detail_rejection_with_real_chrome(
            context,
            fetched,
            rejection_reason=rejection_reason,
        )
        if retry_stage is not None:
            set_logfire_attributes(span, retry="real_chrome_rejection")
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
    _record_extraction_trace(context, records)
    set_logfire_attributes(
        span,
        final_record_count=len(records),
        rejection_reason=rejection_reason,
    )
    return _ExtractedURLStage(fetched=fetched, records=records)


def _record_extraction_trace(
    context: _URLProcessingContext,
    records: list[dict[str, object]],
) -> None:
    """Project extraction internals into the RunTrace (observe-only).

    Closes the extraction blackhole: tier execution (`_extraction_tiers`), the
    skip-DOM decision (`_dom_skip_decision`), and per-high-value-field winning
    source (`_field_sources`) become first-class trace data. No-op when tracing
    is disabled. Reads only fields the extractor already attaches; never mutates
    the record or changes selection.
    """
    trace = getattr(context, "trace", None)
    if trace is None:
        return
    primary = next(
        (record for record in records if isinstance(record, dict)),
        None,
    )
    if primary is None:
        return

    tiers = mapping_or_empty(primary.get("_extraction_tiers"))
    completed = tiers.get("completed")
    if isinstance(completed, list):
        trace.record_completed_tiers([str(item) for item in completed])
        dom_in_completed = any(
            str(item).strip().lower() == obs_config.EXTRACTION_TIER_DOM
            for item in completed
        )
    else:
        dom_in_completed = False

    skip_decision = mapping_or_empty(primary.get("_dom_skip_decision"))
    if skip_decision:
        trace.record_skip_dom_decision(
            dom_skipped=bool(skip_decision.get("dom_skipped", not dom_in_completed)),
            confidence=_as_float(skip_decision.get("confidence")),
            threshold=_as_float(skip_decision.get("threshold")),
            dom_completion_reason=str(skip_decision.get("reason") or "") or None,
        )

    field_sources = mapping_or_empty(primary.get("_field_sources"))
    for field_name, sources in field_sources.items():
        source_list = sources if isinstance(sources, list) else [sources]
        winning_source = next(
            (str(item) for item in source_list if str(item or "").strip()),
            "",
        )
        if not winning_source:
            continue
        value = primary.get(field_name)
        trace.record_field_candidate(
            str(field_name),
            source=winning_source,
            won=True,
            value_preview="" if value in (None, "", [], {}) else str(value),
        )
    trace_fields = set(field_sources)
    trace_field_names = getattr(trace, "trace_field_names", None)
    if callable(trace_field_names):
        trace_fields.update(str(field_name) for field_name in trace_field_names())
    for field_name in sorted(trace_fields):
        source_values = field_sources.get(field_name)
        source_list = source_values if isinstance(source_values, list) else [source_values]
        trace.record_field_state(
            str(field_name),
            value=primary.get(field_name),
            candidate_sources=[
                str(item)
                for item in source_list
                if str(item or "").strip()
            ],
        )


def _is_content_detail_surface(surface: str) -> bool:
    return str(surface or "").strip().lower() in CONTENT_DETAIL_SURFACES


async def _run_normalization_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> _ExtractedURLStage:
    await _enter_stage(context, STAGE_NORMALIZE)
    acquisition_result = extracted.fetched.acquisition_result
    trace = context.trace
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
            for validation_error in validation_errors:
                if trace is not None:
                    trace.record_normalize_edit(
                        field_name=f"record_{index}",
                        reason=str(validation_error),
                    )
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
    with logfire_span(
        "pipeline.llm.backfill",
        run_id=context.run.id,
        domain=normalize_domain(str(acquisition_result.final_url or context.url)),
        surface=context.surface,
        input_record_count=len(records),
        detail_surface="detail" in context.surface,
    ) as span:
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
        set_logfire_attributes(span, output_record_count=len(records))
    _annotate_field_repair(
        records,
        surface=context.surface,
        requested_fields=list(context.requested_fields),
        llm_enabled=True,
        action="checked",
        reason=None,
    )
    return records, selector_rules


# skipcq: PY-R1000
async def _run_persistence_stage(
    context: _URLProcessingContext,
    extracted: _ExtractedURLStage,
) -> URLProcessingResult:
    acquisition_result = extracted.fetched.acquisition_result
    extracted_records = list(extracted.records or [])
    with logfire_span(
        "pipeline.persist",
        run_id=context.run.id,
        domain=normalize_domain(str(acquisition_result.final_url or context.url)),
        surface=context.surface,
        input_record_count=len(extracted_records),
    ) as span:
        raw_html_path = await persist_acquisition_artifacts(
            run_id=context.run.id,
            acquisition_result=acquisition_result,
            browser_attempted=_browser_attempted(acquisition_result),
            screenshot_required=_screenshot_required(
                _browser_outcome(acquisition_result)
            ),
            surface=context.surface,
            blocked=_effective_blocked(acquisition_result),
        )
        await _enter_stage(context, STAGE_PERSIST)
        persisted_count = await persist_extracted_records(
            context.session,
            context.run,
            extracted_records,
            acquisition_result=acquisition_result,
            raw_html_path=raw_html_path,
        )
        set_logfire_attributes(
            span,
            persisted_count=persisted_count,
            artifact_path=str(raw_html_path or ""),
        )
    if persisted_count > 0:
        await auto_save_dom_observed_selectors(
            context.session,
            domain=normalize_domain(acquisition_result.final_url),
            surface=context.surface,
            html=acquisition_result.html,
            records=extracted_records,
            source_run_id=context.run.id,
        )
    verdict = compute_verdict(
        is_listing="listing" in context.surface,
        blocked=_effective_blocked(acquisition_result),
        record_count=persisted_count,
    )
    status_code = int(getattr(acquisition_result, "status_code", 0) or 0)
    if persisted_count == 0 and is_non_retryable_http_status(status_code):
        url_metrics = mapping_or_empty(extracted.fetched.url_metrics)
        url_metrics["failure_reason"] = NON_RETRYABLE_HTTP_STATUS_REASON
        extracted.fetched.url_metrics = url_metrics
        verdict = VERDICT_ERROR
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
        verdict = VERDICT_LISTING_FAILED
    trace = context.trace
    if trace is not None:
        diagnostics = mapping_or_empty(
            getattr(acquisition_result, "browser_diagnostics", {})
        )
        failure_reason = mapping_or_empty(extracted.fetched.url_metrics).get(
            "failure_reason"
        ) or diagnostics.get("failure_reason")
        trace.record_extraction_rejection(str(failure_reason or "").strip() or None)
        trace.record_verdict(verdict)
        await persist_run_trace(
            run_id=context.run.id,
            source_url=acquisition_result.final_url,
            trace=trace,
            flagged=verdict not in obs_config.TRACE_SUCCESS_VERDICTS,
        )
    await update_acquisition_contract_memory(
        context,
        acquisition_result=acquisition_result,
        records=extracted_records,
        persisted_count=persisted_count,
        verdict=verdict,
    )
    result_records = []
    for record in extracted_records:
        next_record = dict(record)
        next_record.pop("_field_repair", None)
        result_records.append(next_record)
    return URLProcessingResult(
        records=result_records,
        verdict=verdict,
        url_metrics=finalize_url_metrics(
            mapping_or_empty(extracted.fetched.url_metrics),
            record_count=persisted_count,
        ),
    )


URLProcessingContext = _URLProcessingContext
empty_extraction_browser_retry_decision = _empty_extraction_browser_retry_decision
resolved_url_processing_config = _resolved_url_processing_config


def _as_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(value))  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
