"""Cascade configuration knobs (extraction rearchitecture, Phase 0).

Single owner of the tunable thresholds and enable flags for the selector-free
listing+detail extraction cascade. Per the repo invariant, all strings /
thresholds / field-name descriptors live here, never inline in service code.

The cascade runs floors in a fixed order (adapter -> structured source -> DOM)
and only escalates to the LEARN-ONCE LLM tier as an explicit, degradable
backfill when floors produce nothing for a new template and ``llm_enabled`` is
set. Nothing here turns the LLM into a primary extractor.
"""

from __future__ import annotations

from typing import Final

# --- Capability-request escalation -----------------------------------------

# Upper bound on how many acquisition rungs a single ``CapabilityRequest`` may
# ask the acquisition ladder to climb. The contract clamps ``max_attempts`` to
# this value. Kept small: one initial attempt plus one escalation is enough to
# cover the http-shell -> rendered-html -> network-payload progression without
# unbounded re-fetch loops.
CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP: Final[int] = 2

# --- Listing record-cardinality floor --------------------------------------

# Minimum number of repeated same-shape records a listing surface must yield
# before the DOM floor is trusted to have detected a real listing grid (rather
# than a single hero card or navigation chrome).
CASCADE_LISTING_MIN_REPEATED_RECORDS: Final[int] = 3

# --- Cascade tier enable flags ---------------------------------------------

# Structured-source and DOM floors are always on; they are the deterministic
# backbone and are never gated behind an operator flag. The LEARN-ONCE LLM tier
# is off unless the crawl explicitly enables the LLM (``llm_enabled``) AND the
# per-template auto-learn gate below is satisfied.
CASCADE_ADAPTER_FLOOR_ENABLED: Final[bool] = True
CASCADE_STRUCTURED_FLOOR_ENABLED: Final[bool] = True
CASCADE_DOM_FLOOR_ENABLED: Final[bool] = True

# LEARN-ONCE LLM tier master switch. Even when True, the tier only fires for a
# crawl whose ``llm_enabled`` control is set; this flag lets the tier be
# disabled globally (e.g. during eval-gated rollout) regardless of per-crawl
# controls.
CASCADE_LEARN_ONCE_TIER_ENABLED: Final[bool] = True

# Auto-learn a recipe on first crawl only for a NEW template when the floors
# produced nothing and the crawl has ``llm_enabled`` set.
CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL: Final[bool] = True

# --- Recipe scope (User Decision #1368) ------------------------------------

# A learned recipe is scoped and replayed by (domain, surface, route_pattern).
# This tuple names the components of that key so callers do not hardcode the
# field names when building or matching a scope key.
CASCADE_RECIPE_SCOPE_KEY: Final[tuple[str, str, str]] = (
    "domain",
    "surface",
    "route_pattern",
)

# Number of consecutive replay grounding-drift failures after which a learned
# recipe is marked stale and (if eligible) recompiled once. Mirrors the
# acquisition-contract self-heal loop rather than inventing a new mechanism.
CASCADE_RECIPE_STALE_FAILURE_THRESHOLD: Final[int] = 3

__all__ = [
    "CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP",
    "CASCADE_LISTING_MIN_REPEATED_RECORDS",
    "CASCADE_ADAPTER_FLOOR_ENABLED",
    "CASCADE_STRUCTURED_FLOOR_ENABLED",
    "CASCADE_DOM_FLOOR_ENABLED",
    "CASCADE_LEARN_ONCE_TIER_ENABLED",
    "CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL",
    "CASCADE_RECIPE_SCOPE_KEY",
    "CASCADE_RECIPE_STALE_FAILURE_THRESHOLD",
]
