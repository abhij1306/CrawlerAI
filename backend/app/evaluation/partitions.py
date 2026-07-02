"""Evaluation partition gating for offline universal-extractor research."""

from __future__ import annotations

from collections import Counter

from app.core.config.evaluation import (
    RELEASE_REQUIRED_EVALUATION_PARTITIONS,
    RELEASE_REQUIRED_EVALUATION_SCENARIOS,
    RELEASE_REQUIRED_EVALUATION_SURFACES,
)
from app.evaluation.schema import EvaluationCase


def release_label_counts_by_partition(
    cases: tuple[EvaluationCase, ...],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for case in cases:
        if case.release_evaluation_labels:
            counts[case.partition] += len(case.release_evaluation_labels)
    return dict(sorted(counts.items()))


def release_label_counts_by_surface(
    cases: tuple[EvaluationCase, ...],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for case in cases:
        if case.release_evaluation_labels:
            counts[case.surface] += len(case.release_evaluation_labels)
    return dict(sorted(counts.items()))


def release_label_counts_by_scenario(
    cases: tuple[EvaluationCase, ...],
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for case in cases:
        label_count = len(case.release_evaluation_labels)
        if not label_count:
            continue
        for scenario in case.scenario_tags:
            counts[scenario] += label_count
    return dict(sorted(counts.items()))


def validate_release_partitions(
    cases: tuple[EvaluationCase, ...],
    *,
    required_partitions: tuple[str, ...] = RELEASE_REQUIRED_EVALUATION_PARTITIONS,
    required_surfaces: tuple[str, ...] = RELEASE_REQUIRED_EVALUATION_SURFACES,
    required_scenarios: tuple[str, ...] = RELEASE_REQUIRED_EVALUATION_SCENARIOS,
) -> dict[str, object]:
    partition_counts = release_label_counts_by_partition(cases)
    surface_counts = release_label_counts_by_surface(cases)
    scenario_counts = release_label_counts_by_scenario(cases)
    missing_partitions = _missing(required_partitions, partition_counts)
    missing_surfaces = _missing(required_surfaces, surface_counts)
    missing_scenarios = _missing(required_scenarios, scenario_counts)
    return {
        "passed": not (missing_partitions or missing_surfaces or missing_scenarios),
        "missing_partitions": missing_partitions,
        "missing_surfaces": missing_surfaces,
        "missing_scenarios": missing_scenarios,
        "release_label_counts": partition_counts,
        "release_label_counts_by_surface": surface_counts,
        "release_label_counts_by_scenario": scenario_counts,
    }


def _missing(required: tuple[str, ...], counts: dict[str, int]) -> tuple[str, ...]:
    return tuple(name for name in required if counts.get(name, 0) == 0)
