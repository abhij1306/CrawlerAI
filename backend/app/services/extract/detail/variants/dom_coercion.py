from __future__ import annotations

__all__ = (
    "_dom_variant_axis_allowed",
    "_dom_variant_group_name_allowed",
    "_resolve_dom_variant_group_name",
    "_dom_variant_axis_from_attributes",
    "_strip_variant_option_value_suffix_noise",
    "_coerce_variant_option_value",
    "_coerce_color_option_value",
    "_color_option_value_candidates",
    "_component_size_style_from_group_name",
    "_prefer_axis_inferred_from_values",
    "_split_compound_axis_name",
    "_strip_variant_option_price_suffix",
    "_split_compound_option_value",
    "_expand_compound_option_group",
)

import re
from typing import Any

from app.services.config.extraction_rules import VARIANT_COMPONENT_SIZE_STYLE_LABELS
from app.services.extract.variant_choice_traversal import (
    infer_variant_group_name_from_values,
    resolve_variant_group_name,
)
from app.services.extract.variant_axis import (
    normalized_variant_axis_display_name,
    normalized_variant_axis_key,
    option_scalar_fields,
    public_variant_axis_fields,
    variant_axis_name_is_semantic,
)
from app.services.extract.variant_option_value import (
    variant_option_value_suffix_noise_patterns,
    variant_size_value_patterns,
)
from app.services.shared.field_coerce import (
    clean_text,
    coerce_field_value,
    object_list as _object_list,
    text_or_none,
)

def _dom_variant_axis_allowed(axis_name: str) -> bool:
    return axis_name in public_variant_axis_fields or axis_name == "style"


def _dom_variant_group_name_allowed(group_name: str) -> bool:
    axis_name = normalized_variant_axis_key(group_name)
    return _dom_variant_axis_allowed(axis_name) or bool(
        _split_compound_axis_name(group_name)
    )



def _resolve_dom_variant_group_name(node: Any) -> str:
    attribute_axis = _dom_variant_axis_from_attributes(node)
    if attribute_axis:
        return attribute_axis
    resolved = resolve_variant_group_name(node)
    if resolved and _dom_variant_group_name_allowed(resolved):
        return resolved
    if not hasattr(node, "select"):
        return resolved or ""
    for input_node in node.select("input[type='radio'], input[type='checkbox']")[:24]:
        attribute_axis = _dom_variant_axis_from_attributes(input_node)
        if attribute_axis:
            return attribute_axis
        input_resolved = resolve_variant_group_name(input_node)
        if input_resolved and _dom_variant_group_name_allowed(input_resolved):
            return input_resolved
    return resolved or ""


def _dom_variant_axis_from_attributes(node: Any) -> str:
    if node is None or not hasattr(node, "attrs"):
        return ""
    attrs = getattr(node, "attrs", {}) or {}
    parts: list[str] = []
    for key, value in attrs.items():
        key_text = str(key)
        parts.append(key_text)
        if value not in (None, "", [], {}) and key_text.lower() in {
            "class",
            "data-option-name",
            "data-qa",
            "data-qa-action",
            "data-testid",
            "data-test",
            "id",
            "name",
        }:
            parts.append(str(value))
    attr_blob = " ".join(parts).casefold()
    if "color" in attr_blob or "colour" in attr_blob:
        return "color"
    if "size" in attr_blob:
        return "size"
    return ""


def _strip_variant_option_value_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in variant_option_value_suffix_noise_patterns:
        stripped = pattern.sub("", stripped).strip()
    return stripped or cleaned


def _coerce_variant_option_value(
    axis_name: str,
    raw_value: object,
    *,
    page_url: str,
) -> str:
    if axis_name == "color":
        return _coerce_color_option_value(raw_value, page_url=page_url)
    if axis_name in option_scalar_fields:
        coerced = text_or_none(coerce_field_value(axis_name, raw_value, page_url))
        if coerced:
            return coerced
    return clean_text(raw_value)


def _coerce_color_option_value(raw_value: object, *, page_url: str) -> str:
    cleaned = clean_text(raw_value)
    if not cleaned:
        return ""
    for candidate in _color_option_value_candidates(cleaned):
        coerced = text_or_none(coerce_field_value("color", candidate, page_url))
        if coerced:
            return coerced
    return cleaned


def _color_option_value_candidates(value: str) -> list[str]:
    candidates: list[str] = []
    for pattern in (
        re.compile(
            r"^(?:choose|select|view)\s+(?:alternate\s+product\s+)?(?:colour|color)?\s*(.+?)\s+(?:variant|selected|unselected)$",
            flags=re.I,
        ),
        re.compile(
            r"^(?:choose|select|view)\s+(?:alternate\s+product\s+)?(?:colour|color)\s+(.+)$",
            flags=re.I,
        ),
        re.compile(r"\b(?:in|colour|color)\s*[:\-]?\s+(.+)$", flags=re.I),
        re.compile(r"\b(?:colour|color)\s*[:\-]\s*(.+)$", flags=re.I),
    ):
        match = pattern.search(value)
        if match is None:
            continue
        candidate = clean_text(match.group(1))
        if candidate and candidate.casefold() not in {"an option", "option"}:
            candidates.append(candidate)
    candidates.append(value)
    return list(dict.fromkeys(candidates))


def _component_size_style_from_group_name(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    lowered = cleaned.casefold()
    if "size" not in re.split(r"[^a-z0-9]+", lowered):
        return ""
    for label in tuple(VARIANT_COMPONENT_SIZE_STYLE_LABELS or ()):
        normalized_label = clean_text(label).casefold()
        if not normalized_label:
            continue
        if normalized_label in re.split(r"[^a-z0-9]+", lowered):
            return " ".join(part.capitalize() for part in normalized_label.split())
    return ""


def _prefer_axis_inferred_from_values(
    cleaned_name: str,
    values: list[str],
) -> str:
    inferred_name = infer_variant_group_name_from_values(values)
    if not inferred_name:
        return cleaned_name
    normalized_name = normalized_variant_axis_key(cleaned_name)
    if normalized_name == inferred_name:
        return cleaned_name
    normalized_values = {
        clean_text(value).casefold() for value in values if clean_text(value)
    }
    if clean_text(cleaned_name).casefold() in normalized_values:
        return inferred_name
    if {normalized_name, inferred_name} == {"color", "size"}:
        return inferred_name
    if normalized_name == "base" and inferred_name in {"color", "size"}:
        return inferred_name
    if not variant_axis_name_is_semantic(cleaned_name):
        return inferred_name
    return cleaned_name


def _split_compound_axis_name(name: object) -> list[tuple[str, str]]:
    cleaned = clean_text(name)
    if not cleaned:
        return []
    parts = [
        clean_text(part)
        for part in re.split(r"\s*(?:&|/|\band\b)\s*", cleaned, flags=re.I)
        if clean_text(part)
    ]
    if len(parts) < 2:
        return []
    resolved: list[tuple[str, str]] = []
    seen: set[str] = set()
    for part in parts:
        if not variant_axis_name_is_semantic(part):
            return []
        axis_key = normalized_variant_axis_key(part)
        if not axis_key or axis_key in seen:
            return []
        seen.add(axis_key)
        resolved.append((axis_key, normalized_variant_axis_display_name(part) or part))
    return resolved if len(resolved) >= 2 else []


def _strip_variant_option_price_suffix(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    without_price = re.sub(r"\s*\([^)]*[\d][^)]*\)\s*$", "", cleaned).strip()
    return without_price or cleaned


def _split_compound_option_value(
    value: object,
    *,
    axis_keys: tuple[str, ...],
) -> dict[str, str] | None:
    cleaned = _strip_variant_option_price_suffix(value)
    if not cleaned or len(axis_keys) != 2 or "size" not in axis_keys:
        return None
    other_axis = next((axis for axis in axis_keys if axis != "size"), "")
    if not other_axis:
        return None
    tokens = [token for token in cleaned.split() if token]
    for width in range(min(3, len(tokens)), 0, -1):
        size_candidate = " ".join(tokens[-width:])
        if not any(
            pattern.fullmatch(size_candidate)
            for pattern in variant_size_value_patterns
        ):
            continue
        other_value = clean_text(" ".join(tokens[:-width]))
        if not other_value:
            return None
        return {
            other_axis: other_value,
            "size": size_candidate,
        }
    return None


def _expand_compound_option_group(
    group: dict[str, object],
) -> list[dict[str, object]] | None:
    axis_parts = _split_compound_axis_name(group.get("name"))
    if len(axis_parts) != 2:
        return None
    entries = [
        entry for entry in _object_list(group.get("entries")) if isinstance(entry, dict)
    ]
    if not entries:
        return None
    axis_keys = tuple(axis_key for axis_key, _ in axis_parts)
    parsed_rows: list[dict[str, str]] = []
    for entry in entries:
        parsed = _split_compound_option_value(entry.get("value"), axis_keys=axis_keys)
        if not parsed:
            return None
        parsed_rows.append(parsed)
    axis_values: dict[str, list[str]] = {axis_key: [] for axis_key, _ in axis_parts}
    observed_combos: set[tuple[str, ...]] = set()
    for parsed in parsed_rows:
        combo = tuple(parsed.get(axis_key, "") for axis_key, _ in axis_parts)
        if any(not value for value in combo):
            return None
        observed_combos.add(combo)
        for axis_key, _ in axis_parts:
            axis_value = parsed[axis_key]
            if axis_value not in axis_values[axis_key]:
                axis_values[axis_key].append(axis_value)
    expected_combo_count = 1
    for axis_key, _ in axis_parts:
        values = axis_values.get(axis_key) or []
        if len(values) < 2:
            return None
        expected_combo_count *= len(values)
    if (
        len(observed_combos) != len(parsed_rows)
        or len(observed_combos) != expected_combo_count
    ):
        return None
    return [
        {
            "name": display_name,
            "values": axis_values[axis_key],
            "entries": [{"value": axis_value} for axis_value in axis_values[axis_key]],
        }
        for axis_key, display_name in axis_parts
    ]
