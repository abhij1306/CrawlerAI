from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.evaluation.schema import (
    BoundingBox,
    EntityRelationship,
    EvaluationCase,
    ExpectedRecord,
    GroundedLabel,
    GroundingReference,
)

pytestmark = pytest.mark.unit


def _node(locator: str = "node-17") -> GroundingReference:
    return GroundingReference(kind="node", artifact_id="dom", locator=locator)


def _region(locator: str = "region-primary") -> GroundingReference:
    return GroundingReference(
        kind="region",
        artifact_id="screenshot-1",
        locator=locator,
        bounding_box=BoundingBox(x=10, y=20, width=300, height=200),
    )


def _human_field(label_id: str = "label-title") -> GroundedLabel:
    return GroundedLabel(
        label_id=label_id,
        authority="human_verified",
        target_kind="field",
        subject_id="product-1",
        record_id="record-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_node(),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )


def _boundary() -> GroundedLabel:
    return GroundedLabel(
        label_id="boundary-1",
        authority="human_verified",
        target_kind="record_boundary",
        record_id="record-1",
        grounding=(_region("record-card-1"),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )


def _case(*labels: GroundedLabel, release_ids: tuple[str, ...]) -> EvaluationCase:
    return EvaluationCase(
        case_id="case-1",
        input_bundle_ref="bundle://frozen/1",
        partition="known_template",
        labels=labels,
        release_evaluation_label_ids=release_ids,
        expected_trust_outcome="trusted",
        required_metrics=("field_f1", "ungrounded_value_rate"),
    )


def test_human_truth_is_release_eligible_and_versioned() -> None:
    label = _human_field()
    case = _case(label, release_ids=(label.label_id,))

    assert label.schema_version == "grounded_label.v1"
    assert case.schema_version == "evaluation_case.v1"
    assert case.release_evaluation_labels == (label,)
    assert case.model_dump(mode="json")["labels"][0]["verified_at"].endswith("Z")


@pytest.mark.parametrize("authority", ("weak", "unverified_model"))
def test_weak_and_model_labels_are_rejected_from_release_set(authority: str) -> None:
    label = GroundedLabel(
        label_id=f"label-{authority}",
        authority=authority,
        target_kind="field",
        subject_id="product-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_node(),),
        confidence=0.9,
    )

    with pytest.raises(ValidationError, match="human truth or qualified"):
        _case(label, release_ids=(label.label_id,))


def test_unqualified_pseudo_label_is_rejected_from_release_set() -> None:
    label = GroundedLabel(
        label_id="pseudo-title",
        authority="deterministic_pseudo",
        target_kind="field",
        subject_id="product-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_node(),),
    )

    with pytest.raises(ValidationError, match="human truth or qualified"):
        _case(label, release_ids=(label.label_id,))


def test_qualified_deterministic_pseudo_label_is_release_eligible() -> None:
    label = GroundedLabel(
        label_id="pseudo-title",
        authority="deterministic_pseudo",
        target_kind="field",
        subject_id="product-1",
        field_name="title",
        canonical_value="Trail Shoe",
        semantic_role="product_title",
        locale_interpretation="not_applicable",
        grounding=(_node(),),
        qualified_for_release=True,
        qualification_ref="evaluation://title-rule/precision-0.999",
    )

    assert _case(label, release_ids=(label.label_id,)).release_evaluation_labels == (
        label,
    )


def test_model_label_cannot_claim_release_qualification() -> None:
    with pytest.raises(ValidationError, match="Only deterministic pseudo-labels"):
        GroundedLabel(
            label_id="model-title",
            authority="unverified_model",
            target_kind="field",
            subject_id="product-1",
            field_name="title",
            canonical_value="Trail Shoe",
            semantic_role="product_title",
            locale_interpretation="not_applicable",
            grounding=(_node(),),
            qualified_for_release=True,
        )


def test_text_value_without_grounding_is_rejected() -> None:
    with pytest.raises(ValidationError, match="grounding reference"):
        GroundedLabel(
            label_id="floating-title",
            authority="unverified_model",
            target_kind="field",
            subject_id="product-1",
            field_name="title",
            canonical_value="Trail Shoe",
            semantic_role="product_title",
            locale_interpretation="not_applicable",
            grounding=(),
        )


def test_explicit_absence_uses_absence_assertion_only() -> None:
    label = GroundedLabel(
        label_id="absence-mpn",
        authority="human_verified",
        target_kind="explicit_absence",
        subject_id="product-1",
        record_id="record-1",
        field_name="mpn",
        semantic_role="manufacturer_part_number",
        locale_interpretation="not_applicable",
        grounding=(
            GroundingReference(
                kind="absence_assertion",
                artifact_id="dom",
                locator="primary-product-region-fully-reviewed",
            ),
        ),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert label.canonical_value is None
    assert label.release_eligible is True


def test_primary_and_recommendation_regions_are_typed() -> None:
    primary = GroundedLabel(
        label_id="primary-region",
        authority="human_verified",
        target_kind="page_region",
        region_role="primary",
        grounding=(_region("primary-pdp"),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )
    recommendation = GroundedLabel(
        label_id="recommendation-region",
        authority="human_verified",
        target_kind="page_region",
        region_role="recommendation",
        grounding=(_region("you-may-also-like"),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert {primary.region_role, recommendation.region_role} == {
        "primary",
        "recommendation",
    }


def test_expected_record_requires_matching_boundary_and_field_labels() -> None:
    boundary = _boundary()
    field = _human_field()
    case = EvaluationCase(
        case_id="listing-case",
        input_bundle_ref="bundle://frozen/listing-1",
        partition="unseen_template",
        labels=(boundary, field),
        expected_records=(
            ExpectedRecord(
                record_id="record-1",
                entity_type="product",
                boundary_label_id=boundary.label_id,
                field_label_ids=(field.label_id,),
            ),
        ),
        release_evaluation_label_ids=(boundary.label_id, field.label_id),
        market_tags=("en-US",),
        template_tags=("product-grid",),
        expected_trust_outcome="trusted",
        required_metrics=("record_boundary_precision", "field_f1"),
    )

    assert case.expected_records[0].field_label_ids == (field.label_id,)


def test_entity_relationship_label_requires_distinct_typed_entities() -> None:
    label = GroundedLabel(
        label_id="variant-offer-link",
        authority="human_verified",
        target_kind="entity_relationship",
        relationship=EntityRelationship(
            source_entity_id="variant-red-m",
            relationship="has_offer",
            target_entity_id="offer-red-m",
        ),
        grounding=(_node("variant-matrix-row-2"),),
        verifier_id="operator-7",
        verified_at=datetime(2026, 7, 2, tzinfo=UTC),
    )

    assert label.relationship is not None
    assert label.relationship.relationship == "has_offer"


def test_schema_forbids_unknown_fields() -> None:
    payload = _human_field().model_dump(mode="python")
    payload["unexpected"] = True

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        GroundedLabel.model_validate(payload)
