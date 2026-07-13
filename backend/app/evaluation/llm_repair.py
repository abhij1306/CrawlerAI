"""Grounded LLM repair (Phase 7, offline / operator-loop).

An LLM may only *propose* grounded corrections. Every proposal must reference
grounded evidence (a ``css:`` node/path) and an uncertainty reason; the model
adjudicates existing evidence or proposes repair diffs, it never emits a
free-form value. Proposals become ``unverified_model`` grounded labels and route
through the same compile, replay, and activation gates as operator corrections
(:func:`app.evaluation.grounded_corrections.save_grounded_correction`) — but the
model can never publish an ungrounded standard value and can never self-activate
a rule (activation is withheld; a human operator approves separately). Rejected
or replay-failed proposals are retained as labels/evidence, never published.

This module is offline: the extraction hot path must never import it.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.llm.tasks import run_prompt_task
from app.core.config.evaluation import (
    GROUNDED_REPAIR_CUSTOM_FIELD_CARDINALITIES,
    GROUNDED_REPAIR_CUSTOM_FIELD_TYPES,
    GROUNDED_REPAIR_LLM_TASK,
    GROUNDED_REPAIR_NO_PROPOSALS_STATUS,
    GROUNDED_REPAIR_PUBLISH_POLICIES,
)
from app.core.domain_utils import normalize_domain
from app.core.records.field_policy import (
    canonical_fields_for_surface,
    normalize_field_key,
)
from app.models.crawl_run import CrawlRun

_UNVERIFIED_MODEL_AUTHORITY = "unverified_model"
_CSS_LOCATOR_PREFIX = "css:"


class GroundedRepairContractError(ValueError):
    """An LLM repair proposal violated the grounded rule-proposal contract."""


class RepairGrounding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["node", "path"]
    artifact_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class CustomFieldDeclaration(BaseModel):
    """Typed declaration required before a non-standard field may be proposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    value_type: str = Field(min_length=1)
    cardinality: str = Field(min_length=1)
    validation: str = Field(min_length=1)
    publish_policy: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_declaration(self) -> CustomFieldDeclaration:
        if self.value_type not in GROUNDED_REPAIR_CUSTOM_FIELD_TYPES:
            raise ValueError(f"Unsupported custom field type: {self.value_type}")
        if self.cardinality not in GROUNDED_REPAIR_CUSTOM_FIELD_CARDINALITIES:
            raise ValueError(
                f"Unsupported custom field cardinality: {self.cardinality}"
            )
        if self.publish_policy not in GROUNDED_REPAIR_PUBLISH_POLICIES:
            raise ValueError(f"Unsupported publish policy: {self.publish_policy}")
        return self


class GroundedRepairProposal(BaseModel):
    """One grounded adjudication or repair diff — never a free-form value."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_name: str = Field(min_length=1)
    subject_id: str = Field(min_length=1)
    canonical_value: JsonValue = None
    semantic_role: str = Field(min_length=1)
    locale_interpretation: str = Field(min_length=1)
    uncertainty_reason: str = Field(min_length=1)
    grounding: tuple[RepairGrounding, ...] = Field(min_length=1)
    custom_field: CustomFieldDeclaration | None = None

    @model_validator(mode="after")
    def _validate_grounded_adjudication(self) -> GroundedRepairProposal:
        if self.canonical_value is None:
            raise ValueError(
                "Grounded repair proposals must adjudicate a grounded value"
            )
        if not any(_is_css_reference(reference) for reference in self.grounding):
            raise ValueError(
                "Grounded repair requires at least one css: node/path reference"
            )
        return self


class GroundedRepairBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    proposals: tuple[GroundedRepairProposal, ...] = ()


def _is_css_reference(reference: RepairGrounding) -> bool:
    locator = reference.locator.strip()
    return (
        reference.kind in {"node", "path"}
        and locator.startswith(_CSS_LOCATOR_PREFIX)
        and bool(locator.removeprefix(_CSS_LOCATOR_PREFIX).strip())
    )


def _label_payload(proposal: GroundedRepairProposal) -> dict[str, object]:
    return {
        "target_kind": "field",
        "field_name": proposal.field_name,
        "subject_id": proposal.subject_id,
        "canonical_value": proposal.canonical_value,
        "semantic_role": proposal.semantic_role,
        "locale_interpretation": proposal.locale_interpretation,
        "uncertainty_reason": proposal.uncertainty_reason,
        "custom_field": (
            proposal.custom_field.model_dump(mode="json")
            if proposal.custom_field is not None
            else None
        ),
        "grounding": [
            {"kind": ref.kind, "artifact_id": ref.artifact_id, "locator": ref.locator}
            for ref in proposal.grounding
        ],
    }


def _reject_undeclared_custom_fields(
    batch: GroundedRepairBatch, *, surface: str
) -> None:
    known = {
        normalize_field_key(name) for name in canonical_fields_for_surface(surface)
    }
    for proposal in batch.proposals:
        is_custom = normalize_field_key(proposal.field_name) not in known
        if is_custom and proposal.custom_field is None:
            raise GroundedRepairContractError(
                f"Custom field '{proposal.field_name}' requires a typed grounding "
                "declaration (type, cardinality, validation, publish policy)"
            )


async def apply_grounded_repair(
    session: AsyncSession,
    *,
    run: CrawlRun,
    batch: GroundedRepairBatch,
    representative_url_result_ids: list[int] | None = None,
) -> dict[str, object]:
    """Route grounded LLM proposals through the operator-correction gates.

    Labels carry ``unverified_model`` authority (never release-eligible) and
    activation is never requested, so the model can neither publish an ungrounded
    value nor activate a rule. Compile + representative replay still run so an
    operator can review before approving.
    """
    _reject_undeclared_custom_fields(batch, surface=run.surface)
    if not batch.proposals:
        return {
            "correction_id": None,
            "domain": normalize_domain(run.url),
            "surface": run.surface,
            "label_count": 0,
            "activation_status": GROUNDED_REPAIR_NO_PROPOSALS_STATUS,
            "replay": None,
        }
    return {
        "correction_id": None,
        "domain": normalize_domain(run.url),
        "surface": run.surface,
        "label_count": len(batch.proposals),
        "activation_status": "recipe_candidate_required",
        "replay": None,
    }


async def run_grounded_repair(
    session: AsyncSession,
    *,
    run: CrawlRun,
    variables: dict[str, Any],
    representative_url_result_ids: list[int] | None = None,
) -> dict[str, object]:
    """Invoke the grounded-repair LLM task and gate its proposals (offline only).

    ``variables`` supplies the bounded prompt input (target schema, compact
    representation, structured objects, existing evidence, operator labels). A
    missing config, transport error, or free-form output yields a diagnostic
    dict rather than raising, so the operator loop degrades cleanly.
    """
    result = await run_prompt_task(
        session,
        task_type=GROUNDED_REPAIR_LLM_TASK,
        run_id=run.id,
        domain=normalize_domain(run.url),
        variables=variables,
    )
    if result.error_message or not isinstance(result.payload, dict):
        return {
            "activation_status": "llm_unavailable",
            "error": result.error_message or "no grounded repair proposals returned",
        }
    batch = GroundedRepairBatch.model_validate(result.payload)
    return await apply_grounded_repair(
        session,
        run=run,
        batch=batch,
        representative_url_result_ids=representative_url_result_ids,
    )
