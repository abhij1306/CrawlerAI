from __future__ import annotations

__all__ = (
    "variant_axis_allowed_single_tokens",
    "public_variant_axis_fields",
    "option_scalar_fields",
    "normalized_variant_axis_key",
    "normalized_variant_axis_display_name",
    "resolve_machine_variant_group_name",
    "resolve_visible_variant_group_name",
    "semantic_group_label_from_text",
    "variant_axis_name_is_semantic",
)

import re

from app.services.config.extraction_rules import (
    VARIANT_AXIS_ALIASES,
    VARIANT_AXIS_ALLOWED_SINGLE_TOKENS,
    VARIANT_AXIS_GENERIC_TOKENS,
    VARIANT_AXIS_LABEL_NOISE_PATTERNS,
    VARIANT_AXIS_LABEL_NOISE_TOKENS,
    VARIANT_AXIS_TECHNICAL_PATTERNS,
    VARIANT_COLOR_AXIS_TOKENS,
    VARIANT_SIZE_AXIS_TOKENS,
)
from app.services.config.variant_policy import OPTION_SCALAR_FIELDS, PUBLIC_VARIANT_AXIS_FIELDS
from app.services.shared.field_coerce import clean_text

_ALNUM_SPLIT_PATTERN = r"[^a-z0-9]+"

_variant_axis_label_noise_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_AXIS_LABEL_NOISE_TOKENS or ())
    if str(token).strip()
)
_variant_axis_label_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_AXIS_LABEL_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
_variant_axis_allowed_single_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_AXIS_ALLOWED_SINGLE_TOKENS or ())
    if str(token).strip()
)
variant_axis_allowed_single_tokens = _variant_axis_allowed_single_tokens
public_variant_axis_fields = frozenset(
    str(token).strip().lower()
    for token in tuple(PUBLIC_VARIANT_AXIS_FIELDS or ())
    if str(token).strip()
)
option_scalar_fields = frozenset(
    str(token).strip().lower()
    for token in tuple(OPTION_SCALAR_FIELDS or ())
    if str(token).strip()
)
_variant_axis_generic_tokens = frozenset(
    str(token).strip().lower()
    for token in tuple(VARIANT_AXIS_GENERIC_TOKENS or ())
    if str(token).strip()
)
_variant_axis_technical_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_AXIS_TECHNICAL_PATTERNS or ())
    if str(pattern).strip()
)


def _variant_axis_label_is_noise(value: object) -> bool:
    lowered = clean_text(value).lower()
    if not lowered:
        return False
    tokens = [token for token in re.split(_ALNUM_SPLIT_PATTERN, lowered) if token]
    if any(token in _variant_axis_label_noise_tokens for token in tokens):
        return True
    return any(
        pattern.search(lowered) for pattern in _variant_axis_label_noise_patterns
    )


def normalized_variant_axis_key(value: object) -> str:
    text = str(value or "").strip().lower().replace("&", " ")
    if not text:
        return ""
    text = re.sub(_ALNUM_SPLIT_PATTERN, "_", text).strip("_")
    aliases = VARIANT_AXIS_ALIASES if isinstance(VARIANT_AXIS_ALIASES, dict) else {}
    normalized = str(aliases.get(text) or text)
    tokens = [token for token in normalized.split("_") if token]
    semantic_tokens = [
        token for token in tokens if token in _variant_axis_allowed_single_tokens
    ]
    if len(semantic_tokens) == 1 and all(
        token == semantic_tokens[0]
        or token in _variant_axis_generic_tokens
        or token.isdigit()
        or len(token) <= 3
        for token in tokens
    ):
        return semantic_tokens[0]
    return normalized


def normalized_variant_axis_display_name(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    axis_key = normalized_variant_axis_key(cleaned)
    if not axis_key:
        return cleaned
    lowered = cleaned.lower().replace("&", " ")
    tokens = [token for token in re.split(_ALNUM_SPLIT_PATTERN, lowered) if token]
    if not tokens:
        return cleaned
    if len(tokens) == 1 and tokens[0] == axis_key:
        return cleaned
    if axis_key not in _variant_axis_allowed_single_tokens:
        return cleaned
    extra_tokens = [token for token in tokens if token != axis_key]
    if extra_tokens and all(
        token in _variant_axis_generic_tokens or token.isdigit() or len(token) <= 3
        for token in extra_tokens
    ):
        return axis_key
    return cleaned


def _normalized_group_label_candidates(value: object) -> list[str]:
    cleaned = clean_text(str(value).replace("_", " ").replace("-", " "))
    if not cleaned:
        return []
    candidates = [cleaned]
    if ":" in cleaned:
        trailing = clean_text(cleaned.rsplit(":", 1)[-1])
        if trailing:
            candidates.insert(0, trailing)
    deduped: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        lowered = candidate.casefold()
        if not candidate or lowered in seen:
            continue
        seen.add(lowered)
        deduped.append(candidate)
    return deduped


def _resolve_visible_variant_group_name(value: object) -> str:
    for candidate in _normalized_group_label_candidates(value):
        if _variant_axis_label_is_noise(candidate):
            continue
        if variant_axis_name_is_semantic(candidate):
            normalized_name = normalized_variant_axis_key(candidate)
            tokens = [
                token
                for token in re.split(_ALNUM_SPLIT_PATTERN, candidate.lower())
                if token
            ]
            if normalized_name in _variant_axis_allowed_single_tokens and any(
                token.isdigit() or token in _variant_axis_generic_tokens
                for token in tokens
            ):
                return normalized_name
            return candidate
        resolved_name = _resolve_machine_variant_group_name(candidate)
        if resolved_name:
            return resolved_name
    return ""


def _resolve_machine_variant_group_name(value: object) -> str:
    cleaned = clean_text(str(value).replace("_", " ").replace("-", " "))
    if not cleaned or not variant_axis_name_is_semantic(cleaned):
        return ""
    normalized = normalized_variant_axis_key(cleaned)
    if not normalized:
        return ""
    normalized_tokens = [token for token in normalized.split("_") if token]
    if not normalized_tokens:
        return ""
    if normalized in _variant_axis_allowed_single_tokens:
        return normalized
    if all(
        token in _variant_axis_allowed_single_tokens
        or token in _variant_axis_generic_tokens
        or token.isdigit()
        for token in normalized_tokens
    ):
        return normalized
    return ""


def _semantic_group_label_from_text(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    lowered = cleaned.lower()
    lowered_tokens = frozenset(
        token for token in re.split(_ALNUM_SPLIT_PATTERN, lowered) if token
    )
    if VARIANT_COLOR_AXIS_TOKENS & lowered_tokens:
        return "color"
    if VARIANT_SIZE_AXIS_TOKENS & lowered_tokens:
        return "size"
    candidates = [
        cleaned,
        clean_text(cleaned.split(":", 1)[0]),
        clean_text(cleaned.split("(", 1)[0]),
    ]
    for candidate in candidates:
        normalized = normalized_variant_axis_key(candidate)
        if normalized in _variant_axis_allowed_single_tokens:
            return normalized
    return ""


resolve_machine_variant_group_name = _resolve_machine_variant_group_name
resolve_visible_variant_group_name = _resolve_visible_variant_group_name
semantic_group_label_from_text = _semantic_group_label_from_text


def variant_axis_name_is_semantic(value: object) -> bool:
    cleaned = clean_text(value)
    lowered = cleaned.lower()
    if not lowered:
        return False
    if _variant_axis_label_is_noise(cleaned):
        return False
    if any(pattern.fullmatch(lowered) for pattern in _variant_axis_technical_patterns):
        return False
    if (
        re.fullmatch(r"[a-z0-9]+", lowered)
        and lowered in _variant_axis_allowed_single_tokens
    ):
        return True
    tokens = [token for token in re.split(_ALNUM_SPLIT_PATTERN, lowered) if token]
    if not tokens or len(tokens) > 4:
        return False
    if any(token in _variant_axis_label_noise_tokens for token in tokens):
        return False
    axis_key = normalized_variant_axis_key(cleaned)
    if not axis_key or len(axis_key) > 32:
        return False
    axis_tokens = [token for token in axis_key.split("_") if token]
    if not axis_tokens:
        return False
    if any(pattern.fullmatch(axis_key) for pattern in _variant_axis_technical_patterns):
        return False
    if any(token in _variant_axis_allowed_single_tokens for token in axis_tokens):
        return True
    non_generic_tokens = [
        token
        for token in axis_tokens
        if token not in _variant_axis_generic_tokens and not token.isdigit()
    ]
    if not non_generic_tokens:
        return False
    return True
