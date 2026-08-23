from __future__ import annotations
# ruff: noqa: F401,F403,F405

import re

from . import _common as _common_exports
from . import _images as _images_exports
from ._common import *
from ._images import *
from ._common import _STATIC_EXPORTS
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS,
    PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES,
)

DETAIL_IDENTITY_QUERY_KEYS = frozenset(
    {
        *PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS,
        "id",
        "pid",
        "style",
        "style_no",
        "styleno",
    }
)
DETAIL_IDENTITY_QUERY_PREFIXES = tuple(PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES)
DETAIL_LOWER_ALNUM_TOKEN_PATTERN = r"[a-z0-9]+"
DETAIL_NON_LOWER_ALNUM_PATTERN = r"[^a-z0-9]+"
DETAIL_JSONLD_STRUCTURED_ATTRIBUTES = ("schema-productgroup",)

DETAIL_BRAND_BOILERPLATE_VALUES = frozenset(
    {
        "& more",
        "at",
        "black",
        "blue",
        "brand",
        "brown",
        "csc",
        "fifa world cup™",
        "fragrance",
        "for men",
        "green",
        "grey",
        "girls",
        "india",
        "india | the",
        "kids",
        "mens",
        "more",
        "petite",
        "petites",
        "red",
        "refurbished",
        "register",
        "the",
        "unisex",
        "utility",
        "womens",
        "we",
        "white",
    }
)
DETAIL_BRAND_WEAK_SINGLE_TOKEN_PATTERN = (
    r"^(?:"
    r"beige|black|blue|brown|clear|cream|gold|gray|green|grey|navy|orange|"
    r"pink|purple|red|silver|tan|white|yellow|"
    r"brand|designer|fragrance|manufacturer|register|refurbished|sale|shop|store"
    r")$"
)
DETAIL_BRAND_FRAGMENT_PATTERN = (
    r"^(?:and|at|by|for|from|in|more|of|on|the|to|with|&\s*more)$"
)
DETAIL_BRAND_DOM_SELECTORS = (
    "main [data-brand]",
    "main [data-brand-name]",
    "main [data-manufacturer]",
    "main [data-manufacturer-name]",
    "main [data-designer]",
    "main [data-designer-name]",
    "main [itemprop='brand']",
    "main [itemprop='manufacturer']",
    "main [class*='product-brand']",
    "main [class*='product_brand']",
    "main [data-testid*='brand']",
    "main [data-testid*='manufacturer']",
)
DETAIL_BRAND_DOM_VALUE_ATTRIBUTES = (
    "data-brand",
    "data-brand-name",
    "data-manufacturer",
    "data-manufacturer-name",
    "data-designer",
    "data-designer-name",
    "content",
)
DETAIL_BRAND_VISIBLE_LABEL_PATTERN = (
    r"^\s*(?:brand|manufacturer|designed\s+by|designer)\s*[:\-]\s*"
    r"(?P<brand>[^|\n]{1,80})\s*$"
)
DETAIL_BRAND_CATEGORY_PATTERN = (
    r"^(?:men(?:'s|s)?|women(?:'s|s)?|boys?|girls?|kids?)\s+"
    r"(?:[a-z0-9&'\-]+\s+){0,5}"
    r"(?:shirts?|shorts?|shoes?|sneakers?|dresses?|pants?|jeans?|jackets?|hoodies?|tops?|tees?|t-?shirts?)$"
)
DETAIL_LOW_SIGNAL_TITLE_VALUES = frozenset(
    {
        "6 easy payments",
        "frequently bought together",
        "added to cart",
        "cashmere",
        "clothing",
        "boy",
        "boys",
        "girl",
        "girls",
        "kids",
        "linen",
        "men",
        "new",
        "sale",
        "swim",
        "women",
        "hats & caps",
        "home",
        "mens footwear sneakers",
        "mens shoes",
        "men's shoes",
        "maternity",
        "petite",
        "petites",
        "pick up today",
        "plus",
        "plus size",
        "plp",
        "tall",
        "size",
        "stylehint app",
        "t shirts",
        "tread pdp compose page",
        "us",
        "womens shoes",
        "women's shoes",
        "shoes",
        "short sleeved t shirts",
        # Generic gender-plus-category title leak when real title selector fails (LUISAVIAROMA DQ-9).
        "kids boys",
        "kids girls",
        "kids boy",
        "kids girl",
        "boys kids",
        "girls kids",
    }
) | frozenset(_STATIC_EXPORTS.get("DETAIL_LOW_SIGNAL_TITLE_VALUES_EXTRA", ()))
DETAIL_SHELL_TITLE_VALUES = frozenset(
    {
        "oops! something went wrong",
        "something went wrong",
        "error",
        "error page",
        "access denied",
        "access denied. we invite you to return at a later time to complete your purchase.",
        "access forbidden",
        "add to cart",
        "adding to bag",
        "adding to basket",
        "adding to cart",
        "accès refusé",
        "accès refusé. nous vous invitons à revenir plus tard pour effectuer votre achat.",
    }
)
DETAIL_SHELL_TITLE_KEYS = frozenset(
    " ".join(re.findall(r"[a-z0-9]+", value.casefold()))
    for value in DETAIL_SHELL_TITLE_VALUES
)
DETAIL_NOT_FOUND_HTTP_STATUS_CODES = frozenset({404, 410})
DETAIL_SHELL_TITLE_FLAG = "shell_title"
DETAIL_SHELL_FINDING_RULE_ID = "HTTP_SHELL_TITLE"
DETAIL_SHELL_MEANINGFUL_RECORD_FIELDS = (
    "brand",
    "description",
    "image_url",
    "price",
    "sku",
    "variants",
)
DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS = frozenset(
    {"title", "price", "currency", "availability", "image_url"}
)
DETAIL_REVIEW_RISK_FINDING_RULE_IDS = frozenset(
    {
        DETAIL_SHELL_FINDING_RULE_ID,
        "PUBLIC_RESOLUTION_DIVERGENCE",
        "PRICE_WITHOUT_CURRENCY",
        "CURRENCY_WITHOUT_PRICE",
        "NON_POSITIVE_PRICE",
        "INVALID_ORIGINAL_PRICE",
        "PARENT_VARIANT_AVAILABILITY_CONFLICT",
        # A structured child offer that could not be joined to its variant drops
        # per-variant commercial data from the public projection — a public-output
        # risk that warrants operator review (Crawl-Run-2 §4.4, result 118 Nike).
        # Matches ``variant_policy.CHILD_JOIN_FAILED_RULE_ID`` (scope "page").
        "CHILD_JOIN_FAILED",
    }
)
DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS = ("price", "currency", "availability")
DETAIL_CAPTURE_OK_OUTCOME = "ok"
DETAIL_CAPTURE_BLOCKED_OUTCOME = "blocked"
DETAIL_CAPTURE_ERROR_OUTCOME = "error"
DETAIL_CAPTURE_SEMANTIC_SHELL_OUTCOME = "semantic_shell"
DETAIL_CAPTURE_NOT_FOUND_OUTCOME = "not_found"
DETAIL_TERMINAL_SOURCE_UNAVAILABLE_OUTCOMES = frozenset(
    {
        DETAIL_CAPTURE_BLOCKED_OUTCOME,
        DETAIL_CAPTURE_NOT_FOUND_OUTCOME,
        DETAIL_CAPTURE_SEMANTIC_SHELL_OUTCOME,
    }
)
VARIANT_COLOR_BRAND_CONFLICT_FLAG = "brand_as_variant_color"
DETAIL_TITLE_NON_PRODUCT_LOCATOR_TOKENS = (
    "/public_config/",
    "/badges/",
    "/sellerbadges/",
    "/sustainabilitybadges/",
    "/fitassistant/",
    "/breadcrumbs/",
)
DETAIL_TITLE_REJECTION_FLAGS = frozenset(
    {
        "code_only_title",
        "filename_title",
        "generic_title",
        "measurement_title",
        "placeholder_text",
        DETAIL_SHELL_TITLE_FLAG,
        "title_url_mismatch",
        "truncated_title",
    }
)
DETAIL_TITLE_REJECT_SUFFIXES = (
    " compose page",
    " product card",
)
DETAIL_TITLE_REJECT_VALUES = (
    frozenset(
        {
            "& more",
            "black",
            "description",
            "more",
            "refurbished",
            "details",
            "measurements",
            "navigation",
            "not added",
            "overview",
            "product detail",
            "product details",
            "reviews",
            "shipping",
            "size guide",
            "specifications",
            "x",
        }
    )
    | DETAIL_LOW_SIGNAL_TITLE_VALUES
)
DETAIL_TITLE_CODE_ONLY_PATTERN = r"^(?=.{4,40}$)(?=.*\d)[A-Za-z0-9._-]+$"
DETAIL_TITLE_IDENTIFIER_ONLY_PATTERN = r"^(?=.{2,80}$)(?=.*\d)(?:[A-Za-z]{0,4}\d[A-Za-z0-9]*|[A-Za-z]|\d+)(?:[\s._-]+(?:[A-Za-z]{0,4}\d[A-Za-z0-9]*|[A-Za-z]|\d+))*$"
DETAIL_TITLE_INTERNAL_SYSTEM_PATTERN = (
    r"^(?=.{12,120}$)(?=.*\d)(?=(?:.*\b(?:core|eva|unit|variant|style|model|base)\b){2,})"
    r"(?:[a-z0-9]+[\s_-]+){3,}[a-z0-9]+$"
)
DETAIL_TITLE_PATH_EXTENSION_PATTERN = r"\.(?:aspx?|html?|jsp|php)$"
DETAIL_TITLE_ENDPOINT_FILENAME_PATTERN = r"^(?:product|detail|pdp|item|catalog|view)(?:\.(?:do|action|aspx?|html?|jsp|php))?$"
DETAIL_TITLE_GENERIC_CATEGORY_VALUES = frozenset(
    {
        "interchangeable lens cameras",
        "digital cameras",
        "camera lenses",
        "mens clothing",
        "womens clothing",
        "men's clothing",
        "women's clothing",
        "shoes",
        "footwear",
        "accessories",
    }
)
DETAIL_TITLE_STYLE_ONLY_TOKENS = frozenset(
    {
        "wide",
        "leg",
        "slim",
        "skinny",
        "straight",
        "relaxed",
        "cropped",
        "oversized",
        "classic",
        "regular",
        "petite",
        "tall",
        "small",
        "medium",
        "large",
        "x-large",
        "xx-large",
    }
)
DETAIL_TITLE_STYLE_ONLY_MAX_WORDS = 2
DETAIL_TITLE_SEO_POLLUTION_PATTERN = (
    r"(?:\s[|\u2013\u2014]\s|\s+-\s+\$?\d|\bshop\s+online\b|\$\d+(?:\.\d{2})?)"
)
DETAIL_TITLE_TRAILING_CODE_PATTERN = r"(?:^|[\s_-])\d{4,}$"
DETAIL_TITLE_URL_TOKEN_MIN_OVERLAP = 2
DETAIL_TITLE_SEO_PREFIXES = ("buy ", "shop ")
DETAIL_TITLE_SEO_PREFIX_MIN_WORDS = 8
DETAIL_TITLE_MARKETPLACE_PREFIX_PATTERN = (
    r"^\s*[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\s*:\s*"
)
DETAIL_TITLE_MARKETPLACE_CATEGORY_SUFFIX_PATTERN = r"\s*:\s*[^:]{2,80}\s*$"
DETAIL_TITLE_SHORT_NAVIGATION_PATTERN = r"^(?:shop|browse|view)\s+(?:graphic\s+)?(?:t-?shirts?|shirts?|tops?|pants?|jeans?|dresses?|shoes?|sneakers?|accessories?)$"
DETAIL_TITLE_UI_INSTRUCTION_TOKENS = frozenset(
    {"assembly", "delivery", "faq", "faqs", "fee", "variation"}
)
DETAIL_TITLE_UI_INSTRUCTION_MIN_HITS = 3
DETAIL_URL_TITLE_IGNORED_SEGMENTS = frozenset(
    {
        "boys",
        "girls",
        "kids boys",
        "kids girls",
        "men",
        "p",
        "pd",
        "dp",
        "product",
        "product detail",
        "productpage",
        "products",
        "shop",
        "women",
    }
)
DETAIL_URL_TITLE_CODE_PATTERN = (
    r"^(?=.{2,48}$)(?=.*\d)[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+){0,2}$"
)
DETAIL_URL_TITLE_LOCALE_PATTERN = r"^[A-Za-z]{2}(?:[-_][A-Za-z]{2})?$"
DETAIL_URL_TITLE_FALLBACK_MIN_TOKENS = 2
DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES = frozenset(
    {"criteoproductrail", "giftoption", "promotionalcallout"}
) | frozenset(_STATIC_EXPORTS.get("DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES_EXTRA", ()))
DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES = frozenset(
    {
        "brightcove video",
        "criteoproductrail",
        "default",
        "giftoption",
        "inline",
        "promotionalcallout",
        "tag",
    }
)
TITLE_PROMOTION_EXACT_VALUES = frozenset({"prime"})
DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS = (
    r"^(?=.*\d)[a-z0-9]+(?:_[a-z0-9]+){2,}$",
) + tuple(_STATIC_EXPORTS.get("DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS_EXTRA", ()))
DETAIL_ARTIFACT_IDENTIFIER_VALUES = frozenset(
    {"description", "details", "product details", "specification", "specifications"}
)
DETAIL_ARTIFACT_PRICE_VALUES = frozenset(
    {"free", "n/a", "na", "unavailable", "contact us"}
)
DETAIL_ARTIFACT_SKU_PREFIXES = ("copy-",)
CATEGORY_PLACEHOLDER_VALUES = frozenset({"category", "categories", "uncategorized"})
DETAIL_CATEGORY_UI_TOKENS = frozenset(
    {
        "...",
        "all categories",
        "back",
        "best sellers",
        "home",
        "next",
        "previous",
        "view all",
        "···",
        "…",
        "shop by material",
        "shop by brand",
    }
)
DETAIL_CATEGORY_LABEL_PREFIXES = ("shop by ",)
DETAIL_CATEGORY_BRANCH_STOP_TOKENS = frozenset({"collections"})
DETAIL_TRACKING_TOKEN_PATTERN = r"_[a-z][a-z0-9_]{2,}"  # nosec B105
SMALL_NUMERIC_PATTERN = r"\d{1,2}"
TRACKING_PIXEL_PATTERN = r"_[a-z]+"
COLOR_KEYWORD_PATTERN = r"\b(?:color|colour|black|blue|brown|gold|green|grey|gray|orange|pink|purple|red|silver|white|yellow)\b"
DETAIL_QUOTED_COLOR_PATTERN = (
    r"['\"](?P<color>[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+){0,2})['\"]"
    r"\s+(?:canvas|cotton|denim|leather|mesh|nylon|suede|upper|wool)\b"
)
DETAIL_BRAND_TITLE_PREFIX_MAX_WORDS = 3
DETAIL_BRAND_PREFIX_CONTINUATION_TOKENS = frozenset({"hilfiger", "originals"})
DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST = frozenset({"47"})
DETAIL_BRAND_TITLE_SUFFIX_PATTERN = (
    r"\s[-\u2013\u2014]\s(?P<brand>[A-Z][A-Za-z0-9&'.\-\s]{1,40})$"
)
DETAIL_BRAND_HOST_FALLBACKS = {
    "aesop": "Aesop",
    "apple": "Apple",
    "converse": "Converse",
    "phase-eight": "Phase Eight",
    "vans": "Vans",
}
DETAIL_BRAND_HOST_FALLBACKS.update(
    _STATIC_EXPORTS.get("DETAIL_BRAND_HOST_FALLBACKS_EXTRA", {})
)
DETAIL_BRAND_DESCRIPTION_PATTERNS = (
    r"\bfrom\s+(?P<brand>[A-Z][A-Za-z0-9&'.-]{2,}(?:\s+[A-Z][A-Za-z0-9&'.-]{2,}){0,2})['’]s\b",
    r"\b(?P<brand>[A-Z][A-Za-z0-9&'.-]{2,}(?:\s+[A-Z][A-Za-z0-9&'.-]{2,}){0,2})['’]s\s+upcoming\b",
)
DETAIL_BRAND_SUFFIX_REJECT_TOKENS = frozenset(
    {"lifewear", "vintage watches", "official store"}
)
DETAIL_BRAND_PREFIX_STOP_TOKENS = frozenset(
    {
        "air",
        "boho",
        "classic",
        "gg",
        "going",
        "italian",
        "mens",
        "men",
        "pragmata",
        "tobago",
        "vitamin",
        "womens",
        "women",
    }
) | frozenset(_STATIC_EXPORTS.get("DETAIL_BRAND_PREFIX_STOP_TOKENS_EXTRA", ()))
GIF_BASE64_PREFIX = "r0lgodlh"
URL_DETECTION_TOKENS = ("g_auto", "f_auto", "q_auto", "c_fill")
YEAR_SLUG_PATTERN = r"(?:19|20)\d{2}"
PRODUCT_SLUG_MIN_TERMINAL_TOKENS = 3
GENDER_ARTIFACT_WORDS = ("men", "mens", "women", "womens", "boys", "girls")
GENDER_ARTIFACT_PATTERN = r"\b(?:men|mens|women|womens|boys|girls)['’]?\s+{candidate}\b"
GENDER_KEYWORD_TOKENS = frozenset(GENDER_ARTIFACT_WORDS)
GENDER_POSSESSIVE_PATTERN = r"\b(?:men|women|boys|girls)['’]?s\b"
STANDARD_SIZE_VALUES = frozenset({"xs", "s", "m", "l", "xl", "xxl", "xxxl"})
VARIANT_TITLE_STOPWORDS = frozenset(
    {"and", "for", "the", "with", "size", "color", "colour", "variant"}
)
DOM_VARIANT_GROUP_LIMIT = 4
DOM_VARIANT_CARTESIAN_COMBO_LIMIT = 1000
DETAIL_EXPANSION_STATUS_ATTEMPTED = "attempted"
DETAIL_EXPANSION_STATUS_EXPANDED = "expanded"
DETAIL_EXPANSION_STATUS_INTERACTION_FAILED = "interaction_failed"
DETAIL_EXPANSION_STATUS_INTERACTION_LIMIT_REACHED = "interaction_limit_reached"
DETAIL_EXPANSION_STATUS_NO_MATCHES = "no_matches"
DETAIL_EXPANSION_STATUS_SKIPPED = "skipped"
DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED = "time_budget_reached"
UNRESOLVED_TEMPLATE_URL_TOKENS = (
    "url_to_",
    "{{",
    "}}",
    "{$",
    "%%",
    "[[",
    "]]",
) + tuple(_STATIC_EXPORTS.get("UNRESOLVED_TEMPLATE_URL_TOKENS_EXTRA", ()))
DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS = frozenset(
    {"discount", "false", "off", "on", "sale", "true"}
)
AVAILABILITY_IN_STOCK = "in_stock"
AVAILABILITY_OUT_OF_STOCK = "out_of_stock"
AVAILABILITY_UNKNOWN = "unknown"
MATERIAL_KEYWORDS = frozenset(
    {
        "cotton",
        "leather",
        "linen",
        "nylon",
        "polyamide",
        "polyester",
        "rubber",
        "spandex",
        "wool",
    }
)
ORG_SUFFIXES = frozenset({"co", "company", "corp", "inc", "llc", "ltd", "se"})
NOISY_PRODUCT_ATTRIBUTE_KEYS = frozenset(
    tuple(_STATIC_EXPORTS.get("NOISY_PRODUCT_ATTRIBUTE_KEYS", ()) or ())
) | frozenset(
    {
        "availability",
        "available",
        AVAILABILITY_IN_STOCK,
        AVAILABILITY_OUT_OF_STOCK,
        "stock_status",
    }
)
DETAIL_VARIANT_CONTEXT_NOISE_TOKENS = (
    "account",
    "addon",
    "addons",
    "carousel",
    "cross-sell",
    "footer",
    "header",
    "newsletter",
    "modal",
    "promo",
    "promotion",
    "recommend",
    "related",
    "search",
    "signup",
    "upsell",
    "you may also like",
    "sort by",
    "filter by",
    "results",
    "report",
)
DETAIL_HIDDEN_PRODUCT_CONTENT_POSITIVE_TOKENS = (
    "accordion",
    "collapsible",
    "description",
    "detail",
    "disclosure",
    "feature",
    "panel",
    "pdp",
    "product",
    "specification",
    "tab",
)
DETAIL_HIDDEN_PRODUCT_CONTENT_NEGATIVE_TOKENS = (
    "cart",
    "carousel",
    "footer",
    "header",
    "modal",
    "newsletter",
    "promo",
    "recommend",
    "related",
    "search",
    "sponsored",
    "upsell",
)
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH = 6
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK = 3
VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT = (
    VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK
)
DETAIL_VARIANT_SCOPE_SELECTOR = (
    "form[action*='cart' i], "
    "form[id*='product' i], "
    "form[class*='product' i], "
    "[data-product-form], "
    "[class*='product-form' i], "
    "[class*='product-info' i], "
    "[class*='product-detail' i], "
    "[class*='pdp' i], "
    "[class*='add-to-cart' i], "
    "[id*='add-to-cart' i]"
)
VARIANT_SCOPE_MAX_ROOTS = 4
DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA = 10.0
DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO = 0.1
DETAIL_LOW_SIGNAL_SALE_PRICE_RATIO_MAX = 0.15
DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES = 1
DETAIL_IMAGE_URL_ATTRS = (
    "src",
    "data-src",
    "data-lazy-src",
    "data-original",
    "data-image",
)
INLINE_SCALAR_LABEL_MAX_LEN = 40
INLINE_SCALAR_VALUE_MAX_LEN = 80
INLINE_SCALAR_ALLOWED_FIELDS = frozenset({"color", "size"})
SCALAR_FIELD_MAX_OPTION_TOKENS = 1
SHADE_CODE_COLOR_MIN_TOKENS = 2
SCALAR_FIELD_POLLUTION_VALUES = frozenset(
    {"size", "color", "colour", "bust", "waist", "hips", "length"}
)
DETAIL_SIZE_GUIDE_ALLOWED_HEADER_KEYS = frozenset(
    {
        "alpha",
        "bust",
        "cm",
        "eu",
        "eu_it",
        "hips",
        "in",
        "it",
        "size",
        "uk",
        "uk_size",
        "us",
        "waist",
    }
)
DETAIL_SIZE_GUIDE_CONTEXT_TOKENS = frozenset({"size guide", "size chart"})
DETAIL_TITLE_TRAILING_SIZE_VALUES = frozenset({"one size"})
DETAIL_TITLE_LEADING_SKU_PREFIX_PATTERN = r"^[A-Za-z0-9]{6,18}$"
MULTI_PART_PUBLIC_SUFFIXES = frozenset(
    {
        "ac.in",
        "co.in",
        "co.jp",
        "co.kr",
        "co.nz",
        "co.uk",
        "com.au",
        "com.br",
        "com.cn",
        "com.mx",
        "com.sg",
        "com.tr",
        "edu.au",
        "gov.in",
        "gov.uk",
        "net.au",
        "org.au",
        "org.uk",
    }
)
VARIANT_OPTION_LABEL_MAX_WORDS = 6
DETAIL_BREADCRUMB_ROOT_LABELS = frozenset(
    {
        "home",
        "shop",
        "store",
        "homepage",
        "frontpage",
        "index",
        "home page",
        "homepage home",
    }
)
DETAIL_BREADCRUMB_SELECTORS = (
    "[aria-label*='breadcrumb' i] li",
    "[class*='breadcrumb' i] li",
    "[aria-label*='breadcrumb' i] a",
    "[class*='breadcrumb' i] a",
)
DETAIL_BREADCRUMB_CONTAINER_SELECTORS = (
    "[aria-label*='breadcrumb' i]",
    "[class*='breadcrumb' i]",
)
DETAIL_BREADCRUMB_SEPARATOR_LABELS = frozenset({">", "/", "\\", "|", "›", "»", "→"})
DETAIL_BREADCRUMB_LABEL_PREFIXES = ("shop all ",)
DETAIL_BREADCRUMB_NOISE_ICON_PATTERNS = (r"\barrow-right(?:-[a-z]+)?\b",)
DETAIL_BREADCRUMB_JSONLD_TYPES = frozenset({"breadcrumblist", "breadcrumb_list"})
DETAIL_BREADCRUMB_MIN_LABEL_LENGTH = 8
DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO = 0.92
STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT = 8
STRUCTURED_CANDIDATE_LIST_SLICE = 20
DETAIL_CATEGORY_SOURCE_RANKS = {
    "json_ld_breadcrumb": 1,
    "dom_breadcrumb": 2,
    "json_ld": 3,
    "microdata": 3,
    "adapter": 3,
    "network_payload": 4,
    "js_state": 5,
    "dom_selector": 6,
}
DETAIL_GENDER_TERMS = {
    "women": ("women", "womens", "women's", "woman", "ladies", "female"),
    "men": ("men", "mens", "men's", "man", "male"),
    "girls": ("girls", "girl"),
    "boys": ("boys", "boy"),
    "unisex": (
        "unisex",
        "all gender",
        "all-gender",
        "gender neutral",
        "gender-neutral",
    ),
}

_IMPORTED_EXPORTS = frozenset(
    {
        "PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_KEYS",
        "PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PREFIXES",
    }
)
_LOCAL_EXPORTS = tuple(
    name
    for name in globals()
    if name.isupper()
    and not name.startswith("_")
    and name not in _common_exports.__all__
    and name not in _images_exports.__all__
    and name not in _IMPORTED_EXPORTS
)

__all__ = sorted((*_common_exports.__all__, *_images_exports.__all__, *_LOCAL_EXPORTS))
