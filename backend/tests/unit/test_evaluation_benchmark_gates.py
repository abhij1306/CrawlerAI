"""test_evaluation_phase4 cases split by public behavior."""

from __future__ import annotations

from tests.unit.evaluation_phase4_test_support import (
    EntityRelationship,
    GroundedLabel,
    ModelAdapterResult,
    ModelPrediction,
    OfflineHarnessResult,
    Path,
    UTC,
    ValidationError,
    _boundary,
    _case,
    _fake_adapter,
    _human_field,
    _path,
    _region,
    _run_fixture_adapter,
    benchmark_universal_model,
    build_compact_page_representation,
    datetime,
    json,
    main,
    no_go_report,
    pytest,
    run_offline_adapter,
    validate_release_partitions,
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
