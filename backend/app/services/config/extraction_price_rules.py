from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from app.services.config._export_data import load_export_data

_EXPORTS_PATH = Path(__file__).with_name("extraction_rules.exports.json")
_STATIC_EXPORTS: dict[str, Any] = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}


def _static_export_tuple(key: str, default: tuple[Any, ...] = ()) -> tuple[Any, ...]:
    return tuple(_STATIC_EXPORTS.get(key, default) or ())

DETAIL_PRICE_CENT_MAGNITUDE_RATIO = 100
DETAIL_PRICE_MAGNITUDE_EPSILON = 0.01
DETAIL_PRICE_COMPARISON_TOLERANCE = Decimal("0.01")
DETAIL_VISIBLE_PRICE_MAGNITUDE_RATIOS = (10, 100)
DETAIL_LOW_SIGNAL_PRICE_MAX = Decimal("1")
DETAIL_LOW_SIGNAL_PARENT_MIN = Decimal("10")
DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX = Decimal("2")

DEFAULT_DECIMAL_PLACES = 2
CURRENCY_DECIMAL_PLACES = {
    "BIF": 0,
    "CLP": 0,
    "DJF": 0,
    "GNF": 0,
    "JPY": 0,
    "KMF": 0,
    "KRW": 0,
    "PYG": 0,
    "RWF": 0,
    "UGX": 0,
    "VND": 0,
    "VUV": 0,
    "XAF": 0,
    "XOF": 0,
    "XPF": 0,
}

DETAIL_ORIGINAL_PRICE_SELECTORS = (
    *_static_export_tuple("DETAIL_ORIGINAL_PRICE_SELECTORS"),
    "s",
    "del",
    "[class*='compare' i][class*='price' i]",
    "[class*='regular' i][class*='price' i]",
    "[class*='original' i][class*='price' i]",
    "[class*='was' i][class*='price' i]",
    "[class*='old' i][class*='price' i]",
    "[class*='strike' i][class*='price' i]",
    "[data-testid*='regular-price' i]",
    "[data-testid*='original-price' i]",
    "[aria-label*='original price' i]",
    "[aria-label*='regular price' i]",
    "[aria-label*='was price' i]",
)
DETAIL_CURRENT_PRICE_SELECTORS = (
    *_static_export_tuple("DETAIL_CURRENT_PRICE_SELECTORS"),
    "button[aria-label*='$']",
    "button[aria-label*='₹']",
    "button[aria-label*='Rs' i]",
    "button[class*='add' i][class*='bag' i]",
    "button[class*='add' i][class*='cart' i]",
    "button[name*='add' i]",
    "[role='button'][aria-label*='$']",
    "[role='button'][aria-label*='₹']",
    "[role='button'][aria-label*='Rs' i]",
    "[aria-label*='$'][class*='buy' i]",
    "[aria-label*='₹'][class*='buy' i]",
    "[aria-label*='Rs' i][class*='buy' i]",
    "[aria-label*='$'][data-testid*='buy' i]",
    "[aria-label*='₹'][data-testid*='buy' i]",
    "[aria-label*='Rs' i][data-testid*='buy' i]",
)
DETAIL_JSONLD_GRAPH_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple("DETAIL_JSONLD_GRAPH_FIELDS", ("@graph",))
    if str(field).strip()
)
DETAIL_JSONLD_TYPE_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple("DETAIL_JSONLD_TYPE_FIELDS", ("@type",))
    if str(field).strip()
)
DETAIL_JSONLD_OFFER_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple(
        "DETAIL_JSONLD_OFFER_FIELDS",
        ("offers", "offer"),
    )
    if str(field).strip()
)
DETAIL_JSONLD_PRICE_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple(
        "DETAIL_JSONLD_PRICE_FIELDS",
        ("price", "lowPrice"),
    )
    if str(field).strip()
)
DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple(
        "DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS",
        ("highPrice",),
    )
    if str(field).strip()
)
DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple(
        "DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS",
        ("priceSpecification",),
    )
    if str(field).strip()
)
DETAIL_JSONLD_CURRENCY_FIELDS = tuple(
    str(field).strip()
    for field in _static_export_tuple(
        "DETAIL_JSONLD_CURRENCY_FIELDS",
        ("priceCurrency", "currency"),
    )
    if str(field).strip()
)
DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS = (
    "afterpay",
    "affirm",
    "installment",
    "klarna",
    "monthly payment",
    "pay in",
    "payments of",
    "per month",
)
DETAIL_RELATED_PRICE_CONTEXT_TOKENS = (
    "add-on",
    "addon",
    "product-set",
    "sticky",
)
DETAIL_AUTHORITATIVE_PRICE_SOURCES = ("adapter", "json_ld", "network_payload")
DETAIL_STRICT_PARENT_PRICE_SOURCES = ("network_payload",)
DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCE_SET = frozenset(
    _static_export_tuple("DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCES")
)
DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET = frozenset(DETAIL_AUTHORITATIVE_PRICE_SOURCES)
DETAIL_STRICT_PARENT_PRICE_SOURCE_SET = frozenset(DETAIL_STRICT_PARENT_PRICE_SOURCES)
DETAIL_CENT_BASED_PRICE_CURRENCY_SET = frozenset(
    _static_export_tuple("DETAIL_CENT_BASED_PRICE_CURRENCIES")
)
DETAIL_VISIBLE_PRICE_MAGNITUDE_RATIOS_DECIMAL = tuple(
    Decimal(str(ratio))
    for ratio in DETAIL_VISIBLE_PRICE_MAGNITUDE_RATIOS
    if Decimal(str(ratio)) > 0
)
DETAIL_PRICE_CENT_MAGNITUDE_RATIO_DECIMAL = Decimal(
    str(DETAIL_PRICE_CENT_MAGNITUDE_RATIO)
)
DETAIL_PRICE_MAGNITUDE_EPSILON_DECIMAL = Decimal(str(DETAIL_PRICE_MAGNITUDE_EPSILON))
DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX_DECIMAL = Decimal(
    str(DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX)
)
DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS_NORMALIZED = tuple(
    str(token).strip().lower()
    for token in tuple(DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS or ())
    if str(token).strip()
)
DETAIL_PRICE_JSONLD_TYPE_RE = re.compile(
    str(_STATIC_EXPORTS.get("DETAIL_PRICE_JSONLD_TYPE_PATTERN", r"\bOffer\b"))
)
DETAIL_PRICE_JSONLD_RE = re.compile(
    str(_STATIC_EXPORTS.get("DETAIL_PRICE_JSONLD_PATTERN", r"\bprice\b"))
)
DETAIL_CURRENCY_JSONLD_RE = re.compile(
    str(_STATIC_EXPORTS.get("DETAIL_CURRENCY_JSONLD_PATTERN", r"\bpriceCurrency\b"))
)

__all__ = [
    "CURRENCY_DECIMAL_PLACES",
    "DEFAULT_DECIMAL_PLACES",
    "DETAIL_AUTHORITATIVE_PRICE_SOURCE_SET",
    "DETAIL_CENT_BASED_PRICE_CURRENCY_SET",
    "DETAIL_CURRENCY_JSONLD_RE",
    "DETAIL_CURRENT_PRICE_SELECTORS",
    "DETAIL_INSTALLMENT_PRICE_TEXT_TOKENS_NORMALIZED",
    "DETAIL_JSONLD_CURRENCY_FIELDS",
    "DETAIL_JSONLD_GRAPH_FIELDS",
    "DETAIL_JSONLD_OFFER_FIELDS",
    "DETAIL_JSONLD_ORIGINAL_PRICE_FIELDS",
    "DETAIL_JSONLD_PRICE_FIELDS",
    "DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS",
    "DETAIL_JSONLD_TYPE_FIELDS",
    "DETAIL_LOW_SIGNAL_PARENT_MIN",
    "DETAIL_LOW_SIGNAL_PRICE_MAX",
    "DETAIL_LOW_SIGNAL_ZERO_PRICE_SOURCE_SET",
    "DETAIL_ORIGINAL_PRICE_SELECTORS",
    "DETAIL_PARENT_VARIANT_PRICE_RATIO_MAX_DECIMAL",
    "DETAIL_PRICE_CENT_MAGNITUDE_RATIO_DECIMAL",
    "DETAIL_PRICE_COMPARISON_TOLERANCE",
    "DETAIL_PRICE_JSONLD_RE",
    "DETAIL_PRICE_JSONLD_TYPE_RE",
    "DETAIL_PRICE_MAGNITUDE_EPSILON_DECIMAL",
    "DETAIL_RELATED_PRICE_CONTEXT_TOKENS",
    "DETAIL_STRICT_PARENT_PRICE_SOURCE_SET",
    "DETAIL_VISIBLE_PRICE_MAGNITUDE_RATIOS_DECIMAL",
]
