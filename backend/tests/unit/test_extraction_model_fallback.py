from __future__ import annotations

from typing import NoReturn

import pytest

from app.extraction.contracts import UniversalModelArtifact
from app.connectors.llm.generalized_extraction import HostedGeneralizedExtractionAdapter
from app.core.config.evaluation import GENERALIZED_EXTRACTION_BUDGET
from app.extraction.engine import extract
from app.extraction.model_runtime import (
    RuntimeCompactSource,
    RuntimeFlatMapEntry,
    RuntimeFlatMapPage,
    _normalize_source_value,
    run_model_recipe_proposals,
)
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


def _approved_snapshot() -> dict[str, object]:
    return {
        "llm_enabled": True,
        "universal_model": {
            "schema_version": "universal_model_artifact.v1",
            "artifact_id": "universal-extractor",
            "artifact_version": "2026-07-02",
            "adapter_id": "fixture-runtime-adapter",
            "model_family": "fixture-grounded-model",
            "deployment_mode": "local",
            "benchmark_schema_version": "universal_model_benchmark.v2",
            "benchmark_report_id": "benchmark-approved-1",
            "benchmark_passed": True,
            "approved": True,
            "enabled": True,
            "confidence_threshold": 0.8,
            "timeout_ms": 1000,
            "max_memory_mb": 128.0,
            "max_cost_per_page_usd": 0.01,
            "supported_surfaces": ["ecommerce_listing"],
        },
    }


def _request(
    html: str,
    *,
    runtime_snapshot: dict[str, object] | None = None,
):
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_LISTING,
        html,
        "https://shop.test/category/shoes",
        max_records=5,
    )
    return request.model_copy(update={"runtime_snapshot": runtime_snapshot or {}})


class MustNotRunAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise AssertionError("universal model must remain lazy")


class ProviderErrorAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise RuntimeError("provider_error:timeout")


def test_source_value_normalization_preserves_zero_like_values() -> None:
    assert _normalize_source_value(0) == "0"
    assert _normalize_source_value(False) == "false"
    assert _normalize_source_value(None) == ""


def test_missing_or_unapproved_artifact_disables_fallback_cleanly() -> None:
    adapter = MustNotRunAdapter()
    result = extract(
        _request("<main><span>Trail Shoe /p/trail-shoe</span></main>"),
        model_adapter=adapter,
    )

    assert result.records == ()
    assert result.diagnostics.model_outcome == "disabled"
    assert result.metrics.universal_model_invocation_count == 0
    assert result.failure_classifications[0].code != "model_service_failure"


def test_run_setting_disables_approved_model_without_invocation() -> None:
    snapshot = _approved_snapshot()
    snapshot["llm_enabled"] = False

    result = extract(
        _request(
            "<main><span>Trail Shoe /p/trail-shoe</span></main>",
            runtime_snapshot=snapshot,
        ),
        model_adapter=MustNotRunAdapter(),
    )

    assert result.records == ()
    assert result.diagnostics.model_outcome == "disabled"
    assert result.metrics.universal_model_invocation_count == 0


def test_runtime_preserves_safe_provider_error_category() -> None:
    result = run_model_recipe_proposals(
        _request("<main>Trail Shoe</main>", runtime_snapshot=_approved_snapshot()),
        ProviderErrorAdapter(),
    )

    assert result.invoked is True
    assert result.terminal_state == "provider_error"
    assert result.detail == "provider_error:timeout"


def test_generalized_budget_config_has_required_runtime_controls() -> None:
    assert GENERALIZED_EXTRACTION_BUDGET == {
        "budget_ms": 30000,
        "model_tier": "hosted_llama",
        "max_cost_usd_per_page": 0.02,
        "max_input_tokens": 60000,
        "max_output_tokens": 8000,
        "escalate_to_vision_below_confidence": 0.8,
        "cooldown_minutes": 5,
    }


def test_hosted_generalized_adapter_converts_schema_payload(monkeypatch) -> None:
    async def fake_provider_call(**kwargs):
        return (
            """
            {
              "schema_version": "generalized_extraction_response.v1",
              "predictions": [
                {
                  "prediction_id": "title",
                  "source_path": "/html[1]/body[1]/main[1]",
                  "fact_type": "product.title",
                  "raw_value": "Trail Shoe",
                  "value": "Trail Shoe",
                  "subject_id": "generalized-product-1",
                  "subject_scope": "product",
                  "confidence": 0.91
                },
                {
                  "prediction_id": "variant-size",
                  "source_path": "/html[1]/body[1]/main[2]",
                  "fact_type": "variant.option.size",
                  "raw_value": "L",
                  "value": "L",
                  "subject_id": "variant-1",
                  "subject_scope": "variant",
                  "confidence": 0.90
                },
                {
                  "prediction_id": "variant-price",
                  "source_path": "/html[1]/body[1]/main[2]",
                  "fact_type": "offer.price",
                  "raw_value": "64.00",
                  "value": "64.00",
                  "subject_id": "offer-variant-1",
                  "subject_scope": "offer",
                  "parent_subject_id": "variant-1",
                  "relation_type": "variant_offer",
                  "group_id": "variant-1-offer",
                  "confidence": 0.90
                }
              ]
            }
            """,
            100,
            20,
        )

    monkeypatch.setattr(
        "app.connectors.llm.generalized_extraction.call_provider_with_retry",
        fake_provider_call,
    )
    adapter = HostedGeneralizedExtractionAdapter(
        config_snapshot={
            "provider": "groq",
            "model": "llama-3.3-70b-versatile",
            "api_key_encrypted": "",
        }
    )
    page = RuntimeFlatMapPage(
        source=RuntimeCompactSource(artifact_id="html", content_hash="hash"),
        entries=(
            RuntimeFlatMapEntry(
                path="/html[1]/body[1]/main[1]",
                text="Trail Shoe",
            ),
            RuntimeFlatMapEntry(
                path="/html[1]/body[1]/main[2]",
                text="Size L 64.00",
            ),
        ),
    )
    artifact = UniversalModelArtifact.model_validate(
        _approved_snapshot()["universal_model"]
    )

    result = adapter.predict(page, artifact, timeout_ms=1000)

    assert result.adapter_id == adapter.adapter_id
    assert result.predictions[0].fact_type == "product.title"
    assert result.predictions[0].value == "Trail Shoe"
    assert result.predictions[1].fact_type == "variant.option.size"
    assert result.predictions[2].relation_type == "variant_offer"
    assert result.cost_usd >= 0.0
