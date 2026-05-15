"""Price and currency coercion helpers for public field shaping."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from app.services.config.extraction_rules import (
    CURRENCY_ALIAS_PATTERNS,
    CURRENCY_CODES,
    CURRENCY_SYMBOL_MAP,
)
from app.services.config.field_mappings import PRICE_DICT_PREFERRED_KEYS
from app.services.shared.text_coerce import clean_text, coerce_text, text_or_none

CURRENCY_SYMBOL_PATTERN = (
    "|".join(
        re.escape(symbol)
        for symbol in sorted(
            (str(symbol) for symbol in dict(CURRENCY_SYMBOL_MAP or {}).keys() if symbol),
            key=len,
            reverse=True,
        )
    )
    or r"(?!)"
)
CURRENCY_CODE_PATTERN = (
    "|".join(
        re.escape(code)
        for code in sorted(
            (
                code
                for code in tuple(CURRENCY_CODES or ())
                if isinstance(code, str) and len(code) == 3
            ),
            key=len,
            reverse=True,
        )
    )
    or r"(?!)"
)
PRICE_RE = re.compile(
    rf"(?:(?:{CURRENCY_SYMBOL_PATTERN})\s*\d[\d.,]*|\d[\d.,]*\s*(?:{CURRENCY_SYMBOL_PATTERN}))"
)
_CODED_PRICE_RE = re.compile(
    rf"(?:(?:\b(?:{CURRENCY_CODE_PATTERN})\b)\s*\d[\d.,]*|\d[\d.,]*\s*(?:\b(?:{CURRENCY_CODE_PATTERN})\b))"
)
_UNMARKED_PRICE_RE = re.compile(r"\d[\d.,]*")
_CURRENCY_CODE_RE = re.compile(rf"\b({CURRENCY_CODE_PATTERN})\b")


def extract_price_text(
    value: object,
    *,
    prefer_last: bool = True,
    allow_unmarked: bool = False,
) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    matches = list(PRICE_RE.finditer(text))
    if not matches:
        matches = list(_CODED_PRICE_RE.finditer(text.upper()))
    if not matches and allow_unmarked:
        matches = list(_UNMARKED_PRICE_RE.finditer(text))
    if not matches:
        return None
    match = matches[-1] if prefer_last else matches[0]
    return clean_text(match.group(0))


def price_text_is_negative(value: object) -> bool:
    text = clean_text(value)
    if not text:
        return False
    marker = rf"(?:{CURRENCY_SYMBOL_PATTERN}|\b(?:{CURRENCY_CODE_PATTERN})\b)?"
    return re.match(rf"^\s*-\s*{marker}\s*\d", text, re.I) is not None


def _price_candidate_has_money_signal(value: str) -> bool:
    text = clean_text(value)
    return (
        "." in text
        or "," in text
        or extract_currency_code(text) is not None
        or PRICE_RE.search(text) is not None
        or _CODED_PRICE_RE.search(text.upper()) is not None
    )


def coerce_price_from_dict(value: dict[str, object]) -> str | None:
    fallback: str | None = None
    for key in PRICE_DICT_PREFERRED_KEYS:
        candidate = value.get(key)
        if candidate in (None, "", [], {}):
            continue
        text = coerce_text(candidate)
        if not text or price_text_is_negative(text):
            continue
        if fallback is None:
            fallback = text
        if _price_candidate_has_money_signal(text):
            return text
    return fallback


def extract_currency_code(value: object) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    for pattern, code in dict(CURRENCY_ALIAS_PATTERNS or {}).items():
        if re.search(str(pattern), text, flags=re.I):
            return str(code)
    for symbol, code in dict(CURRENCY_SYMBOL_MAP or {}).items():
        if str(symbol) in text:
            return str(code)
    code_match = _CURRENCY_CODE_RE.search(text.upper())
    if code_match:
        return code_match.group(1)
    return None


def decimal_for_shared_price(value: object) -> Decimal | None:
    text = text_or_none(value)
    if not text:
        return None
    normalized = _normalize_shared_price_decimal_text(text)
    if not normalized:
        return None
    try:
        return Decimal(normalized).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None


def _normalize_shared_price_decimal_text(value: str) -> str:
    stripped = re.sub(r"[^\d,.\-]+", "", str(value or "").strip())
    if not stripped:
        return ""
    if "." in stripped and "," in stripped:
        if stripped.rfind(",") > stripped.rfind("."):
            return stripped.replace(".", "").replace(",", ".")
        return stripped.replace(",", "")
    if "," in stripped:
        if "." not in stripped and stripped.count(",") > 1:
            return stripped.replace(",", "")
        head, _, tail = stripped.rpartition(",")
        if head and tail.isdigit() and len(tail) == 3 and "," not in head:
            return f"{head}{tail}"
        return stripped.replace(",", ".")
    if "." not in stripped:
        return stripped
    parts = stripped.split(".")
    if len(parts) == 2:
        return stripped
    return "".join(parts[:-1]) + f".{parts[-1]}"
