from __future__ import annotations

from app.services.extraction_v2.contracts import Decision, DerivedFact


def lineage(decision: Decision | None = None, derived: DerivedFact | None = None) -> dict[str, object]:
    if derived is not None:
        return {"derived_fact_id": derived.derived_fact_id, "rule_id": derived.rule_id, "evidence_ids": list(derived.input_evidence_ids)}
    if decision is None:
        return {}
    return {"decision_id": decision.decision_id, "evidence_ids": list(decision.accepted_evidence_ids), "rule_id": decision.rule_id}
