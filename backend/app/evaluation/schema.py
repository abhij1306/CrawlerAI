"""Versioned offline evaluation and grounded-label contracts.

These models carry truth for replay, release evaluation, and future training.
They are deliberately independent from the extraction runtime.
"""

from __future__ import annotations

from collections.abc import Collection
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.config.evaluation import (
    EVALUATION_CASE_SCHEMA_VERSION,
    EVALUATION_PARTITIONS,
    EVALUATION_SCENARIOS,
    EVALUATION_SURFACES,
    GROUNDED_LABEL_SCHEMA_VERSION,
    GROUNDING_REFERENCE_KINDS,
    LABEL_AUTHORITIES,
    LABEL_TARGET_KINDS,
    REGION_SEMANTIC_ROLES,
    TRUST_OUTCOMES,
    UNIVERSAL_MODEL_REQUIRED_METRICS,
)

NonEmptyText = Annotated[str, Field(min_length=1)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
LabelAuthority = Literal[
    "human_verified", "deterministic_pseudo", "weak", "unverified_model"
]
LabelTargetKind = Literal[
    "page_region",
    "record_boundary",
    "field",
    "entity_relationship",
    "explicit_absence",
]
GroundingReferenceKind = Literal["node", "path", "region", "absence_assertion"]
RegionSemanticRole = Literal["primary", "recommendation", "boilerplate", "unrelated"]
EvaluationPartition = Literal[
    "known_template",
    "unseen_domain",
    "unseen_template",
    "temporal_change",
    "ab_variant",
    "personalized_or_promotional",
    "market_or_locale",
    "platform_collision",
    "sentinel_disagreement",
]
EvaluationSurface = Literal[
    "ecommerce_listing",
    "ecommerce_detail",
    "job_listing",
    "job_detail",
]
EvaluationScenario = Literal[
    "multi_variant",
    "personalized_or_promotional",
    "platform_collision",
    "sentinel_disagreement",
]
TrustOutcome = Literal["trusted", "review", "rejected", "blocked"]


def _validate_unique_members(
    values: tuple[str, ...],
    allowed: Collection[str],
    *,
    unsupported_prefix: str,
    duplicate_message: str,
) -> None:
    invalid = sorted(set(values).difference(allowed))
    if invalid:
        raise ValueError(f"{unsupported_prefix}: {invalid}")
    if len(set(values)) != len(values):
        raise ValueError(duplicate_message)


class EvaluationSchemaModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class BoundingBox(EvaluationSchemaModel):
    x: float
    y: float
    width: Annotated[float, Field(gt=0)]
    height: Annotated[float, Field(gt=0)]


class GroundingReference(EvaluationSchemaModel):
    """Stable reference into one immutable input-bundle artifact."""

    kind: GroundingReferenceKind
    artifact_id: NonEmptyText
    locator: NonEmptyText
    bounding_box: BoundingBox | None = None

    @model_validator(mode="after")
    def validate_reference(self) -> GroundingReference:
        if self.kind not in GROUNDING_REFERENCE_KINDS:
            raise ValueError(f"Unsupported grounding reference kind: {self.kind}")
        if self.kind == "region" and self.bounding_box is None:
            raise ValueError("Region references require a bounding_box")
        if self.kind != "region" and self.bounding_box is not None:
            raise ValueError("Only region references may carry a bounding_box")
        return self


class EntityRelationship(EvaluationSchemaModel):
    source_entity_id: NonEmptyText
    relationship: NonEmptyText
    target_entity_id: NonEmptyText

    @model_validator(mode="after")
    def reject_self_relationship(self) -> EntityRelationship:
        if self.source_entity_id == self.target_entity_id:
            raise ValueError("Entity relationships require distinct entities")
        return self


class GroundedLabel(EvaluationSchemaModel):
    """One grounded truth, pseudo-label, weak label, or model observation."""

    schema_version: Literal["grounded_label.v1"] = GROUNDED_LABEL_SCHEMA_VERSION
    label_id: NonEmptyText
    authority: LabelAuthority
    target_kind: LabelTargetKind
    subject_id: NonEmptyText | None = None
    record_id: NonEmptyText | None = None
    field_name: NonEmptyText | None = None
    canonical_value: JsonValue = None
    semantic_role: NonEmptyText | None = None
    locale_interpretation: NonEmptyText | None = None
    uncertainty_reason: NonEmptyText | None = None
    custom_field: dict[str, JsonValue] | None = None
    region_role: RegionSemanticRole | None = None
    relationship: EntityRelationship | None = None
    grounding: tuple[GroundingReference, ...]
    verifier_id: NonEmptyText | None = None
    verified_at: datetime | None = None
    qualified_for_release: bool = False
    qualification_ref: NonEmptyText | None = None
    confidence: UnitInterval | None = None

    @property
    def release_eligible(self) -> bool:
        return self.authority == "human_verified" or (
            self.authority == "deterministic_pseudo" and self.qualified_for_release
        )

    @model_validator(mode="after")
    def validate_grounded_label(self) -> GroundedLabel:
        if self.authority not in LABEL_AUTHORITIES:
            raise ValueError(f"Unsupported label authority: {self.authority}")
        if self.target_kind not in LABEL_TARGET_KINDS:
            raise ValueError(f"Unsupported label target kind: {self.target_kind}")
        if (
            self.region_role is not None
            and self.region_role not in REGION_SEMANTIC_ROLES
        ):
            raise ValueError(f"Unsupported region role: {self.region_role}")
        self._validate_authority()
        self._validate_target()
        return self

    def _validate_authority(self) -> None:
        if self.authority == "human_verified":
            if self.verifier_id is None or self.verified_at is None:
                raise ValueError(
                    "Human-verified labels require verifier_id and verified_at"
                )
            if self.qualification_ref is not None:
                raise ValueError("Human labels do not use pseudo-label qualification")
        elif self.verifier_id is not None or self.verified_at is not None:
            raise ValueError("Only human-verified labels may carry verifier metadata")

        if self.authority == "deterministic_pseudo" and self.qualified_for_release:
            if self.qualification_ref is None:
                raise ValueError(
                    "Release-qualified pseudo-labels require qualification_ref"
                )
        elif self.authority != "deterministic_pseudo" and self.qualified_for_release:
            raise ValueError(
                "Only deterministic pseudo-labels may be qualified for release"
            )
        if self.authority in {"weak", "unverified_model"} and self.qualification_ref:
            raise ValueError("Weak and model labels cannot carry release qualification")

    def _validate_target(self) -> None:
        kinds = {reference.kind for reference in self.grounding}
        if not self.grounding:
            raise ValueError("Every label requires a grounding reference")
        self._validate_absence(kinds)
        self._validate_field()
        self._validate_record_boundary(kinds)
        self._validate_region(kinds)
        self._validate_relationship()

    def _validate_absence(self, kinds: set[GroundingReferenceKind]) -> None:
        if self.target_kind == "explicit_absence":
            if self.field_name is None:
                raise ValueError("Explicit absence requires field_name")
            if self.canonical_value is not None:
                raise ValueError("Explicit absence cannot carry canonical_value")
            if kinds != {"absence_assertion"}:
                raise ValueError(
                    "Explicit absence must use only absence_assertion grounding"
                )
        elif "absence_assertion" in kinds:
            raise ValueError(
                "absence_assertion grounding is reserved for explicit absence"
            )

    def _validate_field(self) -> None:
        if self.target_kind == "field":
            if self.field_name is None or self.subject_id is None:
                raise ValueError("Field labels require field_name and subject_id")
            if self.canonical_value is None:
                raise ValueError("Present field labels require canonical_value")
            if self.semantic_role is None or self.locale_interpretation is None:
                raise ValueError(
                    "Field labels require semantic_role and locale_interpretation"
                )
        elif self.target_kind == "explicit_absence":
            if self.subject_id is None:
                raise ValueError("Explicit absence requires subject_id")
            if self.semantic_role is None or self.locale_interpretation is None:
                raise ValueError(
                    "Explicit absence requires semantic_role and locale_interpretation"
                )
        elif self.field_name is not None:
            raise ValueError("field_name is valid only for field or explicit absence")

    def _validate_record_boundary(self, kinds: set[GroundingReferenceKind]) -> None:
        if self.target_kind == "record_boundary":
            if self.record_id is None or not kinds.intersection({"node", "region"}):
                raise ValueError(
                    "Record boundaries require record_id and node/region grounding"
                )

    def _validate_region(self, kinds: set[GroundingReferenceKind]) -> None:
        if self.target_kind == "page_region":
            if self.region_role is None or "region" not in kinds:
                raise ValueError(
                    "Page regions require region_role and region grounding"
                )
        elif self.region_role is not None:
            raise ValueError("region_role is valid only for page_region labels")

    def _validate_relationship(self) -> None:
        if self.target_kind == "entity_relationship":
            if self.relationship is None:
                raise ValueError(
                    "Entity relationship labels require a typed relationship"
                )
        elif self.relationship is not None:
            raise ValueError(
                "relationship is valid only for entity_relationship labels"
            )


class ExpectedRecord(EvaluationSchemaModel):
    record_id: NonEmptyText
    entity_type: NonEmptyText
    boundary_label_id: NonEmptyText
    field_label_ids: tuple[NonEmptyText, ...] = ()


class EvaluationCase(EvaluationSchemaModel):
    """One replay/evaluation case with an explicit release-truth subset."""

    schema_version: Literal["evaluation_case.v1"] = EVALUATION_CASE_SCHEMA_VERSION
    case_id: NonEmptyText
    input_bundle_ref: NonEmptyText
    partition: EvaluationPartition
    surface: EvaluationSurface
    scenario_tags: tuple[EvaluationScenario, ...] = ()
    labels: tuple[GroundedLabel, ...]
    expected_records: tuple[ExpectedRecord, ...] = ()
    release_evaluation_label_ids: tuple[NonEmptyText, ...] = ()
    market_tags: tuple[NonEmptyText, ...] = ()
    template_tags: tuple[NonEmptyText, ...] = ()
    expected_trust_outcome: TrustOutcome
    required_metrics: tuple[NonEmptyText, ...]

    @property
    def release_evaluation_labels(self) -> tuple[GroundedLabel, ...]:
        selected = set(self.release_evaluation_label_ids)
        return tuple(label for label in self.labels if label.label_id in selected)

    @model_validator(mode="after")
    def validate_case(self) -> EvaluationCase:
        if self.partition not in EVALUATION_PARTITIONS:
            raise ValueError(f"Unsupported evaluation partition: {self.partition}")
        if self.surface not in EVALUATION_SURFACES:
            raise ValueError(f"Unsupported evaluation surface: {self.surface}")
        _validate_unique_members(
            self.scenario_tags,
            EVALUATION_SCENARIOS,
            unsupported_prefix="Unsupported evaluation scenarios",
            duplicate_message="Evaluation scenario tags must be unique",
        )
        _validate_unique_members(
            self.required_metrics,
            UNIVERSAL_MODEL_REQUIRED_METRICS,
            unsupported_prefix="Unsupported evaluation metrics",
            duplicate_message="Required evaluation metrics must be unique",
        )
        if self.expected_trust_outcome not in TRUST_OUTCOMES:
            raise ValueError(
                f"Unsupported trust outcome: {self.expected_trust_outcome}"
            )
        label_index = {label.label_id: label for label in self.labels}
        if len(label_index) != len(self.labels):
            raise ValueError("Label IDs must be unique within an evaluation case")
        release_ids = set(self.release_evaluation_label_ids)
        if len(release_ids) != len(self.release_evaluation_label_ids):
            raise ValueError("Release evaluation label IDs must be unique")
        missing = release_ids.difference(label_index)
        if missing:
            raise ValueError(f"Unknown release evaluation label IDs: {sorted(missing)}")
        ineligible = [
            label_id
            for label_id in self.release_evaluation_label_ids
            if not label_index[label_id].release_eligible
        ]
        if ineligible:
            raise ValueError(
                "Release evaluation accepts only human truth or qualified "
                f"deterministic pseudo-labels: {ineligible}"
            )
        self._validate_expected_records(label_index)
        return self

    def _validate_expected_records(self, label_index: dict[str, GroundedLabel]) -> None:
        record_ids: set[str] = set()
        for record in self.expected_records:
            if record.record_id in record_ids:
                raise ValueError("Expected record IDs must be unique")
            record_ids.add(record.record_id)
            boundary = label_index.get(record.boundary_label_id)
            if boundary is None or boundary.target_kind != "record_boundary":
                raise ValueError("Expected records require a record_boundary label")
            if boundary.record_id != record.record_id:
                raise ValueError("Boundary label record_id does not match record")
            for label_id in record.field_label_ids:
                label = label_index.get(label_id)
                if label is None or label.target_kind not in {
                    "field",
                    "explicit_absence",
                }:
                    raise ValueError(
                        "Expected record field_label_ids require field/absence labels"
                    )
                if label.record_id not in {None, record.record_id}:
                    raise ValueError("Field label belongs to a different record")
