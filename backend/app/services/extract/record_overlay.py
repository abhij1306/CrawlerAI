"""Shared record overlay helpers for primary-wins extraction merges."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.services.config.extraction_rules import RECORD_OVERLAY_MAX_DEPTH
from app.services.shared.coerce_primitives import is_blank

__all__ = ("overlay_record",)


def overlay_record(
    primary: dict[str, Any],
    secondary: dict[str, Any],
    *,
    skip_fields: Iterable[str] = (),
    overwrite_fields: Iterable[str] = (),
    skip_private: bool = False,
    deep_structured: bool = False,
    max_depth: int = RECORD_OVERLAY_MAX_DEPTH,
) -> dict[str, Any]:
    if max_depth <= 0:
        deep_structured = False
    skipped = {str(field) for field in skip_fields}
    overwrite = {str(field) for field in overwrite_fields}
    merged = dict(primary)
    for field_name, field_value in secondary.items():
        normalized_field = str(field_name)
        if skip_private and normalized_field.startswith("_"):
            continue
        if normalized_field in skipped or is_blank(field_value):
            continue
        existing = merged.get(normalized_field)
        if (
            deep_structured
            and isinstance(existing, dict)
            and isinstance(field_value, dict)
        ):
            merged[normalized_field] = overlay_record(
                existing,
                field_value,
                skip_fields=skip_fields,
                overwrite_fields=overwrite_fields,
                skip_private=skip_private,
                deep_structured=True,
                max_depth=max_depth - 1,
            )
            continue
        if normalized_field in overwrite or is_blank(existing):
            merged[normalized_field] = field_value
    return merged
