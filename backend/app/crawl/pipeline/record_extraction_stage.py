from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.acquirer import PageAcquisitionResult, PageEvidence
from app.connectors.adapters.base import AdapterResult
from app.connectors.adapters.registry import run_adapter
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.crawl.profile import record_acquisition_contract_outcome
from app.core.db_utils import mapping_or_empty
from app.crawl.domain_memory_service import (
    compose_runtime_selector_rules,
    load_domain_selector_rules,
)
from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.contract_runtime import select_active_recipe
from app.extraction import extract, parse_surface
from app.extraction.contracts import ExtractionResult
from app.extraction.replay import request_from_acquisition_result
from app.crawl.pipeline.runtime_helpers import (
    log_pipeline_event as _log_pipeline_event,
    merge_browser_diagnostics as _merge_browser_diagnostics,
)
from app.acquisition.platform_policy import detect_platform_family
from app.acquisition.variant_endpoint_expansion import expand_sfcc_variant_endpoints
from app.persistence.publish import build_url_metrics
from app.persistence.extraction_memory import (
    load_release_payload,
    selector_rules_from_release,
)

from .url_processing_context import (
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)

__all__ = (
    "extract_records_for_acquisition",
    "update_acquisition_contract_memory",
)

logger = logging.getLogger(__name__)


def _session_needs_rollback(session: AsyncSession) -> bool:
    return getattr(session, "is_active", True) is False


def extract_records_for_acquisition_result(
    acquisition_result,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str,
    requested_fields: list[str] | None = None,
    selector_rules: list[dict[str, object]] | None = None,
    runtime_snapshot: dict[str, object] | None = None,
) -> ExtractionResult:
    request = request_from_acquisition_result(
        parse_surface(surface),
        acquisition_result,
        requested_url=requested_page_url,
        max_records=max_records,
        requested_fields=tuple(str(field) for field in requested_fields or ()),
        selector_rules=selector_rules,
        runtime_snapshot=runtime_snapshot or {},
    )
    return extract(request)


async def _extract_records_for_acquisition(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> tuple[ExtractionResult, list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    await _populate_adapter_artifacts(context, acquisition_result)
    _assign_platform_family(acquisition_result)

    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    selector_rules = await _load_selector_rules(context, acquisition_result.final_url)
    await context.session.commit()
    result = await _run_record_extraction(
        context,
        acquisition_result=acquisition_result,
        selector_rules=selector_rules,
    )
    if (
        not result.records
        and "listing" in context.surface
        and getattr(acquisition_result, "method", "") == "browser"
    ):
        fallback_result = await _extract_records_from_preserved_browser_html(
            context,
            fetched,
            selector_rules=selector_rules,
        )
        if fallback_result is not None and fallback_result.records:
            result = fallback_result
    if not result.records:
        await _maybe_learn_once(
            context,
            acquisition_result=acquisition_result,
            selector_rules=selector_rules,
            result=result,
        )
    return result, selector_rules


async def _populate_adapter_artifacts(
    context: _URLProcessingContext,
    acquisition_result: PageAcquisitionResult,
) -> None:
    acquisition_result.adapter_name = None
    acquisition_result.adapter_source_type = None
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    adapter_proxy = _adapter_proxy(context)
    with logfire_span(
        "extract.tier.adapter",
        run_id=context.run.id,
        domain=normalize_domain(acquisition_result.final_url),
        surface=context.surface,
        proxy_configured=bool(adapter_proxy),
    ) as span:
        adapter_result = await _run_adapter_for_capture(
            context, acquisition_result, artifacts, adapter_proxy
        )
        set_logfire_attributes(
            span,
            adapter=(adapter_result.adapter_name if adapter_result else None),
            artifact_count=(len(adapter_result.artifacts) if adapter_result else 0),
        )
    if adapter_result is None or not adapter_result.artifacts:
        artifacts.pop("adapter_artifacts", None)
        acquisition_result.artifacts = artifacts
        return
    artifacts["adapter_artifacts"] = adapter_result.artifacts
    acquisition_result.artifacts = artifacts
    acquisition_result.adapter_name = adapter_result.adapter_name or None
    acquisition_result.adapter_source_type = adapter_result.source_type or None


def _adapter_proxy(context: _URLProcessingContext) -> str | None:
    config = getattr(context, "config", None)
    return next(
        (
            str(proxy).strip()
            for proxy in getattr(config, "proxy_list", ()) or ()
            if str(proxy).strip()
        ),
        None,
    )


async def _run_adapter_for_capture(
    context: _URLProcessingContext,
    acquisition_result: PageAcquisitionResult,
    artifacts: dict[str, object],
    proxy: str | None,
) -> AdapterResult | None:
    html_inputs = dict.fromkeys(
        value
        for value in (
            str(acquisition_result.html or "").strip(),
            str(artifacts.get("full_rendered_html") or "").strip(),
        )
        if value
    )
    for html in html_inputs:
        candidate = await run_adapter(
            acquisition_result.final_url,
            html,
            context.surface,
            proxy=proxy,
        )
        if candidate is not None and candidate.artifacts:
            return candidate
    return None


def _browser_retry_pending(
    context: _URLProcessingContext,
    acquisition_result: PageAcquisitionResult,
    result: ExtractionResult,
) -> bool:
    """True when a browser retry rung will still run, so learning is deferred.

    Learning fires only after the FINAL browser rung, so the defer decision is
    driven by the REMAINING RUNG BUDGET: after rung 1 a retry can still be
    required (``browser_escalation_count < max_attempts``) while
    ``browser_attempted`` is already true, so a bare browser-attempted check
    would latch learning too early — before the multi-rung ladder is exhausted.
    The initial-browser short-circuit is preserved: with nothing escalated yet
    (``browser_escalation_count == 0``) but the first pass already browser-fetched,
    ``retry/stage.py`` short-circuits and climbs NO rung, so learning may fire now
    (a pure budget check would defer forever for those initial-browser pages).
    """

    retry_request = result.retry_request
    if retry_request is None or not retry_request.required:
        return False
    if (
        context.browser_escalation_count == 0
        and PageEvidence.from_acquisition_result(acquisition_result).browser_attempted
    ):
        return False
    return context.browser_escalation_count < retry_request.max_attempts


async def _maybe_learn_once(
    context: _URLProcessingContext,
    *,
    acquisition_result: PageAcquisitionResult,
    selector_rules: list[dict[str, object]],
    result: ExtractionResult,
) -> None:
    """Invoke the LEARN-ONCE compiler once when floors stay empty.

    Gated inside ``learn_recipe_after_extraction`` on config, ``llm_enabled``,
    the per-surface allow-list, and a not-yet-learned template. Failures never
    change the crawl verdict.
    """

    from app.crawl.pipeline.learn_once import learn_recipe_after_extraction

    # Finding 5: at most one learn attempt per URL. The same context threads
    # through the browser retry, so short-circuit once learning has been attempted.
    if context.learn_once_attempted:
        return
    # Learn only after the FINAL attempt: if a browser retry is still pending, the
    # post-browser pass is the single learn attempt (and, with finding 6, the
    # HTTP-only first pass would not call the model anyway).
    if _browser_retry_pending(context, acquisition_result, result):
        return
    context.learn_once_attempted = True

    runtime_snapshot = await _load_runtime_snapshot(context)
    request = request_from_acquisition_result(
        parse_surface(context.surface),
        acquisition_result,
        requested_url=context.url,
        max_records=context.config.max_records,
        requested_fields=tuple(str(field) for field in context.requested_fields),
        selector_rules=selector_rules,
        runtime_snapshot=runtime_snapshot,
    )
    is_new_template = (
        select_active_recipe(
            runtime_snapshot,
            surface=context.surface,
            url=acquisition_result.final_url or context.url,
        )
        is None
    )
    try:
        if is_new_template:
            learned = await learn_recipe_after_extraction(
                context.session,
                request=request,
                result=result,
                run_id=context.run.id,
                llm_enabled=context.run.settings_view.llm_enabled(),
                is_new_template=is_new_template,
            )
            if learned:
                await context.session.commit()
        else:
            # A recipe exists for this route yet the floors are empty: the stored
            # recipe drifted. Count the failure and self-heal past the threshold.
            from app.crawl.pipeline.learn_once import note_recipe_drift_after_replay

            suspended = await note_recipe_drift_after_replay(
                context.session,
                request=request,
            )
            if suspended:
                await context.session.commit()
    except Exception:  # pragma: no cover - learning never breaks the crawl
        logger.warning("LEARN-ONCE recipe compilation failed", exc_info=True)
        if _session_needs_rollback(context.session):
            await context.session.rollback()


def _assign_platform_family(acquisition_result: PageAcquisitionResult) -> None:
    platform_family = detect_platform_family(
        acquisition_result.final_url,
        acquisition_result.html,
    )
    if not platform_family and acquisition_result.adapter_name:
        platform_family = acquisition_result.adapter_name
    acquisition_result.platform_family = platform_family or None


async def _load_runtime_snapshot(context: _URLProcessingContext) -> dict[str, object]:
    snapshot = await load_release_payload(
        context.session, context.run.extraction_release_snapshot_id
    )
    snapshot["_release_snapshot_id"] = (
        str(context.run.extraction_release_snapshot_id)
        if context.run.extraction_release_snapshot_id is not None
        else None
    )
    return snapshot


async def _run_record_extraction(
    context: _URLProcessingContext,
    *,
    acquisition_result: PageAcquisitionResult,
    selector_rules: list[dict[str, object]],
) -> ExtractionResult:
    await _expand_variant_endpoint_payloads(context, acquisition_result)
    runtime_snapshot = await _load_runtime_snapshot(context)
    await context.session.commit()
    adapter_artifacts = mapping_or_empty(
        getattr(acquisition_result, "artifacts", {})
    ).get("adapter_artifacts")
    adapter_artifact_count = (
        len(adapter_artifacts) if isinstance(adapter_artifacts, list) else 0
    )
    with logfire_span(
        "extract.record_thread",
        run_id=context.run.id,
        domain=normalize_domain(acquisition_result.final_url),
        surface=context.surface,
        adapter_artifact_count=adapter_artifact_count,
        network_payload_count=len(acquisition_result.network_payloads or []),
        selector_rule_count=len(selector_rules or []),
    ) as span:
        result = await asyncio.to_thread(
            extract_records_for_acquisition_result,
            acquisition_result,
            context.surface,
            max_records=context.config.max_records,
            requested_page_url=context.url,
            requested_fields=list(context.requested_fields),
            selector_rules=selector_rules,
            runtime_snapshot=runtime_snapshot,
        )
        set_logfire_attributes(
            span,
            record_count=len(result.records),
            verdict=result.verdict,
        )
        return result


async def _expand_variant_endpoint_payloads(
    context: _URLProcessingContext,
    acquisition_result: PageAcquisitionResult,
) -> None:
    if str(context.surface or "").strip().lower() != "ecommerce_detail":
        return
    html_text = str(getattr(acquisition_result, "html", "") or "")
    page_url = str(getattr(acquisition_result, "final_url", "") or context.url)
    payloads = list(getattr(acquisition_result, "network_payloads", []) or [])
    request = getattr(acquisition_result, "request", None)
    proxy_list = list(
        getattr(request, "proxy_list", None)
        or getattr(context.config, "proxy_list", None)
        or []
    )
    proxy = str(proxy_list[0] or "").strip() if proxy_list else None
    try:
        extra = await expand_sfcc_variant_endpoints(
            page_url=page_url,
            html_text=html_text,
            existing_payloads=payloads,
            proxy=proxy,
        )
    except Exception as exc:
        diagnostics = dict(
            getattr(acquisition_result, "acquisition_diagnostics", {}) or {}
        )
        diagnostics["sfcc_variant_endpoint_expansion_error"] = type(exc).__name__
        acquisition_result.acquisition_diagnostics = diagnostics
        logger.warning("SFCC variant endpoint expansion failed", exc_info=True)
        try:
            _log_pipeline_event(
                context,
                "warning",
                "SFCC variant endpoint expansion failed; continuing deterministic extraction",
            )
        except Exception:
            logger.warning(
                "Failed to persist SFCC variant endpoint expansion diagnostic",
                exc_info=True,
            )
        return
    if not extra:
        return
    acquisition_result.network_payloads = [*payloads, *extra]
    diagnostics = dict(getattr(acquisition_result, "acquisition_diagnostics", {}) or {})
    diagnostics["sfcc_variant_endpoint_payload_count"] = len(extra)
    acquisition_result.acquisition_diagnostics = diagnostics


async def _extract_records_from_preserved_browser_html(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    selector_rules: list[dict[str, object]],
) -> ExtractionResult | None:
    acquisition_result = fetched.acquisition_result
    browser_diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    if not bool(browser_diagnostics.get("traversal_activated")):
        return None
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    rendered_html = str(artifacts.get("full_rendered_html") or "").strip()
    if not rendered_html or rendered_html == str(acquisition_result.html or "").strip():
        return None
    original_html = acquisition_result.html
    acquisition_result.html = rendered_html
    runtime_snapshot = await _load_runtime_snapshot(context)
    try:
        fallback_result = await asyncio.to_thread(
            extract_records_for_acquisition_result,
            acquisition_result,
            context.surface,
            max_records=context.config.max_records,
            requested_page_url=context.url,
            requested_fields=list(context.requested_fields),
            selector_rules=selector_rules,
            runtime_snapshot=runtime_snapshot,
        )
    finally:
        acquisition_result.html = original_html
    if not fallback_result.records:
        _log_pipeline_event(
            context,
            "warning",
            "Traversal yielded no extractable listing records; fallback extraction on full rendered HTML also returned 0 records",
        )
        _merge_browser_diagnostics(
            acquisition_result,
            {
                "traversal_fallback_used": True,
                "traversal_fallback_recovered": False,
                "traversal_fallback_record_count": 0,
            },
        )
        fetched.url_metrics = build_url_metrics(
            acquisition_result,
            requested_fields=list(context.requested_fields),
        )
        return None
    artifacts["traversal_composed_html"] = str(acquisition_result.html or "")
    acquisition_result.artifacts = artifacts
    acquisition_result.html = rendered_html
    _log_pipeline_event(
        context,
        "info",
        f"Traversal yielded 0 extractable records; recovered {len(fallback_result.records)} record(s) from full rendered HTML",
    )
    _merge_browser_diagnostics(
        acquisition_result,
        {
            "traversal_fallback_used": True,
            "traversal_fallback_recovered": True,
            "traversal_fallback_record_count": len(fallback_result.records),
        },
    )
    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    return fallback_result


async def _load_selector_rules(
    context: _URLProcessingContext,
    page_url: str,
) -> list[dict[str, object]]:
    if context.run.extraction_release_snapshot_id is not None:
        release = await load_release_payload(
            context.session, context.run.extraction_release_snapshot_id
        )
        saved_rules = selector_rules_from_release(release, surface=context.surface)
    else:
        saved_rules = await load_domain_selector_rules(
            context.session,
            domain=normalize_domain(page_url),
            surface=context.surface,
        )
    return compose_runtime_selector_rules(
        saved_rules,
        context.run.settings_view.extraction_contract(),
    )


async def _update_acquisition_contract_memory(
    context: _URLProcessingContext,
    *,
    acquisition_result,
    url_result,
) -> None:
    domain = normalize_domain(
        getattr(acquisition_result, "final_url", "") or context.url
    )
    if not domain:
        return
    await record_acquisition_contract_outcome(
        context.session,
        domain=domain,
        surface=context.surface,
        source_run_id=int(context.run.id),
        acquisition_result=acquisition_result,
        url_result=url_result,
    )


extract_records_for_acquisition = _extract_records_for_acquisition
update_acquisition_contract_memory = _update_acquisition_contract_memory
