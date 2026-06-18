from __future__ import annotations

from app.services.extraction_v2.contracts import Decision, Evidence, Finding, RejectedEvidence
from app.services.extraction_v2.ids import stable_id


def resolve_scalar(entity_id: str, fact_type: str, ids: tuple[str, ...], evidence_by_id: dict[str, Evidence], findings: tuple[Finding, ...]) -> Decision:
    candidates = sorted((evidence_by_id[eid] for eid in ids if eid in evidence_by_id), key=_rank)
    blocking = {eid for finding in findings if finding.blocking for eid in finding.evidence_ids}
    admissible = [ev for ev in candidates if ev.evidence_id not in blocking and not _invalid(ev)]
    if not admissible:
        return Decision(decision_id=stable_id("decision", entity_id, fact_type, ids), entity_id=entity_id, fact_type=fact_type, accepted_evidence_ids=(), rejected=tuple(RejectedEvidence(evidence_id=ev.evidence_id, reason="blocked_by_finding" if ev.evidence_id in blocking else "invalid_value") for ev in candidates), finding_ids=tuple(f.finding_id for f in findings if set(f.evidence_ids) & set(ids)), rule_id="SCALAR_LEXICOGRAPHIC", status="unresolved")
    winner = admissible[0]
    rejected = tuple(RejectedEvidence(evidence_id=ev.evidence_id, reason="stable_tiebreak" if _rank(ev) == _rank(winner) else "lower_confidence") for ev in candidates if ev.evidence_id != winner.evidence_id)
    return Decision(decision_id=stable_id("decision", entity_id, fact_type, winner.evidence_id), entity_id=entity_id, fact_type=fact_type, accepted_evidence_ids=(winner.evidence_id,), rejected=rejected, finding_ids=tuple(f.finding_id for f in findings if set(f.evidence_ids) & set(ids)), rule_id="SCALAR_LEXICOGRAPHIC", status="resolved")


def _invalid(ev: Evidence) -> bool:
    return bool(set(ev.flags) & {"invalid_decimal", "invalid_currency", "invalid_gtin", "placeholder_text", "tracking_url"})


def _rank(ev: Evidence) -> tuple[int, int, float, str]:
    directness = {"direct": 0, "embedded": 1, "inferred": 2}.get(ev.directness, 3)
    reliability = {"jsonld": 0, "microdata": 1, "js_state": 2, "network": 3, "opengraph": 4, "dom": 5, "url": 6}.get(ev.collector_id, 7)
    return directness, reliability, -float(ev.confidence), ev.evidence_id
