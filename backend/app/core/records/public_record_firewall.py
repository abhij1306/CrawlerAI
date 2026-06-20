from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from urllib.parse import urlparse

from app.core.config.field_mappings import (
    ADDITIONAL_IMAGES_FIELD,
    AVAILABILITY_FIELD,
    BARCODE_FIELD,
    CANONICAL_SCHEMAS,
    CURRENCY_FIELD,
    IMAGE_URL_FIELD,
    NAVIGATION_URL_FIELDS,
    OPEN_FIELD_SURFACES,
    PRICE_FIELD,
    ROUTE_BARCODE_TO_SKU,
    SKU_FIELD,
    STOCK_QUANTITY_FIELD,
    URL_FIELD,
    VARIANTS_FIELD,
)
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS,
    PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS,
    PUBLIC_RECORD_LEGACY_VARIANT_FIELDS,
    PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS,
    PUBLIC_RECORD_URL_MAX_LENGTH,
)
from app.core.config.variant_policy import (
    PUBLIC_FLAT_VARIANT_FIELDS,
    PUBLIC_VARIANT_AXIS_FIELDS,
)
from app.core.records.field_policy import canonical_requested_fields, normalize_field_key
from app.core.shared.field_coerce import (
    IMAGE_FIELDS,
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    URL_FIELDS,
    coerce_field_value,
    finalize_record,
    text_or_none,
)
from app.core.records.field_url_normalization import (
    canonical_public_record_url,
    is_concatenated_url,
)

_SKIP_FIELD = object()


def public_record_data_for_surface(
    record: dict[str, Any],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    normalized_surface = str(surface or "").strip().lower()
    allowed_fields, explicit_fields, open_field_passthrough = _public_field_policy(
        record,
        normalized_surface=normalized_surface,
        requested_fields=requested_fields,
    )
    data: dict[str, Any] = {}
    rejected: dict[str, str] = {}
    for raw_field_name, raw_value in dict(record or {}).items():
        field_name = normalize_field_key(raw_field_name)
        if not field_name or str(raw_field_name).startswith("_"):
            continue
        if raw_value in (None, "", [], {}):
            continue
        rejection = _policy_rejection_reason(
            field_name,
            normalized_surface=normalized_surface,
            explicit_fields=explicit_fields,
            allowed_fields=allowed_fields,
            open_field_passthrough=open_field_passthrough,
        )
        if rejection:
            rejected[str(raw_field_name)] = rejection
            continue
        coerced = _coerce_public_field(
            record,
            data=data,
            field_name=field_name,
            raw_value=raw_value,
            page_url=page_url,
            allowed_fields=allowed_fields,
        )
        if coerced is _SKIP_FIELD:
            rejected[str(raw_field_name)] = "routed_to_sku"
            continue
        if coerced in (None, "", [], {}):
            rejected[str(raw_field_name)] = "empty_after_coercion"
            continue
        canonical_value, rejection = _validate_and_canonicalize_public_field(
            field_name,
            coerced,
            surface=normalized_surface,
        )
        if rejection:
            rejected[str(raw_field_name)] = rejection
            continue
        data[field_name] = canonical_value
    if normalized_surface.startswith("ecommerce_") and VARIANTS_FIELD in data:
        enforce_flat_variant_public_contract(data, page_url=page_url)
    return finalize_record(data, surface=surface), rejected


def _public_field_policy(
    record: dict[str, Any],
    *,
    normalized_surface: str,
    requested_fields: list[str] | None,
) -> tuple[set[str], set[str], bool]:
    allowed_fields = {
        str(field_name).strip()
        for field_name in list(CANONICAL_SCHEMAS.get(normalized_surface, []))
        if str(field_name).strip()
    }
    allowed_fields.add(URL_FIELD)
    explicit_fields = {
        normalize_field_key(field_name)
        for field_name in canonical_requested_fields(requested_fields or [])
        if normalize_field_key(field_name)
    }
    allowed_fields.update(explicit_fields)
    open_field_passthrough = (
        normalized_surface
        in {
            normalize_field_key(surface_name)
            for surface_name in tuple(OPEN_FIELD_SURFACES or ())
        }
        and normalize_field_key(record.get("_extraction_mode")) == "table_rows"
    )
    return allowed_fields, explicit_fields, open_field_passthrough


def _policy_rejection_reason(
    field_name: str,
    *,
    normalized_surface: str,
    explicit_fields: set[str],
    allowed_fields: set[str],
    open_field_passthrough: bool,
) -> str | None:
    ecommerce_excluded = {
        normalize_field_key(value)
        for value in (
            *tuple(PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS or ()),
            *tuple(PUBLIC_RECORD_LEGACY_VARIANT_FIELDS or ()),
        )
        if normalize_field_key(value)
    }
    if normalized_surface.startswith("ecommerce_") and field_name in ecommerce_excluded:
        return "public_contract_excluded"
    default_excluded = _default_excluded_fields_for_surface(normalized_surface)
    if field_name in default_excluded and field_name not in explicit_fields:
        return "default_public_field_excluded"
    if field_name not in allowed_fields and not open_field_passthrough:
        return "field_not_allowed_for_surface"
    return None


def _coerce_public_field(
    record: dict[str, Any],
    *,
    data: dict[str, Any],
    field_name: str,
    raw_value: object,
    page_url: str,
    allowed_fields: set[str],
) -> object:
    coerced = (
        flatten_variants_for_public_output(raw_value, page_url=page_url)
        if field_name == VARIANTS_FIELD
        else coerce_field_value(field_name, raw_value, page_url)
    )
    if coerced not in (None, "", [], {}):
        return coerced
    if field_name != BARCODE_FIELD or not ROUTE_BARCODE_TO_SKU:
        return coerced
    routed_sku = coerce_field_value(SKU_FIELD, raw_value, page_url)
    if (
        routed_sku not in (None, "", [], {})
        and SKU_FIELD in allowed_fields
        and record.get(SKU_FIELD) in (None, "", [], {})
        and _public_record_field_shape_valid(SKU_FIELD, routed_sku)
    ):
        data[SKU_FIELD] = routed_sku
        return _SKIP_FIELD
    return coerced


def _validate_and_canonicalize_public_field(
    field_name: str,
    coerced: object,
    *,
    surface: str,
) -> tuple[object, str | None]:
    if not _public_record_field_shape_valid(field_name, coerced):
        return coerced, "invalid_field_shape"
    if field_name in URL_FIELDS and isinstance(coerced, str) and is_concatenated_url(coerced):
        return coerced, "concatenated_url"
    if field_name in NAVIGATION_URL_FIELDS and not public_navigation_url_safe(coerced):
        return coerced, "unsafe_navigation_url"
    if field_name not in NAVIGATION_URL_FIELDS:
        return coerced, None
    canonical = canonical_public_record_url(
        coerced,
        surface=surface,
        field_name=field_name,
    )
    if canonical in (None, "", [], {}):
        return canonical, "empty_after_canonical_url"
    return canonical, None


def flatten_variants_for_public_output(
    value: object,
    *,
    page_url: str = "",
) -> list[dict[str, object]] | None:
    del page_url
    if not isinstance(value, list):
        return None
    rows: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        row = {
            str(key): val
            for key, val in item.items()
            if (
                val not in (None, "", [], {})
                and not isinstance(val, bool)
                and not str(key).startswith("_")
                and str(key).strip() in PUBLIC_FLAT_VARIANT_FIELDS
            )
        }
        if _public_variant_row_is_sellable(row):
            rows.append(row)
    return rows or None


def _public_variant_row_is_sellable(row: dict[str, object]) -> bool:
    if not row:
        return False
    transport_fields = {
        "variant_id",
        SKU_FIELD,
        BARCODE_FIELD,
        URL_FIELD,
        PRICE_FIELD,
        CURRENCY_FIELD,
        IMAGE_URL_FIELD,
        AVAILABILITY_FIELD,
        STOCK_QUANTITY_FIELD,
    }
    if any(row.get(field) not in (None, "", [], {}) for field in transport_fields):
        return True
    axes = {
        str(key)
        for key, value in row.items()
        if str(key) in PUBLIC_VARIANT_AXIS_FIELDS and value not in (None, "", [], {})
    }
    return len(axes) >= 2


def enforce_flat_variant_public_contract(
    record: dict[str, Any],
    *,
    page_url: str = "",
) -> None:
    variants = flatten_variants_for_public_output(record.get(VARIANTS_FIELD), page_url=page_url)
    if variants:
        record[VARIANTS_FIELD] = variants
        record["variant_count"] = len(variants)
    else:
        record.pop(VARIANTS_FIELD, None)
        record.pop("variant_count", None)


def _default_excluded_fields_for_surface(normalized_surface: str) -> set[str]:
    if not isinstance(PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS, Mapping):
        raise TypeError(
            "PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS must be a mapping; "
            f"got {type(PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS).__name__} "
            f"for surface {normalized_surface!r}"
        )
    return {
        normalize_field_key(field_name)
        for field_name in PUBLIC_RECORD_DEFAULT_EXCLUDED_FIELDS.get(
            normalized_surface,
            [],
        )
        if normalize_field_key(field_name)
    }


def _public_record_field_shape_valid(field_name: str, value: object) -> bool:
    if field_name == VARIANTS_FIELD:
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    if field_name in STRUCTURED_OBJECT_FIELDS:
        return isinstance(value, dict)
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS:
        return isinstance(value, list) and all(isinstance(item, dict) for item in value)
    if field_name in STRUCTURED_MULTI_FIELDS or field_name == ADDITIONAL_IMAGES_FIELD:
        return isinstance(value, list) and all(
            not isinstance(item, (dict, list, tuple, set)) for item in value
        )
    if field_name in URL_FIELDS | IMAGE_FIELDS | LONG_TEXT_FIELDS:
        return isinstance(value, str)
    return not isinstance(value, (dict, list, tuple, set))


def public_navigation_url_safe(value: object) -> bool:
    text = text_or_none(value)
    if not text:
        return False
    if len(text) > int(PUBLIC_RECORD_URL_MAX_LENGTH):
        return False
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return False
    lowered_path = str(parsed.path or "").lower()
    if any(
        marker in lowered_path
        for marker in tuple(PUBLIC_RECORD_URL_BLOCKED_PATH_MARKERS or ())
    ):
        return False
    return True
