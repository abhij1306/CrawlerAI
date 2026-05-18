from __future__ import annotations

__all__ = (
    "variant_size_value_patterns",
    "variant_option_value_suffix_noise_patterns",
    "variant_option_value_matches_ui_noise",
    "variant_option_value_matches_noise_token",
    "variant_option_value_is_noise",
    "is_sequential_integer_run",
    "select_option_texts_from_node",
    "select_option_values_are_noise",
    "value_looks_like_color",
)

import re
from typing import Any

from app.services.config.extraction_rules import (
    DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS,
    VARIANT_COLOR_HINT_WORDS,
    VARIANT_OPTION_NOISE_PHRASES,
    VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS,
    VARIANT_OPTION_VALUE_NOISE_PATTERNS,
    VARIANT_OPTION_VALUE_NOISE_TOKENS,
    VARIANT_OPTION_VALUE_UI_NOISE_PHRASES,
    VARIANT_PROMO_NOISE_TOKENS,
    VARIANT_SELECT_OPTION_SCAN_LIMIT,
    VARIANT_SEQUENTIAL_INTEGER_MIN_RUN,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_SIZE_VALUE_PATTERNS,
    VARIANT_UI_NOISE_EXACT_MATCH_MAX_LENGTH,
)
from app.services.config.variant_migration_rules import (
    VARIANT_OPTION_VALUE_NOISE_FULLMATCH_PATTERNS_EXTRA,
    VARIANT_OPTION_VALUE_UI_NOISE_PHRASES_EXTRA,
)
from app.services.shared.field_coerce import clean_text

_ALNUM_SPLIT_PATTERN = r"[^a-z0-9]+"

_variant_color_hint_words = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_COLOR_HINT_WORDS or ())
    if str(token).strip()
)
_variant_option_value_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_OPTION_VALUE_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_promo_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_PROMO_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_artifact_value_tokens = frozenset(
    compact
    for token in tuple(DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS or ())
    if (
        compact := re.sub(
            r"[^a-z0-9%#]+", "", str(token).strip().lower()
        )
    )
)
_variant_option_value_ui_noise_phrases = tuple(
    cleaned.casefold()
    for token in (
        *tuple(VARIANT_OPTION_VALUE_UI_NOISE_PHRASES or ()),
        *tuple(VARIANT_OPTION_VALUE_UI_NOISE_PHRASES_EXTRA or ()),
    )
    if (cleaned := clean_text(token))
)
_variant_option_noise_phrases = tuple(
    cleaned.casefold()
    for token in tuple(VARIANT_OPTION_NOISE_PHRASES or ())
    if (cleaned := clean_text(token))
)
_variant_option_value_exact_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_OPTION_VALUE_EXACT_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_option_value_noise_patterns = VARIANT_OPTION_VALUE_NOISE_PATTERNS or {}
variant_size_value_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SIZE_VALUE_PATTERNS or ())
    if str(pattern).strip()
)
variant_option_value_suffix_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_option_value_noise_fullmatch_regexes = tuple(
    re.compile(str(pattern), re.I)
    for pattern in (
        *tuple(_variant_option_value_noise_patterns.get("fullmatch") or ()),
        *tuple(VARIANT_OPTION_VALUE_NOISE_FULLMATCH_PATTERNS_EXTRA or ()),
    )
    if str(pattern).strip()
)
_variant_option_value_noise_search_regexes = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(_variant_option_value_noise_patterns.get("search") or ())
    if str(pattern).strip()
)


def _is_sequential_integer_run(
    values: list[str],
    *,
    min_length: int = int(VARIANT_SEQUENTIAL_INTEGER_MIN_RUN),
) -> bool:
    """Return True for contiguous integer runs, which signal quantity selectors."""
    if min_length <= 0:
        raise ValueError("min_length must be positive")
    if len(values) < min_length:
        return False
    ints: list[int] = []
    for value in values:
        stripped = value.strip()
        if not stripped.isdigit():
            return False
        ints.append(int(stripped))
    ints.sort()
    return ints[-1] - ints[0] == len(ints) - 1


def variant_option_value_matches_ui_noise(value: object) -> bool:
    """Return True for UI-control phrases. Blank values are not noise here."""
    lowered = clean_text(value).casefold()
    if not lowered:
        return False
    if any(
        rx.fullmatch(lowered) for rx in _variant_option_value_noise_fullmatch_regexes
    ):
        return True
    try:
        max_len = int(VARIANT_UI_NOISE_EXACT_MATCH_MAX_LENGTH)
    except (TypeError, ValueError):
        max_len = 8
    for phrase in _variant_option_value_ui_noise_phrases:
        if " " not in phrase:
            if lowered == phrase:
                return True
            continue
        if len(phrase) <= max_len and lowered == phrase:
            return True
        if len(phrase) <= max_len:
            continue
        if phrase in lowered:
            return True
    return False


def variant_option_value_matches_noise_token(value: object) -> bool:
    cleaned = clean_text(value)
    return bool(cleaned) and cleaned.casefold() in _variant_option_value_noise_tokens


def variant_option_value_is_noise(value: object) -> bool:
    cleaned = clean_text(value)
    if not cleaned:
        return True
    lowered = cleaned.casefold()
    compact = re.sub(r"[^a-z0-9%#]+", "", lowered)
    return (
        compact in _variant_option_value_noise_tokens
        or compact in _variant_artifact_value_tokens
        or re.fullmatch(r"#[0-9a-f]{3}(?:[0-9a-f]{3})?", compact) is not None
        or (
            "%" in lowered
            and any(token in lowered for token in _variant_promo_noise_tokens)
        )
        or lowered in _variant_option_value_exact_noise_tokens
        or variant_option_value_matches_ui_noise(cleaned)
        or any(phrase in lowered for phrase in _variant_option_noise_phrases)
        or any(
            rx.search(lowered) for rx in _variant_option_value_noise_search_regexes
        )
    )


def _select_option_texts_from_node(node: Any) -> list[str]:
    if not hasattr(node, "select"):
        return []
    values: list[str] = []
    for option in node.select("option")[: int(VARIANT_SELECT_OPTION_SCAN_LIMIT)]:
        text = (
            clean_text(option.get_text(" ", strip=True))
            if hasattr(option, "get_text")
            else ""
        )
        if text:
            values.append(text)
    return values


def _select_option_values_are_noise(node: Any) -> bool:
    values = _select_option_texts_from_node(node)
    if not values:
        return False
    if _is_sequential_integer_run(values):
        return True
    normalized = {
        re.sub(_ALNUM_SPLIT_PATTERN, "", value.lower()) for value in values if value.strip()
    }
    return bool(normalized) and normalized <= _variant_option_value_noise_tokens


def _value_looks_like_color(value: object) -> bool:
    tokens = [
        token
        for token in re.split(_ALNUM_SPLIT_PATTERN, clean_text(value).lower())
        if token and not token.isdigit()
    ]
    if not tokens:
        return False
    return any(token in _variant_color_hint_words for token in tokens)


is_sequential_integer_run = _is_sequential_integer_run
select_option_texts_from_node = _select_option_texts_from_node
select_option_values_are_noise = _select_option_values_are_noise
value_looks_like_color = _value_looks_like_color
