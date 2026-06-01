from __future__ import annotations

from itertools import product
from typing import Any

from app.services.config.extraction_rules import DOM_VARIANT_CARTESIAN_COMBO_LIMIT
from app.services.extract.variant_axis import public_variant_axis_fields
from app.services.extract.variant_identity_merge import (
    axis_values_are_mislabeled_duplicate,
)
from app.services.shared.field_coerce import text_or_none

__all__ = (
    "dom_variants_add_missing_existing_axis",
    "expand_existing_variants_with_dom_axes",
)

_PUBLIC_AXIS_FIELDS = tuple(public_variant_axis_fields or ())

_VARIANT_TRANSPORT_FIELDS = (
    "sku",
    "price",
    "currency",
    "url",
    "image_url",
    "availability",
    "stock_quantity",
)


def dom_variants_add_missing_existing_axis(
    existing_variants: list[dict[str, Any]],
    dom_variant_rows: list[dict[str, Any]],
) -> bool:
    existing_axes = _variant_axes_present(existing_variants)
    return bool(
        existing_axes and _real_new_dom_axes(existing_variants, dom_variant_rows)
    )


def expand_existing_variants_with_dom_axes(
    existing_variants: list[dict[str, Any]],
    dom_variant_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not existing_variants or not dom_variant_rows:
        return []
    missing_dom_axes = _real_new_dom_axes(existing_variants, dom_variant_rows)
    if not _variant_axes_present(existing_variants) or not missing_dom_axes:
        return []
    if not all(
        any(
            text_or_none(row.get(field_name))
            for field_name in _VARIANT_TRANSPORT_FIELDS
        )
        for row in existing_variants
        if isinstance(row, dict)
    ):
        return []
    if len(existing_variants) * len(dom_variant_rows) > _safe_int_config(
        DOM_VARIANT_CARTESIAN_COMBO_LIMIT,
        1000,
    ):
        return []

    expanded_rows: list[dict[str, Any]] = []
    for existing_row, dom_row in product(existing_variants, dom_variant_rows):
        merged = dict(existing_row)
        for field_name in ("sku", "variant_id", "barcode"):
            merged.pop(field_name, None)
        option_values = {
            key: value
            for source in (
                existing_row.get("option_values"),
                dom_row.get("option_values"),
            )
            if isinstance(source, dict)
            for key, value in source.items()
            if text_or_none(value)
        }
        for axis in public_variant_axis_fields:
            dom_value = text_or_none(dom_row.get(axis))
            if axis in missing_dom_axes and dom_value:
                merged[axis] = dom_value
                option_values[axis] = dom_value
        if option_values:
            merged["option_values"] = option_values
        expanded_rows.append(merged)
    return expanded_rows


def _real_new_dom_axes(
    existing_variants: list[dict[str, Any]],
    dom_variant_rows: list[dict[str, Any]],
) -> set[str]:
    existing_axes = _variant_axes_present(existing_variants)
    candidate_axes = _variant_axes_present(dom_variant_rows) - existing_axes
    if not candidate_axes:
        return set()
    existing_axis_values = _variant_axis_values(existing_variants)
    dom_axis_values = _variant_axis_values(dom_variant_rows)
    return {
        dom_axis
        for dom_axis in candidate_axes
        if not any(
            axis_values_are_mislabeled_duplicate(
                dom_axis_values.get(dom_axis, []),
                existing_values,
            )
            for existing_values in existing_axis_values.values()
        )
    }


def _variant_axes_present(rows: list[dict[str, Any]]) -> set[str]:
    axes: set[str] = set()
    for row in rows:
        option_values = row.get("option_values")
        if isinstance(option_values, dict):
            axes.update(
                str(axis)
                for axis, value in option_values.items()
                if axis in _PUBLIC_AXIS_FIELDS and text_or_none(value)
            )
        axes.update(axis for axis in _PUBLIC_AXIS_FIELDS if text_or_none(row.get(axis)))
    return axes


def _variant_axis_values(rows: list[dict[str, Any]]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    for row in rows:
        option_values = row.get("option_values")
        if isinstance(option_values, dict):
            for axis, value in option_values.items():
                if axis in _PUBLIC_AXIS_FIELDS and (text := text_or_none(value)):
                    values.setdefault(str(axis), []).append(text)
        for axis in _PUBLIC_AXIS_FIELDS:
            if text := text_or_none(row.get(axis)):
                values.setdefault(axis, []).append(text)
    return values


def _safe_int_config(value: object, default: int) -> int:
    try:
        if not isinstance(value, (int, float, str)):
            raise TypeError
        return max(1, int(value))
    except (TypeError, ValueError):
        return default
