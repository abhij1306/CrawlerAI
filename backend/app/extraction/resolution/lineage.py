"""Lineage construction and resolved-value lookups shared by resolvers."""

from __future__ import annotations

from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.core.shared.ids import stable_id
from app.extraction.contracts import Decision, DerivedFact, Evidence


def _resolved_value_and_lineage(
    entity_id: str,
    fact_type: str,
    decisions: tuple[Decision, ...],
    derived_facts: tuple[DerivedFact, ...],
    evidence_by_id: dict[str, Evidence],
) -> tuple[object, dict[str, object]] | None:
    derived = next(
        (
            row
            for row in reversed(derived_facts)
            if row.entity_id == entity_id and row.fact_type == fact_type
        ),
        None,
    )
    if derived is not None:
        return derived.value, _derived_lineage(derived)
    decision = next(
        (
            row
            for row in decisions
            if row.entity_id == entity_id
            and row.fact_type == fact_type
            and row.status == "resolved"
            and row.accepted_evidence_ids
        ),
        None,
    )
    if decision is None:
        return None
    evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return None
    return evidence.value, _decision_lineage(decision)


def _aggregate_fact(
    entity_id: str,
    fact_type: str,
    value: object,
    evidence_ids: tuple[str, ...],
    rule_id: str,
    *,
    input_selected_fact_ids: tuple[str, ...] = (),
    input_derived_fact_ids: tuple[str, ...] = (),
) -> DerivedFact:
    return DerivedFact(
        derived_fact_id=stable_id("derived", rule_id, entity_id, fact_type, value),
        entity_id=entity_id,
        fact_type=fact_type,
        value=value,
        input_evidence_ids=evidence_ids,
        input_selected_fact_ids=input_selected_fact_ids,
        input_derived_fact_ids=input_derived_fact_ids,
        rule_id=rule_id,
    )


def _has_parent_inherited_lineage(values) -> bool:
    return any(
        isinstance(item, dict)
        and item.get("rule_id") == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        for item in values
    )


def _lineage_evidence_ids(values) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        evidence_ids = value.get("evidence_ids")
        if not isinstance(evidence_ids, (list, tuple)):
            continue
        out.extend(str(evidence_id) for evidence_id in evidence_ids)
    return tuple(dict.fromkeys(out))


def _lineage_reference_ids(values, key: str) -> tuple[str, ...]:
    out: list[str] = []
    for value in values:
        if not isinstance(value, dict):
            continue
        reference = value.get(key)
        if reference:
            out.append(str(reference))
    return tuple(dict.fromkeys(out))


def _put_decision_value(values, lineage, field, decision, evidence_by_id) -> None:
    if not decision or not decision.accepted_evidence_ids:
        return
    evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
    if evidence is None:
        return
    values[field] = evidence.value
    lineage[field] = _decision_lineage(decision)


def _resolved_product_url(decisions: list[Decision], evidence_by_id) -> str:
    for decision in decisions:
        if (
            decision.fact_type == "product.url"
            and decision.status == "resolved"
            and decision.accepted_evidence_ids
        ):
            evidence = evidence_by_id.get(decision.accepted_evidence_ids[0])
            if evidence:
                return str(evidence.value or "")
    return ""


def _decision_lineage(decision: Decision) -> dict[str, object]:
    return {
        "decision_id": decision.decision_id,
        "selected_fact_id": stable_id("selected", decision.decision_id),
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rule_id": decision.rule_id,
    }


def _derived_lineage(derived: DerivedFact) -> dict[str, object]:
    return {
        "derived_fact_id": derived.derived_fact_id,
        "evidence_ids": list(derived.input_evidence_ids),
        "rule_id": derived.rule_id,
    }
