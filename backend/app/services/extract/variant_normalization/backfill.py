from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

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

currency_codes_upper = frozenset(
    str(code).upper() for code in tuple(CURRENCY_CODES or ()) if str(code).strip()
)

__all__ = (
    "backfill_variant_context",
    "enforce_variant_currency_context",
    "_backfill_variant_context",
    "_enforce_variant_currency_context",
)


def _backfill_variant_context(record: dict[str, Any]) -> None:
    _backfill_variant_prices_from_record(record)
    _enforce_variant_currency_context(record)
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
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_currency = _currency_code(variant.get("currency"))
        if variant_currency and variant_currency != parent_currency:
            continue
        if not variant_currency:
            variant["currency"] = parent_currency
    record["variant_count"] = len(
        [variant for variant in variants if isinstance(variant, dict)]
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
    record_color = clean_text(record.get("color"))
    fallback_image_key = _image_url_normalize_key(fallback_image)
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        variant_color = clean_text(variant.get("color"))
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


def _image_url_normalize_key(url: object) -> str:
    """Strip query string and fragment so two image URLs that differ only by
    CDN resize params (``&width=...``, ``&crop=...``) compare equal."""
    text = clean_text(url)
    if not text:
        return ""
    base = text.split("?", 1)[0].split("#", 1)[0]
    return base.casefold()


backfill_variant_context = _backfill_variant_context
enforce_variant_currency_context = _enforce_variant_currency_context
