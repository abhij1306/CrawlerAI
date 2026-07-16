"""Stable vocabulary for the relational extraction-memory store."""

EXTRACTION_MEMORY_STATUS_ACTIVE = "active"
EXTRACTION_MEMORY_STATUS_PROVISIONAL = "provisional"
EXTRACTION_MEMORY_STATUS_RETIRED = "retired"
EXTRACTION_MEMORY_STATUS_SUSPENDED = "suspended"
EXTRACTION_MEMORY_STATUS_TRUSTED = EXTRACTION_MEMORY_STATUS_ACTIVE
EXTRACTION_RECIPE_LAYER_PLATFORM = "platform"
EXTRACTION_RECIPE_LAYER_DOMAIN = "domain"
EXTRACTION_RECIPE_LAYER_TEMPLATE = "template"
EXTRACTION_RECIPE_LAYER_LOCALE = "locale"
EXTRACTION_RECIPE_LAYER_EXCEPTION = "exception"
EXTRACTION_RECIPE_LAYER_ORDER = (
    EXTRACTION_RECIPE_LAYER_PLATFORM,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    EXTRACTION_RECIPE_LAYER_LOCALE,
    EXTRACTION_RECIPE_LAYER_EXCEPTION,
)
EXTRACTION_RECIPE_KIND_SELECTORS = "selectors"
EXTRACTION_RECIPE_KIND_CONTRACTS = "contracts"
# LEARN-ONCE executable recipe (``extraction_recipe.v2``) stored as one recipe
# layer keyed by ``(domain, surface, route_pattern)``.
EXTRACTION_RECIPE_KIND_EXECUTABLE = "executable_recipe"
EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC = "generic"
EXTRACTION_CONTRACT_RESOLVER_OBSERVED = "observed_published_evidence"
EXTRACTION_CONTRACT_OBSERVATION_SOURCE = "successful_crawl"
EXTRACTION_CONTRACT_CANDIDATE_LIMIT = 8
EXTRACTION_CONTRACT_HISTORY_LIMIT = 20
EXTRACTION_CONTRACT_OBSERVABLE_VERDICTS = ("success", "partial", "review")
EXTRACTION_LABEL_KIND_FIELD_FEEDBACK = "field_feedback"
EXTRACTION_LABEL_KIND_GROUNDED_CORRECTION = "grounded_correction"
EXTRACTION_LABEL_KIND_REVIEW_PROMOTION = "review_promotion"
EXTRACTION_LABEL_KIND_RECIPE_OVERRIDE = "recipe_override"
# Operator label kinds that constitute explicit ownership of a specific
# template's recipe. Only these — scoped to the exact ``template_id`` — exempt a
# learned recipe from auto-suspension on drift; a generic domain/surface label
# is not enough.
EXTRACTION_RECIPE_OWNERSHIP_LABEL_KINDS = (
    EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
    EXTRACTION_LABEL_KIND_RECIPE_OVERRIDE,
)
EXTRACTION_CORRECTION_STATUS_REPLAY_PASSED = "replay_passed"
EXTRACTION_CORRECTION_STATUS_REPLAY_FAILED = "replay_failed"
EXTRACTION_CORRECTION_STATUS_ACTIVATED = "activated"
EXTRACTION_COMPILER_VERSION = "recipe.v1"
# One versioned release payload per run. It carries selector/contract recipes
# AND executable ``extraction_recipe.v2`` recipes so a single frozen snapshot
# drives both the deterministic floors and LEARN-ONCE recipe replay. Bumped from
# ``release.v1`` when executable recipes were folded into the unified payload.
EXTRACTION_RELEASE_VERSION = "release.v2"
EXTRACTION_MANIFEST_VERSION = "manifest.v1"
SENTINEL_DETERMINISTIC_CHALLENGER_ENABLED = True
SENTINEL_DEFAULT_SAMPLE_RATE = 0.05
SENTINEL_CRITICAL_DRIFT_CONFIRMATION_THRESHOLD = 2
SENTINEL_OBSERVATION_KIND = "sentinel_challenger"
SENTINEL_SUSPENSION_KIND = "sentinel_suspension"
