from __future__ import annotations

from ._common import _STATIC_EXPORTS
from ._detail import AVAILABILITY_IN_STOCK, AVAILABILITY_OUT_OF_STOCK

DETAIL_DOM_BASE_SELECTORS = (
    ("h1", "product.title"),
    ("head title", "product.title"),
    ("[data-price]", "offer.price"),
    ("[data-currency]", "offer.currency"),
    ("[data-sku]", "product.sku"),
)
DETAIL_TITLE_SOURCE_ROLE_METADATA_KEY = "title_source_role"
DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_PRODUCT = "structured_product_name"
DETAIL_TITLE_SOURCE_ROLE_VISIBLE_HEADING = "visible_product_heading"
DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_STATE = "structured_state_name"
DETAIL_TITLE_SOURCE_ROLE_PRODUCT_METADATA = "product_metadata"
DETAIL_TITLE_SOURCE_ROLE_DOCUMENT = "document_title"
DETAIL_TITLE_SOURCE_ROLE_URL = "url_derived"
DETAIL_TITLE_SOURCE_ROLE_RANKS = {
    DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_PRODUCT: 0,
    DETAIL_TITLE_SOURCE_ROLE_VISIBLE_HEADING: 1,
    DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_STATE: 2,
    DETAIL_TITLE_SOURCE_ROLE_PRODUCT_METADATA: 3,
    DETAIL_TITLE_SOURCE_ROLE_DOCUMENT: 4,
    DETAIL_TITLE_SOURCE_ROLE_URL: 5,
}
DETAIL_DOM_TITLE_SOURCE_ROLES = {
    "h1": DETAIL_TITLE_SOURCE_ROLE_VISIBLE_HEADING,
    "head title": DETAIL_TITLE_SOURCE_ROLE_DOCUMENT,
}
DETAIL_TITLE_COLLECTOR_SOURCE_ROLES = {
    "adapter": DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_PRODUCT,
    "jsonld": DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_PRODUCT,
    "js_state": DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_STATE,
    "network": DETAIL_TITLE_SOURCE_ROLE_STRUCTURED_STATE,
    "microdata": DETAIL_TITLE_SOURCE_ROLE_PRODUCT_METADATA,
    "opengraph": DETAIL_TITLE_SOURCE_ROLE_PRODUCT_METADATA,
    "css_recipe": DETAIL_TITLE_SOURCE_ROLE_VISIBLE_HEADING,
    "url": DETAIL_TITLE_SOURCE_ROLE_URL,
}
DETAIL_DOM_IMAGE_SCOPE_ATTRIBUTES = (
    "id",
    "class",
    "data-testid",
    "data-component",
    "data-section",
    "aria-label",
    "role",
)
DETAIL_DOM_IMAGE_CANDIDATE_SELECTOR = (
    "main img[src], main img[data-src], main img[data-lazy-src], "
    "main img[data-original], main img[data-image], main img[srcset], "
    "main img[data-srcset], main source[srcset], main source[data-srcset], "
    "img[data-product-image][src], img[data-product-image][data-src]"
)
DETAIL_DOM_REQUESTED_VALUE_ATTRIBUTES = {
    "product.url": ("href", "content", "value", "title", "aria-label"),
    "asset.image_url": ("src", "data-src", "content", "href", "alt", "title"),
}
DETAIL_DOM_REQUESTED_DEFAULT_VALUE_ATTRIBUTES = (
    "content",
    "value",
    "title",
    "aria-label",
)

DETAIL_MICRODATA_NON_PRODUCT_ITEMTYPE_TOKENS = frozenset({"breadcrumblist", "listitem"})
DETAIL_DESCRIPTION_NON_PRODUCT_LOCATOR_TOKENS = (
    "/public_config/",
    "/sellerbadges/",
    "/badges/",
    "/sustainabilitybadges/",
    "/fitassistant/",
    "/breadcrumbs/",
)
DETAIL_DESCRIPTION_UI_PATTERNS = (
    r"^\s*(?:please\s+)?(?:choose|select)\s+(?:(?:a|your|the)\s+)?(?:fabric|material|finish|color|colour|size)\b",
    r"^\s*(?:fabric|material|finish|color|colour|size)\s+selection\b",
    r"^\s*read\s+reviews?\s+and\s+buy\b",
    r"\bchoose\s+from\s+(?:contactless|same[- ]day|drive[- ]up|order\s+pickup)\b",
    r"\b(?:web\s+pdp|default\s+layout|mix\s+and\s+match\s+carousel|home\s+categories)\b",
    r"^\s*expect\s+a\s+(?:quick|fast)\s+response\s+from\s+(?:this|the)\s+seller\b",
    r"\busually\s+within\s+\d+\s+(?:minutes?|hours?|days?)\b",
    r"^\s*(?:this|the)\s+seller\s+(?:typically|usually)\s+(?:responds?|ships?)\b",
    r"^\s*seller\s+(?:response|shipping|dispatch)\s+time\b",
    r"^\s*px-captcha\s*$",
    r"\baccess to this page has been denied\b",
)
DETAIL_DESCRIPTION_HARD_BOUNDARY_LENGTHS = frozenset({320})
DETAIL_DESCRIPTION_INCOMPLETE_ENDING_PATTERN = (
    r"\b(?:and|or|with|for|to|the|a|an|of|in|on|at|by)\s*$"
)
DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN = r"\d{1,3}%(?=[A-Z])|\d{1,2}oz(?=[A-Z])"
DETAIL_DESCRIPTION_MIN_GROUNDED_PROSE_LENGTH = 80
DETAIL_DESCRIPTION_PROMOTIONAL_PATTERNS = (
    r"\b(?:buy now|free shipping|lowest prices?|exclusive offers?|fast delivery)\b",
    r"^\s*(?:shop|buy|find|browse)\b.{0,220}\b(?:online|sale|shipping|delivery|price|today|shop\s+now|more\s+items?)\b",
    r"^\s*searching\s+for\b.{0,220}\b(?:we(?:'|’)ve\s+got|shop|discover)\b",
    r"^\s*discover\b.{0,220}\bavailable\s+to\s+buy\s+online\b.{0,220}\b(?:delivery|returns?|shop\s+now)\b",
    r"\b(?:search results?|product directory|shopping directory|compare prices?)\b",
    r"\bget\s+your\s+pair\s+of\b.{0,120}\bnow\b",
    r"^\s*buy\b.{0,180}\bat\b.{0,80}\b(?:us|uk|online|store)\b",
    r"^\s*find\b.{0,180}\band\s+more\s+items?\s+on\b",
    r"^items?\s+listed.{0,60}shipped.{0,60}directly\s+from\b",
    r"\bdirectly\s+from\s+[\w&'.-]+(?:\s+[\w&'.-]+){0,3}\s+hq\s+to\s+you\b",
    r"^items?\s+listed,?\s+sold\s+and\b",
)
DETAIL_LOW_SIGNAL_LONG_TEXT_VALUES = frozenset(
    {
        "description",
        "details",
        "normal",
        "overview",
        "product label",
        "product summary",
        "specifications",
        "overview specs specifications compatibility resources support software",
        "overview specs compatibility resources support software",
        "overview specifications compatibility resources support software",
    }
)

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
DETAIL_LONG_TEXT_UI_TAIL_PHRASES = ("show more", "more details", "learn more")
DETAIL_LONG_TEXT_UI_TAIL_PREFIXES = ("learn more about ",)
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
DETAIL_MATERIALS_SECTION_TAIL_PATTERNS = (r"\breviews?\s*\(\s*\d+\s*\)",)
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
    r"\btracking\s+status\s+reads\b",
    r"\border\s+is\s+shipped\b.{0,120}\b(?:tracking|email)\b",
    r"\blabel\s+created\b.{0,80}\b(?:tracking|carrier|status|shipping|hours)\b",
    r"\bshipping\s+statuses?\s+can\s+remain\b",
    r"\([A-Z]{2,4}\)\s*[-\u2013\u2014]\s*only\s+\$\d",
    r"\bfast\s+shipping\s+on\s+latest\b",
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
    *tuple(_STATIC_EXPORTS.get("DETAIL_LONG_TEXT_DISCLAIMER_PATTERNS_EXTRA", ())),
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
DETAIL_DOM_PRODUCT_ROOT_SELECTORS = tuple(
    dict.fromkeys(
        (
            "main",
            "article",
            "[role='main']",
            "[class*='product-main' i]",
            "[class*='product-detail' i]",
            "[class*='product-content' i]",
            "[data-testid*='product' i]",
        )
    )
)
DETAIL_DOM_PRODUCT_ROOT_POSITIVE_SELECTORS = (
    "h1",
    "[data-price]",
    "[itemprop='price']",
    "[class*='current-price' i]",
    "[class*='product-price' i]",
    "[class*='sale-price' i]",
    "[data-testid*='price' i]",
    "[class*='gallery' i]",
    "[data-product-image]",
    "form[action*='cart' i]",
    "button[name*='add' i]",
    "button[class*='cart' i]",
    "button[class*='bag' i]",
)
DETAIL_DOM_DESCRIPTION_SELECTORS = (
    "[data-description]",
    "[data-field='description']",
    "[itemprop='description']",
    "[class*='product-description' i]",
    "[class*='product__description' i]",
    "[data-testid*='description' i]",
    "[class*='description' i]",
)
DETAIL_DOM_DESCRIPTION_MIN_CHARS = 24
DETAIL_DOM_MATERIAL_EXPLICIT_SELECTOR = (
    "li, dt, [class*='label' i], [itemprop='material'], "
    "[data-field='material'], [data-testid*='material' i], "
    "[class*='material' i], [class*='composition' i]"
)
DETAIL_DOM_MATERIAL_TEXT_BLOCK_SELECTOR = "li, p, dd"
DETAIL_DOM_MATERIAL_META_SELECTOR = (
    "meta[name='description'], meta[property='og:description']"
)
DETAIL_DOM_MATERIAL_SCAN_LIMIT = 400
DETAIL_DOM_MATERIAL_MAX_VALUE_CHARS = 160
DETAIL_DOM_MATERIAL_LABEL_PATTERN = (
    r"^(?:(?:upper|outer|shell|footbed)\s+)?"
    r"(?:material(?:s)?|fabric|composition)\s*:?\s*(?P<value>.*)$"
)
DETAIL_DOM_MATERIAL_INLINE_LABEL_PATTERN = (
    r"\b(?:(?:upper|outer|shell|footbed)\s+)?"
    r"(?:material(?:s)?|fabric|composition)\s*:\s*(?P<value>.+)"
)
DETAIL_DOM_MATERIAL_INLINE_COMPOSITION_PATTERN = r"\bcomposition\s+(?P<value>.+)"
DETAIL_DOM_MATERIAL_VALUE_BOUNDARY_PATTERN = (
    r"\s+(?:care(?:\s+instructions?)?|origin|style|color|colour|delivery|"
    r"shipping|returns?|reviews?|lining|insole|outsole|trim|closure|"
    r"made\s+in|internal\s+details)\s*:?(?:\s|$).*$"
)
DETAIL_DOM_MATERIAL_VALUE_REJECT = frozenset(
    {
        "",
        "base",
        "composition",
        "details",
        "fabric",
        "insole",
        "lining",
        "material",
        "materials",
        "outsole",
        "upper",
    }
)
DETAIL_DOM_MATERIAL_PERCENTAGE_PATTERNS = (
    r"\b\d{1,3}(?:\.\d+)?\s*%\s*[A-Za-z][A-Za-z\u00C0-\u017F\- ]{1,50}?"
    r"(?=\s+(?:and|with|for|to|that|which)\b|[,.;]|$)",
    r"\b[A-Za-z][A-Za-z\u00C0-\u017F\- ]{1,40}?\s+\d{1,3}(?:\.\d+)?\s*%"
    r"(?=\s+(?:and|with|for|to|that|which)\b|[,.;]|$)",
)
DETAIL_DOM_MATERIAL_CONSTRUCTION_PATTERNS = (
    r"\b(?:made|crafted|built|constructed)\s+(?:from|of|with)\s+"
    r"(?P<value>[^.;]{2,100}?)(?=\s+(?:for|to|that|which|with)\b|[.;]|$)",
)
DETAIL_DOM_MATERIAL_COMPONENT_PATTERN = (
    r"(?P<value>(?:[^,.;:]|\bwith\b){2,70}?)\s+"
    r"(?:fabric|upper|lining|insole|outsole|base)\b"
)
DETAIL_DOM_MATERIAL_DECORATIVE_SYMBOL_PATTERN = r"[®™℠�]"
MATERIAL_KEYWORDS = frozenset(
    {
        "acrylic",
        "aluminum",
        "brass",
        "canvas",
        "cashmere",
        "ceramic",
        "cotton",
        "denim",
        "elastane",
        "glass",
        "gold",
        "jersey",
        "latex",
        "leather",
        "linen",
        "lyocell",
        "mesh",
        "modal",
        "nylon",
        "paper",
        "polyamide",
        "polycarbonate",
        "polyester",
        "polyurethane",
        "rayon",
        "rubber",
        "satin",
        "silk",
        "silver",
        "spandex",
        "steel",
        "suede",
        "synthetic",
        "thermoplastic",
        "titanium",
        "viscose",
        "wood",
        "wool",
    }
)
DETAIL_DOM_OFFER_SELECTORS = (
    "[data-price]",
    "[itemprop='price']",
    "[class*='current-price' i]",
    "[class*='product-price' i]",
    "[class*='sale-price' i]",
    "[data-testid*='price' i]",
    "[aria-label*='$']",
    "[aria-label*='£']",
    "[aria-label*='€']",
    "[aria-label*='₹']",
)
DETAIL_DOM_OFFER_CONTEXT_ANCESTOR_LIMIT = 4
DETAIL_DOM_OFFER_MAX_CANDIDATES = 8
DETAIL_DOM_PRICE_TEXT_PATTERN = (
    r"(?P<symbol>[$€£¥₹])?\s*(?P<amount>\d{1,3}(?:[,.]\d{2,3})+(?:[,.]\d{1,2})?|\d{1,7}(?:[,.]\d{1,2})?)"
    r"(?:\s*(?P<code>USD|EUR|GBP|INR|CAD|AUD|JPY|CNY))?"
)
DETAIL_DOM_CURRENCY_CODE_PATTERN = r"[A-Z]{3}"
DETAIL_DOM_CURRENCY_CONTEXT_PATTERN = r"\b(USD|EUR|GBP|INR|CAD|AUD|JPY|CNY)\b"
DETAIL_DOM_AVAILABILITY_TEXT_PATTERNS = {
    AVAILABILITY_IN_STOCK: (r"\bin\s+stock\b", r"\bavailable\b", r"\bonline\s+only\b"),
    AVAILABILITY_OUT_OF_STOCK: (
        r"\bout\s+of\s+stock\b",
        r"\bsold\s+out\b",
        r"\bunavailable\b",
    ),
}
DETAIL_TEXT_SCOPE_PRIORITY_TOKENS = ("description", "detail", "pdp", "product")
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
DETAIL_TEXT_SCOPE_OVERLAY_TOKENS = frozenset(
    {"dialog", "lightbox", "modal", "overlay", "popup"}
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
DETAIL_IDENTITY_FIELDS = frozenset({"title", "image_url"})
VARIANT_FIELDS = frozenset({"variants"})

_LOCAL_EXPORTS = tuple(
    name for name in globals() if name.isupper() and not name.startswith("_")
)
__all__ = sorted(_LOCAL_EXPORTS)
