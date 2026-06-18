from __future__ import annotations

from app.services.extraction_v2.contracts import Decision, Evidence, Finding
from app.services.extraction_v2.entities.contracts import OfferEntity
from app.services.extraction_v2.resolution.scalar import resolve_scalar


def resolve_offer(offer: OfferEntity, evidence_by_id: dict[str, Evidence], findings: tuple[Finding, ...]) -> tuple[Decision, ...]:
    if not offer.fact_evidence.get("offer.price") or not offer.fact_evidence.get("offer.currency"):
        return ()
    return tuple(
        resolve_scalar(offer.entity_id, fact, ids, evidence_by_id, findings)
        for fact, ids in sorted(offer.fact_evidence.items())
    )
