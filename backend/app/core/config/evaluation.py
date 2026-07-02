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
TRUST_OUTCOMES = frozenset({"trusted", "review", "rejected", "blocked"})
