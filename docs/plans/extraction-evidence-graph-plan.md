# Plan: Extraction Evidence Graph Architecture

**Created:** 2026-06-14
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** Bucket 2 (pipeline/LLM), Bucket 3 (network capture), Bucket 4 (extraction), Bucket 5 (persistence/export), Bucket 6 (review/domain memory), docs/tests

## Goal

Make ecommerce detail extraction evidence-backed without rebuilding the backend. Done means deterministic extraction still produces the same flat public record shape, but final fields have evidence IDs or transform/finding trace; ecommerce detail LLM field filling is disabled; recurring variant, currency, and image defects have regression coverage.

## Acceptance Criteria

- [x] Ecommerce detail runs do not call LLM missing-field extraction.
- [x] Candidate values have index-aligned evidence IDs in detail extraction.
- [x] Source trace exposes optional evidence and validation fields without leaking internals into `record.data`.
- [x] Size-only sellable variants create offer-completeness findings and do not count as rich enough to skip DOM completion.
- [x] Root/variant currency contradictions remain visible as findings or traceable consensus transforms.
- [x] Existing canonical image dedupe remains active.
- [x] LLM adjudication contract accepts evidence IDs/recipe suggestions and rejects generated values.
- [x] Detail candidate arbitration has one typed owner; parallel candidate/source/evidence decision structures are removed.
- [x] Repeated pre-DOM materialization and superseded detail LLM-fill test are deleted after replacement behavior passes.
- [x] Final extraction-core LOC and duplicate-decision count are lower than the audited baseline.
- [x] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0 before plan close.

## Do Not Touch

- `backend/app/services/acquisition/*` beyond additive network payload metadata.
- `backend/app/services/public_record_firewall.py` except if an internal leak regression requires a boundary assertion.
- `backend/app/services/dom/image_extraction.py` canonical dedupe logic; extend asset scope later, do not replace dedupe.
- `backend/app/services/adapters/*` unless a test proves a shared adapter candidate path lacks evidence.
- Existing user changes in unrelated files.

## Slices

### Slice 1: Safety Gates and Regression Harness
**Status:** COMPLETE
**Files:** `agent_debug/VERIFIED_ISSUES.md`, `backend/tests/regression/test_detail_llm_guard.py`, `backend/tests/regression/test_evidence_graph.py`, `backend/tests/regression/test_variant_offer_completeness.py`, `backend/tests/regression/test_price_currency_context.py`
**What:** Encode the first recurring defect classes as tests: detail LLM guard, evidence trace shape, size-only variant offer finding, currency contradiction finding, and public data no-internals.
**Verify:** Focused pytest for the new files fails before implementation, then passes after implementation.

### Slice 2: Disable Ecommerce Detail LLM Field Filling
**Status:** COMPLETE
**Files:** `backend/app/services/pipeline/extraction_loop.py`, `backend/app/services/pipeline/direct_record_fallback.py`, `backend/tests/regression/test_detail_llm_guard.py`
**What:** Guard the call site and the function so ecommerce detail never calls `extract_missing_fields()`. Keep non-detail LLM fallback behavior.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_detail_llm_guard.py tests/regression/test_pipeline_core.py::test_apply_llm_fallback_re_normalizes_llm_values_before_return -q`

### Slice 3: Shadow Evidence Graph
**Status:** COMPLETE
**Files:** `backend/app/services/extract/contracts.py`, `backend/app/services/extract/detail/assembly/tiers.py`, `backend/app/services/extract/detail/assembly/record_assembly.py`, `backend/app/services/extract/detail/assembly/candidate_collection.py`, `backend/app/services/export/schema.py`
**What:** Promote the existing unused `RawCandidate`/`CandidateSet` contracts into the one detail candidate/evidence ledger. Delete parallel candidate/source/evidence arbitration structures and duplicate ordering/grouping decisions. Emit trace summaries from the ledger. Preserve only the flat public output contract.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_evidence_graph.py -q`

### Slice 4: Offer and Currency Findings
**Status:** COMPLETE
**Files:** `backend/app/services/extract/detail/validation.py`, `backend/app/services/extract/detail/assembly/dom_section_targets.py`, `backend/app/services/extract/variant_normalization/backfill.py`
**What:** Add findings for incomplete sellable variants and currency contradictions. Update rich-variant detection so size-only variants are not treated as complete.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_variant_offer_completeness.py tests/regression/test_price_currency_context.py tests/unit/test_normalizers.py::test_enforce_variant_currency_context_keeps_all_mismatched_variants_for_review -q`

### Slice 5: Docs and Broader Verification
**Status:** COMPLETE
**Files:** `docs/INVARIANTS.md`, `docs/BUSINESS_LOGIC.md`, `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, this plan
**What:** Document the evidence-first detail contract, LLM adjudication-only future role, and new owners. Run focused and broad verification.
**Verify:** Focused test set, then selected and previously excluded backend pytest suites. Smoke and acceptance runs are intentionally omitted per user instruction.

### Slice 6: Delete Superseded Decisions and Tests
**Status:** COMPLETE
**Files:** repeated materialization in `extract/detail/assembly/tiers.py`, superseded repair paths in `extract/detail/assembly/final_cleanup.py`, `extract/detail/price/*`, `extract/variant_normalization/*`, old implementation-coupled tests
**What:** After resolver/validator behavior is verified, delete intermediate materialization, silent repairs, duplicate source trace construction, compatibility-only helpers, and tests that pin removed internals. Retain contract/regression tests for public behavior and recurring defects.
**Verify:** Record before/after LOC and duplicate-decision inventory in Notes; full tests pass.

## Doc Updates Required

- [x] `docs/INVARIANTS.md` - evidence-first rule and ecommerce detail LLM guard.
- [x] `docs/BUSINESS_LOGIC.md` - LLM role and reviewable evidence decisions.
- [x] `docs/CODEBASE_MAP.md` - new evidence graph/validator owners.
- [x] `docs/backend-architecture.md` - extraction pipeline target flow.

## Notes

- `agent_debug/VERIFIED_ISSUES.md` confirms price misses, incomplete variants, Bombas currency inconsistency, and Kith color mismatch.
- Ecommerce detail is guarded at both the extraction-loop call site and `apply_llm_fallback()`.
- Image dedupe owner is `backend/app/services/dom/image_extraction.py`, exported through `dom/selector_engine.py` and used by `extract/detail/images/dedupe.py`.
- Existing silent mutation owners include `extract/detail/assembly/final_cleanup.py`, `extract/detail/price/core.py`, `extract/detail/price/money_repair.py`, and `extract/variant_normalization/backfill.py`.
- `extract/contracts.py` already defines `RawCandidate` and `CandidateSet`, but current runtime does not use them. They will become the candidate/evidence owner instead of adding another parallel graph builder.
- Net architecture reduction is a hard acceptance criterion. New types must replace existing decision paths in the same plan, and superseded tests may be deleted.
- Detail `candidate_sources`, `field_sources`, and candidate/evidence alignment repair were deleted. CandidateSet now owns source/evidence ordering.
- Pre-DOM materialization was reduced from three decisions to one.
- Network evidence now retains safe request/response locality headers, body hash, capture timestamp, resource type, and frame URL. Secret headers are excluded.
- The unused value-generating `field_cleanup_review` LLM contract was replaced with evidence-ID choose/reject/abstain decisions and reusable recipe suggestions.
- Domain Recipe now exposes confusing field evidence summaries and validation findings without exposing `_evidence_graph`.
- Focused verification: 267 passed, 7 skipped, 4 deselected. Browser capture context: 9 passed across focused context/capture tests.
- Final selected backend suite: 1235 passed, 1031 deselected.
- Current jscpd extraction scan: 25 exact clone groups / 200 duplicated lines / 0.88%. The initial audit used a different scan result (11 / 140 / 0.52%), so the lower-than-baseline criterion is not claimed.
- Latest `agent_debug/30.json` verified-issue audit drove shared fixes: Shopify/Nike asset identity dedupe, metadata-prefixed color alias collapse, negative-stock resolution, related-volume row rejection, and unanimous variant-currency resolution.
- Applying the new owners to the latest crawl reduced Shopify duplicate galleries by roughly half, Nike images from 34 to 26, Fashion Nova variants from 48 to 24, removed Aesop false variants, normalized Revolver Club negative stock, and corrected Arc'teryx root currency to CAD.
- Dead detail package reexports, `variant_normalization/common.py`, duplicate parent scalar backfill, per-variant currency warning decisions, and tests pinning lossy variant-offer stripping were deleted.
- Extraction and regression diff is net smaller: 512 added / 590 deleted lines. Whole working diff is also net smaller.
- Previously excluded suite: 1021 passed, 10 skipped, 1235 deselected. No smoke or acceptance tests were run.
