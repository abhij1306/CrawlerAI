# Plan: Core Architecture Production Hardening

**Created:** 2026-06-11
**Agent:** Codex
**Status:** DONE
**Touches buckets:** Crawl/Pipeline, Acquisition + Browser Runtime, Extraction, Product Intelligence, Config, Backend architecture tests

## Goal

Make the core crawler architecture leaner and safer before production by deepening the main core modules identified in the architecture review: pipeline record extraction, fetch runtime, detail identity, Product Intelligence discovery, and config export surfaces. Done means private reach-ins and compatibility debt are reduced, duplicated logic is deleted or consolidated behind existing owners, known core-module bugs discovered during each slice are fixed upstream, core contracts stay stable, and verification passes without commits.

## Acceptance Criteria

- [x] Plan exists and `docs/plans/ACTIVE.md` points to it while active.
- [x] No implementation changes are made under Playground, monitors, product alerts, or AI Discoverability modules listed in Do Not Touch.
- [x] No public extraction contract changes: extraction order stays adapter -> structured source -> DOM, and LLM remains opt-in backfill only.
- [x] No downstream compensation is added in `publish/*`, persistence, exports, or UI.
- [x] Private service import allowlist in `backend/tests/regression/test_structure.py` shrinks for every private reach-in removed.
- [x] Any duplicate logic removed from core modules is covered by focused contract tests through public module interfaces.
- [x] Slice verification commands pass before each slice is marked DONE.
- [x] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_structure.py -q` exits 0.
- [x] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0 before plan closes.

## Do Not Touch

- `frontend/app/playground/*`, `frontend/components/playground/*`, `backend/app/services/playground_service.py`, `backend/app/api/playground.py`, `backend/app/models/playground.py`, `backend/app/schemas/playground.py` — Playground must stay separate and out of this core architecture plan.
- `backend/app/services/monitor*.py`, `backend/app/api/monitors.py`, `backend/app/models/monitor.py`, `frontend/app/monitors/*`, `frontend/components/monitors/*` — monitors are excluded by user request.
- `backend/app/services/alert_service.py`, `backend/app/services/monitor_alert*.py`, `backend/app/services/monitor_condition.py`, `backend/app/services/monitor_webhook_service.py`, `backend/app/api/alerts.py`, `backend/app/api/public_alerts.py`, `frontend/app/alerts/*` — product alerts are excluded by user request.
- `backend/app/services/ucp_audit/*`, `backend/app/services/page_audit/*`, `backend/app/api/ucp_audit.py`, `backend/app/api/page_audit.py`, `backend/app/models/ucp_audit.py`, `backend/app/models/page_audit.py`, `frontend/app/ucp-audit/*` — AI Discoverability and page audit modules are excluded by user request.
- `backend/app/services/publish/*` and `backend/app/services/pipeline/persistence.py` — downstream compensation forbidden.
- `docs/plans/agentic-browser-playground-plan.md` — queued Playground work is intentionally not part of this plan.

## Slices

### Slice 1: Pipeline Stage Public Interface

**Status:** DONE
**Files:** `backend/app/services/pipeline/extraction_loop.py`, `backend/app/services/pipeline/record_extraction_stage.py`, `backend/app/services/pipeline/retry/stage.py`, `backend/tests/regression/test_pipeline_core.py`, `backend/tests/regression/test_structure.py`
**What:** Replace private imports from `record_extraction_stage` with public stage functions. Promote any real caller surface needed by `extraction_loop` and retry stages. Delete now-redundant private aliases where possible. Shrink the private service import allowlist for `pipeline/extraction_loop.py -> .record_extraction_stage:*`. Fix any core pipeline bug found while moving callers, but only at the upstream owner.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_pipeline_core.py tests/unit/test_content_article_forum_surfaces.py tests/regression/test_structure.py -q`

### Slice 2: Fetch Runtime Internal Decomposition

**Status:** DONE
**Files:** `backend/app/services/fetch/fetch_context.py`, new internal files under `backend/app/services/fetch/` if needed, `backend/tests/component/test_crawl_fetch_runtime.py`, `backend/tests/unit/test_block_detection.py`, `backend/tests/regression/test_structure.py`
**What:** Keep `fetch_page` and `reset_fetch_runtime_state` as the external interface. Move HTTP attempt-chain implementation and browser attempt-chain implementation into internal fetch modules only if the deletion test says the split improves locality. Remove compatibility shims such as host-policy signature probing only if current call sites and tests prove they are no longer needed. Preserve explicit user controls for `fetch_mode`, proxy settings, browser engine, traversal, and locality.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/component/test_crawl_fetch_runtime.py tests/unit/test_block_detection.py tests/regression/test_structure.py -q`

### Slice 3: Detail Identity Package Deepening

**Status:** DONE
**Files:** `backend/app/services/extract/detail/identity/core.py`, `backend/app/services/extract/detail/identity/__init__.py`, new focused files under `backend/app/services/extract/detail/identity/` if needed, `backend/tests/regression/test_listing_identity_regressions.py`, `backend/tests/regression/test_detail_extractor_structured_sources.py`, `backend/tests/regression/test_crawl_engine.py`, `backend/tests/regression/test_structure.py`
**What:** Split detail identity by domain concept while preserving the package facade: listing structural URL checks, detail URL identity, record identity, model-code comparison, redirect mismatch, and DOM pruning. Promote model-number comparison through a public interface only if tests need that behavior directly. Move tests away from private identity imports where possible. Fix confirmed false-positive or false-negative identity bugs upstream in this package.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_listing_identity_regressions.py tests/regression/test_detail_extractor_structured_sources.py tests/regression/test_crawl_engine.py tests/regression/test_structure.py -q`

### Slice 4: Product Intelligence Discovery Seams

**Status:** DONE
**Files:** `backend/app/services/product_intelligence/discovery.py`, new focused files under `backend/app/services/product_intelligence/` if needed, `backend/app/services/product_intelligence/service.py`, `backend/tests/component/test_product_intelligence.py`, `backend/tests/regression/test_structure.py`
**What:** Keep Product Intelligence separate from Playground, monitors, alerts, and AI Discoverability. Deepen the discovery module by separating provider adapters, query construction, candidate admission, and ranking behind public discovery behavior. Remove `service.py` private import of `_looks_like_product_detail_url` by promoting a real public predicate or moving the caller behavior behind discovery. Move tests away from private `_candidate_dedupe_key` if a public contract can cover it. Fix known discovery bugs only in discovery/admission/ranking owners.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/component/test_product_intelligence.py tests/regression/test_structure.py -q`

### Slice 5: Core Config Export Surface Cleanup

**Status:** DONE
**Files:** `backend/app/services/config/extraction_rules/__init__.py`, `backend/app/services/config/extraction_rules/_*.py`, `backend/app/services/config/field_mappings.py`, `backend/app/services/config/selectors.py`, `backend/tests/regression/test_config_imports.py`, `backend/tests/regression/test_structure.py`
**What:** Reduce import-time export magic and wildcard compatibility where it is shallow or hides config ownership. Keep config values in `app/services/config/*`. Do not create new config sources. Tighten structure tests so config export cleanup cannot drift back. No behavior changes unless a duplicated or stale config source is proven wrong.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_config_imports.py tests/regression/test_structure.py -q`

### Slice 6: Final Ratchets and Full Verification

**Status:** DONE
**Files:** `backend/tests/regression/test_structure.py`, `docs/CODEBASE_MAP.md`, `docs/ENGINEERING_STRATEGY.md`, touched owner docs only if ownership or anti-patterns changed
**What:** Ratchet reduced LOC budgets, private-import allowlists, config-magic checks, and deleted-shim checks. Update ownership docs only for stable new files or moved owners. Run full backend verification. Do not commit.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — updated for `extract/detail/identity/model_codes.py`.
- [x] `docs/ENGINEERING_STRATEGY.md` — no new recurring anti-pattern; no update required.
- [x] `docs/INVARIANTS.md` — no core runtime contract change; no update required.
- [x] `docs/plans/ACTIVE.md` — marked no active plan after completion.

## Notes

- Prior active plan `docs/plans/loc-complexity-reduction-plan.md` is BLOCKED only on external extraction smoke DNS/browser failure. This new plan is user-requested and replaces the active pointer.
- Execution is end-to-end but no commit will be made. User wants code review before committing.
- User confirmed execution by continuing the active goal; no commit made.
- Core module focus only: pipeline, fetch/acquisition runtime, extraction identity, Product Intelligence discovery, config, and structure tests.
- Slice 1 started 2026-06-11. Replacing private `record_extraction_stage` imports with public stage names and shrinking the structure allowlist.
- Slice 1 done 2026-06-11. Promoted `best_adapter_result`, `extract_records_for_acquisition`, and `update_acquisition_contract_memory` as the public `record_extraction_stage` interface; changed `extraction_loop` and the content-detail test to use public names; removed three private import allowlist entries. Verify passed: planned command selected 18 unit tests and passed; explicit regression/structure command `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_pipeline_core.py tests/regression/test_structure.py -m regression -q` passed 88 tests.
- Slice 2 started 2026-06-11. Inspecting `fetch_context.py` for HTTP/browser attempt-chain locality before editing.
- Slice 2 done 2026-06-11. Deletion test did not justify moving HTTP/browser attempts to separate files because attempt chains share host memory, escalation, diagnostics, and deadline state. Instead, promoted the real attempt seams as public `run_browser_attempts` and `try_browser_http_handoff`, moved tests off private patch/call points, and deleted stale `_load_host_protection_policy_compat` signature probing now that `load_host_protection_policy` supports `ttl_seconds`. Verify passed: planned command selected 100 component/unit tests and passed; explicit structure command `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_structure.py -m regression -q` passed 29 tests.
- Slice 3 started 2026-06-11. Inspecting `extract/detail/identity/core.py` call sites before splitting identity concepts.
- Slice 3 done 2026-06-11. Split model-number/code compatibility into `extract/detail/identity/model_codes.py`, exposed `detail_model_number_sets_compatible` through the identity package, moved the listing identity regression test off a private core import, removed the private test allowlist entry, and updated `docs/CODEBASE_MAP.md`. Also fixed one stale fetch-runtime test double that still lacked the public `ttl_seconds` loader argument after Slice 2. Verify passed: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_listing_identity_regressions.py tests/regression/test_detail_extractor_structured_sources.py tests/regression/test_crawl_engine.py tests/regression/test_structure.py -m regression -q` passed 452 tests, 16 skipped.
- Slice 4 started 2026-06-11. Inspecting Product Intelligence discovery private imports and candidate URL predicate ownership.
- Slice 4 done 2026-06-11. Split candidate URL admission, URL cleanup, compare keys, and dedupe keys into `product_intelligence/candidate_urls.py`; changed discovery, service, and tests to use public names; removed Product Intelligence private service/test import allowlist entries; updated `docs/CODEBASE_MAP.md` product intelligence owner text. Verify passed: planned command selected 103 Product Intelligence component tests and passed; explicit structure command `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_structure.py -m regression -q` passed 29 tests.
- Slice 5 started 2026-06-11. Inspecting config wildcard/export surface and structure ratchets before edits.
- Slice 5 done 2026-06-11. Removed `globals()`-derived `__all__` from `_images.py`, `_jobs.py`, and `_detail_sections.py` by composing exports from upstream config owner `__all__` plus explicit local export tuples. Shrunk the structure-test allowlist for global export modules to only the larger remaining modules. Verify passed: initial planned command selected no tests because regression markers are deselected by default; explicit command `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_config_imports.py tests/regression/test_structure.py -m regression -q` passed 69 tests.
- Slice 6 started 2026-06-11. Auditing scope exclusions and running final ratchets/full verification.
- Slice 6 done 2026-06-11. Scope audit found no touched Playground, monitor, product-alert, AI Discoverability, publish, persistence, or export/UI implementation files. Existing unrelated dirty frontend layout files remain untouched. Structure gate passed: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_structure.py -m regression -q` passed 29 tests. Full backend verification passed: `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` passed 1364 tests, 1018 deselected.
