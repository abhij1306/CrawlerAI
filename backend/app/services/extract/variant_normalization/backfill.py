from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

import logging

from app.services.config.extraction_rules import CURRENCY_CODES
from app.services.extract.variant_structural_pruning import (
    drop_parent_sku_alias_variant_rows,
    prune_low_signal_numeric_only_variants,
)
from app.services.shared.field_coerce import (
    clean_text,
    extract_currency_code,
    text_or_none,
)

logger = logging.getLogger(__name__)
currency_codes_upper = frozenset(
    str(code).upper() for code in tuple(CURRENCY_CODES or ()) if str(code).strip()
)

__all__ = (
    "_backfill_variant_context",
    "_backfill_parent_scalar_axes_from_variants",
    "_enforce_variant_currency_context",
)


def _backfill_variant_context(record: dict[str, Any]) -> None:
    _backfill_variant_prices_from_record(record)
    _enforce_variant_currency_context(record)
    _backfill_variant_shared_fields_from_record(record)
    prune_low_signal_numeric_only_variants(record)
    drop_parent_sku_alias_variant_rows(record)


def _backfill_parent_scalar_axes_from_variants(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    for field_name in ("color",):
        if clean_text(record.get(field_name)):
            continue
        values = [
            clean_text(variant.get(field_name))
            for variant in variant_rows
            if clean_text(variant.get(field_name))
        ]
        if len(values) != len(variant_rows):
            continue
        first_value = values[0]
        if all(value.casefold() == first_value.casefold() for value in values[1:]):
            record[field_name] = first_value


def _enforce_variant_currency_context(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    parent_currency = _currency_code(record.get("currency"))
    if not parent_currency:
        return
    variant_currencies = {
        currency
        for variant in variants
        if isinstance(variant, dict)
        if (currency := _currency_code(variant.get("currency")))
    }
    if len(variant_currencies) == 1:
        only_variant_currency = next(iter(variant_currencies))
        if only_variant_currency != parent_currency:
            record["currency"] = only_variant_currency
            parent_currency = only_variant_currency
    kept: list[dict[str, Any]] = []
    mismatched: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_currency = _currency_code(variant.get("currency"))
        if variant_currency and variant_currency != parent_currency:
            logger.warning(
                "Dropping variant with mismatched currency",
                extra={
                    "variant_id": variant.get("id") or variant.get("sku"),
                    "variant_currency": variant_currency,
                    "parent_currency": parent_currency,
                },
            )
            mismatch = dict(variant)
            mismatch["currency_mismatch"] = True
            mismatch["parent_currency"] = parent_currency
            mismatch["variant_currency"] = variant_currency
            mismatched.append(mismatch)
            continue
        variant["currency"] = parent_currency
        kept.append(variant)
    if mismatched:
        record["variants_currency_mismatch"] = mismatched
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    if mismatched:
        restored_variants = [
            {
                key: value
                for key, value in variant.items()
                if key
                not in {
                    "currency_mismatch",
                    "parent_currency",
                    "variant_currency",
                }
            }
            for variant in mismatched
        ]
        record["variants"] = restored_variants
        record["variant_count"] = len(restored_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


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
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if not distinct_price and variant.get("price") in (None, "", [], {}):
            variant["price"] = fallback_fields.get("price")
        if variant.get("currency") in (None, "", [], {}) and fallback_fields.get(
            "currency"
        ) not in (
            None,
            "",
            [],
            {},
        ):
            variant["currency"] = fallback_fields.get("currency")


def _backfill_variant_shared_fields_from_record(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    fallback_image = record.get("image_url")
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        if fallback_image not in (None, "", [], {}) and variant.get("image_url") in (
            None,
            "",
            [],
            {},
        ):
            variant["image_url"] = fallback_image
