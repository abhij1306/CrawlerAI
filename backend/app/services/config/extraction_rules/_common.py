from __future__ import annotations
# ruff: noqa: F401,F403,F405

import re
from pathlib import Path
from collections.abc import Iterable, Mapping
from typing import Any

from app.services.config._export_data import load_export_data
from app.services.config import extraction_price_rules as _price_rules
from app.services.config.variant_policy import (
    AXIS_NAME_ALIASES,
    PUBLIC_VARIANT_AXIS_FIELDS,
)

HTML_PARSER = "html.parser"
DETAIL_AOM_EXPAND_ROLES = frozenset({"button", "tab"})
AMAZON_PRICE_OFFSCREEN_SELECTOR = ".a-offscreen"
AMAZON_PRICE_WHOLE_SELECTOR = ".a-price-whole"
AMAZON_PRICE_FRACTION_SELECTOR = ".a-price-fraction"
AMAZON_PRICE_SYMBOL_SELECTOR = ".a-price-symbol"
AMAZON_PRICE_CONTAINER_SELECTOR = ".a-price"
AMAZON_DETAIL_PRICE_SELECTORS = (
    f"{AMAZON_PRICE_CONTAINER_SELECTOR} {AMAZON_PRICE_OFFSCREEN_SELECTOR}",
    "#priceblock_ourprice",
    "#priceblock_dealprice",
)
AMAZON_DETAIL_TABLE_IGNORED_LABELS = frozenset(
    {"best sellers rank", "customer reviews"}
)

_EXPORTS_PATH = Path(__file__).resolve().parent.parent / "extraction_rules.exports.json"
_STATIC_EXPORTS = {
    name: value
    for name, value in load_export_data(str(_EXPORTS_PATH)).items()
    if not name.startswith("_")
}

HYDRATED_STATE_PATTERNS = tuple(
    dict.fromkeys(
        [
            *( 
                value
                for value in _STATIC_EXPORTS.get("HYDRATED_STATE_PATTERNS", ())
                if str(value).strip()
            ),
            "INITIAL_STATE",
            "__INITIAL_CONFIG__",
            "_boldmetrics",
            "asos.pdp.config.product",
            "asos.pdp.config.stockPriceResponse",
        ]
    )
)
HYDRATED_STATE_GLOBAL_ONLY_PATTERNS = frozenset({"INITIAL_STATE"})
SHIPPING_DATE_FIELD = "shipping_date"
SPECIAL_DAYS_FIELD = "special_days"
IS_AVAILABLE_FIELD = "is_available"
IS_INVENTORY_ONLY_FIELD = "is_inventory_only"
SHIPPING_INVENTORY_PAYLOAD_HINT_FIELDS = frozenset(
    {
        SHIPPING_DATE_FIELD,
        SPECIAL_DAYS_FIELD,
        IS_AVAILABLE_FIELD,
        IS_INVENTORY_ONLY_FIELD,
    }
)
ECOMMERCE_DESCRIPTION_BLOCK_LIMIT = 40
DETAIL_PAYLOAD_LIST_LIMIT = 50
DETAIL_PAYLOAD_MAX_DEPTH = 12
RECORD_OVERLAY_MAX_DEPTH = 10
DETAIL_PRODUCT_IMAGE_CUE_SELECTOR = (
    "main img, article img, [role='main'] img, "
    "[class*='product' i] img, [id*='product' i] img, [data-testid*='product' i] img"
)
LISTING_VISUAL_PRICE_REGEX_PATTERN = r"(?:₹|Rs\.?|INR|\$|€|£)\s?[\d,.]+"
TRACKING_PIXEL_PATTERNS = (
    "facebook.com/tr?",
    "facebook.com/tr&id=",
    "/tr?id=",
    "doubleclick",
    "googletagmanager",
    "google-analytics",
    "pixel",
)
DETAIL_SURFACE_KEYWORD = "detail"
ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
VARIANT_AXIS_EXCLUDED_SINGLE_TOKENS = frozenset({"color", "colour", "fit", "size"})
VARIANT_COLOR_AXIS_TOKENS = frozenset({"color", "colour"})
VARIANT_SIZE_AXIS_TOKENS = frozenset({"fit", "size"})
VARIANT_DESCENDANT_SCAN_LIMIT = 24
VARIANT_SIBLING_SEARCH_DEPTH = 4
VARIANT_SELECT_OPTION_SCAN_LIMIT = 24
VARIANT_SEQUENTIAL_INTEGER_MIN_RUN = 5
VARIANT_SELECT_GROUP_MAX = 4
VARIANT_CHOICE_GROUP_MAX = 8
HASH_LINK_SELECTOR = "a[href^='#']"
VARIANT_SWATCH_BUTTON_SELECTOR = (
    "button[class*='swatch' i], button[class*='color-option' i],"
    " button[class*='color-selector' i], button[class*='size-option' i],"
    " button[class*='size-selector' i], button[class*='variant' i],"
    " button[data-option], button[data-value], button[data-size], a[href],"
    " a[class*='swatch' i],"
    " div[class*='swatch' i], div[role='radio'],"
    " [data-testid='swatch' i], [data-testid*='swatch-option' i],"
    " [data-testid*='variants-selector' i]"
)
VARIANT_COMPONENT_SIZE_STYLE_LABELS = ("jacket", "trouser", "pant", "pants")
VARIANT_COMPONENT_TYPE_ATTRIBUTES = ("data-suit-component-type",)
VARIANT_COMPONENT_TYPE_AXIS_NAME = "size"
VARIANT_SWATCH_BUTTON_LIMIT = 20
VARIANT_SWATCH_PARENT_DEPTH = 6
VARIANT_MATCHING_INPUT_LIMIT = 12
BROWSER_REQUESTED_DETAIL_SELECTOR_PRIORITY = (
    HASH_LINK_SELECTOR,
    "[role='tab'][aria-controls]",
    "button[aria-controls]",
    "[role='button'][aria-controls]",
    "[aria-expanded='false']",
    "summary",
    "details > summary",
    "button",
    "[role='button']",
    "a",
)
BROWSER_REQUESTED_DETAIL_GENERIC_TOGGLE_LABELS = frozenset(
    {
        "details",
        "description",
        "product details",
        "specification",
        "specifications",
        "materials",
        "materials and care",
    }
)

_EXTRACTION_RULES_RAW = _STATIC_EXPORTS.get("EXTRACTION_RULES", {})
EXTRACTION_RULES = (
    dict(_EXTRACTION_RULES_RAW) if isinstance(_EXTRACTION_RULES_RAW, dict) else {}
)
CONTENT_SURFACE_SANITIZE_SELECTORS = (
    "script",
    "style",
    "noscript",
    "nav",
    "footer",
    "aside",
    "form",
    "[role='navigation']",
    "[role='complementary']",
    "[aria-label*='cookie' i]",
    "[class*='cookie' i]",
    "[class*='advert' i]",
    ".sidebar",
    ".right-sidebar",
    ".left-sidebar",
    "[class~='sidebar']",
)
CONTENT_SURFACE_CONTAINER_TAGS = frozenset({"html", "body", "main", "article"})
CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS = (
    "main",
    "article",
    "[role='main']",
    "[itemprop='articleBody']",
    ".article-body",
    ".content",
    ".entry-content",
    ".post",
    ".post-content",
)
CONTENT_SURFACE_MAIN_SELECTORS = (
    "main",
    "[role='main']",
    "#pageContent",
    ".main-content",
    ".content",
    "article",
    ".post",
    ".entry-content",
)
CONTENT_SURFACE_DATE_SELECTORS = (
    "time[datetime]",
    "[itemprop='datePublished']",
    ".post-date",
    ".published",
    ".posted-on",
    ".date",
)
CONTENT_SURFACE_FORUM_BODY_SELECTORS = (
    ".post-body",
    ".message-content",
    ".thread-content",
    ".bbp-reply-content",
    "[slot='text-body']",
    "div[slot='text-body']",
    ".md",
    "article",
)
CONTENT_DETAIL_MIN_BODY_TEXT_LENGTH = 50

_CANDIDATE_IMAGE_FILE_EXTENSIONS = _STATIC_EXPORTS.get(
    "CANDIDATE_IMAGE_FILE_EXTENSIONS", ()
)
_BARE_HOST_URL_PATTERN = _STATIC_EXPORTS.get("BARE_HOST_URL_PATTERN", "")
_IMAGE_FIELDS_RAW = _STATIC_EXPORTS.get("IMAGE_FIELDS", ())
_INTEGER_VALUE_FIELDS_RAW = _STATIC_EXPORTS.get("INTEGER_VALUE_FIELDS", ())
_LONG_TEXT_FIELDS_RAW = _STATIC_EXPORTS.get("LONG_TEXT_FIELDS", ())
_PRICE_VALUE_FIELDS_RAW = _STATIC_EXPORTS.get("PRICE_VALUE_FIELDS", ())
_SEMANTIC_SECTION_NOISE = _STATIC_EXPORTS.get("SEMANTIC_SECTION_NOISE", {})
_RATING_PATTERN = _STATIC_EXPORTS.get("RATING_PATTERN", "")
_REVIEW_COUNT_PATTERN = _STATIC_EXPORTS.get("REVIEW_COUNT_PATTERN", "")
_REVIEW_TITLE_PATTERN = _STATIC_EXPORTS.get("REVIEW_TITLE_PATTERN", "")
_STRUCTURED_MULTI_FIELDS_RAW = _STATIC_EXPORTS.get("STRUCTURED_MULTI_FIELDS", ())
_STRUCTURED_OBJECT_FIELDS_RAW = _STATIC_EXPORTS.get("STRUCTURED_OBJECT_FIELDS", ())
_STRUCTURED_OBJECT_LIST_FIELDS_RAW = _STATIC_EXPORTS.get(
    "STRUCTURED_OBJECT_LIST_FIELDS", ()
)
_URL_FIELDS_RAW = _STATIC_EXPORTS.get("URL_FIELDS", ())


def _string_frozenset(value: object) -> frozenset[str]:
    values: Iterable[object]
    if isinstance(value, str):
        values = (value,)
    elif isinstance(value, Mapping):
        values = value.keys()
    elif isinstance(value, Iterable):
        values = value
    else:
        return frozenset()
    return frozenset(str(item).strip() for item in values if str(item).strip())

__all__ = [
    "annotations",
    "re",
    "Path",
    "Iterable",
    "Mapping",
    "Any",
    "load_export_data",
    "_price_rules",
    "AXIS_NAME_ALIASES",
    "PUBLIC_VARIANT_AXIS_FIELDS",
    "HTML_PARSER",
    "DETAIL_AOM_EXPAND_ROLES",
    "AMAZON_PRICE_OFFSCREEN_SELECTOR",
    "AMAZON_PRICE_WHOLE_SELECTOR",
    "AMAZON_PRICE_FRACTION_SELECTOR",
    "AMAZON_PRICE_SYMBOL_SELECTOR",
    "AMAZON_PRICE_CONTAINER_SELECTOR",
    "AMAZON_DETAIL_PRICE_SELECTORS",
    "AMAZON_DETAIL_TABLE_IGNORED_LABELS",
    "_EXPORTS_PATH",
    "_STATIC_EXPORTS",
    "HYDRATED_STATE_PATTERNS",
    "HYDRATED_STATE_GLOBAL_ONLY_PATTERNS",
    "SHIPPING_DATE_FIELD",
    "SPECIAL_DAYS_FIELD",
    "IS_AVAILABLE_FIELD",
    "IS_INVENTORY_ONLY_FIELD",
    "SHIPPING_INVENTORY_PAYLOAD_HINT_FIELDS",
    "ECOMMERCE_DESCRIPTION_BLOCK_LIMIT",
    "DETAIL_PAYLOAD_LIST_LIMIT",
    "DETAIL_PAYLOAD_MAX_DEPTH",
    "RECORD_OVERLAY_MAX_DEPTH",
    "DETAIL_PRODUCT_IMAGE_CUE_SELECTOR",
    "LISTING_VISUAL_PRICE_REGEX_PATTERN",
    "TRACKING_PIXEL_PATTERNS",
    "DETAIL_SURFACE_KEYWORD",
    "ECOMMERCE_DETAIL_SURFACE",
    "VARIANT_AXIS_EXCLUDED_SINGLE_TOKENS",
    "VARIANT_COLOR_AXIS_TOKENS",
    "VARIANT_SIZE_AXIS_TOKENS",
    "VARIANT_DESCENDANT_SCAN_LIMIT",
    "VARIANT_SIBLING_SEARCH_DEPTH",
    "VARIANT_SELECT_OPTION_SCAN_LIMIT",
    "VARIANT_SEQUENTIAL_INTEGER_MIN_RUN",
    "VARIANT_SELECT_GROUP_MAX",
    "VARIANT_CHOICE_GROUP_MAX",
    "HASH_LINK_SELECTOR",
    "VARIANT_SWATCH_BUTTON_SELECTOR",
    "VARIANT_COMPONENT_SIZE_STYLE_LABELS",
    "VARIANT_COMPONENT_TYPE_AXIS_NAME",
    "VARIANT_COMPONENT_TYPE_ATTRIBUTES",
    "VARIANT_SWATCH_BUTTON_LIMIT",
    "VARIANT_SWATCH_PARENT_DEPTH",
    "VARIANT_MATCHING_INPUT_LIMIT",
    "BROWSER_REQUESTED_DETAIL_SELECTOR_PRIORITY",
    "BROWSER_REQUESTED_DETAIL_GENERIC_TOGGLE_LABELS",
    "_EXTRACTION_RULES_RAW",
    "EXTRACTION_RULES",
    "CONTENT_SURFACE_SANITIZE_SELECTORS",
    "CONTENT_SURFACE_CONTAINER_TAGS",
    "CONTENT_SURFACE_PROTECTED_DESCENDANT_SELECTORS",
    "CONTENT_SURFACE_MAIN_SELECTORS",
    "CONTENT_SURFACE_DATE_SELECTORS",
    "CONTENT_SURFACE_FORUM_BODY_SELECTORS",
    "CONTENT_DETAIL_MIN_BODY_TEXT_LENGTH",
    "_CANDIDATE_IMAGE_FILE_EXTENSIONS",
    "_BARE_HOST_URL_PATTERN",
    "_IMAGE_FIELDS_RAW",
    "_INTEGER_VALUE_FIELDS_RAW",
    "_LONG_TEXT_FIELDS_RAW",
    "_PRICE_VALUE_FIELDS_RAW",
    "_SEMANTIC_SECTION_NOISE",
    "_RATING_PATTERN",
    "_REVIEW_COUNT_PATTERN",
    "_REVIEW_TITLE_PATTERN",
    "_STRUCTURED_MULTI_FIELDS_RAW",
    "_STRUCTURED_OBJECT_FIELDS_RAW",
    "_STRUCTURED_OBJECT_LIST_FIELDS_RAW",
    "_URL_FIELDS_RAW",
    "_string_frozenset",
]
