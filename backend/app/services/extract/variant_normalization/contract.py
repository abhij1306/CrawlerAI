from __future__ import annotations

import re
from typing import Any

from app.services.config.field_mappings import PRICE_FIELD
from app.services.config.public_record_policy import (
    PUBLIC_RECORD_LEGACY_OPTION_FIELD_PATTERN,
    PUBLIC_RECORD_LEGACY_VARIANT_FIELDS,
)
from app.services.config.variant_policy import (
    FLAT_VARIANT_KEYS,
    PUBLIC_VARIANT_AXIS_FIELDS,
    VARIANT_PARENT_SHARED_FIELDS,
    VARIANT_TRANSPORT_FIELDS,
)
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_normalization import deduplication
from app.services.normalizers import normalize_decimal_price
from app.services.shared.field_coerce import (
    coerce_field_value,
    decimal_for_shared_price,
    text_or_none,
)

__all__ = (
    "flatten_variants_for_public_output",
    "enforce_flat_variant_public_contract",
    "finalize",
    "enforce_payload_limits",
)

_PUBLIC_VARIANT_AXIS_KEYS = frozenset(
    str(token).strip().lower()
    for token in tuple(PUBLIC_VARIANT_AXIS_FIELDS or ())
    if str(token).strip()
)
option_field_pattern = re.compile(PUBLIC_RECORD_LEGACY_OPTION_FIELD_PATTERN)


def _coerce_variant_axis_value(
    axis_key: str,
    value: object,
    *,
    page_url: str,
) -> str | None:
    if value in (None, "", [], {}):
        return None
    coerced = coerce_field_value(axis_key, value, page_url)
    text = text_or_none(coerced)
    if text:
        return text
    return None


def _variant_row_looks_like_shopify_raw(raw_variant: dict[str, Any]) -> bool:
    if any(
        raw_variant.get(field_name) not in (None, "", [], {})
        for field_name in ("option1", "compare_at_price", "inventory_quantity")
    ):
        return True
    variant_url = text_or_none(raw_variant.get("url")) or ""
    return "?variant=" in variant_url and any(
        raw_variant.get(f"option{index}") not in (None, "", [], {})
        for index in range(1, 4)
    )


def _coerce_variant_transport_value(
    field_name: str,
    value: object,
    *,
    raw_variant: dict[str, Any],
    page_url: str,
) -> object | None:
    if field_name in {PRICE_FIELD, "original_price"} and _variant_row_looks_like_shopify_raw(
        raw_variant
    ):
        normalized = normalize_decimal_price(value, interpret_integral_as_cents=True)
        if normalized not in (None, ""):
            return normalized
    return coerce_field_value(field_name, value, page_url)


def flatten_variants_for_public_output(
    value: object,
    *,
    page_url: str = "",
) -> list[dict[str, object]] | None:
    """Flatten variants to the Zyte-shaped public schema."""

    if not isinstance(value, list):
        return None
    flattened: list[dict[str, object]] = []
    for raw_variant in value:
        if not isinstance(raw_variant, dict):
            continue
        merged: dict[str, object] = {}
        has_option_axis = False
        option_values = raw_variant.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, axis_value in option_values.items():
                axis_text = text_or_none(axis_name)
                if not axis_text:
                    continue
                axis_key = normalized_variant_axis_key(axis_text)
                if axis_key not in _PUBLIC_VARIANT_AXIS_KEYS:
                    continue
                value_text = _coerce_variant_axis_value(
                    axis_key,
                    axis_value,
                    page_url=page_url,
                )
                if not value_text:
                    continue
                if axis_key not in merged:
                    merged[axis_key] = value_text
                has_option_axis = True
        for key in FLAT_VARIANT_KEYS:
            if key in merged and merged[key] not in (None, "", [], {}):
                continue
            candidate = raw_variant.get(key)
            if candidate in (None, "", [], {}):
                continue
            coerced = _coerce_variant_transport_value(
                key,
                candidate,
                raw_variant=raw_variant,
                page_url=page_url,
            )
            if coerced in (None, "", [], {}):
                continue
            merged[key] = coerced
        for raw_key, candidate in raw_variant.items():
            axis_key = normalized_variant_axis_key(raw_key)
            if axis_key not in _PUBLIC_VARIANT_AXIS_KEYS or axis_key in merged:
                continue
            value_text = _coerce_variant_axis_value(
                axis_key,
                candidate,
                page_url=page_url,
            )
            if not value_text:
                continue
            merged[axis_key] = value_text
            has_option_axis = True
        if text_or_none(merged.get("scent")) and "body-mist" in str(page_url or "").casefold():
            merged.pop("color", None)
        if merged and (
            has_option_axis
            or any(
                text_or_none(merged.get(field_name))
                for field_name in _PUBLIC_VARIANT_AXIS_KEYS
            )
        ):
            flattened.append(merged)
    return flattened or None


def _drop_parent_shared_variant_fields(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    for field_name in VARIANT_PARENT_SHARED_FIELDS:
        if field_name == "currency" and any(
            variant.get(PRICE_FIELD) not in (None, "", [], {})
            for variant in variant_rows
        ):
            continue
        parent_value = text_or_none(record.get(field_name))
        if parent_value is None:
            continue
        if not all(
            _variant_shared_value_matches_parent(
                field_name,
                variant.get(field_name),
                parent_value,
            )
            for variant in variant_rows
        ):
            continue
        for variant in variant_rows:
            if _variant_shared_value_matches_parent(
                field_name,
                variant.get(field_name),
                parent_value,
            ):
                variant.pop(field_name, None)
    _drop_unanimous_variant_transport_fields(variant_rows)


def _drop_unanimous_variant_transport_fields(
    variant_rows: list[dict[str, Any]],
) -> None:
    if len(variant_rows) < 2:
        return
    if not any(
        text_or_none(variant.get(axis_name))
        for variant in variant_rows
        for axis_name in _PUBLIC_VARIANT_AXIS_KEYS
    ):
        return
    for field_name in VARIANT_TRANSPORT_FIELDS:
        if field_name == "currency" and any(
            variant.get(PRICE_FIELD) not in (None, "", [], {})
            for variant in variant_rows
        ):
            continue
        values = [variant.get(field_name) for variant in variant_rows]
        if any(value in (None, "", [], {}) for value in values):
            continue
        first_value = values[0]
        if not all(
            _variant_shared_value_matches_parent(field_name, value, first_value)
            for value in values[1:]
        ):
            continue
        for variant in variant_rows:
            variant.pop(field_name, None)


def _variant_shared_value_matches_parent(
    field_name: str,
    variant_value: object,
    parent_value: object,
) -> bool:
    variant_text = text_or_none(variant_value)
    parent_text = text_or_none(parent_value)
    if variant_text is None or parent_text is None:
        return False
    if field_name == PRICE_FIELD:
        variant_price = decimal_for_shared_price(variant_text)
        parent_price = decimal_for_shared_price(parent_text)
        return (
            variant_price is not None
            and parent_price is not None
            and variant_price == parent_price
        )
    return variant_text == parent_text


def enforce_flat_variant_public_contract(
    record: dict[str, Any],
    *,
    page_url: str = "",
) -> None:
    variants = flatten_variants_for_public_output(
        record.get("variants"), page_url=page_url
    )
    if variants:
        record["variants"] = variants
        record["variant_count"] = len(variants)
        _drop_parent_shared_variant_fields(record)
    else:
        record.pop("variants", None)
        record.pop("variant_count", None)
    for field_name in tuple(PUBLIC_RECORD_LEGACY_VARIANT_FIELDS or ()):
        record.pop(str(field_name), None)


def finalize(record: dict[str, Any], *, max_rows: int) -> None:
    enforce_payload_limits(record, max_rows=max_rows)
    _enforce_flat_variant_contract(record)


def enforce_payload_limits(record: dict[str, Any], *, max_rows: int) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    try:
        max_rows = int(max_rows) if max_rows is not None else 0
    except (TypeError, ValueError):
        max_rows = 0
    if max_rows <= 0:
        return
    if len(variants) <= max_rows:
        return
    candidates = list(variants[:max_rows])
    kept = [
        variant
        for variant in candidates
        if isinstance(variant, dict)
        and (
            deduplication._variant_primary_key(variant)
            or _variant_has_axis_value(variant)
        )
    ]
    truncated = kept if kept else candidates
    if truncated:
        record["variants"] = truncated
        record["variant_count"] = len(truncated)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _enforce_flat_variant_contract(record: dict[str, Any]) -> None:
    enforce_flat_variant_public_contract(record)
    for field_name in tuple(record):
        if option_field_pattern.fullmatch(str(field_name)):
            record.pop(field_name, None)


def _variant_has_axis_value(variant: dict[str, Any]) -> bool:
    return any(text_or_none(variant.get(axis)) for axis in _PUBLIC_VARIANT_AXIS_KEYS)
