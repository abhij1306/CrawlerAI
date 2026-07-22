"""Stable diagnose.json schema vocabulary and payload bounds."""

from typing import Final

DIAGNOSE_SCHEMA_VERSION: Final[str] = "diagnose.v3"
DIAGNOSE_PREVIEW_LIMIT: Final[int] = 120
DIAGNOSE_FIELDS_LIMIT: Final[int] = 100
DIAGNOSE_REJECTED_PER_FIELD_LIMIT: Final[int] = 10
DIAGNOSE_VARIANT_DROPS_LIMIT: Final[int] = 200
DIAGNOSE_COLLECTORS_LIMIT: Final[int] = 50
DIAGNOSE_STAGES_LIMIT: Final[int] = 50
DIAGNOSE_CONTRACTS_LIMIT: Final[int] = 100
DIAGNOSE_FINDINGS_LIMIT: Final[int] = 100
DIAGNOSE_EVIDENCE_DISPOSITIONS_LIMIT: Final[int] = 500
DIAGNOSE_NETWORK_PROVENANCE_LIMIT: Final[int] = 10
DIAGNOSE_ESCALATION_ATTEMPT_LIMIT: Final[int] = 4

# 2.13: per-record source_trace.acquisition.browser_diagnostics is slimmed to
# the only keys consumed downstream (crawl/review/domain_recipe_support.py
# reads browser_reason + detail_expansion). Full page-level diagnostics remain
# in diagnose.json; old rows keep fat traces and readers tolerate both.
SOURCE_TRACE_BROWSER_DIAGNOSTIC_KEYS: Final[tuple[str, ...]] = (
    "browser_reason",
    "detail_expansion",
)
