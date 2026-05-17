from __future__ import annotations

from app.services.config.extraction_rules import (
    DETAIL_IRRELEVANT_JSON_LD_TYPES,
    INTEGRAL_PRICE_PAYLOAD_HINT_FIELDS,
    INTEGRAL_PRICE_PAYLOAD_VARIANT_FIELDS,
    IS_AVAILABLE_FIELD,
    IS_INVENTORY_ONLY_FIELD,
    PRICE_SOURCE_KEY_FIELDS,
    SHIPPING_DATE_FIELD,
    SHIPPING_INVENTORY_PAYLOAD_HINT_FIELDS,
    SPECIAL_DAYS_FIELD,
)
from app.services.field_policy import normalize_field_key
from app.services.normalizers import normalize_decimal_price
from app.services.shared.field_coerce import coerce_field_value, extract_urls

_price_source_key_fields = frozenset(
    normalize_field_key(str(field))
    for field in tuple(PRICE_SOURCE_KEY_FIELDS or ())
    if normalize_field_key(str(field))
)


def _uses_integral_price_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    payload_hint_fields = INTEGRAL_PRICE_PAYLOAD_HINT_FIELDS
    variant_hint_fields = INTEGRAL_PRICE_PAYLOAD_VARIANT_FIELDS
    if any(key in payload for key in payload_hint_fields):
        return True
    raw_variants = payload.get("variants")
    if isinstance(raw_variants, list):
        return any(
            isinstance(variant, dict)
            and any(field in variant for field in variant_hint_fields)
            for variant in raw_variants
        )
    return any(field in payload for field in variant_hint_fields)


def _coerce_structured_candidate_value(
    canonical: str,
    value: object,
    *,
    page_url: str,
    payload: object,
    source_key: str = "",
) -> object | None:
    if canonical == "url":
        urls = extract_urls(value, page_url)
        if urls:
            return urls[0]
    if canonical in {
        "price",
        "sale_price",
        "original_price",
    } and _source_key_is_price_field(source_key) and _uses_integral_price_payload(payload):
        normalized = normalize_decimal_price(
            value,
            interpret_integral_as_cents=True,
        )
        if normalized not in (None, ""):
            return normalized
    return coerce_field_value(canonical, value, page_url)


def _source_key_is_price_field(value: object) -> bool:
    normalized = normalize_field_key(str(value or ""))
    return normalized in _price_source_key_fields


def _is_product_attribute_row(payload: dict[str, object]) -> bool:
    keys = {normalize_field_key(str(key or "")) for key in payload}
    return bool(keys & {"id", "name", "label"}) and bool(keys & {"value", "values"})


def _structured_alias_allowed(
    *,
    canonical: str,
    normalized_key: str,
    payload: dict[str, object],
) -> bool:
    if (
        canonical == "sku"
        and normalized_key == "id"
        and _is_product_attribute_row(payload)
    ):
        return False
    payload_types = _structured_payload_types(payload)
    raw_types = payload.get("@type")
    if not payload_types:
        return raw_types in (None, "", [], {})
    if canonical in {
        "title",
        "description",
        "image_url",
        "additional_images",
        "url",
    } and (payload_types & {"brand", "organization", "person", "review", "reviewrating"}):
        return False
    if canonical == "brand" and "person" in payload_types:
        return False
    return True


def _structured_alias_value_allowed(
    *,
    canonical: str,
    normalized_key: str,
    payload: dict[str, object],
    value: object,
) -> bool:
    if canonical == "features" and isinstance(value, (dict, list, tuple, set)):
        return False
    if canonical != "size" or normalized_key != "size":
        return True
    if not isinstance(value, (int, float, str)):
        return True
    payload_keys = {normalize_field_key(str(key or "")) for key in payload}
    inventory_payload_hint_fields = frozenset(SHIPPING_INVENTORY_PAYLOAD_HINT_FIELDS or ())
    inventory_payload_keys = payload_keys & inventory_payload_hint_fields
    return not (
        {SHIPPING_DATE_FIELD, SPECIAL_DAYS_FIELD} <= inventory_payload_keys
        and bool(inventory_payload_keys & {IS_AVAILABLE_FIELD, IS_INVENTORY_ONLY_FIELD})
    )


def _structured_payload_types(payload: dict[str, object]) -> set[str]:
    raw_types = payload.get("@type")
    normalized_types = {
        _normalize_structured_payload_type(item)
        for item in (raw_types if isinstance(raw_types, list) else [raw_types])
        if _normalize_structured_payload_type(item)
    }
    irrelevant_types = {
        str(value).strip().lower()
        for value in tuple(DETAIL_IRRELEVANT_JSON_LD_TYPES or ())
        if str(value).strip()
    }
    if normalized_types and normalized_types <= irrelevant_types:
        return set()
    return normalized_types


def _normalize_structured_payload_type(value: object) -> str:
    text = str(value or "").strip().lower()
    if not text:
        return ""
    for separator in ("#", "/"):
        if separator in text:
            text = text.rsplit(separator, 1)[-1]
    return text
