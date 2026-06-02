from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.services.config.field_mappings import (
    AVAILABLE_SIZES_FIELD,
    COLOR_FIELD,
    SELECTED_VARIANT_FIELD,
    SIZE_FIELD,
    VARIANTS_FIELD,
    VARIANT_AXES_FIELD,
    WIDTH_FIELD,
)


DATA_ENRICHMENT_STATUS_UNENRICHED = "unenriched"
DATA_ENRICHMENT_STATUS_PENDING = "pending"
DATA_ENRICHMENT_STATUS_RUNNING = "running"
DATA_ENRICHMENT_STATUS_ENRICHED = "enriched"
DATA_ENRICHMENT_STATUS_DEGRADED = "degraded"
DATA_ENRICHMENT_STATUS_FAILED = "failed"
DATA_ENRICHMENT_LLM_TASK = "data_enrichment_semantic"
DATA_ENRICHMENT_TAXONOMY_VERSION = "shopify-2026-02"

DATA_ENRICHMENT_SKIP_RECORD_STATUSES = (
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_STATUS_RUNNING,
)
DATA_ENRICHMENT_JOB_TERMINAL_STATUSES = (
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_FAILED,
)

ECOMMERCE_DETAIL_SURFACE = "ecommerce_detail"
ECOMMERCE_LISTING_SURFACE = "ecommerce_listing"
DATA_ENRICHMENT_TAXONOMY_FILENAME = "shopify_categories.json"
DATA_ENRICHMENT_ATTRIBUTES_FILENAME = "shopify_attributes.json"
DATA_ENRICHMENT_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "enrichment"
DATA_ENRICHMENT_TAXONOMY_PATH = (
    DATA_ENRICHMENT_DATA_DIR / DATA_ENRICHMENT_TAXONOMY_FILENAME
)
DATA_ENRICHMENT_ATTRIBUTES_PATH = (
    DATA_ENRICHMENT_DATA_DIR / DATA_ENRICHMENT_ATTRIBUTES_FILENAME
)
DATA_ENRICHMENT_BASE_REQUIRED_ATTRIBUTES = (
    "title",
    "description",
    "link",
    "image_link",
    "availability",
    "price",
)
DATA_ENRICHMENT_LLM_BACKFILL_FIELDS = (
    "category_path",
    "color_family",
    "size_normalized",
    "size_system",
    "gender_normalized",
    "materials_normalized",
    "availability_normalized",
    "intent_attributes",
    "audience",
    "style_tags",
    "ai_discovery_tags",
    "suggested_bundles",
)
DATA_ENRICHMENT_SHOPIFY_NORMALIZATION_ATTRIBUTE_NAMES = {
    "audience": "Target audience",
    "color": "Color",
    "size": "Size",
    "gender": "Target gender",
    "fabric": "Fabric",
    "material": "Material",
}
DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS = frozenset(
    {
        "adult",
        "baby",
        "boy",
        "child",
        "children",
        "girl",
        "kid",
        "men",
        "toddler",
        "unisex",
        "women",
    }
)
DATA_ENRICHMENT_TAXONOMY_ACCESSORY_PATH_TERMS = (
    "accessories",
    "accessory",
    "parts",
    "replacement",
    "cases",
    "covers",
    "skins",
    "wraps",
    "cushions",
    "tips",
    "adapters",
    "cables",
    "chargers",
    "stands",
    "mounts",
    "straps",
    "storage",
)
DATA_ENRICHMENT_TAXONOMY_ACCESSORY_EVIDENCE_TERMS = (
    "adapter",
    "adapters",
    "cable",
    "cables",
    "case",
    "cases",
    "charger",
    "chargers",
    "cover",
    "covers",
    "cushion",
    "cushions",
    "dock",
    "mount",
    "mounts",
    "part",
    "parts",
    "protector",
    "replacement",
    "skin",
    "skins",
    "stand",
    "stands",
    "strap",
    "straps",
    "tip",
    "tips",
    "wrap",
    "wraps",
)
DATA_ENRICHMENT_TAXONOMY_TOY_EVIDENCE_TERMS = (
    "block",
    "blocks",
    "building",
    "doll",
    "figure",
    "figures",
    "kids",
    "lego",
    "minifigure",
    "minifigures",
    "play",
    "playground",
    "playset",
    "toy",
    "toys",
)
DATA_ENRICHMENT_TAXONOMY_SPORT_EVIDENCE_TERMS = (
    "athletic",
    "athletics",
    "ball",
    "balls",
    "fitness",
    "padel",
    "sport",
    "sports",
    "tennis",
)
DATA_ENRICHMENT_TAXONOMY_GAME_EVIDENCE_TERMS = (
    "capcom",
    "game",
    "games",
    "gaming",
    "nintendo",
    "preorder",
    "switch",
    "video",
)
DATA_ENRICHMENT_TAXONOMY_SPECIFIC_SPORT_TERMS = (
    "badminton",
    "baseball",
    "basketball",
    "cricket",
    "football",
    "golf",
    "hockey",
    "padel",
    "pickleball",
    "racquetball",
    "soccer",
    "squash",
    "tennis",
    "volleyball",
)
DATA_ENRICHMENT_CATEGORY_URL_CONTEXT_MARKERS = (
    "product",
    "products",
)
DATA_ENRICHMENT_CATEGORY_URL_CONTEXT_STOP_SEGMENTS = (
    "en",
    "en-us",
    "gb",
    "intl",
    "shop",
    "store",
    "us",
    "www",
)
DATA_ENRICHMENT_PRICE_EFFECTIVE_FIELDS = (
    "price",
    "sale_price",
    "current_price",
    "final_price",
    "discounted_price",
)
DATA_ENRICHMENT_PRICE_ORIGINAL_FIELDS = (
    "original_price",
    "compare_at_price",
    "list_price",
    "was_price",
    "regular_price",
)
DATA_ENRICHMENT_COLOR_FAMILY_ALIASES = {
    "black": ("black",),
    "blue": ("blue", "navy", "cobalt", "royal blue", "sky blue"),
    "brown": ("beige", "brown", "tan", "camel", "chocolate", "taupe", "khaki"),
    "gold": ("gold", "bronze", "champagne", "rose gold"),
    "gray": ("gray", "grey", "silver", "charcoal", "slate"),
    "green": ("green", "olive", "mint", "emerald", "sage", "forest green"),
    "multi": ("multicolor", "multi", "multi color", "rainbow", "assorted"),
    "orange": ("orange", "coral", "terracotta", "rust", "peach"),
    "pink": ("pink", "blush", "rose", "fuchsia", "magenta", "mauve"),
    "purple": ("purple", "lavender", "lilac", "plum", "violet"),
    "red": ("red", "burgundy", "maroon", "crimson", "wine"),
    "white": ("white", "clear", "ivory", "cream", "ecru", "off white", "off-white"),
    "yellow": ("yellow", "mustard", "lemon"),
}
DATA_ENRICHMENT_GENDER_ALIASES = {
    "female": (
        "female",
        "women",
        "woman",
        "womens",
        "women's",
        "ladies",
        "girl",
        "girls",
    ),
    "male": ("male", "men", "man", "mens", "men's", "boy", "boys"),
    "unisex": (
        "unisex",
        "all gender",
        "all-gender",
        "gender neutral",
        "gender-neutral",
    ),
}
DATA_ENRICHMENT_AUDIENCE_ALIASES = {
    "adults": ("adult", "adults"),
    "babies": ("baby", "babies", "infant", "infants"),
    "children": ("child", "children", "kid", "kids", "toddler", "toddlers"),
}
DATA_ENRICHMENT_AVAILABILITY_TERMS = {
    "in_stock": (
        "in_stock",
        "in stock",
        "available",
        "ready to ship",
        "ships now",
        "add to cart",
        "preorder available",
    ),
    "limited_stock": (
        "limited_stock",
        "limited stock",
        "limited availability",
        "low stock",
        "few left",
        "left in stock",
    ),
    "out_of_stock": (
        "out_of_stock",
        "out of stock",
        "sold out",
        "unavailable",
        "notify me",
        "currently unavailable",
    ),
    "preorder": ("preorder", "pre-order", "pre order"),
    "backorder": ("backorder", "back order"),
}
DATA_ENRICHMENT_MATERIAL_PRIMARY_FIELDS = (
    "materials",
    "material",
    "fabric",
    "composition",
    "product_attributes",
)
DATA_ENRICHMENT_MATERIAL_FALLBACK_FIELDS = ("description",)
DATA_ENRICHMENT_COLOR_CANDIDATE_FIELDS = (
    COLOR_FIELD,
    "title",
    "category",
    "product_type",
)
DATA_ENRICHMENT_COLOR_CANDIDATE_SOURCES = (
    VARIANTS_FIELD,
    VARIANT_AXES_FIELD,
    SELECTED_VARIANT_FIELD,
)
DATA_ENRICHMENT_COLOR_CANDIDATE_TARGETS = frozenset(
    {COLOR_FIELD, "colour", "shade", "finish", "tone"}
)
DATA_ENRICHMENT_SIZE_CANDIDATE_FIELDS = (SIZE_FIELD, AVAILABLE_SIZES_FIELD)
DATA_ENRICHMENT_SIZE_CONTEXT_FIELDS = (
    "category",
    "product_type",
    "title",
    "department",
)
DATA_ENRICHMENT_SIZE_CONTEXT_TERMS = (
    "apparel",
    "clothing",
    "dress",
    "footwear",
    "jacket",
    "pant",
    "pants",
    "shirt",
    "shoe",
    "shoes",
    "sneaker",
    "trouser",
)
DATA_ENRICHMENT_SIZE_CANDIDATE_SOURCES = (
    VARIANTS_FIELD,
    VARIANT_AXES_FIELD,
    SELECTED_VARIANT_FIELD,
)
DATA_ENRICHMENT_SIZE_CANDIDATE_TARGETS = frozenset({SIZE_FIELD, WIDTH_FIELD})
DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_SOURCES = (
    VARIANTS_FIELD,
    SELECTED_VARIANT_FIELD,
)
DATA_ENRICHMENT_AVAILABILITY_CANDIDATE_TARGETS = frozenset(
    {"availability", "stock", "status", "inventory"}
)
DATA_ENRICHMENT_MATERIAL_CONTEXT_STRIP_PATTERNS = (
    r"\bcare\b.*$",
    r"\bcare instructions?\b.*$",
    r"\bwash\b.*$",
    r"\biron(?:ing)?\s+instructions?\b.*$",
    r"\bdo\s+not\s+iron\b.*$",
    r"\bdry clean\b.*$",
)
DATA_ENRICHMENT_MATERIAL_PERCENTAGE_RE = (
    r"\b(?P<percent>\d{1,3}(?:\.\d+)?)\s*%\s*(?P<material>[a-z]+(?:-[a-z]+)?(?:\s+[a-z]+(?:-[a-z]+)?){0,4})\b"
)
"""Taxonomy conflict blocks.

``context_terms`` are positive source-text cues. ``path_terms`` are taxonomy
path exclusions. Values are case-insensitive and may be phrases; a block
rejects a candidate only when source context and excluded path both match.
"""
DATA_ENRICHMENT_TAXONOMY_CONTEXT_BLOCKS = (
    {
        "context_terms": (
            "apparel",
            "clothing",
            "dress",
            "fashion",
            "jacket",
            "pant",
            "bag",
            "bags",
            "handbag",
            "handbags",
            "shirt",
            "scarf",
            "scarves",
            "shawl",
            "stole",
            "sunglasses",
            "t-shirt",
            "tee",
            "trouser",
        ),
        "path_terms": (
            "animals & pet supplies",
            "arts & crafts",
            "fabric",
            "furniture",
            "hardware",
            "pet apparel",
            "shopping bags",
            "textiles",
            "tools",
        ),
    },
    {
        "context_terms": ("boot", "footwear", "oxford", "shoe", "sneaker"),
        "path_terms": (
            "foot care",
            "insoles",
            "arch supports",
            "shoe care",
            "shoe polishes",
            "undergarments",
            "underwear",
        ),
    },
    {
        "context_terms": ("adult", "men", "mens", "women", "womens", "male", "female"),
        "path_terms": ("baby & children's", "baby", "children"),
    },
    {
        "context_terms": ("scarf", "scarves", "shawl", "stole", "accessories"),
        "path_terms": ("undergarments", "underwear"),
    },
)
DATA_ENRICHMENT_SEO_STOPWORDS = (
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "new",
    "of",
    "on",
    "or",
    "sale",
    "the",
    "to",
    "with",
    "your",
)
DATA_ENRICHMENT_SHOPIFY_ATTRIBUTE_CRAWL_FIELDS = {
    "age_group": ("age_group", "gender", "category", "product_type", "title"),
    "availability": ("availability", "stock_status", "variants"),
    "brand": ("brand", "vendor", "manufacturer"),
    "care_instructions": ("care_instructions", "product_attributes", "details"),
    "color": ("color", "variants", "title"),
    "description": ("description", "short_description", "summary"),
    "fabric": ("materials", "material", "product_attributes", "description"),
    "gender": ("gender", "department", "category", "product_type", "title"),
    "image_link": ("image_url", "image", "thumbnail"),
    "link": ("canonical_url", "source_url", "url"),
    "material": ("materials", "material", "product_attributes", "description"),
    "pattern": ("pattern", "product_attributes", "description", "title"),
    "price": ("price", "original_price"),
    "size": ("size", "variants"),
    "size_system": ("size_system", "size", "variants"),
    "target_gender": ("gender", "department", "category", "product_type", "title"),
    "title": ("title", "name"),
}

DATA_ENRICHMENT_PROMPT_REGISTRY = {
    DATA_ENRICHMENT_LLM_TASK: {
        "response_type": "object",
        "system_file": "data_enrichment_semantic.system.txt",
        "user_file": "data_enrichment_semantic.user.txt",
    },
}


@dataclass(frozen=True, slots=True)
class DataEnrichmentSettings:
    max_source_records: int = 500
    max_concurrency: int = 3
    taxonomy_path: Path = DATA_ENRICHMENT_TAXONOMY_PATH
    attributes_path: Path = DATA_ENRICHMENT_ATTRIBUTES_PATH
    category_match_threshold: float = 0.42
    candidate_flatten_max_depth: int = 50
    max_seo_keywords: int = 20
    llm_description_excerpt_chars: int = 600
    llm_taxonomy_hint_count: int = 5
    llm_semantic_list_item_chars: int = 80
    llm_call_timeout_seconds: float = 20.0
    taxonomy_phrase_source_max_chars: int = 300


data_enrichment_settings = DataEnrichmentSettings()
