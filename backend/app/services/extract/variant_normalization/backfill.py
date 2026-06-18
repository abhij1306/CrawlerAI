from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.services.config.extraction_rules import CURRENCY_CODES
from app.services.extract.variant_identity_merge import variant_url_matches_parent_product
from app.services.extract.variant_structural_pruning import (
    drop_parent_sku_alias_variant_rows,
    prune_low_signal_numeric_only_variants,
)
from app.services.shared.field_coerce import (
    clean_text,
    extract_currency_code,
    text_or_none,
)

currency_codes_upper = frozenset(
    str(code).upper() for code in tuple(CURRENCY_CODES or ()) if str(code).strip()
)

__all__ = (
    "backfill_variant_context",
    "backfill_variant_color_from_record",
    "enforce_variant_currency_context",
    "remove_unproven_flat_variant_offers",
    "_backfill_variant_context",
    "_enforce_variant_currency_context",
)


def _backfill_variant_context(record: dict[str, Any]) -> None:
    _backfill_variant_prices_from_record(record)
    _enforce_variant_currency_context(record)
    _remove_unproven_flat_variant_offers(record)
    _backfill_variant_shared_fields_from_record(record)
    prune_low_signal_numeric_only_variants(record)
    drop_parent_sku_alias_variant_rows(record)


def _enforce_variant_currency_context(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    parent_currency = _currency_code(record.get("currency"))
    if not parent_currency:
        return
    parent_url = clean_text(record.get("url") or record.get("source_url"))
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_currency = _currency_code(variant.get("currency"))
        if variant_currency and variant_currency != parent_currency:
            if _variant_price_matches_parent(variant, record) and not _variant_has_distinct_product_url(
                variant,
                parent_url=parent_url,
            ):
                variant["currency"] = parent_currency
                _append_variant_currency_conflict_finding(
                    record,
                    variant_currency=variant_currency,
                    parent_currency=parent_currency,
                )
            continue
        if (
            not variant_currency
            and not _variant_can_inherit_parent_offer(
                variant,
                parent_url=parent_url,
            )
            and variant.get("price") in (None, "", [], {})
        ):
            continue
        if not variant_currency:
            variant["currency"] = parent_currency
    record["variant_count"] = len(
        [variant for variant in variants if isinstance(variant, dict)]
    )


def _variant_price_matches_parent(
    variant: dict[str, Any],
    record: dict[str, Any],
) -> bool:
    variant_price = text_or_none(variant.get("price"))
    parent_price = text_or_none(record.get("price"))
    return bool(variant_price and parent_price and variant_price == parent_price)


def _append_variant_currency_conflict_finding(
    record: dict[str, Any],
    *,
    variant_currency: str,
    parent_currency: str,
) -> None:
    findings = record.setdefault("_validation_findings", [])
    if not isinstance(findings, list):
        return
    if any(
        isinstance(finding, dict)
        and finding.get("rule_id") == "VARIANT_CURRENCY_PARENT_CONFLICT"
        for finding in findings
    ):
        return
    findings.append(
        {
            "finding_id": "variant_currency:parent_conflict",
            "rule_id": "VARIANT_CURRENCY_PARENT_CONFLICT",
            "severity": "medium",
            "field_name": "variants.currency",
            "entity_ref": "variants",
            "message": "Variant currency conflicted with same-price parent currency.",
            "suggested_action": "verify_variant_offer_currency",
            "metadata": {
                "variant_currency": variant_currency,
                "parent_currency": parent_currency,
            },
        }
    )


def _currency_code(value: object) -> str:
    extracted = extract_currency_code(value)
    if extracted:
        return extracted
    text = text_or_none(value)
    if text:
        upper = text.upper()
        if upper in currency_codes_upper:
            return upper
    return ""


def _backfill_variant_prices_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_fields = {
        field_name: record.get(field_name)
        for field_name in ("price", "currency")
        if record.get(field_name) not in (None, "", [], {})
    }
    if not fallback_fields:
        return

    def _value_present(value: object) -> bool:
        return value not in (None, "", [], {})

    def _comparable_scalar(value: object) -> object:
        if isinstance(value, bool):
            return text_or_none(value)
        if isinstance(value, (int, float)):
            try:
                parsed = Decimal(str(value))
            except InvalidOperation:
                return text_or_none(value)
            return parsed if parsed.is_finite() else text_or_none(value)
        text = text_or_none(value)
        if text is None:
            return None
        try:
            parsed = Decimal(text)
        except InvalidOperation:
            return text
        return parsed if parsed.is_finite() else text

    def _has_distinct_variant_value(field_name: str) -> bool:
        """Distinct means a non-empty variant value differs from the parent fallback."""
        fallback_value = _comparable_scalar(fallback_fields.get(field_name))
        if fallback_value is None:
            return False
        return any(
            isinstance(variant, dict)
            and _value_present(variant.get(field_name))
            and _comparable_scalar(variant.get(field_name)) != fallback_value
            for variant in variants
        )

    distinct_price = _has_distinct_variant_value("price")
    parent_url = clean_text(record.get("url") or record.get("source_url"))
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        has_variant_price = variant.get("price") not in (None, "", [], {})
        can_inherit_parent_offer = _variant_can_inherit_parent_offer(
            variant,
            parent_url=parent_url,
        )
        if (
            not distinct_price
            and can_inherit_parent_offer
            and variant.get("price") in (None, "", [], {})
        ):
            variant["price"] = fallback_fields.get("price")
        if variant.get("currency") in (None, "", [], {}) and fallback_fields.get(
            "currency"
        ) not in (
            None,
            "",
            [],
            {},
        ) and (can_inherit_parent_offer or has_variant_price):
            variant["currency"] = fallback_fields.get("currency")


def _backfill_variant_shared_fields_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_image = record.get("image_url")
    record_color = clean_text(record.get("color"))
    fallback_image_key = _image_url_normalize_key(fallback_image)
    can_inherit_record_color = _variants_can_inherit_record_color(
        variants,
        record_color=record_color,
        has_parent_image=bool(text_or_none(fallback_image)),
    ) and not bool(record.get("_disable_variant_parent_color_inheritance"))
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_color = clean_text(variant.get("color"))
        if record_color and not variant_color and can_inherit_record_color:
            variant["color"] = record_color
            variant_color = record_color
        # Drop pre-existing variant images that match the parent image but
        # represent a different colorway. Source upstreams (Shopify swatch
        # blocks, network listings) sometimes paint the current PDP image
        # onto every sibling colorway, leaving misleading data.
        existing_variant_image = variant.get("image_url")
        if (
            existing_variant_image
            and fallback_image_key
            and _image_url_normalize_key(existing_variant_image) == fallback_image_key
            and record_color
            and variant_color
            and variant_color.casefold() != record_color.casefold()
        ):
            variant.pop("image_url", None)
            existing_variant_image = None
        if fallback_image not in (None, "", [], {}) and existing_variant_image in (
            None,
            "",
            [],
            {},
        ):
            # Do not paint the parent image onto a variant that represents a
            # different colorway. Otherwise consumers see (e.g.) the Yellow
            # PDP image attached to Black/Brown variants on FashionNova.
            if (
                record_color
                and variant_color
                and variant_color.casefold() != record_color.casefold()
            ):
                continue
            variant["image_url"] = fallback_image


def backfill_variant_color_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    record_color = clean_text(record.get("color"))
    can_inherit_record_color = _variants_can_inherit_record_color(
        variants,
        record_color=record_color,
        has_parent_image=bool(text_or_none(record.get("image_url"))),
    ) and not bool(record.get("_disable_variant_parent_color_inheritance"))
    if not can_inherit_record_color:
        return
    for variant in variants:
        if isinstance(variant, dict) and not clean_text(variant.get("color")):
            variant["color"] = record_color


def _variants_can_inherit_record_color(
    variants: list[object],
    *,
    record_color: str,
    has_parent_image: bool = False,
) -> bool:
    if not record_color:
        return False
    rows = [variant for variant in variants if isinstance(variant, dict)]
    if not rows:
        return False
    colors = {
        clean_text(row.get("color")).casefold()
        for row in rows
        if clean_text(row.get("color"))
    }
    if colors and colors != {record_color.casefold()}:
        return False
    return all(
        not clean_text(row.get("color"))
        and (
            any(
                text_or_none(row.get(field_name))
                for field_name in (
                    "sku",
                    "variant_id",
                    "barcode",
                    "url",
                    "image_url",
                )
            )
            or (has_parent_image and text_or_none(row.get("size")))
        )
        for row in rows
    )


def _image_url_normalize_key(url: object) -> str:
    """Strip query string and fragment so two image URLs that differ only by
    CDN resize params (``&width=...``, ``&crop=...``) compare equal."""
    text = clean_text(url)
    if not text:
        return ""
    base = text.split("?", 1)[0].split("#", 1)[0]
    return base.casefold()


def _variant_has_offer_identity(variant: dict[str, Any]) -> bool:
    return any(
        text_or_none(variant.get(field_name))
        for field_name in ("sku", "variant_id", "url", "image_url", "barcode")
    )


def _variant_can_inherit_parent_offer(
    variant: dict[str, Any],
    *,
    parent_url: str,
) -> bool:
    return _variant_has_offer_identity(variant) and not _variant_has_distinct_product_url(
        variant,
        parent_url=parent_url,
    )


def _variant_has_distinct_product_url(
    variant: dict[str, Any],
    *,
    parent_url: str,
) -> bool:
    variant_url = text_or_none(variant.get("url"))
    if not variant_url or not parent_url:
        return False
    return not variant_url_matches_parent_product(variant_url, parent_url=parent_url)


def _remove_unproven_flat_variant_offers(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 4:
        return
    parent_price = text_or_none(record.get("price"))
    if not parent_price:
        return
    rows = [variant for variant in variants if isinstance(variant, dict)]
    prices = {
        text_or_none(variant.get("price"))
        for variant in rows
        if text_or_none(variant.get("price"))
    }
    if prices != {parent_price}:
        return
    has_offer_identity = any(
        text_or_none(variant.get(field_name))
        for variant in rows
        for field_name in ("sku", "variant_id", "barcode")
    )
    if has_offer_identity and not _flat_offer_rows_look_like_unproven_matrix(rows):
        return
    for variant in rows:
        variant.pop("price", None)
        if text_or_none(variant.get("currency")) == text_or_none(record.get("currency")):
            variant.pop("currency", None)
    findings = record.setdefault("_validation_findings", [])
    if isinstance(findings, list):
        findings.append(
            {
                "finding_id": "variant_offer:flat_parent_unproven",
                "rule_id": "FLAT_PARENT_VARIANT_OFFER_REMOVED",
                "severity": "high",
                "field_name": "variants",
                "entity_ref": "variants",
                "message": "Repeated parent offer removed from variants without per-variant offer identity.",
                "suggested_action": "collect_per_variant_offer_evidence",
                "metadata": {"variant_count": len(rows)},
            }
        )


def _flat_offer_rows_look_like_unproven_matrix(rows: list[dict[str, Any]]) -> bool:
    if len(rows) < 12:
        return False
    axis_value_counts = []
    for axis_name in ("color", "size", "width", "condition", "storage"):
        values = {
            clean_text(row.get(axis_name)).casefold()
            for row in rows
            if clean_text(row.get(axis_name))
        }
        if values:
            axis_value_counts.append(len(values))
    return sum(1 for count in axis_value_counts if count > 1) >= 2


backfill_variant_context = _backfill_variant_context
enforce_variant_currency_context = _enforce_variant_currency_context
remove_unproven_flat_variant_offers = _remove_unproven_flat_variant_offers
