"""Canonical config for the self-healing observability / run-audit layer.

All tunables for run tracing and auditing live here (INVARIANT Rule 1). Service
code in ``app/services/observability/*`` imports from this module and must not
define its own thresholds, artifact names, or token constants.
"""

from __future__ import annotations

# --- Master switch -----------------------------------------------------------
# When False, the RunTrace collector is a no-op and nothing is written. Kept as
# a plain module constant so it can be patched in tests and overridden via the
# settings layer without importing service code.
RUN_TRACE_ENABLED = True

# --- Artifact layout ---------------------------------------------------------
# Subdirectories under ``artifacts/runs/<run_id>/`` owned by this layer.
TRACE_ARTIFACT_SUBDIR = "trace"
AUDIT_ARTIFACT_SUBDIR = "audit"
RUN_TRACE_FILENAME = "run_trace.json"
FLAGS_FILENAME = "flags.json"
LLM_DIAGNOSIS_FILENAME = "llm_diagnosis.json"

# Schema version stamped into every run_trace.json so readers (audit engine,
# future frontend) can evolve safely.
RUN_TRACE_SCHEMA_VERSION = 1

# --- Trace tiers -------------------------------------------------------------
# Lightweight trace is always captured. Full candidate-competition detail (every
# losing candidate + reject reason for high-value fields) is captured only when
# the verdict is not in this success set, OR when an audit flag fires.
TRACE_TIER_LIGHT = "light"
TRACE_TIER_FULL = "full"

# Verdicts that are considered clean enough to skip full candidate-competition
# capture. Mirrors the publish verdict vocabulary; kept here so the trace layer
# does not import publish internals just for the string.
TRACE_SUCCESS_VERDICTS = frozenset({"success"})

# --- High-value field policy hook --------------------------------------------
# The high-value field set = union(run requested_fields, default canonical
# repair targets for the surface). The trace layer resolves this via
# ``app.services.field_policy.repair_target_fields_for_surface`` and must not
# hardcode a parallel list. This constant only bounds candidate capture when no
# requested/default fields resolve (defensive floor for ecommerce detail).
HIGH_VALUE_FIELD_FLOOR = ("price", "title", "image_url")

# Detail fields that are always useful for debugging extraction quality, even
# when the run did not request them. These do not make a field contractually
# required; they only widen trace visibility so missing/deleted variant paths are
# obvious from artifacts.
DETAIL_DIAGNOSTIC_FIELDS = (
    "availability",
    "brand",
    "color",
    "sku",
    "size",
    "variant_count",
    "variants",
)

# Max losing candidates captured per field in full-tier traces. Bounds trace
# size on pathological pages with many rejected candidates.
MAX_CANDIDATE_LOSERS_PER_FIELD = 12

# --- Acquire-timeline event kinds --------------------------------------------
# Stable identifiers for ordered acquire-timeline events so the audit engine and
# frontend can match on kind rather than free text.
ACQUIRE_EVENT_NAVIGATION = "navigation"
ACQUIRE_EVENT_HTTP_FETCH = "http_fetch"
ACQUIRE_EVENT_READINESS_PROBE = "readiness_probe"
ACQUIRE_EVENT_INTERSTITIAL = "interstitial"
ACQUIRE_EVENT_CHALLENGE = "challenge"
ACQUIRE_EVENT_ESCALATION = "escalation"
ACQUIRE_EVENT_POLICY_DECISION = "policy_decision"

# --- Extraction-trace stage names --------------------------------------------
EXTRACTION_TIER_AUTHORITATIVE = "authoritative"
EXTRACTION_TIER_STRUCTURED = "structured_data"
EXTRACTION_TIER_JS_STATE = "js_state"
EXTRACTION_TIER_DOM = "dom"

# --- DOM-skip decision contract ----------------------------------------------
# Keys of the observe-only ``_dom_skip_decision`` record dict produced by the
# detail tier runner and consumed by the trace projection + audit engine. Kept
# here so producer (tiers.py) and consumers (run_audit.py, trace) cannot drift.
DOM_SKIP_KEY_SKIPPED = "dom_skipped"
DOM_SKIP_KEY_CONFIDENCE = "confidence"
DOM_SKIP_KEY_THRESHOLD = "threshold"
DOM_SKIP_KEY_REASON = "reason"

# Canonical reason values for the DOM-skip decision.
DOM_SKIP_REASON_CLEARED = "confidence_cleared_no_dom_completion_needed"
DOM_SKIP_REASON_CONFIDENCE_BELOW_THRESHOLD = "confidence_below_threshold"
DOM_SKIP_REASON_DOM_COMPLETION_REQUIRED = "dom_completion_required"

# --- Persisted browser.json shaping (Slice 2) --------------------------------
# The runtime browser_diagnostics dict stays as-is for in-memory consumers
# (contract memory, listing decisions, log messages). Only the *saved* artifact
# is shaped to be honest and lean via these rules.
#
# Engine-derivable fields: pure functions of ``browser_engine`` (see
# ``browser_diagnostics.browser_profile_diagnostics``). Dropped from the saved
# file and recomputed on read by ``derive_browser_profile_fields``.
BROWSER_ARTIFACT_DERIVABLE_FIELDS = frozenset(
    {
        "browser_headless",
        "browser_launch_mode",
        "browser_profile",
        "browser_native_context",
        "browser_binary",
        "browser_stealth_enabled",
    }
)

# Listing-only diagnostics: meaningful on listing surfaces, pure noise on detail
# /content/other surfaces. Dropped from the saved file when surface is not a
# listing surface.
BROWSER_ARTIFACT_LISTING_ONLY_FIELDS = frozenset(
    {
        "listing_readiness",
        "listing_recovery",
        "listing_artifact_capture",
        "extractable_listing_evidence",
        "rendered_listing_fragment_count",
        "listing_visual_element_count",
        "listing_visual_capture",
    }
)

# Keys that carry no signal when empty: dropped from the saved file if their
# value is an empty list/dict (kept verbatim when populated).
BROWSER_ARTIFACT_DROP_WHEN_EMPTY = frozenset(
    {
        "challenge_evidence",
        "challenge_provider_hits",
        "challenge_element_hits",
        "behavior_realism",
        "policy_decisions",
        "host_outcome",
    }
)

# Substring marking a surface as a listing surface (mirrors pipeline usage).
LISTING_SURFACE_KEYWORD = "listing"

# Pre-fetch host snapshot key (misleading on read-back) replaced by an honest
# post-fetch ``host_outcome`` in the saved artifact.
BROWSER_ARTIFACT_PREFETCH_HOST_KEY = "host_policy_snapshot"
BROWSER_ARTIFACT_HOST_OUTCOME_KEY = "host_outcome"

# Phase-timing key for the interstitial step. When the interstitial probe finds
# nothing, the time is detection cost, not dismissal cost; the shaper relabels
# it so the saved file is self-consistent (no "not_found yet 3873ms").
INTERSTITIAL_DISMISSAL_TIMING_KEY = "interstitial_dismissal"
INTERSTITIAL_PROBE_TIMING_KEY = "interstitial_probe"

# --- Baseline drift thresholds (Slice 5) -------------------------------------
# Phase-timing band tolerance: a run's total acquire time breaches the baseline
# band when it exceeds baseline_mean * (1 + tolerance) and the absolute slack.
BASELINE_TIMING_TOLERANCE_RATIO = 0.5
BASELINE_TIMING_ABSOLUTE_SLACK_MS = 4000
# Minimum number of prior runs before a baseline is trusted enough to flag drift.
BASELINE_MIN_SAMPLES = 3

# --- Flag severities ---------------------------------------------------------
FLAG_SEVERITY_HIGH = "high"
FLAG_SEVERITY_MEDIUM = "medium"
FLAG_SEVERITY_LOW = "low"

# --- Audit policy (Rule 1: policy literals live in config, not service code) -
# Verdicts that mean the URL was effectively blocked (no usable content owed).
AUDIT_BLOCKED_VERDICTS = frozenset({"blocked"})
# Page-metadata-ish keys that signal a fake single-row listing result.
AUDIT_METADATA_ONLY_KEYS = frozenset(
    {
        "brand",
        "canonical_url",
        "description",
        "image",
        "image_url",
        "site_name",
        "source_url",
        "title",
        "url",
    }
)
# Record keys whose presence on a detail record indicates real variant cues
# (used to flag a DOM-skip that dropped variants — INVARIANT Rule 3).
AUDIT_VARIANT_CUE_FIELDS = (
    "available_sizes",
    "option_values",
    "variant_axes",
    "size",
    "color",
)

__all__ = [
    "RUN_TRACE_ENABLED",
    "TRACE_ARTIFACT_SUBDIR",
    "AUDIT_ARTIFACT_SUBDIR",
    "RUN_TRACE_FILENAME",
    "FLAGS_FILENAME",
    "LLM_DIAGNOSIS_FILENAME",
    "RUN_TRACE_SCHEMA_VERSION",
    "TRACE_TIER_LIGHT",
    "TRACE_TIER_FULL",
    "TRACE_SUCCESS_VERDICTS",
    "HIGH_VALUE_FIELD_FLOOR",
    "DETAIL_DIAGNOSTIC_FIELDS",
    "MAX_CANDIDATE_LOSERS_PER_FIELD",
    "ACQUIRE_EVENT_NAVIGATION",
    "ACQUIRE_EVENT_HTTP_FETCH",
    "ACQUIRE_EVENT_READINESS_PROBE",
    "ACQUIRE_EVENT_INTERSTITIAL",
    "ACQUIRE_EVENT_CHALLENGE",
    "ACQUIRE_EVENT_ESCALATION",
    "ACQUIRE_EVENT_POLICY_DECISION",
    "EXTRACTION_TIER_AUTHORITATIVE",
    "EXTRACTION_TIER_STRUCTURED",
    "EXTRACTION_TIER_JS_STATE",
    "EXTRACTION_TIER_DOM",
    "DOM_SKIP_KEY_SKIPPED",
    "DOM_SKIP_KEY_CONFIDENCE",
    "DOM_SKIP_KEY_THRESHOLD",
    "DOM_SKIP_KEY_REASON",
    "DOM_SKIP_REASON_CLEARED",
    "DOM_SKIP_REASON_CONFIDENCE_BELOW_THRESHOLD",
    "DOM_SKIP_REASON_DOM_COMPLETION_REQUIRED",
    "BROWSER_ARTIFACT_DERIVABLE_FIELDS",
    "BROWSER_ARTIFACT_LISTING_ONLY_FIELDS",
    "BROWSER_ARTIFACT_DROP_WHEN_EMPTY",
    "LISTING_SURFACE_KEYWORD",
    "BROWSER_ARTIFACT_PREFETCH_HOST_KEY",
    "BROWSER_ARTIFACT_HOST_OUTCOME_KEY",
    "INTERSTITIAL_DISMISSAL_TIMING_KEY",
    "INTERSTITIAL_PROBE_TIMING_KEY",
    "BASELINE_TIMING_TOLERANCE_RATIO",
    "BASELINE_TIMING_ABSOLUTE_SLACK_MS",
    "BASELINE_MIN_SAMPLES",
    "FLAG_SEVERITY_HIGH",
    "FLAG_SEVERITY_MEDIUM",
    "FLAG_SEVERITY_LOW",
    "AUDIT_BLOCKED_VERDICTS",
    "AUDIT_METADATA_ONLY_KEYS",
    "AUDIT_VARIANT_CUE_FIELDS",
]
