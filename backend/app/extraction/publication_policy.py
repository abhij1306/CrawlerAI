"""Whether a resolved detail fact may be published, and why not when it may not.

Separated from ``publication.py`` so the record-shaping code there stays
focused on projection and serialization.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Literal

from app.core.config import field_mappings
from app.extraction.contracts import CanonicalizationTrace

__all__ = ["numeric_canonicalization", "publication_disposition"]

# Facts the canonical record declares numeric (NORMALIZER_DECIMAL_FIELDS /
# NORMALIZER_INTEGER_FIELDS) but whose evidence arrives as source text. The
# conversion is a representation-only canonicalization carrying its own
# lineage, so the published value stays traceable to the evidence it came from
# and the divergence gate compares against the canonical value.
_NUMERIC_CANONICAL_FACTS: dict[str, str] = {
    field_mappings.PRODUCT_RATING_FACT_TYPE: "decimal",
    field_mappings.PRODUCT_REVIEW_COUNT_FACT_TYPE: "integer",
}
_NUMERIC_CANONICALIZER_VERSION = "1"

_PRICE_FACTS = {
    field_mappings.OFFER_PRICE_FACT_TYPE,
    field_mappings.OFFER_ORIGINAL_PRICE_FACT_TYPE,
    "offer.price_min",
    "offer.price_max",
}


def publication_disposition(
    *,
    fact_type: str,
    value: object,
    variant_skus: set[str],
    product_declared: bool = False,
    has_primary_price: bool,
    has_child_price: bool,
    has_primary_currency: bool,
) -> tuple[Literal["publish", "suppress", "review"], str | None]:
    # A variant SKU must not be promoted to the parent, but a SKU the product
    # node declares is its own identifier even if a variant repeats it.
    if (
        fact_type == field_mappings.PRODUCT_SKU_FACT_TYPE
        and not product_declared
        and len(variant_skus) > 1
        and str(value) in variant_skus
    ):
        return "suppress", "parent_sku_is_variant_specific"
    if fact_type in _PRICE_FACTS and not has_primary_currency:
        return "suppress", "currency_unresolved"
    if fact_type == field_mappings.OFFER_CURRENCY_FACT_TYPE and not (
        has_primary_price or has_child_price
    ):
        return "suppress", "price_unresolved"
    return "publish", None


def numeric_canonicalization(
    fact_type: str, value: object
) -> CanonicalizationTrace | None:
    """Canonicalize a numeric-typed fact's source text to its declared type.

    Returns ``None`` when the fact is not numeric-typed or the source text does
    not parse, so an unparseable value stays published as the text it came from
    rather than being dropped.
    """
    kind = _NUMERIC_CANONICAL_FACTS.get(fact_type)
    if kind is None or isinstance(value, bool) or value is None:
        return None
    try:
        number = Decimal(str(value).strip().replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
    if kind == "integer":
        if number != number.to_integral_value():
            return None
        canonical: object = int(number)
    else:
        canonical = float(number)
    if canonical == value:
        return None
    return CanonicalizationTrace(
        raw_value=value,
        canonical_value=canonical,
        canonicalizer_id=f"numeric_{kind}",
        canonicalizer_version=_NUMERIC_CANONICALIZER_VERSION,
    )
