from __future__ import annotations

__all__ = (
    "split_variant_axes",
    "resolve_variants",
    "variant_identity",
    "variant_semantic_identity",
    "collapse_duplicate_size_aliases",
    "variant_row_richness",
    "merge_variant_pair",
    "merge_variant_rows",
    "axis_values_are_mislabeled_duplicate",
)

import itertools
import logging
from typing import Any

from app.services.config.extraction_rules import (
    VARIANT_MISLABELED_AXIS_MIN_OVERLAP_RATIO,
    VARIANT_SIZE_ALIAS_SUFFIXES,
)
from app.services.extract.variant_axis import (
    normalized_variant_axis_key,
    variant_axis_allowed_single_tokens,
)
from app.services.shared.field_coerce import clean_text, text_or_none

logger = logging.getLogger(__name__)
_variant_axis_allowed_single_tokens = variant_axis_allowed_single_tokens
_variant_size_alias_suffixes = tuple(
    str(token).strip().lower()
    for token in tuple(VARIANT_SIZE_ALIAS_SUFFIXES or ())
    if str(token).strip()
)
try:
    _variant_mislabeled_axis_min_overlap_ratio = float(
        VARIANT_MISLABELED_AXIS_MIN_OVERLAP_RATIO
    )
except (TypeError, ValueError):
    _variant_mislabeled_axis_min_overlap_ratio = 0.5


def _normalized_axis_value_set(values: object) -> set[str]:
    if isinstance(values, (list, tuple, set, frozenset)):
        raw_values = list(values)
    elif values in (None, "", [], {}):
        raw_values = []
    else:
        raw_values = [values]
    normalized: set[str] = set()
    for value in raw_values:
        cleaned = clean_text(value).casefold()
        if cleaned:
            normalized.add(cleaned)
    return normalized


def axis_values_are_mislabeled_duplicate(
    values_a: object,
    values_b: object,
    *,
    min_overlap_ratio: float | None = None,
) -> bool:
    """Return True when two axis value sets are really one axis mislabeled.

    Generic guard: a real second axis multiplies the variant matrix, but when a
    second axis (often from a different source) carries (almost) the same value
    set as an existing axis, the two "axes" are the same single axis under two
    names. Treating them as independent fabricates a Cartesian explosion.
    """
    set_a = _normalized_axis_value_set(values_a)
    set_b = _normalized_axis_value_set(values_b)
    if not set_a or not set_b:
        return False
    ratio = (
        _variant_mislabeled_axis_min_overlap_ratio
        if min_overlap_ratio is None
        else min_overlap_ratio
    )
    overlap = len(set_a & set_b)
    if not overlap:
        return False
    # Jaccard similarity (overlap / union): two axes are the same axis mislabeled
    # only when their value sets are (near-)identical. Using the union as the
    # denominator avoids false positives between genuinely distinct numeric axes
    # that merely share a value (e.g. waist {28,30} vs inseam {30,32} -> 1/3),
    # while identical sets still score 1.0 and collapse.
    union = len(set_a | set_b)
    return overlap / union >= ratio

def split_variant_axes(
    axes: dict[str, list[str]],
    *,
    always_selectable_axes: frozenset[str] | None = None,
) -> tuple[dict[str, list[str]], dict[str, str]]:
    selectable: dict[str, list[str]] = {}
    single_value_attributes: dict[str, str] = {}
    forced = set(always_selectable_axes or ())
    for axis_name, values in dict(axes or {}).items():
        raw_values = (
            list(values)
            if isinstance(values, (list, tuple, set))
            else ([values] if values not in (None, "", [], {}) else [])
        )
        cleaned_values = [
            str(value).strip() for value in raw_values if str(value).strip()
        ]
        if not cleaned_values:
            continue
        unique_values: list[str] = []
        seen: set[str] = set()
        for value in cleaned_values:
            lowered = value.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            unique_values.append(value)
        if len(unique_values) > 1 or axis_name in forced:
            selectable[str(axis_name)] = unique_values
        else:
            single_value_attributes[str(axis_name)] = unique_values[0]
    return selectable, single_value_attributes


def _collapse_mislabeled_duplicate_axes(
    options_matrix: dict[str, list[str]],
    variants: list[dict[str, Any]],
) -> dict[str, list[str]]:
    """Drop a matrix axis that is the same single axis mislabeled under two names.

    Two axes whose value sets substantially overlap are not independent
    dimensions; multiplying them fabricates phantom combinations. Keep the axis
    that the variant rows actually carry inside `option_values` (the real one)
    and drop the duplicate so the Cartesian product cannot explode.
    """
    keys = list(options_matrix.keys())
    if len(keys) < 2:
        return options_matrix
    option_value_axis_counts: dict[str, int] = {key: 0 for key in keys}
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict):
            continue
        for key in keys:
            if text_or_none(option_values.get(key)):
                option_value_axis_counts[key] += 1
    dropped: set[str] = set()
    for index, key_a in enumerate(keys):
        if key_a in dropped:
            continue
        for key_b in keys[index + 1 :]:
            if key_b in dropped:
                continue
            if not axis_values_are_mislabeled_duplicate(
                options_matrix.get(key_a, []),
                options_matrix.get(key_b, []),
            ):
                continue
            # Keep the axis the variant rows actually populate; on a tie keep the
            # axis with more distinct values, then the first-declared axis.
            if option_value_axis_counts[key_a] != option_value_axis_counts[key_b]:
                weaker = (
                    key_b
                    if option_value_axis_counts[key_a]
                    >= option_value_axis_counts[key_b]
                    else key_a
                )
            elif len(options_matrix.get(key_a, [])) >= len(
                options_matrix.get(key_b, [])
            ):
                weaker = key_b
            else:
                weaker = key_a
            dropped.add(weaker)
            if weaker == key_a:
                break
    if not dropped:
        return options_matrix
    return {key: values for key, values in options_matrix.items() if key not in dropped}


def resolve_variants(
    options_matrix: dict[str, list[str]],
    variants: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Resolve variants as a Cartesian product matrix, preserving unmatched rows."""
    if not options_matrix or not variants:
        return list(variants)

    options_matrix = _collapse_mislabeled_duplicate_axes(options_matrix, variants)
    keys = list(options_matrix.keys())
    if not keys:
        return list(variants)

    # Index variants by their option_values tuple for O(1) lookup.
    # When duplicates map to the same combo, keep the richer row.
    variant_by_combo: dict[tuple[str, ...], dict[str, Any]] = {}
    no_option_values: list[dict[str, Any]] = []
    for variant in variants:
        option_values = variant.get("option_values")
        if not isinstance(option_values, dict) or not option_values:
            no_option_values.append(variant)
            continue
        combo = tuple(str(option_values.get(k, "")) for k in keys)
        if any(not option_values.get(k) for k in keys):
            no_option_values.append(variant)
            continue
        existing = variant_by_combo.get(combo)
        if existing is None or variant_row_richness(variant) > variant_row_richness(
            existing
        ):
            variant_by_combo[combo] = variant

    # Walk the Cartesian product; only emit combos that have a real variant.
    resolved: list[dict[str, Any]] = []
    for combo in itertools.product(*(options_matrix[k] for k in keys)):
        matched = variant_by_combo.get(combo)
        if matched is not None:
            resolved.append(matched)

    # Append variants that lacked full option_values (avoid data loss).
    if no_option_values:
        seen_ids = {
            v.get("variant_id") or v.get("sku")
            for v in resolved
            if v.get("variant_id") or v.get("sku")
        }
        for v in no_option_values:
            vid = v.get("variant_id") or v.get("sku")
            if vid and vid in seen_ids:
                continue
            resolved.append(v)
            if vid:
                seen_ids.add(vid)

    return resolved or list(variants)


def variant_identity(variant: dict[str, Any]) -> str | None:
    """Canonical identity for a variant row."""
    if not isinstance(variant, dict):
        return None
    variant_id = text_or_none(variant.get("variant_id"))
    if variant_id:
        return f"id:{variant_id}"
    sku = text_or_none(variant.get("sku"))
    if sku:
        return f"sku:{sku}"
    option_values = variant.get("option_values")
    if isinstance(option_values, dict) and option_values:
        normalized_pairs = sorted(
            (str(axis_name).strip(), text_or_none(axis_value) or "")
            for axis_name, axis_value in option_values.items()
            if str(axis_name).strip() and text_or_none(axis_value)
        )
        if normalized_pairs:
            return "options:" + "|".join(
                f"{axis}={value}" for axis, value in normalized_pairs
            )
    # URL-based identity causes duplicate rows; unidentifiable variants
    # are handled by merge_variant_rows instead.
    return None


def _canonical_variant_axis_value(axis_name: object, value: object) -> str:
    axis_key = normalized_variant_axis_key(axis_name)
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    if axis_key != "size":
        return cleaned
    lowered = cleaned.lower()
    for suffix in _variant_size_alias_suffixes:
        if lowered.endswith(suffix):
            base = clean_text(cleaned[: -len(suffix)])
            if base:
                return base
    return cleaned


def variant_semantic_identity(variant: dict[str, Any]) -> str | None:
    if not isinstance(variant, dict):
        return None
    option_values = variant.get("option_values")
    normalized_pairs: list[tuple[str, str]] = []
    if isinstance(option_values, dict) and option_values:
        normalized_pairs = sorted(
            (
                axis_key,
                canonical_value,
            )
            for axis_name, axis_value in option_values.items()
            if (axis_key := normalized_variant_axis_key(axis_name))
            and (
                canonical_value := _canonical_variant_axis_value(axis_name, axis_value)
            )
        )
    else:
        for axis_name in ("size", "color", *_variant_axis_allowed_single_tokens):
            canonical_value = _canonical_variant_axis_value(
                axis_name, variant.get(axis_name)
            )
            if canonical_value:
                normalized_pairs.append((axis_name, canonical_value))
        normalized_pairs.sort()
    if not normalized_pairs:
        return None
    return "semantic:" + "|".join(
        f"{axis_name}={axis_value}" for axis_name, axis_value in normalized_pairs
    )


def collapse_duplicate_size_aliases(record: dict[str, Any]) -> None:
    canonical_targets = _duplicate_size_alias_targets(record)
    if not canonical_targets:
        return
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict) and isinstance(variant_axes.get("size"), list):
        rewritten_values = [
            _canonicalize_size_alias(value, canonical_targets=canonical_targets)
            for value in variant_axes["size"]
        ]
        variant_axes["size"] = list(
            dict.fromkeys(value for value in rewritten_values if clean_text(value))
        )
    for row in [record.get("selected_variant"), *(record.get("variants") or [])]:
        _rewrite_variant_row_size_alias(row, canonical_targets=canonical_targets)


def _duplicate_size_alias_targets(record: dict[str, Any]) -> dict[str, str]:
    seen_values: dict[str, str] = {}
    variant_axes = record.get("variant_axes")
    if isinstance(variant_axes, dict):
        for value in variant_axes.get("size") or []:
            cleaned = clean_text(value)
            if cleaned:
                seen_values.setdefault(cleaned.casefold(), cleaned)
    for row in [record.get("selected_variant"), *(record.get("variants") or [])]:
        if not isinstance(row, dict):
            continue
        for value in (
            row.get("size"),
            row.get("option_values", {}).get("size")
            if isinstance(row.get("option_values"), dict)
            else None,
        ):
            cleaned = clean_text(value)
            if cleaned:
                seen_values.setdefault(cleaned.casefold(), cleaned)
    targets: dict[str, str] = {}
    for lowered, cleaned in seen_values.items():
        base_value = _canonical_variant_axis_value("size", cleaned)
        if not base_value:
            continue
        base_lowered = base_value.casefold()
        if base_lowered in seen_values and base_lowered != lowered:
            targets[lowered] = seen_values[base_lowered]
    return targets


def _canonicalize_size_alias(
    value: object,
    *,
    canonical_targets: dict[str, str],
) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    return canonical_targets.get(cleaned.casefold(), cleaned)


def _rewrite_variant_row_size_alias(
    row: object,
    *,
    canonical_targets: dict[str, str],
) -> None:
    if not isinstance(row, dict):
        return
    canonical_size = _canonicalize_size_alias(
        row.get("size"), canonical_targets=canonical_targets
    )
    if canonical_size:
        row["size"] = canonical_size
    option_values = row.get("option_values")
    if isinstance(option_values, dict):
        option_size = _canonicalize_size_alias(
            option_values.get("size"),
            canonical_targets=canonical_targets,
        )
        if option_size:
            option_values["size"] = option_size


def variant_row_richness(variant: dict[str, Any]) -> tuple[int, int, int]:
    """Compare key for two rows that share an identity."""
    populated_fields = sum(
        1 for value in variant.values() if value not in (None, "", [], {})
    )
    option_values = variant.get("option_values")
    option_value_count = len(option_values) if isinstance(option_values, dict) else 0
    has_stock_signal = int(
        variant.get("stock_quantity") not in (None, "", [], {})
        or variant.get("original_price") not in (None, "", [], {})
    )
    return (populated_fields, option_value_count, has_stock_signal)


def merge_variant_pair(
    primary: dict[str, Any],
    secondary: dict[str, Any],
) -> dict[str, Any]:
    """Merge two rows of the same identity. Primary wins; missing fields filled from secondary."""
    merged = dict(primary)
    for field_name, field_value in secondary.items():
        if merged.get(field_name) in (None, "", [], {}) and field_value not in (
            None,
            "",
            [],
            {},
        ):
            merged[field_name] = field_value
    return merged


def merge_variant_rows(*row_lists: Any) -> list[dict[str, Any]]:
    """Merge variant rows by canonical identity, keeping richer data per identity."""
    merged_by_identity: dict[str, dict[str, Any]] = {}
    ordered_keys: list[str] = []
    identityless_rows: list[dict[str, Any]] = []
    for rows in row_lists:
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            identity = variant_identity(row)
            if not identity:
                identityless_rows.append(dict(row))
                continue
            current = merged_by_identity.get(identity)
            if current is None:
                merged_by_identity[identity] = dict(row)
                ordered_keys.append(identity)
                continue
            primary, secondary = (
                (row, current)
                if variant_row_richness(row) > variant_row_richness(current)
                else (current, row)
            )
            merged_by_identity[identity] = merge_variant_pair(primary, secondary)
    deduped_rows = [merged_by_identity[key] for key in ordered_keys]
    deduped_rows.extend(identityless_rows)
    merged_by_semantic: dict[str, dict[str, Any]] = {}
    for row in deduped_rows:
        semantic_identity = variant_semantic_identity(row)
        if not semantic_identity:
            continue
        current = merged_by_semantic.get(semantic_identity)
        if current is None:
            merged_by_semantic[semantic_identity] = dict(row)
            continue
        primary, secondary = (
            (row, current)
            if variant_row_richness(row) > variant_row_richness(current)
            else (current, row)
        )
        merged_by_semantic[semantic_identity] = merge_variant_pair(primary, secondary)
    merged_rows: list[dict[str, Any]] = []
    emitted_semantic: set[str] = set()
    for row in deduped_rows:
        semantic_identity = variant_semantic_identity(row)
        if not semantic_identity:
            merged_rows.append(row)
            continue
        if semantic_identity in emitted_semantic:
            continue
        merged = merged_by_semantic.get(semantic_identity)
        if merged is None:
            # Defensive: we populated merged_by_semantic on the first pass, so a
            # miss here signals a semantic-identity inconsistency. Preserve the
            # original row rather than silently losing variant data.
            logger.warning(
                "variant merge missed semantic identity %r; preserving original row",
                semantic_identity,
            )
            emitted_semantic.add(semantic_identity)
            merged_rows.append(row)
            continue
        emitted_semantic.add(semantic_identity)
        merged_rows.append(merged)
    return merged_rows
