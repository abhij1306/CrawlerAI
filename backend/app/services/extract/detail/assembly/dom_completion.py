from __future__ import annotations

__all__ = (
    "early_price_repair_required_fields",
    "variant_signal_strength",
    "variant_axis_coverage",
    "should_collect_dom_variants",
    "dom_variants_are_validated",
    "missing_requested_fields",
    "detail_long_text_value_looks_truncated",
    "detail_description_value_looks_thin",
    "requires_dom_long_text_completion",
    "requires_dom_completion",
    "normalized_category_path",
)

import re
from typing import Any

from bs4 import BeautifulSoup

from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
    IMAGE_URL_FIELD,
    TITLE_FIELD,
    URL_FIELD,
    VARIANT_AXIS_FIELD_NAMES,
    VARIANT_DOM_FIELD_NAMES,
)
from app.services.config.extraction_rules import (
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_LONG_TEXT_SOURCE_RANKS,
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS,
    DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS,
    DETAIL_PRODUCT_IMAGE_CUE_SELECTOR,
)
from app.services.dom.selector_engine import requested_content_extractability
from app.services.extract.detail.assembly.dom_section_targets import (
    record_has_rich_existing_variants,
)
from app.services.extract.detail.assembly.raw_signals import (
    breadcrumb_category_from_dom,
)
from app.services.extract.field_candidates import finalize_candidate_value
from app.services.extract.variant_choice_traversal import variant_dom_cues_present
from app.services.field_policy import exact_requested_field_key
from app.services.shared.field_coerce import (
    clean_text,
    object_dict as _object_dict,
    object_list as _object_list,
    text_or_none,
)

_EARLY_PRICE_REPAIR_REQUIRED_FIELDS = (TITLE_FIELD, IMAGE_URL_FIELD, URL_FIELD)

try:
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS_INT = int(
        DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS
    )
except (TypeError, ValueError):
    DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS_INT = 50


def _variant_signal_strength(variants: object) -> tuple[int, int, int, int]:
    if not isinstance(variants, list):
        return (0, 0, 0, 0)
    rows = [row for row in variants if isinstance(row, dict)]
    axis_coverage = _variant_axis_coverage(rows)
    return (
        sum(1 for row in rows if text_or_none(row.get("price"))),
        sum(
            1
            for row in rows
            if (
                any(
                    text_or_none(row.get(axis_name))
                    for axis_name in VARIANT_AXIS_FIELD_NAMES
                )
                or (
                    isinstance(row.get("option_values"), dict)
                    and any(
                        text_or_none(value) for value in row["option_values"].values()
                    )
                )
            )
        ),
        len(axis_coverage),
        len(rows),
    )


def _variant_axis_coverage(variants: object) -> set[str]:
    if not isinstance(variants, list):
        return set()
    coverage: set[str] = set()
    for row in variants:
        if not isinstance(row, dict):
            continue
        option_values = row.get("option_values")
        if isinstance(option_values, dict):
            for axis_name, axis_value in option_values.items():
                if text_or_none(axis_value):
                    coverage.add(str(axis_name).strip().lower())
        for axis_name in VARIANT_AXIS_FIELD_NAMES:
            if text_or_none(row.get(axis_name)):
                coverage.add(axis_name)
    return coverage


def _should_collect_dom_variants(
    candidates: dict[str, list[object]],
    dom_variants: dict[str, object],
) -> bool:
    if not _dom_variants_are_validated(dom_variants):
        return False
    if not any(candidates.get(field_name) for field_name in VARIANT_DOM_FIELD_NAMES):
        return True
    existing_variants = finalize_candidate_value(
        "variants", list(candidates.get("variants") or [])
    )
    existing_strength = _variant_signal_strength(existing_variants)
    if dom_variants:
        existing_axes = _variant_axis_coverage(existing_variants)
        dom_axes = _variant_axis_coverage(dom_variants.get("variants"))
        if (
            dom_axes - existing_axes
            and existing_strength[0] == 0
            and existing_strength[1] == 0
        ):
            return True
    if existing_strength[3] == 0:
        return True
    if existing_strength[0] == 0 and existing_strength[1] == 0:
        return True
    dom_strength = _variant_signal_strength(dom_variants.get("variants"))
    return dom_strength > existing_strength


def _dom_variants_are_validated(dom_variants: dict[str, object]) -> bool:
    rows = dom_variants.get("variants") if isinstance(dom_variants, dict) else None
    return (
        isinstance(rows, list)
        and bool(rows)
        and all(isinstance(row, dict) and row.get("_validated") is True for row in rows)
    )


def _missing_requested_fields(
    record: dict[str, Any],
    requested_fields: list[str] | None,
) -> set[str]:
    missing: set[str] = set()
    for field_name in list(requested_fields or []):
        normalized = exact_requested_field_key(str(field_name or ""))
        if normalized and record.get(normalized) in (None, "", [], {}):
            missing.add(normalized)
    return missing


def _detail_long_text_value_looks_truncated(value: object) -> bool:
    text = clean_text(value).rstrip()
    if not text:
        return False
    if text.endswith(("...", "…")):
        return True
    if text[-1] in ".!?":
        return False
    tokens = re.findall(r"[A-Za-z0-9']+", text.casefold())
    return bool(tokens) and tokens[-1] in DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS


def _detail_description_value_looks_thin(value: object) -> bool:
    text = clean_text(value)
    if not text:
        return False
    tokens = (
        re.findall(r"[A-Za-z0-9']+", text)
        if text.isascii()
        else re.findall(r"\w+", text, flags=re.UNICODE)
    )
    return bool(tokens) and len(tokens) <= DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS_INT


def _requires_dom_long_text_completion(
    record: dict[str, Any],
    *,
    extractable_fields: set[str],
) -> bool:
    if not (extractable_fields & DETAIL_LONG_TEXT_RANK_FIELDS):
        return False
    field_sources = _object_dict(record.get("_field_sources"))
    weak_source_rank = DETAIL_LONG_TEXT_SOURCE_RANKS.get("opengraph", 20)
    for field_name in extractable_fields & DETAIL_LONG_TEXT_RANK_FIELDS:
        value = clean_text(record.get(field_name))
        if not value:
            continue
        source_ranks = [
            DETAIL_LONG_TEXT_SOURCE_RANKS.get(str(source or ""), 20)
            for source in _object_list(field_sources.get(field_name))
        ]
        best_rank = min(source_ranks) if source_ranks else 20
        if field_name == "description" and _detail_description_value_looks_thin(value):
            return True
        if best_rank >= weak_source_rank or _detail_long_text_value_looks_truncated(
            value
        ):
            return True
    return False


def _requires_dom_completion(
    *,
    record: dict[str, Any],
    surface: str,
    requested_fields: list[str] | None,
    selector_rules: list[dict[str, object]] | None,
    soup: BeautifulSoup,
    breadcrumb_soup: BeautifulSoup | None = None,
) -> bool:
    normalized_surface = str(surface or "").strip().lower()
    raw_soup = breadcrumb_soup or soup
    requested_missing_fields = _missing_requested_fields(record, requested_fields)
    if normalized_surface == "ecommerce_detail":
        breadcrumb_category = breadcrumb_category_from_dom(
            raw_soup,
            current_title=text_or_none(record.get("title")),
        )
        record_category = _normalized_category_path(record.get("category"))
        dom_category = _normalized_category_path(breadcrumb_category)
        if record_category and dom_category and record_category != dom_category:
            return True
    if (
        normalized_surface == "ecommerce_detail"
        and not record_has_rich_existing_variants(record)
        and (variant_dom_cues_present(soup) or variant_dom_cues_present(raw_soup))
    ):
        return True
    if (
        normalized_surface == "ecommerce_detail"
        and record.get("image_url") in (None, "", [], {})
        and raw_soup.select_one(DETAIL_PRODUCT_IMAGE_CUE_SELECTOR) is not None
    ):
        return True
    if (
        normalized_surface == "ecommerce_detail"
        and not requested_fields
        and not selector_rules
        and record_has_rich_existing_variants(record)
        and all(
            record.get(field_name) not in (None, "", [], {})
            for field_name in _EARLY_PRICE_REPAIR_REQUIRED_FIELDS
        )
    ):
        return False
    high_value_fields = set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ())
    optional_probe_fields = set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ())
    probe_fields = sorted(
        {
            *high_value_fields,
            *optional_probe_fields,
            *requested_missing_fields,
        }
    )
    extractability = requested_content_extractability(
        soup,
        surface=surface,
        requested_fields=requested_fields,
        selector_rules=selector_rules,
        probe_fields=probe_fields or None,
    )
    extractable_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("extractable_fields"))
        if str(field_name).strip()
    }
    advertised_high_value_fields = extractable_fields & high_value_fields
    missing_high_value_fields = {
        field_name
        for field_name in advertised_high_value_fields
        if record.get(field_name) in (None, "", [], {})
    }
    missing_high_value_fields.update(
        {
            field_name
            for field_name in high_value_fields
            if field_name in requested_missing_fields
        }
    )
    if extractable_fields & requested_missing_fields:
        return True
    if missing_high_value_fields or requested_missing_fields & high_value_fields:
        return True
    if normalized_surface == "ecommerce_detail" and _requires_dom_long_text_completion(
        record,
        extractable_fields=extractable_fields,
    ):
        return True
    optional_cue_fields = {
        field_name
        for field_name in set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ())
        if record.get(field_name) in (None, "", [], {})
    }
    dom_pattern_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("dom_pattern_fields"))
        if str(field_name).strip()
    }
    if optional_cue_fields & dom_pattern_fields:
        return True
    selector_backed_fields = {
        str(field_name).strip()
        for field_name in _object_list(extractability.get("selector_backed_fields"))
        if str(field_name).strip()
    }
    return bool(requested_missing_fields & selector_backed_fields)


def _normalized_category_path(value: object) -> str:
    if isinstance(value, (list, tuple)):
        return " > ".join(
            part
            for item in value
            for part in _normalized_category_path(item).split(" > ")
            if part
        )
    text = clean_text(value).casefold()
    return " > ".join(
        part for part in re.split(r"\s*(?:>|/|›|»|→|\|)\s*", text) if part
    )


early_price_repair_required_fields = _EARLY_PRICE_REPAIR_REQUIRED_FIELDS
variant_signal_strength = _variant_signal_strength
variant_axis_coverage = _variant_axis_coverage
should_collect_dom_variants = _should_collect_dom_variants
dom_variants_are_validated = _dom_variants_are_validated
missing_requested_fields = _missing_requested_fields
detail_long_text_value_looks_truncated = _detail_long_text_value_looks_truncated
detail_description_value_looks_thin = _detail_description_value_looks_thin
requires_dom_long_text_completion = _requires_dom_long_text_completion
requires_dom_completion = _requires_dom_completion
normalized_category_path = _normalized_category_path
