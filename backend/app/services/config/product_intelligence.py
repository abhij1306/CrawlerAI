from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, model_validator

from app.services.config.runtime_settings import settings_config
from pydantic_settings import BaseSettings

PRODUCT_INTELLIGENCE_JOB_STATUS_QUEUED = "queued"
PRODUCT_INTELLIGENCE_JOB_STATUS_RUNNING = "running"
PRODUCT_INTELLIGENCE_JOB_STATUS_COMPLETE = "complete"
PRODUCT_INTELLIGENCE_JOB_STATUS_FAILED = "failed"

PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_DISCOVERED = "discovered"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED = "crawl_queued"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_COMPLETE = "crawl_complete"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS = "no_records"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT = "crawl_timeout"
PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_FAILED = "failed"

PRODUCT_INTELLIGENCE_REVIEW_PENDING = "pending"
PRODUCT_INTELLIGENCE_REVIEW_ACCEPTED = "accepted"
PRODUCT_INTELLIGENCE_REVIEW_REJECTED = "rejected"

SOURCE_TYPE_BRAND_DTC = "brand_dtc"
SOURCE_TYPE_RETAILER = "retailer"
SOURCE_TYPE_MARKETPLACE = "marketplace"
SOURCE_TYPE_AGGREGATOR = "aggregator"
SOURCE_TYPE_UNKNOWN = "unknown"

PRIVATE_LABEL_INCLUDE = "include"
PRIVATE_LABEL_FLAG = "flag"
PRIVATE_LABEL_EXCLUDE = "exclude"

SEARCH_PROVIDER_SERPAPI = "serpapi"
SEARCH_PROVIDER_GOOGLE_NATIVE = "google_native"

DEFAULT_SCORE_LABEL_HIGH = "high"
DEFAULT_SCORE_LABEL_MEDIUM = "medium"
DEFAULT_SCORE_LABEL_LOW = "low"
DEFAULT_SCORE_LABEL_UNCERTAIN = "uncertain"

ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
RUN_TYPE_CRAWL = "crawl"

SOURCE_TITLE_FIELDS = ("title", "name", "product_title")
SOURCE_BRAND_FIELDS = ("brand", "manufacturer", "vendor")
SOURCE_PRICE_FIELDS = ("price", "sale_price", "current_price", "final_price")
SOURCE_CURRENCY_FIELDS = ("currency", "price_currency")
SOURCE_IMAGE_FIELDS = ("image_url", "image", "primary_image", "thumbnail")
SOURCE_URL_FIELDS = ("url", "product_url", "canonical_url", "source_url")
SOURCE_SKU_FIELDS = ("sku", "style", "style_id", "product_id", "id")
SOURCE_MPN_FIELDS = ("mpn", "model", "model_number", "part_number")
SOURCE_STYLE_FIELDS = ("style", "style_id", "product_id")
SOURCE_GTIN_FIELDS = ("gtin", "barcode", "sku_upc", "upc", "ean", "isbn")
SOURCE_AVAILABILITY_FIELDS = ("availability", "stock_status", "in_stock")

SEARCH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "for",
    "in",
    "of",
    "or",
    "the",
    "with",
}
DISCOVERY_PRODUCT_PATH_HINTS = (
    "/p/",
    "/product/",
    "/products/",
    "/proddetail/",
    "/dp/",
    "/gp/product/",
    "/itm/",
    "/ip/",
)
DISCOVERY_PRODUCT_DETAIL_EXTENSIONS = (".html", ".htm")
DISCOVERY_LISTING_PATH_SEGMENTS = (
    "c",
    "category",
    "categories",
    "collection",
    "collections",
    "s",
    "search",
    "w",
)
DISCOVERY_NON_PRODUCT_PATH_SEGMENTS = (
    "article",
    "blog",
    "blogs",
    "guide",
    "guides",
    "how to",
    "learn",
    "stories",
)
DISCOVERY_GENERIC_PRODUCT_TOKENS = {
    "apparel",
    "buy",
    "clothing",
    "denim",
    "dress",
    "fit",
    "for",
    "jean",
    "jeans",
    "kid",
    "kids",
    "ladies",
    "men",
    "mens",
    "pant",
    "pants",
    "product",
    "sale",
    "shirt",
    "shop",
    "shoe",
    "shoes",
    "style",
    "the",
    "women",
    "womens",
}
DISCOVERY_TITLE_MISMATCH_MIN_DISTINCTIVE_TOKENS = 2
DISCOVERY_TITLE_MISMATCH_MIN_OVERLAP_RATIO = 0.5
SEARCH_EXCLUDED_DOMAIN_PREFIX = "-site:"
SEARCH_SITE_PREFIX = "site:"
SERPAPI_SEARCH_URL = "https://serpapi.com/search.json"
SERPAPI_ENGINE = "google"
SERPAPI_SHOPPING_ENGINE = "google_shopping"
SERPAPI_IMMERSIVE_PRODUCT_ENGINE = "google_immersive_product"
SERPAPI_QUERY_PARAM = "q"
SERPAPI_PAGE_TOKEN_PARAM = "page_token"  # nosec B105
SERPAPI_MORE_STORES_PARAM = "more_stores"
SERPAPI_KEY_PARAM = "api_key"
SERPAPI_ENGINE_PARAM = "engine"
SERPAPI_RESULT_COUNT_PARAM = "num"
SERPAPI_ORGANIC_RESULTS_FIELD = "organic_results"
SERPAPI_LINK_FIELD = "link"
SERPAPI_TITLE_FIELD = "title"
SERPAPI_SNIPPET_FIELD = "snippet"
SERPAPI_POSITION_FIELD = "position"
SERPAPI_SOURCE_FIELD = "source"
SERPAPI_DISPLAYED_LINK_FIELD = "displayed_link"
SERPAPI_SHOPPING_RESULTS_FIELD = "shopping_results"
SERPAPI_SHOPPING_PRODUCT_ID_FIELD = "product_id"
SERPAPI_SHOPPING_PRODUCT_LINK_FIELD = "product_link"
SERPAPI_SHOPPING_IMMERSIVE_API_FIELD = "serpapi_immersive_product_api"
SERPAPI_SHOPPING_IMMERSIVE_TOKEN_FIELD = "immersive_product_page_token"  # nosec B105
SERPAPI_SHOPPING_LINK_FIELDS = ("direct_link", "link", "product_link")
SERPAPI_PRICE_FIELDS = ("extracted_price", "price")
SERPAPI_THUMBNAIL_FIELDS = ("thumbnail", "image", "favicon")
GOOGLE_NATIVE_HOME_URL = "https://www.google.com/"
GOOGLE_NATIVE_SEARCH_URL = "https://www.google.com/search"
GOOGLE_NATIVE_QUERY_PARAM = "q"
GOOGLE_NATIVE_RESULT_COUNT_PARAM = "num"
GOOGLE_NATIVE_SEARCH_INPUT_SELECTOR = "textarea[name='q'], input[name='q']"
GOOGLE_NATIVE_RESULT_LINK_SELECTOR = "a[href]"
GOOGLE_NATIVE_TITLE_SELECTOR = "h3"
GOOGLE_NATIVE_THUMBNAIL_ANCESTOR_DEPTH = 6
GOOGLE_NATIVE_THUMBNAIL_MIN_SRC_LENGTH = 20
GOOGLE_NATIVE_REDIRECT_PATH = "/url"
GOOGLE_NATIVE_REDIRECT_TARGET_PARAM = "q"
GOOGLE_NATIVE_IGNORED_DOMAINS = ("google.com", "webcache.googleusercontent.com")
GOOGLE_NATIVE_PROVIDER_PAYLOAD = "google_native"
GOOGLE_NATIVE_BROWSER_ENGINE = "real_chrome"
GOOGLE_NATIVE_NAVIGATION_TIMEOUT_MS = 20000
GOOGLE_NATIVE_RESULT_WAIT_MS = 2500
GOOGLE_NATIVE_TYPING_EXTRA_WAIT_MS = 1500
GOOGLE_NATIVE_SUBMIT_KEY = "Enter"
GOOGLE_NATIVE_BLOCKED_CLASSIFICATION_OFFSET = 0
GOOGLE_NATIVE_BLOCKED_URL_PATTERNS = ("/sorry/",)
GOOGLE_NATIVE_BLOCKED_HTML_PATTERNS = (
    "unusual traffic from your computer network",
    "really you sending the requests",
)
ADMIN_ROLE = "admin"
CRAWL_RUN_FINAL_STATUSES = frozenset(
    {"completed", "failed", "killed", "proxy_exhausted"}
)
PRODUCT_INTELLIGENCE_LLM_TASK = "product_intelligence_enrichment"
PRODUCT_INTELLIGENCE_BRAND_INFERENCE_LLM_TASK = "product_intelligence_brand_inference"

SEARCH_PHRASE_BUY = "buy"
BRAND_ALIAS_COLLECTION_BY_MICHAEL_STRAHAN = "collection by michael strahan"
BRAND_ALIAS_LEVIS = "levi's"
BRAND_ALIAS_RALPH_LAUREN = "ralph lauren"
BRAND_ALIAS_TOMMY_BAHAMA = "tommy bahama"

BRAND_ALIAS_MAP = {
    BRAND_ALIAS_COLLECTION_BY_MICHAEL_STRAHAN: BRAND_ALIAS_COLLECTION_BY_MICHAEL_STRAHAN,
    "collection by michael strahan tm": BRAND_ALIAS_COLLECTION_BY_MICHAEL_STRAHAN,
    "izod": "izod",
    "kenneth cole reaction": "kenneth cole",
    "levi s": BRAND_ALIAS_LEVIS,
    "levis": BRAND_ALIAS_LEVIS,
    BRAND_ALIAS_LEVIS: BRAND_ALIAS_LEVIS,
    "lee": "lee",
    "michael strahan": BRAND_ALIAS_COLLECTION_BY_MICHAEL_STRAHAN,
    "polo ralph lauren": BRAND_ALIAS_RALPH_LAUREN,
    "ralph lauren childrenswear": BRAND_ALIAS_RALPH_LAUREN,
    "rare too": "rare editions",
    "skechers slip ins go walk": "skechers",
    "skechers men s slip ins": "skechers",
    "skechers men s max cushioning": "skechers",
    "skechers go run consistent": "skechers",
    BRAND_ALIAS_TOMMY_BAHAMA: BRAND_ALIAS_TOMMY_BAHAMA,
    "tommy bahama r": BRAND_ALIAS_TOMMY_BAHAMA,
}

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "product_intelligence"
_BELK_BRAND_URLS_FILE = _DATA_DIR / "belk_brand_urls.tsv"


def _brand_domain_key(value: object) -> str:
    normalized = re.sub(r"[^a-z0-9]+", " ", str(value or "").casefold()).strip()
    return BRAND_ALIAS_MAP.get(normalized, normalized)


def _brand_domain_keys(value: object) -> set[str]:
    text = str(value or "").strip()
    values = {text, re.sub(r"\([^)]*\)", " ", text).strip()}
    for separator in (" / ", "/"):
        if separator in text:
            values.update(part.strip() for part in text.split(separator))
    return {key for key in (_brand_domain_key(item) for item in values) if key}


def _domain_from_brand_url(value: object) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    parsed = urlsplit(text if "://" in text else f"https://{text}")
    return str(parsed.hostname or "").removeprefix("www.").lower()


def _load_brand_domain_file(path: Path) -> dict[str, str]:
    try:
        rows = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    domains: dict[str, str] = {}
    for row in rows[1:]:
        if not row.strip() or "\t" not in row:
            continue
        brand, url = row.split("\t", 1)
        domain = _domain_from_brand_url(url)
        if not domain:
            continue
        for key in _brand_domain_keys(brand):
            domains.setdefault(key, domain)
    return domains


BRAND_DOMAIN_MAP = {
    "adidas": "adidas.com",
    "bonnie jean": "bonniejean.com",
    "calvin klein": "calvinklein.com",
    "coach": "coach.com",
    "columbia": "columbia.com",
    "haggar": "haggar.com",
    "izod": "izod.com",
    "kenneth cole": "kennethcole.com",
    "lee": "lee.com",
    BRAND_ALIAS_LEVIS: "levi.com",
    "lucky brand": "luckybrand.com",
    "michael kors": "michaelkors.com",
    "nautica": "nautica.com",
    "nike": "nike.com",
    "puma": "puma.com",
    "rare editions": "therareeditions.com",
    BRAND_ALIAS_RALPH_LAUREN: "ralphlauren.com",
    "reebok": "reebok.com",
    "skechers": "skechers.com",
    BRAND_ALIAS_TOMMY_BAHAMA: "tommybahama.com",
    "tommy hilfiger": "tommy.com",
    "under armour": "underarmour.com",
    "wrangler": "wrangler.com",
}
BRAND_DOMAIN_MAP = {**_load_brand_domain_file(_BELK_BRAND_URLS_FILE), **BRAND_DOMAIN_MAP}

PRIVATE_LABEL_BRANDS = {
    "belk",
    "kaari blue",
    "new directions",
    "requirements",
    "studio 1",
}

RETAILER_DOMAINS = {
    "belk.com",
    "bloomingdales.com",
    "dillards.com",
    "jcpenney.com",
    "kohls.com",
    "macys.com",
    "menswearhouse.com",
    "myntra.com",
    "nykaa.com",
    "nordstrom.com",
    "saksfifthavenue.com",
    "target.com",
    "walmart.com",
    "zappos.com",
}

MARKETPLACE_DOMAINS = {
    "amazon.com",
    "amazon.ca",
    "amazon.co.uk",
    "amazon.com.au",
    "amazon.com.mx",
    "amazon.de",
    "amazon.fr",
    "amazon.in",
    "amazon.it",
    "amazon.co.jp",
    "ebay.com",
    "ebay.ca",
    "ebay.co.uk",
    "ebay.com.au",
    "ebay.de",
    "ebay.fr",
    "ebay.in",
    "ebay.it",
    "etsy.com",
    "flipkart.com",
}

AGGREGATOR_DOMAINS = {
    "coolspringsgalleria.com",
    "google.com",
    "hamiltonplace.com",
    "shopmy.us",
    "shopstyle.com",
    "thesummitbirmingham.com",
}

DISCOVERY_SOURCE_TYPE_PRIORITY = {
    SOURCE_TYPE_BRAND_DTC: 0,
    SOURCE_TYPE_RETAILER: 1,
    SOURCE_TYPE_MARKETPLACE: 2,
    SOURCE_TYPE_UNKNOWN: 3,
    SOURCE_TYPE_AGGREGATOR: 4,
}

SOURCE_TYPE_AUTHORITY_BONUS = {
    SOURCE_TYPE_BRAND_DTC: 0.18,
    SOURCE_TYPE_RETAILER: 0.10,
    SOURCE_TYPE_MARKETPLACE: 0.06,
    SOURCE_TYPE_AGGREGATOR: 0.04,
    SOURCE_TYPE_UNKNOWN: 0.0,
}

MATCH_SCORE_WEIGHTS = {
    "title_similarity": 0.45,
    "brand_match": 0.25,
    "gtin_match": 0.25,
    "style_code_match": 0.25,
    "shopping_product_group": 0.04,
    "price_band": 0.05,
    "source_authority": 0.18,
}

# Manufacturer style/model code identity (deterministic, no LLM). Branded goods carry a
# universal manufacturer style number (e.g. Nike "FV5285") that every retailer keys on.
# Belk embeds it inside a composite SKU ("3900462FV5285" = Belk numeric prefix + "FV5285"),
# and external listings expose it bare or with a colorway suffix ("FV5285-002"). The leading
# retailer prefix is why a naive token match fails across sites, so the manufacturer core is
# decomposed before comparison. An exact style-code match is a GTIN-class identity signal;
# the distinctive brand-stripped model name token ("promina") is a model-level signal. These
# drive both the discovery identity ladder (ranking/accept) and the matching floors below.
PRODUCT_STYLE_CODE_PATTERN = r"[a-z]{2,}\d{3,}"
PRODUCT_STYLE_CODE_MIN_LENGTH = 5
# Generic apparel/footwear descriptors, sizes, and colors that are NOT distinctive model
# identifiers. Used to isolate the distinctive model-name token (after brand removal) so a
# shared distinctive token (e.g. "promina", "bedford") signals a model-level match while a
# shared generic word (e.g. "walking", "shoes") does not.
MATCH_GENERIC_PRODUCT_TOKENS = frozenset({
    "athletic", "boot", "boots", "boys", "casual", "chino", "chinos", "classic",
    "comfort", "cushioning", "dress", "extra", "fit", "flat", "front", "girls",
    "gym", "kid", "kids", "ladies", "lace", "leather", "loafer", "loafers", "low",
    "men", "mens", "pant", "pants", "regular", "running", "sandal", "sandals",
    "shoe", "shoes", "short", "shorts", "size", "skinny", "slim", "slip", "sneaker",
    "sneakers", "stretch", "straight", "top", "training", "trainer", "trainers",
    "up", "walking", "wide", "women", "womens", "workout",
})
# Confidence floors for manufacturer-code / model-level identity (deterministic). Ranked
# just below GTIN (0.92) for an exact style-code match; a brand-exact + distinctive model
# token is a strong model-level match. Model-level matching requires a brand anchor: a
# distinctive model token WITHOUT a confirmed brand is not floored, because a generic
# descriptive title ("Floral Midi Dress") would otherwise collide across unrelated makers.
MATCH_SCORE_FLOOR_STYLE_CODE = 0.92
MATCH_SCORE_FLOOR_STYLE_CODE_NO_BRAND = 0.85
MATCH_SCORE_FLOOR_MODEL_BRAND = 0.82
# Minimum fraction of the SOURCE's distinctive model tokens that must appear in the
# candidate title for a model-level match. Directional (source -> candidate) so a truncated
# generic candidate ("Samsung Galaxy") cannot match a specific source ("Galaxy S24 Ultra").
MATCH_MODEL_TOKEN_MIN_CONTAINMENT = 0.6

# Match basis labels recorded in score_reasons["match_basis"] so review is explainable.
MATCH_BASIS_GTIN = "gtin"
MATCH_BASIS_STYLE_CODE = "style_code"
MATCH_BASIS_MODEL_BRAND = "model+brand"
MATCH_BASIS_BRAND_DTC = "brand_dtc"
MATCH_BASIS_BRAND_TITLE = "brand+title"
MATCH_BASIS_TITLE = "title"

# Volatile query parameters stripped when building a candidate canonical-dedupe key. The same
# listing offered at multiple sizes/colors arrives as separate URLs differing only by these
# params (e.g. "?size=13", "?activeColor=002", tracking tokens). Collapsing them stops one
# product at N sizes from consuming N per-product candidate slots. Identity-bearing params
# (e.g. "product", "productId") are intentionally NOT stripped.
DISCOVERY_VOLATILE_QUERY_PARAMS = frozenset({
    "_country", "activecolor", "active_color", "cawidth", "clr", "cm_mmc", "cm_ven",
    "color", "colour", "dwvar", "dwvar_color", "fbclid", "gclid", "link_id", "msclkid",
    "ranmid", "show_expr", "size", "srsltid", "utm_campaign", "utm_content",
    "utm_medium", "utm_source", "utm_term", "variant", "vid", "width",
})

# Confidence floors and thresholds. Search-result payloads (SerpAPI/Google) almost
# never carry a UPC/GTIN, and Belk SKU/style numbers are meaningless to external
# retailers, so confidence is driven by brand-exact + title similarity (+ price and
# source authority). These floors guarantee a brand-exact + strong-title match lands
# in the correct band regardless of additive-weight drift.
MATCH_TITLE_SIM_HIGH = 0.90
MATCH_TITLE_SIM_MEDIUM = 0.75
MATCH_DTC_MIN_TITLE_SIM = 0.50
MATCH_SCORE_FLOOR_GTIN = 0.92
MATCH_SCORE_FLOOR_BRAND_DTC = 0.90
MATCH_SCORE_FLOOR_BRAND_TITLE_HIGH = 0.85
MATCH_SCORE_FLOOR_BRAND_TITLE_PRICE_HIGH = 0.88
MATCH_SCORE_FLOOR_BRAND_TITLE_MEDIUM = 0.65

# Variant / spec mismatch (deterministic, no LLM). When source and candidate titles
# BOTH explicitly state a comparable spec (capacity unit or "N-in-1") and the values
# differ, the candidate is a different variant of the product: apply a penalty and
# block promotion into the auto-accept band so a wrong-spec listing ranks below the
# true match.
MATCH_VARIANT_MISMATCH_PENALTY = 0.15
MATCH_VARIANT_MISMATCH_SCORE_CAP = 0.62
VARIANT_SPEC_NUMBER_UNIT_PATTERN = (
    r"(\d+(?:\.\d+)?)\s*-?\s*"
    r"(oz|ounce|ounces|qt|quart|quarts|cup|cups|l|liter|liters|ml|gal|gallon|"
    r"in|inch|inches|ft|pc|pcs|piece|pieces|pack|count|ct)\b"
)
VARIANT_SPEC_N_IN_ONE_PATTERN = r"(\d+)\s*-?\s*in\s*-?\s*1\b"
VARIANT_SPEC_UNIT_ALIASES = {
    "ounce": "oz",
    "ounces": "oz",
    "quart": "qt",
    "quarts": "qt",
    "cups": "cup",
    "liter": "l",
    "liters": "l",
    "gallon": "gal",
    "inch": "in",
    "inches": "in",
    "pcs": "pc",
    "piece": "pc",
    "pieces": "pc",
    "count": "ct",
}

PRODUCT_INTELLIGENCE_PROMPT_REGISTRY = {
    PRODUCT_INTELLIGENCE_LLM_TASK: {
        "response_type": "object",
        "system_file": "product_intelligence_enrichment.system.txt",
        "user_file": "product_intelligence_enrichment.user.txt",
    },
    PRODUCT_INTELLIGENCE_BRAND_INFERENCE_LLM_TASK: {
        "response_type": "object",
        "system_file": "product_intelligence_brand_inference.system.txt",
        "user_file": "product_intelligence_brand_inference.user.txt",
    },
}


class ProductIntelligenceSettings(BaseSettings):
    model_config = settings_config(env_prefix="PRODUCT_INTELLIGENCE_")

    default_search_provider: str = SEARCH_PROVIDER_SERPAPI
    serpapi_key: str = Field(
        default="",
        validation_alias=AliasChoices(
            "PRODUCT_INTELLIGENCE_SERPAPI_KEY",
            "SERP_API_KEY",
            "SERPAPI_API_KEY",
            "SERPAPI_KEY",
            "serp_api_key",
        ),
    )
    max_source_products: int = 10
    max_candidates_per_product: int = 15
    discovery_pool_multiplier: int = 4
    max_urls_per_result_domain: int = 25
    search_timeout_seconds: float = 20.0
    search_delay_ms: int = 800
    google_native_max_results: int = 10
    google_native_max_queries_per_product: int = 2
    serpapi_immersive_products_per_query: int = 2
    candidate_poll_seconds: float = 30.0
    candidate_poll_interval_seconds: float = 2.0
    confidence_threshold: float = 0.4
    title_token_limit: int = 6
    price_band_ratio: float = 0.25
    brand_inference_confidence_threshold: float = 0.6

    @model_validator(mode="after")
    def _validate(self) -> "ProductIntelligenceSettings":
        self.default_search_provider = str(self.default_search_provider or "").strip().lower()
        if self.default_search_provider not in {
            SEARCH_PROVIDER_SERPAPI,
            SEARCH_PROVIDER_GOOGLE_NATIVE,
        }:
            raise ValueError(
                "default_search_provider must be 'serpapi' or 'google_native'"
            )
        self.max_source_products = max(1, int(self.max_source_products))
        self.max_candidates_per_product = max(1, int(self.max_candidates_per_product))
        self.discovery_pool_multiplier = max(1, int(self.discovery_pool_multiplier))
        self.max_urls_per_result_domain = max(1, int(self.max_urls_per_result_domain))
        self.search_timeout_seconds = max(1.0, float(self.search_timeout_seconds))
        self.search_delay_ms = max(0, int(self.search_delay_ms))
        self.google_native_max_results = max(1, int(self.google_native_max_results))
        self.google_native_max_queries_per_product = max(
            1, int(self.google_native_max_queries_per_product)
        )
        self.serpapi_immersive_products_per_query = max(
            0, int(self.serpapi_immersive_products_per_query)
        )
        self.candidate_poll_seconds = max(0.0, float(self.candidate_poll_seconds))
        self.candidate_poll_interval_seconds = max(
            0.5,
            float(self.candidate_poll_interval_seconds),
        )
        self.confidence_threshold = min(max(float(self.confidence_threshold), 0.0), 1.0)
        self.title_token_limit = max(1, int(self.title_token_limit))
        self.price_band_ratio = min(max(float(self.price_band_ratio), 0.0), 1.0)
        self.brand_inference_confidence_threshold = min(
            max(float(self.brand_inference_confidence_threshold), 0.0), 1.0
        )
        return self


product_intelligence_settings = ProductIntelligenceSettings()
