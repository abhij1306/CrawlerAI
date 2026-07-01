from __future__ import annotations

import asyncio
import logging

from app.acquisition.acquirer import PageAcquisitionResult
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.crawl.profile import record_acquisition_contract_outcome
from app.core.db_utils import mapping_or_empty
from app.crawl.domain_memory_service import (
    compose_runtime_selector_rules,
    load_domain_selector_rules,
)
from app.core.domain_utils import normalize_domain
from app.core.records.field_policy import acquisition_contract_fields_for_surface
from app.extraction import extract, parse_surface
from app.extraction.contracts import ExtractionResult
from app.extraction.replay import request_from_acquisition_result
from app.crawl.pipeline.runtime_helpers import (
    effective_blocked as _effective_blocked,
    log_pipeline_event as _log_pipeline_event,
    merge_browser_diagnostics as _merge_browser_diagnostics,
)
from app.acquisition.platform_policy import detect_platform_family
from app.acquisition.variant_endpoint_expansion import expand_sfcc_variant_endpoints
from app.persistence.publish import build_url_metrics

from .url_processing_context import (
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)

__all__ = (
    "extract_records_for_acquisition",
    "update_acquisition_contract_memory",
)

logger = logging.getLogger(__name__)


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
    _assign_platform_family(acquisition_result)

    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    selector_rules = await _load_selector_rules(context, acquisition_result.final_url)
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
    return result, selector_rules


def _assign_platform_family(acquisition_result: PageAcquisitionResult) -> None:
    from app.crawl.pipeline import extraction_loop

    detect_family = getattr(
        extraction_loop,
        "detect_platform_family",
        detect_platform_family,
    )
    platform_family = detect_family(
        acquisition_result.final_url,
        acquisition_result.html,
    )
    if not platform_family and acquisition_result.adapter_name:
        platform_family = acquisition_result.adapter_name
    acquisition_result.platform_family = platform_family or None


async def _run_record_extraction(
    context: _URLProcessingContext,
    *,
    acquisition_result: PageAcquisitionResult,
    selector_rules: list[dict[str, object]],
) -> ExtractionResult:
    from app.crawl.pipeline import extraction_loop

    await _expand_variant_endpoint_payloads(context, acquisition_result)
    extract_records_impl = getattr(
        extraction_loop,
        "extract_records_for_acquisition_result",
        extract_records_for_acquisition_result,
    )
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
            extract_records_impl,
            acquisition_result,
            context.surface,
            max_records=context.config.max_records,
            requested_page_url=context.url,
            requested_fields=list(context.requested_fields),
            selector_rules=selector_rules,
            runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
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
            await _log_pipeline_event(
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
    from app.crawl.pipeline import extraction_loop as _extraction_loop

    extract_impl = getattr(
        _extraction_loop,
        "extract_records_for_acquisition_result",
        extract_records_for_acquisition_result,
    )
    original_html = acquisition_result.html
    acquisition_result.html = rendered_html
    try:
        fallback_result = await asyncio.to_thread(
            extract_impl,
            acquisition_result,
            context.surface,
            max_records=context.config.max_records,
            requested_page_url=context.url,
            requested_fields=list(context.requested_fields),
            selector_rules=selector_rules,
            runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        )
    finally:
        acquisition_result.html = original_html
    if not fallback_result.records:
        await _log_pipeline_event(
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
    await _log_pipeline_event(
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
    from app.crawl.pipeline import extraction_loop

    load_rules = getattr(
        extraction_loop,
        "load_domain_selector_rules",
        load_domain_selector_rules,
    )
    saved_rules = await load_rules(
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
    records: list[dict[str, object]],
    persisted_count: int,
    verdict: str,
) -> None:
    domain = normalize_domain(
        getattr(acquisition_result, "final_url", "") or context.url
    )
    if not domain:
        return
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    await record_acquisition_contract_outcome(
        context.session,
        domain=domain,
        surface=context.surface,
        source_run_id=int(context.run.id),
        method=getattr(acquisition_result, "method", None),
        browser_engine=str(diagnostics.get("browser_engine") or "").strip().lower(),
        browser_diagnostics=dict(diagnostics),
        requested_fields=acquisition_contract_fields_for_surface(
            context.surface,
            list(context.requested_fields),
        ),
        records=records,
        persisted_count=persisted_count,
        verdict=verdict,
        blocked=_effective_blocked(acquisition_result),
        page_url=getattr(acquisition_result, "final_url", "") or context.url,
        network_payloads=list(
            getattr(acquisition_result, "network_payloads", []) or []
        ),
    )


extract_records_for_acquisition = _extract_records_for_acquisition
update_acquisition_contract_memory = _update_acquisition_contract_memory
