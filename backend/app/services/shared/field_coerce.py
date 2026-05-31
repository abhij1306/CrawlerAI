"""Shared field coercion, normalization, and public-record shaping helpers."""
from __future__ import annotations

import ast
import re
from typing import Any, cast
from app.services.extraction_html_helpers import html_to_text
from app.services.config.extraction_rules import (
    AVAILABILITY_URL_MAP,
    CANDIDATE_AVAILABILITY_NOISE_PHRASES,
    COLOR_KEYWORD_PATTERN,
    IMAGE_FIELDS as IMAGE_FIELDS,
    INTEGER_VALUE_FIELDS,
    LISTING_UTILITY_TITLE_PATTERNS,
    LONG_TEXT_FIELDS,
    NOISY_PRODUCT_ATTRIBUTE_KEYS,
    OPTION_VALUE_NOISE_WORDS,
    PRICE_VALUE_FIELDS,
    RATING_RE,
    REVIEW_COUNT_RE as _REVIEW_COUNT_RE,
    SIZE_REJECT_TOKENS,
    SMALL_NUMERIC_PATTERN,
    STRUCTURED_MULTI_FIELDS,
    STRUCTURED_OBJECT_FIELDS,
    STRUCTURED_OBJECT_LIST_FIELDS,
    TRACKING_PIXEL_PATTERN,
    URL_FIELDS as URL_FIELDS,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
)
from app.services.config.field_mappings import (
    CANONICAL_SCHEMAS,
    ADDITIONAL_IMAGES_FIELD,
    BRAND_LIKE_FIELDS,
    FIELD_ALIASES,
    TITLE_FIELD,
    TITLE_STRUCTURED_VALUE_KEYS,
    URL_FIELD,
    WEIGHT_FIELD,
)
from app.services.config.design_system import DESIGN_SYSTEM_PUBLIC_FIELDS, DESIGN_SYSTEM_SURFACE
from app.services.config.public_record_policy import (
    PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS,
    PUBLIC_RECORD_LEGACY_VARIANT_FIELDS,
    PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS,
)
from app.services.config.variant_policy import OPTION_SCALAR_FIELDS
from app.services.config.surface_hints import detail_path_hints
from app.services.field_policy import (
    exact_requested_field_key,
    expand_requested_fields,
    get_surface_field_aliases,
    normalize_field_key,
)
from app.services.normalizers import normalize_record_fields
from app.services.shared.coerce_primitives import (
    coerce_int as _coerce_int,
    object_dict as _object_dict,
    object_list as _object_list,
    safe_int as _safe_int,
)
from app.services.shared.text_coerce import (
    clean_text,
    coerce_literal_text_list,
    coerce_long_text,
    coerce_text,
    is_title_noise as is_title_noise,
    strip_html_tags as strip_html_tags,
    text_or_none,
)
from app.services.shared.field_coerce_price import (
    CURRENCY_CODE_PATTERN,
    CURRENCY_SYMBOL_PATTERN,
    PRICE_RE as PRICE_RE,
    coerce_price_from_dict,
    decimal_for_shared_price,
    extract_currency_code,
    extract_price_text as extract_price_text,
    price_text_is_negative,
)
from app.services.shared.field_coerce_text import (
    category_value_is_url_path,
    coerce_barcode,
    coerce_brand_text,
    coerce_gender,
    coerce_identity_token_or_none,
    coerce_sku,
    identity_internal_tokens,
    infer_brand_from_product_url as infer_brand_from_product_url,
    infer_brand_from_title_marker as infer_brand_from_title_marker,
)
from app.services.shared.field_coerce_url import (
    absolute_url as absolute_url,
    coerce_url_field_value,
    extract_urls as extract_urls,
    is_url_field,
    same_host as same_host,
    strip_record_tracking_params,
    strip_tracking_query_params as strip_tracking_query_params,
)

REVIEW_COUNT_RE = _REVIEW_COUNT_RE
_decimal_for_shared_price = decimal_for_shared_price

PRODUCT_URL_HINTS = detail_path_hints("ecommerce_detail")
JOB_URL_HINTS = detail_path_hints("job_detail")
_FIELD_ALIASES = FIELD_ALIASES
_OPTION_VALUE_SUFFIX_NOISE_RE = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_OPTION_VALUE_NOISE_WORD_PATTERN = "|".join(
    re.escape(str(word))
    for word in tuple(OPTION_VALUE_NOISE_WORDS or ())
    if str(word).strip()
)
ALL_CANONICAL_FIELDS = sorted(
    {
        field_name
        for fields in CANONICAL_SCHEMAS.values()
        for field_name in fields or []
        if field_name
    }
)
_PRICE_FIELD_NAMES = PRICE_VALUE_FIELDS
_INTEGER_FIELD_NAMES = INTEGER_VALUE_FIELDS
_NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    normalize_field_key(str(key or ""))
    for key in tuple(NOISY_PRODUCT_ATTRIBUTE_KEYS or ())
    if str(key or "").strip()
)
_SMALL_NUMERIC_RE = re.compile(str(SMALL_NUMERIC_PATTERN), re.I)
_TRACKING_PIXEL_RE = re.compile(str(TRACKING_PIXEL_PATTERN), re.I)
_COLOR_KEYWORD_RE = re.compile(str(COLOR_KEYWORD_PATTERN), re.I)
_SIZE_REJECT_TOKENS_NORMALIZED: frozenset[str] = frozenset(
    str(token).strip().lower()
    for token in tuple(SIZE_REJECT_TOKENS or ())
    if str(token).strip()
)


object_list = _object_list
object_dict = _object_dict
safe_int = _safe_int
coerce_int = _coerce_int


LISTING_UTILITY_TITLE_REGEXES = tuple(
    re.compile(pattern, re.I) for pattern in LISTING_UTILITY_TITLE_PATTERNS
)
_AVAILABILITY_CANONICAL_ENUM = frozenset(
    str(v) for v in dict(AVAILABILITY_URL_MAP or {}).values() if v
)
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")
_product_type_noise_tokens = frozenset(
    str(token).casefold()
    for token in tuple(PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS or ())
)


def clean_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in record.items()
        if value not in (None, "", [], {})
    }


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


def validate_record_for_surface(
    record: dict[str, Any],
    surface: str,
    *,
    requested_fields: list[str] | None = None,
    strict_types: bool = False,
) -> tuple[dict[str, Any], list[str]]:
    if str(surface or "").strip().lower() == DESIGN_SYSTEM_SURFACE:
        allowed = set(DESIGN_SYSTEM_PUBLIC_FIELDS)
        return {
            key: value
            for key, value in dict(record or {}).items()
            if str(key).startswith("_") or (key in allowed and value not in (None, "", [], {}))
        }, []
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
            allow_noncanonical_requested=False,
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
    return {
        **clean_record(validated_fields),
        **internal_fields,
    }, validation_errors


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
    """Build aliases with exact canonical field keys taking precedence."""
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
        if normalized_requested and exact_field:
            lookup[normalized_requested] = exact_field
    for canonical in fields:
        normalized_canonical = normalize_field_key(canonical)
        if normalized_canonical:
            lookup[normalized_canonical] = canonical
        canonical_aliases = list(aliases.get(canonical, []))
        if not canonical_aliases:
            canonical_aliases = list(_FIELD_ALIASES.get(canonical, []))
        for alias in canonical_aliases:
            normalized_alias = normalize_field_key(alias)
            if normalized_alias:
                lookup.setdefault(normalized_alias, canonical)
    return lookup


def direct_record_to_surface_fields(
    record: dict[str, Any],
    *,
    surface: str,
    page_url: str,
    requested_fields: list[str] | None = None,
    base_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    shaped = dict(base_fields or {})
    source_fields = surface_fields(
        surface,
        requested_fields,
        allow_noncanonical_requested=False,
    )
    for field_name in source_fields:
        value = coerce_field_value(
            field_name, dict(record or {}).get(field_name), page_url
        )
        if value not in (None, "", [], {}):
            shaped[field_name] = value
    return finalize_record(shaped, surface=surface)


def _split_multivalue_text_rows(value: str) -> list[str]:
    rows = [
        clean_text(part)
        for part in re.split(r"(?:\r?\n|[•]+)", str(value or ""))
        if clean_text(part)
    ]
    return rows


def _iter_structured_multi_values(value: object) -> list[object]:
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return []


def _coerce_structured_multi_rows(field_name: str, value: object) -> list[str]:
    if value in (None, "", [], {}):
        return []
    if isinstance(value, bool):
        return []
    iterable_values = _iter_structured_multi_values(value)
    if iterable_values:
        rows = []
        for item in iterable_values:
            rows.extend(_coerce_structured_multi_rows(field_name, item))
        return rows
    if isinstance(value, str):
        literal_rows = coerce_literal_text_list(value)
        if literal_rows:
            return literal_rows
        text = (
            html_to_text(value, preserve_block_breaks=True)
            if ("<" in value or _HTML_ENTITY_RE.search(value))
            else str(value)
        )
        rows = _split_multivalue_text_rows(text)
        if rows:
            return rows
    coerced_text = coerce_text(value)
    return [coerced_text] if coerced_text is not None else []


def coerce_structured_scalar(
    value: object,
    *,
    keys: tuple[str, ...],
) -> str | None:
    if isinstance(value, str):
        stripped = value.strip()
        if stripped.startswith("{") and stripped.endswith("}"):
            try:
                parsed = ast.literal_eval(stripped)
            except (MemoryError, RecursionError, SyntaxError, TypeError, ValueError):
                return None
            if isinstance(parsed, (dict, list)):
                return coerce_structured_scalar(parsed, keys=keys)
            return None
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate in (None, "", [], {}):
                continue
            text = coerce_structured_scalar(candidate, keys=keys)
            if text:
                return text
        return None
    if isinstance(value, list):
        for item in value:
            text = coerce_structured_scalar(item, keys=keys)
            if text:
                return text
        return None
    return coerce_text(value)


def _join_text_parts(parts: list[str | None], *, separator: str) -> str | None:
    cleaned_parts = [part for part in parts if part]
    return separator.join(cleaned_parts) if cleaned_parts else None


def _color_value_is_opaque_code(value: str) -> bool:
    """Reject internal swatch/style codes that masquerade as colors.

    Real color values render as human-readable text. Some sources (e.g.
    Patagonia structured payload ``"color":["SMDB","FGE","OLGG",...]``)
    expose internal short codes for swatches. The full color names exist
    elsewhere on the page; the codes pollute the canonical color when
    the candidate scoring picks the first list element.

    Signature: short (2-5 chars), all upper-case, no separators, AND not a
    recognized short color word. Lowercase short values can be real DOM color
    text ("mint", "ecru", "aqua") and must not be dropped here.
    """
    text = value.strip()
    if not text or " " in text or any(sep in text for sep in ("-", "_", "/", ".")):
        return False
    if not re.fullmatch(r"[A-Za-z]{2,5}", text):
        return False
    if not text.isupper():
        return False
    if text.casefold() in _SHORT_COLOR_ALLOWLIST:
        return False
    return True


_SHORT_COLOR_ALLOWLIST = frozenset(
    {
        # short, real color words. Lower-case only is fine; real PDPs use
        # mixed-case rendering. Keep this list narrow — it only protects
        # genuinely human-readable short forms.
        "red", "tan", "navy", "blue", "pink", "gold", "lime", "teal",
        "gray", "grey", "black", "white", "green", "ivory", "khaki",
        "olive", "rose", "wine", "rust", "sand", "snow", "cyan",
        "plum", "ruby", "lilac", "coral", "azure", "beige", "amber",
        "denim", "ochre", "mocha", "mauve", "stone", "stoun",
    }
)


def _sanitize_option_scalar(field_name: str, value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    if text.lstrip().startswith(("{", "[")):
        return None
    cleaned = text
    if field_name in OPTION_SCALAR_FIELDS:
        for pattern in _OPTION_VALUE_SUFFIX_NOISE_RE:
            cleaned = clean_text(pattern.sub("", cleaned))
        cleaned = re.sub(
            rf"\s+(?:{CURRENCY_SYMBOL_PATTERN})\s*\d[\d.,]*.*$", "", cleaned
        )
        cleaned = re.sub(
            rf"\s+\d[\d.,]*\s*(?:{CURRENCY_CODE_PATTERN})\b.*$",
            "",
            cleaned,
            flags=re.I,
        )
        if _OPTION_VALUE_NOISE_WORD_PATTERN:
            cleaned = re.sub(
                rf"\s+\b(?:{_OPTION_VALUE_NOISE_WORD_PATTERN})\b.*$",
                "",
                cleaned,
                flags=re.I,
            )
        cleaned = clean_text(cleaned)
    if field_name == "color":
        if _SMALL_NUMERIC_RE.fullmatch(cleaned):
            return None
        if _TRACKING_PIXEL_RE.fullmatch(cleaned):
            return None
        if _color_value_is_opaque_code(cleaned):
            return None
        match = re.fullmatch(r"select\s+(.+?)\s+color", cleaned, flags=re.I)
        if match is not None:
            cleaned = clean_text(match.group(1))
        cleaned = re.split(r"\bstyle\s*:", cleaned, maxsplit=1, flags=re.I)[0]
        if ":" in cleaned:
            _prefix, suffix = cleaned.rsplit(":", 1)
            if len(clean_text(suffix).split()) <= 4 and _COLOR_KEYWORD_RE.search(
                suffix
            ):
                cleaned = suffix
        cleaned = re.sub(r"^color\s*:\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\bcolor\s+details\b.*$", "", cleaned, flags=re.I).strip()
        cleaned = re.split(r"\bview as list\b", cleaned, maxsplit=1, flags=re.I)[0]
        cleaned = re.split(
            r"\bsize(?:\s*\([^)]*\))?\b", cleaned, maxsplit=1, flags=re.I
        )[0]
        cleaned = clean_text(cleaned)
        if not cleaned or re.search(r"\d+\s*x\s*\d+", cleaned):
            return None
    elif field_name == "size":
        cleaned = re.sub(r"^size\s*:\s*", "", cleaned, flags=re.I)
        cleaned = re.split(r"\bview as list\b", cleaned, maxsplit=1, flags=re.I)[0]
        cleaned = re.sub(r"\s*\(size[\s_-]*chart\)", "", cleaned, flags=re.I)
        cleaned = clean_text(cleaned)
        if re.search(r"\b(?:please\s+)?select(?:\s+size)?\b", cleaned, flags=re.I):
            return None
        if cleaned.strip().lower() in _SIZE_REJECT_TOKENS_NORMALIZED:
            return None
    elif field_name == WEIGHT_FIELD and re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return None
    if cleaned.strip().casefold() in {"none", "null", "- / null", "n/a", "na"}:
        return None
    return cleaned or None


def coerce_location(value: object) -> str | None:
    if isinstance(value, dict):
        address = value.get("address")
        if isinstance(address, str):
            address_text = text_or_none(address)
            if address_text:
                return address_text
        if isinstance(address, dict):
            joined_address = _join_text_parts(
                [
                    text_or_none(address.get("streetAddress")),
                    text_or_none(address.get("addressLocality")),
                    text_or_none(address.get("addressRegion")),
                    text_or_none(address.get("postalCode")),
                    text_or_none(address.get("addressCountry")),
                ],
                separator=", ",
            )
            if joined_address:
                return joined_address
        return _join_text_parts(
            [
                text_or_none(value.get("name")),
                text_or_none(value.get("addressLocality")),
                text_or_none(value.get("addressRegion")),
                text_or_none(value.get("addressCountry")),
            ],
            separator=", ",
        )
    if isinstance(value, list):
        return _join_text_parts(
            [coerce_location(item) for item in value],
            separator=" | ",
        )
    return coerce_text(value)


def _salary_from_nested_value(
    nested: dict[str, object],
    *,
    currency: str | None,
) -> str | None:
    minimum = text_or_none(nested.get("minValue"))
    maximum = text_or_none(nested.get("maxValue"))
    amount = text_or_none(nested.get("value"))
    unit = text_or_none(nested.get("unitText"))
    numbers = " - ".join(part for part in (minimum, maximum) if part)
    if not numbers:
        numbers = amount or ""
    if not numbers:
        return None
    return " ".join(piece for piece in (currency, numbers, unit) if piece)


def salary_from_json(value: object) -> str | None:
    if isinstance(value, dict):
        currency = text_or_none(
            value.get("currency")
            or value.get("salaryCurrency")
            or value.get("currencyCode")
        )
        nested = value.get("value")
        if isinstance(nested, dict):
            nested_salary = _salary_from_nested_value(nested, currency=currency)
            if nested_salary:
                return nested_salary
        text = coerce_text(value.get("value"))
        if text:
            return f"{currency} {text}".strip() if currency else text
    return coerce_text(value)


def coerce_product_attributes(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    cleaned = _clean_product_attribute_dict(value)
    return cleaned or None


def _product_attribute_key_is_noise(value: object) -> bool:
    normalized = normalize_field_key(str(value or ""))
    return bool(normalized and normalized in _NOISY_PRODUCT_ATTRIBUTE_KEYS)


def _product_attribute_row_is_noise(value: dict[str, object]) -> bool:
    row_id = (
        value.get("Id") or value.get("id") or value.get("name") or value.get("label")
    )
    return _product_attribute_key_is_noise(row_id)


def _clean_product_attribute_value(value: object) -> object | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, dict):
        if _product_attribute_row_is_noise(value):
            return None
        return _clean_product_attribute_dict(value)
    if isinstance(value, list):
        rows = [
            cleaned
            for item in value
            if (cleaned := _clean_product_attribute_value(item))
            not in (None, "", [], {})
        ]
        return rows or None
    return value


def _clean_product_attribute_dict(value: dict[str, object]) -> dict[str, object]:
    cleaned: dict[str, object] = {}
    for key, item in value.items():
        if _product_attribute_key_is_noise(key):
            continue
        cleaned_value = _clean_product_attribute_value(item)
        if cleaned_value not in (None, "", [], {}):
            cleaned[str(key)] = cleaned_value
    return cleaned


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
    # Drop non-canonical residual text so noisy values cannot leak through.
    normalized_enum = lowered.replace("-", "_").replace(" ", "_")
    if normalized_enum in _AVAILABILITY_CANONICAL_ENUM:
        return normalized_enum
    return None


def coerce_rating_value(value: object) -> float | None:
    text = coerce_text(value)
    if not text:
        return None
    match = RATING_RE.search(text)
    candidate = match.group(0) if match else text
    try:
        return float(candidate)
    except (TypeError, ValueError):
        return None


def coerce_field_value(field_name: str, value: object, page_url: str) -> object | None:
    if value in (None, "", [], {}):
        return None
    if field_name == "product_attributes":
        return coerce_product_attributes(value)
    if field_name in STRUCTURED_OBJECT_FIELDS and isinstance(value, dict):
        return value
    if field_name in STRUCTURED_OBJECT_LIST_FIELDS and isinstance(value, list):
        dict_rows = [item for item in value if isinstance(item, dict)]
        return dict_rows or None
    if field_name == "location":
        return coerce_location(value)
    if field_name == "salary":
        return salary_from_json(value)
    if field_name in {"currency", "salary_currency"} and isinstance(value, str):
        currency_code = extract_currency_code(value)
        if currency_code:
            return currency_code
        text = coerce_text(value)
        if text and re.fullmatch(r"[A-Za-z]{3}", text):
            return text.upper()
        return text
    if field_name in BRAND_LIKE_FIELDS and isinstance(
        value,
        dict,
    ):
        explicit_value = value.get("name") or value.get("title") or value.get("value")
        if explicit_value in (None, "", [], {}) and set(value.keys()) <= {
            str(index) for index in range(len(value))
        }:
            explicit_value = list(value.values())[0] if value else None
        return coerce_brand_text(explicit_value)
    if field_name in BRAND_LIKE_FIELDS:
        return coerce_brand_text(value)
    if field_name == "category":
        if isinstance(value, dict):
            value = (
                value.get("name")
                or value.get("title")
                or value.get("slug")
                or value.get("value")
            )
        category_text = coerce_text(value)
        if category_text and category_value_is_url_path(category_text):
            return None
        return category_text
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
        scalar_input: object = value
        if field_name == "color" and isinstance(value, list):
            # Filter out opaque internal swatch codes before picking the first
            # candidate. Real human-readable colors elsewhere in the list
            # should win over codes like "SMDB"/"OLGG".
            filtered = [
                item
                for item in value
                if not (
                    isinstance(item, str) and _color_value_is_opaque_code(item)
                )
            ]
            if filtered:
                scalar_input = filtered
        return _sanitize_option_scalar(
            field_name,
            coerce_structured_scalar(
                scalar_input,
                keys=(field_name, "name", "title", "label", "value", "text"),
            ),
        )
    if field_name in _PRICE_FIELD_NAMES and isinstance(value, str):
        text = coerce_text(value)
        if text and not re.search(r"\d", text):
            return None
        if price_text_is_negative(text):
            return None
        return text or None
    if (
        field_name in _INTEGER_FIELD_NAMES
        and isinstance(value, (int, float))
        and not isinstance(value, bool)
    ):
        return int(value)
    if field_name in _INTEGER_FIELD_NAMES and isinstance(value, str):
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
    if field_name in {
        "price",
        "sale_price",
        "original_price",
        "discount_amount",
    } and isinstance(value, dict):
        return coerce_price_from_dict(value)
    if field_name in {"currency", "salary_currency"} and isinstance(value, dict):
        for key in ("currency", "currencyCode", "priceCurrency", "salaryCurrency"):
            if value.get(key) not in (None, "", [], {}):
                return coerce_text(value.get(key))
        return None
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
        rows = _coerce_structured_multi_rows(field_name, value)
        deduped: list[str] = []
        seen: set[str] = set()
        for row in rows:
            lowered = row.lower()
            if lowered in seen:
                continue
            seen.add(lowered)
            deduped.append(row)
        return deduped or None
    if isinstance(value, list):
        normalized_rows: list[object] = []
        for item in value:
            normalized_value = cast(
                object, coerce_field_value(field_name, item, page_url)
            )
            if normalized_value in (None, "", [], {}):
                continue
            if isinstance(normalized_value, list):
                normalized_rows.extend(normalized_value)
            else:
                normalized_rows.append(normalized_value)
        return normalized_rows or None
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
        structured = coerce_structured_scalar(
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
        value = coerce_structured_scalar(
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
    if any(token in folded for token in _product_type_noise_tokens):
        return None
    return text


def finalize_record(
    record: dict[str, Any],
    *,
    normalize_fields: bool = True,
    surface: str | None = None,
) -> dict[str, Any]:
    cleaned = clean_record(record)
    cleaned = strip_record_tracking_params(cleaned, surface=surface)
    return normalize_record_fields(cleaned) if normalize_fields else cleaned


decimal_for_shared_price = _decimal_for_shared_price


__all__ = [
    "ADDITIONAL_IMAGES_FIELD",
    "ALL_CANONICAL_FIELDS",
    "AVAILABILITY_URL_MAP",
    "BRAND_LIKE_FIELDS",
    "CANDIDATE_AVAILABILITY_NOISE_PHRASES",
    "CANONICAL_SCHEMAS",
    "COLOR_KEYWORD_PATTERN",
    "CURRENCY_CODE_PATTERN",
    "CURRENCY_SYMBOL_PATTERN",
    "DESIGN_SYSTEM_PUBLIC_FIELDS",
    "DESIGN_SYSTEM_SURFACE",
    "FIELD_ALIASES",
    "IMAGE_FIELDS",
    "INTEGER_VALUE_FIELDS",
    "JOB_URL_HINTS",
    "LISTING_UTILITY_TITLE_PATTERNS",
    "LISTING_UTILITY_TITLE_REGEXES",
    "LONG_TEXT_FIELDS",
    "NOISY_PRODUCT_ATTRIBUTE_KEYS",
    "OPTION_SCALAR_FIELDS",
    "OPTION_VALUE_NOISE_WORDS",
    "PRICE_RE",
    "PRICE_VALUE_FIELDS",
    "PRODUCT_URL_HINTS",
    "PUBLIC_RECORD_ECOMMERCE_DROPPED_FIELDS",
    "PUBLIC_RECORD_LEGACY_VARIANT_FIELDS",
    "PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS",
    "RATING_RE",
    "REVIEW_COUNT_RE",
    "SIZE_REJECT_TOKENS",
    "SMALL_NUMERIC_PATTERN",
    "STRUCTURED_MULTI_FIELDS",
    "STRUCTURED_OBJECT_FIELDS",
    "STRUCTURED_OBJECT_LIST_FIELDS",
    "TITLE_FIELD",
    "TITLE_STRUCTURED_VALUE_KEYS",
    "TRACKING_PIXEL_PATTERN",
    "URL_FIELD",
    "URL_FIELDS",
    "VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS",
    "WEIGHT_FIELD",
    "absolute_url",
    "category_value_is_url_path",
    "clean_record",
    "clean_text",
    "coerce_availability_dict",
    "coerce_availability_value",
    "coerce_barcode",
    "coerce_brand_text",
    "coerce_field_value",
    "coerce_gender",
    "coerce_identity_token_or_none",
    "coerce_int",
    "coerce_literal_text_list",
    "coerce_location",
    "coerce_long_text",
    "coerce_price_from_dict",
    "coerce_product_attributes",
    "coerce_rating_value",
    "coerce_sku",
    "coerce_structured_scalar",
    "coerce_text",
    "coerce_url_field_value",
    "decimal_for_shared_price",
    "detail_path_hints",
    "direct_record_to_surface_fields",
    "exact_requested_field_key",
    "expand_requested_fields",
    "extract_currency_code",
    "extract_price_text",
    "extract_urls",
    "finalize_record",
    "get_surface_field_aliases",
    "identity_internal_tokens",
    "infer_brand_from_product_url",
    "infer_brand_from_title_marker",
    "is_title_noise",
    "is_url_field",
    "normalize_field_key",
    "normalize_record_fields",
    "object_dict",
    "object_list",
    "price_text_is_negative",
    "safe_int",
    "salary_from_json",
    "same_host",
    "strip_html_tags",
    "strip_record_tracking_params",
    "strip_tracking_query_params",
    "surface_alias_lookup",
    "surface_fields",
    "text_or_none",
    "validate_record_for_surface",
]
