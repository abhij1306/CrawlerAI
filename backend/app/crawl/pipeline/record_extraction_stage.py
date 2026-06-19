from __future__ import annotations

import asyncio
import inspect
import json

from app.acquisition.acquirer import AcquisitionResult
from app.acquisition.runtime_plan import AcquisitionPlan
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.connectors.adapters.base import AdapterResult
from app.connectors.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.crawl.profile import record_acquisition_contract_outcome
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.db_utils import mapping_or_empty
from app.crawl.domain_memory_service import (
    compose_runtime_selector_rules,
    load_domain_selector_rules,
)
from app.core.domain_utils import normalize_domain
from app.core.records.field_policy import repair_target_fields_for_surface
from app.extraction.contracts import ExtractionResult
from app.crawl.pipeline.extract_records import (
    extract_records_for_acquisition_result,
)
from app.crawl.pipeline.runtime_helpers import (
    browser_result_is_extractable as _browser_result_is_extractable,
    effective_blocked as _effective_blocked,
    log_pipeline_event as _log_pipeline_event,
    merge_browser_diagnostics as _merge_browser_diagnostics,
)
from app.acquisition.platform_policy import detect_platform_family
from app.persistence.publish import build_url_metrics

from .url_processing_context import (
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)

__all__ = (
    "best_adapter_result",
    "extract_records_for_acquisition",
    "update_acquisition_contract_memory",
)


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


async def _populate_adapter_artifacts(
    context: _URLProcessingContext,
    acquisition_result: AcquisitionResult,
) -> None:
    acquisition_result.adapter_name = None
    acquisition_result.adapter_source_type = None

    adapter_results: list[AdapterResult] = []
    adapter_proxy = next(
        (
            str(proxy).strip()
            for proxy in context.config.proxy_list or []
            if str(proxy).strip()
        ),
        None,
    )
    with logfire_span(
        "extract.tier.adapter",
        run_id=context.run.id,
        domain=normalize_domain(acquisition_result.final_url),
        surface=context.surface,
        proxy_configured=bool(adapter_proxy),
    ) as span:
        for html in [
            str(acquisition_result.html or ""),
            *_adapter_browser_artifact_htmls(acquisition_result),
            *_adapter_network_payload_inputs(acquisition_result),
        ]:
            from app.crawl.pipeline import extraction_loop

            adapter_runner = getattr(extraction_loop, "run_adapter", run_adapter)
            adapter_kwargs = (
                {"proxy": adapter_proxy}
                if adapter_proxy
                and "proxy" in inspect.signature(adapter_runner).parameters
                else {}
            )
            adapter_result = await adapter_runner(
                acquisition_result.final_url,
                html,
                context.surface,
                **adapter_kwargs,
            )
            if adapter_result is not None and list(adapter_result.artifacts or []):
                adapter_results.append(adapter_result)
                break
        set_logfire_attributes(
            span,
            adapter_result_count=len(adapter_results),
            adapter_names=[
                str(result.adapter_name or "")
                for result in adapter_results
                if str(result.adapter_name or "").strip()
            ],
            record_count=sum(
                len(list(result.artifacts or [])) for result in adapter_results
            ),
        )
    adapter_result = _best_adapter_result(adapter_results)
    if (
        adapter_result is None or not list(adapter_result.artifacts or [])
    ) and _effective_blocked(acquisition_result):
        adapter_result = await try_blocked_adapter_recovery(
            acquisition_result.final_url,
            AcquisitionPlan(
                surface=context.surface,
                proxy_list=tuple(context.config.proxy_list or []),
                traversal_mode=context.config.traversal_mode,
                max_pages=context.config.max_pages,
                max_scrolls=context.config.max_scrolls,
                max_records=context.config.max_records,
                sleep_ms=context.config.sleep_ms,
                adapter_recovery_enabled=True,
            ),
            proxy_list=list(context.config.proxy_list or []),
        )
    if adapter_result is not None and list(adapter_result.artifacts or []):
        artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
        artifacts["adapter_artifacts"] = list(adapter_result.artifacts or [])
        acquisition_result.artifacts = artifacts
        acquisition_result.adapter_name = adapter_result.adapter_name or None
        acquisition_result.adapter_source_type = adapter_result.source_type or None


def _best_adapter_result(adapter_results: list[AdapterResult]) -> AdapterResult | None:
    if not adapter_results:
        return None
    best = max(
        adapter_results,
        key=lambda result: _adapter_result_score(
            list(getattr(result, "artifacts", []) or [])
        ),
    )
    return AdapterResult(
        artifacts=list(best.artifacts or []),
        source_type=best.source_type,
        adapter_name=best.adapter_name,
    )


def _adapter_result_score(records: list[object]) -> tuple[int, int]:
    populated = 0
    for record in records:
        if not isinstance(record, dict):
            continue
        populated += sum(
            value not in (None, "", [], {})
            for key, value in record.items()
            if not str(key).startswith("_")
        )
    return len(records), populated


def _adapter_browser_artifact_htmls(
    acquisition_result: AcquisitionResult,
) -> list[str]:
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    seen = {str(getattr(acquisition_result, "html", "") or "").strip()}
    htmls: list[str] = []
    for value in (
        artifacts.get("full_rendered_html"),
        _rendered_listing_fragments_html(artifacts.get("rendered_listing_fragments")),
    ):
        html = str(value or "").strip()
        if not html or html in seen:
            continue
        seen.add(html)
        htmls.append(html)
    return htmls


def _adapter_network_payload_inputs(
    acquisition_result: AcquisitionResult,
) -> list[str]:
    inputs: list[str] = []
    seen: set[str] = set()
    identity_tokens = _adapter_payload_identity_tokens(acquisition_result.final_url)
    for payload in list(getattr(acquisition_result, "network_payloads", []) or []):
        if not isinstance(payload, dict):
            continue
        body = payload.get("body")
        if body in (None, "", [], {}):
            continue
        try:
            serialized = json.dumps(body, ensure_ascii=True, separators=(",", ":"))
        except (TypeError, ValueError):
            continue
        serialized_key = serialized.casefold()
        if identity_tokens and not any(
            token in serialized_key for token in identity_tokens
        ):
            continue
        if not serialized or serialized in seen:
            continue
        seen.add(serialized)
        inputs.append(serialized)
    return inputs


def _adapter_payload_identity_tokens(page_url: str) -> set[str]:
    from app.core.records.url_identity import detail_identity_codes_from_url

    min_length = max(
        0, int(crawler_runtime_settings.adapter_payload_identity_min_token_length)
    )
    return {
        str(token).casefold()
        for token in detail_identity_codes_from_url(page_url)
        if len(str(token or "").strip()) >= min_length
    }


def _rendered_listing_fragments_html(value: object) -> str:
    if not isinstance(value, list):
        return ""
    fragments = [
        fragment for fragment in (str(item or "").strip() for item in value) if fragment
    ]
    if not fragments:
        return ""
    joined = "\n".join(fragments)
    return f"<html><body>{joined}</body></html>"


def _assign_platform_family(acquisition_result: AcquisitionResult) -> None:
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
    acquisition_result: AcquisitionResult,
    selector_rules: list[dict[str, object]],
) -> ExtractionResult:
    from app.crawl.pipeline import extraction_loop

    extract_records_impl = getattr(
        extraction_loop,
        "extract_records_for_acquisition_result",
        extract_records_for_acquisition_result,
    )
    with logfire_span(
        "extract.record_thread",
        run_id=context.run.id,
        domain=normalize_domain(acquisition_result.final_url),
        surface=context.surface,
        adapter_artifact_count=len(
            list(mapping_or_empty(getattr(acquisition_result, "artifacts", {})).get("adapter_artifacts") or [])
        ),
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
        )
        set_logfire_attributes(
            span,
            record_count=len(result.records),
            verdict=result.verdict,
        )
        return result


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
        requested_fields=repair_target_fields_for_surface(
            context.surface,
            list(context.requested_fields),
        ),
        records=records,
        persisted_count=persisted_count,
        verdict=verdict,
        blocked=_effective_blocked(acquisition_result),
        page_url=getattr(acquisition_result, "final_url", "") or context.url,
        network_payloads=list(getattr(acquisition_result, "network_payloads", []) or []),
    )


extract_records_for_acquisition = _extract_records_for_acquisition
best_adapter_result = _best_adapter_result
update_acquisition_contract_memory = _update_acquisition_contract_memory


def _record_list(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [record for record in value if isinstance(record, dict)]
