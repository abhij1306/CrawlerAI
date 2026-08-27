from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import urlsplit

from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    AVAILABILITY_CANONICAL_ENUM,
    DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY,
    DETAIL_TITLE_SOURCE_ROLE_RANKS,
)
from app.core.records.url_identity import (
    detail_title_rank_components,
    detail_url_rank_components,
)
from app.core.config.locale_format_rules import parse_money, validate_gtin
from app.extraction.contracts import Evidence

_PRICE_FACT_TYPES = frozenset(
    {
        field_mappings.OFFER_PRICE_FACT_TYPE,
        field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    }
)
_GTIN_FACT_TYPES = frozenset(
    {field_mappings.PRODUCT_GTIN_FACT_TYPE, field_mappings.VARIANT_GTIN_FACT_TYPE}
)
_URL_FACT_TYPES = frozenset(
    {field_mappings.PRODUCT_URL_FACT_TYPE, field_mappings.ASSET_IMAGE_URL_FACT_TYPE}
)


def non_positive_money(value: object) -> bool:
    try:
        return Decimal(str(value)) <= 0
    except (InvalidOperation, ValueError):
        return False


def _value_quality(ev: Evidence) -> int:
    """Shape-only quality of a candidate value (lower = better)."""

    fact_type = ev.fact_type
    if fact_type in _PRICE_FACT_TYPES:
        return 1 if non_positive_money(ev.value) or parse_money(ev.value) is None else 0
    if fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE:
        return 0 if _is_iso4217_shape(ev.value) else 1
    if fact_type == field_mappings.OFFER_AVAILABILITY_FACT_TYPE:
        return 0 if _is_canonical_availability(ev.value) else 1
    if fact_type in _GTIN_FACT_TYPES:
        return 0 if validate_gtin(ev.value) else 1
    if fact_type in _URL_FACT_TYPES:
        return 0 if _is_absolute_url(ev.value) else 1
    return 0


def _is_iso4217_shape(value: object) -> bool:
    text = str(value or "").strip()
    return len(text) == 3 and text.isalpha()


def _is_canonical_availability(value: object) -> bool:
    text = str(value or "").strip().casefold().replace(" ", "_")
    return text in AVAILABILITY_CANONICAL_ENUM


def _is_absolute_url(value: object) -> bool:
    parts = urlsplit(str(value or "").strip())
    return parts.scheme in {"http", "https"} and bool(parts.netloc)


def rank(ev: Evidence) -> tuple[object, ...]:
    quality = _value_quality(ev)
    directness = {"direct": 0, "embedded": 1, "inferred": 2}.get(ev.directness, 3)
    reliability = {
        "jsonld": 0,
        "microdata": 1,
        "js_state": 2,
        "network": 3,
        "opengraph": 4,
        "dom": 5,
        "css_recipe": 5,
        "url": 6,
    }.get(ev.collector_id, 7)
    default = (reliability, directness, -float(ev.confidence), ev.evidence_id)
    if ev.fact_type == field_mappings.PRODUCT_TITLE_FACT_TYPE:
        pollution = int(
            "seo_title_pollution" in ev.flags or "truncated_title" in ev.flags
        )
        source_role = str(ev.metadata.get(DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY) or "")
        source_authority = DETAIL_TITLE_SOURCE_ROLE_RANKS.get(
            source_role, len(DETAIL_TITLE_SOURCE_ROLE_RANKS)
        )
        url_disagreement = int("title_url_mismatch" in ev.flags)
        return (
            quality,
            pollution,
            source_authority,
            *detail_title_rank_components(ev.flags, ev.metadata),
            url_disagreement,
            reliability,
            directness,
            -float(ev.confidence),
            -len(str(ev.value or "")),
            ev.evidence_id,
        )
    if ev.fact_type == field_mappings.PRODUCT_URL_FACT_TYPE:
        return (quality, *detail_url_rank_components(ev.flags), *default)
    if ev.fact_type == "product.description":
        boundary_excerpt = int("description_hard_boundary" in ev.flags)
        return (quality, boundary_excerpt, *default)
    if ev.fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE:
        inferred_from_symbol = int(
            str(ev.metadata.get("derived_by") or "") == "currency_from_price_symbol"
        )
        return (quality, inferred_from_symbol, *default)
    if ev.fact_type == field_mappings.PRODUCT_BRAND_FACT_TYPE:
        derived_penalty = int(bool(ev.metadata.get("derived_by")))
        role_rank = {
            "manufacturer": 0,
            "designer": 0,
            "private_label": 0,
            "vendor": 1,
            "unknown": 2,
            "seller": 5,
            "retailer": 5,
            "marketplace": 5,
            "site_identity": 5,
        }.get(ev.brand_role or "manufacturer", 2)
        derived_rank = {
            "brand_from_product_url": 0,
            "brand_from_title_marker": 1,
            "page_identity": 2,
            "brand_from_title_host": 3,
        }.get(str(ev.metadata.get("derived_by") or ""), 1)
        return (
            quality,
            role_rank,
            derived_penalty,
            reliability,
            directness,
            derived_rank,
            -float(ev.confidence),
            ev.evidence_id,
        )
    return (quality, *default)
