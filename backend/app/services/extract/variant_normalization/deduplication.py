from __future__ import annotations

from typing import Any

import re

from app.services.config.extraction_rules import VARIANT_SEPARATE_DIMENSION_SIZE_RULES
from app.services.config.variant_policy import FLAT_VARIANT_KEYS
from app.services.extract.variant_identity_merge import (
    collapse_duplicate_size_aliases,
    merge_variant_pair,
    variant_identity,
    variant_row_richness,
    variant_semantic_identity,
)
from app.services.extract.variant_structural_pruning import (
    drop_color_only_rows_when_size_rows_exist,
    drop_subset_variants_when_richer_alternative_exists,
    prune_axisless_rows_when_axisful_rows_exist,
)
from app.services.shared.field_coerce import clean_text
from app.services.extract.variant_normalization import size_color_extraction

__all__ = (
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
    merged_by_key: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    for variant in variants:
        if not isinstance(variant, dict):
            continue
        key = _variant_primary_key(variant)
        if key is None:
            continue
        current = merged_by_key.get(key)
        if current is None:
            merged_by_key[key] = dict(variant)
            ordered_keys.append(key)
            continue
        primary, secondary = _richer_variant_pair(current, variant)
        merged_by_key[key] = merge_variant_pair(primary, secondary)
    deduped_variants = [merged_by_key[key] for key in ordered_keys]
    semantic_merged: dict[str, dict[str, Any]] = {}
    semantic_order: list[str] = []
    passthrough: list[dict[str, Any]] = []
    for variant in deduped_variants:
        semantic_key = variant_semantic_identity(variant)
        if not semantic_key:
            passthrough.append(variant)
            continue
        current = semantic_merged.get(semantic_key)
        if current is None:
            semantic_merged[semantic_key] = dict(variant)
            semantic_order.append(semantic_key)
            continue
        primary, secondary = _richer_variant_pair(current, variant)
        semantic_merged[semantic_key] = merge_variant_pair(primary, secondary)
    merged_variants = [semantic_merged[key] for key in semantic_order]
    merged_variants.extend(passthrough)
    if merged_variants:
        record["variants"] = merged_variants
        record["variant_count"] = len(merged_variants)
        return
    record.pop("variants", None)
    record.pop("variant_count", None)


def _variant_primary_key(variant: dict[str, Any]) -> str | None:
    identity = variant_identity(variant)
    if identity:
        return identity
    semantic = variant_semantic_identity(variant)
    if semantic:
        return semantic
    fingerprint = tuple(
        (field_name, _variant_field_fingerprint(variant.get(field_name)))
        for field_name in FLAT_VARIANT_KEYS
        if _variant_field_fingerprint(variant.get(field_name)) is not None
    )
    if fingerprint:
        return f"flat:{repr(fingerprint)}"
    return None


def _variant_field_fingerprint(value: object) -> str | int | float | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (int, float)):
        return value
    cleaned = clean_text(value)
    return cleaned or None


def _richer_variant_pair(
    left: dict[str, Any],
    right: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    if variant_row_richness(right) > variant_row_richness(left):
        return right, left
    return left, right
