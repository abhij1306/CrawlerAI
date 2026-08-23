from __future__ import annotations

import ast
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.config.extraction_rules import (
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
    REMOTE_BOOLEAN_FALSE_TOKENS,
    REMOTE_BOOLEAN_TRUE_TOKENS,
    normalize_availability_value as normalize_config_availability_value,
)
from app.core.config.field_mappings import (
    NORMALIZER_BOOLEAN_FIELDS,
    NORMALIZER_DECIMAL_FIELDS,
    NORMALIZER_INTEGER_FIELDS,
    NORMALIZER_LIST_TEXT_FIELDS,
)
from app.core.config.locale_format_rules import PRICE_CONTEXT_TOKENS

_NUMERIC_TEXT_RE = re.compile(r"[-+−]?\d[\d.,]*")
_UNICODE_MINUS_CHARS = "\u2212"
_CURRENCY_CODE_CONTEXT_PATTERN = (
    "|".join(
        re.escape(code.lower())
        for code in tuple(CURRENCY_CODES or ())
        # Exclude "rs": common substring false positive; "rs.?" is handled as rupee context.
        if isinstance(code, str) and code.strip().lower() != "rs"
    )
    or r"(?!)"
)
_CURRENCY_CODE_TOKENS = frozenset(
    str(code).strip().casefold() for code in CURRENCY_CODES if str(code).strip()
)
def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _normalize_text_list(value: object) -> object:
    if isinstance(value, str):
        return _normalize_text(value)
    if not isinstance(value, (list, tuple, set)):
        return _normalize_text(value)
    rows: list[str] = []
    seen: set[str] = set()
    for part in value:
        cleaned = _normalize_text(part)
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        rows.append(cleaned)
    return rows


_NORMALIZED_BOOLEAN_TRUE = frozenset(REMOTE_BOOLEAN_TRUE_TOKENS or ())
_NORMALIZED_BOOLEAN_FALSE = frozenset(REMOTE_BOOLEAN_FALSE_TOKENS or ())


def _normalize_bool(value: object) -> bool | str:
    if isinstance(value, bool):
        return value
    text = _normalize_text(value).lower()
    if text in _NORMALIZED_BOOLEAN_TRUE:
        return True
    if text in _NORMALIZED_BOOLEAN_FALSE:
        return False
    return _normalize_text(value)


def normalize_decimal_price(
    value: object,
    *,
    interpret_integral_as_cents: bool = False,
) -> str | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, (list, tuple, set)):
        return None
    if isinstance(value, dict):
        val = _decimal_mapping_scalar(value)
        if val is not None:
            return normalize_decimal_price(
                val, interpret_integral_as_cents=interpret_integral_as_cents
            )
        return None
    text = _admitted_price_text(value)
    if text is None:
        return None
    match = _NUMERIC_TEXT_RE.search(text)
    if match is None:
        return None
    candidate = _canonicalize_decimal_candidate(match.group(0))
    if candidate is None:
        return None
    try:
        decimal = Decimal(candidate)
    except (InvalidOperation, ValueError):
        return None
    if decimal < 0:
        return None
    digit_count = sum(1 for char in candidate if char.isdigit())
    if all((interpret_integral_as_cents, "." not in candidate, digit_count >= 3)):
        decimal = decimal / Decimal("100")
    return format(decimal, "f")


def _admitted_price_text(value: object) -> str | None:
    text = _normalize_text(value)
    if not text:
        return None
    negative_patterns = (
        rf"^[-−]\s*(?:[$€£¥₹]|rs\.?|\b(?:{_CURRENCY_CODE_CONTEXT_PATTERN}))?\s*\d",
        rf"^(?:[$€£¥₹]|rs\.?|\b(?:{_CURRENCY_CODE_CONTEXT_PATTERN})\b)\s*[-−]\s*\d",
    )
    if any(re.match(pattern, text, re.I) for pattern in negative_patterns):
        return None
    if not isinstance(value, str):
        return text
    stripped = _canonicalize_decimal_candidate(text)
    if stripped is None:
        return None
    digit_count = sum(char.isdigit() for char in stripped)
    short_integral = "." not in stripped and digit_count <= 3
    plain_numeric = _NUMERIC_TEXT_RE.fullmatch(text) is not None
    if short_integral and not plain_numeric and not _has_price_context(text):
        return None
    return text


def _has_price_context(text: str) -> bool:
    words = frozenset(re.findall(r"[a-z]+", text.casefold()))
    return bool(
        any(symbol in text for symbol in CURRENCY_SYMBOL_MAP)
        or not words.isdisjoint(_CURRENCY_CODE_TOKENS)
        or not words.isdisjoint(PRICE_CONTEXT_TOKENS)
    )


def _decimal_mapping_scalar(value: dict[object, object]) -> object | None:
    for key in (
        "value",
        "amount",
        "price",
        "standard_price",
        "list_price",
        "listPrice",
    ):
        if key in value:
            candidate = value[key]
            return (
                None if isinstance(candidate, (dict, list, tuple, set)) else candidate
            )
    return None


def _canonicalize_decimal_candidate(value: str) -> str | None:
    text = _normalize_text(value).translate(str.maketrans(_UNICODE_MINUS_CHARS, "-"))
    if not text:
        return None
    match = _NUMERIC_TEXT_RE.search(text)
    if match is None:
        return None
    candidate = match.group(0)
    if all(("," in candidate, "." in candidate)):
        if candidate.rfind(",") > candidate.rfind("."):
            return candidate.replace(".", "").replace(",", ".")
        return candidate.replace(",", "")
    if "," in candidate:
        head, tail = candidate.rsplit(",", 1)
        if tail.isdigit() and len(tail) in {1, 2} and re.search(r"\d", head):
            return head.replace(",", "").replace(".", "") + "." + tail
        return candidate.replace(",", "")
    if "." in candidate:
        parts = candidate.split(".")
        if len(parts) > 1 and all(part.isdigit() for part in parts):
            if all(len(part) == 3 for part in parts[1:]):
                return "".join(parts)
    return candidate


def _normalize_int(value: object) -> int | str:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    text = _normalize_text(value)
    if not text:
        return ""
    match = _NUMERIC_TEXT_RE.search(text.replace(",", ""))
    if match is None:
        return ""
    try:
        return int(
            Decimal(match.group(0).translate(str.maketrans(_UNICODE_MINUS_CHARS, "-")))
        )
    except (InvalidOperation, ValueError):
        return ""


def _normalize_availability(value: object) -> str:
    return normalize_config_availability_value(value)


def normalize_value(field_name: str, value: object) -> object:
    normalized_field = str(field_name or "").strip().lower()
    if value is None:
        return None
    if normalized_field == "barcode" and isinstance(value, str):
        parsed = _unwrap_singleton_literal_list(value)
        if parsed is not None:
            value = parsed
    if normalized_field in NORMALIZER_LIST_TEXT_FIELDS:
        return _normalize_text_list(value)
    if normalized_field in NORMALIZER_BOOLEAN_FIELDS:
        return _normalize_bool(value)
    if normalized_field == "availability":
        return _normalize_availability(value)
    if normalized_field == "rating":
        result = normalize_decimal_price(value)
        return _normalize_rating(result) if result is not None else ""
    if normalized_field in NORMALIZER_DECIMAL_FIELDS:
        return _normalize_decimal_field(value)
    if any(
        (
            normalized_field.endswith("_count"),
            normalized_field in NORMALIZER_INTEGER_FIELDS,
        )
    ):
        return _normalize_int(value)
    return _normalize_untyped_value(normalized_field, value)


def _normalize_untyped_value(field_name: str, value: object) -> object:
    if isinstance(value, str):
        return _normalize_text(value)
    if isinstance(value, list):
        return [
            normalize_value(field_name, item)
            for item in value
            if item not in (None, "", [], {})
        ]
    if isinstance(value, dict):
        return {
            str(key): normalize_value(str(key), item)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    if isinstance(value, (bool, int, float)):
        return value
    return _normalize_text(value)


def _normalize_decimal_field(value: object) -> str:
    if isinstance(value, str):
        trimmed = value.strip()
        if re.fullmatch(r"[-+]?\d+(?:\.\d+)?", trimmed):
            candidate = _canonicalize_decimal_candidate(trimmed)
            if candidate is None:
                return ""
            try:
                decimal = Decimal(candidate)
            except (InvalidOperation, ValueError):
                return ""
            return "" if decimal < 0 else format(decimal, "f")
    result = normalize_decimal_price(value)
    return result if result is not None else ""


def _unwrap_singleton_literal_list(value: str) -> str | None:
    text = _normalize_text(value)
    if not text.startswith("[") or not text.endswith("]"):
        return None
    try:
        parsed = ast.literal_eval(text)
    except (SyntaxError, ValueError):
        return None
    if not isinstance(parsed, (list, tuple)) or len(parsed) != 1:
        return None
    return _normalize_text(parsed[0])


def _normalize_rating(value: str) -> float | str:
    text = _normalize_text(value)
    if not text:
        return ""
    try:
        decimal = Decimal(text)
    except (InvalidOperation, ValueError):
        return text
    quantized = decimal.quantize(Decimal("0.01"))
    normalized = float(quantized)
    return normalized


def normalize_record_fields(record: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): (
            value if str(key).startswith("_") else normalize_value(str(key), value)
        )
        for key, value in dict(record or {}).items()
        if value not in (None, "", [], {})
    }
