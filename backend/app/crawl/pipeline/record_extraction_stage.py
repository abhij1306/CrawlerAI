from __future__ import annotations

import asyncio
import logging

from app.acquisition.acquirer import PageAcquisitionResult
from app.core.logfire_integration import logfire_span, set_logfire_attributes
from app.connectors.llm.config_service import validate_config_snapshot
from app.connectors.llm.cost_logging import record_llm_cost_log
from app.connectors.llm.errors import LLMErrorCategory, classify_error
from app.connectors.llm.generalized_extraction import hosted_generalized_adapter
from app.core.config.evaluation import (
    GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID,
    GENERALIZED_EXTRACTION_LLM_TASK,
    GENERALIZED_EXTRACTION_OPERATOR_RUNTIME_ARTIFACT,
    UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY,
)
from app.crawl.profile import record_acquisition_contract_outcome
from app.crawl.profile.acquisition_contract import InternalApiReplayMemoryUpdate
from app.core.db_utils import mapping_or_empty
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
from app.persistence.extraction_memory import load_release_payload

from .url_processing_context import (
    FetchedURLStage as _FetchedURLStage,
    URLProcessingContext as _URLProcessingContext,
)

__all__ = (
    "extract_records_for_acquisition",
    "update_acquisition_contract_memory",
)

logger = logging.getLogger(__name__)


class _ObservedModelAdapter:
    def __init__(self, delegate, on_start) -> None:
        self._delegate = delegate
        self._on_start = on_start

    @property
    def adapter_id(self) -> str:
        return self._delegate.adapter_id

    def predict(self, page, artifact, *, timeout_ms: int):
        self._on_start()
        return self._delegate.predict(page, artifact, timeout_ms=timeout_ms)


def extract_records_for_acquisition_result(
    acquisition_result,
    surface: str,
    *,
    max_records: int,
    requested_page_url: str,
    requested_fields: list[str] | None = None,
    runtime_snapshot: dict[str, object] | None = None,
    model_adapter=None,
) -> ExtractionResult:
    request = request_from_acquisition_result(
        parse_surface(surface),
        acquisition_result,
        requested_url=requested_page_url,
        max_records=max_records,
        requested_fields=tuple(str(field) for field in requested_fields or ()),
        runtime_snapshot=runtime_snapshot or {},
    )
    return extract(request, model_adapter=model_adapter)


async def _extract_records_for_acquisition(
    context: _URLProcessingContext,
    fetched: _FetchedURLStage,
) -> ExtractionResult:
    acquisition_result = fetched.acquisition_result
    _assign_platform_family(acquisition_result)

    fetched.url_metrics = build_url_metrics(
        acquisition_result,
        requested_fields=list(context.requested_fields),
    )
    result = await _run_record_extraction(
        context,
        acquisition_result=acquisition_result,
    )
    if (
        not result.records
        and "listing" in context.surface
        and getattr(acquisition_result, "method", "") == "browser"
    ):
        fallback_result = await _extract_records_from_preserved_browser_html(
            context,
            fetched,
        )
        if fallback_result is not None:
            await _record_model_cost_log(context, fallback_result)
            if fallback_result.records:
                result = fallback_result
    return result


async def _record_model_cost_log(
    context: _URLProcessingContext,
    result: ExtractionResult,
) -> None:
    if not result.metrics.universal_model_invocation_count:
        return
    config = _generalized_model_config(context) or {}
    state = result.diagnostics.model_terminal_state
    error_message = (
        ""
        if state in {"invoked_produced_evidence", "invoked_no_match"}
        else f"generalized extraction {state}"
    )
    await record_llm_cost_log(
        context.session,
        run_id=context.run.id,
        task_type=GENERALIZED_EXTRACTION_LLM_TASK,
        domain=normalize_domain(context.url),
        provider=str(config.get("provider") or "unknown"),
        model=str(config.get("model") or "unknown"),
        input_tokens=result.metrics.universal_model_input_tokens,
        output_tokens=result.metrics.universal_model_output_tokens,
        error_message=error_message,
        error_category=classify_error(f"Error: {error_message}")
        if error_message
        else LLMErrorCategory.NONE,
    )
    await _log_pipeline_event(
        context,
        "info",
        "Generalized model invocation finished: "
        f"{state} ({result.metrics.universal_model_latency_ms:.0f} ms)",
    )


def _observed_model_adapter(
    context: _URLProcessingContext,
    runtime_snapshot: dict[str, object],
):
    adapter = _model_adapter(context, runtime_snapshot)
    if adapter is None:
        return None
    loop = asyncio.get_running_loop()

    def _on_start() -> None:
        loop.call_soon_threadsafe(
            lambda: asyncio.create_task(
                _log_pipeline_event(
                    context,
                    "info",
                    "Generalized model invocation started",
                )
            )
        )

    return _ObservedModelAdapter(adapter, _on_start)


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


async def _load_runtime_snapshot(context: _URLProcessingContext) -> dict[str, object]:
    snapshot = await load_release_payload(
        context.session, context.run.extraction_release_snapshot_id
    )
    snapshot["llm_enabled"] = context.run.settings_view.llm_enabled()
    snapshot["_release_snapshot_id"] = (
        str(context.run.extraction_release_snapshot_id)
        if context.run.extraction_release_snapshot_id is not None
        else None
    )
    if (
        context.run.settings_view.llm_enabled()
        and _generalized_model_config(context) is not None
        and not isinstance(snapshot.get(UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY), dict)
    ):
        snapshot[UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY] = dict(
            GENERALIZED_EXTRACTION_OPERATOR_RUNTIME_ARTIFACT
        )
    return snapshot


async def _run_record_extraction(
    context: _URLProcessingContext,
    *,
    acquisition_result: PageAcquisitionResult,
) -> ExtractionResult:
    from app.crawl.pipeline import extraction_loop

    await _expand_variant_endpoint_payloads(context, acquisition_result)
    runtime_snapshot = await _load_runtime_snapshot(context)
    model_adapter = _observed_model_adapter(context, runtime_snapshot)
    await context.session.commit()
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
    ) as span:
        result = await asyncio.to_thread(
            extract_records_impl,
            acquisition_result,
            context.surface,
            max_records=context.config.max_records,
            requested_page_url=context.url,
            requested_fields=list(context.requested_fields),
            runtime_snapshot=runtime_snapshot,
            model_adapter=model_adapter,
        )
        await _record_model_cost_log(context, result)
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
    runtime_snapshot = await _load_runtime_snapshot(context)
    model_adapter = _observed_model_adapter(context, runtime_snapshot)
    try:
        fallback_result = await asyncio.to_thread(
            extract_impl,
            acquisition_result,
            context.surface,
            max_records=context.config.max_records,
            requested_page_url=context.url,
            requested_fields=list(context.requested_fields),
            runtime_snapshot=runtime_snapshot,
            model_adapter=model_adapter,
        )
    finally:
        acquisition_result.html = original_html
    if not fallback_result.records:
        await _record_model_cost_log(context, fallback_result)
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


def _model_adapter(
    context: _URLProcessingContext,
    runtime_snapshot: dict[str, object],
):
    if not context.run.settings_view.llm_enabled():
        return None
    artifact = runtime_snapshot.get(UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY)
    if not isinstance(artifact, dict):
        return None
    if artifact.get("adapter_id") != GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID:
        return None
    config = _generalized_model_config(context)
    if config is None:
        return None
    return hosted_generalized_adapter(config_snapshot=config)


def _generalized_model_config(
    context: _URLProcessingContext,
) -> dict[str, object] | None:
    snapshot = context.run.settings_view.llm_config_snapshot()
    for task_type in (GENERALIZED_EXTRACTION_LLM_TASK, "general"):
        config = snapshot.get(task_type)
        if isinstance(config, dict) and validate_config_snapshot(config):
            return config
    return None


async def _update_acquisition_contract_memory(
    context: _URLProcessingContext,
    *,
    acquisition_result,
    records: list[dict[str, object]],
    persisted_count: int,
    verdict: str,
) -> InternalApiReplayMemoryUpdate:
    domain = normalize_domain(
        getattr(acquisition_result, "final_url", "") or context.url
    )
    if not domain:
        return InternalApiReplayMemoryUpdate()
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    acquisition_diagnostics = mapping_or_empty(
        getattr(acquisition_result, "acquisition_diagnostics", {})
    )
    network_payloads = getattr(acquisition_result, "network_payloads", ())
    failed_endpoint_ids = acquisition_diagnostics.get(
        "internal_api_replay_failed_endpoint_ids"
    )
    return await record_acquisition_contract_outcome(
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
        network_payloads=(
            list(network_payloads)
            if isinstance(network_payloads, (list, tuple))
            else []
        ),
        replay_failed_endpoint_ids=(
            list(failed_endpoint_ids)
            if isinstance(failed_endpoint_ids, (list, tuple))
            else []
        ),
    )


extract_records_for_acquisition = _extract_records_for_acquisition
update_acquisition_contract_memory = _update_acquisition_contract_memory
