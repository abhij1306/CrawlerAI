from __future__ import annotations

from typing import Any

import re

from app.services.config.extraction_rules import VARIANT_SEPARATE_DIMENSION_SIZE_RULES
from app.services.extract.variant_identity_merge import (
    collapse_duplicate_size_aliases,
    merge_variant_rows,
)
from app.services.extract.variant_structural_pruning import (
    drop_color_only_rows_when_size_rows_exist,
    drop_subset_variants_when_richer_alternative_exists,
    prune_axisless_rows_when_axisful_rows_exist,
)
from app.services.shared.field_coerce import clean_text
from app.services.extract.variant_normalization import size_color_extraction

__all__ = (
    "dedupe_and_prune_variant_rows",
    "prune_child_size_rows_from_adult_products",
    "prune_unrecognized_size_rows_when_real_sizes_exist",
    "_dedupe_and_prune_variant_rows",
    "_prune_unrecognized_size_rows_when_real_sizes_exist",
    "_prune_child_size_rows_from_adult_products",
)

variant_separate_dimension_size_rules = tuple(
    (re.compile(str(rule.get("pattern")), re.I), clean_text(rule.get("style")))
    for rule in tuple(VARIANT_SEPARATE_DIMENSION_SIZE_RULES or ())
    if isinstance(rule, dict)
    and str(rule.get("pattern") or "").strip()
    and clean_text(rule.get("style"))
)


def _dedupe_and_prune_variant_rows(record: dict[str, Any]) -> None:
    collapse_duplicate_size_aliases(record)
    _dedupe_variant_rows(record)
    drop_color_only_rows_when_size_rows_exist(record)
    drop_subset_variants_when_richer_alternative_exists(record)
    prune_axisless_rows_when_axisful_rows_exist(record)


def _prune_unrecognized_size_rows_when_real_sizes_exist(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    recognized_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and (
            size_color_extraction._size_value_is_recognized(variant.get("size"))
            or _variant_row_has_labeled_size_dimension(variant)
        )
    ]
    if len(recognized_rows) < 2:
        return
    kept = [
        variant
        for variant in variants
        if not isinstance(variant, dict)
        or not clean_text(variant.get("size"))
        or size_color_extraction._size_value_is_recognized(variant.get("size"))
        or _variant_row_has_labeled_size_dimension(variant)
        or clean_text(variant.get("color"))
    ]
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_row_has_labeled_size_dimension(variant: dict[str, Any]) -> bool:
    size_value = clean_text(variant.get("size"))
    if not size_value:
        return False
    option_values = variant.get("option_values")
    if not isinstance(option_values, dict):
        return False
    style_value = clean_text(option_values.get("style"))
    return bool(
        style_value
        and any(
            label.casefold() == style_value.casefold()
            and pattern.fullmatch(size_value)
            for pattern, label in variant_separate_dimension_size_rules
        )
    )


def _prune_child_size_rows_from_adult_products(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    if not size_color_extraction._record_targets_adult_sizes(record):
        return
    adult_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and size_color_extraction._size_value_is_recognized(variant.get("size"))
        and not size_color_extraction._size_value_is_child_specific(variant.get("size"))
    ]
    child_rows = [
        variant
        for variant in variants
        if isinstance(variant, dict)
        and size_color_extraction._size_value_is_child_specific(variant.get("size"))
    ]
    if len(adult_rows) < 2 or not child_rows:
        return
    kept = [
        variant
        for variant in variants
        if not isinstance(variant, dict)
        or not size_color_extraction._size_value_is_child_specific(variant.get("size"))
    ]
    if kept:
        record["variants"] = kept
        record["variant_count"] = len(kept)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _dedupe_variant_rows(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or not variants:
        return
    merged_variants = merge_variant_rows(variants)
    if merged_variants:
        record["variants"] = merged_variants
        record["variant_count"] = len(merged_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


dedupe_and_prune_variant_rows = _dedupe_and_prune_variant_rows
prune_child_size_rows_from_adult_products = _prune_child_size_rows_from_adult_products
prune_unrecognized_size_rows_when_real_sizes_exist = (
    _prune_unrecognized_size_rows_when_real_sizes_exist
)
