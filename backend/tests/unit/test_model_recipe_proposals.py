from __future__ import annotations

from typing import NoReturn

from app.core.extraction_memory.recipe_executor import execute_recipe
from app.extraction.contracts import (
    EntityHint,
    ModelEvidenceCandidate,
    UniversalModelArtifact,
    UniversalModelResult,
)
from app.extraction.model_runtime import (
    RuntimeFlatMapPage,
    run_model_recipe_proposals,
)
from app.extraction.recipe_compiler import compile_model_proposals
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface


def _snapshot(*, enabled: bool = True) -> dict[str, object]:
    return {
        "llm_enabled": enabled,
        "universal_model": {
            "schema_version": "universal_model_artifact.v1",
            "artifact_id": "universal-extractor",
            "artifact_version": "2026-07-11",
            "adapter_id": "proposal-adapter",
            "model_family": "fixture-grounded-model",
            "deployment_mode": "local",
            "benchmark_schema_version": "universal_model_benchmark.v2",
            "benchmark_report_id": "benchmark-approved",
            "benchmark_passed": True,
            "approved": True,
            "enabled": True,
            "confidence_threshold": 0.8,
            "timeout_ms": 1000,
            "max_memory_mb": 128.0,
            "max_cost_per_page_usd": 0.01,
            "supported_surfaces": ["ecommerce_detail"],
        },
    }


def _request(*, enabled: bool = True):
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        """
        <main data-product-id="P-1">
          <a href="/products/correct-shoe">/products/correct-shoe</a>
          <h1>Correct Shoe</h1>
        </main>
        """,
        "https://shop.test/products/correct-shoe",
    )
    return request.model_copy(update={"runtime_snapshot": _snapshot(enabled=enabled)})


class ProposalAdapter:
    adapter_id = "proposal-adapter"

    def predict(
        self,
        page: RuntimeFlatMapPage,
        artifact: UniversalModelArtifact,
        *,
        timeout_ms: int,
    ) -> UniversalModelResult:
        del timeout_ms
        title = next(row for row in page.entries if row.text == "Correct Shoe")
        url = next(row for row in page.entries if "/products/correct-shoe" in row.text)
        hint = EntityHint(entity_type="product")
        return UniversalModelResult(
            adapter_id=self.adapter_id,
            artifact_id=artifact.artifact_id,
            artifact_version=artifact.artifact_version,
            predictions=(
                ModelEvidenceCandidate(
                    prediction_id="title-path",
                    artifact_id=page.source.artifact_id,
                    source_path=title.path,
                    fact_type="product.title",
                    raw_value="Correct Shoe",
                    value="Correct Shoe",
                    subject_id="product-1",
                    subject_scope="product",
                    confidence=0.95,
                    entity_hint=hint,
                ),
                ModelEvidenceCandidate(
                    prediction_id="url-path",
                    artifact_id=page.source.artifact_id,
                    source_path=url.path,
                    fact_type="product.url",
                    raw_value="/products/correct-shoe",
                    value="https://shop.test/products/correct-shoe",
                    subject_id="product-1",
                    subject_scope="product",
                    confidence=0.95,
                    entity_hint=hint,
                ),
            ),
            latency_ms=2.0,
            memory_mb=12.0,
            cost_usd=0.001,
            input_tokens=24,
            output_tokens=12,
        )


class MustNotRunAdapter:
    adapter_id = "proposal-adapter"

    def predict(self, *args, **kwargs) -> NoReturn:
        raise AssertionError("disabled model must not run")


def test_grounded_model_paths_compile_and_replay_without_model_values() -> None:
    request = _request()

    result = run_model_recipe_proposals(request, ProposalAdapter())

    assert result.invoked is True
    assert result.terminal_state == "invoked_produced_evidence"
    assert result.input_tokens == 24
    assert result.output_tokens == 12
    assert result.cost_usd == 0.001
    assert {proposal.field for proposal in result.proposals} == {"title", "url"}
    assert all(
        "value" not in type(proposal).model_fields for proposal in result.proposals
    )

    discovery = compile_model_proposals(request, result.proposals)
    assert discovery.candidate is not None
    execution = execute_recipe(request, discovery.candidate.recipe)
    assert execution.failure_code is None
    assert execution.records == (
        {
            "title": "Correct Shoe",
            "url": "https://shop.test/products/correct-shoe",
        },
    )


def test_disabled_model_proposal_path_is_lazy_and_classified() -> None:
    result = run_model_recipe_proposals(_request(enabled=False), MustNotRunAdapter())

    assert result.invoked is False
    assert result.proposals == ()
    assert result.terminal_state == "disabled"
    assert result.input_tokens == 0
    assert result.output_tokens == 0
