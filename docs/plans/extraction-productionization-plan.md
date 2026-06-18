# Plan: Extraction Pipeline Productionization

**Created:** 2026-06-16
**Agent:** Codex
**Status:** BLOCKED
**Touches buckets:** Extraction, Pipeline provenance, Docs

## Goal

Make ecommerce detail public fields explainable from `_evidence_graph`. Any repair after candidate resolution must be recorded as a graph transform before the final public record is emitted.

## Acceptance Criteria

- [x] `CandidateSet.as_graph()` includes `field_transforms`.
- [x] Detail price/currency/variant/entity repairs record graph transforms.
- [x] `_evidence_graph` is attached only after final detail repairs.
- [x] Detail LLM missing-field fallback remains blocked for detail surfaces, including casing/spacing variants.
- [x] Variant rows expose graph-only row lineage.
- [x] Focused extraction and evidence tests pass.
- [ ] `run_test_sites_acceptance.py` completes.

## Do Not Touch

- `publish/*` and persistence semantics: do not hide extraction defects downstream.
- Public record shape: keep exported data unchanged.
- Site-specific adapters: this is shared extraction work.
- Acquisition retry/browser policy: owned by the queued acquisition plan.

## Slices

### Slice 1: Plan Activation
**Status:** DONE
**Files:** `docs/plans/extraction-productionization-plan.md`, `docs/plans/ACTIVE.md`
**What:** Make this plan active and keep existing queued work queued.
**Verify:** `git ls-files backend/app/services | rg "(__pycache__|\\.pyc$)"`

### Slice 2: Lock Current Guards
**Status:** DONE
**Files:** `backend/tests/regression/test_detail_llm_guard.py`, `backend/app/services/pipeline/direct_record_fallback.py`
**What:** Normalize surface checks before blocking detail LLM fallback.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_detail_llm_guard.py tests/regression/test_pipeline_core.py -q`

### Slice 3: Graph Transform Boundary
**Status:** DONE
**Files:** `backend/app/services/extract/contracts.py`, detail repair owners
**What:** Record repair transforms in `CandidateSet` and expose them in `_evidence_graph`.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_contracts.py tests/regression/test_evidence_graph.py -q`

### Slice 4: Materialize Once
**Status:** DONE
**Files:** `backend/app/services/extract/detail/assembly/*`
**What:** Attach `_evidence_graph` after final cleanup, not before.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_evidence_graph.py tests/unit/test_detail_quality_cleanup.py tests/unit/test_normalizers.py -q`

### Slice 5: Variant Provenance And DOM Skip Trace
**Status:** DONE
**Files:** `backend/app/services/extract/detail/assembly/tiers.py`, `backend/app/services/extract/detail/assembly/dom_completion.py`
**What:** Add graph-only variant row lineage and richer DOM skip decisions.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_variant_offer_completeness.py tests/regression/test_detail_extractor_priority_and_selector_self_heal.py -q`

## Doc Updates Required

- [x] `docs/INVARIANTS.md` — evidence graph transform contract.
- [x] `docs/CODEBASE_MAP.md` — no ownership/files changed.
- [x] `docs/BUSINESS_LOGIC.md` — no user-visible behavior changed.

## Notes

- `.gitignore` already covers cache artifacts.
- Public output shape stays unchanged.
- `2026-06-16`: focused unit/regression suites pass.
- `2026-06-16`: `pytest tests -q` passed: 1252 selected, 1048 deselected.
- `2026-06-16`: `run_extraction_smoke.py` passed 10/10; emitted Windows closed-pipe deallocator noise after exit 0.
- `2026-06-16`: `run_acquire_smoke.py commerce` passed 6/6.
- `2026-06-16`: `run_test_sites_acceptance.py` timed out twice, at 7 minutes and 15 minutes, with no useful output before timeout. Plan remains blocked on this verification.
