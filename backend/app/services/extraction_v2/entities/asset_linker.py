from __future__ import annotations

from collections import defaultdict

from app.services.extraction_v2.contracts import Evidence
from app.services.extraction_v2.entities.contracts import AssetEntity, VariantEntity
from app.services.extraction_v2.ids import stable_id


def link_assets(evidence: tuple[Evidence, ...], product_id: str, variants: tuple[VariantEntity, ...]) -> tuple[AssetEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type == "asset.image_url":
            groups[str(ev.value)].append(ev)
    return tuple(
        AssetEntity(
            entity_id=stable_id("asset", product_id, url),
            product_entity_id=product_id,
            variant_entity_id=None,
            url_evidence_ids=tuple(sorted(ev.evidence_id for ev in rows)),
        )
        for url, rows in sorted(groups.items())
    )
