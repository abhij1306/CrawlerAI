from __future__ import annotations

import logging
import re
from functools import lru_cache

from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS,
    DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS,
    DATA_ENRICHMENT_MATERIAL_PERCENTAGE_RE,
    DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS,
)
from app.core.shared.field_coerce import clean_text, strip_html_tags
from app.core.shared.regex_patterns import compile_regex_patterns
from app.core.shared.value_walk import candidate_values, term_present

logger = logging.getLogger(__name__)


def normalize_materials(
    data: dict[str, object], *, terms: dict[str, object]
) -> list[str] | None:
    raw_material_terms = terms.get("material_terms")
    material_terms = (
        {str(key): value for key, value in raw_material_terms.items()}
        if isinstance(raw_material_terms, dict)
        else {}
    )
    found: list[str] = []
    seen: set[str] = set()
    for value in candidate_values(data, *DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS):
        collect_material_matches(
            clean_text(strip_html_tags(value)).casefold(),
            material_terms,
            found,
            seen,
        )
    for value in candidate_values(data, *DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS):
        lowered = clean_text(strip_html_tags(value)).casefold()
        collect_material_percentage_matches(lowered, material_terms, found, seen)
        collect_material_matches(
            strip_material_context_noise(lowered), material_terms, found, seen
        )
    return found or None


def collect_material_matches(
    text: str,
    material_terms: dict[str, object],
    found: list[str],
    seen: set[str],
) -> None:
    collect_material_percentage_matches(text, material_terms, found, seen)
    for canonical, tokens in material_terms.items():
        if canonical in seen:
            continue
        if isinstance(tokens, list) and any(
            term_present(text, token) for token in tokens
        ):
            found.append(str(canonical))
            seen.add(str(canonical))


def collect_material_percentage_matches(
    text: str,
    material_terms: dict[str, object],
    found: list[str],
    seen: set[str],
) -> None:
    for material in percentage_material_parse(text):
        add_material_match(material, material_terms, found, seen)


def percentage_material_parse(text: str) -> list[str]:
    materials: list[str] = []
    material_token = r"[a-z]+(?:-[a-z]+)?"
    material_phrase = rf"{material_token}(?:\s+{material_token}){{0,4}}"
    patterns = (
        DATA_ENRICHMENT_MATERIAL_PERCENTAGE_RE,
        rf"\b(?P<material>{material_phrase})\s*(?P<percent>\d{{1,3}}(?:\.\d+)?)\s*(?:%|percent)\b",
        rf"\b(?P<percent>\d{{1,3}}(?:\.\d+)?)\s*percent\s*(?P<material>{material_phrase})\b",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, text, re.I):
            try:
                material_value = match.group("material")
                match.group("percent")
            except (AttributeError, IndexError):
                continue
            if material := clean_percentage_material(material_value):
                materials.append(material)
    return materials


def clean_percentage_material(value: object) -> str:
    material = clean_text(value).casefold()
    material = re.sub(r"^(?:and|or|with|of|made\s+with|made\s+of)\s+", "", material)
    material = re.sub(r"^.*\b(?:with|of|contains|composition|fabric)\s+", "", material)
    material = re.split(r"\b(?:and|or|plus)\b|[,.;:/()]", material, maxsplit=1)[0]
    return clean_text(material)


def add_material_match(
    value: str,
    material_terms: dict[str, object],
    found: list[str],
    seen: set[str],
) -> None:
    normalized = clean_text(value).casefold()
    for canonical, tokens in material_terms.items():
        if canonical in seen:
            continue
        if normalized == str(canonical).casefold() or (
            isinstance(tokens, list)
            and any(term_present(normalized, token) for token in tokens)
        ):
            found.append(str(canonical))
            seen.add(str(canonical))
            return


@lru_cache(maxsize=1)
def compiled_material_strip_patterns() -> tuple[re.Pattern[str], ...]:
    return compile_regex_patterns(
        tuple(DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS or ()),
        logger=logger,
        warning_message="Skipping invalid material strip pattern: %r",
        skip_blank=False,
    )


def strip_material_context_noise(value: str) -> str:
    cleaned = value
    for pattern in compiled_material_strip_patterns():
        cleaned = pattern.sub("", cleaned)
    return clean_text(cleaned)
