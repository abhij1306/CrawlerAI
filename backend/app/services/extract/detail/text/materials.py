from __future__ import annotations

import re

from app.services.config.extraction_rules import (
    DETAIL_MATERIALS_COMPOSITION_PATTERN,
    DETAIL_MATERIALS_EDITORIAL_HEAD_THRESHOLD,
    DETAIL_MATERIALS_EDITORIAL_LENGTH_THRESHOLD,
    DETAIL_MATERIALS_POLLUTION_TOKENS,
    DETAIL_MATERIALS_SECTION_TAIL_PATTERNS,
    DETAIL_MATERIALS_ZERO_PERCENT_PATTERN,
    MATERIAL_KEYWORDS,
)
from app.services.shared.field_coerce import clean_text
from app.services.shared.regex_patterns import compile_regex_patterns

__all__ = ("sanitize_materials_text",)

_composition_pattern = re.compile(str(DETAIL_MATERIALS_COMPOSITION_PATTERN), re.I)
_zero_percent_pattern = re.compile(str(DETAIL_MATERIALS_ZERO_PERCENT_PATTERN), re.I)
_pollution_tokens = frozenset(
    clean_text(token).casefold()
    for token in tuple(DETAIL_MATERIALS_POLLUTION_TOKENS or ())
    if clean_text(token)
)
_section_tail_patterns = compile_regex_patterns(
    DETAIL_MATERIALS_SECTION_TAIL_PATTERNS or ()
)
_editorial_head_len = int(DETAIL_MATERIALS_EDITORIAL_HEAD_THRESHOLD)
_editorial_min_len = int(DETAIL_MATERIALS_EDITORIAL_LENGTH_THRESHOLD)
_head_trim_terminators = re.compile(
    r"\b(?:Made\s+in|Garment\s+Made\s+in|Fabric\s+(?:From|Made\s+in)|"
    r"Dry\s+Clean(?:\s+Only)?|Machine\s+Wash|Hand\s+Wash|Wash\s+Cold|"
    r"Tumble\s+Dry|Do\s+Not\s+Bleach)\b[^.]{0,80}\.",
    re.I,
)


def sanitize_materials_text(value: str) -> str:
    text = _strip_section_tail(clean_text(value))
    if (
        len(text) > _editorial_min_len
        and not _composition_pattern.search(text)
        and not any(
            re.search(rf"\b{re.escape(str(token))}\b", text, re.I)
            for token in MATERIAL_KEYWORDS
        )
    ):
        return ""
    repaired = _extract_trailing_composition(text)
    if repaired is not None:
        text = repaired
    text = _trim_to_first_specifics(text)
    chunks = [
        clean_text(chunk)
        for chunk in re.split(r"(?<=[.!?])\s+|\s+:\s+|\n+", text)
        if clean_text(chunk)
    ]
    cleaned = _dedupe_adjacent_chunks(
        " ".join(
            chunk
            for chunk in chunks
            if chunk.casefold() not in _pollution_tokens
            and not _zero_percent_pattern.search(chunk)
        ).strip()
    )
    while True:
        parts = cleaned.split(maxsplit=1)
        if not parts or parts[0].casefold().strip(":") not in _pollution_tokens:
            return _dedupe_adjacent_chunks(cleaned)
        cleaned = parts[1] if len(parts) > 1 else ""


def _strip_section_tail(text: str) -> str:
    for pattern in _section_tail_patterns:
        match = pattern.search(text)
        if match:
            return clean_text(text[: match.start()])
    return text


def _extract_trailing_composition(text: str) -> str | None:
    if len(text) <= _editorial_min_len:
        return None
    if _composition_pattern.search(text[:_editorial_head_len]):
        return None
    matches = list(_composition_pattern.finditer(text))
    if not matches:
        return None
    return text[matches[0].start() :].strip()


def _trim_to_first_specifics(text: str) -> str:
    if len(text) <= 200 or not _composition_pattern.match(text):
        return text
    match = _head_trim_terminators.search(text[:400])
    if match is None or any(
        item.start() > match.end() for item in _composition_pattern.finditer(text)
    ):
        return text
    return text[: match.end()].strip() or text


def _dedupe_adjacent_chunks(text: str) -> str:
    chunks = [
        clean_text(chunk)
        for chunk in re.split(r"(?<=[.;!?])\s+", clean_text(text))
        if clean_text(chunk)
    ]
    deduped: list[str] = []
    for chunk in chunks:
        if not deduped or chunk.casefold() != deduped[-1].casefold():
            deduped.append(chunk)
    return " ".join(deduped)
