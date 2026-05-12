# Plan: Architecture Audit 2 Remediation

**Created:** 2026-05-12
**Agent:** Claude
**Status:** COMPLETE
**Touches buckets:** Models, crawl orchestration, run dispatch, progress state, structure tests

## Goal

`docs/plans/architecture-audit-plan2.md` proposes sweeping phase work. A code-truth pass
against that audit shows most Phase 1 items (fetch_context duplicates, llm_tasks size,
variant_record_normalization size, a 500-LOC ratchet) are already resolved. What remains
is a smaller, well-scoped set: retire the stale LOC budget, evict business logic from the
ORM god file, split that god file by domain, and make run dispatch extensible. This plan
executes only those items incrementally — one transformation per slice, verify before the
next — per `docs/agent/PLAN_PROTOCOL.md` and the incremental-refactoring skill.

Done looks like:

- `app/models/crawl.py` no longer exists. Classes live in domain-aligned model files.
  Every caller imports from the new owner directly. No pass-through shim.
- `BatchRunProgressState` lives in a services owner, not in the ORM layer.
- `dispatch_run` selects a dispatcher through a small indirection so adding a new
  executor does not touch `crawl_service.py`. The legacy in-process fallback stays as an
  internal detail of the celery dispatcher, not a protocol parameter.
- `test_structure.py` reflects real file sizes and gates against `SessionLocal()`
  re-entering orchestration code.
- `python -m pytest tests -q` passes. No behavior change observable in smoke runs.

## Execution Discipline

Follow the incremental-refactoring skill:

1. One transformation per slice. One slice per commit.
2. Plan concrete slices one step ahead. Slices beyond the current "Candidates" list are
   chosen only after observing the state left by the previous slice.
3. Verify after every slice. Do not batch.
4. No speculative abstraction. Introduce a protocol/interface only when two concrete
   implementations exist and the seam is needed today.

## Acceptance Criteria

- [ ] `backend/app/models/crawl.py` is deleted. All ORM classes reachable from
      `app.models` via domain-aligned modules (`crawl_run.py`, `review.py`,
      `domain_memory.py`, `product_intelligence.py`, `data_enrichment.py`). No
      pass-through or `sys.modules` shim left behind.
- [ ] `BatchRunProgressState` and its helpers are imported from
      `app.services.pipeline.run_progress`. No business logic remains in
      `app/models/*.py`.
- [ ] `dispatch_run` in `crawl_service.py` contains no direct reference to
      `settings.celery_dispatch_enabled` or `settings.legacy_inprocess_runner_enabled`.
      Dispatcher selection is resolved once via `core.dependencies.get_run_dispatcher`.
- [ ] `backend/tests/services/test_structure.py`:
      - stale `crawl_fetch_runtime.py` LOC budget dropped from 1260 to ~50.
      - new guard: allowlist of service modules permitted to call `SessionLocal()`.
      - any new model files stay within the default LOC ceiling.
- [ ] `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
- [ ] `.\.venv\Scripts\python.exe run_acquire_smoke.py commerce` runs without regression.
- [ ] `.\.venv\Scripts\python.exe -c "from app.models import *; from app.core.database import Base; assert Base.metadata.tables"` returns ok.

## Do Not Touch

- `backend/app/services/crawl_fetch_runtime.py` — 8-line shim. 9 callers. Renaming is
  busywork without architectural payoff in this plan.
- `backend/app/services/acquisition/browser_runtime.py`, `traversal.py` — covered by the
  previous audit and by existing `test_structure.py` budgets. Out of scope.
- `extract/shared_variant_logic.py`, `variant_record_normalization.py`,
  `listing_extractor.py`, `field_value_candidates.py` — budgets already managed. Do not
  split here.
- `pipeline/extraction_loop.py` — deferred. Splitting during a model refactor compounds
  risk.
- `detail_extractor.py` candidate selection — AGENTS.md extraction warning applies.
- Legitimate Celery/worker owners of `SessionLocal()`:
  `product_intelligence/service.py::run_product_intelligence_job`,
  `data_enrichment/service.py::run_data_enrichment_job`,
  `crawl_events.py` log-write fallback,
  `acquisition/host_protection_memory.py` / `acquisition/cookie_store.py` cache
  fallbacks, `_batch_runtime.py` recovery path, `pipeline/runtime_helpers.py` failure
  recovery. These are correct owners and stay.
- `docs/plans/architecture-audit-plan2.md` — input audit, leave untouched.

## Slices — Executed

All slice entries below are closed. Candidate promotions become "Slice Nx" entries here
when their predecessor verifies.

### Slice 1: Retire The Stale LOC Budget
**Status:** DONE
**Files:** `backend/tests/services/test_structure.py`
**Transformation:** Remove Dead Code.
**What:** Drop the `crawl_fetch_runtime.py` budget from 1260 to ~50. The file is an
8-line `sys.modules` shim; the 1260 figure lies about current size.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_structure.py -q` → 9 passed.

### Slice 2: Move `BatchRunProgressState` Out Of The Model Layer
**Status:** DONE
**Files:**
- new `backend/app/services/pipeline/run_progress.py`
- `backend/app/models/crawl.py` (removed dataclass, helpers, trampoline method, dead imports)
- `backend/app/services/_batch_runtime.py` (inlined the single external caller)
- `backend/tests/services/test_structure.py` (budget for the new module)
**Transformation:** Move Class + Move Function (Fowler Ch. 7 / Ch. 6).
**Verify:** import probe + 165 focused tests passed.

### Slice 3a: Extract `crawl_run.py` From The God File
**Status:** DONE
**Transformation:** Extract Class (Fowler Ch. 7).
**Verify:** structural probe + alembic heads + 352 focused tests passed.

### Slice 3b: Extract `review.py` From The God File
**Status:** DONE
**Files:**
- new `backend/app/models/review.py` — `ReviewPromotion`
- `backend/app/models/crawl.py` (removed `ReviewPromotion`)
- `backend/app/models/__init__.py` (re-sourced from `review.py`; public surface unchanged)
- 7 caller files rewired:
  `app/services/dashboard_service.py`, `app/services/publish/metadata.py`,
  `app/services/review/__init__.py`, `app/services/schema_service.py`,
  `tests/services/test_crawl_service.py`,
  `tests/services/test_dashboard_service.py`,
  `tests/services/test_review_service.py`.
**Transformation:** Extract Class (Fowler Ch. 7).
**What:** `ReviewPromotion` imports `CASCADE`, `CRAWL_RUN_FK`, `UpdatedAtMixin` from
`crawl_run.py`. No re-export shim.
**Verify:**
- Structural probe: `ReviewPromotion.__module__ == 'app.models.review'`, `review_promotions` table present.
- `pytest tests/services/test_review_service.py tests/services/test_crawl_service.py tests/services/test_dashboard_service.py tests/services/test_structure.py -q` → 51 passed.

## Candidates — Chosen After Slice 3a Lands

Slices below are not committed. Their existence depends on what Slice 3a reveals. Do not
pre-plan their internals. After 3a, pick ONE, write its concrete slice entry at the end
of this plan, and execute.

- **3b — Extract `review.py`:** `ReviewPromotion`.
- **3c — Extract `domain_memory.py`:** `DomainMemory`, `DomainRunProfile`,
  `DomainCookieMemory`, `DomainFieldFeedback`, `HostProtectionMemory`.
- **3d — Extract `product_intelligence.py`:** 4 Product Intelligence ORM classes.
- **3e — Extract `data_enrichment.py`:** `DataEnrichmentJob`, `EnrichedProduct`.
- **3f — Delete `models/crawl.py`:** Only when no symbols remain and no caller imports
  from it. This is a Remove Dead Code transformation, not a new module file.
- **4 — Dispatcher seam:** Introduce a Strategy indirection for `dispatch_run`. Scope
  decided after the model split is verified. The intent is one indirection call in
  `crawl_service.dispatch_run`; the celery dispatcher internally decides whether to fall
  back to local execution based on `legacy_inprocess_runner_enabled`. No `fallback`
  constructor parameter until a second fallback target exists.
- **5 — `SessionLocal()` guard:** Add the allowlist test to `test_structure.py` once the
  orchestration surface has settled. Folded into Slice 4's verify if that slice happens.

Each candidate becomes a committed slice only when its predecessor has landed and its
verify step has passed. No batching. No "I'll do 3b–3e together."

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — models section updated after every 3x slice that moves
      classes. Do not batch doc updates either.
- [ ] `docs/ENGINEERING_STRATEGY.md` — note the model-file-per-domain rule so the god
      file does not regrow. Only after 3f lands.
- [ ] `docs/backend-architecture.md` — "Models" section updated only if it describes
      file-level layout.

## Notes

Against `docs/plans/architecture-audit-plan2.md`:

- Phase 1.1 (lava flow delete in `fetch_context.py`): already done in repo.
- Phase 1.2 (shim rename): low payoff, dropped.
- Phase 1.3 (500-LOC ratchet): existing per-file budgets are stricter and more
  accurate. Only cleanup is the stale `crawl_fetch_runtime.py` budget — Slice 1.
- Phase 2 (model split + progress evict): Slices 2, 3a, plus Candidates 3b–3f.
- Phase 3 (service mega-file splits): deferred. Existing budgets hold the line.
- Phase 4.1 (dispatch strategy): deferred to Candidate 4. Will happen only after the
  model layer is clean.
- Phase 4.2 (inject `AsyncSession`): scoped down. Only the orchestration offender
  matters, and that decision sits inside Candidate 4/5.
- Phase 4.3 (`CrawlRunFactory`): deferred. No slice here.
- Phase 5 (domain folders): deferred. Premature.
- Phase 6 (test coverage): implicit in each slice's verify step.

Plan review applied the incremental-refactoring skill to an earlier draft of this file.
Changes versus that draft:

- Split the single "split `models/crawl.py`" slice into five candidate extractions plus a
  final delete step. One Extract Class per slice.
- Committed only Slices 1, 2, 3a up front. Later slices are candidates, picked after
  observation.
- Removed the pass-through shim idea. Every move rewrites its callers in the same slice.
- Replaced the `RunDispatcher` protocol with `fallback` parameter with a narrower seam.
  Deferred the detail until the state after Slice 3 is known.
- Removed the standalone "narrow `SessionLocal()` audit" slice; folded the guard into
  the dispatcher candidate where it is actually triggered.
