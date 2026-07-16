from __future__ import annotations

from time import sleep
from typing import NoReturn

import pytest

from app.extraction.contracts import (
    EntityHint,
    ModelEvidenceCandidate,
    UniversalModelArtifact,
    UniversalModelResult,
)
from app.extraction.engine import extract
from app.extraction.model_runtime import (
    RuntimeCompactPage,
    _normalize_source_value,
    run_model_fallback,
)
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


def _approved_snapshot() -> dict[str, object]:
    return {
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
        }
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


class GroundedListingAdapter:
    adapter_id = "fixture-runtime-adapter"
    calls = 0

    def predict(
        self,
        page: RuntimeCompactPage,
        artifact: UniversalModelArtifact,
        *,
        timeout_ms: int,
    ) -> UniversalModelResult:
        self.calls += 1
        node = next(row for row in page.nodes if row.text == "Trail Shoe")
        hint = EntityHint(
            entity_type="product",
            url="https://shop.test/p/trail-shoe",
        )
        return UniversalModelResult(
            adapter_id=self.adapter_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            predictions=(
                ModelEvidenceCandidate(
                    prediction_id="title",
                    artifact_id=page.source.artifact_id,
                    source_path=node.path,
                    fact_type="product.title",
                    raw_value="Trail Shoe",
                    value="Trail Shoe",
                    subject_id="model-product-1",
                    subject_scope="product",
                    confidence=0.97,
                    entity_hint=hint,
                ),
                ModelEvidenceCandidate(
                    prediction_id="url",
                    artifact_id=page.source.artifact_id,
                    source_path=node.path,
                    fact_type="product.url",
                    raw_value="/p/trail-shoe",
                    value="https://shop.test/p/trail-shoe",
                    subject_id="model-product-1",
                    subject_scope="product",
                    confidence=0.96,
                    entity_hint=hint,
                ),
            ),
            latency_ms=2.0,
            memory_mb=32.0,
            cost_usd=0.001,
        )


class MustNotRunAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise AssertionError("universal model must remain lazy")


class TimeoutAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise TimeoutError("fixture timeout")


class BlockingAdapter:
    adapter_id = "fixture-runtime-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        sleep(0.1)
        raise AssertionError("late adapter result must be ignored")


def test_source_value_normalization_preserves_zero_like_values() -> None:
    assert _normalize_source_value(0) == "0"
    assert _normalize_source_value(False) == "false"
    assert _normalize_source_value(None) == ""


def test_deterministic_success_never_builds_or_invokes_model() -> None:
    request = _request(
        """
        <article class="product-card">
          <a href="/p/trail-shoe">Trail Shoe</a>
        </article>
        """,
        runtime_snapshot=_approved_snapshot(),
    )

    result = extract(request, model_adapter=MustNotRunAdapter())

    assert result.records
    assert result.metrics.universal_representation_build_count == 0
    assert result.metrics.universal_model_invocation_count == 0
    assert result.diagnostics.model_outcome == "not_considered"


def test_missing_or_unapproved_artifact_disables_fallback_cleanly() -> None:
    # With no approved artifact in the frozen snapshot the runtime fallback is a
    # clean no-op: it never touches the adapter and reports ``disabled``.
    fallback = run_model_fallback(
        _request("<main><span href='/p/trail-shoe'>Trail Shoe</span></main>"),
        MustNotRunAdapter(),
    )

    assert fallback.outcome == "disabled"
    assert fallback.invoked is False
    assert fallback.evidence == ()
    assert fallback.failure_code is None


def test_grounded_model_evidence_is_source_grounded() -> None:
    adapter = GroundedListingAdapter()
    fallback = run_model_fallback(
        _request(
            "<main><span href='/p/trail-shoe'>Trail Shoe</span></main>",
            runtime_snapshot=_approved_snapshot(),
        ),
        adapter,
    )

    assert adapter.calls == 1
    assert fallback.outcome == "produced_evidence"
    assert fallback.invoked is True
    assert fallback.representation_built is True
    assert fallback.ungrounded_rejection_count == 0
    title_evidence = next(
        row
        for row in fallback.evidence
        if row.collector_id == "universal_model" and row.fact_type == "product.title"
    )
    assert title_evidence.value == "Trail Shoe"
    assert any(row.fact_type == "product.url" for row in fallback.evidence)
    assert fallback.cost_usd == 0.001


def test_ungrounded_model_value_is_rejected_before_resolution() -> None:
    class UngroundedAdapter(GroundedListingAdapter):
        def predict(self, page, artifact, *, timeout_ms):
            result = super().predict(page, artifact, timeout_ms=timeout_ms)
            bad = result.predictions[0].model_copy(
                update={"value": "Fabricated Product"}
            )
            return result.model_copy(update={"predictions": (bad,)})

    fallback = run_model_fallback(
        _request(
            "<main><span href='/p/trail-shoe'>Trail Shoe</span></main>",
            runtime_snapshot=_approved_snapshot(),
        ),
        UngroundedAdapter(),
    )

    assert all(row.value != "Fabricated Product" for row in fallback.evidence)
    assert fallback.ungrounded_rejection_count == 1


def test_model_timeout_degrades_to_classified_service_failure() -> None:
    fallback = run_model_fallback(
        _request(
            "<main><span href='/p/trail-shoe'>Trail Shoe</span></main>",
            runtime_snapshot=_approved_snapshot(),
        ),
        TimeoutAdapter(),
    )

    assert fallback.outcome == "timed_out"
    assert fallback.evidence == ()
    assert fallback.failure_code == "model_service_failure"


def test_blocking_model_adapter_is_cut_off_at_runtime_boundary() -> None:
    snapshot = _approved_snapshot()
    artifact = snapshot["universal_model"]
    assert isinstance(artifact, dict)
    artifact["timeout_ms"] = 5

    fallback = run_model_fallback(
        _request(
            "<main><span href='/p/trail-shoe'>Trail Shoe</span></main>",
            runtime_snapshot=snapshot,
        ),
        BlockingAdapter(),
    )

    assert fallback.outcome == "timed_out"
    assert fallback.failure_code == "model_service_failure"


def test_model_budget_overrun_discards_all_predictions() -> None:
    class OverBudgetAdapter(GroundedListingAdapter):
        def predict(self, page, artifact, *, timeout_ms):
            result = super().predict(page, artifact, timeout_ms=timeout_ms)
            return result.model_copy(update={"memory_mb": 256.0})

    fallback = run_model_fallback(
        _request(
            "<main><span href='/p/trail-shoe'>Trail Shoe</span></main>",
            runtime_snapshot=_approved_snapshot(),
        ),
        OverBudgetAdapter(),
    )

    assert fallback.outcome == "budget_limited"
    assert fallback.evidence == ()


def test_model_result_identity_mismatch_fails_closed() -> None:
    class WrongIdentityAdapter(GroundedListingAdapter):
        def predict(self, page, artifact, *, timeout_ms):
            result = super().predict(page, artifact, timeout_ms=timeout_ms)
            return result.model_copy(update={"artifact_version": "wrong-version"})

    fallback = run_model_fallback(
        _request(
            "<main><span href='/p/trail-shoe'>Trail Shoe</span></main>",
            runtime_snapshot=_approved_snapshot(),
        ),
        WrongIdentityAdapter(),
    )

    assert fallback.outcome == "failed"
    assert fallback.evidence == ()
    assert fallback.failure_code == "model_service_failure"


def test_attribute_spelling_mutation_stays_deterministic_and_model_free() -> None:
    for attribute in ("test-data-id", "test-dataid"):
        result = extract(
            _request(
                f"""
                <main>
                  <div {attribute}="product-card">
                    <a href="/p/trail-shoe">Trail Shoe</a>
                  </div>
                </main>
                """,
                runtime_snapshot=_approved_snapshot(),
            ),
            model_adapter=MustNotRunAdapter(),
        )

        assert [row["title"] for row in result.records] == ["Trail Shoe"]
        assert result.metrics.universal_model_invocation_count == 0
