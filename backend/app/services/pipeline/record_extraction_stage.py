from __future__ import annotations

import asyncio
import inspect
import json

from app.services.acquisition.acquirer import AcquisitionResult
from app.services.acquisition_plan import AcquisitionPlan
from app.services.adapters.base import AdapterResult
from app.services.adapters.registry import run_adapter, try_blocked_adapter_recovery
from app.services.crawl.profile import record_acquisition_contract_outcome
from app.services.db_utils import mapping_or_empty
from app.services.domain_memory_service import (
    compose_runtime_selector_rules,
    load_domain_selector_rules,
)
from app.services.domain_utils import normalize_domain
from app.services.field_policy import repair_target_fields_for_surface
from app.services.pipeline.extract_records import extract_records
from app.services.pipeline.runtime_helpers import (
    browser_result_is_extractable as _browser_result_is_extractable,
    effective_blocked as _effective_blocked,
    log_event,
    merge_browser_diagnostics as _merge_browser_diagnostics,
)
from app.services.platform_policy import detect_platform_family
from app.services.publish import build_url_metrics

from .url_processing_context import (
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)


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

async def _extract_records_for_acquisition(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    acquisition_result = fetched.acquisition_result
    if not _browser_result_is_extractable(acquisition_result):
        return [], []
    await _populate_adapter_records(context, acquisition_result)
    _assign_platform_family(acquisition_result)

    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    selector_rules = await _load_selector_rules(context, acquisition_result.final_url)
    records = await _run_record_extraction(
        context,
        acquisition_result=acquisition_result,
        selector_rules=selector_rules,
    )
    if (
        not records
        and "listing" in context.surface
        and getattr(acquisition_result, "method", "") == "browser"
    ):
        fallback_records = await _extract_records_from_preserved_browser_html(
            context,
            fetched,
            selector_rules=selector_rules,
        )
        if fallback_records:
            records = fallback_records
    return records, selector_rules

async def _populate_adapter_records(
    context: _URLProcessingContext,
    acquisition_result: AcquisitionResult,
) -> None:
    acquisition_result.adapter_records = []
    acquisition_result.adapter_name = None
    acquisition_result.adapter_source_type = None

    adapter_results = []
    adapter_proxy = next(
        (
            str(proxy).strip()
            for proxy in context.config.proxy_list or []
            if str(proxy).strip()
        ),
        None,
    )
    for html in [
        str(acquisition_result.html or ""),
        *_adapter_browser_artifact_htmls(acquisition_result),
    ]:
        from app.services.pipeline import extraction_loop

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
        if adapter_result is not None and list(adapter_result.records or []):
            adapter_results.append(adapter_result)
    adapter_result = _best_adapter_result(adapter_results)
    if (
        adapter_result is None or not list(adapter_result.records or [])
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
    if adapter_result is not None and list(adapter_result.records or []):
        acquisition_result.adapter_records = list(adapter_result.records or [])
        acquisition_result.adapter_name = adapter_result.adapter_name or None
        acquisition_result.adapter_source_type = adapter_result.source_type or None

def _best_adapter_result(adapter_results: list[AdapterResult]) -> AdapterResult | None:
    if not adapter_results:
        return None
    best = max(
        adapter_results,
        key=lambda result: _adapter_result_score(
            list(getattr(result, "records", []) or [])
        ),
    )
    merged_records: dict[str, dict[str, object]] = {}
    unsourced_records: list[dict[str, object]] = []
    seen_unsourced: set[str] = set()
    for result in sorted(
        adapter_results,
        key=lambda item: _adapter_result_score(list(item.records or [])),
        reverse=True,
    ):
        for record in list(result.records or []):
            if not isinstance(record, dict):
                continue
            url = str(record.get("url") or "").strip()
            if not url:
                fingerprint = json.dumps(record, sort_keys=True, default=str)
                if fingerprint in seen_unsourced:
                    continue
                seen_unsourced.add(fingerprint)
                unsourced_records.append(dict(record))
                continue
            existing = merged_records.setdefault(url, {})
            for key, value in record.items():
                if value in (None, "", [], {}):
                    continue
                if existing.get(key) in (None, "", [], {}):
                    existing[key] = value
    return AdapterResult(
        records=[*merged_records.values(), *unsourced_records],
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
    from app.services.pipeline import extraction_loop

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
) -> list[dict[str, object]]:
    from app.services.pipeline import extraction_loop

    extract_records_impl = getattr(extraction_loop, "extract_records", extract_records)
    return await asyncio.to_thread(
        extract_records_impl,
        acquisition_result.html,
        acquisition_result.final_url,
        context.surface,
        max_records=context.config.max_records,
        requested_page_url=context.url,
        requested_fields=list(context.requested_fields),
        adapter_records=acquisition_result.adapter_records,
        network_payloads=acquisition_result.network_payloads,
        artifacts=acquisition_result.artifacts,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        content_type=acquisition_result.content_type,
        browser_diagnostics=getattr(acquisition_result, "browser_diagnostics", None),
        record_dom_observed_selectors=True,
    )

async def _extract_records_from_preserved_browser_html(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
    *,
    selector_rules: list[dict[str, object]],
) -> list[dict[str, object]]:
    acquisition_result = fetched.acquisition_result
    browser_diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    if not bool(browser_diagnostics.get("traversal_activated")):
        return []
    artifacts = mapping_or_empty(getattr(acquisition_result, "artifacts", {}))
    rendered_html = str(artifacts.get("full_rendered_html") or "").strip()
    if not rendered_html or rendered_html == str(acquisition_result.html or "").strip():
        return []
    from app.services.pipeline import extraction_loop as _extraction_loop

    extract_impl = getattr(_extraction_loop, "extract_records", extract_records)
    fallback_records = await asyncio.to_thread(
        extract_impl,
        rendered_html,
        acquisition_result.final_url,
        context.surface,
        max_records=context.config.max_records,
        requested_page_url=context.url,
        requested_fields=list(context.requested_fields),
        adapter_records=acquisition_result.adapter_records,
        network_payloads=acquisition_result.network_payloads,
        artifacts=acquisition_result.artifacts,
        selector_rules=selector_rules,
        extraction_runtime_snapshot=context.run.settings_view.extraction_runtime_snapshot(),
        content_type=acquisition_result.content_type,
        record_dom_observed_selectors=True,
    )
    if not fallback_records:
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
        return []
    artifacts["traversal_composed_html"] = str(acquisition_result.html or "")
    acquisition_result.artifacts = artifacts
    acquisition_result.html = rendered_html
    await _log_pipeline_event(
        context,
        "info",
        f"Traversal yielded 0 extractable records; recovered {len(fallback_records)} record(s) from full rendered HTML",
    )
    _merge_browser_diagnostics(
        acquisition_result,
        {
            "traversal_fallback_used": True,
            "traversal_fallback_recovered": True,
            "traversal_fallback_record_count": len(fallback_records),
        },
    )
    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    return fallback_records

async def _load_selector_rules(
    context: _URLProcessingContext,
    page_url: str,
) -> list[dict[str, object]]:
    from app.services.pipeline import extraction_loop

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
    )


extract_records_for_acquisition = _extract_records_for_acquisition
