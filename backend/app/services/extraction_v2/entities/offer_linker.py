from __future__ import annotations

from collections import defaultdict

from app.services.extraction_v2.contracts import CaptureBundle, Evidence
from app.services.extraction_v2.entities.contracts import OfferEntity, VariantEntity
from app.services.extraction_v2.ids import stable_id


def link_offers(bundle: CaptureBundle, evidence: tuple[Evidence, ...], product_id: str, variants: tuple[VariantEntity, ...]) -> tuple[OfferEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if ev.fact_type.startswith("offer."):
            groups[ev.group_id or f"ungrouped:{ev.evidence_id}"].append(ev)
    offers: list[OfferEntity] = []
    for group_id, rows in sorted(groups.items()):
        attrs: dict[str, list[str]] = defaultdict(list)
        for ev in rows:
            attrs[ev.fact_type].append(ev.evidence_id)
        variant_id = _variant_for(rows, variants)
        offers.append(OfferEntity(entity_id=stable_id("offer", product_id, variant_id, group_id), product_entity_id=product_id, variant_entity_id=variant_id, group_id=group_id, request_context_id=bundle.request_context.context_id, fact_evidence={name: tuple(sorted(set(ids))) for name, ids in attrs.items()}))
    return tuple(offers)


def _variant_for(rows: list[Evidence], variants: tuple[VariantEntity, ...]) -> str | None:
    skus = {str(ev.entity_hint.sku) for ev in rows if ev.entity_hint and ev.entity_hint.sku}
    for variant in variants:
        if any(str(item).split(":", 1)[-1] in skus for item in (variant.identity_key,)):
            return variant.entity_id
    return None
