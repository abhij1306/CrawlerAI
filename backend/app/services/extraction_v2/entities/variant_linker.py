from __future__ import annotations

from collections import defaultdict

from app.services.extraction_v2.contracts import Evidence
from app.services.extraction_v2.entities.contracts import VariantEntity
from app.services.extraction_v2.ids import stable_id


def link_variants(evidence: tuple[Evidence, ...], product_id: str) -> tuple[VariantEntity, ...]:
    groups: dict[str, list[Evidence]] = defaultdict(list)
    for ev in evidence:
        if not ev.fact_type.startswith("variant."):
            continue
        key = _variant_key(ev)
        if key:
            groups[key].append(ev)
    variants: list[VariantEntity] = []
    for key, rows in sorted(groups.items()):
        options = {ev.fact_type.removeprefix("variant.option."): str(ev.value) for ev in rows if ev.fact_type.startswith("variant.option.")}
        attrs: dict[str, list[str]] = defaultdict(list)
        for ev in rows:
            attrs[ev.fact_type].append(ev.evidence_id)
        variants.append(VariantEntity(entity_id=stable_id("variant", product_id, key), product_entity_id=product_id, identity_key=key, identity_evidence_ids=tuple(sorted(ev.evidence_id for ev in rows if ev.fact_type in {"variant.id", "variant.sku", "variant.gtin", "variant.url"})) or tuple(sorted(ev.evidence_id for ev in rows)), option_values=options, attribute_evidence={name: tuple(sorted(set(ids))) for name, ids in attrs.items()}, offer_ids=(), asset_ids=(), selected=any(ev.fact_type == "variant.selected" and bool(ev.value) for ev in rows)))
    return tuple(variants)


def _variant_key(ev: Evidence) -> str:
    hint = ev.entity_hint
    if hint and hint.variant_id:
        return f"id:{hint.variant_id}"
    if ev.fact_type in {"variant.id", "variant.sku", "variant.gtin", "variant.url"}:
        return f"{ev.fact_type}:{ev.value}"
    if ev.group_id:
        return f"group:{ev.group_id}"
    if hint and hint.sku:
        return f"sku:{hint.sku}"
    return ""
