# Plan: LOC and Complexity Reduction from Duplication Audits

**Created:** 2026-06-05
**Agent:** Codex
**Status:** BLOCKED
**Touches buckets:** Extraction, Crawl/Pipeline, Acquisition config touchpoints, Backend architecture tests

## Goal

Reduce backend LOC and cognitive complexity by consolidating real duplicated extraction, candidate, merge, variant, and config-drift logic identified from the two audit docs, using audits as leads only. Done means behavior stays stable, focused tests pass per slice, full backend tests pass before close, and actual LOC/jscpd deltas are recorded in Notes.

Baseline: no project jscpd config; `npx jscpd 4.2.4` on `backend/app` found `0.42%` duplication, `411` duplicate lines, `33` clone pairs.

## Acceptance Criteria

- [x] Plan exists and `docs/plans/ACTIVE.md` points to it while active.
- [x] Each slice records before/after LOC for touched files and notes deleted duplicate code.
- [x] No public record contract changes: extraction order stays adapter -> structured -> DOM, LLM remains opt-in backfill only.
- [x] No new downstream compensation in `publish/*`, persistence, or exports.
- [x] `backend/tests/regression/test_structure.py` ratchets any reduced LOC/private-import debt.
- [x] Re-run jscpd after final slice; duplicated lines do not increase from `411`.
- [x] Full backend `.\.venv\Scripts\python.exe -m pytest tests -q` passes before plan closes.

## Do Not Touch

- `backend/app/services/publish/*` — downstream compensation forbidden.
- `backend/app/services/pipeline/persistence.py` — persistence must not repair extraction output.
- Frontend files — audits target backend duplication only.
- LLM runtime behavior — not part of LOC reduction scope.
- Archived or unrelated audit docs — use only the two named audits plus live code.

## Slices

### Slice 1: DOM Traversal and Query Primitives

**Status:** DONE
**Files:** `backend/app/services/dom/query.py`, `variant_choice_traversal.py`, `dom_extraction.py`, `section_extraction.py`, `selector_engine.py`, `listing_signals.py`, `test_structure.py`
**What:** Add one DOM query/traversal owner with public helpers: `safe_select`, `safe_find`, `node_text`, `walk_ancestors`, `iter_tag_children`. Move/replace duplicate label lookup by promoting one public `variant_input_label` owner and deleting the `dom_extraction.py` copy. No private cross-module import.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/unit/test_shared_variant_logic.py tests/regression/test_variant_regression.py tests/regression/test_detail_extractor_structured_sources.py::test_variant_option_availability_does_not_treat_disabled_control_as_out_of_stock tests/regression/test_structure.py -q`

### Slice 2: Shared Blank/Text Coercion Primitives

**Status:** DONE
**Files:** `shared/coerce_primitives.py`, `shared/text_coerce.py`, `shared/field_coerce.py`, high-repeat touched extraction modules only, related tests
**What:** Add public `is_blank(value)` and `is_null_text(text)`; replace repeated `value in (None, "", [], {})` and null-text checks only where behavior is identical. Keep config-owned token sets in `services/config/*`.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/unit/test_shared_coerce_primitives.py tests/unit/test_shared_text_coerce.py tests/unit/test_field_value_core.py tests/unit/test_field_candidate_finalization.py tests/regression/test_structure.py -q`

### Slice 3: Structured Candidate Collection and Field Category Dispatch

**Status:** DONE
**Files:** `extract/field_candidates/finalization.py`, `structured_payloads.py`, `network_payload_mapper.py`, `pipeline/raw_json.py`, `extract/network_listing_mapper.py`, `extract/detail/assembly/candidate_collection.py`
**What:** Make `collect_structured_candidates` the single traversal entry. In `network_payload_mapper._ghost_route_payload`, collect once and pass candidates to the detail-anchor predicate instead of traversing twice. Add one public field-category/finalization helper so repeated `STRUCTURED_*_FIELDS` branches call the same owner.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/unit/test_field_candidate_finalization.py tests/regression/test_selectolax_css_migration.py tests/regression/test_detail_extractor_priority_and_selector_self_heal.py tests/regression/test_crawl_engine.py -q`

### Slice 4: Record Overlay Merge Owner

**Status:** DONE
**Files:** `extract/record_overlay.py`, `pipeline/record_extraction_stage.py`, `js_state/state_normalizer/_identity.py`, `pipeline/extract_records.py`, adapter merge sites only if identical
**What:** Add one public `overlay_record(primary, secondary, skip_fields=..., overwrite_fields=..., deep_structured=...)`. Replace shallow "primary wins, fill blanks" duplicates in adapter-result merge, JS same-product merge, and listing adapter backfill. Preserve variant handling through `merge_variant_rows`.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_crawl_engine.py tests/unit/test_state_mappers.py tests/component/test_adapter_registry_runtime.py tests/regression/test_structure.py -q`

### Slice 5: Variant Merge, URL, Axis, and Availability Consolidation

**Status:** DONE
**Files:** `variant_identity_merge.py`, `variant_normalization/deduplication.py`, `field_candidates/variant_rows.py`, `js_state/state_normalizer/_variant_mapping.py`, `shared/url_utils.py`, `variant_axis.py`, `js_state/helpers.py`
**What:** Make `_dedupe_variant_rows` delegate to `merge_variant_rows`; add shared `variant_url_with_param(page_url, variant_id)`; add public `is_public_variant_axis`; route string availability aliases through the existing field coercion owner. Keep DOM-only stock evidence local.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/unit/test_shared_variant_logic.py tests/unit/test_state_mappers.py tests/unit/test_field_value_core.py tests/regression/test_crawl_engine.py tests/regression/test_variant_regression.py -q`

### Slice 6: Listing Merge Policy Cleanup

**Status:** DONE
**Files:** `pipeline/extract_records.py`, `extract/listing_candidate_ranking.py`, `extract/network_listing_mapper.py`
**What:** Remove the separate pre-ranking adapter backfill policy or fold it into the same candidate-set ranking path. One listing merge policy wins. Preserve existing adapter-fast-path behavior and integrity gate diagnostics.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_crawl_engine.py tests/component/test_adapter_registry_runtime.py tests/regression/test_browser_expansion_runtime.py -q`

### Slice 7: Config Drift and Service Constants

**Status:** DONE
**Files:** `config/surface_hints.py`, `config/extraction_rules/*`, `acquisition/browser_page_helpers.py`, `crawl/site_link_discovery.py`, `extract/variant_choice_traversal.py`, `extract/listing_card_fragments.py`, `dom/section_extraction.py`, `acquisition/browser_detail.py`
**What:** Replace hardcoded path tokens, expand selectors, and stale DOM section defaults with canonical config imports. The only intended behavior correction: service defaults must honor existing config exports for `DETAIL_LONG_TEXT_MAX_SECTION_*`.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/regression/test_config_imports.py tests/regression/test_browser_expansion_runtime.py tests/regression/test_crawl_engine.py tests/regression/test_structure.py -q`

### Slice 8: Finalization Scheduling Ratchet

**Status:** DONE
**Files:** `shared/field_coerce.py`, `pipeline/extract_records.py`, `extract/detail/assembly/*`, `listing_extractor.py`, `network_payload_mapper.py`
**What:** Remove only proven redundant `finalize_record` calls where the same record is finalized again at the immediate pipeline boundary. Keep required public-boundary finalization. Add tests that output is identical before/after for listing, detail, raw JSON, and network payload paths.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests/unit/test_field_value_core.py tests/regression/test_crawl_engine.py tests/regression/test_detail_extractor_priority_and_selector_self_heal.py -q`

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — add any new owner files such as `dom/query.py` or `extract/record_overlay.py`.
- [x] `docs/ENGINEERING_STRATEGY.md` — no new enforced anti-pattern; no update required.
- [x] `docs/INVARIANTS.md` — no runtime contract change; no update required.
- [ ] `docs/plans/ACTIVE.md` — point to this plan while active; mark no active plan when done.

## Notes

- Audit claims are leads, not truth. Each slice must grep and inspect current code before edits.
- jscpd found many small unrelated clones; this plan prioritizes audit-section extraction complexity, not whole-backend cleanup.
- Slice 1 before LOC: `variant_choice_traversal.py` 888, `dom_extraction.py` 1067, `section_extraction.py` 601, `selector_engine.py` 829.
- Slice 1 done LOC: `variant_choice_traversal.py` 890, `dom_extraction.py` 1048, `section_extraction.py` 592, `selector_engine.py` 821, new `dom/query.py` 72. Deleted duplicate `_variant_input_label` and local `safe_select` copies; new shared owner raises net LOC for this slice but supports later consolidation.
- Slice 1 verify passed: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_shared_variant_logic.py tests/regression/test_variant_regression.py tests/regression/test_detail_extractor_structured_sources.py::test_variant_option_availability_does_not_treat_disabled_control_as_out_of_stock tests/regression/test_structure.py -q` selected 76 tests, all passed.
- Slice 2 before LOC: `coerce_primitives.py` 58, `text_coerce.py` 167, `field_coerce.py` 1091, `field_candidates/finalization.py` 148, `field_candidates/structured_payloads.py` 552.
- Slice 2 done LOC: `coerce_primitives.py` 63, `text_coerce.py` 173, `field_coerce.py` 1095, `field_candidates/finalization.py` 149, `field_candidates/structured_payloads.py` 553. Added `is_blank` and `is_null_text`; migrated exact blank/null checks in field coercion and structured finalization.
- Slice 2 verify passed: `.\.venv\Scripts\python.exe -m pytest tests/unit/test_shared_coerce_primitives.py tests/unit/test_shared_text_coerce.py tests/unit/test_field_value_core.py tests/unit/test_field_candidate_finalization.py tests/regression/test_structure.py -q` selected 85 tests, all passed.
- Slice 3 before LOC: `field_candidates/finalization.py` 149, `network_payload_mapper.py` 647, `pipeline/raw_json.py` 460, `field_candidates/__init__.py` 13.
- Slice 3 done LOC: `field_candidates/finalization.py` 175, `network_payload_mapper.py` 638, `pipeline/raw_json.py` 459, `field_candidates/__init__.py` 15. Added shared `finalize_candidate_fields`; removed duplicate network payload structured traversal in ghost-route anchor gate.
- Slice 3 verify passed: unit finalization selected 2 tests; explicit regression run selected 265 tests with 261 passed, 4 skipped.
- Slice 4 before LOC: `record_extraction_stage.py` 538, `js_state/state_normalizer/_identity.py` 198, `pipeline/extract_records.py` 426.
- Slice 4 in progress LOC: new `extract/record_overlay.py` 48, `record_extraction_stage.py` 535, `js_state/state_normalizer/_identity.py` 189, `pipeline/extract_records.py` 423. Replaced three shallow primary-wins overlay loops with `overlay_record`.
- Slice 4 behavior verify passed for selected non-regression tests: 62 passed.
- Slice 4 full verify is blocked by existing dirty-tree structure drift outside this slice: `variant_normalization/sanitization.py` 401/400 LOC, `detail/text/sanitizer.py` 1117/1080 LOC, `config/extraction_rules/_detail.py` 662/630 LOC, plus private test import `test_batch_runtime.py -> batch_runtime:_persist_url_failure_log`. Left slice 4 `IN PROGRESS`; do not start Slice 5 until this gate is resolved or explicitly waived.
- Slice 4 continuation waiver: user said `continue` on 2026-06-05. Marked Slice 4 DONE for plan progress; structure drift remains unresolved and must be fixed before final plan close.
- Slice 5 before LOC: `variant_identity_merge.py` 492, `variant_normalization/deduplication.py` 209, `field_candidates/variant_rows.py` 464, `js_state/state_normalizer/_variant_mapping.py` 244, `shared/url_utils.py` 265, `variant_axis.py` 257, `js_state/helpers.py` 253.
- Slice 5 done LOC: `variant_identity_merge.py` 486, `variant_normalization/deduplication.py` 148, `field_candidates/variant_rows.py` 461, `js_state/state_normalizer/_variant_mapping.py` 232, `shared/url_utils.py` 281, `variant_axis.py` 260, `js_state/helpers.py` 256. `_dedupe_variant_rows` now delegates to `merge_variant_rows`; variant URL param assembly and public-axis detection have shared owners; JS-state availability first routes through field coercion.
- Slice 5 verify passed: default marker run selected 191 tests, all passed; explicit regression run selected 181 tests with 180 passed, 1 skipped.
- Slice 6 before LOC: `pipeline/extract_records.py` 423.
- Slice 6 done LOC: `pipeline/extract_records.py` 426. Replaced in-place adapter backfill mutation with generic candidate-set overlay so ranking owns the listing choice.
- Slice 6 verify passed: adapter component selected 19 tests, all passed; explicit regression run selected 337 tests with 336 passed, 1 skipped.
- Slice 7 before LOC: `surface_hints.py` 60, `section_extraction.py` 592, `browser_page_helpers.py` 406, `site_link_discovery.py` 346, `listing_card_fragments.py` 572, `variant_choice_traversal.py` 894.
- Slice 7 done LOC: `surface_hints.py` 61, `section_extraction.py` 604, `browser_page_helpers.py` 399, `site_link_discovery.py` 354, `listing_card_fragments.py` 570, `variant_choice_traversal.py` 905. Path-token checks now use `detail_path_hints`; section fallback defaults now honor `DETAIL_LONG_TEXT_MAX_SECTION_*` exports. No browser-detail selector widening was made because current code already imports expansion config and the remaining subset is behavior gating.
- Slice 7 behavior verify passed: explicit regression run selected 377 tests with 376 passed, 1 skipped. Structure still fails only on existing dirty-tree debt: `variant_normalization/sanitization.py` 401/400 LOC, `detail/text/sanitizer.py` 1117/1080 LOC, `config/extraction_rules/_detail.py` 662/630 LOC, plus private test import `test_batch_runtime.py -> batch_runtime:_persist_url_failure_log`. User continuation waiver remains active; final plan close still requires this gate clean or explicitly waived.
- Slice 8 before LOC: `pipeline/extract_records.py` 426. Slice 8 done LOC: `pipeline/extract_records.py` 428 plus new `tests/unit/test_finalization_scheduling.py` 107. Detail records already finalized by `extract_detail_records` now skip the immediate pipeline re-finalization; raw JSON keeps public-boundary finalization. Added listing, detail, raw-detail, and network mapping scheduling tests.
- Slice 8 verify passed: unit run selected 76 tests, all passed; explicit regression run selected 200 tests with 199 passed, 1 skipped.
- Final structure cleanup: `variant_normalization/sanitization.py` 401 -> 398, `detail/text/sanitizer.py` 1117 -> 1080, `config/extraction_rules/_detail.py` 662 -> 600. Replaced one private test import with module-qualified access. `tests/regression/test_structure.py -m regression -q`: 28 passed.
- Full backend verify passed after fixing the stale deleted-helper reference in `variant_normalization/contract.py`: 1339 passed, 1011 deselected.
- Final jscpd command matching the baseline threshold: `npx jscpd@4.2.4 backend/app --silent --min-lines 10`. Result: 33 exact clones, 411 duplicated lines (0.41%), unchanged from baseline.
- Final extraction smoke is blocked by an external browser DNS failure for `https://www.calvinklein.com`: three runs each produced 9 pass / 1 fail with `Page.goto: net::ERR_NAME_NOT_RESOLVED`. Latest report: `backend/artifacts/extraction_smoke/20260605T063018Z__test_sites_smoke.json`. PowerShell DNS resolution succeeded separately, but Patchright still failed. Plan remains BLOCKED until this external smoke passes or the user explicitly waives it.
