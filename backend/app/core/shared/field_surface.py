from __future__ import annotations

from typing import Any

from app.core.config.extraction_rules import (
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
)
from app.core.config.field_mappings import (
    ADDITIONAL_IMAGES_FIELD,
    CANONICAL_SCHEMAS,
    FIELD_ALIASES,
    URL_FIELD,
)
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS,
    PUBLIC_RECORD_LEGACY_VARIANT_FIELDS,
)
from app.core.records.field_policy import (
    exact_requested_field_key,
    expand_requested_fields,
    get_surface_field_aliases,
    normalize_field_key,
)
from app.core.shared.coerce_primitives import is_blank

ALL_CANONICAL_FIELDS = sorted(
    {
        field_name
        for fields in CANONICAL_SCHEMAS.values()
        for field_name in fields or []
        if field_name
    }
)


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {str(key): value for key, value in record.items() if not is_blank(value)}


def validate_record_for_surface(
    record: dict[str, Any],
    surface: str,
    *,
    requested_fields: list[str] | None = None,
    strict_types: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    logical_fields = {
        key: value
        for key, value in dict(record).items()
        if not str(key).startswith("_")
    }
    internal_fields = {
        key: value for key, value in dict(record).items() if str(key).startswith("_")
    }
    allowed_fields = {
        normalize_field_key(field_name)
        for field_name in surface_fields(
            surface,
            requested_fields,
            allow_noncanonical_requested=True,
        )
    }
    validation_errors: list[str] = []
    validated_fields: dict[str, Any] = {}
    scalar_list_fields = set(STRUCTURED_MULTI_FIELDS) | {ADDITIONAL_IMAGES_FIELD}
    for field_name, value in logical_fields.items():
        normalized_field = normalize_field_key(field_name)
        if normalized_field not in allowed_fields:
            continue
        if strict_types:
            type_error = _surface_field_type_error(
                field_name=field_name,
                normalized_field=normalized_field,
                value=value,
                scalar_list_fields=scalar_list_fields,
            )
            if type_error:
                validation_errors.append(type_error)
                continue
        validated_fields[field_name] = value
    if str(surface or "").strip().lower().startswith("ecommerce_"):
        for field_name in (
            *tuple(PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS or ()),
            *tuple(PUBLIC_RECORD_LEGACY_VARIANT_FIELDS or ()),
        ):
            validated_fields.pop(str(field_name), None)
    return {**clean_record(validated_fields), **internal_fields}, validation_errors


def _surface_field_type_error(
    *,
    field_name: str,
    normalized_field: str,
    value: object,
    scalar_list_fields: set[str],
) -> str | None:
    if normalized_field in STRUCTURED_OBJECT_LIST_FIELDS and not isinstance(value, list):
        return f"{field_name} expected list"
    if normalized_field in STRUCTURED_OBJECT_FIELDS and not isinstance(value, dict):
        return f"{field_name} expected object"
    if (
        normalized_field not in STRUCTURED_OBJECT_FIELDS
        and normalized_field not in STRUCTURED_OBJECT_LIST_FIELDS
        and not (normalized_field in scalar_list_fields and isinstance(value, list))
        and isinstance(value, (dict, list, set, frozenset))
    ):
        return f"{field_name} expected scalar"
    return None


def surface_fields(
    surface: str,
    requested_fields: list[str] | None,
    *,
    allow_noncanonical_requested: bool = True,
) -> list[str]:
    normalized_surface = str(surface or "").strip().lower()
    fields = list(CANONICAL_SCHEMAS.get(normalized_surface, ALL_CANONICAL_FIELDS))
    allowed_fields = set(ALL_CANONICAL_FIELDS)
    if URL_FIELD not in fields:
        fields.append(URL_FIELD)
    for field_name in requested_fields or []:
        exact_field = exact_requested_field_key(field_name)
        if (
            exact_field
            and (allow_noncanonical_requested or exact_field in allowed_fields)
            and exact_field not in fields
        ):
            fields.append(exact_field)
    for field_name in expand_requested_fields(requested_fields or []):
        if (
            field_name
            and (allow_noncanonical_requested or field_name in allowed_fields)
            and field_name not in fields
        ):
            fields.append(field_name)
    return fields


def surface_alias_lookup(
    surface: str,
    requested_fields: list[str] | None,
) -> dict[str, str]:
    fields = surface_fields(surface, requested_fields)
    aliases = get_surface_field_aliases(surface)
    lookup: dict[str, str] = {}
    for requested in requested_fields or []:
        normalized_requested = normalize_field_key(requested)
        exact_field = exact_requested_field_key(requested)
        if normalized_requested:
            lookup[normalized_requested] = exact_field or normalized_requested
        if exact_field:
            lookup[exact_field] = exact_field
    for canonical in fields:
        normalized_canonical = normalize_field_key(canonical)
        if normalized_canonical:
            lookup[normalized_canonical] = canonical
        canonical_aliases = list(aliases.get(canonical, []))
        if not canonical_aliases:
            canonical_aliases = list(FIELD_ALIASES.get(canonical, []))
        for alias in canonical_aliases:
            normalized_alias = normalize_field_key(alias)
            if normalized_alias:
                lookup.setdefault(normalized_alias, canonical)
    return lookup
