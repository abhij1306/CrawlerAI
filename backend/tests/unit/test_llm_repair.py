"""Contract tests for grounded LLM repair (Phase 7).

These are pure, DB-free checks of the proposal contract: the model cannot emit an
ungrounded value, cannot skip its uncertainty reason, and cannot introduce a
non-standard field without a typed declaration.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.evaluation.llm_repair import (
    CustomFieldDeclaration,
    GroundedRepairBatch,
    GroundedRepairContractError,
    GroundedRepairProposal,
    _label_payload,
    _reject_undeclared_custom_fields,
)


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


def test_batch_requires_at_least_one_proposal() -> None:
    with pytest.raises(ValidationError):
        GroundedRepairBatch.model_validate({"proposals": []})


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
