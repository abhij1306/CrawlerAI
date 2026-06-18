from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

from . import _common as _common_exports
from . import _detail as _detail_exports
from ._common import *
from ._detail import *

DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS = (
    r"\b(?:shipping|delivery|pickup|pick\s*up)\b.{0,80}\b(?:checkout|options?|available)\b",
    r"\bget\s+it\s+today\b.{0,120}\b(?:shipping|delivery|pickup|pick\s*up)\b",
)
DETAIL_NOISE_SECTION_SELECTORS = (
    "[id*='recently-viewed']",
    "[class*='recently-viewed']",
    "[id*='similar-products']",
    "[class*='similar-products']",
    "[id*='recommendations']",
    "[class*='recommendations']",
    "[id*='people-also-bought']",
    "[class*='people-also-bought']",
    ".upsell",
    ".related-products",
)
DETAIL_IDENTITY_FIELDS = frozenset({"title", "image_url"})
VARIANT_FIELDS = frozenset({"variants"})

_LOCAL_EXPORTS = (
    "DETAIL_FULFILLMENT_LONG_TEXT_PATTERNS",
    "DETAIL_IDENTITY_FIELDS",
    "DETAIL_NOISE_SECTION_SELECTORS",
    "VARIANT_FIELDS",
)
__all__ = sorted((*_common_exports.__all__, *_detail_exports.__all__, *_LOCAL_EXPORTS))
