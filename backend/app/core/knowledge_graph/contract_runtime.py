"""Frozen contract execution for extraction (Slice 7).

Pure, storage-free runtime that matches pages against frozen templates and
applies saved extraction contracts to prefer learned sources when current
evidence validates them. No DB access; called by the extraction engine.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.extraction.contracts import ContractOutcome, Decision, ResolutionResult

if TYPE_CHECKING:
    from app.extraction.contracts import Evidence


def match_template(
    snapshot: dict[str, Any], fingerprint: str, surface: str
) -> dict[str, Any] | None:
    """Match page fingerprint against frozen templates in snapshot.

    Returns the matched template dict or None if no match found.
    """
    if not snapshot or snapshot.get("surface") != surface:
        return None

    for template in snapshot.get("templates", []):
        if template.get("fingerprint") == fingerprint:
            return template

    return None


def apply_contracts(
    snapshot: dict[str, Any],
    fingerprint: str,
    surface: str,
    evidence: tuple[Evidence, ...],
    resolution: ResolutionResult,
    requested_fields: frozenset[str],
    user_controlled_fields: frozenset[str],
) -> tuple[ResolutionResult, tuple[ContractOutcome, ...]]:
    """Apply frozen extraction contracts to resolution, preferring saved sources.

    Re-points decisions to preferred sources when current evidence validates them;
    falls back to generic resolution otherwise. Returns updated ResolutionResult
    with regenerated derived_facts for price fields, plus contract outcomes.

    Fields in user_controlled_fields are skipped (never override explicit rules).
    """
    template = match_template(snapshot, fingerprint, surface)
    if not template:
        return resolution, ()

    contracts = {c["canonical_field"]: c for c in template.get("contracts", [])}
    if not contracts:
        return resolution, ()

    evidence_by_id = {e.evidence_id: e for e in evidence}
    decisions_by_field = {d.fact_type: d for d in resolution.decisions}
    outcomes: list[ContractOutcome] = []
    modified_decisions: dict[str, Decision] = {}

    for field, contract in contracts.items():
        if field not in requested_fields or field in user_controlled_fields:
            continue

        selected_source = contract.get("selected_source", "")
        selection_origin = contract.get("selection_origin", "generic")
        decision = decisions_by_field.get(field)

        if not decision:
            outcome_code = "miss"
            detail = "field unresolved"
            outcomes.append(
                ContractOutcome(
                    field=field,
                    outcome=outcome_code,
                    selected_source=selected_source,
                    selection_origin=selection_origin,
                    applied=False,
                    detail=detail,
                )
            )
            continue

        if not selected_source:
            continue

        # Find matching non-rejected evidence for preferred source
        preferred_evidence = None
        stale_evidence = None

        for ev in evidence:
            if ev.fact_type != field:
                continue
            source_desc = _source_descriptor(ev)
            if source_desc == selected_source:
                # Check if this evidence was rejected in current resolution
                rejected_ids = {r.evidence_id for r in decision.rejected}
                if ev.evidence_id in rejected_ids:
                    stale_evidence = ev
                else:
                    preferred_evidence = ev
                    break

        if preferred_evidence:
            # Re-point decision to preferred source
            new_decision = Decision(
                decision_id=decision.decision_id,
                entity_id=decision.entity_id,
                fact_type=decision.fact_type,
                accepted_evidence_ids=(preferred_evidence.evidence_id,),
                rejected=decision.rejected,
                finding_ids=decision.finding_ids,
                rule_id=contract.get("resolver_rule", decision.rule_id),
                status="resolved",
            )
            modified_decisions[field] = new_decision
            outcomes.append(
                ContractOutcome(
                    field=field,
                    outcome="hit",
                    selected_source=selected_source,
                    selection_origin=selection_origin,
                    applied=True,
                    detail=f"re-pointed to {selected_source}",
                )
            )
        elif stale_evidence:
            outcomes.append(
                ContractOutcome(
                    field=field,
                    outcome="stale_source",
                    selected_source=selected_source,
                    selection_origin=selection_origin,
                    applied=False,
                    detail="preferred source present but rejected",
                )
            )
        elif decision.status == "resolved":
            # Preferred absent but generic resolved
            outcome_code = (
                "override_miss" if selection_origin == "operator" else "fallback"
            )
            outcomes.append(
                ContractOutcome(
                    field=field,
                    outcome=outcome_code,
                    selected_source=selected_source,
                    selection_origin=selection_origin,
                    applied=False,
                    detail="preferred source absent, used generic",
                )
            )
        else:
            outcomes.append(
                ContractOutcome(
                    field=field,
                    outcome="miss",
                    selected_source=selected_source,
                    selection_origin=selection_origin,
                    applied=False,
                    detail="field unresolved",
                )
            )

    if not modified_decisions:
        return resolution, tuple(outcomes)

    # Build updated decisions tuple
    updated_decisions = tuple(
        modified_decisions.get(d.fact_type, d) for d in resolution.decisions
    )

    # Regenerate derived_facts for price fields
    from app.extraction.resolution import _derived

    updated_derived = _derived(list(updated_decisions), evidence_by_id)
    updated_unresolved = tuple(
        field
        for field in resolution.unresolved_fact_types
        if decisions_by_field.get(field) is None
        or modified_decisions.get(field, decisions_by_field[field]).status != "resolved"
    )
    resolved_finding_ids = {
        finding_id
        for decision in modified_decisions.values()
        if decision.status == "resolved"
        for finding_id in decision.finding_ids
    }
    updated_blocking = tuple(
        finding_id
        for finding_id in resolution.blocking_finding_ids
        if finding_id not in resolved_finding_ids
    )

    return (
        ResolutionResult(
            primary_product_entity_id=resolution.primary_product_entity_id,
            primary_offer_entity_id=resolution.primary_offer_entity_id,
            decisions=updated_decisions,
            asset_decisions=resolution.asset_decisions,
            derived_facts=updated_derived,
            unresolved_fact_types=updated_unresolved,
            blocking_finding_ids=updated_blocking,
        ),
        tuple(outcomes),
    )


def _source_descriptor(evidence: Evidence) -> str:
    """Build source descriptor matching projection format."""
    parts = [evidence.collector_id]
    if evidence.locator:
        parts.append(evidence.locator.value[:80])
    return ":".join(parts)
