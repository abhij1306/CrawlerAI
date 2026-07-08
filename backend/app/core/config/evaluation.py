"""Stable vocabulary for extraction evaluation and grounded labels."""

from typing import Final, Literal, TypedDict

EVALUATION_CASE_SCHEMA_VERSION: Final[Literal["evaluation_case.v1"]] = (
    "evaluation_case.v1"
)
GROUNDED_LABEL_SCHEMA_VERSION: Final[Literal["grounded_label.v1"]] = "grounded_label.v1"

LABEL_AUTHORITIES = frozenset(
    {
        "human_verified",
        "deterministic_pseudo",
        "weak",
        "unverified_model",
    }
)
LABEL_TARGET_KINDS = frozenset(
    {
        "page_region",
        "record_boundary",
        "field",
        "entity_relationship",
        "explicit_absence",
    }
)
GROUNDING_REFERENCE_KINDS = frozenset({"node", "path", "region", "absence_assertion"})
REGION_SEMANTIC_ROLES = frozenset(
    {"primary", "recommendation", "boilerplate", "unrelated"}
)
EVALUATION_PARTITIONS = frozenset(
    {
        "known_template",
        "unseen_domain",
        "unseen_template",
        "temporal_change",
        "ab_variant",
        "personalized_or_promotional",
        "market_or_locale",
        "platform_collision",
        "sentinel_disagreement",
    }
)
EVALUATION_SURFACES = frozenset(
    {
        "ecommerce_listing",
        "ecommerce_detail",
        "job_listing",
        "job_detail",
    }
)
EVALUATION_SCENARIOS = frozenset(
    {
        "multi_variant",
        "personalized_or_promotional",
        "platform_collision",
        "sentinel_disagreement",
    }
)
TRUST_OUTCOMES = frozenset({"trusted", "review", "rejected", "blocked"})

# Grounded LLM repair (Phase 7, offline / operator-loop). The model may only
# propose grounded repairs; these route through the same compile/replay/activation
# gates as operator corrections but are never release-eligible and never self-activate.
GROUNDED_REPAIR_LLM_TASK: Final[str] = "grounded_extraction_repair"
GROUNDED_REPAIR_NO_PROPOSALS_STATUS: Final[str] = "no_grounded_repairs"
GROUNDED_REPAIR_CUSTOM_FIELD_TYPES = frozenset(
    {
        "string",
        "list",
        "number",
        "money",
        "date",
        "boolean",
        "enum",
        "key_value",
        "structured_object",
    }
)
GROUNDED_REPAIR_CUSTOM_FIELD_CARDINALITIES = frozenset({"single", "multi"})
GROUNDED_REPAIR_PUBLISH_POLICIES = frozenset({"retain_only", "publish_when_valid"})
GROUNDED_REPAIR_PROMPT_REGISTRY: Final[dict[str, dict[str, str]]] = {
    GROUNDED_REPAIR_LLM_TASK: {
        "response_type": "object",
        "system_file": "grounded_extraction_repair.system.txt",
        "user_file": "grounded_extraction_repair.user.txt",
    },
}
GENERALIZED_EXTRACTION_LLM_TASK: Final[str] = "generalized_extraction"
GENERALIZED_EXTRACTION_HOSTED_ADAPTER_ID: Final[str] = (
    "hosted_llm_generalized_extraction"
)
GENERALIZED_EXTRACTION_RESPONSE_SCHEMA_VERSION: Final[
    Literal["generalized_extraction_response.v1"]
] = "generalized_extraction_response.v1"
GENERALIZED_EXTRACTION_PROMPT_REGISTRY: Final[dict[str, dict[str, str]]] = {
    GENERALIZED_EXTRACTION_LLM_TASK: {
        "response_type": "object",
        "system_file": "generalized_extraction.system.txt",
        "user_file": "generalized_extraction.user.txt",
    },
}
GENERALIZED_EXTRACTION_FIELD_SENSES: Final[tuple[dict[str, str], ...]] = (
    {"field": "title", "fact_type": "product.title", "sense": "product display title"},
    {
        "field": "description",
        "fact_type": "product.description",
        "sense": "product description, not navigation or reviews",
    },
    {"field": "brand", "fact_type": "product.brand", "sense": "manufacturer brand"},
    {"field": "sku", "fact_type": "product.sku", "sense": "selected product sku"},
    {"field": "mpn", "fact_type": "product.mpn", "sense": "manufacturer part number"},
    {"field": "gtin", "fact_type": "product.gtin", "sense": "UPC/EAN/GTIN barcode"},
    {
        "field": "category",
        "fact_type": "product.category",
        "sense": "breadcrumb category path",
    },
    {
        "field": "price",
        "fact_type": "offer.price",
        "sense": "current sell price after discount",
    },
    {
        "field": "sale_price",
        "fact_type": "offer.price",
        "sense": "discounted sale price only when distinct from list price",
    },
    {
        "field": "original_price",
        "fact_type": "offer.original_price",
        "sense": "struck-through or compare-at list price",
    },
    {"field": "currency", "fact_type": "offer.currency", "sense": "ISO currency"},
    {
        "field": "availability",
        "fact_type": "offer.availability",
        "sense": "selected product availability",
    },
    {"field": "image", "fact_type": "asset.image_url", "sense": "same-product image"},
    {"field": "variant_id", "fact_type": "variant.id", "sense": "variant id"},
    {"field": "variant_sku", "fact_type": "variant.sku", "sense": "variant sku"},
    {
        "field": "variant_size",
        "fact_type": "variant.option.size",
        "sense": "variant size option",
    },
    {
        "field": "variant_color",
        "fact_type": "variant.option.color",
        "sense": "variant color option",
    },
    {
        "field": "variant_price",
        "fact_type": "offer.price",
        "sense": "variant-specific sell price",
    },
    {
        "field": "variant_availability",
        "fact_type": "offer.availability",
        "sense": "variant-specific availability",
    },
)

COMPACT_REPRESENTATION_SCHEMA_VERSION: Final[Literal["compact_page.v2"]] = (
    "compact_page.v2"
)
EXTRACTION_V3_FLAT_MAP_PAGE_SCHEMA_VERSION: Final[Literal["flat_map_page.v1"]] = (
    "flat_map_page.v1"
)
COMPACT_REPRESENTATION_MAX_NODES: Final[int] = 80
COMPACT_REPRESENTATION_MAX_TEXT_CHARS: Final[int] = 120
COMPACT_REPRESENTATION_ATTRIBUTES: Final[tuple[str, ...]] = (
    "id",
    "class",
    "href",
    "src",
    "alt",
    "title",
    "aria-label",
    "role",
    "itemprop",
    "data-testid",
    "data-test-id",
    "data-test-dataid",
    "test-data-id",
    "test-dataid",
)
COMPACT_REPRESENTATION_EXCLUDED_TAGS: Final[frozenset[str]] = frozenset(
    {"script", "style", "noscript", "svg", "template"}
)

RELEASE_REQUIRED_EVALUATION_PARTITIONS: Final[tuple[str, ...]] = (
    "known_template",
    "unseen_domain",
    "unseen_template",
    "temporal_change",
    "ab_variant",
    "market_or_locale",
)
RELEASE_REQUIRED_EVALUATION_SURFACES: Final[tuple[str, ...]] = (
    "ecommerce_listing",
    "ecommerce_detail",
    "job_listing",
    "job_detail",
)
RELEASE_REQUIRED_EVALUATION_SCENARIOS: Final[tuple[str, ...]] = (
    "multi_variant",
    "sentinel_disagreement",
)
UNIVERSAL_MODEL_REQUIRED_METRICS: Final[tuple[str, ...]] = (
    "field_precision",
    "field_recall",
    "field_f1",
    "normalized_exact_match",
    "record_boundary_accuracy",
    "variant_binding_accuracy",
    "recommendation_contamination_rate",
    "ungrounded_value_rate",
    "latency_ms_p95",
    "memory_mb_p95",
    "cost_per_1000_pages",
)
UNIVERSAL_MODEL_BENCHMARK_SCHEMA_VERSION: Final[
    Literal["universal_model_benchmark.v2"]
] = "universal_model_benchmark.v2"

UNIVERSAL_MODEL_RUNTIME_SNAPSHOT_KEY: Final[str] = "universal_model"
UNIVERSAL_MODEL_COLLECTOR_ID: Final[str] = "universal_model"

EXTRACTION_V3_EVAL_SCHEMA_VERSION: Final[Literal["extraction_v3_eval.v1"]] = (
    "extraction_v3_eval.v1"
)
EXTRACTION_V3_LABEL_SCHEMA_VERSION: Final[Literal["extraction_v3_label.v1"]] = (
    "extraction_v3_label.v1"
)
EXTRACTION_V3_BASELINE_SCHEMA_VERSION: Final[Literal["extraction_v3_baseline.v1"]] = (
    "extraction_v3_baseline.v1"
)
EXTRACTION_V3_COMMERCE_DETAIL_SURFACE: Final[str] = "commerce_detail"
EXTRACTION_V3_EXCLUDED_RESULT_DIRS: Final[frozenset[int]] = frozenset({6, 79, 83})
EXTRACTION_V3_VARIANT_BUCKETS: Final[tuple[str, ...]] = (
    "embedded_json",
    "dom_only",
    "partial",
    "single_sku",
    "unknown",
)
# Buckets whose pages carry a real variant matrix, so an empty variants list is a
# defect. Excludes single_sku (no variants expected) and unknown (unclassified).
EXTRACTION_V3_VARIANT_EXPECTED_BUCKETS: Final[frozenset[str]] = frozenset(
    {"embedded_json", "dom_only", "partial"}
)
EXTRACTION_V3_LABEL_CORE_FIELDS: Final[tuple[str, ...]] = (
    "title",
    "description",
    "price",
    "sale_price",
    "currency",
    "availability",
    "brand",
    "gtin",
    "mpn",
    "sku",
    "images",
    "category",
)
EXTRACTION_V3_MIN_HUMAN_LABELS_PER_NEW_SURFACE: Final[int] = 20
EXTRACTION_V3_SURFACE_LABEL_FIELDS: Final[dict[str, tuple[str, ...]]] = {
    EXTRACTION_V3_COMMERCE_DETAIL_SURFACE: EXTRACTION_V3_LABEL_CORE_FIELDS,
    "ecommerce_listing": ("title", "price", "currency", "url", "image_url"),
    "job_detail": (
        "title",
        "company",
        "location",
        "description",
        "employment_type",
        "salary",
        "posted_at",
        "url",
    ),
    "job_listing": ("title", "company", "location", "url"),
}
EXTRACTION_V3_BASELINE_EXPECTED_DEFECTS: Final[dict[str, int]] = {
    "empty_records": 5,
    "missing_price_on_commerce_detail": 13,
    "empty_variants_where_expected": 11,
}
EXTRACTION_V3_FULL_CORPUS_GATE_DEFECTS: Final[tuple[str, ...]] = (
    "empty_records",
    "empty_variants_where_expected",
)
EXTRACTION_V3_FLAT_MAP_EXCLUDED_TAGS: Final[frozenset[str]] = frozenset(
    {"script", "style", "noscript", "svg", "template"}
)
EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS: Final[tuple[str, ...]] = (
    "price",
    "add to cart",
    "availability",
    "sku",
    "description",
)
EXTRACTION_V3_SCOPED_MIN_TOKENS: Final[int] = 300
EXTRACTION_V3_MAX_INPUT_TOKENS: Final[int] = 60000
EXTRACTION_V3_CHUNK_TARGET_TOKENS: Final[int] = 12000


class _GeneralizedExtractionBudget(TypedDict):
    budget_ms: int
    model_tier: str
    max_cost_usd_per_page: float
    max_input_tokens: int
    max_output_tokens: int
    escalate_to_vision_below_confidence: float
    cooldown_minutes: int


GENERALIZED_EXTRACTION_BUDGET: Final[_GeneralizedExtractionBudget] = {
    # Per-page ceiling for a hosted-LLM fallback call. This fires only on cache
    # miss / recipe drift, not every page, so a multi-second ceiling is affordable
    # at <=20k pages/day. 1000ms was a placeholder tuned to the synchronous test
    # adapter and is impossible for any real hosted provider (Mistral p95 ~20-30s
    # on a 6-12k-token scoped map); 30s captures the successful-call distribution
    # while still bounding the tail so a hung provider can't stall the crawl.
    "budget_ms": 30000,
    "model_tier": "hosted_llama",
    "max_cost_usd_per_page": 0.02,
    "max_input_tokens": EXTRACTION_V3_MAX_INPUT_TOKENS,
    # Output ceiling for the grounded prediction array. The per-provider defaults
    # (e.g. mistral_max_tokens=1200) are tuned to short single-record tasks and
    # truncate a full generalized-extraction array mid-JSON -> unparseable ->
    # ValueError -> nothing published. A scoped map yields one prediction row per
    # field-sense with an XPath + evidence text; 8000 tokens covers the observed
    # array size with headroom while staying well under provider hard limits.
    "max_output_tokens": 8000,
    "escalate_to_vision_below_confidence": 0.8,
    "cooldown_minutes": 5,
}
EXTRACTION_V3_GROUNDING_CURRENCY_SYMBOLS: Final[dict[str, str]] = {
    "$": "usd",
    "€": "eur",
    "£": "gbp",
    "₹": "inr",
}
