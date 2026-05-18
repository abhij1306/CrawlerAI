from __future__ import annotations

import logging
import re
from typing import Any

from app.services.config.extraction_rules import (
    SCALAR_FIELD_MAX_OPTION_TOKENS,
    SCALAR_FIELD_POLLUTION_VALUES,
    SHADE_CODE_COLOR_MIN_TOKENS,
    VARIANT_SEPARATE_DIMENSION_SIZE_RULES,
    VARIANT_TITLE_STOPWORDS,
)
from app.services.config.variant_policy import FLAT_VARIANT_KEYS, PUBLIC_VARIANT_AXIS_FIELDS
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_choice_traversal import (
    infer_variant_group_name_from_values,
)
from app.services.extract.variant_structural_pruning import (
    drop_cross_product_variant_rows,
    drop_parent_shared_variant_axes,
)
from app.services.extract.variant_normalization.contract import (
    flatten_variants_for_public_output,
)
from app.services.extract.variant_value_guards import drop_invalid_variant_urls
from app.services.shared.field_coerce import clean_text
from app.services.extract.variant_normalization import backfill
from app.services.extract.variant_normalization import deduplication
from app.services.extract.variant_normalization import size_color_extraction

__all__ = (
    "_sanitize_variant_axes",
    "_drop_polluted_parent_scalar_axes",
)

logger = logging.getLogger(__name__)
_REMAP_ELIGIBLE_AXES = frozenset({"state", "type", "style", "configuration"})
_CORE_AXES = frozenset({"size", "color"})
try:
    scalar_field_max_option_tokens = max(1, int(SCALAR_FIELD_MAX_OPTION_TOKENS))
except (TypeError, ValueError):
    scalar_field_max_option_tokens = 6
try:
    shade_code_color_min_tokens = max(2, int(SHADE_CODE_COLOR_MIN_TOKENS))
except (TypeError, ValueError):
    shade_code_color_min_tokens = 2
public_variant_axis_fields = tuple(
    str(field_name).strip().lower()
    for field_name in tuple(PUBLIC_VARIANT_AXIS_FIELDS or ())
    if str(field_name).strip()
)
_VARIANT_REQUIRED_FIELDS = (*FLAT_VARIANT_KEYS, *public_variant_axis_fields)
scalar_field_pollution_values = frozenset(
    clean_text(value).casefold()
    for value in tuple(SCALAR_FIELD_POLLUTION_VALUES or ())
    if clean_text(value)
)
variant_separate_dimension_size_rules = []
for rule in tuple(VARIANT_SEPARATE_DIMENSION_SIZE_RULES or ()):
    if not isinstance(rule, dict):
        continue
    pattern = str(rule.get("pattern") or "").strip()
    style = clean_text(rule.get("style"))
    if not pattern or not style:
        continue
    try:
        variant_separate_dimension_size_rules.append((re.compile(pattern, re.I), style))
    except re.error:
        logger.warning(
            "Skipping invalid variant separate-dimension size rule",
            extra={"pattern": pattern},
        )
variant_separate_dimension_size_rules = tuple(variant_separate_dimension_size_rules)
variant_title_stopwords = frozenset(
    clean_text(token).lower()
    for token in tuple(VARIANT_TITLE_STOPWORDS or ())
    if clean_text(token)
)


def _remap_generic_variant_axes(record: dict[str, Any]) -> None:
    """Remap generic/non-semantic axes to size or color when values match."""
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    # Collect axes that appear across all variant rows (excluding core axes).
    generic_axis_values: dict[str, list[str]] = {}
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        for axis in _REMAP_ELIGIBLE_AXES:
            value = clean_text(variant.get(axis))
            if value:
                generic_axis_values.setdefault(axis, []).append(value)
    if not generic_axis_values:
        return
    for axis, values in generic_axis_values.items():
        unique_values = list(dict.fromkeys(values))
        if len(unique_values) < 2:
            continue
        # Only remap if no variant already has the target axis populated.
        inferred = infer_variant_group_name_from_values(unique_values)
        if not inferred or inferred not in _CORE_AXES:
            continue
        # Check that no variant already has the target axis set.
        if any(
            clean_text(variant.get(inferred))
            for variant in variants
            if isinstance(variant, dict)
        ):
            continue
        # Check that the parent record does not already have the target axis
        # populated — remapping would create conflicting parent/variant state.
        if clean_text(record.get(inferred)):
            continue
        # Remap: move values from generic axis to the inferred axis.
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            value = variant.pop(axis, None)
            if value not in (None, "", [], {}):
                variant[inferred] = value


def _sanitize_variant_axes(record: dict[str, Any]) -> None:
    _remap_generic_variant_axes(record)
    drop_cross_product_variant_rows(
        record,
        color_extractor=size_color_extraction._extract_color_value,
    )
    _flatten_variant_rows(record)
    _clean_variant_rows(record)
    _normalize_separate_dimension_size_rows(record)
    deduplication._prune_unrecognized_size_rows_when_real_sizes_exist(record)
    deduplication._prune_child_size_rows_from_adult_products(record)
    drop_parent_shared_variant_axes(record)
    _enforce_variant_axis_contract(record)
    backfill._enforce_variant_currency_context(record)


def _flatten_variant_rows(record: dict[str, Any]) -> None:
    variants = flatten_variants_for_public_output(record.get("variants"))
    if variants:
        record["variants"] = variants
        record["variant_count"] = len(variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_title_tokens(value: object) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold())
        if len(token) >= 3 and token not in variant_title_stopwords
    }


def _clean_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    cleaned_variants: list[dict[str, Any]] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        cleaned_variant = dict(variant)
        drop_row = False
        for field_name in public_variant_axis_fields:
            raw_axis_key = _variant_axis_source_key(cleaned_variant, field_name)
            raw_axis_value = (
                cleaned_variant.get(raw_axis_key)
                if raw_axis_key is not None
                else None
            )
            if size_color_extraction._variant_size_axis_value_is_quantity_control(
                field_name,
                raw_axis_value,
            ):
                drop_row = True
                break
            cleaned_value = size_color_extraction._normalize_variant_axis_value(
                field_name,
                raw_axis_value,
            )
            if cleaned_value:
                cleaned_variant[field_name] = cleaned_value
                if raw_axis_key is not None and raw_axis_key != field_name:
                    cleaned_variant.pop(raw_axis_key, None)
            else:
                cleaned_variant.pop(field_name, None)
                if raw_axis_key is not None and raw_axis_key != field_name:
                    cleaned_variant.pop(raw_axis_key, None)
        if drop_row:
            continue
        _promote_misfiled_color_size(cleaned_variant)
        _drop_shade_code_size_duplicate(cleaned_variant)
        drop_invalid_variant_urls(cleaned_variant)
        if _should_restore_original_variant_url(
            original_variant=variant,
            cleaned_variant=cleaned_variant,
        ):
            cleaned_variant["url"] = variant.get("url")
        if any(
            cleaned_variant.get(field_name) not in (None, "", [], {})
            for field_name in _VARIANT_REQUIRED_FIELDS
        ):
            cleaned_variants.append(cleaned_variant)
    if cleaned_variants:
        record["variants"] = cleaned_variants
        record["variant_count"] = len(cleaned_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _enforce_variant_axis_contract(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    axisful_variants = [
        variant
        for variant in variants
        if isinstance(variant, dict) and _variant_has_axis_value(variant)
    ]
    if axisful_variants:
        record["variants"] = axisful_variants
        record["variant_count"] = len(axisful_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_has_axis_value(variant: dict[str, Any]) -> bool:
    return any(clean_text(variant.get(axis)) for axis in public_variant_axis_fields)


def _variant_axis_source_key(
    variant: dict[str, Any],
    field_name: str,
) -> str | None:
    if field_name in variant:
        return field_name
    for key in variant:
        if normalized_variant_axis_key(key) == field_name:
            return str(key)
    return None


def _should_restore_original_variant_url(
    *,
    original_variant: dict[str, Any],
    cleaned_variant: dict[str, Any],
) -> bool:
    original_url = clean_text(original_variant.get("url"))
    if not original_url or clean_text(cleaned_variant.get("url")):
        return False
    remaining_transport_fields = [
        field_name
        for field_name in FLAT_VARIANT_KEYS
        if (
            field_name != "url"
            and field_name not in public_variant_axis_fields
            and cleaned_variant.get(field_name) not in (None, "", [], {})
        )
    ]
    return not remaining_transport_fields


def _drop_polluted_parent_scalar_axes(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not any(
        isinstance(variant, dict) for variant in variants
    ):
        return
    max_tokens = scalar_field_max_option_tokens
    for field_name in ("color", "size"):
        value = clean_text(record.get(field_name))
        if not value:
            continue
        lowered = value.casefold()
        tokens = [token for token in re.split(r"[\s,|/]+", lowered) if token]
        numeric_tokens = sum(1 for token in tokens if re.search(r"\d", token))
        if lowered in scalar_field_pollution_values or (
            field_name == "size"
            and len(tokens) > max_tokens + 2
            and numeric_tokens >= 2
        ):
            record.pop(field_name, None)


def _promote_misfiled_color_size(variant: dict[str, Any]) -> None:
    if clean_text(variant.get("color")):
        return
    size_value = clean_text(variant.get("size"))
    if not size_value:
        return
    if size_color_extraction._extract_size_value(size_value):
        return
    color_value = size_color_extraction._extract_color_value(size_value)
    if not color_value:
        return
    variant["color"] = color_value
    variant.pop("size", None)


def _drop_shade_code_size_duplicate(variant: dict[str, Any]) -> None:
    size_value = clean_text(variant.get("size"))
    color_value = clean_text(variant.get("color"))
    if not size_value or not color_value:
        return
    option_values = variant.get("option_values")
    if isinstance(option_values, dict) and clean_text(option_values.get("size")):
        return
    if not size_value.isdigit():
        return
    color_tokens = color_value.split()
    if len(color_tokens) < shade_code_color_min_tokens:
        return
    if color_tokens[0].casefold() != size_value:
        return
    variant.pop("size", None)


def _normalize_separate_dimension_size_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    rows = [variant for variant in variants if isinstance(variant, dict)]
    if not rows or any(clean_text(row.get("color")) for row in rows):
        return
    size_values = [
        clean_text(row.get("size")) for row in rows if clean_text(row.get("size"))
    ]
    if len(size_values) < 2:
        return
    separate_family_hits = [
        sum(1 for value in size_values if pattern.fullmatch(value))
        for pattern, _label in variant_separate_dimension_size_rules
    ]
    if sum(1 for count in separate_family_hits if count >= 2) < 2:
        return
    relabeled_rows: list[dict[str, Any]] = []
    for row in rows:
        relabeled = dict(row)
        size_value = clean_text(relabeled.get("size"))
        style_label = _separate_dimension_style_label(size_value)
        if style_label and size_value:
            option_values = relabeled.get("option_values")
            relabeled["option_values"] = (
                dict(option_values) if isinstance(option_values, dict) else {}
            )
            relabeled["option_values"]["style"] = style_label
            relabeled["option_values"]["size"] = size_value
        relabeled_rows.append(relabeled)
    record["variants"] = relabeled_rows
    record["variant_count"] = len(relabeled_rows)


def _separate_dimension_style_label(size_value: str) -> str:
    for pattern, label in variant_separate_dimension_size_rules:
        if pattern.fullmatch(size_value):
            return label
    return ""
