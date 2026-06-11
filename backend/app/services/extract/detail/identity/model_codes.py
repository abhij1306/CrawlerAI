from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    DETAIL_MODEL_NUMBER_TOKEN_PATTERNS,
    DETAIL_MODEL_SMALL_NUMERIC_TOKEN_PATTERN,
)
from app.services.shared.field_coerce import clean_text

__all__ = (
    "detail_model_number_sets_compatible",
    "detail_model_number_tokens",
    "detail_small_numeric_model_tokens",
    "normalized_model_token",
)


def detail_model_number_sets_compatible(
    requested_numbers: set[str],
    candidate_numbers: set[str],
) -> bool:
    for requested in requested_numbers:
        for candidate in candidate_numbers:
            if requested == candidate:
                return True
            shorter, longer = sorted((requested, candidate), key=len)
            if (
                len(shorter) >= 5
                and len(longer) - len(shorter) <= 2
                and longer.startswith(shorter)
                and any(char.isalpha() for char in shorter)
            ):
                return True
    return False


def detail_model_number_tokens(value: object) -> set[str]:
    tokens: set[str] = set()
    text = clean_text(value)
    for pattern in tuple(DETAIL_MODEL_NUMBER_TOKEN_PATTERNS or ()):
        if not str(pattern).strip():
            continue
        for match in re.findall(str(pattern), text):
            raw_token = match[0] if isinstance(match, tuple) else match
            normalized = normalized_model_token(raw_token)
            if normalized:
                tokens.add(normalized)
    return tokens


def detail_small_numeric_model_tokens(value: object) -> set[str]:
    pattern = str(DETAIL_MODEL_SMALL_NUMERIC_TOKEN_PATTERN or "").strip()
    if not pattern:
        return set()
    return {
        token.lstrip("0") or "0"
        for token in re.findall(pattern, clean_text(value))
    }


def normalized_model_token(value: object) -> str:
    normalized = re.sub(r"[^A-Za-z0-9]+", "", str(value or "")).lower()
    if not normalized:
        return ""
    if normalized.isdigit():
        return normalized.lstrip("0") or "0"
    return normalized
