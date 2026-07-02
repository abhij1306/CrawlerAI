"""Stable offline benchmark gates for universal-extractor candidates."""

from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path
from statistics import quantiles
from typing import Any

from app.core.config.evaluation import (
    RELEASE_REQUIRED_EVALUATION_PARTITIONS,
    RELEASE_REQUIRED_EVALUATION_SCENARIOS,
    RELEASE_REQUIRED_EVALUATION_SURFACES,
    UNIVERSAL_MODEL_BENCHMARK_SCHEMA_VERSION,
    UNIVERSAL_MODEL_REQUIRED_METRICS,
)
from app.evaluation.model_harness import OfflineHarnessResult
from app.evaluation.partitions import validate_release_partitions
from app.evaluation.schema import EvaluationCase, GroundingReference


DEFAULT_PHASE4_REPORT = (
    Path(__file__).resolve().parent / "benchmarks" / "universal_model_phase4.json"
)
_REQUIRED_BASELINE_SIGNALS = (
    "unseen_template_field_f1",
    "ungrounded_value_rate",
)


def benchmark_universal_model(
    *,
    cases: tuple[EvaluationCase, ...],
    results: tuple[OfflineHarnessResult, ...],
    deterministic_baseline: dict[str, Any],
    required_partitions: tuple[str, ...] = RELEASE_REQUIRED_EVALUATION_PARTITIONS,
    required_surfaces: tuple[str, ...] = RELEASE_REQUIRED_EVALUATION_SURFACES,
    required_scenarios: tuple[str, ...] = RELEASE_REQUIRED_EVALUATION_SCENARIOS,
) -> dict[str, Any]:
    partition_gate = validate_release_partitions(
        cases,
        required_partitions=required_partitions,
        required_surfaces=required_surfaces,
        required_scenarios=required_scenarios,
    )
    input_errors = (
        *_input_errors(cases, results),
        *_baseline_errors(deterministic_baseline),
    )
    metrics = _metrics(cases, results)
    partition_metrics = _partition_field_metrics(cases, results)
    missing_baseline_signals = tuple(
        name
        for name in _REQUIRED_BASELINE_SIGNALS
        if deterministic_baseline.get(name) is None
    )
    release_gate = _release_gate(
        metrics=metrics,
        partition_metrics=partition_metrics,
        deterministic_baseline=deterministic_baseline,
        missing_baseline_signals=missing_baseline_signals,
        partition_gate=partition_gate,
        input_errors=input_errors,
    )
    return {
        "schema_version": UNIVERSAL_MODEL_BENCHMARK_SCHEMA_VERSION,
        "evaluation_status": "completed",
        "case_count": len(cases),
        "result_count": len(results),
        "candidate": _candidate_metadata(results),
        "metrics_available": True,
        "metrics": metrics,
        "partition_metrics": partition_metrics,
        "partition_gate": partition_gate,
        "input_errors": input_errors,
        "baseline": {
            "unseen_template_field_f1": _safe_rate(
                deterministic_baseline.get("unseen_template_field_f1")
            ),
            "ungrounded_value_rate": _safe_rate(
                deterministic_baseline.get("ungrounded_value_rate")
            ),
            "missing_signals": missing_baseline_signals,
        },
        "release_gate": release_gate,
    }


def write_benchmark_report(report: dict[str, Any], path: Path | str) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def no_go_report(reason: str) -> dict[str, Any]:
    partition_gate = validate_release_partitions(())
    return {
        "schema_version": UNIVERSAL_MODEL_BENCHMARK_SCHEMA_VERSION,
        "evaluation_status": "not_run",
        "case_count": 0,
        "result_count": 0,
        "candidate": None,
        "metrics_available": False,
        "metrics": {name: None for name in UNIVERSAL_MODEL_REQUIRED_METRICS},
        "partition_metrics": {},
        "partition_gate": partition_gate,
        "input_errors": ("candidate_results_not_supplied",),
        "baseline": {
            "unseen_template_field_f1": None,
            "ungrounded_value_rate": None,
            "missing_signals": _REQUIRED_BASELINE_SIGNALS,
        },
        "release_gate": {
            "passed": False,
            "reason_codes": ("candidate_benchmark_not_run",),
            "reason": reason,
            "serving_decision": "no_production_serving",
            "phase5_status": "blocked_until_candidate_beats_baseline",
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Write the Phase 4 offline universal-model benchmark report."
    )
    parser.add_argument("--out", default=str(DEFAULT_PHASE4_REPORT))
    parser.add_argument("--cases", help="JSON array of EvaluationCase objects")
    parser.add_argument("--results", help="JSON array of OfflineHarnessResult objects")
    parser.add_argument(
        "--baseline", help="JSON object with deterministic baseline rates"
    )
    parser.add_argument(
        "--no-go-reason",
        default="no approved offline candidate benchmark has been supplied",
    )
    parsed = parser.parse_args(argv)
    supplied_inputs = (parsed.cases, parsed.results, parsed.baseline)
    if any(supplied_inputs) and not all(supplied_inputs):
        parser.error("--cases, --results, and --baseline must be supplied together")
    if all(supplied_inputs):
        report = benchmark_universal_model(
            cases=tuple(
                EvaluationCase.model_validate(value)
                for value in _load_json_array(Path(str(parsed.cases)), "cases")
            ),
            results=tuple(
                OfflineHarnessResult.model_validate(value)
                for value in _load_json_array(Path(str(parsed.results)), "results")
            ),
            deterministic_baseline=_load_json_object(
                Path(str(parsed.baseline)), "baseline"
            ),
        )
    else:
        report = no_go_report(str(parsed.no_go_reason))
    write_benchmark_report(report, parsed.out)
    print(f"wrote {parsed.out}: gate_passed={report['release_gate']['passed']}")
    return 0


def _load_json_array(path: Path, input_name: str) -> list[object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list):
        raise ValueError(f"{input_name} input must be a JSON array")
    return value


def _load_json_object(path: Path, input_name: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{input_name} input must be a JSON object")
    return value


def _metrics(
    cases: tuple[EvaluationCase, ...], results: tuple[OfflineHarnessResult, ...]
) -> dict[str, float | int]:
    fields = _field_metrics(cases, results)
    latency_values = [result.latency_ms for result in results]
    memory_values = [result.memory_mb for result in results]
    cost_total = sum(result.cost_usd for result in results)
    return {
        **fields,
        "record_boundary_accuracy": _record_boundary_accuracy(cases, results),
        "variant_binding_accuracy": _relationship_accuracy(cases, results),
        "recommendation_contamination_rate": _recommendation_contamination_rate(
            cases, results
        ),
        "ungrounded_value_rate": _ungrounded_value_rate(results),
        "latency_ms_p95": _p95(latency_values),
        "memory_mb_p95": _p95(memory_values),
        "cost_per_1000_pages": _ratio(cost_total * 1000, len(results)),
    }


def _field_metrics(
    cases: tuple[EvaluationCase, ...], results: tuple[OfflineHarnessResult, ...]
) -> dict[str, float | int]:
    truth = _field_truth(cases)
    predicted = _field_predictions(results)
    matched_count = sum((truth & predicted).values())
    truth_count = sum(truth.values())
    prediction_count = sum(predicted.values())
    precision = _ratio(matched_count, prediction_count)
    recall = _ratio(matched_count, truth_count)
    return {
        "field_precision": precision,
        "field_recall": recall,
        "field_f1": _f1(precision, recall),
        "normalized_exact_match": _ratio(matched_count, truth_count),
        "field_truth_count": truth_count,
        "field_prediction_count": prediction_count,
    }


def _partition_field_metrics(
    cases: tuple[EvaluationCase, ...], results: tuple[OfflineHarnessResult, ...]
) -> dict[str, dict[str, float | int]]:
    result_by_case = {result.case_id: result for result in results}
    metrics: dict[str, dict[str, float | int]] = {}
    for partition in sorted({case.partition for case in cases}):
        partition_cases = tuple(case for case in cases if case.partition == partition)
        partition_results = tuple(
            result_by_case[case.case_id]
            for case in partition_cases
            if case.case_id in result_by_case
        )
        metrics[partition] = _field_metrics(partition_cases, partition_results)
    return metrics


def _field_truth(
    cases: tuple[EvaluationCase, ...],
) -> Counter[tuple[str, str, str, tuple[tuple[object, ...], ...]]]:
    truth: Counter[tuple[str, str, str, tuple[tuple[object, ...], ...]]] = Counter()
    for case in cases:
        for label in case.release_evaluation_labels:
            if label.target_kind == "field" and label.field_name:
                truth[
                    (
                        case.case_id,
                        label.field_name,
                        _norm(label.canonical_value),
                        _grounding_set(label.grounding),
                    )
                ] += 1
    return truth


def _field_predictions(
    results: tuple[OfflineHarnessResult, ...],
) -> Counter[tuple[str, str, str, tuple[tuple[object, ...], ...]]]:
    predicted: Counter[tuple[str, str, str, tuple[tuple[object, ...], ...]]] = Counter()
    for result in results:
        for prediction in result.predictions:
            if prediction.kind == "field" and prediction.field_name:
                predicted[
                    (
                        result.case_id,
                        prediction.field_name,
                        _norm(prediction.value),
                        _grounding_set(prediction.grounding),
                    )
                ] += 1
    return predicted


def _record_boundary_accuracy(
    cases: tuple[EvaluationCase, ...], results: tuple[OfflineHarnessResult, ...]
) -> float:
    truth: Counter[tuple[object, ...]] = Counter()
    predicted: Counter[tuple[object, ...]] = Counter()
    for case in cases:
        for label in case.release_evaluation_labels:
            if label.target_kind == "record_boundary":
                truth[
                    (case.case_id, label.record_id, _grounding_set(label.grounding))
                ] += 1
    for result in results:
        for prediction in result.predictions:
            if prediction.kind == "record_boundary":
                predicted[
                    (
                        result.case_id,
                        prediction.record_id,
                        _grounding_set(prediction.grounding),
                    )
                ] += 1
    return _ratio(sum((truth & predicted).values()), sum(truth.values()))


def _relationship_accuracy(
    cases: tuple[EvaluationCase, ...], results: tuple[OfflineHarnessResult, ...]
) -> float:
    truth: Counter[tuple[str, str, str, str]] = Counter()
    predicted: Counter[tuple[str, str, str, str]] = Counter()
    for case in cases:
        for label in case.release_evaluation_labels:
            relationship = label.relationship
            if label.target_kind == "entity_relationship" and relationship is not None:
                truth[
                    (
                        case.case_id,
                        relationship.source_entity_id,
                        relationship.relationship,
                        relationship.target_entity_id,
                    )
                ] += 1
    for result in results:
        for prediction in result.predictions:
            relationship = prediction.relationship
            if prediction.kind == "entity_relationship" and relationship is not None:
                predicted[
                    (
                        result.case_id,
                        relationship.source_entity_id,
                        relationship.relationship,
                        relationship.target_entity_id,
                    )
                ] += 1
    return _ratio(sum((truth & predicted).values()), sum(truth.values()))


def _recommendation_contamination_rate(
    cases: tuple[EvaluationCase, ...],
    results: tuple[OfflineHarnessResult, ...],
) -> float:
    recommendation_refs_by_case: dict[str, set[tuple[object, ...]]] = {}
    for case in cases:
        references = recommendation_refs_by_case.setdefault(case.case_id, set())
        for label in case.release_evaluation_labels:
            if (
                label.target_kind == "page_region"
                and label.region_role == "recommendation"
            ):
                references.update(_grounding_set(label.grounding))
    field_count = 0
    contaminated = 0
    for result in results:
        recommendation_refs = recommendation_refs_by_case.get(result.case_id, set())
        for prediction in result.predictions:
            if prediction.kind != "field":
                continue
            field_count += 1
            contaminated += int(
                bool(
                    recommendation_refs.intersection(
                        _grounding_set(prediction.grounding)
                    )
                )
            )
    return _ratio(contaminated, field_count)


def _ungrounded_value_rate(results: tuple[OfflineHarnessResult, ...]) -> float:
    fields = [
        prediction
        for result in results
        for prediction in result.predictions
        if prediction.kind == "field"
    ]
    return _ratio(sum(not prediction.grounding for prediction in fields), len(fields))


def _grounding_set(
    references: tuple[GroundingReference, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(sorted(_grounding_signature(reference) for reference in references))


def _grounding_signature(reference: GroundingReference) -> tuple[object, ...]:
    box = reference.bounding_box
    return (
        reference.kind,
        reference.artifact_id,
        reference.locator,
        box.x if box else None,
        box.y if box else None,
        box.width if box else None,
        box.height if box else None,
    )


def _input_errors(
    cases: tuple[EvaluationCase, ...], results: tuple[OfflineHarnessResult, ...]
) -> tuple[str, ...]:
    errors: list[str] = []
    case_ids = [case.case_id for case in cases]
    result_case_ids = [result.case_id for result in results]
    if not cases:
        errors.append("evaluation_cases_required")
    if len(set(case_ids)) != len(case_ids):
        errors.append("duplicate_case_ids")
    if len(set(result_case_ids)) != len(result_case_ids):
        errors.append("duplicate_result_case_ids")
    if set(case_ids) != set(result_case_ids):
        errors.append("case_result_coverage_mismatch")
    candidate_ids = {
        (
            result.adapter_id,
            result.model_family,
            result.deployment_mode,
            result.artifact_version,
        )
        for result in results
    }
    if len(candidate_ids) != 1:
        errors.append("single_candidate_identity_required")
    return tuple(errors)


def _candidate_metadata(
    results: tuple[OfflineHarnessResult, ...],
) -> dict[str, str] | None:
    if not results:
        return None
    first = results[0]
    return {
        "adapter_id": first.adapter_id,
        "model_family": first.model_family,
        "deployment_mode": first.deployment_mode,
        "artifact_version": first.artifact_version,
    }


def _baseline_errors(deterministic_baseline: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        f"invalid_baseline_signal:{name}"
        for name in _REQUIRED_BASELINE_SIGNALS
        if name in deterministic_baseline
        and deterministic_baseline[name] is not None
        and not _valid_rate(deterministic_baseline[name])
    )


def _release_gate(
    *,
    metrics: dict[str, float | int],
    partition_metrics: dict[str, dict[str, float | int]],
    deterministic_baseline: dict[str, Any],
    missing_baseline_signals: tuple[str, ...],
    partition_gate: dict[str, object],
    input_errors: tuple[str, ...],
) -> dict[str, object]:
    reasons: list[str] = []
    if input_errors:
        reasons.append("invalid_benchmark_inputs")
    if not bool(partition_gate["passed"]):
        reasons.append("required_evaluation_coverage_missing")
    if missing_baseline_signals:
        reasons.append("deterministic_baseline_signals_missing")
    unseen = partition_metrics.get("unseen_template")
    if unseen is None or int(unseen.get("field_truth_count", 0)) == 0:
        reasons.append("unseen_template_truth_missing")
    baseline_unseen_f1 = deterministic_baseline.get("unseen_template_field_f1")
    unseen_gain = (
        unseen is not None
        and _valid_rate(baseline_unseen_f1)
        and float(unseen["field_f1"]) > float(baseline_unseen_f1)
    )
    if not unseen_gain:
        reasons.append("unseen_template_f1_not_improved")
    baseline_ungrounded = deterministic_baseline.get("ungrounded_value_rate")
    no_ungrounded_regression = _valid_rate(baseline_ungrounded) and float(
        metrics["ungrounded_value_rate"]
    ) <= float(baseline_ungrounded)
    if not no_ungrounded_regression:
        reasons.append("ungrounded_value_rate_regressed")
    return {
        "passed": not reasons,
        "reason_codes": tuple(dict.fromkeys(reasons)),
        "unseen_template_gain": unseen_gain,
        "no_ungrounded_regression": no_ungrounded_regression,
        "serving_decision": (
            "benchmark_eligible_for_serving_review"
            if not reasons
            else "no_production_serving"
        ),
        "phase5_status": (
            "eligible_for_explicit_approval"
            if not reasons
            else "blocked_until_candidate_beats_baseline"
        ),
    }


def _ratio(numerator: float, denominator: float) -> float:
    return round(float(numerator) / float(denominator), 6) if denominator else 0.0


def _valid_rate(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(float(value))
        and 0.0 <= float(value) <= 1.0
    )


def _safe_rate(value: Any) -> float | None:
    return float(value) if _valid_rate(value) else None


def _f1(precision: float, recall: float) -> float:
    return (
        round(2 * precision * recall / (precision + recall), 6)
        if precision + recall
        else 0.0
    )


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return round(float(values[0]), 6)
    return round(float(quantiles(values, n=20, method="inclusive")[18]), 6)


def _norm(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


if __name__ == "__main__":
    raise SystemExit(main())
