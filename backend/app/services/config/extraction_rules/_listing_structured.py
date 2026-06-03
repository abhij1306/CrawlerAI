from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

from ._common import *
from ._images import *
from ._detail import *
from ._detail_sections import *
from ._variants import *
from ._common import (
    AXIS_NAME_ALIASES,
    HASH_LINK_SELECTOR,
    PUBLIC_VARIANT_AXIS_FIELDS,
    _IMAGE_FIELDS_RAW,
    _INTEGER_VALUE_FIELDS_RAW,
    _LONG_TEXT_FIELDS_RAW,
    _PRICE_VALUE_FIELDS_RAW,
    _RATING_PATTERN,
    _REVIEW_COUNT_PATTERN,
    _REVIEW_TITLE_PATTERN,
    _SEMANTIC_SECTION_NOISE,
    _STATIC_EXPORTS,
    _STRUCTURED_MULTI_FIELDS_RAW,
    _STRUCTURED_OBJECT_FIELDS_RAW,
    _STRUCTURED_OBJECT_LIST_FIELDS_RAW,
    _URL_FIELDS_RAW,
    re,
)

BELK_PRODUCT_BARCODE_KEYS = (
    "sku_upc",
    "skuUpc",
    "UPC",
    "upc",
    "barcode",
    "barCode",
    "gtin",
    "gtin8",
    "gtin12",
    "gtin13",
    "gtin14",
    "ean",
)
# Belk React PDP `utag_data` per-SKU parallel arrays. Each index is one sellable
# variant; arrays are positionally aligned (sku_id[i] <-> sku_upc[i] <-> ...).
BELK_SKU_ARRAY_ID_KEY = "sku_id"
BELK_SKU_ARRAY_UPC_KEY = "sku_upc"
BELK_SKU_ARRAY_PRICE_KEY = "sku_price"
BELK_SKU_ARRAY_ORIGINAL_PRICE_KEY = "sku_original_price"
BELK_SKU_ARRAY_INVENTORY_KEY = "sku_inventory"
BELK_SKU_ARRAY_OUT_OF_STOCK_KEY = "sku_out_of_stock"
BELK_SKU_ARRAY_IMAGE_KEY = "sku_image_url"
# Variant objects elsewhere in the RSC payload carry the size/color labels and a
# `variantId` that joins to the `sku_id` array.
BELK_VARIANT_ID_KEYS = ("variantId", "variant_id", "id")
# Belk's `colorSizeMap` carries a `colors` dict mapping the numeric color code
# (the variant object's `color` value, e.g. "289475425516") to its display name
# ({"289475425516": {"name": "Tan", ...}}). Multi-colorway PDPs expose several
# codes; each variant resolves its own colorway through this map.
BELK_COLOR_MAP_KEY = "colors"
BELK_COLOR_NAME_KEYS = ("name", "label", "displayName", "colorName")
FEATURE_SECTION_SELECTORS = (
    "[data-section='features']",
    ".features",
    ".product-features",
    "#features",
    "#features_section",
)
DETAIL_MATERIALS_ZERO_PERCENT_PATTERN = r"\b0\s*%"
FEATURE_ROW_NOISE_PATTERNS = (
    r"^(?:key\s+)?features?(?:\s*&\s*benefits?)?$",
    r"^(?:see|show)\s+more\s+(?:key\s+)?features?(?:\s*&\s*benefits?)?$",
    r"^.+?\$\d[\d,.]*\s+add\s+to\s+(?:bag|cart|basket)$",
    r"^\d{6,}$",
)
DETAIL_BRACKET_PROSE_MIN_WORDS = 5
PRICE_SOURCE_KEY_FIELDS = frozenset(
    {"price", "sale_price", "original_price", "compare_at_price"}
)
DETAIL_IDENTITY_STOPWORDS = frozenset(
    {
        "and",
        "buy",
        "fit",
        "for",
        "men",
        "online",
        "oversized",
        "product",
        "products",
        "shirt",
        "shirts",
        "souled",
        "store",
        "tee",
        "tees",
        "the",
        "tshirt",
        "tshirts",
        "women",
    }
)
DETAIL_GENERIC_TERMINAL_TOKENS = frozenset(
    {
        "color",
        "colors",
        "detail",
        "dp",
        "job",
        "jobs",
        "p",
        "product",
        "productpage",
        "products",
        "release",
        "size",
        "sizes",
        "style",
        "styles",
        "variant",
        "variants",
        "width",
        "widths",
    }
)
JOB_LISTING_DETAIL_ROOT_MARKERS = frozenset(
    {"job", "jobs", "opening", "position", "posting", "career", "careers"}
)
JOB_POSTING_PATH_MARKERS = tuple(
    dict.fromkeys(
        (
            *tuple(_STATIC_EXPORTS.get("JOB_LISTING_DETAIL_PATH_MARKERS", ()) or ()),
            "/career/",
            "/careers/",
            "/opening/",
            "/openings/",
            "/position/",
            "/positions/",
            "/posting/",
            "/postings/",
            "/requisition/",
            "/requisitions/",
            "/role/",
            "/roles/",
            "/vacancy/",
            "/vacancies/",
        )
    )
)
JOB_LISTING_HUB_TITLE_PREFIXES = (
    "remote ",
)
JOB_LISTING_HUB_TITLE_SUFFIXES = (
    " jobs",
    " careers",
    " openings",
)
JOB_LISTING_HUB_TERMINAL_SUFFIXES = (
    "-jobs",
    "-careers",
    "-openings",
)
DETAIL_IDENTITY_CODE_MIN_LENGTH = 8
DETAIL_TITLE_FALLBACK_CODE_PATTERN = r"[A-Za-z0-9]{4,12}"
DETAIL_TITLE_FALLBACK_MIN_SEMANTIC_TOKENS = 2
DETAIL_TITLE_FALLBACK_ROUTE_TOKENS = frozenset({"dp", "s"})
DETAIL_MODEL_NUMBER_TOKEN_PATTERNS = (
    (
        r"(?<![A-Za-z0-9])(?=[A-Za-z0-9_-]*[A-Za-z])"
        r"(?=[A-Za-z0-9_-]*\d)[A-Za-z0-9][A-Za-z0-9_-]{2,}"
        r"[A-Za-z0-9](?![A-Za-z0-9])"
    ),
    (
        r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*[A-Za-z])"
        r"(?=[A-Za-z0-9]*\d)[A-Za-z0-9]{2,12}(?![A-Za-z0-9])"
    ),
    r"(?<![A-Za-z0-9])\d{5,}(?![A-Za-z0-9])",
)
DETAIL_MODEL_SMALL_NUMERIC_TOKEN_PATTERN = (
    r"(?<![A-Za-z0-9])\d{1,4}(?![A-Za-z0-9])"  # nosec B105
)
DETAIL_MODEL_CONFLICT_MIN_SHARED_WORDS = 2
REMOTE_BOOLEAN_TRUE_TOKENS = frozenset(
    {"true", "1", "yes", "remote", "fully remote", "work from home", "telecommute"}
)
REMOTE_BOOLEAN_FALSE_TOKENS = frozenset(
    {"false", "0", "no", "onsite", "on site", "office"}
)
DETAIL_CROSS_PRODUCT_TEXT_TYPE_TOKENS = frozenset(
    {
        "boot",
        "boots",
        "dress",
        "jacket",
        "oxford",
        "oxfords",
        "pants",
        "sandal",
        "sandals",
        "shirt",
        "shoe",
        "shoes",
        "sneaker",
        "sneakers",
        "t-shirt",
        "tee",
    }
)
DETAIL_CROSS_PRODUCT_TEXT_GENERIC_TOKENS = frozenset(
    {
        "casual",
        "dress",
        "lace",
        "men",
        "mens",
        "shoe",
        "shoes",
        "the",
        "up",
        "with",
        "women",
        "womens",
    }
)
DETAIL_TITLE_DIMENSION_SIZE_PATTERN = r"\b\d{2,}(?:\.\d+)?\s*(?:\"|in\.?|inch|inches)"
DETAIL_DOM_SCALAR_SIZE_PATTERN = (
    r"\bsize\b\s*[:\-]?\s*"
    r"("
    r"\d+(?:\.\d+)?\s*(?:fl\.?\s*oz|oz|g|kg|mg|ml|l|lb|lbs)\b"
    r"(?:\s*/\s*\d+(?:\.\d+)?\s*(?:fl\.?\s*oz|oz|g|kg|mg|ml|l|lb|lbs)\b)?"
    r")"
)
DETAIL_LOW_SIGNAL_NUMERIC_SIZE_MAX = 4
DETAIL_LONG_TEXT_SOURCE_RANKS = {
    "adapter": 0,
    "network_payload": 1,
    "dom_sections": 2,
    "selector_rule": 3,
    "dom_selector": 4,
    "json_ld": 5,
    "microdata": 6,
    "embedded_json": 7,
    "js_state": 8,
    "opengraph": 9,
    "dom_h1": 10,
    "dom_canonical": 11,
    "dom_images": 12,
    "dom_text": 13,
}
DETAIL_LONG_TEXT_THIN_DESCRIPTION_WORDS = 18
IMAGE_FIELDS = frozenset(_IMAGE_FIELDS_RAW)
INTEGER_VALUE_FIELDS = frozenset(_INTEGER_VALUE_FIELDS_RAW)
LONG_TEXT_FIELDS = frozenset(
    field_name
    for field_name in tuple(_LONG_TEXT_FIELDS_RAW or ())
    if str(field_name) != "features"
)
DETAIL_LONG_TEXT_RANK_FIELDS = frozenset({*LONG_TEXT_FIELDS, "features"})
LISTING_PRICE_NODE_SELECTORS = (
    "[itemprop='price']",
    "[class*='price']",
    "[class*='text-red']",
    "[data-testid*='price']",
    "[data-price]",
    "[aria-label*='price']",
)
LISTING_PROMINENT_TITLE_TAGS = frozenset(
    {"strong", "b", "h1", "h2", "h3", "h4", "h5", "h6"}
)
LISTING_CHROME_TEXT_LIMIT = 800
LISTING_CATEGORY_PATH_PREFIXES = (
    "/c/",
    "/category/",
    "/categories/",
    "/collection/",
    "/collections/",
    "/catalog/",
    "/browse/",
    "/plp/",
    "/clp/",
)
LISTING_CATEGORY_PATH_SEGMENTS = frozenset({"productlist"})
LISTING_STRUCTURAL_QUERY_CATEGORY_TOKENS = ("categor",)
LISTING_STRUCTURAL_QUERY_FILTER_TOKENS = ("price", "rf=")
LISTING_PRODUCT_DETAIL_ID_RE = re.compile(
    r"(?:^|[/?#&])(?:id(?:=|%3d))?[a-z0-9_-]*\d{4,}[a-z0-9_-]*-product(?:$|[/?#&])",
    re.I,
)
JSON_RECORD_LIST_KEYS = (
    "data",
    "edges",
    "entries",
    "items",
    "jobs",
    "listings",
    "nodes",
    "posts",
    "products",
    "records",
    "results",
)
PRICE_VALUE_FIELDS = frozenset(_PRICE_VALUE_FIELDS_RAW)
SEMANTIC_SECTION_LABEL_SKIP_TOKENS = tuple(
    sorted(
        {
            *(
                str(token).lower()
                for token in (_SEMANTIC_SECTION_NOISE.get("label_skip_tokens") or ())
            ),
            "answer",
            "answers",
            "q&a",
            "question",
            "questions",
            "rating snapshot",
            "review",
            "reviews",
        }
    )
)
RATING_RE = re.compile(str(_RATING_PATTERN), re.I)
REVIEW_COUNT_RE = re.compile(str(_REVIEW_COUNT_PATTERN), re.I)
REVIEW_TITLE_RE = re.compile(str(_REVIEW_TITLE_PATTERN), re.I)
STRUCTURED_MULTI_FIELDS = frozenset(
    {*tuple(_STRUCTURED_MULTI_FIELDS_RAW or ()), "features"}
)
_detail_expand_selectors_base = tuple(
    _STATIC_EXPORTS.get("DETAIL_EXPAND_SELECTORS", ()) or ()
)
_detail_expand_selectors_ordered: list[str] = []
_detail_expand_anchor_inserted = False
for _selector in _detail_expand_selectors_base:
    if _selector == "button" and not _detail_expand_anchor_inserted:
        _detail_expand_selectors_ordered.append(HASH_LINK_SELECTOR)
        _detail_expand_anchor_inserted = True
    _detail_expand_selectors_ordered.append(str(_selector))
if not _detail_expand_anchor_inserted:
    _detail_expand_selectors_ordered.append(HASH_LINK_SELECTOR)
DETAIL_EXPAND_SELECTORS = tuple(dict.fromkeys(_detail_expand_selectors_ordered))
STRUCTURED_OBJECT_FIELDS = frozenset(_STRUCTURED_OBJECT_FIELDS_RAW)
STRUCTURED_OBJECT_LIST_FIELDS = frozenset(_STRUCTURED_OBJECT_LIST_FIELDS_RAW)
URL_FIELDS = frozenset(_URL_FIELDS_RAW)

NON_PRODUCT_IMAGE_HINTS = tuple(
    dict.fromkeys(
        [
            *tuple(_STATIC_EXPORTS.get("NON_PRODUCT_IMAGE_HINTS", ())),
            "arrow",
            "blank",
            "loading",
            "loding",
            "placeholder",
            "spinner",
            "via.placeholder.com",
            "white.svg",
            # Shipping badges and delivery-time indicators.
            "shipping",
            "sameday",
            "same-day",
            "shipsintime",
            "shipstime",
            # Swatch/DYO icons (narrowed to path segments to preserve variant thumbnails).
            "/swatch/",
            "_swatch.",
            "dyo-icon",
            "/static-dyo/",
            "/media/catalog/category/",
            "/category/",
            "dropdown",
        ]
    )
)
DETAIL_NON_PRODUCT_IMAGE_URL_HINTS = (
    "/media/catalog/category/",
    "/category/",
    "/library-sites-sharedlibrary/",
    "/search-page-",
    "_nav.",
    "-nav.",
    "dropdown",
)
PAGE_URL_CURRENCY_HINTS_RAW = {
    **dict(_STATIC_EXPORTS.get("PAGE_URL_CURRENCY_HINTS_RAW", {})),
    "firstcry.com/": "INR",
    "converse.com/": "USD",
    "gymshark.com/": "USD",
    "myntra.com/": "INR",
    "notre-shop.com/": "USD",
    "onepeloton.com/": "USD",
    "patagonia.com/": "USD",
    "phase-eight.com/": "GBP",
    "yeti.com/": "USD",
}
VARIANT_AXIS_ALIASES = {
    **dict(_STATIC_EXPORTS.get("VARIANT_AXIS_ALIASES", {})),
    **dict(AXIS_NAME_ALIASES),
    "part_or_kit": "bundle_type",
    "style_and_size": "size",
}
VARIANT_CHOICE_GROUP_SELECTOR = ", ".join(
    dict.fromkeys(
        (
            *(
                str(value).strip()
                for value in str(
                    _STATIC_EXPORTS.get("VARIANT_CHOICE_GROUP_SELECTOR", "")
                ).split(",")
                if str(value).strip()
            ),
            "[data-testid*='variants-selector' i]",
            "[role='group'][aria-label]",
            "[class*='selectable-container' i]",
            "#productSizeStock",
            "[class*='sizeOptions' i]",
        )
    )
)
VARIANT_SIZE_VALUE_PATTERNS = tuple(
    dict.fromkeys(
        (
            *tuple(_STATIC_EXPORTS.get("VARIANT_SIZE_VALUE_PATTERNS", ()) or ()),
            r"^(?:(?:eu|uk|us|cm|mm)[-\s]?)?\d{1,3}(?:\.\d+)?(?:/\d{1,3}(?:\.\d+)?)?$",
            r"^m\s*\d+(?:\.\d+)?\s*/\s*w\s*\d+(?:\.\d+)?$",
            r"^\d+(?:\.\d+)?/\d+(?:\.\d+)?\s+us\s+\(\d+\s+eu\)$",
            r"^(?:xxxs|xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]xl)\s*\(?(?:\d{1,3}(?:\s*[-–]\s*\d{1,3})?)\)?$",
            r"^(?:xxxs|xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]xl)\s*/\s*(?:xxxs|xxs|xs|s|m|l|xl|xxl|xxxl|[2-6]xl)$",
            # Numeric footwear size with a trailing US/EU width code (e.g. 10M,
            # 8.5W, 11.5XW, 9N, 7D). Width codes use the standard letter system
            # (AAAA..EEEE, [2-6]E) plus narrow/medium/wide abbreviations. Apparel
            # band+cup sizes (32A, 34DD) match the same shape and are also sizes.
            r"^(?:(?:eu|uk|us)[-\s]?)?\d{1,2}(?:\.\d+)?\s?"
            r"(?:aaaa|aaa|aa|eeee|eee|ee|xxw|xw|ww|[2-6]e|n|m|w|a|b|c|d|e|dd|ddd)$",
            # Waist x inseam pant sizing (e.g. 32x30, 34 x 32).
            r"^\d{2}(?:\.\d+)?\s?[x×]\s?\d{2}(?:\.\d+)?$",
        )
    )
)
VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS = tuple(
    dict.fromkeys(
        (
            *(
                str(value).strip()
                for value in tuple(
                    _STATIC_EXPORTS.get(
                        "VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS", ()
                    )
                    or ()
                )
                if str(value).strip()
            ),
            r"^\s*option\s+",
            r"\s+(?:not\s+)?selected\s*$",
            r"\s+\((?:sold\s+out|unavailable)\)\s*$",
            r"\s+(?:variant\s+)?sold\s+out(?:\s+or\s+unavailable)?\s*$",
            r"\s+learn\s+more\s*$",
        )
    )
)
AVAILABILITY_URL_MAP = {
    "https://schema.org/instock": "in_stock",
    "http://schema.org/instock": "in_stock",
    "schema.org/instock": "in_stock",
    "instock": "in_stock",
    "https://schema.org/outofstock": "out_of_stock",
    "http://schema.org/outofstock": "out_of_stock",
    "schema.org/outofstock": "out_of_stock",
    "outofstock": "out_of_stock",
    "https://schema.org/limitedavailability": "limited_stock",
    "http://schema.org/limitedavailability": "limited_stock",
    "schema.org/limitedavailability": "limited_stock",
    "limitedavailability": "limited_stock",
    "https://schema.org/preorder": "pre_order",
    "http://schema.org/preorder": "pre_order",
    "schema.org/preorder": "pre_order",
    "preorder": "pre_order",
}
NORMALIZER_AVAILABILITY_TOKENS = {
    "in_stock": ("in stock", "instock", "available", "ready to ship"),
    "limited_stock": (
        "limited stock",
        "limitedstock",
        "low stock",
        "lowstock",
        "only",
        "left in stock",
    ),
    "out_of_stock": ("out of stock", "outofstock", "oos", "sold out", "unavailable"),
    "pre_order": ("pre-order", "preorder", "backorder", "back-order"),
}
VARIANT_OPTION_TEXT_FIELDS = frozenset(PUBLIC_VARIANT_AXIS_FIELDS)
VARIANT_AXIS_ALLOWED_SINGLE_TOKENS = frozenset(
    {
        *VARIANT_OPTION_TEXT_FIELDS,
        "arms",
        "back",
        "band",
        "base",
        "bundle_type",
        "carat",
        "clarity",
        "colour",
        "commitment_period",
        "configuration",
        "connectivity",
        "count",
        "cup",
        "cut",
        "dimensions",
        "edition",
        "engraving",
        "fabric_grade",
        "finish",
        "firmness",
        "fit",
        "flavor",
        "flavour",
        "format",
        "frame",
        "frequency",
        "gemstone",
        "height",
        "leg_finish",
        "length",
        "load_rating",
        "material",
        "material_composition",
        "memory",
        "metal",
        "model",
        "pack",
        "pattern",
        "personalization",
        "plug_type",
        "scent",
        "seat_count",
        "setting",
        "shade",
        "shape",
        "skin_type",
        "spf_rating",
        "state",
        "stone",
        "storage",
        "storage_capacity",
        "support",
        "thickness",
        "thread_size",
        "tier",
        "tilt",
        "tolerance_level",
        "type",
        "usage_limit",
        "voltage",
        "volume",
        "weight",
        "width",
    }
)
VARIANT_AXIS_GENERIC_TOKENS = frozenset(
    {
        "attribute",
        "choice",
        "description",
        "dropdown",
        "item",
        "name",
        "option",
        "options",
        "please",
        "shoe",
        "shoes",
        "select",
        "selected",
        "selector",
        "styledselect",
        "swatch",
        "variant",
        "variation",
    }
)
VARIANT_AXIS_TECHNICAL_PATTERNS = (
    r"^(?:option|options?|select|selector|dropdown|variant|variation|styledselect)[_\s-]*\d+$",
    r"^(?:variation|variant|option|attribute|selector|styledselect)(?:[_\s-]+(?:selector|select))?(?:[_\s-]*\d+)?$",
    r"^[a-z]*select\d+$",
)
VARIANT_QUANTITY_ATTR_TOKENS = frozenset(
    {
        "amount",
        "howmany",
        "item-count",
        "item_count",
        "number-of-items",
        "number_of_items",
        "quantity",
        "qty",
    }
)
VARIANT_OPTION_TEXT_CHILD_DROP_PATTERNS = (
    r"[$€£¥₹]\s*\d",
    r"\b\d[\d.,]*\s*(?:usd|eur|gbp|inr|aud|cad|ars)\b",
    r"\b(?:popular|sale|discount|off|sold out|unavailable|left in stock)\b",
)

__all__ = sorted(name for name in globals() if name.isupper())
