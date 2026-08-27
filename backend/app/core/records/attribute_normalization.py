"""Normalization for published product attributes.

Owns the source-shape cleanups that stand between raw evidence and a published
attribute: field labels a DOM cell carries with an identifier, GTIN check-digit
validation, and schema.org enumerations that arrive as bare words or as full
enumeration URLs.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_SCHEMA_CONDITION_VALUES,
    DETAIL_SCHEMA_ENUM_SUFFIXES,
    DETAIL_SCHEMA_GENDER_VALUES,
    DETAIL_URL_GENDER_MARKERS,
)
from app.core.shared.field_coerce_text import strip_identifier_label_prefix
from app.core.config.locale_format_rules import GTIN_LENGTHS, validate_gtin

__all__ = ["audience_gender_from_path", "normalize_product_attribute_value"]

_SCHEMA_ENUM_VOCABULARIES = {
    field_mappings.PRODUCT_GENDER_FACT_TYPE: DETAIL_SCHEMA_GENDER_VALUES,
    field_mappings.PRODUCT_CONDITION_FACT_TYPE: DETAIL_SCHEMA_CONDITION_VALUES,
}


def normalize_product_attribute_value(
    fact_type: str, value: str, flags: set[str]
) -> str:
    return _schema_enum_value(fact_type, _identifier_value(fact_type, value, flags))


def _identifier_value(fact_type: str, value: str, flags: set[str]) -> str:
    """Strip page furniture from identifier values and validate check digits."""
    if fact_type in field_mappings.ECOMMERCE_LABELLED_IDENTIFIER_FACT_TYPES:
        return strip_identifier_label_prefix(value)
    if fact_type not in {"product.gtin", "variant.gtin"}:
        return value
    digits = re.sub(r"\D+", "", value)
    if digits and len(digits) not in GTIN_LENGTHS:
        flags.add(field_mappings.INVALID_GTIN_SHAPE_EVIDENCE_FLAG)
    elif digits and not validate_gtin(digits):
        flags.add("invalid_gtin")
    return digits


def _schema_enum_value(fact_type: str, value: str) -> str:
    """Map a schema.org enumeration to published wording.

    Values arrive bare ("Male") or as a full enumeration URL
    ("https://schema.org/NewCondition"); only the final token carries meaning.
    """
    vocabulary = _SCHEMA_ENUM_VOCABULARIES.get(fact_type)
    if vocabulary is None:
        return value
    token = re.split(r"[/#]", value.strip())[-1]
    key = re.sub(r"[^a-z0-9]+", "", token.casefold())
    for suffix in DETAIL_SCHEMA_ENUM_SUFFIXES:
        if key != suffix and key.endswith(suffix):
            key = key[: -len(suffix)]
    return vocabulary.get(key, value)


def audience_gender_from_path(url: str) -> str | None:
    """Audience the retailer's own PDP path states, or ``None``.

    Only the path is read: a query string carries variant and tracking state
    that frequently names an unrelated department. Word boundaries keep
    ``women`` out of a token that merely contains it.
    """
    path = re.sub(r"[^a-z0-9]+", " ", urlsplit(url).path.casefold())
    for pattern, gender in DETAIL_URL_GENDER_MARKERS:
        if re.search(rf"(?<![a-z]){pattern}(?![a-z])", path):
            return gender
    return None
