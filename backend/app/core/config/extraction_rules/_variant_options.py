from __future__ import annotations

import re

VARIANT_OPTION_OUT_OF_STOCK_CLASS_TOKENS = (
    "outstock",
    "out-stock",
    "soldout",
    "sold-out",
    "unavailable",
    "oos",
    "no-stock",
    "nostock",
)
VARIANT_OPTION_DISABLED_CLASS_TOKENS = ("disabled", "is-disabled")
VARIANT_OPTION_DISABLED_ATTRIBUTE_NAMES = ("disabled", "aria-disabled")
VARIANT_OPTION_OUT_OF_STOCK_FLAG_ATTRIBUTE_NAMES = (
    "data-oos",
    "data-out-of-stock",
    "data-outofstock",
    "data-sold-out",
    "data-soldout",
    "data-unavailable",
)
VARIANT_OPTION_AVAILABLE_FLAG_ATTRIBUTE_NAMES = (
    "data-available",
    "data-in-stock",
    "data-instock",
)
VARIANT_OPTION_FLAG_FALSE_VALUES = frozenset(
    {"0", "false", "no", "none", "off", "out", "outofstock", "out_of_stock"}
)
VARIANT_OPTION_OUT_OF_STOCK_TEXT_PHRASES = ("out of stock", "sold out")
VARIANT_OPTION_IN_STOCK_TEXT_PHRASES = ("in stock", "available")
VARIANT_OPTION_STOCK_LEFT_PATTERN = re.compile(r"\b(\d+)\s+left\b")
VARIANT_OPTION_SELECTED_CLASS_TOKENS = (
    "selected",
    "active",
    "current",
    "highlight",
    "checked",
)
VARIANT_OPTION_SELECTED_TRUTHY_ATTRIBUTES = (
    "aria-checked",
    "aria-selected",
    "aria-current",
    "aria-pressed",
)
VARIANT_OPTION_SELECTED_STATE_VALUES = frozenset({"checked", "selected", "active"})

__all__ = [
    "VARIANT_OPTION_AVAILABLE_FLAG_ATTRIBUTE_NAMES",
    "VARIANT_OPTION_DISABLED_ATTRIBUTE_NAMES",
    "VARIANT_OPTION_DISABLED_CLASS_TOKENS",
    "VARIANT_OPTION_FLAG_FALSE_VALUES",
    "VARIANT_OPTION_IN_STOCK_TEXT_PHRASES",
    "VARIANT_OPTION_OUT_OF_STOCK_CLASS_TOKENS",
    "VARIANT_OPTION_OUT_OF_STOCK_FLAG_ATTRIBUTE_NAMES",
    "VARIANT_OPTION_OUT_OF_STOCK_TEXT_PHRASES",
    "VARIANT_OPTION_SELECTED_CLASS_TOKENS",
    "VARIANT_OPTION_SELECTED_STATE_VALUES",
    "VARIANT_OPTION_SELECTED_TRUTHY_ATTRIBUTES",
    "VARIANT_OPTION_STOCK_LEFT_PATTERN",
]
