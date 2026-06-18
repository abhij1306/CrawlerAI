from __future__ import annotations

from app.services.extraction_v2.contracts import Decision, Evidence, Finding
from app.services.extraction_v2.entities.contracts import AssetEntity
from app.services.extraction_v2.resolution.scalar import resolve_scalar


def resolve_asset(asset: AssetEntity, evidence_by_id: dict[str, Evidence], findings: tuple[Finding, ...]) -> Decision:
    return resolve_scalar(asset.entity_id, "asset.image_url", asset.url_evidence_ids, evidence_by_id, findings)
