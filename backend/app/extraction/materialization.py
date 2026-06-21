from __future__ import annotations

from app.extraction.contracts import (
    AssetDecision,
    CommerceDetailRecord,
    CommerceVariantRecord,
    Decision,
    DerivedFact,
    Evidence,
    ResolutionResult,
)
from app.core.config.variant_policy import DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
from app.extraction.entities import EntitySet

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


def materialize(
    entities: EntitySet,
    resolution: ResolutionResult,
    evidence: tuple[Evidence, ...],
    *,
    canonical_url: str,
) -> CommerceDetailRecord:
    by_id = {ev.evidence_id: ev for ev in evidence}
    derived = {(item.entity_id, item.fact_type): item for item in resolution.derived_facts}
    record: dict[str, object] = {}
    lineages: dict[str, object] = {}
    selector_traces: dict[str, object] = {}
    for decision in resolution.decisions:
        field = PUBLIC_MAP.get(decision.fact_type)
        if not field or decision.status != "resolved" or not decision.accepted_evidence_ids:
            continue
        value = derived.get((decision.entity_id, decision.fact_type))
        accepted = by_id[decision.accepted_evidence_ids[0]]
        record[field] = value.value if value is not None else accepted.value
        lineages[field] = lineage(derived=value) if value else lineage(decision=decision)
        if (
            accepted.locator.kind == "css_selector"
            and not accepted.metadata.get("derived_by")
        ):
            selector_traces[field] = {
                "selector_kind": "css_selector",
                "selector_value": accepted.locator.value,
                "selector_source": accepted.collector_id,
                "sample_value": accepted.value,
            }
    _materialize_product_assets(record, lineages, resolution.asset_decisions)
    if not record.get("url"):
        record["url"] = canonical_url
        lineages["url"] = {"rule_id": "canonical_capture_url", "evidence_ids": []}
    variants, variant_lineage = _variants(entities, resolution, by_id)
    if variants:
        record["variants"] = variants
        lineages["variants"] = variant_lineage
        _cohere_parent_availability(
            record,
            lineages,
            variants,
            variant_lineage,
            expected_variant_count=len(entities.variants),
        )
    if lineages:
        record["_lineage"] = lineages
    if selector_traces:
        record["_selector_traces"] = selector_traces
    return _typed_detail_record(record)


def _cohere_parent_availability(
    record: dict[str, object],
    lineages: dict[str, object],
    variants: list[dict[str, object]],
    variant_lineage: list[dict[str, object]],
    *,
    expected_variant_count: int,
) -> None:
    if len(variants) != expected_variant_count or any(
        isinstance(row.get("availability"), dict)
        and row["availability"].get("rule_id") == DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID
        for row in variant_lineage
    ):
        return
    availability = [str(row.get("availability") or "") for row in variants]
    if not availability or any(value not in {"in_stock", "out_of_stock"} for value in availability):
        return
    evidence_ids = tuple(
        str(evidence_id)
        for row in variant_lineage
        for evidence_id in _lineage_evidence_ids(row.get("availability"))
    )
    record["availability"] = "in_stock" if "in_stock" in availability else "out_of_stock"
    lineages["availability"] = {
        "rule_id": "variant_availability_aggregate",
        "evidence_ids": list(dict.fromkeys(evidence_ids)),
    }


def _lineage_evidence_ids(value: object) -> tuple[object, ...]:
    if not isinstance(value, dict):
        return ()
    evidence_ids = value.get("evidence_ids")
    if isinstance(evidence_ids, (list, tuple)):
        return tuple(evidence_ids)
    return ()


def _variants(
    entities: EntitySet,
    resolution: ResolutionResult,
    by_id: dict[str, Evidence],
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    decisions = {(d.entity_id, d.fact_type): d for d in resolution.decisions if d.status == "resolved"}
    derived = {(item.entity_id, item.fact_type): item for item in resolution.derived_facts}
    rows: list[dict[str, object]] = []
    lineage_rows: list[dict[str, object]] = []
    offer_by_variant = {
        offer.variant_entity_id: offer
        for offer in entities.offers
        if offer.variant_entity_id
    }
    asset_by_variant = {
        asset.variant_entity_id: asset
        for asset in entities.assets
        if asset.variant_entity_id
    }
    for variant in entities.variants:
        row, lineage_row = _variant_public_row(
            variant,
            decisions,
            derived,
            by_id,
            offer_by_variant.get(variant.entity_id),
            asset_by_variant.get(variant.entity_id),
        )
        if _publishable_variant_row(variant, row):
            rows.append(row)
            lineage_rows.append(lineage_row)
    ordered = sorted(
        zip(rows, lineage_rows),
        key=lambda item: (
            str(item[0].get("color") or ""),
            _size_sort_key(item[0].get("size")),
            str(item[0].get("sku") or ""),
            str(item[0].get("url") or ""),
        ),
    )
    return [row for row, _ in ordered], [item for _, item in ordered]


def _publishable_variant_row(variant, row: dict[str, object]) -> bool:
    if not variant.identity_key:
        return False
    return _has_variant_option(row) or _has_variant_commercial_fact(row)


def _has_variant_option(row: dict[str, object]) -> bool:
    transport_fields = {"variant_id", "sku", "gtin", "url", "image_url", "price", "currency", "availability", "stock_quantity"}
    return any(key not in transport_fields and value not in (None, "", [], {}, ()) for key, value in row.items())


def _has_variant_commercial_fact(row: dict[str, object]) -> bool:
    return any(row.get(field) not in (None, "", [], {}, ()) for field in ("price", "currency", "availability", "stock_quantity"))


def _variant_public_row(variant, decisions, derived, by_id, offer, asset) -> tuple[dict[str, object], dict[str, object]]:
    row: dict[str, object] = {}
    lineage_row: dict[str, object] = {}
    for fact, field in {
        "variant.id": "variant_id",
        "variant.sku": "sku",
        "variant.gtin": "gtin",
        "variant.url": "url",
    }.items():
        decision = decisions.get((variant.entity_id, fact))
        if decision and decision.accepted_evidence_ids:
            row[field] = by_id[decision.accepted_evidence_ids[0]].value
            lineage_row[field] = lineage(decision=decision)
    row.update(variant.option_values)
    _variant_option_lineage(variant, decisions, lineage_row)
    _variant_offer_fields(row, lineage_row, variant, offer, decisions, derived, by_id)
    _variant_asset_field(row, lineage_row, asset, decisions, by_id)
    return row, lineage_row


def _variant_option_lineage(variant, decisions, lineage_row: dict[str, object]) -> None:
    for fact, decision in decisions.items():
        entity_id, fact_type = fact
        if entity_id == variant.entity_id and fact_type.startswith("variant.option."):
            lineage_row[fact_type.rsplit(".", 1)[-1]] = lineage(decision=decision)


def _variant_offer_fields(row, lineage_row, variant, offer, decisions, derived, by_id) -> None:
    for fact, field in {"offer.price": "price", "offer.currency": "currency", "offer.original_price": "original_price", "offer.availability": "availability", "offer.stock_quantity": "stock_quantity"}.items():
        decision = decisions.get((offer.entity_id, fact)) if offer else None
        decision = decision or decisions.get((variant.entity_id, fact))
        if not decision or not decision.accepted_evidence_ids:
            continue
        value = derived.get((decision.entity_id, fact))
        row[field] = value.value if value is not None else by_id[decision.accepted_evidence_ids[0]].value
        lineage_row[field] = lineage(derived=value) if value else lineage(decision=decision)


def _variant_asset_field(row, lineage_row, asset, decisions, by_id) -> None:
    decision = decisions.get((asset.entity_id, "asset.image_url")) if asset else None
    if decision and decision.accepted_evidence_ids:
        row["image_url"] = asset.url
        lineage_row["image_url"] = lineage(decision=decision)


def _size_sort_key(value: object) -> tuple[int, str]:
    text = str(value or "").strip().casefold()
    order = {"xxs": 1, "xs": 2, "s": 3, "m": 4, "l": 5, "xl": 6, "xxl": 7}
    return order.get(text, 100), text


def _typed_detail_record(record: dict[str, object]) -> CommerceDetailRecord:
    cleaned = {key: value for key, value in record.items() if value not in (None, "", [], {})}
    variants = cleaned.get("variants")
    if isinstance(variants, list):
        cleaned["variants"] = tuple(
            CommerceVariantRecord.model_validate(row).model_dump(exclude_none=True)
            for row in variants
            if isinstance(row, dict)
        )
    return CommerceDetailRecord.model_validate(cleaned)


def _materialize_product_assets(
    record: dict[str, object],
    lineages: dict[str, object],
    asset_decisions: tuple[AssetDecision, ...],
) -> None:
    selected = [item for item in asset_decisions if item.url and item.accepted_evidence_ids]
    primary = next((item for item in selected if item.role == "primary"), None)
    if primary is None:
        return
    record["image_url"] = primary.url
    lineages["image_url"] = _asset_lineage(primary)
    primary_url = str(primary.url)
    additional: list[str] = []
    additional_lineage: list[dict[str, object]] = []
    for item in selected:
        if item.role != "additional" or str(item.url) == primary_url:
            continue
        if str(item.url) in additional:
            continue
        additional.append(str(item.url))
        additional_lineage.append(_asset_lineage(item))
    if additional:
        record["additional_images"] = tuple(additional)
        lineages["additional_images"] = additional_lineage


def _asset_lineage(decision: AssetDecision) -> dict[str, object]:
    return {
        "asset_entity_id": decision.asset_entity_id,
        "evidence_ids": list(decision.accepted_evidence_ids),
        "rank": decision.rank,
        "role": decision.role,
        "rule_id": decision.rule_id,
    }
