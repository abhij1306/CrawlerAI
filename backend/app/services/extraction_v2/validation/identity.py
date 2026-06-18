from __future__ import annotations

from app.services.extraction_v2.contracts import Evidence, Finding
from app.services.extraction_v2.entities.contracts import EntitySet
from app.services.extraction_v2.ids import stable_id


def validate_identity(evidence: tuple[Evidence, ...], entities: EntitySet) -> tuple[Finding, ...]:
    if not entities.products:
        ids = tuple(sorted(ev.evidence_id for ev in evidence if ev.fact_type.startswith("product.")))
        return (finding("MISSING_PRODUCT_IDENTITY", (), ids, "No primary product entity.", True),)
    if len(entities.products) > 1:
        return (finding("PRIMARY_PRODUCT_AMBIGUOUS", tuple(p.entity_id for p in entities.products), (), "Primary product ambiguous.", True),)
    return ()


def finding(rule: str, entity_ids: tuple[str, ...], evidence_ids: tuple[str, ...], message: str, blocking: bool) -> Finding:
    return Finding(finding_id=stable_id("finding", rule, entity_ids, evidence_ids), rule_id=rule, severity="high" if blocking else "medium", entity_ids=entity_ids, evidence_ids=evidence_ids, message=message, blocking=blocking)
