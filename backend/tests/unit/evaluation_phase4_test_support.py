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
    locator: str = "/#document[1]/html[1]/body[1]/h1[1]",
) -> GroundingReference:
    return GroundingReference(kind="path", artifact_id="html", locator=locator)


def _region(
    locator: str = "/#document[1]/html[1]/body[1]/h1[1]",
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


__all__ = [
    "COMPACT_REPRESENTATION_MAX_NODES",
    "UTC",
    "BoundingBox",
    "EntityRelationship",
    "EvaluationCase",
    "EvaluationPartition",
    "EvaluationScenario",
    "EvaluationSurface",
    "GroundedLabel",
    "GroundingReference",
    "ModelAdapterResult",
    "ModelPrediction",
    "OfflineHarnessResult",
    "Path",
    "ValidationError",
    "_boundary",
    "_case",
    "_fake_adapter",
    "_human_field",
    "_node",
    "_path",
    "_region",
    "_run_fixture_adapter",
    "benchmark_universal_model",
    "build_compact_page_representation",
    "cast",
    "datetime",
    "json",
    "main",
    "no_go_report",
    "pytest",
    "pytestmark",
    "run_offline_adapter",
    "validate_release_partitions",
]
