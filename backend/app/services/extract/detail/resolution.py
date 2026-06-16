from __future__ import annotations

from typing import Any

from app.services.config.extraction_rules import (
    AVAILABILITY_IN_STOCK,
    AVAILABILITY_OUT_OF_STOCK,
    AVAILABILITY_UNKNOWN,
)
from app.services.config.variant_policy import (
    DETAIL_PARENT_INHERITED_OFFER_FIELDS,
    DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
    DETAIL_NEGATIVE_STOCK_RULE_ID,
    DETAIL_PRODUCT_VARIANT_CONSENSUS_FIELDS,
    DETAIL_PRODUCT_VARIANT_OVERRIDE_FIELDS,
    DETAIL_VARIANT_CONSENSUS_RULE_ID,
)
from app.services.shared.field_coerce import text_or_none

__all__ = ("resolve_detail_entities", "variant_parent_availability_value")


def resolve_detail_entities(record: dict[str, Any]) -> None:
    variants = [row for row in record.get("variants") or [] if isinstance(row, dict)]
    if not variants:
        return
    for field_name in DETAIL_PRODUCT_VARIANT_CONSENSUS_FIELDS:
        consensus = _variant_consensus(variants, field_name)
        if consensus is None:
            continue
        before = record.get(field_name)
        if (
            field_name not in DETAIL_PRODUCT_VARIANT_OVERRIDE_FIELDS
            and before not in (None, "", [], {})
        ):
            continue
        if text_or_none(before) == text_or_none(consensus):
            continue
        record[field_name] = consensus
        _record_transform(record, field_name=field_name, before=before, after=consensus)
    availability = variant_parent_availability_value(record)
    if availability is not None and record.get("availability") != availability:
        before = record.get("availability")
        record["availability"] = availability
        _record_transform(
            record,
            field_name="availability",
            before=before,
            after=availability,
        )
    _complete_variant_offers_from_parent(record, variants)
    _resolve_negative_variant_stock(record, variants)


def variant_parent_availability_value(record: dict[str, Any]) -> str | None:
    variants = [row for row in record.get("variants") or [] if isinstance(row, dict)]
    if not variants:
        return None
    values = {text_or_none(row.get("availability")) for row in variants}
    values.discard(None)
    if AVAILABILITY_IN_STOCK in values:
        return AVAILABILITY_IN_STOCK
    complete_variant_set = bool(
        record.get("variants_complete") or record.get("variant_rows_complete")
    )
    parent_is_out_of_stock = record.get("availability") == AVAILABILITY_OUT_OF_STOCK
    if values == {AVAILABILITY_OUT_OF_STOCK} and (
        complete_variant_set
        or parent_is_out_of_stock
    ):
        return AVAILABILITY_OUT_OF_STOCK
    if (
        values
        and values <= {AVAILABILITY_OUT_OF_STOCK, AVAILABILITY_UNKNOWN}
        and (complete_variant_set or parent_is_out_of_stock)
    ):
        return AVAILABILITY_OUT_OF_STOCK
    return None


def _variant_consensus(variants: list[dict[str, Any]], field_name: str) -> object | None:
    if len(variants) < 2:
        return None
    values = [
        variant.get(field_name)
        for variant in variants
        if variant.get(field_name) not in (None, "", [], {})
    ]
    if len(values) != len(variants):
        return None
    first = text_or_none(values[0])
    if first is None or not all(text_or_none(value) == first for value in values[1:]):
        return None
    return values[0]


def _complete_variant_offers_from_parent(
    record: dict[str, Any],
    variants: list[dict[str, Any]],
) -> None:
    for index, variant in enumerate(variants):
        for field_name in DETAIL_PARENT_INHERITED_OFFER_FIELDS:
            parent_value = record.get(field_name)
            if parent_value in (None, "", [], {}) or variant.get(field_name) not in (
                None,
                "",
                [],
                {},
            ):
                continue
            variant[field_name] = parent_value
            _record_transform(
                record,
                field_name=field_name,
                before=None,
                after=parent_value,
                entity_ref=f"variant:{index}",
                rule_id=DETAIL_PARENT_OFFER_INHERITANCE_RULE_ID,
            )


def _resolve_negative_variant_stock(
    record: dict[str, Any],
    variants: list[dict[str, Any]],
) -> None:
    for index, variant in enumerate(variants):
        stock_quantity = variant.get("stock_quantity")
        try:
            stock_number = int(str(stock_quantity).strip())
        except (TypeError, ValueError):
            continue
        if stock_number >= 0:
            continue
        variant["stock_quantity"] = 0
        _record_transform(
            record,
            field_name="stock_quantity",
            before=stock_quantity,
            after=0,
            entity_ref=f"variant:{index}",
            rule_id=DETAIL_NEGATIVE_STOCK_RULE_ID,
        )
        before_availability = variant.get("availability")
        if before_availability != AVAILABILITY_OUT_OF_STOCK:
            variant["availability"] = AVAILABILITY_OUT_OF_STOCK
            _record_transform(
                record,
                field_name="availability",
                before=before_availability,
                after=AVAILABILITY_OUT_OF_STOCK,
                entity_ref=f"variant:{index}",
                rule_id=DETAIL_NEGATIVE_STOCK_RULE_ID,
            )


def _record_transform(
    record: dict[str, Any],
    *,
    field_name: str,
    before: object,
    after: object,
    entity_ref: str = "product",
    rule_id: str = DETAIL_VARIANT_CONSENSUS_RULE_ID,
) -> None:
    field_evidence = record.get("_field_evidence")
    summary = (
        field_evidence.get(field_name)
        if isinstance(field_evidence, dict)
        else None
    )
    evidence_ids = (
        list(summary.get("winning_evidence_ids") or [])
        if isinstance(summary, dict)
        else []
    )
    record.setdefault("_transforms", []).append(
        {
            "rule_id": rule_id,
            "field_name": field_name,
            "entity_ref": entity_ref,
            "before": before,
            "after": after,
            "evidence_ids": evidence_ids,
        }
    )
