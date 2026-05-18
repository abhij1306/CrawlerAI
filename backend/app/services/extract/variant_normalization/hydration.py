from __future__ import annotations

import re
from typing import Any
from urllib.parse import unquote, urlparse

from app.services.config.extraction_rules import (
    GENDER_POSSESSIVE_PATTERN,
    STANDARD_SIZE_VALUES,
    VARIANT_SKU_SIZE_SUFFIX_PATTERNS,
)
from app.services.extract.variant_normalization import size_color_extraction
from app.services.shared.field_coerce import clean_text, text_or_none

__all__ = ("_hydrate_variant_axes",)

gender_possessive_re = (
    re.compile(str(GENDER_POSSESSIVE_PATTERN), re.I)
    if GENDER_POSSESSIVE_PATTERN
    else None
)
standard_size_values = frozenset(
    str(value).casefold() for value in tuple(STANDARD_SIZE_VALUES or ())
)
variant_sku_size_suffix_patterns = tuple(
    pattern if isinstance(pattern, re.Pattern) else re.compile(str(pattern), re.I)
    for pattern in tuple(VARIANT_SKU_SIZE_SUFFIX_PATTERNS or ())
    if str(pattern).strip()
)


def _hydrate_variant_axes(record: dict[str, Any]) -> None:
    _infer_variant_sizes_from_titles(record)
    _infer_variant_sizes_from_skus(record)
    _infer_shared_variant_color_from_record_identity(record)
    _infer_single_variant_axes(record)


def _infer_variant_sizes_from_titles(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    inferred_by_index: dict[int, str] = {}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict) or clean_text(variant.get("size")):
            continue
        size_value = _variant_size_from_title_or_url(variant, record=record)
        if size_value:
            inferred_by_index[index] = size_value
    unique_values: list[str] = []
    seen: set[str] = set()
    for value in inferred_by_index.values():
        lowered = value.casefold()
        if lowered in seen:
            continue
        seen.add(lowered)
        unique_values.append(value)
    if len(unique_values) < 2:
        return
    for index, size_value in inferred_by_index.items():
        variant = variants[index]
        if isinstance(variant, dict) and variant.get("size") in (None, "", [], {}):
            variant["size"] = size_value


def _infer_variant_sizes_from_skus(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    inferred_by_index: dict[int, str] = {}
    for index, variant in enumerate(variants):
        if not isinstance(variant, dict) or clean_text(variant.get("size")):
            continue
        size_value = _variant_size_from_sku(variant.get("sku"))
        if size_value:
            inferred_by_index[index] = size_value
    unique_values = {
        value.casefold() for value in inferred_by_index.values() if clean_text(value)
    }
    if len(unique_values) < 2:
        return
    for index, size_value in inferred_by_index.items():
        variant = variants[index]
        if isinstance(variant, dict) and variant.get("size") in (None, "", [], {}):
            variant["size"] = size_value


def _infer_single_variant_axes(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) != 1:
        return
    variant = variants[0]
    if not isinstance(variant, dict):
        return
    if not clean_text(variant.get("size")):
        size_value = _variant_size_from_title_or_url(variant, record=record)
        if size_value:
            variant["size"] = size_value
    if not clean_text(variant.get("color")):
        color_value = size_color_extraction._variant_color_from_title_or_url(
            variant,
            record=record,
        )
        if color_value:
            variant["color"] = color_value


def _infer_shared_variant_color_from_record_identity(record: dict[str, Any]) -> None:
    variants = record.get("variants")
    if not isinstance(variants, list) or len(variants) < 2:
        return
    variant_rows = [variant for variant in variants if isinstance(variant, dict)]
    if len(variant_rows) < 2:
        return
    if any(clean_text(variant.get("color")) for variant in variant_rows):
        return
    if not any(clean_text(variant.get("size")) for variant in variant_rows):
        return
    color_value = _record_url_suffix_after_title(record)
    if not color_value:
        color_value = size_color_extraction._variant_color_from_title_or_url(
            {},
            record=record,
        )
    if not color_value:
        return
    for variant in variant_rows:
        if variant.get("color") in (None, "", [], {}):
            variant["color"] = color_value


def _variant_size_from_title_or_url(
    variant: dict[str, Any],
    *,
    record: dict[str, Any],
) -> str:
    candidates = [
        (variant.get("title"), False),
        (variant.get("name"), False),
        (record.get("title"), True),
        (_url_terminal_text(variant.get("url")), False),
        (_url_terminal_text(record.get("url")), False),
    ]
    record_title = clean_text(record.get("title")).casefold()
    for candidate, allow_record_title in candidates:
        text = clean_text(candidate)
        if not text:
            continue
        if not allow_record_title and record_title and text.casefold() == record_title:
            continue
        extracted = size_color_extraction._extract_size_value(text)
        if (
            extracted
            and extracted.casefold() in standard_size_values
            and gender_possessive_re is not None
            and gender_possessive_re.search(text)
        ):
            continue
        if extracted:
            return extracted
    return ""


def _variant_size_from_sku(value: object) -> str:
    sku = clean_text(value)
    if not sku:
        return ""
    for pattern in variant_sku_size_suffix_patterns:
        match = pattern.search(sku)
        if match is None:
            continue
        size_value = clean_text(match.groupdict().get("size") or match.group(0))
        if size_value:
            return size_value.upper()
    return ""


def _url_terminal_text(value: object) -> str:
    text = text_or_none(value)
    if not text:
        return ""
    parsed = urlparse(text)
    parts = [part for part in str(parsed.path or "").split("/") if part]
    if not parts:
        return ""
    return clean_text(unquote(parts[-1]).replace("-", " ").replace("_", " "))


def _record_url_suffix_after_title(record: dict[str, Any]) -> str:
    title = clean_text(record.get("title") or record.get("name"))
    terminal = _url_terminal_text(record.get("url"))
    if not title or not terminal:
        return ""
    title_tokens = _identity_tokens(title)
    terminal_tokens = _identity_tokens(terminal)
    if len(terminal_tokens) <= len(title_tokens):
        return ""
    if terminal_tokens[: len(title_tokens)] != title_tokens:
        return ""
    suffix_tokens = terminal_tokens[len(title_tokens) :]
    if not suffix_tokens or len(suffix_tokens) > 4:
        return ""
    return _title_preserving_acronyms(" ".join(suffix_tokens))


def _identity_tokens(value: str) -> list[str]:
    return [
        _identity_token_root(token)
        for token in re.findall(r"[a-z0-9]+", clean_text(value).casefold())
        if token and token != "s"
    ]


def _identity_token_root(value: str) -> str:
    if value in {"mens", "womens", "kids"}:
        return value[:-1]
    if len(value) > 4 and value.endswith("s"):
        return value[:-1]
    return value


def _title_preserving_acronyms(value: str) -> str:
    return " ".join(
        token.upper() if token.isupper() else token.capitalize()
        for token in clean_text(value).split()
    )
