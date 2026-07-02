from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from pydantic import ValidationError

from app.core.config.evaluation import COMPACT_REPRESENTATION_MAX_NODES
from app.evaluation.benchmark import benchmark_universal_model, main, no_go_report
from app.evaluation.compact_representation import build_compact_page_representation
from app.evaluation.model_harness import (
    ModelAdapterResult,
    ModelPrediction,
    OfflineHarnessResult,
    run_offline_adapter,
)
from app.evaluation.partitions import validate_release_partitions
from app.evaluation.schema import (
    BoundingBox,
    EntityRelationship,
    EvaluationCase,
    EvaluationPartition,
    EvaluationScenario,
    EvaluationSurface,
    GroundedLabel,
    GroundingReference,
)

pytestmark = pytest.mark.unit


def _node(
    locator: str = "css:.title",
) -> GroundingReference:
    return GroundingReference(kind="node", artifact_id="html", locator=locator)


def _path(
    locator: str = "/html[1]/body[1]/h1[1]",
) -> GroundingReference:
    return GroundingReference(kind="path", artifact_id="html", locator=locator)


def _region(
    locator: str = "/html[1]/body[1]/h1[1]",
) -> GroundingReference:
    return GroundingReference(
        kind="region",
        artifact_id="html",
        locator=locator,
        bounding_box=BoundingBox(x=1, y=2, width=10, height=20),
    )


def _human_field(
    *,
    label_id: str = "label-title",
    field_name: str = "title",
    value: str = "Trail Shoe",
    grounding: tuple[GroundingReference, ...] | None = None,
) -> GroundedLabel:
    return GroundedLabel(
        label_id=label_id,
        authority="human_verified",
        target_kind="field",
        subject_id="product-1",
        record_id="record-1",
        field_name=field_name,
        canonical_value=value,
        semantic_role="product_title" if field_name == "title" else "primary_price",
        locale_interpretation="not_applicable" if field_name == "title" else "en-US",
        grounding=grounding or (_path(),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )


def _boundary(label_id: str = "boundary-1") -> GroundedLabel:
    return GroundedLabel(
        label_id=label_id,
        authority="human_verified",
        target_kind="record_boundary",
        record_id="record-1",
        grounding=(_region(),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )


def _case(
    partition: str,
    *labels: GroundedLabel,
    case_id: str = "case-1",
    surface: str = "ecommerce_detail",
    scenario_tags: tuple[str, ...] = (),
) -> EvaluationCase:
    return EvaluationCase(
        case_id=case_id,
        input_bundle_ref=f"bundle://{case_id}",
        partition=cast(EvaluationPartition, partition),
        surface=cast(EvaluationSurface, surface),
        scenario_tags=cast(tuple[EvaluationScenario, ...], scenario_tags),
        labels=labels,
        release_evaluation_label_ids=tuple(label.label_id for label in labels),
        expected_trust_outcome="trusted",
        required_metrics=("field_f1", "ungrounded_value_rate"),
    )


def _fake_adapter(
    *,
    adapter_id: str,
    result: ModelAdapterResult | None = None,
    predict=None,
):
    if (result is None) == (predict is None):
        raise ValueError("provide exactly one of result or predict")
    predictor = predict or (lambda _page: cast(ModelAdapterResult, result))
    return type(
        "FakeAdapter",
        (),
        {"adapter_id": adapter_id, "predict": staticmethod(predictor)},
    )()


def _run_fixture_adapter(
    *,
    case_id: str,
    predictions: tuple[ModelPrediction, ...],
    adapter_id: str = "fake-universal",
) -> OfflineHarnessResult:
    result = ModelAdapterResult(
        adapter_id=adapter_id,
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=predictions,
        latency_ms=5.0,
        memory_mb=30.0,
        cost_usd=0.002,
    )
    adapter = _fake_adapter(adapter_id=adapter_id, result=result)
    return run_offline_adapter(
        case_id=case_id,
        page=build_compact_page_representation(
            html="<h1 class='title'>Trail Shoe</h1>", artifact_id="html"
        ),
        adapter=adapter,
    )


def test_compact_page_representation_is_bounded_and_source_grounded() -> None:
    html = """
    <html><body>
      <script>var huge = 'ignored';</script>
      <main data-testid="primary">
        <article class="card"><h2 class="title">Trail Shoe</h2><span class="price">$10</span></article>
        <article class="card"><h2 class="title">Road Shoe</h2><span class="price">$20</span></article>
      </main>
    </body></html>
    """

    page = build_compact_page_representation(
        html=html, artifact_id="html", market_tags=("en-US",), max_nodes=4
    )

    assert page.schema_version == "compact_page.v2"
    assert len(page.nodes) == 4
    assert page.truncated is True
    assert page.source.artifact_id == "html"
    assert all(node.tag != "script" for node in page.nodes)
    assert any(node.attributes.get("data-testid") == "primary" for node in page.nodes)
    assert any(node.repeated_block_key for node in page.nodes)
    assert page.market_tags == ("en-US",)


def test_compact_representation_does_not_duplicate_descendant_text_on_containers() -> (
    None
):
    page = build_compact_page_representation(
        html="<main data-testid='product'><h1>Trail Shoe</h1><p>Fast shoe</p></main>",
        artifact_id="html",
    )

    main = next(node for node in page.nodes if node.tag == "main")
    title = next(node for node in page.nodes if node.tag == "h1")
    assert main.text == ""
    assert title.text == "Trail Shoe"


def test_compact_page_representation_carries_path_label_references() -> None:
    html = "<html><body><main><h1>Trail Shoe</h1></main></body></html>"
    initial = build_compact_page_representation(html=html, artifact_id="html")
    title_path = next(node.path for node in initial.nodes if node.tag == "h1")
    label = GroundedLabel(
        label_id="label-title-path",
        authority="human_verified",
        target_kind="field",
        subject_id="product-1",
        record_id="record-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_path(title_path),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    page = build_compact_page_representation(
        html=html, artifact_id="html", labels=(label,)
    )

    title_node = next(node for node in page.nodes if node.path == title_path)
    assert title_node.label_ids == ("label-title-path",)
    assert page.labels == (label,)
    assert page.grounding_references == label.grounding


def test_compact_representation_resolves_css_node_labels_and_enforces_global_cap() -> (
    None
):
    html = (
        "<main>"
        + "".join(
            f'<article class="card"><h2 class="title">Item {index}</h2></article>'
            for index in range(100)
        )
        + "</main>"
    )
    label = _human_field(grounding=(_node(),))

    page = build_compact_page_representation(
        html=html,
        artifact_id="html",
        labels=(label,),
        max_nodes=10_000,
    )

    assert len(page.nodes) <= COMPACT_REPRESENTATION_MAX_NODES
    assert page.truncated is True
    assert any("label-title" in node.label_ids for node in page.nodes)
    assert page.grounding_references == label.grounding


def test_compact_representation_rejects_non_positive_node_bound() -> None:
    with pytest.raises(ValueError, match="max_nodes"):
        build_compact_page_representation(
            html="<h1>Trail Shoe</h1>", artifact_id="html", max_nodes=0
        )


def test_release_partition_gate_fails_closed_when_required_partitions_are_missing() -> (
    None
):
    cases = (
        _case("known_template", _human_field(), case_id="known"),
        _case(
            "unseen_template", _human_field(label_id="label-unseen"), case_id="unseen"
        ),
    )

    gate = validate_release_partitions(cases)

    assert gate["passed"] is False
    assert gate["release_label_counts"] == {"known_template": 1, "unseen_template": 1}
    missing = cast(tuple[str, ...], gate["missing_partitions"])
    assert "temporal_change" in missing


def test_release_partition_gate_counts_only_release_eligible_labels() -> None:
    weak = GroundedLabel(
        label_id="weak-title",
        authority="weak",
        target_kind="field",
        subject_id="product-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_path(),),
    )
    case = EvaluationCase(
        case_id="weak-case",
        input_bundle_ref="bundle://weak",
        partition="known_template",
        surface="ecommerce_detail",
        labels=(weak,),
        release_evaluation_label_ids=(),
        expected_trust_outcome="review",
        required_metrics=("field_f1",),
    )

    gate = validate_release_partitions(
        (case,),
        required_partitions=("known_template",),
        required_surfaces=(),
        required_scenarios=(),
    )

    assert gate == {
        "passed": False,
        "missing_partitions": ("known_template",),
        "missing_surfaces": (),
        "missing_scenarios": (),
        "release_label_counts": {},
        "release_label_counts_by_surface": {},
        "release_label_counts_by_scenario": {},
    }


def test_offline_model_harness_emits_evidence_only_predictions() -> None:
    page = build_compact_page_representation(
        html="<html><body><h1>Trail Shoe</h1></body></html>", artifact_id="html"
    )

    title_path = next(node.path for node in page.nodes if node.text == "Trail Shoe")
    adapter_result = ModelAdapterResult(
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(
            ModelPrediction(
                prediction_id="pred-title",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.99,
                grounding=(_path(title_path),),
            ),
        ),
        latency_ms=3.0,
        memory_mb=12.0,
        cost_usd=0.001,
    )
    result = run_offline_adapter(
        case_id="case-1",
        page=page,
        adapter=_fake_adapter(adapter_id="fake-universal", result=adapter_result),
    )

    assert result.adapter_id == "fake-universal"
    assert result.public_records == ()
    assert result.predictions[0].grounding[0].locator == title_path


def test_offline_harness_rejects_adapter_identity_mismatch() -> None:
    page = build_compact_page_representation(
        html="<h1 class='title'>Trail Shoe</h1>", artifact_id="html"
    )
    result = ModelAdapterResult(
        adapter_id="different-adapter",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(),
        latency_ms=1.0,
        memory_mb=1.0,
        cost_usd=0.0,
    )
    adapter = _fake_adapter(adapter_id="expected-adapter", result=result)

    with pytest.raises(ValueError, match="identity"):
        run_offline_adapter(case_id="case-1", page=page, adapter=adapter)


def test_offline_harness_rejects_evaluation_truth_leakage() -> None:
    label = _human_field()
    page = build_compact_page_representation(
        html="<h1>Trail Shoe</h1>", artifact_id="html", labels=(label,)
    )
    adapter = _fake_adapter(
        adapter_id="must-not-run",
        predict=lambda page: pytest.fail("adapter must not receive evaluation truth"),
    )

    with pytest.raises(ValueError, match="cannot expose evaluation labels"):
        run_offline_adapter(case_id="case-1", page=page, adapter=adapter)


def test_offline_harness_rejects_grounding_outside_compact_source() -> None:
    page = build_compact_page_representation(
        html="<h1>Trail Shoe</h1>", artifact_id="html"
    )
    result = ModelAdapterResult(
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(
            ModelPrediction(
                prediction_id="pred-title",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(
                    GroundingReference(
                        kind="path",
                        artifact_id="other-artifact",
                        locator="/html[1]/body[1]/h1[1]",
                    ),
                ),
            ),
        ),
        latency_ms=1.0,
        memory_mb=1.0,
        cost_usd=0.0,
    )
    adapter = _fake_adapter(adapter_id="fake-universal", result=result)

    with pytest.raises(ValueError, match="represented source artifact"):
        run_offline_adapter(case_id="case-1", page=page, adapter=adapter)


def test_offline_harness_result_rejects_publication_payload() -> None:
    with pytest.raises(ValidationError, match="cannot emit public records"):
        OfflineHarnessResult(
            case_id="case-1",
            adapter_id="fake-universal",
            model_family="deterministic-fixture",
            deployment_mode="offline_fixture",
            artifact_version="fixture-v1",
            representation_hash="abc123",
            predictions=(),
            latency_ms=1.0,
            memory_mb=1.0,
            cost_usd=0.0,
            public_records=({},),
        )


def test_model_field_prediction_requires_grounding() -> None:
    with pytest.raises(ValidationError, match="Grounded prediction"):
        ModelPrediction(
            prediction_id="floating-title",
            kind="field",
            field_name="title",
            value="Trail Shoe",
            confidence=0.8,
        )


def test_model_result_rejects_unknown_prediction_relationships() -> None:
    with pytest.raises(ValidationError, match="Related prediction IDs must exist"):
        ModelAdapterResult(
            adapter_id="fake-universal",
            model_family="deterministic-fixture",
            deployment_mode="offline_fixture",
            artifact_version="fixture-v1",
            predictions=(
                ModelPrediction(
                    prediction_id="pred-title",
                    kind="field",
                    field_name="title",
                    value="Trail Shoe",
                    confidence=0.8,
                    grounding=(_path(),),
                    related_prediction_ids=("missing-boundary",),
                ),
            ),
            latency_ms=1.0,
            memory_mb=1.0,
            cost_usd=0.0,
        )


def test_benchmark_gate_compares_to_baseline_and_ungrounded_rate() -> None:
    title = _human_field()
    boundary = _boundary()
    relationship = GroundedLabel(
        label_id="variant-link",
        authority="human_verified",
        target_kind="entity_relationship",
        relationship=EntityRelationship(
            source_entity_id="variant-1",
            relationship="has_offer",
            target_entity_id="offer-1",
        ),
        grounding=(_path(),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    case = _case("unseen_template", title, boundary, relationship)
    result = ModelAdapterResult(
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        predictions=(
            ModelPrediction(
                prediction_id="pred-boundary",
                kind="record_boundary",
                record_id="record-1",
                confidence=0.95,
                grounding=(_region(),),
            ),
            ModelPrediction(
                prediction_id="pred-title",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.99,
                grounding=(_path(),),
            ),
            ModelPrediction(
                prediction_id="pred-link",
                kind="entity_relationship",
                relationship=EntityRelationship(
                    source_entity_id="variant-1",
                    relationship="has_offer",
                    target_entity_id="offer-1",
                ),
                confidence=0.8,
                grounding=(_path(),),
            ),
        ),
        latency_ms=5.0,
        memory_mb=30.0,
        cost_usd=0.002,
    )
    harness = run_offline_adapter(
        case_id="case-1",
        page=build_compact_page_representation(
            html="<h1>Trail Shoe</h1>", artifact_id="html"
        ),
        adapter=_fake_adapter(adapter_id="fake-universal", result=result),
    )

    report = benchmark_universal_model(
        cases=(case,),
        results=(harness,),
        deterministic_baseline={
            "unseen_template_field_f1": 0.5,
            "ungrounded_value_rate": 0.0,
        },
        required_partitions=("unseen_template",),
        required_surfaces=("ecommerce_detail",),
        required_scenarios=(),
    )

    assert report["schema_version"] == "universal_model_benchmark.v2"
    assert report["metrics"]["field_f1"] == 1.0
    assert report["metrics"]["record_boundary_accuracy"] == 1.0
    assert report["metrics"]["variant_binding_accuracy"] == 1.0
    assert report["metrics"]["ungrounded_value_rate"] == 0.0
    assert report["metrics"]["cost_per_1000_pages"] == 2.0
    assert report["release_gate"]["passed"] is True


def test_benchmark_gate_uses_unseen_partition_not_aggregate_f1() -> None:
    known = _case(
        "known_template",
        _human_field(label_id="known-title", value="Known Product"),
        case_id="known",
    )
    unseen = _case(
        "unseen_template",
        _human_field(label_id="unseen-title", value="Unseen Product"),
        case_id="unseen",
    )
    known_result = _run_fixture_adapter(
        case_id="known",
        predictions=(
            ModelPrediction(
                prediction_id="known-prediction",
                kind="field",
                field_name="title",
                value="Known Product",
                confidence=0.9,
                grounding=(_path(),),
            ),
        ),
    )
    unseen_result = _run_fixture_adapter(
        case_id="unseen",
        predictions=(
            ModelPrediction(
                prediction_id="unseen-prediction",
                kind="field",
                field_name="title",
                value="Wrong Product",
                confidence=0.9,
                grounding=(_path(),),
            ),
        ),
    )

    report = benchmark_universal_model(
        cases=(known, unseen),
        results=(known_result, unseen_result),
        deterministic_baseline={
            "unseen_template_field_f1": 0.4,
            "ungrounded_value_rate": 0.0,
        },
        required_partitions=("known_template", "unseen_template"),
        required_surfaces=("ecommerce_detail",),
        required_scenarios=(),
    )

    assert report["metrics"]["field_f1"] == 0.5
    assert report["partition_metrics"]["unseen_template"]["field_f1"] == 0.0
    assert report["release_gate"]["passed"] is False
    assert "unseen_template_f1_not_improved" in report["release_gate"]["reason_codes"]


def test_benchmark_field_score_requires_correct_source_grounding() -> None:
    case = _case("unseen_template", _human_field(), case_id="unseen")
    result = OfflineHarnessResult(
        case_id="unseen",
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        representation_hash="abc123",
        predictions=(
            ModelPrediction(
                prediction_id="wrong-node",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(_path("/html[1]/body[1]/aside[1]"),),
            ),
        ),
        latency_ms=1.0,
        memory_mb=1.0,
        cost_usd=0.0,
    )

    report = benchmark_universal_model(
        cases=(case,),
        results=(result,),
        deterministic_baseline={
            "unseen_template_field_f1": 0.5,
            "ungrounded_value_rate": 0.0,
        },
        required_partitions=("unseen_template",),
        required_surfaces=("ecommerce_detail",),
        required_scenarios=(),
    )

    assert report["metrics"]["field_f1"] == 0.0
    assert report["release_gate"]["passed"] is False


def test_recommendation_contamination_uses_truth_regions() -> None:
    recommendation = GroundedLabel(
        label_id="recommendation-region",
        authority="human_verified",
        target_kind="page_region",
        region_role="recommendation",
        grounding=(_region("/html[1]/body[1]/aside[1]"),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    case = _case(
        "unseen_template",
        _human_field(),
        recommendation,
        case_id="unseen",
    )
    result = OfflineHarnessResult(
        case_id="unseen",
        adapter_id="fake-universal",
        model_family="deterministic-fixture",
        deployment_mode="offline_fixture",
        artifact_version="fixture-v1",
        representation_hash="abc123",
        predictions=(
            ModelPrediction(
                prediction_id="contaminated-title",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(_region("/html[1]/body[1]/aside[1]"),),
            ),
        ),
        latency_ms=1.0,
        memory_mb=1.0,
        cost_usd=0.0,
    )

    report = benchmark_universal_model(
        cases=(case,),
        results=(result,),
        deterministic_baseline={
            "unseen_template_field_f1": 0.5,
            "ungrounded_value_rate": 0.0,
        },
        required_partitions=("unseen_template",),
        required_surfaces=("ecommerce_detail",),
        required_scenarios=(),
    )

    assert report["metrics"]["recommendation_contamination_rate"] == 1.0


def test_benchmark_gate_fails_closed_when_baseline_signals_are_missing() -> None:
    case = _case("unseen_template", _human_field(), case_id="unseen")
    result = _run_fixture_adapter(
        case_id="unseen",
        predictions=(
            ModelPrediction(
                prediction_id="prediction",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(_path(),),
            ),
        ),
    )

    report = benchmark_universal_model(
        cases=(case,),
        results=(result,),
        deterministic_baseline={"ungrounded_value_rate": 0.0},
        required_partitions=("unseen_template",),
        required_surfaces=("ecommerce_detail",),
        required_scenarios=(),
    )

    assert report["release_gate"]["passed"] is False
    assert (
        "deterministic_baseline_signals_missing"
        in report["release_gate"]["reason_codes"]
    )


def test_benchmark_gate_fails_closed_for_invalid_baseline_rates() -> None:
    case = _case("unseen_template", _human_field(), case_id="unseen")
    result = _run_fixture_adapter(
        case_id="unseen",
        predictions=(
            ModelPrediction(
                prediction_id="prediction",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(_path(),),
            ),
        ),
    )

    report = benchmark_universal_model(
        cases=(case,),
        results=(result,),
        deterministic_baseline={
            "unseen_template_field_f1": -1.0,
            "ungrounded_value_rate": float("nan"),
        },
        required_partitions=("unseen_template",),
        required_surfaces=("ecommerce_detail",),
        required_scenarios=(),
    )

    assert report["release_gate"]["passed"] is False
    assert report["release_gate"]["reason_codes"][0] == "invalid_benchmark_inputs"
    assert report["input_errors"] == (
        "invalid_baseline_signal:unseen_template_field_f1",
        "invalid_baseline_signal:ungrounded_value_rate",
    )


def test_partition_gate_covers_surface_and_scenario_dimensions() -> None:
    listing = _case(
        "known_template",
        _human_field(label_id="listing-title"),
        case_id="listing",
        surface="ecommerce_listing",
        scenario_tags=("multi_variant",),
    )
    job = _case(
        "sentinel_disagreement",
        _human_field(label_id="job-title"),
        case_id="job",
        surface="job_detail",
        scenario_tags=("sentinel_disagreement",),
    )

    gate = validate_release_partitions(
        (listing, job),
        required_partitions=("known_template", "sentinel_disagreement"),
        required_surfaces=("ecommerce_listing", "job_detail"),
        required_scenarios=("multi_variant", "sentinel_disagreement"),
    )

    assert gate["passed"] is True
    assert gate["release_label_counts_by_surface"] == {
        "ecommerce_listing": 1,
        "job_detail": 1,
    }
    assert gate["release_label_counts_by_scenario"] == {
        "multi_variant": 1,
        "sentinel_disagreement": 1,
    }


def test_no_go_report_blocks_runtime_serving_without_candidate_benchmark() -> None:
    report = no_go_report("candidate missing")

    assert report["metrics_available"] is False
    assert report["metrics"]["field_f1"] is None
    assert report["release_gate"] == {
        "passed": False,
        "reason_codes": ("candidate_benchmark_not_run",),
        "reason": "candidate missing",
        "serving_decision": "no_production_serving",
        "phase5_status": "blocked_until_candidate_beats_baseline",
    }


def test_benchmark_command_loads_candidate_inputs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = _case("unseen_template", _human_field(), case_id="unseen")
    result = _run_fixture_adapter(
        case_id="unseen",
        predictions=(
            ModelPrediction(
                prediction_id="prediction",
                kind="field",
                field_name="title",
                value="Trail Shoe",
                confidence=0.9,
                grounding=(_path(),),
            ),
        ),
    )
    cases_path = tmp_path / "cases.json"
    results_path = tmp_path / "results.json"
    baseline_path = tmp_path / "baseline.json"
    output_path = tmp_path / "report.json"
    cases_path.write_text(json.dumps([case.model_dump(mode="json")]), encoding="utf-8")
    results_path.write_text(
        json.dumps([result.model_dump(mode="json")]), encoding="utf-8"
    )
    baseline_path.write_text(
        json.dumps({"unseen_template_field_f1": 0.5, "ungrounded_value_rate": 0.0}),
        encoding="utf-8",
    )

    exit_code = main(
        [
            "--cases",
            str(cases_path),
            "--results",
            str(results_path),
            "--baseline",
            str(baseline_path),
            "--out",
            str(output_path),
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert report["evaluation_status"] == "completed"
    assert report["candidate"]["adapter_id"] == "fake-universal"
    assert "gate_passed=False" in capsys.readouterr().out
