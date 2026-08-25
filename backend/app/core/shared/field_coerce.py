"""Shared field coercion, normalization, and public-record shaping helpers."""

from __future__ import annotations

import ast
import json
import re
from typing import Any
from app.core.records.html_helpers import html_to_text
from app.core.config.extraction_rules import (
    AVAILABILITY_URL_MAP,
    COLOR_KEYWORD_PATTERN,
    IMAGE_FIELDS as IMAGE_FIELDS,
    LONG_TEXT_FIELDS as LONG_TEXT_FIELDS,
    NOISY_PRODUCT_ATTRIBUTE_KEYS,
    OPTION_VALUE_NOISE_WORDS,
    # Read dynamically by field_coerce_dispatch via module attribute.
    RATING_RE as RATING_RE,
    REVIEW_COUNT_RE as _REVIEW_COUNT_RE,
    SIZE_REJECT_TOKENS,
    SMALL_NUMERIC_PATTERN,
    TRACKING_PIXEL_PATTERN,
    URL_FIELDS as URL_FIELDS,
    VARIANT_COLOR_CODELIKE_TOKEN_PATTERN,
    VARIANT_OPAQUE_NUMERIC_OPTION_AXES,
    VARIANT_OPAQUE_NUMERIC_OPTION_MIN_DIGITS,
    VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
)
from app.core.config.field_mappings import (
    FIELD_ALIASES,
    WEIGHT_FIELD,
)
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS,
)
from app.core.config.variant_policy import OPTION_SCALAR_FIELDS
from app.core.records.field_policy import (
    normalize_field_key,
)
from app.core.records.normalizers import normalize_record_fields
from app.core.shared.coerce_primitives import (
    coerce_int as _coerce_int,
    object_dict as _object_dict,
    object_list as _object_list,
    safe_int as _safe_int,
)
from app.core.shared.text_coerce import (
    clean_text,
    coerce_literal_text_list,
    coerce_text,
    is_null_text,
    is_title_noise as is_title_noise,
    strip_html_tags as strip_html_tags,
    text_or_none,
)
from app.core.shared.field_coerce_price import (
    CURRENCY_CODE_PATTERN,
    CURRENCY_SYMBOL_PATTERN,
    PRICE_RE as PRICE_RE,
    decimal_for_shared_price,
    extract_currency_code as extract_currency_code,
    extract_price_text as extract_price_text,
)
from app.core.shared.field_coerce_text import (
    infer_brand_from_product_url as infer_brand_from_product_url,
    infer_brand_from_title_host as infer_brand_from_title_host,
    infer_brand_from_title_marker as infer_brand_from_title_marker,
)
from app.core.shared.field_coerce_url import (
    absolute_url as absolute_url,
    extract_urls as extract_urls,
    same_host as same_host,
    strip_record_tracking_params,
    strip_tracking_query_params as strip_tracking_query_params,
)
from app.core.shared.field_surface import (
    clean_record as clean_record,
    surface_fields as surface_fields,
)
from app.core.shared.regex_patterns import compile_regex_patterns

REVIEW_COUNT_RE = _REVIEW_COUNT_RE
_decimal_for_shared_price = decimal_for_shared_price

__all__ = (
    "IMAGE_FIELDS",
    "URL_FIELDS",
    "PRICE_RE",
    "absolute_url",
    "clean_text",
    "extract_price_text",
    "extract_urls",
    "infer_brand_from_product_url",
    "infer_brand_from_title_host",
    "infer_brand_from_title_marker",
    "is_title_noise",
    "sanitize_option_scalar",
    "same_host",
    "strip_html_tags",
    "strip_tracking_query_params",
    "variant_option_value_is_opaque_numeric",
)

_FIELD_ALIASES = FIELD_ALIASES
_OPTION_VALUE_SUFFIX_NOISE_RE = compile_regex_patterns(
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS or ()
)
_OPTION_VALUE_NOISE_WORD_PATTERN = "|".join(
    re.escape(str(word))
    for word in tuple(OPTION_VALUE_NOISE_WORDS or ())
    if str(word).strip()
)
_NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    normalize_field_key(str(key or ""))
    for key in tuple(NOISY_PRODUCT_ATTRIBUTE_KEYS or ())
    if str(key or "").strip()
)
_SMALL_NUMERIC_RE = re.compile(str(SMALL_NUMERIC_PATTERN), re.I)
_TRACKING_PIXEL_RE = re.compile(str(TRACKING_PIXEL_PATTERN), re.I)
_COLOR_KEYWORD_RE = re.compile(str(COLOR_KEYWORD_PATTERN), re.I)
_variant_color_codelike_token_re = re.compile(
    str(VARIANT_COLOR_CODELIKE_TOKEN_PATTERN), re.I
)
_SIZE_REJECT_TOKENS_NORMALIZED: frozenset[str] = frozenset(
    str(token).strip().lower()
    for token in tuple(SIZE_REJECT_TOKENS or ())
    if str(token).strip()
)


object_list = _object_list
object_dict = _object_dict
safe_int = _safe_int
coerce_int = _coerce_int


_AVAILABILITY_CANONICAL_ENUM = frozenset(
    str(v) for v in dict(AVAILABILITY_URL_MAP or {}).values() if v
)
_HTML_ENTITY_RE = re.compile(r"&(?:#\d+|#x[0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]+);")
_product_type_noise_tokens = frozenset(
    str(token).casefold()
    for token in tuple(PUBLIC_RECORD_PRODUCT_TYPE_NOISE_TOKENS or ())
)


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
        parsed, fallback = _parse_structured_scalar_text(value, keys=keys)
        if parsed is not None:
            return coerce_structured_scalar(parsed, keys=keys)
        if fallback is not None:
            return fallback
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


def _parse_structured_scalar_text(
    value: str,
    *,
    keys: tuple[str, ...],
) -> tuple[dict | list | None, str | None]:
    stripped = value.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None, None
    try:
        parsed = json.loads(stripped)
    except (TypeError, ValueError):
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError, TypeError):
            return None, _coerce_simple_string_dict_scalar(stripped, keys=keys)
    if isinstance(parsed, (dict, list)):
        return parsed, None
    return None, _coerce_simple_string_dict_scalar(stripped, keys=keys)


def _coerce_simple_string_dict_scalar(
    value: str,
    *,
    keys: tuple[str, ...],
) -> str | None:
    """Parse simple {'key': 'value'} scalars, returning None if malformed.

    This fallback naively splits on commas, so embedded comma values such as
    {'name': 'Foo, Inc'} are unsupported; prefer JSON when commas are possible.
    """
    body = value[1:-1].strip()
    if not body:
        return None
    for part in body.split(","):
        raw_key, separator, raw_value = part.partition(":")
        if not separator:
            return None
        key = _unquote_simple_string_dict_token(raw_key.strip())
        candidate = _unquote_simple_string_dict_token(raw_value.strip())
        if key in keys and candidate:
            return candidate
    return None


def _unquote_simple_string_dict_token(value: str) -> str | None:
    if len(value) < 2 or value[0] != value[-1] or value[0] not in {"'", '"'}:
        return None
    inner = value[1:-1].strip()
    if not inner or any(token in inner for token in "{}[]\r\n"):
        return None
    return inner


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


def _strip_color_value_code_pollution(value: str) -> str:
    if not value or not any(char.isdigit() for char in value):
        return value
    tokens = re.findall(r"[A-Za-z0-9]+", value)
    if len(tokens) < 2:
        return value
    color_indexes = [
        index
        for index, token in enumerate(tokens)
        if _COLOR_KEYWORD_RE.fullmatch(token)
    ]
    if not color_indexes:
        return value
    tail = tokens[color_indexes[-1] + 1 :]
    if not tail:
        return value
    if not all(
        token.isdigit() or _variant_color_codelike_token_re.fullmatch(token)
        for token in tail
    ):
        return value
    color_prefix = [
        token
        for token in tokens[: color_indexes[0]]
        if not _color_prefix_token_is_code_like(token)
    ]
    color_tokens = tokens[color_indexes[0] : color_indexes[-1] + 1]
    return clean_text(" ".join([*color_prefix, *color_tokens]))


def _color_prefix_token_is_code_like(token: str) -> bool:
    text = token.strip()
    return (
        1 < len(text) <= 3
        and not text.islower()
        and text.casefold() not in _SHORT_COLOR_ALLOWLIST
        and _COLOR_KEYWORD_RE.fullmatch(text) is None
    )


_SHORT_COLOR_ALLOWLIST = frozenset(
    {
        # short, real color words. Lower-case only is fine; real PDPs use
        # mixed-case rendering. Keep this list narrow — it only protects
        # genuinely human-readable short forms.
        "red",
        "tan",
        "navy",
        "blue",
        "pink",
        "gold",
        "lime",
        "teal",
        "gray",
        "grey",
        "black",
        "white",
        "green",
        "ivory",
        "khaki",
        "olive",
        "rose",
        "wine",
        "rust",
        "sand",
        "snow",
        "cyan",
        "plum",
        "ruby",
        "lilac",
        "coral",
        "azure",
        "beige",
        "amber",
        "denim",
        "ochre",
        "mocha",
        "mauve",
        "stone",
        "stoun",
    }
)


def variant_option_value_is_opaque_numeric(field_name: str, value: object) -> bool:
    text = coerce_text(value)
    if not (
        field_name in VARIANT_OPAQUE_NUMERIC_OPTION_AXES and text and text.isdigit()
    ):
        return False
    return (
        field_name == "color" or len(text) >= VARIANT_OPAQUE_NUMERIC_OPTION_MIN_DIGITS
    )


def sanitize_option_scalar(field_name: str, value: object) -> str | None:
    text = coerce_text(value)
    if not text:
        return None
    if text.lstrip().startswith(("{", "[")):
        return None
    cleaned = _clean_option_value(text) if field_name in OPTION_SCALAR_FIELDS else text
    if field_name in OPTION_SCALAR_FIELDS and _option_value_is_invalid(
        field_name, cleaned
    ):
        return None
    if field_name == "color":
        cleaned = _sanitize_color_option(cleaned)
    elif field_name == "size":
        cleaned = _sanitize_size_option(cleaned)
    elif field_name == WEIGHT_FIELD and re.fullmatch(r"\d+(?:\.\d+)?", cleaned):
        return None
    if not cleaned or is_null_text(cleaned):
        return None
    return cleaned


def _clean_option_value(value: str) -> str:
    cleaned = value
    for pattern in _OPTION_VALUE_SUFFIX_NOISE_RE:
        cleaned = clean_text(pattern.sub("", cleaned))
    cleaned = re.sub(rf"\s+(?:{CURRENCY_SYMBOL_PATTERN})\s*\d[\d.,]*.*$", "", cleaned)
    cleaned = re.sub(
        rf"\s+\d[\d.,]*\s*(?:{CURRENCY_CODE_PATTERN})\b.*$", "", cleaned, flags=re.I
    )
    if _OPTION_VALUE_NOISE_WORD_PATTERN:
        cleaned = re.sub(
            rf"\s+\b(?:{_OPTION_VALUE_NOISE_WORD_PATTERN})\b.*$",
            "",
            cleaned,
            flags=re.I,
        )
    return clean_text(cleaned)


def _option_value_is_invalid(field_name: str, value: str) -> bool:
    key = value.casefold()
    axis_aliases = {field_name.casefold()}
    if field_name == "color":
        axis_aliases.add("colour")
    return bool(
        key in axis_aliases
        or key in VARIANT_PLACEHOLDER_VALUES
        or key in VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS
        or any(key.startswith(prefix) for prefix in VARIANT_PLACEHOLDER_PREFIXES)
        or variant_option_value_is_opaque_numeric(field_name, value)
    )


def _sanitize_color_option(value: str) -> str:
    if _color_option_is_code(value):
        return ""
    folded = value.casefold()
    cleaned = (
        clean_text(value[len("select ") : -len(" color")])
        if folded.startswith("select ") and folded.endswith(" color")
        else value
    )
    cleaned = re.split(r"\bstyle\s*:", cleaned, maxsplit=1, flags=re.I)[0]
    if ":" in cleaned:
        _prefix, suffix = cleaned.rsplit(":", 1)
        if len(clean_text(suffix).split()) <= 4 and _COLOR_KEYWORD_RE.search(suffix):
            cleaned = suffix
    cleaned = re.sub(r"^color\s*:\s*", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\bcolor\s+details\b.*$", "", cleaned, flags=re.I).strip()
    cleaned = re.split(r"\bview as list\b", cleaned, maxsplit=1, flags=re.I)[0]
    cleaned = re.split(r"\bsize(?:\s*\([^)]*\))?\b", cleaned, maxsplit=1, flags=re.I)[0]
    cleaned = clean_text(_strip_color_value_code_pollution(cleaned))
    return "" if _contains_numeric_dimensions(cleaned) else cleaned


def _color_option_is_code(value: str) -> bool:
    return bool(
        _SMALL_NUMERIC_RE.fullmatch(value)
        or _TRACKING_PIXEL_RE.fullmatch(value)
        or (
            _variant_color_codelike_token_re.fullmatch(value)
            and _COLOR_KEYWORD_RE.search(value) is None
        )
        or _color_value_is_opaque_code(value)
    )


def _sanitize_size_option(value: str) -> str:
    cleaned = re.sub(r"^size\s*:\s*", "", value, flags=re.I)
    cleaned = re.split(r"\bview as list\b", cleaned, maxsplit=1, flags=re.I)[0]
    cleaned = _remove_size_chart_label(cleaned)
    cleaned = clean_text(cleaned)
    if re.search(r"\b(?:please\s+)?select(?:\s+size)?\b", cleaned, flags=re.I):
        return ""
    return "" if cleaned.casefold() in _SIZE_REJECT_TOKENS_NORMALIZED else cleaned


def _contains_numeric_dimensions(value: str) -> bool:
    for index, character in enumerate(value):
        if character.casefold() != "x":
            continue
        left = value[:index].rstrip()
        right = value[index + 1 :].lstrip()
        if left and right and left[-1].isdigit() and right[0].isdigit():
            return True
    return False


def _remove_size_chart_label(value: str) -> str:
    folded = value.casefold()
    start = folded.find("(size")
    while start >= 0:
        end = folded.find("chart)", start + len("(size"))
        if end < 0:
            break
        between = value[start + len("(size") : end]
        if all(character.isspace() or character in "_-" for character in between):
            trim_start = start
            while trim_start and value[trim_start - 1].isspace():
                trim_start -= 1
            value = value[:trim_start] + value[end + len("chart)") :]
            folded = value.casefold()
            start = folded.find("(size", trim_start)
            continue
        start = folded.find("(size", start + 1)
    return value


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


def coerce_availability_value(value: object) -> str | None:
    from app.core.shared.field_coerce_dispatch import (
        coerce_availability_value as _coerce_availability_value,
    )

    return _coerce_availability_value(value)


def coerce_field_value(field_name: str, value: object, page_url: str) -> object | None:
    from app.core.shared.field_coerce_dispatch import (
        coerce_field_value as _coerce_field_value,
    )

    return _coerce_field_value(field_name, value, page_url)


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
