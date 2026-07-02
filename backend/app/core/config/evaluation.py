"""Stable vocabulary for extraction evaluation and grounded labels."""

from typing import Final, Literal

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

COMPACT_REPRESENTATION_SCHEMA_VERSION: Final[Literal["compact_page.v2"]] = (
    "compact_page.v2"
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
