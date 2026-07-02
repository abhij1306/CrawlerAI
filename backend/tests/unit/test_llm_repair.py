"""Contract tests for grounded LLM repair (Phase 7).

These are pure, DB-free checks of the proposal contract: the model cannot emit an
ungrounded value, cannot skip its uncertainty reason, and cannot introduce a
non-standard field without a typed declaration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.connectors.llm.payloads import SUPPORTED_TASK_TYPES
from app.evaluation.llm_repair import (
    CustomFieldDeclaration,
    GroundedRepairBatch,
    GroundedRepairContractError,
    GroundedRepairProposal,
    _label_payload,
    _reject_undeclared_custom_fields,
)
from app.evaluation.schema import GroundedLabel


def _grounding(locator: str = "css:.price", kind: str = "node") -> dict[str, str]:
    return {"kind": kind, "artifact_id": "url-result:1:page.html", "locator": locator}


def _proposal(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "field_name": "price",
        "subject_id": "product:1",
        "canonical_value": "19.99",
        "semantic_role": "primary_price",
        "locale_interpretation": "USD",
        "uncertainty_reason": "current value read the strike-through price",
        "grounding": [_grounding()],
    }
    base.update(overrides)
    return base


def test_valid_grounded_proposal_round_trips() -> None:
    proposal = GroundedRepairProposal.model_validate(_proposal())
    assert proposal.canonical_value == "19.99"
    payload = _label_payload(proposal)
    assert payload["target_kind"] == "field"
    assert payload["grounding"][0]["locator"] == "css:.price"
    assert payload["uncertainty_reason"] == proposal.uncertainty_reason
    assert payload["custom_field"] is None


def test_proposal_without_grounding_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedRepairProposal.model_validate(_proposal(grounding=[]))


def test_proposal_without_css_locator_is_rejected() -> None:
    with pytest.raises(ValidationError, match="css: node/path"):
        GroundedRepairProposal.model_validate(
            _proposal(grounding=[_grounding(locator="xpath://span")])
        )


def test_proposal_without_uncertainty_reason_is_rejected() -> None:
    with pytest.raises(ValidationError):
        GroundedRepairProposal.model_validate(_proposal(uncertainty_reason=""))


def test_proposal_without_a_value_cannot_publish() -> None:
    with pytest.raises(ValidationError, match="adjudicate a grounded value"):
        GroundedRepairProposal.model_validate(_proposal(canonical_value=None))


def test_empty_batch_is_valid_when_nothing_is_grounded() -> None:
    batch = GroundedRepairBatch.model_validate({"proposals": []})
    assert batch.proposals == ()


def test_grounded_repair_is_a_supported_llm_task() -> None:
    assert "grounded_extraction_repair" in SUPPORTED_TASK_TYPES


def test_undeclared_custom_field_is_rejected() -> None:
    batch = GroundedRepairBatch.model_validate(
        {"proposals": [_proposal(field_name="warranty_terms")]}
    )
    with pytest.raises(GroundedRepairContractError, match="typed grounding"):
        _reject_undeclared_custom_fields(batch, surface="ecommerce_detail")


def test_declared_custom_field_is_accepted() -> None:
    batch = GroundedRepairBatch.model_validate(
        {
            "proposals": [
                _proposal(
                    field_name="warranty_terms",
                    custom_field={
                        "value_type": "string",
                        "cardinality": "single",
                        "validation": "non-empty text",
                        "publish_policy": "retain_only",
                    },
                )
            ]
        }
    )
    _reject_undeclared_custom_fields(batch, surface="ecommerce_detail")
    payload = _label_payload(batch.proposals[0])
    assert payload["custom_field"] == {
        "value_type": "string",
        "cardinality": "single",
        "validation": "non-empty text",
        "publish_policy": "retain_only",
    }
    label = GroundedLabel.model_validate(
        {
            **payload,
            "label_id": "model-label-1",
            "authority": "unverified_model",
        }
    )
    assert label.custom_field == payload["custom_field"]
    assert label.uncertainty_reason == batch.proposals[0].uncertainty_reason


def test_standard_field_needs_no_declaration() -> None:
    batch = GroundedRepairBatch.model_validate({"proposals": [_proposal()]})
    _reject_undeclared_custom_fields(batch, surface="ecommerce_detail")


def test_custom_field_declaration_rejects_unknown_type() -> None:
    with pytest.raises(ValidationError, match="Unsupported custom field type"):
        CustomFieldDeclaration.model_validate(
            {
                "value_type": "wormhole",
                "cardinality": "single",
                "validation": "x",
                "publish_policy": "retain_only",
            }
        )
