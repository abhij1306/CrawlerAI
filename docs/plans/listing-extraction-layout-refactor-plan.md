# Plan: Verified Architecture Refactor - Listing + LLM First

**Created:** 2026-05-17
**Updated:** 2026-05-17
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** Bucket 2 Crawl Ingestion + Orchestration, Bucket 4 Extraction, Bucket 7 LLM Admin + Runtime, docs

## Goal

Turn the root-level architecture audit into executable, verified refactor work. Execute the first phase only after each slice passes: listing extraction layout cleanup plus LLM package consolidation. Keep later phases as confirmed backlog, not active code work, until the current phase passes its verify gates.

## Audit Verification Scope

- Verified `backend/app/services` has 56 root `.py` files and 17 real subdirectories, excluding `__pycache__`.
- Verified 12 root-level `llm_*.py` files and active imports from API, pipeline, enrichment, selectors, product intelligence, and tests.
- Verified 7 root-level `crawl_*.py` files plus root `_batch_runtime.py`; current owners are Bucket 2.
- Verified `listing_extractor.py`, `extraction_runtime.py`, `field_value_candidates.py`, and `domain_run_profile_service.py` are the largest service files.
- Verified `js_state/` has real modules and `js_state_helpers.py` is still root-level.
- Verified `extraction_context.py` and `extraction_html_helpers.py` are root-level, but `extraction_html_helpers.py` is shared by adapters, DOM, JS-state, LLM prompt rendering, selectors, and shared coercion. Do not blindly move it into `extract/`.
- Rejected the audit claim that `robots_policy.py`, `platform_policy.py`, and `public_record_firewall.py` are one policy layer. Code ownership differs: robots is crawlability, platform is platform runtime/readiness, firewall is public record shaping.
- Rejected the target of zero root service files for now. Current architecture map still assigns root owners. Reduce root sprawl by confirmed owners first.

## Acceptance Criteria

- [x] Audit claims used by this plan are backed by file inventory, symbol grep, or import grep.
- [x] `backend/app/services/listing_extractor.py` keeps listing orchestration and imports cohesive helpers from `backend/app/services/extract/`.
- [x] Structured listing JSON-LD helpers live in `backend/app/services/extract/structured_listing_handler.py`.
- [x] Article card parsing helpers live in `backend/app/services/extract/article_card_parser.py`.
- [x] Network listing payload mapping lives in `backend/app/services/extract/network_listing_mapper.py`, exposed through public module functions only.
- [x] `_listing_record_from_card` is split into named candidate-building and record-finalization helpers without changing scoring, signal extraction, or validation order.
- [x] `extract_listing_records` uses module-level structured and DOM stage helpers instead of inner closures.
- [x] Per-card BeautifulSoup parsing is only done when selector rules or article/content parsing need it.
- [x] Root-level `backend/app/services/llm_*.py` modules are moved under `backend/app/services/llm/` with imports updated and no compat shim files left behind.
- [x] No extraction scoring, selection, network payload semantics, LLM runtime behavior, surface routing, or public record shape changes.
- [x] `backend/tests/services/test_structure.py` reflects the new layout and still acts as the architecture ratchet.
- [x] Focused extraction, LLM, structure, and config tests pass.
- [x] Full backend `.\.venv\Scripts\python.exe -m pytest tests -q` passes.

## Do Not Touch

- `backend/app/services/publish/*` and `backend/app/services/pipeline/persistence.py` - no downstream compensation.
- Browser interaction, traversal clicks, adapters, and Playwright acquisition code - not needed for this refactor.
- `backend/app/services/extraction_html_helpers.py` - shared helper, not confirmed as `extract/` owner.
- `backend/app/services/robots_policy.py`, `backend/app/services/platform_policy.py`, `backend/app/services/public_record_firewall.py` - audit grouping rejected until a narrower owner split is proven.
- `backend/app/services/artifact_store.py`, `db_utils.py`, `exceptions.py`, `runtime_metrics.py`, `run_config_snapshot.py` - no infra package move in this active phase.
- `backend/app/services/field_value_candidates.py` - confirmed large, but shared by listing, runtime, detail, DOM, and network; split only in a later phase after Phase 1 passes.
- `backend/app/services/domain_run_profile_service.py` - confirmed large Bucket 2 owner; split only in a later crawl/profile phase.
- `backend/app/services/extraction_runtime.py::extract_records` - keep routing behavior. Move only verified network listing mapping cluster in this phase.

## Phase 1: Active Slices

### Slice 1: Structured Listing Handler
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, `backend/app/services/extract/structured_listing_handler.py`, relevant tests
**What:** Move the verified structured JSON-LD cluster into a cohesive structured listing handler: `_structured_listing_record`, `_structured_listing_url`, `_extract_structured_listing`, `_structured_listing_items`, `_listing_payload_candidates`, `_normalized_payload_type`, `_typed_listing_payloads`, `_allow_standalone_typed_listing_payloads`, `_allow_embedded_json_listing_payloads`, and `_looks_like_untyped_listing_payload`.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_detail_extractor_structured_sources.py -q`

### Slice 2: Article Card Parser
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, `backend/app/services/extract/article_card_parser.py`, relevant article/listing tests
**What:** Move `_article_card_text`, `_article_card_date`, and `_article_card_summary` into an article-only parser module. Keep the article listing gate and orchestration in `listing_extractor.py`.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_article_forum_live_regressions.py tests/services/test_content_article_forum_surfaces.py -q`

### Slice 3: Network Listing Mapper
**Status:** DONE
**Files:** `backend/app/services/extraction_runtime.py`, `backend/app/services/extract/network_listing_mapper.py`, relevant extraction runtime tests
**What:** Move network listing payload mapping out of `extraction_runtime.py` behind public functions such as `extract_listing_rows_from_network` and `backfill_listing_rows_from_network`. Include the full dependency cluster so `extraction_runtime.py` does not import cross-module private helpers: `_extract_listing_rows_from_network`, `_backfill_listing_rows_from_network`, `_network_listing_row`, `_network_listing_url`, `_network_listing_image_url`, `_image_url_from_value`, `_listing_network_backfill_maps`, `_iter_listing_price_candidates`, `_first_candidate_text`, `_listing_candidate_backfill_entry`, `_listing_candidate_price`, `_listing_candidate_raw_price`, `_listing_candidate_currency`, `_listing_currency_code`, and `_listing_identity_from_url`.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py -q`

### Slice 4: Listing Card Trace And Title-Only Gate
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, focused listing tests
**What:** Extract `_selected_selector_trace` from inside `_listing_record_from_card` into module-level `_resolve_selector_trace(field_name, finalized_value, selector_trace_candidates)`. Extract the inline `allow_title_only_dom_candidate` boolean into `_is_title_only_candidate_allowed(...)` with named conditions. Preserve predicate logic.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_selectolax_css_migration.py -q`

### Slice 5: Card Candidate Builder
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, focused listing tests
**What:** Extract candidate assembly from `_listing_record_from_card` into `_build_card_candidates(...)`. Keep `_listing_record_from_card` responsible for orchestration, support gates, finalization, structural validation, selector trace attachment, and structural signature attachment. Do not change the order candidates are added. Make BeautifulSoup parsing lazy: create `card_soup` only when selector rules exist or surface is `article_listing` / `content_listing`.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_article_forum_live_regressions.py tests/services/test_content_article_forum_surfaces.py -q`

### Slice 6: Listing Stage Helpers
**Status:** DONE
**Files:** `backend/app/services/listing_extractor.py`, focused listing tests
**What:** Extract the inner `_structured_stage` and `_dom_stage` closures from `extract_listing_records` into module-level helpers with explicit parameters. Keep top-level flow and fallback order unchanged.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_content_article_forum_surfaces.py -q`

### Slice 7: LLM Package Layout
**Status:** DONE
**Files:** `backend/app/services/llm_*.py`, `backend/app/services/llm/__init__.py`, import callers, LLM tests
**What:** Move the 12 root-level LLM modules into `backend/app/services/llm/`. Update imports from `app.services.llm_*` to `app.services.llm.*`. Do not leave root-level compatibility stubs. Preserve public API behavior.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_llm_runtime.py tests/services/test_llm_circuit_breaker.py tests/services/test_config_imports.py -q`

### Slice 8: Scoped Runtime Settings Injection
**Status:** DONE
**Files:** `backend/app/services/extract/structured_listing_handler.py`, `backend/app/services/listing_extractor.py`, `backend/app/services/extraction_runtime.py`, `backend/app/services/extract/network_listing_mapper.py`, focused tests
**What:** Replace confirmed inline `crawler_runtime_settings` reads with explicit parameters or defaulted local arguments where it improves testability. Keep defaults sourced from `app/services/config/runtime_settings.py`. Do not create a second config source.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_config_imports.py tests/services/test_extraction_runtime_listing_integrity.py -q`

### Slice 9: Docs And Architecture Ratchet
**Status:** DONE
**Files:** `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, `backend/tests/services/test_structure.py`, this plan
**What:** Update ownership docs for new extraction modules and the `services/llm/` package. Adjust structure tests, LOC budgets, and private-import allowlists only as needed. Mark slices complete only after their verify commands pass.
**Verify:** From `backend`: `.\.venv\Scripts\python.exe -m pytest tests/services/test_structure.py tests -q`

## Confirmed Backlog Phases

These are verified enough to plan later. Do not execute them until Phase 1 is done and verified.

### Phase 2: Field Candidate Owner Split
**Status:** DONE
**Files:** `backend/app/services/extract/field_candidates/*`, callers in listing/runtime/detail/DOM/network, focused extraction tests
**Confirmed:** File is 41,476 bytes and exposes collection, structured candidate assembly, variant row extraction, finalization, and scoring responsibilities.
**What:** Split by responsibility under `backend/app/services/extract/field_candidates/`: candidate collection, structured payload extraction, variant row extraction, candidate finalization, scoring. Keep public import surface stable or update callers in one slice. Add structure test budget ratchet.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_structure.py -q`

### Phase 3: Crawl Runtime Package
**Status:** DONE
**Files:** `crawl/access_service.py`, `crawl/crud.py`, `crawl/events.py`, `crawl/ingestion_service.py`, `crawl/service.py`, `crawl/state.py`, `crawl/utils.py`, `crawl/batch_runtime.py`, import callers
**Confirmed:** Seven `crawl_*.py` files plus `_batch_runtime.py` are root-level Bucket 2 owners. `_batch_runtime.process_run` is imported by app tasks, dispatchers, and tests.
**What:** Move Bucket 2 crawl owners into `backend/app/services/crawl/` with public module names. Rename `_batch_runtime.py` to a non-private package module only if imports and tests are updated in the same slice. No compatibility shims.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/services/test_batch_runtime.py tests/services/test_crawl_service.py tests/services/test_crawls_api_domain_recipe.py tests/services/test_run_config_snapshots.py tests/services/test_structure.py -q`

### Phase 4: JS-State Helper Consolidation
**Status:** DONE
**Files:** `backend/app/services/js_state/helpers.py`, `backend/app/services/js_state/*`, adapter callers, JS-state/detail tests
**Confirmed:** `js_state/` has real modules and root `js_state_helpers.py` is imported by adapters, JS-state normalizer, detail DOM extractor, and tests.
**What:** Move root helper into `backend/app/services/js_state/helpers.py` or split helpers by JS-state concern if symbol usage proves multiple owners. Update imports. No root shim.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_job_platform_adapters.py tests/services/test_structure.py -q`

### Phase 5: Domain Run Profile Split
**Status:** DONE
**Files:** `backend/app/services/crawl/profile/*`, API/review/crawl/pipeline callers, crawl profile tests
**Confirmed:** File is 28,458 bytes and mixes contract normalization, profile merge/application, acquisition recipe resolution, outcome recording, and DB persistence.
**What:** Split under a crawl/profile owner after Phase 3 decides the package location. Keep explicit user controls intact: surface, traversal intent, proxy settings, and LLM enablement must not be rewritten.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_service.py tests/services/test_crawls_api_domain_recipe.py tests/services/test_run_config_snapshots.py tests/services/test_pipeline_core.py tests/services/test_structure.py -q`

## Rejected Or Unverified Audit Items

- `services/policy/` collapse is rejected for now. The named files do not share one responsibility.
- `services/infra/` move is unverified. Small root files have existing bucket ownership and need separate import-risk review.
- Full `extraction_runtime.py` stage split is unverified. Only network listing mapper movement is confirmed for Phase 1.
- Moving `extraction_html_helpers.py` into `extract/` is rejected for now because it is used outside extraction-only code.
- Targeting `< 5,000 bytes per file` is not a project rule. Use `backend/tests/services/test_structure.py` LOC budgets instead.
- Zero loose root `.py` files is not a current acceptance target. It conflicts with existing `CODEBASE_MAP.md` ownership.

## Doc Updates Required

- [x] `docs/backend-architecture.md` - document new extraction helper modules and LLM package layout if backend architecture lists service file ownership.
- [x] `docs/CODEBASE_MAP.md` - add `extract/structured_listing_handler.py`, `extract/article_card_parser.py`, `extract/network_listing_mapper.py`, and replace root `llm_*.py` entries with `llm/*`.
- [x] `docs/INVARIANTS.md` - not expected; update only if runtime extraction contracts change, which this plan should avoid.
- [x] `docs/ENGINEERING_STRATEGY.md` - not expected; update only if implementation finds a new repeatable anti-pattern or a new ratchet.

## Notes

- Audit source: `audit.md` plus user-supplied architecture review checklist.
- Verification commands used during plan update:
  - `Get-ChildItem backend/app/services -File`
  - `Get-ChildItem backend/app/services -Directory`
  - `rg "app\.services\.llm_|from app\.services import llm_" backend/app backend/tests`
  - `rg "app\.services\.(crawl_|_batch_runtime|robots_policy|platform_policy|public_record_firewall|js_state_helpers|extraction_context|extraction_html_helpers)" backend/app backend/tests`
  - `rg "def |class " backend/app/services/field_value_candidates.py backend/app/services/domain_run_profile_service.py backend/app/services/extraction_runtime.py backend/app/services/listing_extractor.py`
- Current verified sizes: `listing_extractor.py` 49,528 bytes; `field_value_candidates.py` 41,476 bytes; `extraction_runtime.py` 39,801 bytes; `domain_run_profile_service.py` 28,458 bytes.
- Current `test_structure.py` is the architecture ratchet and already owns LOC budgets, config placement checks, and private service import drift.
- No slice is complete yet. Do not mark any slice done without its verify command passing.
- Slice 1 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_detail_extractor_structured_sources.py -q` reported 183 passed, 12 skipped.
- Slice 2 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_article_forum_live_regressions.py tests/services/test_content_article_forum_surfaces.py -q` reported 21 passed.
- Slice 3 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py -q` reported 8 passed.
- Slice 4 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_selectolax_css_migration.py -q` reported 54 passed, 3 skipped.
- Slice 5 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_article_forum_live_regressions.py tests/services/test_content_article_forum_surfaces.py -q` reported 29 passed.
- Slice 6 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_content_article_forum_surfaces.py -q` reported 19 passed.
- Slice 7 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_llm_runtime.py tests/services/test_llm_circuit_breaker.py tests/services/test_config_imports.py -q` reported 50 passed.
- Slice 8 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_config_imports.py tests/services/test_extraction_runtime_listing_integrity.py -q` reported 41 passed.
- Phase 2 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_detail_extractor_structured_sources.py tests/services/test_extraction_runtime_listing_integrity.py tests/services/test_structure.py -q` reported 352 passed, 13 skipped.
- Phase 3 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_batch_runtime.py tests/services/test_crawl_service.py tests/services/test_crawls_api_domain_recipe.py tests/services/test_run_config_snapshots.py tests/services/test_structure.py -q` reported 67 passed.
- Phase 4 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_engine.py tests/services/test_job_platform_adapters.py tests/services/test_structure.py -q` reported 209 passed, 1 skipped.
- Phase 5 verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests/services/test_crawl_service.py tests/services/test_crawls_api_domain_recipe.py tests/services/test_run_config_snapshots.py tests/services/test_pipeline_core.py tests/services/test_structure.py -q` reported 102 passed.
- Full backend verification passed on 2026-05-17: `.\.venv\Scripts\python.exe -m pytest tests -q` reported 1679 passed, 16 skipped.
