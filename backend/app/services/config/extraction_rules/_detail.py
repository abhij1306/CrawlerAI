from __future__ import annotations
# ruff: noqa: F401,F403,F405
# pylint: disable=wildcard-import,unused-wildcard-import

from . import _common as _common_exports
from . import _images as _images_exports
from ._common import *
from ._images import *
from ._common import _STATIC_EXPORTS

DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES = frozenset(
    {
        "description",
        "details",
        "normal",
        "overview",
        "product label",
        "product summary",
        "specifications",
        # Tab/nav strip text leak when extractor hits the tab shell, not content (Canon DQ-6).
        "overview specs specifications compatibility resources support software",
        "overview specs compatibility resources support software",
        "overview specifications compatibility resources support software",
    }
)
DETAIL_LOW_SIGNAL_TITLE_VALUES = frozenset(
    {
        "6 easy payments",
        "frequently bought together",
        "mens shoes",
        "men's shoes",
        "plp",
        "womens shoes",
        "women's shoes",
        "shoes",
        # Generic gender-plus-category title leak when real title selector fails (LUISAVIAROMA DQ-9).
        "kids boys",
        "kids girls",
        "kids boy",
        "kids girl",
        "boys kids",
        "girls kids",
    }
)
DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES = frozenset(
    {"criteoproductrail", "giftoption", "promotionalcallout"}
)
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
DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS = (r"^(?=.*\d)[a-z0-9]+(?:_[a-z0-9]+){2,}$",)
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
DETAIL_LONG_TEXT_UI_TAIL_PHRASES = (
    "show more",
    "more details",
    "learn more",
)
DETAIL_LONG_TEXT_LEADING_ATTRIBUTE_BLOB_PATTERN = (
    r"^(?:[a-zA-Z][\w:-]*\s*=\s*(?:\"[^\"]*\"|'[^']*')\s*){1,8}"
)
DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS = frozenset(
    {
        "a",
        "an",
        "and",
        "at",
        "by",
        "for",
        "from",
        "in",
        "into",
        "of",
        "on",
        "or",
        "the",
        "to",
        "with",
    }
)
DETAIL_VARIANT_SIZE_SEQUENCE_MIN_COUNT = 5
DETAIL_LEGAL_TAIL_PATTERNS = {
    "contains": (
        "product safety",
        "powered by product details have been supplied by the manufacturer",
    ),
    "digit_contains": ("customer service", "contact "),
    "all_contains": (("privacy", "policy"),),
    "exact": ("view more",),
}
LONG_TEXT_MIN_WORDS = 3
LONG_TEXT_MAX_WORDS = 14
TOKEN_MIN_LEN_DISTINCTIVE = 5
TOKEN_MIN_LEN_CHUNK = 4
LONG_TEXT_PREFIXES = ("official ", "shop for ")
DETAIL_NOISE_PREFIXES = (
    "buy ",
    "check the details",
    "discover ",
    "product summary",
    "shop for ",
    "shop the ",
)
DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS = 4
DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS = 24
DETAIL_LONG_TEXT_MAX_SECTION_CHARS = 12000
DETAIL_MATERIALS_POLLUTION_TOKENS = ("care", "reviews")
DETAIL_MATERIALS_COMPOSITION_PATTERN = (
    r"\d{1,3}\s*%\s*[A-Za-z][A-Za-z\u00C0-\u017F\s\-]{2,40}"
)
DETAIL_MATERIALS_EDITORIAL_HEAD_THRESHOLD = 200
DETAIL_MATERIALS_EDITORIAL_LENGTH_THRESHOLD = 500
DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS = (
    r"\b(?:regular|slim|relaxed)\s+fit\b.{0,240}\b(?:regular|slim|relaxed)\s+fit\b",
    r"\b(?:fabric|material)\s+glossary\b",
    r"\bthe\s+word\s+['\"][a-z -]+['\"]\s+originates\b",
    r"\b(?:find|select)\s+your\s+(?:shade|size|color)\b",
)
DETAIL_GUIDE_GLOSSARY_HEADING_TOKENS = (
    "fabric",
    "fit",
    "glossary",
    "material",
    "materials",
    "size",
)
DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS = 3
DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS = (
    r"\bbuy\s+now\s+with\s+free\s+shipping\b",
    r"\bbuyer\s+protection\s+guaranteed\b",
    r"\bwe\s+aim\s+to\s+show\s+you\s+accurate\s+product\s+information\b",
    r"\bshipping\s+and\s+returns?\b.{0,240}\b(?:orders?|privacy|policy|refunds?|returns?)\b",
    r"\bcookie\s+(?:notice|policy|preferences?)\b",
    r"\bprivacy\s+policy\b",
    # Audit 2026-05-03 3.2: Shipping/fulfillment status blurbs leaked into
    # Jordan 5 description. Context-bound so legitimate prose that mentions
    # tracking or shipping is not rejected.
    r"\btracking\s+status\s+reads\b",
    r"\border\s+is\s+shipped\b.{0,120}\b(?:tracking|email)\b",
    r"\blabel\s+created\b.{0,80}\b(?:tracking|carrier|status|shipping|hours)\b",
    r"\bshipping\s+statuses?\s+can\s+remain\b",
    # Audit 2026-05-03 3.3: Marketing banner openers like "(US) - only $35. Fast shipping..."
    r"\([A-Z]{2,4}\)\s*[-\u2013\u2014]\s*only\s+\$\d",
    r"\bfast\s+shipping\s+on\s+latest\b",
    # Audit 2026-05-03 3.4: SEO meta blurbs ("Shop the X at Brand today",
    # "Read customer reviews ... and discover more").
    r"\bshop\s+the\b.{0,160}\bat\s+\S+\s+today\b",
    r"\bread\s+customer\s+reviews?\b.{0,160}\b(?:discover|learn|and\s+more)\b",
    r"\bread\s+reviews?\s+and\s+buy\b.{0,220}\b(?:same\s+day\s+delivery|drive\s+up|contactless|more)\b",
    r"^\s*read\s+reviews?\s+and\s+buy\b",
    r"^\s*shop\b.{0,120}\brefurbished\s+excellent\b",
    r"\bchoose\s+from\s+contactless\b.{0,160}\b(?:same\s+day\s+delivery|drive\s+up)\b",
    r"\bfind\s+low\s+everyday\s+prices\b.{0,180}\b(?:buy\s+online|price\s+match\s+guarantee|in-store\s+pick-?up)\b",
    r"\bprice\s+match\s+guarantee\b",
    r"\bitem\s+details\s+above\s+aren['’]?t\s+accurate\b",
    r"\breport\s+incorrect\s+product\s+info\b",
    r"\bwants\s+you\s+to\s+be\s+fully\s+satisfied\s+with\s+your\s+purchase\b",
    r"\bview\s+our\s+returns?\s+policy\b",
    r"\bunlock\s+unlimited\s+free\s+international\s+shipping\b",
    r"\bexclusive\s+member-only\s+deals\b",
    r"\bwas\s+this\s+product\s+information\s+helpful\b",
    r"\bwrite\s+a\s+review\b",
)
DETAIL_LONG_TEXT_SUBSTRING_REMOVE_PATTERNS = (
    r"\b(?:l|i)nstagram\s+@[A-Za-z0-9_.-]+\b",
    r"\bimport\s+duties,\s+taxes,\s+and\s+charges\b.{0,260}\bprior\s+to\s+(?:bidding|buying)\b\.?",
    r"\bFootnote\s+\d+\s*\.?",
)
DETAIL_LONG_TEXT_REPEATED_PROMPTS = ("Please check the measurements below",)
DETAIL_COOKIE_DISCLOSURE_TEXT_PATTERNS = (
    r"\bcookie\s+name\s+is\s+associated\s+with\b",
    r"\bcookie\s+descriptions?\s+are\s+displayed\b",
    r"\bcookiepedia\b",
    r"\bpreference\s+center\b",
    r"\bcloudflare\s+bot\s+management\b",
    r"\bmicrosoft\s+clarity\b",
    r"\bdynatrace\b",
    r"\bcriteo\b",
    r"\bgoogle\s+adsense\b",
    r"\breal\s+time\s+bidding\b",
)
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
DETAIL_BRAND_TITLE_SUFFIX_PATTERN = r"\s[-\u2013\u2014]\s(?P<brand>[A-Z][A-Za-z0-9&'.\-\s]{1,40})$"
DETAIL_BRAND_HOST_FALLBACKS = {
    "aesop": "Aesop",
    "apple": "Apple",
    "converse": "Converse",
    "phase-eight": "Phase Eight",
    "vans": "Vans",
}
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
)
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
)
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
DETAIL_TEXT_SCOPE_SELECTORS = tuple(
    dict.fromkeys(
        (
            _STATIC_EXPORTS.get("DETAIL_PRIMARY_DOM_CONTEXT_SELECTOR", "main"),
            "main",
            "article",
            "[role='main']",
            "[class*='product-main' i]",
            "[class*='product-content' i]",
        )
    )
)
DETAIL_TEXT_SCOPE_PRIORITY_TOKENS = (
    "description",
    "detail",
    "pdp",
    "product",
)
DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS = (
    "also-viewed",
    "also viewed",
    "ask",
    "compare",
    "dialog",
    "disclaimer",
    "fit-guide",
    "fit guide",
    "lightbox",
    "modal",
    "newsletter",
    "overlay",
    "popup",
    "recommend",
    "related",
    "review",
    "similar",
    "shipping",
    "size-guide",
    "size guide",
    "sponsored",
    "you-may-also-like",
    "you may also like",
)
DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS = (
    "also-viewed",
    "also viewed",
    "complete-the-look",
    "complete the look",
    "customers",
    "people-also-bought",
    "people also bought",
    "recommend",
    "related",
    "similar",
    "sponsored",
)
DETAIL_TEXT_HIDDEN_STYLE_TOKENS = (
    "display:none",
    "display: none",
    "left:-9999",
    "left: -9999",
    "opacity:0",
    "opacity: 0",
    "top:-9999",
    "top: -9999",
    "visibility:hidden",
    "visibility: hidden",
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

_LOCAL_EXPORTS = (
    "DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES", "DETAIL_LOW_SIGNAL_TITLE_VALUES",
    "DETAIL_LOW_SIGNAL_PRODUCT_TYPE_VALUES", "DETAIL_ARTIFACT_PRODUCT_TYPE_VALUES",
    "TITLE_PROMOTION_EXACT_VALUES", "DETAIL_ARTIFACT_PRODUCT_TYPE_PATTERNS",
    "DETAIL_ARTIFACT_IDENTIFIER_VALUES", "DETAIL_ARTIFACT_PRICE_VALUES",
    "DETAIL_ARTIFACT_SKU_PREFIXES", "CATEGORY_PLACEHOLDER_VALUES",
    "DETAIL_CATEGORY_UI_TOKENS", "DETAIL_CATEGORY_LABEL_PREFIXES",
    "DETAIL_CATEGORY_BRANCH_STOP_TOKENS", "DETAIL_LONG_TEXT_UI_TAIL_PHRASES",
    "DETAIL_LONG_TEXT_LEADING_ATTRIBUTE_BLOB_PATTERN",
    "DETAIL_LONG_TEXT_TRUNCATED_TAIL_TOKENS", "DETAIL_VARIANT_SIZE_SEQUENCE_MIN_COUNT",
    "DETAIL_LEGAL_TAIL_PATTERNS", "LONG_TEXT_MIN_WORDS", "LONG_TEXT_MAX_WORDS",
    "TOKEN_MIN_LEN_DISTINCTIVE", "TOKEN_MIN_LEN_CHUNK", "LONG_TEXT_PREFIXES",
    "DETAIL_NOISE_PREFIXES", "DETAIL_LONG_TEXT_UI_TAIL_MIN_PRODUCT_WORDS",
    "DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS", "DETAIL_LONG_TEXT_MAX_SECTION_CHARS",
    "DETAIL_MATERIALS_POLLUTION_TOKENS", "DETAIL_MATERIALS_COMPOSITION_PATTERN",
    "DETAIL_MATERIALS_EDITORIAL_HEAD_THRESHOLD",
    "DETAIL_MATERIALS_EDITORIAL_LENGTH_THRESHOLD", "DETAIL_GUIDE_GLOSSARY_TEXT_PATTERNS",
    "DETAIL_GUIDE_GLOSSARY_HEADING_TOKENS", "DETAIL_GUIDE_GLOSSARY_HEADING_MIN_HITS",
    "DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS", "DETAIL_LONG_TEXT_SUBSTRING_REMOVE_PATTERNS",
    "DETAIL_LONG_TEXT_REPEATED_PROMPTS", "DETAIL_COOKIE_DISCLOSURE_TEXT_PATTERNS",
    "DETAIL_TRACKING_TOKEN_PATTERN", "SMALL_NUMERIC_PATTERN", "TRACKING_PIXEL_PATTERN",
    "COLOR_KEYWORD_PATTERN", "DETAIL_QUOTED_COLOR_PATTERN",
    "DETAIL_BRAND_TITLE_PREFIX_MAX_WORDS", "DETAIL_BRAND_PREFIX_CONTINUATION_TOKENS",
    "DETAIL_BRAND_NUMERIC_PREFIX_ALLOWLIST", "DETAIL_BRAND_TITLE_SUFFIX_PATTERN",
    "DETAIL_BRAND_HOST_FALLBACKS", "DETAIL_BRAND_DESCRIPTION_PATTERNS",
    "DETAIL_BRAND_SUFFIX_REJECT_TOKENS", "DETAIL_BRAND_PREFIX_STOP_TOKENS",
    "GIF_BASE64_PREFIX", "URL_DETECTION_TOKENS", "YEAR_SLUG_PATTERN",
    "PRODUCT_SLUG_MIN_TERMINAL_TOKENS", "GENDER_ARTIFACT_WORDS",
    "GENDER_ARTIFACT_PATTERN", "GENDER_KEYWORD_TOKENS", "GENDER_POSSESSIVE_PATTERN",
    "STANDARD_SIZE_VALUES", "VARIANT_TITLE_STOPWORDS", "DOM_VARIANT_GROUP_LIMIT",
    "DOM_VARIANT_CARTESIAN_COMBO_LIMIT", "DETAIL_EXPANSION_STATUS_ATTEMPTED",
    "DETAIL_EXPANSION_STATUS_EXPANDED", "DETAIL_EXPANSION_STATUS_INTERACTION_FAILED",
    "DETAIL_EXPANSION_STATUS_INTERACTION_LIMIT_REACHED", "DETAIL_EXPANSION_STATUS_NO_MATCHES",
    "DETAIL_EXPANSION_STATUS_SKIPPED", "DETAIL_EXPANSION_STATUS_TIME_BUDGET_REACHED",
    "UNRESOLVED_TEMPLATE_URL_TOKENS", "DETAIL_VARIANT_ARTIFACT_VALUE_TOKENS",
    "AVAILABILITY_IN_STOCK", "AVAILABILITY_OUT_OF_STOCK", "AVAILABILITY_UNKNOWN",
    "MATERIAL_KEYWORDS", "ORG_SUFFIXES", "NOISY_PRODUCT_ATTRIBUTE_KEYS",
    "DETAIL_TEXT_SCOPE_SELECTORS", "DETAIL_TEXT_SCOPE_PRIORITY_TOKENS",
    "DETAIL_TEXT_SCOPE_EXCLUDE_TOKENS", "DETAIL_CROSS_PRODUCT_CONTAINER_TOKENS",
    "DETAIL_TEXT_HIDDEN_STYLE_TOKENS", "DETAIL_VARIANT_CONTEXT_NOISE_TOKENS",
    "VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH", "VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_FALLBACK",
    "VARIANT_CONTEXT_NOISE_ANCESTOR_DEPTH_DEFAULT", "DETAIL_VARIANT_SCOPE_SELECTOR",
    "VARIANT_SCOPE_MAX_ROOTS", "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_MIN_DELTA",
    "DETAIL_LOW_SIGNAL_PRICE_VISIBLE_RATIO", "DETAIL_LOW_SIGNAL_SALE_PRICE_RATIO_MAX",
    "DETAIL_IMAGE_RAW_SOUP_FALLBACK_MAX_WINNING_IMAGES", "DETAIL_IMAGE_URL_ATTRS",
    "INLINE_SCALAR_LABEL_MAX_LEN", "INLINE_SCALAR_VALUE_MAX_LEN",
    "INLINE_SCALAR_ALLOWED_FIELDS", "SCALAR_FIELD_MAX_OPTION_TOKENS",
    "SHADE_CODE_COLOR_MIN_TOKENS", "SCALAR_FIELD_POLLUTION_VALUES",
    "DETAIL_SIZE_GUIDE_ALLOWED_HEADER_KEYS", "DETAIL_SIZE_GUIDE_CONTEXT_TOKENS",
    "DETAIL_TITLE_TRAILING_SIZE_VALUES", "DETAIL_TITLE_LEADING_SKU_PREFIX_PATTERN",
    "MULTI_PART_PUBLIC_SUFFIXES", "VARIANT_OPTION_LABEL_MAX_WORDS",
    "DETAIL_BREADCRUMB_ROOT_LABELS", "DETAIL_BREADCRUMB_SELECTORS",
    "DETAIL_BREADCRUMB_CONTAINER_SELECTORS", "DETAIL_BREADCRUMB_SEPARATOR_LABELS",
    "DETAIL_BREADCRUMB_LABEL_PREFIXES", "DETAIL_BREADCRUMB_NOISE_ICON_PATTERNS",
    "DETAIL_BREADCRUMB_JSONLD_TYPES", "DETAIL_BREADCRUMB_MIN_LABEL_LENGTH",
    "DETAIL_BREADCRUMB_TITLE_DUPLICATE_RATIO", "STRUCTURED_CANDIDATE_TRAVERSAL_LIMIT",
    "STRUCTURED_CANDIDATE_LIST_SLICE", "DETAIL_CATEGORY_SOURCE_RANKS",
    "DETAIL_GENDER_TERMS",
)

__all__ = sorted((*_common_exports.__all__, *_images_exports.__all__, *_LOCAL_EXPORTS))
