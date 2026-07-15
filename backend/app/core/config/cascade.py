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
# than a single hero card or navigation chrome). Matches the reference branch's
# proven ``_MIN_REPEATED_RECORDS`` primitive: DOM-only discovery stays
# repetition-gated at 2 (a single structured record is admissible only via
# structured corroboration, never DOM-only).
CASCADE_LISTING_MIN_REPEATED_RECORDS: Final[int] = 2

# --- Cascade tier enable flags ---------------------------------------------

# Structured-source and DOM floors are always on; they are the deterministic
# backbone and are never gated behind an operator flag. The LEARN-ONCE LLM tier
# is off unless the crawl explicitly enables the LLM (``llm_enabled``) AND the
# per-template auto-learn gate below is satisfied.
CASCADE_ADAPTER_FLOOR_ENABLED: Final[bool] = True
CASCADE_STRUCTURED_FLOOR_ENABLED: Final[bool] = True
CASCADE_DOM_FLOOR_ENABLED: Final[bool] = True

# --- Per-surface cascade enable gates --------------------------------------

# Independent per-surface switch that routes the commerce-listing adapter
# through the selector-free deterministic cascade (structured -> network ->
# DOM). When False, the commerce-listing adapter falls back to the legacy
# ``collect_ecommerce_listing`` card collector, so operators can toggle the
# rearchitecture for commerce listings alone without affecting other surfaces.
CASCADE_ECOMMERCE_LISTING_ENABLED: Final[bool] = True

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

# --- Listing floor evidence tunables ---------------------------------------

# Per-floor confidence assigned to the evidence each deterministic listing
# floor emits. Structured (JSON-LD / microdata) is the strongest signal, the
# network-JSON floor slightly less so, and the generic DOM floor the weakest of
# the three. Kept here (not inline in the floor modules) per the config-owns-
# thresholds invariant.
CASCADE_STRUCTURED_LISTING_CONFIDENCE: Final[float] = 0.9
CASCADE_NETWORK_LISTING_CONFIDENCE: Final[float] = 0.86
CASCADE_DOM_LISTING_CONFIDENCE: Final[float] = 0.72

# Minimum members a repeated network-JSON array must have before it is treated
# as a listing row group (rejects singletons and response metadata).
CASCADE_NETWORK_LISTING_MIN_ROWS: Final[int] = 2

# Pattern matching a URL that carries a query string (a detail-URL *template*
# candidate in rendered HTML). Used to ground opaque response ids to page-local
# detail links without any site-specific rules.
CASCADE_NETWORK_URL_TEMPLATE_PATTERN: Final[str] = (
    r"(?:https?://|/)[^\"'\s<>]+[?&][^\"'\s<>]*"
)

# The all-zero UUID commonly used as a placeholder id in a detail-URL template.
CASCADE_NETWORK_ZERO_UUID: Final[str] = "00000000-0000-0000-0000-000000000000"

# Default (commerce) record-signal: a currency symbol or ISO code anywhere in a
# candidate container's text marks it as a product record, like an image does.
# Symbol/code based (not locale-specific formatting) so it holds across markets:
# $, £, €, ₹, ¥ and the common ISO codes / "Rs".
CASCADE_LISTING_PRICE_SIGNAL_PATTERN: Final[str] = (
    r"[\$£€₹¥]|\b(?:USD|EUR|GBP|INR|CAD|AUD|JPY|Rs)\b"
)

__all__ = [
    "CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP",
    "CASCADE_LISTING_MIN_REPEATED_RECORDS",
    "CASCADE_ADAPTER_FLOOR_ENABLED",
    "CASCADE_STRUCTURED_FLOOR_ENABLED",
    "CASCADE_DOM_FLOOR_ENABLED",
    "CASCADE_ECOMMERCE_LISTING_ENABLED",
    "CASCADE_LEARN_ONCE_TIER_ENABLED",
    "CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL",
    "CASCADE_RECIPE_SCOPE_KEY",
    "CASCADE_RECIPE_STALE_FAILURE_THRESHOLD",
    "CASCADE_STRUCTURED_LISTING_CONFIDENCE",
    "CASCADE_NETWORK_LISTING_CONFIDENCE",
    "CASCADE_DOM_LISTING_CONFIDENCE",
    "CASCADE_NETWORK_LISTING_MIN_ROWS",
    "CASCADE_NETWORK_URL_TEMPLATE_PATTERN",
    "CASCADE_NETWORK_ZERO_UUID",
    "CASCADE_LISTING_PRICE_SIGNAL_PATTERN",
]
