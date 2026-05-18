from __future__ import annotations

__all__ = (
    "record_has_rich_existing_variants",
    "primary_dom_context",
    "existing_variant_cluster_has_transport_signal",
)

import logging
from typing import Any

from bs4 import BeautifulSoup
from selectolax.lexbor import LexborHTMLParser

from app.services.config.extraction_rules import (
    DETAIL_LONG_TEXT_RANK_FIELDS,
    DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR,
)
from app.services.config.field_mappings import (
    DOM_HIGH_VALUE_FIELDS,
    DOM_OPTIONAL_CUE_FIELDS,
)
from app.services.field_policy import exact_requested_field_key, normalize_field_key
from app.services.shared.field_coerce import (
    object_list as _object_list,
    surface_fields,
    text_or_none,
)
from app.services.extract.variant_axis import public_variant_axis_fields

logger = logging.getLogger(__name__)

_VARIANT_TRANSPORT_FIELDS = (
    "sku",
    "price",
    "currency",
    "url",
    "image_url",
    "availability",
    "stock_quantity",
)


def _dom_section_target_fields(
    surface: str,
    requested_fields: list[str] | None,
) -> set[str]:
    normalized_surface = str(surface or "").strip().lower()
    targets = {
        str(field_name).strip()
        for field_name in {
            *set(DETAIL_LONG_TEXT_RANK_FIELDS),
            *set(DOM_HIGH_VALUE_FIELDS.get(normalized_surface) or ()),
            *set(DOM_OPTIONAL_CUE_FIELDS.get(normalized_surface) or ()),
        }
        if str(field_name).strip()
    }
    canonical_fields = set(surface_fields(surface, None))
    for raw_field_name in list(requested_fields or []):
        normalized_field = exact_requested_field_key(
            raw_field_name
        ) or normalize_field_key(raw_field_name)
        if normalized_field and normalized_field not in canonical_fields:
            targets.add(normalized_field)
    return targets


def record_has_rich_existing_variants(record: dict[str, Any]) -> bool:
    variants = [
        row for row in _object_list(record.get("variants")) if isinstance(row, dict)
    ]
    if len(variants) < 2:
        return False
    return all(
        any(text_or_none(row.get(axis)) for axis in public_variant_axis_fields)
        and any(text_or_none(row.get(field)) for field in _VARIANT_TRANSPORT_FIELDS)
        for row in variants
    )


def primary_dom_context(
    context: Any,
    *,
    page_url: str,
) -> tuple[LexborHTMLParser, BeautifulSoup]:
    cleaned_parser = context.dom_parser
    cleaned_soup = context.soup

    def _has_primary_context(
        parser: LexborHTMLParser,
        soup: BeautifulSoup,
    ) -> bool:
        return bool(
            parser.css_first(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
            and soup.select_one(DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR)
        )

    if _has_primary_context(cleaned_parser, cleaned_soup):
        return cleaned_parser, cleaned_soup
    original_parser = context.original_dom_parser
    original_soup = context.original_soup
    if not _has_primary_context(original_parser, original_soup):
        return cleaned_parser, cleaned_soup
    logger.debug(
        "Using original DOM after cleaned DOM lost primary content for %s", page_url
    )
    return original_parser, original_soup


def existing_variant_cluster_has_transport_signal(
    variants: list[dict[str, Any]],
) -> bool:
    if len(variants) < 2:
        return False
    rows_with_transport = 0
    for row in variants:
        if not isinstance(row, dict):
            continue
        has_identity = any(
            text_or_none(row.get(field_name))
            for field_name in ("sku", "variant_id", "url", "image_url")
        )
        has_price = text_or_none(row.get("price")) is not None
        if has_identity and has_price:
            rows_with_transport += 1
    return rows_with_transport >= 2
