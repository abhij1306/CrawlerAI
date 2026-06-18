"""Audit rule table: symptom -> violated INVARIANT rule -> owning file.

Config-only (INVARIANT Rule 1). The audit engine in
``app/services/observability/run_audit.py`` imports these and must not inline
rule strings, owner paths, or severities.

Each rule maps a deterministic symptom (computed from the RunTrace, browser.json,
and persisted record) to:
- ``code``: stable flag id
- ``invariant``: the INVARIANT.md rule it violates (for the human/agent reader)
- ``owner``: the owning file or directory from CODEBASE_MAP (where the fix belongs)
- ``severity``: high | medium | low
- ``symptom``: short human description
"""

from __future__ import annotations

from app.services.config.observability import (
    FLAG_SEVERITY_HIGH,
    FLAG_SEVERITY_LOW,
    FLAG_SEVERITY_MEDIUM,
)

# Stable flag codes (referenced by tests and the audit engine).
FLAG_DOM_SKIPPED_WITH_VARIANT_CUES = "dom_skipped_with_variant_cues"
FLAG_USABLE_CONTENT_BUT_BLOCKED = "usable_content_but_blocked"
FLAG_LISTING_SINGLE_METADATA_RECORD = "listing_single_metadata_record"
FLAG_HIGH_VALUE_FIELD_MISSING = "high_value_field_missing"
FLAG_DETAIL_ON_LISTING_SEED = "detail_on_listing_seed"
FLAG_DETAIL_IDENTITY_REJECTED = "detail_identity_rejected"
FLAG_ACQUISITION_CHALLENGE_BLOCKED = "acquisition_challenge_blocked"
FLAG_VARIANT_CANDIDATE_DROPPED = "variant_candidate_dropped"
FLAG_BASELINE_FIELD_REGRESSION = "baseline_field_regression"
FLAG_BASELINE_ENGINE_CHANGED = "baseline_engine_changed"
FLAG_BASELINE_TIER_REGRESSION = "baseline_tier_regression"
FLAG_BASELINE_TIMING_BREACH = "baseline_timing_breach"
FLAG_BASELINE_VERDICT_REGRESSION = "baseline_verdict_regression"

# Owning files (from docs/CODEBASE_MAP.md).
OWNER_DETAIL_TIERS = "backend/app/services/extract/detail/assembly/tiers.py"
OWNER_BLOCK_CLASSIFY = "backend/app/services/acquisition/browser_result_builder.py"
OWNER_LISTING_EXTRACTOR = "backend/app/services/listing_extractor.py"
OWNER_DETAIL_EXTRACTOR = "backend/app/services/detail_extractor.py"
OWNER_RECORD_ASSEMBLY = (
    "backend/app/services/extract/detail/assembly/record_assembly.py"
)
OWNER_CRAWL_ENGINE = "backend/app/services/crawl_engine.py"
OWNER_DOMAIN_PROFILE = "backend/app/services/crawl/profile"

# Rule metadata keyed by flag code.
AUDIT_RULES: dict[str, dict[str, str]] = {
    FLAG_DOM_SKIPPED_WITH_VARIANT_CUES: {
        "invariant": "Rule 3 (Extraction — DOM tier skipped before variant cues consumed)",
        "owner": OWNER_DETAIL_TIERS,
        "severity": FLAG_SEVERITY_HIGH,
        "symptom": "DOM tier skipped while variants are missing and variant cues exist",
    },
    FLAG_USABLE_CONTENT_BUT_BLOCKED: {
        "invariant": "Rule 6 (Acquisition — usable_content must not be marked blocked on provider noise)",
        "owner": OWNER_BLOCK_CLASSIFY,
        "severity": FLAG_SEVERITY_HIGH,
        "symptom": "browser_outcome=usable_content but run verdict is blocked",
    },
    FLAG_LISTING_SINGLE_METADATA_RECORD: {
        "invariant": "Rule 7 (Listing/Detail separation — listing produced a single page-metadata row)",
        "owner": OWNER_LISTING_EXTRACTOR,
        "severity": FLAG_SEVERITY_HIGH,
        "symptom": "listing run produced exactly one record that looks like page metadata",
    },
    FLAG_HIGH_VALUE_FIELD_MISSING: {
        "invariant": "Rule 3 (Extraction — high-value field missing without repair/diagnostic)",
        "owner": OWNER_DETAIL_EXTRACTOR,
        "severity": FLAG_SEVERITY_MEDIUM,
        "symptom": "requested/default high-value field missing from the persisted record",
    },
    FLAG_DETAIL_ON_LISTING_SEED: {
        "invariant": "Rule 7 (Detail extraction rejected a listing/category seed)",
        "owner": OWNER_RECORD_ASSEMBLY,
        "severity": FLAG_SEVERITY_MEDIUM,
        "symptom": "detail run rejected the URL as a listing/category seed",
    },
    FLAG_DETAIL_IDENTITY_REJECTED: {
        "invariant": "Rule 3 (Extraction — detail identity guard rejected the extracted record)",
        "owner": OWNER_RECORD_ASSEMBLY,
        "severity": FLAG_SEVERITY_HIGH,
        "symptom": "detail extraction rejected a candidate as a different product",
    },
    FLAG_ACQUISITION_CHALLENGE_BLOCKED: {
        "invariant": "Rule 6 (Acquisition — target remained behind bot protection/challenge shell)",
        "owner": OWNER_BLOCK_CLASSIFY,
        "severity": FLAG_SEVERITY_HIGH,
        "symptom": "acquisition produced only a challenge or low-content shell",
    },
    FLAG_VARIANT_CANDIDATE_DROPPED: {
        "invariant": "Rule 3 (Extraction — variant candidate existed but did not survive public output)",
        "owner": OWNER_RECORD_ASSEMBLY,
        "severity": FLAG_SEVERITY_HIGH,
        "symptom": "variants had an extraction source but were missing from final output",
    },
    # Baseline-drift flags (Slice 5).
    FLAG_BASELINE_FIELD_REGRESSION: {
        "invariant": "Rule 9 (Domain memory — field that normally extracts for this domain/surface is now missing)",
        "owner": OWNER_DETAIL_EXTRACTOR,
        "severity": FLAG_SEVERITY_MEDIUM,
        "symptom": "high-value field present in baseline is missing this run",
    },
    FLAG_BASELINE_ENGINE_CHANGED: {
        "invariant": "Rule 9 (Domain memory — engine drifted from learned acquisition contract)",
        "owner": OWNER_DOMAIN_PROFILE,
        "severity": FLAG_SEVERITY_LOW,
        "symptom": "acquisition engine differs from the learned baseline engine",
    },
    FLAG_BASELINE_TIER_REGRESSION: {
        "invariant": "Rule 3 (Extraction — tier that normally runs was skipped this run)",
        "owner": OWNER_DETAIL_TIERS,
        "severity": FLAG_SEVERITY_MEDIUM,
        "symptom": "extraction tier present in baseline did not run this run",
    },
    FLAG_BASELINE_TIMING_BREACH: {
        "invariant": "Rule 6 (Acquisition — acquire time far exceeds learned baseline band)",
        "owner": OWNER_BLOCK_CLASSIFY,
        "severity": FLAG_SEVERITY_LOW,
        "symptom": "total acquire time breached the learned timing band",
    },
    FLAG_BASELINE_VERDICT_REGRESSION: {
        "invariant": "Rule 14 (verdict regressed from the learned baseline verdict)",
        "owner": OWNER_CRAWL_ENGINE,
        "severity": FLAG_SEVERITY_MEDIUM,
        "symptom": "run verdict regressed from the baseline verdict for this domain/surface",
    },
}

# Audit artifact schema version.
AUDIT_SCHEMA_VERSION = 1

__all__ = [
    "AUDIT_RULES",
    "AUDIT_SCHEMA_VERSION",
    "FLAG_DOM_SKIPPED_WITH_VARIANT_CUES",
    "FLAG_USABLE_CONTENT_BUT_BLOCKED",
    "FLAG_LISTING_SINGLE_METADATA_RECORD",
    "FLAG_HIGH_VALUE_FIELD_MISSING",
    "FLAG_DETAIL_ON_LISTING_SEED",
    "FLAG_DETAIL_IDENTITY_REJECTED",
    "FLAG_ACQUISITION_CHALLENGE_BLOCKED",
    "FLAG_VARIANT_CANDIDATE_DROPPED",
    "FLAG_BASELINE_FIELD_REGRESSION",
    "FLAG_BASELINE_ENGINE_CHANGED",
    "FLAG_BASELINE_TIER_REGRESSION",
    "FLAG_BASELINE_TIMING_BREACH",
    "FLAG_BASELINE_VERDICT_REGRESSION",
]
