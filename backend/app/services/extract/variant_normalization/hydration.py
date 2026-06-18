from __future__ import annotations

import re
from typing import Any

from app.services.config.extraction_rules import (
    GENDER_POSSESSIVE_PATTERN,
    STANDARD_SIZE_VALUES,
    VARIANT_URL_SUFFIX_CODE_PREFIX_MAX_LEN,
    VARIANT_SKU_SIZE_SUFFIX_PATTERNS,
)
from app.services.extract.variant_normalization import size_color_extraction
from app.services.shared.field_coerce import clean_text
from app.services.shared.regex_patterns import compile_regex_patterns
from app.services.shared.url_utils import (
    clean_color_tokens,
    terminal_text,
    title_preserving_acronyms,
    title_tokens,
)

__all__ = ("hydrate_variant_axes", "_hydrate_variant_axes")

gender_possessive_re = (
    re.compile(str(GENDER_POSSESSIVE_PATTERN), re.I)
    if GENDER_POSSESSIVE_PATTERN
    else None
)
standard_size_values = frozenset(
    str(value).casefold() for value in tuple(STANDARD_SIZE_VALUES or ())
)
variant_sku_size_suffix_patterns = compile_regex_patterns(
    VARIANT_SKU_SIZE_SUFFIX_PATTERNS or (),
    preserve_compiled=True,
)
try:
    variant_url_suffix_code_prefix_max_len = max(
        1, int(VARIANT_URL_SUFFIX_CODE_PREFIX_MAX_LEN)
    )
except (TypeError, ValueError):
    variant_url_suffix_code_prefix_max_len = 3


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
        (terminal_text(variant.get("url")), False),
        (terminal_text(record.get("url")), False),
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


def _record_url_suffix_after_title(record: dict[str, Any]) -> str:
    title = clean_text(record.get("title") or record.get("name"))
    terminal = terminal_text(record.get("url"))
    if not title or not terminal:
        return ""
    title_parts = title_tokens(title)
    terminal_parts = title_tokens(terminal)
    if len(terminal_parts) <= len(title_parts):
        return ""
    if terminal_parts[: len(title_parts)] != title_parts:
        return ""
    suffix_tokens = terminal_parts[len(title_parts) :]
    if not suffix_tokens or len(suffix_tokens) > 4:
        return ""
    # Drop digit-only and structural tokens (e.g. "html", numeric product IDs).
    cleaned_tokens = clean_color_tokens(suffix_tokens)
    if not cleaned_tokens:
        return ""
    while cleaned_tokens and _token_looks_like_code(cleaned_tokens[-1]):
        cleaned_tokens = cleaned_tokens[:-1]
    while cleaned_tokens and cleaned_tokens[-1].isdigit():
        cleaned_tokens = cleaned_tokens[:-1]
    if not cleaned_tokens:
        return ""
    while (
        len(cleaned_tokens) > 1
        and len(cleaned_tokens[0]) <= variant_url_suffix_code_prefix_max_len
        and cleaned_tokens[0].isalpha()
        and cleaned_tokens[0].casefold()
        not in size_color_extraction.variant_color_hint_words
        and any(
            token.casefold() in size_color_extraction.variant_color_hint_words
            for token in cleaned_tokens[1:]
        )
    ):
        cleaned_tokens = cleaned_tokens[1:]
    # SKU/style codes mix letters and digits inside a single token
    # (e.g. ``cl28517s``, ``vn000e9tbpg``). Real color slugs are
    # alphabetic words such as ``tuke-river`` or ``natural-black``.
    if any(_token_looks_like_code(token) for token in cleaned_tokens):
        return ""
    return title_preserving_acronyms(" ".join(cleaned_tokens))


def _token_looks_like_code(token: str) -> bool:
    """Mixed letter+digit single-token codes are SKUs/style codes, not color words."""
    return bool(re.search(r"[A-Za-z]", token) and re.search(r"\d", token))


hydrate_variant_axes = _hydrate_variant_axes
