from __future__ import annotations

from app.services.extraction_v2.contracts import Decision, Evidence, Finding
from app.services.extraction_v2.entities.contracts import VariantEntity
from app.services.extraction_v2.resolution.scalar import resolve_scalar


def resolve_variant(variant: VariantEntity, evidence_by_id: dict[str, Evidence], findings: tuple[Finding, ...]) -> tuple[Decision, ...]:
    return tuple(resolve_scalar(variant.entity_id, fact, ids, evidence_by_id, findings) for fact, ids in sorted(variant.attribute_evidence.items()))
