from __future__ import annotations

import logging
import re
from typing import Any

from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
    ADULT_SIZE_CONTEXT_TOKENS,
    COMMON_WORD_SIZE_VALUES,
    GENDER_ARTIFACT_PATTERN,
    GENDER_KEYWORD_TOKENS,
    VARIANT_CHILD_SIZE_PATTERNS,
    VARIANT_COLOR_HINT_WORDS,
    VARIANT_CONDITION_HEADER_PREFIXES,
    VARIANT_OPTION_LABEL_MAX_WORDS,
    VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS,
    VARIANT_PLACEHOLDER_PREFIXES,
    VARIANT_PLACEHOLDER_VALUES,
    VARIANT_SIZE_QUANTITY_CONTROL_VALUES,
    VARIANT_SIZE_VALUE_EXTRACT_PATTERNS,
    VARIANT_SIZE_VALUE_PATTERNS,
    STANDARD_SIZE_VALUES,
    VARIANT_TITLE_STOPWORDS,
)
from app.services.extract.variant_axis import normalized_variant_axis_key
from app.services.extract.variant_option_value import variant_option_value_is_noise
from app.services.extract.variant_value_guards import (
    variant_axis_value_exceeds_word_limit,
)
from app.services.shared.field_coerce import clean_text

logger = logging.getLogger(__name__)

__all__ = (
    "_normalize_variant_axis_value",
    "_extract_size_value",
    "_size_value_is_recognized",
    "_size_value_is_child_specific",
    "_record_targets_adult_sizes",
    "_variant_color_from_title_or_url",
    "_extract_color_value",
)

def _safe_compile_patterns(name: str, patterns: object) -> tuple[re.Pattern[str], ...]:
    compiled: list[re.Pattern[str]] = []
    for pattern in tuple(patterns or ()):
        text = str(pattern).strip()
        if not text:
            continue
        try:
            compiled.append(re.compile(text, re.I))
        except re.error:
            logger.warning(
                "Skipping invalid variant regex pattern",
                extra={"name": name, "pattern": text},
            )
    return tuple(compiled)


variant_size_value_extract_patterns = _safe_compile_patterns(
    "VARIANT_SIZE_VALUE_EXTRACT_PATTERNS",
    VARIANT_SIZE_VALUE_EXTRACT_PATTERNS,
)
variant_size_value_patterns = _safe_compile_patterns(
    "VARIANT_SIZE_VALUE_PATTERNS",
    VARIANT_SIZE_VALUE_PATTERNS,
)
variant_color_hint_words = frozenset(
    clean_text(value).lower()
    for value in tuple(VARIANT_COLOR_HINT_WORDS or ())
    if clean_text(value)
)
variant_option_value_suffix_noise_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS or ())
    if str(pattern).strip()
)
variant_placeholder_values = frozenset(
    clean_text(value).lower()
    for value in tuple(VARIANT_PLACEHOLDER_VALUES or ())
    if clean_text(value)
)
variant_placeholder_prefixes = tuple(
    clean_text(prefix).lower()
    for prefix in tuple(VARIANT_PLACEHOLDER_PREFIXES or ())
    if clean_text(prefix)
)
variant_size_quantity_control_values = frozenset(
    clean_text(value).lower()
    for value in tuple(VARIANT_SIZE_QUANTITY_CONTROL_VALUES or ())
    if clean_text(value)
)
try:
    variant_option_label_max_words = max(1, int(VARIANT_OPTION_LABEL_MAX_WORDS))
except (TypeError, ValueError):
    variant_option_label_max_words = 6
gender_artifact_pattern = str(GENDER_ARTIFACT_PATTERN or "")
_gender_artifact_patterns: dict[str, re.Pattern[str]] = {}
standard_size_values = frozenset(
    str(value).lower() for value in tuple(STANDARD_SIZE_VALUES or ())
)
common_word_size_values = frozenset(
    clean_text(value).lower()
    for value in tuple(COMMON_WORD_SIZE_VALUES or ())
    if clean_text(value)
)
variant_title_stopwords = frozenset(
    clean_text(token).lower()
    for token in tuple(VARIANT_TITLE_STOPWORDS or ())
    if clean_text(token)
)
gender_keyword_tokens = frozenset(
    clean_text(token).lower()
    for token in tuple(GENDER_KEYWORD_TOKENS or ())
    if clean_text(token)
)
adult_size_context_tokens = frozenset(
    clean_text(token).lower()
    for token in tuple(ADULT_SIZE_CONTEXT_TOKENS or ())
    if clean_text(token)
)
variant_child_size_patterns = tuple(
    re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_CHILD_SIZE_PATTERNS or ())
    if str(pattern).strip()
)
variant_condition_header_prefixes = frozenset(
    clean_text(token).lower()
    for token in tuple(VARIANT_CONDITION_HEADER_PREFIXES or ())
    if clean_text(token)
)


def _normalize_variant_axis_value(field_name: str, value: object) -> str:
    cleaned = _strip_variant_option_suffix_noise(value)
    if not cleaned:
        return ""
    if variant_axis_value_exceeds_word_limit(
        normalized_variant_axis_key(field_name),
        cleaned,
        max_words=variant_option_label_max_words,
        color_extractor=_extract_color_value,
    ):
        return ""
    if (
        _value_is_placeholder(cleaned)
        or _value_is_ui_noise(cleaned)
        or _value_is_axis_header_noise(field_name, cleaned)
        or _variant_axis_value_is_header(field_name, cleaned)
    ):
        return ""
    return cleaned


def _variant_size_axis_value_is_quantity_control(
    field_name: str,
    value: object,
) -> bool:
    return (
        normalized_variant_axis_key(field_name) == "size"
        and clean_text(value).lower() in variant_size_quantity_control_values
    )


def _strip_variant_option_suffix_noise(value: object) -> str:
    cleaned = clean_text(value)
    if not cleaned:
        return ""
    stripped = cleaned
    for pattern in variant_option_value_suffix_noise_patterns:
        stripped = clean_text(pattern.sub("", stripped))
    return stripped or cleaned


def _value_is_placeholder(value: str) -> bool:
    lowered = clean_text(value).lower()
    if not lowered:
        return True
    return lowered in variant_placeholder_values or any(
        lowered.startswith(prefix) for prefix in variant_placeholder_prefixes
    )


def _value_is_ui_noise(value: str) -> bool:
    return variant_option_value_is_noise(value)


def _extract_size_value(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    lowered_text = text.lower()

    def _size_candidate_is_gender_artifact(candidate: str) -> bool:
        if len(candidate) != 1 or not gender_artifact_pattern:
            return False
        lowered_candidate = candidate.lower()
        pattern = _gender_artifact_patterns.get(lowered_candidate)
        if pattern is None:
            pattern = re.compile(
                gender_artifact_pattern.format(
                    candidate=re.escape(lowered_candidate)
                )
            )
            _gender_artifact_patterns[lowered_candidate] = pattern
        return pattern.search(lowered_text) is not None

    for pattern in variant_size_value_extract_patterns:
        match = pattern.search(text)
        if match is not None:
            candidate = clean_text(match.group(0))
            if len(candidate) == 1 and (
                (match.start() > 0 and text[match.start() - 1] in {"'", "’"})
                or _size_candidate_is_gender_artifact(candidate)
            ):
                continue
            # Numeric values <4 are usually counts like 2-pack, not child sizes.
            if candidate.isdigit() and int(candidate) < 4:
                continue
            return candidate
    tokens = [token for token in re.split(r"[^a-z0-9.]+", text, flags=re.I) if token]
    for width in range(min(3, len(tokens)), 0, -1):
        for index in range(0, len(tokens) - width + 1):
            candidate = clean_text(" ".join(tokens[index : index + width]))
            if not candidate:
                continue
            if _size_candidate_is_gender_artifact(candidate):
                continue
            # Numeric values <4 are usually counts like 2-pack, not child sizes.
            if candidate.isdigit() and int(candidate) < 4:
                continue
            if any(
                pattern.fullmatch(candidate) for pattern in variant_size_value_patterns
            ):
                return candidate
    return ""


def _size_value_is_recognized(value: object) -> bool:
    cleaned = clean_text(value)
    if not cleaned:
        return False
    lowered = cleaned.casefold()
    if lowered in common_word_size_values:
        return True
    if any(pattern.fullmatch(cleaned) for pattern in variant_size_value_patterns):
        return True
    extracted = _extract_size_value(cleaned)
    return bool(extracted) and extracted.casefold() == lowered


def _size_value_is_child_specific(value: object) -> bool:
    cleaned = clean_text(value)
    return bool(
        cleaned
        and any(pattern.fullmatch(cleaned) for pattern in variant_child_size_patterns)
    )


def _variant_title_tokens(value: object) -> set[str]:
    text = clean_text(value).lower()
    if not text:
        return set()
    return {
        token
        for token in re.findall(r"[a-z0-9]+", text)
        if token not in variant_title_stopwords
    }


def _record_targets_adult_sizes(record: dict[str, Any]) -> bool:
    probes = (
        record.get("title"),
        record.get("gender"),
        record.get("category"),
    )
    tokens: set[str] = set()
    for value in probes:
        tokens.update(_variant_title_tokens(value))
    return bool(tokens & adult_size_context_tokens)


def _url_terminal_text(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    parsed = urlparse(text)
    path = parsed.path if parsed.scheme or parsed.netloc else text
    terminal = path.rstrip("/").rsplit("/", 1)[-1]
    return clean_text(unquote(terminal).replace("-", " ").replace("_", " "))


def _variant_color_from_title_or_url(
    variant: dict[str, Any],
    *,
    record: dict[str, Any],
) -> str:
    for candidate in (
        variant.get("title"),
        variant.get("name"),
        record.get("title"),
        _url_terminal_text(variant.get("url")),
        _url_terminal_text(record.get("url")),
    ):
        if color_value := _extract_color_value(candidate):
            return color_value
    return ""


def _extract_color_value(value: object) -> str:
    text = clean_text(value)
    if not text:
        return ""
    for chunk in reversed(
        [
            part
            for part in re.split(r"\s+[|/]\s+|\s+[–—-]\s+|\(", text)
            if clean_text(part)
        ]
    ):
        if color_value := _extract_trailing_color_phrase(chunk):
            return color_value
    return _extract_trailing_color_phrase(text)


def _extract_trailing_color_phrase(value: str) -> str:
    tokens = [
        token
        for token in re.findall(r"[A-Za-z0-9]+", clean_text(value))
        if token and not token.isdigit()
    ]
    if not tokens:
        return ""
    color_indexes = [
        index
        for index, token in enumerate(tokens)
        if token.lower() in variant_color_hint_words
    ]
    if not color_indexes:
        return ""
    start = color_indexes[-1]
    while start > 0 and tokens[start - 1].lower() in variant_color_hint_words:
        start -= 1
    if start > 0:
        previous = tokens[start - 1].lower()
        if (
            previous not in standard_size_values
            and previous not in gender_keyword_tokens
        ):
            start -= 1
    end = color_indexes[-1] + 1
    while end < len(tokens) and tokens[end].lower() in variant_color_hint_words:
        end += 1
    phrase = clean_text(" ".join(tokens[start:end]))
    if not phrase or len(phrase.split()) > 4:
        return ""
    return _title_preserving_acronyms(phrase)


def _title_preserving_acronyms(phrase: str) -> str:
    return " ".join(
        token if token.isupper() else token.capitalize() for token in phrase.split()
    )


def _value_is_axis_header_noise(field_name: str, value: str) -> bool:
    axis_name = normalized_variant_axis_key(field_name)
    lowered = clean_text(value).casefold()
    if axis_name not in {"condition", "state"}:
        return False
    return any(
        prefix and re.fullmatch(rf"{re.escape(prefix)}\s*\(\d+\)", lowered) is not None
        for prefix in variant_condition_header_prefixes
    )


def _variant_axis_value_is_header(field_name: str, value: str) -> bool:
    axis_name = clean_text(field_name).casefold()
    lowered_value = clean_text(value).casefold()
    axis_forms = {
        axis_name,
        f"{axis_name}s",
    }
    return lowered_value in axis_forms or any(
        form and lowered_value.startswith(f"{form}:") for form in axis_forms
    )
