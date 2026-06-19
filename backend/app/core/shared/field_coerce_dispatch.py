from __future__ import annotations

import re
from typing import Any, cast

from app.core.config.extraction_rules import (
    AVAILABILITY_URL_MAP,
    CANDIDATE_AVAILABILITY_NOISE_PHRASES,
    LONG_TEXT_FIELDS,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
)
from app.core.config.field_mappings import (
    BRAND_LIKE_FIELDS,
    TITLE_FIELD,
    TITLE_STRUCTURED_VALUE_KEYS,
)
from app.core.config.variant_policy import OPTION_SCALAR_FIELDS
from app.core.shared.field_coerce_price import (
    extract_currency_code,
    price_text_is_negative,
    coerce_price_from_dict,
)
from app.core.shared.field_coerce_text import (
    category_value_is_url_path,
    coerce_barcode,
    coerce_brand_text,
    coerce_gender,
    coerce_identity_token_or_none,
    coerce_sku,
    identity_internal_tokens,
)
from app.core.shared.field_coerce_url import coerce_url_field_value, is_url_field
from app.core.shared.text_coerce import (
    coerce_long_text,
    coerce_text,
)



def _field_coerce() -> Any:
    from app.core.shared import field_coerce

    return field_coerce


def coerce_availability_dict(value: object) -> str | None:
    if not isinstance(value, dict):
        return None
    explicit_keys = ("availability", "availabilityStatus", "status")
    for key in explicit_keys:
        candidate = value.get(key)
        if candidate not in (None, "", [], {}):
            return coerce_availability_value(candidate)
    if len(value) == 1:
        for key in ("name", "value"):
            candidate = value.get(key)
            if candidate not in (None, "", [], {}):
                return coerce_availability_value(candidate)
    return None


def coerce_availability_value(value: object) -> str | None:
    if isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    text = coerce_text(value)
    if text:
        for phrase in tuple(CANDIDATE_AVAILABILITY_NOISE_PHRASES or ()):
            if phrase.lower() in text.lower():
                text = re.sub(re.escape(phrase), "", text, flags=re.I).strip()
                if not text:
                    return None
    if not text:
        return None
    lowered = text.strip().lower().rstrip("/")
    mapped = dict(AVAILABILITY_URL_MAP or {}).get(lowered)
    if mapped:
        return str(mapped)
    normalized_enum = lowered.replace("-", "_").replace(" ", "_")
    if normalized_enum in _field_coerce()._AVAILABILITY_CANONICAL_ENUM:
        return normalized_enum
    return None


def coerce_rating_value(value: object) -> float | None:
    text = coerce_text(value)
    if not text:
        return None
    match = _field_coerce().RATING_RE.search(text)
    candidate = match.group(0) if match else text
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return None


def _coerce_currency_value(value: object) -> str | None:
    if isinstance(value, dict):
        for key in ("currency", "currencyCode", "priceCurrency", "salaryCurrency"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
    if not isinstance(value, str):
        return None
    currency_code = extract_currency_code(value)
    if currency_code:
        return currency_code
    text = coerce_text(value)
    if text and re.fullmatch(r"[A-Za-z]{3}", text):
        return text.upper()
    return text


def _coerce_category_value(value: object) -> str | None:
    if isinstance(value, dict):
        value = (
            value.get("name")
            or value.get("title")
            or value.get("slug")
            or value.get("value")
            or value.get("en")
        )
    elif isinstance(value, str) and value.strip().startswith(("{", "[")):
        value = _field_coerce().coerce_structured_scalar(
            value,
            keys=("name", "title", "label", "value", "text", "en"),
        )
    category_text = coerce_text(value)
    if category_text and category_value_is_url_path(category_text):
        return None
    return category_text


def _coerce_brand_like_value(value: object) -> str | None:
    if isinstance(value, dict):
        explicit_value = value.get("name") or value.get("title") or value.get("value")
        if explicit_value in (None, "", [], {}) and set(value.keys()) <= {
            str(index) for index in range(len(value))
        }:
            explicit_value = list(value.values())[0] if value else None
        return coerce_brand_text(explicit_value)
    return coerce_brand_text(value)


def _coerce_option_scalar_value(field_name: str, value: object) -> str | None:
    scalar_input: object = value
    if field_name == "color" and isinstance(value, list):
        filtered = [
            item
            for item in value
            if not (
                isinstance(item, str)
                and _field_coerce()._color_value_is_opaque_code(item)
            )
        ]
        if filtered:
            scalar_input = filtered
    return _field_coerce()._sanitize_option_scalar(
        field_name,
        _field_coerce().coerce_structured_scalar(
            scalar_input,
            keys=(field_name, "name", "title", "label", "value", "text"),
        ),
    )


def _coerce_integer_value(value: object) -> int | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(value)
    if not isinstance(value, str):
        return None
    text = coerce_text(value)
    if not text:
        return None
    normalized = text.replace(",", "").strip()
    if not re.fullmatch(r"[-+]?\d+", normalized):
        return None
    try:
        return int(normalized)
    except (TypeError, ValueError):
        return None


def _coerce_structured_multi_value(field_name: str, value: object) -> list[str] | None:
    rows = _field_coerce()._coerce_structured_multi_rows(field_name, value)
    deduped: list[str] = []
    seen: set[str] = set()
    for row in rows:
        lowered = row.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(row)
    return deduped or None


def _coerce_list_value(field_name: str, value: list[object], page_url: str) -> list[object] | None:
    normalized_rows: list[object] = []
    for item in value:
        normalized_value = cast(object, coerce_field_value(field_name, item, page_url))
        if normalized_value in (None, "", [], {}):
            continue
        if isinstance(normalized_value, list):
            normalized_rows.extend(normalized_value)
        else:
            normalized_rows.append(normalized_value)
    return normalized_rows or None


def coerce_field_value(field_name: str, value: object, page_url: str) -> object | None:
    if value in (None, "", [], {}):
        return None
    if field_name == "product_attributes":
        return _field_coerce().coerce_product_attributes(value)
    if field_name in STRUCTURED_OBJECT_FIELDS and isinstance(value, dict):
        return value
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS and isinstance(value, list):
        dict_rows = [item for item in value if isinstance(item, dict)]
        return dict_rows or None
    if field_name == "location":
        return _field_coerce().coerce_location(value)
    if field_name == "salary":
        return _field_coerce().salary_from_json(value)
    if field_name in {"currency", "salary_currency"} and isinstance(value, str):
        return _coerce_currency_value(value)
    if field_name in BRAND_LIKE_FIELDS:
        return _coerce_brand_like_value(value)
    if field_name == "category":
        return _coerce_category_value(value)
    if field_name == "product_type":
        return _coerce_product_type_clean(value)
    if field_name == "product_id":
        return coerce_identity_token_or_none(value)
    if field_name == TITLE_FIELD:
        return _coerce_title_text(value)
    if field_name == "barcode":
        return coerce_barcode(value)
    if field_name == "sku":
        return coerce_sku(value)
    if field_name == "gender":
        return coerce_gender(value)
    if field_name in OPTION_SCALAR_FIELDS:
        return _coerce_option_scalar_value(field_name, value)
    if field_name in _field_coerce().PRICE_VALUE_FIELDS and isinstance(value, str):
        text = coerce_text(value)
        if text and not re.search(r"\d", text):
            return None
        if price_text_is_negative(text):
            return None
        return text or None
    if field_name in _field_coerce().INTEGER_VALUE_FIELDS:
        return _coerce_integer_value(value)
    if field_name in {
        "price",
        "sale_price",
        "original_price",
        "discount_amount",
    } and isinstance(value, dict):
        return coerce_price_from_dict(value)
    if field_name in {"currency", "salary_currency"} and isinstance(value, dict):
        return _coerce_currency_value(value)
    if field_name == "rating" and isinstance(value, dict):
        for key in ("ratingValue", "value", "rating", "score"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_rating_value(value.get(key))
        return None
    if field_name == "review_count" and isinstance(value, dict):
        for key in (
            "reviewCount",
            "ratingCount",
            "count",
            "totalCount",
            "numberOfReviews",
        ):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
    if field_name == "availability" and isinstance(value, bool):
        return "in_stock" if value else "out_of_stock"
    if field_name == "availability" and isinstance(value, dict):
        return coerce_availability_dict(value)
    if field_name == "availability":
        return coerce_availability_value(value)
    if is_url_field(field_name):
        return coerce_url_field_value(field_name, value, page_url)
    if field_name in STRUCTURED_MULTI_FIELDS:
        return _coerce_structured_multi_value(field_name, value)
    if isinstance(value, list):
        return _coerce_list_value(field_name, value, page_url)
    if isinstance(value, (dict, set, frozenset)):
        return None
    if field_name in LONG_TEXT_FIELDS:
        return coerce_long_text(value)
    if field_name == "rating":
        return coerce_rating_value(value)
    return coerce_text(value)


def _coerce_title_text(value: object) -> str | None:
    is_structured_input = isinstance(value, dict) or (
        isinstance(value, str)
        and value.strip().startswith("{")
        and value.strip().endswith("}")
    )
    if is_structured_input:
        structured = _field_coerce().coerce_structured_scalar(
            value,
            keys=TITLE_STRUCTURED_VALUE_KEYS,
        )
        if structured:
            value = structured
        else:
            return None
    return coerce_identity_token_or_none(value)


def _coerce_product_type_clean(value: object) -> str | None:
    if isinstance(value, dict):
        value = _field_coerce().coerce_structured_scalar(
            value, keys=("name", "title", "label", "value", "text", "type")
        )
    text = coerce_text(value)
    if not text:
        return None
    if text.lstrip().startswith(("{", "[")):
        return None
    folded = text.strip().lower()
    if folded in identity_internal_tokens():
        return None
    if any(token in folded for token in _field_coerce()._product_type_noise_tokens):
        return None
    return text
