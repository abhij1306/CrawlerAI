from __future__ import annotations

from app.services.extraction.contracts import Decision, DerivedFact, Evidence, ResolutionResult
from app.services.extraction.entities import EntitySet

PUBLIC_MAP = {
    "product.url": "url",
    "product.title": "title",
    "product.brand": "brand",
    "product.description": "description",
    "product.category": "category",
    "product.sku": "sku",
    "product.mpn": "mpn",
    "product.gtin": "gtin",
    "offer.price": "price",
    "offer.currency": "currency",
    "offer.original_price": "original_price",
    "offer.availability": "availability",
    "asset.image_url": "image_url",
}


def lineage(decision: Decision | None = None, derived: DerivedFact | None = None) -> dict[str, object]:
    if derived is not None:
        return {
            "derived_fact_id": derived.derived_fact_id,
            "rule_id": derived.rule_id,
            "evidence_ids": list(derived.input_evidence_ids),
        }
    if decision is None:
        return {}
    return {
        "decision_id": decision.decision_id,
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rule_id": decision.rule_id,
    }


def materialize(entities: EntitySet, resolution: ResolutionResult, evidence: tuple[Evidence, ...]) -> dict[str, object]:
    by_id = {ev.evidence_id: ev for ev in evidence}
    derived = {(item.entity_id, item.fact_type): item for item in resolution.derived_facts}
    record: dict[str, object] = {}
    lineages: dict[str, object] = {}
    for decision in resolution.decisions:
        field = PUBLIC_MAP.get(decision.fact_type)
        if not field or decision.status != "resolved" or not decision.accepted_evidence_ids:
            continue
        value = derived.get((decision.entity_id, decision.fact_type))
        record[field] = value.value if value is not None else by_id[decision.accepted_evidence_ids[0]].value
        lineages[field] = lineage(derived=value) if value else lineage(decision=decision)
    variants, variant_lineage = _variants(entities, resolution, by_id)
    if variants:
        record["variants"] = variants
        lineages["variants"] = variant_lineage
    if lineages:
        record["_lineage"] = lineages
    return {key: value for key, value in record.items() if value not in (None, "", [], {})}


def _variants(
    entities: EntitySet,
    resolution: ResolutionResult,
    by_id: dict[str, Evidence],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    decisions = {(d.entity_id, d.fact_type): d for d in resolution.decisions if d.status == "resolved"}
    rows: list[dict[str, object]] = []
    lineage_rows: list[dict[str, object]] = []
    for variant in entities.variants:
        row: dict[str, object] = {"selected": variant.selected}
        lineage_row: dict[str, object] = {}
        for fact, field in {"variant.sku": "sku", "variant.gtin": "gtin", "variant.url": "url"}.items():
            decision = decisions.get((variant.entity_id, fact))
            if decision and decision.accepted_evidence_ids:
                row[field] = by_id[decision.accepted_evidence_ids[0]].value
                lineage_row[field] = lineage(decision=decision)
        row.update(variant.option_values)
        for fact, decision in decisions.items():
            entity_id, fact_type = fact
            if entity_id != variant.entity_id or not fact_type.startswith("variant.option."):
                continue
            field = fact_type.rsplit(".", 1)[-1]
            lineage_row[field] = lineage(decision=decision)
        if len(row) > 1:
            rows.append(row)
            lineage_rows.append(lineage_row)
    return rows, lineage_rows
