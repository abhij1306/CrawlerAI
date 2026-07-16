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

# ---------------------------------------------------------------------------
# Offline evaluation harness (backend/eval/*).
#
# Deterministic, zero-network, zero-LLM gating for per-surface selector
# deletion. These constants are the only tunables the harness consumes; the
# scorer and comparator read them rather than hard-coding thresholds in
# service code (repo invariant: config strings/thresholds live under
# ``app/core/config/*``).
# ---------------------------------------------------------------------------

# Directory layout for fixture HTML, ground-truth labels, and emitted reports,
# expressed relative to the ``backend/eval`` package root.
EVAL_HARNESS_FIXTURES_DIRNAME: Final[str] = "fixtures"
EVAL_HARNESS_LABELS_DIRNAME: Final[str] = "labels"
EVAL_HARNESS_REPORTS_DIRNAME: Final[str] = "reports"

# File extensions for a fixture HTML page and its paired label JSON. Fixtures
# and labels are matched by identical stem (``<stem>.html`` <-> ``<stem>.json``).
EVAL_HARNESS_FIXTURE_SUFFIX: Final[str] = ".html"
EVAL_HARNESS_LABEL_SUFFIX: Final[str] = ".json"

# Stable key names in a label JSON document. A label file is a list of record
# objects; each record maps field name -> emitted string value(s).
EVAL_HARNESS_LABEL_RECORDS_KEY: Final[str] = "records"

# Minimum improvement a candidate must show over baseline before a rate metric
# (precision / recall / boundary correctness) counts as a regression. A
# candidate is allowed to drop by at most this tolerance and still pass, which
# absorbs floating-point noise without permitting real quality loss.
EVAL_HARNESS_MIN_RATE_DELTA: Final[float] = 1e-9

# Grounding tolerance: fraction of a fixture's emitted string values that may
# fail the substring-in-source grounding proxy before the candidate is treated
# as regressing on hallucination. Kept at zero by default so any ungrounded
# value is surfaced; comparison also enforces candidate hallucination count
# <= baseline hallucination count.
EVAL_HARNESS_GROUNDING_TOLERANCE: Final[float] = 0.0


# --- Flat-map representation (selector-free grounding) ---------------------
# Tags whose subtree text is never part of the flat path->text representation:
# scripts/styles leak source code, svg/template leak non-visible markup.
EXTRACTION_V3_FLAT_MAP_EXCLUDED_TAGS: Final[frozenset[str]] = frozenset(
    {"script", "style", "noscript", "svg", "template"}
)
# Anchor phrases used to locate the content-rich scope region of a page and to
# confirm a scoped flat-map actually contains extractable signal.
EXTRACTION_V3_FLAT_MAP_CORE_ANCHORS: Final[tuple[str, ...]] = (
    "price",
    "add to cart",
    "availability",
    "sku",
    "description",
)
# A scoped region below this rough token count is treated as too thin and the
# full-document flat map is used instead.
EXTRACTION_V3_SCOPED_MIN_TOKENS: Final[int] = 300
# Hard ceiling on flat-map tokens handed to the learn-once model call.
EXTRACTION_V3_MAX_INPUT_TOKENS: Final[int] = 60000
# Target size per chunk when a flat map exceeds the input ceiling.
EXTRACTION_V3_CHUNK_TARGET_TOKENS: Final[int] = 12000
# Currency symbol -> normalized token, used to ground price-like values whose
# symbol differs between the page and the emitted value.
EXTRACTION_V3_GROUNDING_CURRENCY_SYMBOLS: Final[dict[str, str]] = {
    "$": "usd",
    "€": "eur",
    "£": "gbp",
    "₹": "inr",
}
