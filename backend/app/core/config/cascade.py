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

# Independent per-surface switch that routes the job-listing adapter through the
# same selector-free deterministic cascade (structured -> network -> DOM) as
# commerce. When False, the job-listing adapter falls back to the legacy
# ``collect_job_listing`` card collector, so operators can toggle the
# rearchitecture for job listings alone without affecting other surfaces.
CASCADE_JOB_LISTING_ENABLED: Final[bool] = True

# Independent per-surface switch that routes the commerce-detail adapter through
# the deterministic detail cascade seam (structured source floor -> DOM harvest
# pipeline). When False, the commerce-detail adapter falls back to the exact
# legacy ``harvest_ecommerce_detail`` inline harvest, so operators can toggle the
# rearchitecture for commerce detail alone without affecting other surfaces. The
# seam composes the SAME collectors in the SAME fixed order, so ON/OFF produce
# byte-identical detail records; the flag only changes which code path assembles
# them.
CASCADE_ECOMMERCE_DETAIL_ENABLED: Final[bool] = True

# Independent per-surface switch that routes the job-detail adapter through the
# deterministic detail cascade seam (structured JSON-LD floor -> DOM harvest)
# instead of the legacy ``collect_job_detail`` inline harvest. Mirrors
# ``CASCADE_ECOMMERCE_DETAIL_ENABLED`` so operators can toggle the
# rearchitecture for job detail alone without affecting other surfaces.
CASCADE_JOB_DETAIL_ENABLED: Final[bool] = True

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

# --- LEARN-ONCE compiler configuration -------------------------------------

# Per-surface allow-list for the LEARN-ONCE tier. Only surfaces named here may
# auto-learn a recipe; every other surface (e.g. ``job_detail`` until its slice
# lands) falls through to the deterministic floors and never invokes the model
# compiler. Surface *values* (not the enum) so the cascade body never branches
# on a surface literal — it membership-tests this tuple instead.
CASCADE_LEARN_ONCE_SURFACES: Final[tuple[str, ...]] = (
    "ecommerce_detail",
    "ecommerce_listing",
    "job_listing",
)

# Provider-retry budget for the single LEARN-ONCE compile call. "One model
# call" must mean exactly one provider request, so the tier passes this value
# (zero retries) to ``call_provider_with_retry`` rather than inheriting the
# global ``provider_retry_max_retries`` default (>0), which would issue up to
# ``max_retries + 1`` provider requests for a single learn attempt.
CASCADE_LEARN_ONCE_PROVIDER_MAX_RETRIES: Final[int] = 0

# Maximum number of flat-map entries handed to the model in one compile call.
# The scoped flat map is already token-capped upstream; this is a hard belt-and-
# braces bound so a pathological page cannot blow the prompt budget.
CASCADE_RECIPE_COMPILER_MAX_FLAT_MAP_ENTRIES: Final[int] = 400

# Per-domain, human-readable descriptors for the fields the compiler asks the
# model to bind. Keyed by ``SurfaceSpec.domain`` so no surface-string branching
# is needed. The compiler renders these into the prompt so the model knows what
# each requested field means without any site-specific hint.
CASCADE_RECIPE_COMPILER_FIELD_DESCRIPTORS: Final[dict[str, dict[str, str]]] = {
    "commerce": {
        "title": "The product's display name / title heading.",
        "url": "The canonical product detail page URL (href of the product link).",
        "price": "The current selling price shown to the shopper.",
        "currency": "The ISO currency code or symbol of the price.",
        "image_url": "The primary product image (img src).",
        "brand": "The product's brand or manufacturer name.",
        "category": "The product's category or breadcrumb leaf.",
        "sku": "The product's stock-keeping unit / product code.",
        "description": "The product description text.",
    },
    "jobs": {
        "title": "The job posting's title.",
        "url": "The canonical job posting detail URL (href of the posting link).",
        "apply_url": "The apply / application link for the posting.",
        "company": "The hiring company or organization name.",
        "location": "The job location (city / region / remote).",
        "department": "The team or department the role sits in.",
        "description": "The job description text.",
    },
}

# System prompt for the single LEARN-ONCE compile call. It fixes the contract:
# the model proposes flat-map PATHS only, never field values, and abstains
# (empty path) when a field is absent. Every value is re-read and re-grounded
# from the page at replay time, so the model's job is purely locating nodes.
CASCADE_RECIPE_COMPILER_SYSTEM_PROMPT: Final[str] = (
    "You are a DOM-binding locator for a storage-free extraction engine. You are "
    "given a flat map of a web page: an ordered list of DOM node paths and the "
    "visible text at each path. For each requested field, return the single flat-"
    "map PATH whose node holds that field's value. Return ONLY paths that appear "
    "verbatim in the provided flat map. NEVER return a field value, a guessed "
    "path, or a path that is not in the flat map. If a field is not present on "
    "the page, return an empty string for it. For listing pages, also return the "
    "repeated record-root path: the shortest ancestor path shared by every "
    "repeated record card. Respond with a single JSON object of the form "
    '{"record_root": "<path or empty>", "fields": {"<field>": "<path or empty>"}} '
    "and nothing else."
)

# User-prompt template for the compile call. ``$surface``/``$fields``/``$flat_map``
# are substituted by the compiler; the rendering is owned here, never inline in
# the compiler module.
CASCADE_RECIPE_COMPILER_USER_TEMPLATE: Final[str] = (
    "Surface: $surface\n"
    "Requested fields (name: meaning):\n$fields\n\n"
    "Flat map (path => text):\n$flat_map\n\n"
    "Return the JSON object described in the system prompt."
)

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

# Fact-name suffixes that mark a listing surface's record signals as *visual*
# (image or price). A schema whose ``record_signal_facts`` carry one of these
# (commerce: ``asset.image_url`` / ``offer.price``) keeps the default
# image-or-price record signal; a schema without any of them (jobs) gets a
# non-visual text-and-detail-link signal instead, so job cards are not rejected
# for lacking a price or image. Descriptor lives in config, not discovery code.
CASCADE_LISTING_VISUAL_RECORD_SIGNAL_SUFFIXES: Final[tuple[str, ...]] = (
    ".image_url",
    ".price",
)

# Minimum word-count a non-visual record container (job card) must carry before
# its text-bearing detail link is trusted as a real posting rather than a bare
# nav chip. Mirrors the commerce text-card fallback's 3-word floor.
CASCADE_LISTING_RECORD_MIN_TEXT_TOKENS: Final[int] = 3

# Record-local identity attributes used to admit anchor-less JS-onclick cards: a
# repeated container that carries NO ``<a href>`` but exposes one of these
# stable per-record keys (data-* / id tokens) and repeats at least
# ``CASCADE_LISTING_MIN_REPEATED_RECORDS`` times is still a record set. Purely
# structural attribute names (never site-specific), so commerce anchor grids —
# which always carry a detail ``<a href>`` — are unaffected.
CASCADE_LISTING_RECORD_KEY_ATTRIBUTES: Final[tuple[str, ...]] = (
    "data-id",
    "data-job-id",
    "data-posting-id",
    "data-requisition-id",
    "data-req-id",
    "data-opportunity-id",
    "data-record-id",
    "data-testid",
    "id",
)

# Attributes on (or inside) an anchor-less card that carry a recoverable detail
# URL directly. An anchor-less JS-onclick card is admitted ONLY when a real
# detail URL can be recovered from the card's navigation affordance — a card
# that merely carries a stable id/data-testid with no navigation target (a
# department/category tile) is NOT a job record and is rejected. Purely
# structural attribute names, never site-specific.
CASCADE_LISTING_RECORD_URL_ATTRIBUTES: Final[tuple[str, ...]] = (
    "data-href",
    "data-url",
    "data-link",
    "data-apply-url",
    "data-detail-url",
    "data-posting-url",
)

# Handler attributes whose JavaScript body may embed the card's detail URL
# (``onclick="location.href='/jobs/123'"``). Scanned with
# ``CASCADE_LISTING_ONCLICK_URL_PATTERN`` to recover the navigation target.
CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES: Final[tuple[str, ...]] = (
    "onclick",
    "data-onclick",
)

# Extracts the first quoted absolute URL or root-relative path from an onclick /
# handler string, e.g. ``location.href='/careers/positions/123'`` ->
# ``/careers/positions/123``. Purely structural (a quoted path/URL), never a
# per-site route enumeration.
CASCADE_LISTING_ONCLICK_URL_PATTERN: Final[str] = (
    r"""['"](\/[^'"\s]*|https?:\/\/[^'"\s]+)['"]"""
)

__all__ = [
    "CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP",
    "CASCADE_LISTING_MIN_REPEATED_RECORDS",
    "CASCADE_ADAPTER_FLOOR_ENABLED",
    "CASCADE_STRUCTURED_FLOOR_ENABLED",
    "CASCADE_DOM_FLOOR_ENABLED",
    "CASCADE_ECOMMERCE_LISTING_ENABLED",
    "CASCADE_JOB_LISTING_ENABLED",
    "CASCADE_ECOMMERCE_DETAIL_ENABLED",
    "CASCADE_JOB_DETAIL_ENABLED",
    "CASCADE_LEARN_ONCE_TIER_ENABLED",
    "CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL",
    "CASCADE_RECIPE_SCOPE_KEY",
    "CASCADE_RECIPE_STALE_FAILURE_THRESHOLD",
    "CASCADE_LEARN_ONCE_SURFACES",
    "CASCADE_RECIPE_COMPILER_MAX_FLAT_MAP_ENTRIES",
    "CASCADE_RECIPE_COMPILER_FIELD_DESCRIPTORS",
    "CASCADE_RECIPE_COMPILER_SYSTEM_PROMPT",
    "CASCADE_RECIPE_COMPILER_USER_TEMPLATE",
    "CASCADE_STRUCTURED_LISTING_CONFIDENCE",
    "CASCADE_NETWORK_LISTING_CONFIDENCE",
    "CASCADE_DOM_LISTING_CONFIDENCE",
    "CASCADE_NETWORK_LISTING_MIN_ROWS",
    "CASCADE_NETWORK_URL_TEMPLATE_PATTERN",
    "CASCADE_NETWORK_ZERO_UUID",
    "CASCADE_LISTING_PRICE_SIGNAL_PATTERN",
    "CASCADE_LISTING_VISUAL_RECORD_SIGNAL_SUFFIXES",
    "CASCADE_LISTING_RECORD_MIN_TEXT_TOKENS",
    "CASCADE_LISTING_RECORD_KEY_ATTRIBUTES",
    "CASCADE_LISTING_RECORD_URL_ATTRIBUTES",
    "CASCADE_LISTING_RECORD_ONCLICK_ATTRIBUTES",
    "CASCADE_LISTING_ONCLICK_URL_PATTERN",
]
