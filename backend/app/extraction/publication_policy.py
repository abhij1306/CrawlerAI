"""Whether a resolved detail fact may be published, and why not when it may not.

Separated from ``publication.py`` so the record-shaping code there stays
focused on projection and serialization.
"""

from __future__ import annotations

from typing import Literal

from app.core.config import field_mappings

__all__ = ["publication_disposition"]

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
