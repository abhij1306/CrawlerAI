from __future__ import annotations

from app.services.extract.shared_variant_logic import merge_variant_rows
from app.services.shared.field_coerce import (
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    coerce_text,
    text_or_none,
)

from .collection import candidate_fingerprint


def finalize_candidate_value(field_name: str, values: list[object]) -> object | None:
    if not values:
        return None
    if field_name in STRUCTURED_OBJECT_FIELDS:
        merged: dict[str, object] = {}
        for value in values:
            if not isinstance(value, dict):
                continue
            merged = _deep_merge_structured_dict(merged, value)
        return merged or None
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS:
        merged_rows: list[dict[str, object]] = []
        seen_rows: set[str] = set()
        for value in values:
            if not isinstance(value, list):
                continue
            for row in value:
                if not isinstance(row, dict):
                    continue
                fingerprint = candidate_fingerprint(row)
                if fingerprint in seen_rows:
                    continue
                seen_rows.add(fingerprint)
                merged_rows.append(row)
        if field_name == "variants":
            merged_rows = merge_variant_rows(merged_rows)
        return merged_rows or None
    if field_name in STRUCTURED_MULTI_FIELDS:
        rows: list[str] = []
        seen_values: set[str] = set()
        for value in values:
            items = value if isinstance(value, list) else [value]
            for item in items:
                text = text_or_none(item)
                if not text:
                    continue
                lowered = text.lower()
                if lowered in seen_values:
                    continue
                seen_values.add(lowered)
                rows.append(text)
        if field_name in {"additional_images", "features", "tags"}:
            return rows or None
        return "\n".join(rows) if rows else None
    if field_name in LONG_TEXT_FIELDS:
        text_rows: list[str] = []
        text_seen: set[str] = set()
        for value in values:
            text = coerce_text(value)
            if not text:
                continue
            lowered = text.lower()
            if lowered in text_seen:
                continue
            text_seen.add(lowered)
            text_rows.append(text)
        return "\n\n".join(text_rows) if text_rows else None
    return values[0]


def _deep_merge_structured_dict(
    base: dict[str, object],
    incoming: dict[str, object],
) -> dict[str, object]:
    merged = dict(base)
    incoming_option_values = incoming.get("option_values")
    incoming_option_keys = (
        {str(key) for key in incoming_option_values.keys()}
        if isinstance(incoming_option_values, dict)
        else set()
    )
    for key, value in incoming.items():
        normalized_key = str(key)
        existing = merged.get(normalized_key)
        if (
            normalized_key == "option_values"
            and isinstance(existing, dict)
            and existing
            and isinstance(value, dict)
        ):
            continue
        if (
            incoming_option_keys
            and isinstance(merged.get("option_values"), dict)
            and merged["option_values"]
            and normalized_key in incoming_option_keys
            and existing in (None, "", [], {})
        ):
            continue
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[normalized_key] = _deep_merge_structured_dict(existing, value)
            continue
        if isinstance(existing, list) and isinstance(value, list):
            combined: list[object] = []
            seen: set[str] = set()
            for item in [*existing, *value]:
                fingerprint = candidate_fingerprint(item)
                if fingerprint in seen:
                    continue
                seen.add(fingerprint)
                combined.append(item)
            merged[normalized_key] = combined
            continue
        if existing in (None, "", [], {}) and value not in (None, "", [], {}):
            merged[normalized_key] = value
            continue
        if normalized_key not in merged:
            merged[normalized_key] = value
    return merged
