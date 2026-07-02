"""Offline universal-model adapter harness.

Candidate models emit grounded evidence predictions only. This module intentionally
has no publication or extraction-runtime integration.
"""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.evaluation.compact_representation import CompactPageRepresentation
from app.evaluation.schema import (
    EntityRelationship,
    EvaluationSurface,
    GroundingReference,
    RegionSemanticRole,
)


PredictionKind = Literal[
    "page_type",
    "record_boundary",
    "field",
    "exclusion_region",
    "entity_relationship",
]
DeploymentMode = Literal["local", "shared", "offline_fixture"]


class ModelHarnessModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class ModelPrediction(ModelHarnessModel):
    prediction_id: str
    kind: PredictionKind
    confidence: float = Field(ge=0.0, le=1.0)
    page_type: EvaluationSurface | None = None
    record_id: str | None = None
    field_name: str | None = None
    value: JsonValue = None
    region_role: RegionSemanticRole | None = None
    relationship: EntityRelationship | None = None
    grounding: tuple[GroundingReference, ...] = ()
    related_prediction_ids: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_evidence_only_prediction(self) -> ModelPrediction:
        if self.kind == "page_type" and self.page_type is None:
            raise ValueError("Page-type predictions require page_type")
        if self.kind == "record_boundary":
            if self.record_id is None or not self.grounding:
                raise ValueError(
                    "Grounded prediction record boundaries require record_id and grounding"
                )
        if self.kind == "field":
            if self.field_name is None or self.value is None:
                raise ValueError("Field predictions require field_name and value")
            if not self.grounding:
                raise ValueError("Grounded prediction fields require source grounding")
        if self.kind == "exclusion_region":
            if self.region_role not in {"recommendation", "boilerplate", "unrelated"}:
                raise ValueError(
                    "Exclusion-region predictions require a non-primary region_role"
                )
            if not self.grounding:
                raise ValueError(
                    "Grounded prediction exclusion regions require source grounding"
                )
        if self.kind == "entity_relationship":
            if self.relationship is None or not self.grounding:
                raise ValueError(
                    "Grounded prediction relationships require relationship and grounding"
                )
        return self


class ModelAdapterResult(ModelHarnessModel):
    adapter_id: str
    model_family: str
    deployment_mode: DeploymentMode
    artifact_version: str
    predictions: tuple[ModelPrediction, ...]
    latency_ms: float = Field(ge=0.0)
    memory_mb: float = Field(ge=0.0)
    cost_usd: float = Field(ge=0.0)

    @model_validator(mode="after")
    def validate_prediction_graph(self) -> ModelAdapterResult:
        _validate_prediction_graph(self.predictions)
        return self


class OfflineModelAdapter(Protocol):
    adapter_id: str

    def predict(self, page: CompactPageRepresentation) -> ModelAdapterResult: ...


class OfflineHarnessResult(ModelHarnessModel):
    case_id: str
    adapter_id: str
    model_family: str
    deployment_mode: DeploymentMode
    artifact_version: str
    representation_hash: str
    predictions: tuple[ModelPrediction, ...]
    latency_ms: float
    memory_mb: float
    cost_usd: float
    public_records: tuple[dict[str, object], ...] = ()

    @model_validator(mode="after")
    def reject_publication_payload(self) -> OfflineHarnessResult:
        if self.public_records:
            raise ValueError("Offline model harness cannot emit public records")
        _validate_prediction_graph(self.predictions)
        return self


def run_offline_adapter(
    *, case_id: str, page: CompactPageRepresentation, adapter: OfflineModelAdapter
) -> OfflineHarnessResult:
    _reject_evaluation_truth_leakage(page)
    result = adapter.predict(page)
    if result.adapter_id != adapter.adapter_id:
        raise ValueError("Adapter result identity does not match the invoked adapter")
    _validate_prediction_grounding(page, result.predictions)
    return OfflineHarnessResult(
        case_id=case_id,
        adapter_id=result.adapter_id,
        model_family=result.model_family,
        deployment_mode=result.deployment_mode,
        artifact_version=result.artifact_version,
        representation_hash=page.source.content_hash,
        predictions=result.predictions,
        latency_ms=result.latency_ms,
        memory_mb=result.memory_mb,
        cost_usd=result.cost_usd,
    )


def _reject_evaluation_truth_leakage(page: CompactPageRepresentation) -> None:
    if (
        page.labels
        or page.grounding_references
        or any(node.label_ids or node.region_refs for node in page.nodes)
    ):
        raise ValueError(
            "Candidate inference pages cannot expose evaluation labels or truth references"
        )


def _validate_prediction_grounding(
    page: CompactPageRepresentation,
    predictions: tuple[ModelPrediction, ...],
) -> None:
    source_paths = {node.path for node in page.nodes}
    for prediction in predictions:
        for reference in prediction.grounding:
            if reference.artifact_id != page.source.artifact_id:
                raise ValueError(
                    "Prediction grounding must reference the represented source artifact"
                )
            if reference.kind not in {"path", "region"}:
                raise ValueError(
                    "Prediction grounding must use compact representation paths"
                )
            if reference.locator not in source_paths:
                raise ValueError(
                    "Prediction grounding must resolve to a retained compact node"
                )


def _validate_prediction_graph(predictions: tuple[ModelPrediction, ...]) -> None:
    prediction_ids = {prediction.prediction_id for prediction in predictions}
    if len(prediction_ids) != len(predictions):
        raise ValueError("Model prediction IDs must be unique")
    unknown_related_ids = sorted(
        {
            related_id
            for prediction in predictions
            for related_id in prediction.related_prediction_ids
            if related_id not in prediction_ids
        }
    )
    if unknown_related_ids:
        raise ValueError(
            f"Related prediction IDs must exist in the same result: {unknown_related_ids}"
        )
