from __future__ import annotations

from app.services.extraction_v2.contracts import Evidence
from app.services.extraction_v2.entities.contracts import ProductEntity
from app.services.extraction_v2.ids import stable_id


def link_product(evidence: tuple[Evidence, ...]) -> ProductEntity | None:
    product_evidence = [ev for ev in evidence if ev.fact_type.startswith("product.")]
    if not product_evidence:
        return None
    identity = [ev for ev in product_evidence if ev.fact_type in {"product.gtin", "product.mpn", "product.sku", "product.url"}]
    entity_id = stable_id("product", tuple(sorted((ev.fact_type, ev.value) for ev in identity)) or "primary")
    attributes: dict[str, list[str]] = {}
    for ev in product_evidence:
        attributes.setdefault(ev.fact_type, []).append(ev.evidence_id)
    return ProductEntity(
        entity_id=entity_id,
        identity_evidence_ids=tuple(sorted(ev.evidence_id for ev in identity or product_evidence)),
        attribute_evidence={key: tuple(sorted(set(ids))) for key, ids in attributes.items()},
        variant_ids=(),
        offer_ids=(),
        asset_ids=(),
    )
