# Plan: God Module Consolidation & LOC Reduction

**Created:** 2026-05-12
**Agent:** Claude Opus
**Status:** IN PROGRESS
**Touches buckets:** Acquisition (3), Extraction (4), Shared field coercion, Config, Pipeline (2), Structure tests

## Goal

19 files exceed 1000 LOC (total 25,943 LOC). 38 files exceed 500 LOC (total 39,247 LOC) out of 64,648 service LOC. The top god modules concentrate in two clusters:

- **Acquisition cluster:** `browser_runtime.py` (1853), `traversal.py` (1790), `browser_page_flow.py` (1697), `browser_identity.py` (1529) — total 6,869 LOC in 4 files
- **Extraction cluster:** `shared_variant_logic.py` (1443), `detail_dom_extractor.py` (1355), `detail_materializer.py` (1301) — total 4,099 LOC in 3 files

Additionally:
- 4 facade shims (`crawl_fetch_runtime.py`, `field_value_core.py`, `field_value_dom.py`, `js_state_mapper.py`) exist as `sys.modules` redirects from a Phase 3 migration. Most callers still use old paths.
- `extraction_rules.py` (1758 LOC) is a config file that may contain dead/duplicate constants.

**Done looks like:**
- Net LOC reduction of ≥2,000 lines across services/
- Top god modules each reduced by ≥15% through dead code removal, helper consolidation, and responsibility extraction
- Facade shims either deleted (if callers migrated) or callers migrated and shim deleted
- `test_structure.py` LOC budgets tightened to new baselines
- `pytest tests -q` passes after every slice

## Do Not Touch

- `detail_extractor.py` candidate system — per AP-12, do not redesign
- `config/platforms.json` — adapter metadata, not a refactoring target
- Any behavior change — this is pure structural refactoring
- Frontend code — backend only

## Slices

### Slice 1: Delete facade shims — migrate remaining callers
**Status:** TODO
**Files:** `crawl_fetch_runtime.py`, `field_value_core.py`, `field_value_dom.py`, `js_state_mapper.py`, all callers
**What:**
- `crawl_fetch_runtime.py`: only 1 caller left (`conftest.py`). Rewrite import → delete shim.
- `field_value_core.py`: ~25 callers. Bulk-rewrite imports to `app.services.shared.field_coerce`.
- `field_value_dom.py`: ~5 callers. Rewrite imports to `app.services.dom.selector_engine`.
- `js_state_mapper.py`: ~3 callers. Rewrite imports to `app.services.js_state.state_normalizer`.
- Delete all 4 shim files.
- Remove `crawl_fetch_runtime.py` from `test_structure.py` LOC budgets.
- Remove from `DELETED_FACADES` allowlist in test_structure if present.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0. `grep -r "from app.services.crawl_fetch_runtime\|from app.services.field_value_core\|from app.services.field_value_dom\|from app.services.js_state_mapper" backend/` returns 0 hits.
**LOC impact:** −30 (shim files) + cleaner import graph

### Slice 2: browser_runtime.py — extract storage state helpers
**Status:** TODO
**Files:** `acquisition/browser_runtime.py` → new `acquisition/browser_storage_state.py`
**What:**
Functions `_persist_context_storage_state`, `_load_storage_state_for_run`, `_load_storage_state_for_domain`, `_persist_storage_state_for_run`, `_persist_storage_state_for_domain`, `_mark_storage_state_persist_policy` (lines ~919–1060) form a cohesive storage-state concern. Extract to `browser_storage_state.py`. These are called only from `SharedBrowserRuntime` and `browser_fetch`. Update imports.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −150 from browser_runtime.py (moved, not deleted — but enables budget tightening)

### Slice 3: browser_runtime.py — extract readiness/classification helpers
**Status:** TODO
**Files:** `acquisition/browser_runtime.py` → `acquisition/browser_readiness.py` (existing, extend)
**What:**
Functions `wait_for_listing_readiness`, `_wait_for_listing_readiness`, `probe_browser_readiness`, `listing_card_signal_count`, `detail_readiness_hint_count`, `expand_detail_content_if_needed`, `accessibility_expand_candidates`, `detail_expansion_keywords`, `classify_browser_outcome`, `looks_like_low_content_shell`, `classify_low_content_reason` (lines ~1757–1911) are readiness/classification concerns. Move to `browser_readiness.py` which already exists (260 LOC) and owns DOM readiness checks.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −160 from browser_runtime.py

### Slice 4: browser_runtime.py — extract popup guard and utility helpers
**Status:** TODO
**Files:** `acquisition/browser_runtime.py`
**What:**
Functions `_install_popup_guard`, `_remove_popup_guard`, `_schedule_popup_close`, `_close_unexpected_popup` (lines ~1924–end) plus small utility helpers (`_elapsed_ms`, `_emit_browser_event`, `_normalize_surface`, `_mapping_value`, `_snapshot_count`, `_int_or_zero`) are either dead or can be inlined/consolidated. Audit usage, delete dead helpers, move popup guard to `browser_page_flow.py` where it's consumed.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −80 from browser_runtime.py

### Slice 5: browser_identity.py — consolidate client-hint repair functions
**Status:** TODO
**Files:** `acquisition/browser_identity.py`
**What:**
Functions `_repair_incoherent_client_hints`, `_strip_incoherent_client_hints`, `_coherent_client_hints_from_user_agent`, `_coherent_sec_ch_headers`, `_should_replace_client_hint_headers`, `_sec_ch_ua_major_versions`, `_drop_sec_ch_headers` (lines ~673–990) are all client-hint coherence logic. Consolidate overlapping repair paths, remove dead branches, inline single-use helpers. Target: −100 LOC net.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −100

### Slice 6: traversal.py — extract card counting and snapshot helpers
**Status:** TODO
**Files:** `acquisition/traversal.py` → new `acquisition/traversal_card_counting.py`
**What:**
Functions `count_listing_cards`, `_card_count`, `_heuristic_card_count`, `_unique_listing_card_identity_count_from_html`, `_listing_card_identity`, `_page_snapshot`, `_snapshot_progressed`, `_paginate_snapshot_progressed`, `_is_marginal_card_gain`, `_paginate_fragment_budget_reached`, `_target_record_limit_reached`, `_content_signature` (lines ~1475–1740) form a cohesive card-counting/progress-tracking concern. Extract.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −270 from traversal.py

### Slice 7: shared_variant_logic.py — dead code audit and consolidation
**Status:** TODO
**Files:** `extract/shared_variant_logic.py`
**What:**
Audit all exported functions for actual callers. Functions like `_is_sequential_integer_run`, `_select_option_values_are_noise`, `_variant_group_has_multiple_options`, `_value_looks_like_color` may be dead or only called internally. Inline single-use private helpers. Consolidate overlapping noise-detection functions. Target: −150 LOC net.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −150

### Slice 8: extraction_rules.py — dead constant audit
**Status:** TODO
**Files:** `config/extraction_rules.py`
**What:**
This 1758-LOC config file likely contains constants no longer referenced. Grep every exported name against the codebase. Delete unreferenced constants. Consolidate duplicate token sets.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −100 (estimated)

### Slice 9: Tighten LOC budgets in test_structure.py
**Status:** TODO
**Files:** `tests/services/test_structure.py`
**What:**
After slices 1–8, re-measure all god modules. Set new LOC budgets to current LOC + 5% (tighter than the existing +10% policy). Remove deleted files from budget dict. Add any new extracted files with appropriate budgets.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** Prevents future drift

### Slice 10: browser_page_flow.py — extract location interstitial logic
**Status:** TODO
**Files:** `acquisition/browser_page_flow.py` → new `acquisition/browser_interstitial.py`
**What:**
Functions `location_interstitial_detected`, `_page_might_have_location_interstitial`, `dismiss_safe_location_interstitial`, `_dismiss_location_interstitial_by_text` (lines ~1150–1420) form a cohesive interstitial-handling concern. Extract to dedicated module.
**Verify:** `.\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
**LOC impact:** −270 from browser_page_flow.py

## Estimated Total LOC Reduction

| Slice | Target Reduction |
|-------|-----------------|
| 1 — Facade shims | −30 |
| 2 — Storage state extract | −150 (moved) |
| 3 — Readiness extract | −160 (moved) |
| 4 — Popup/utility cleanup | −80 |
| 5 — Client-hint consolidation | −100 |
| 6 — Card counting extract | −270 (moved) |
| 7 — Variant dead code | −150 |
| 8 — Config dead constants | −100 |
| 9 — Budget tightening | 0 (governance) |
| 10 — Interstitial extract | −270 (moved) |
| **Net deletion** | **~−460** |
| **Net movement (enables tighter budgets)** | **~−850** |
| **Total god-module LOC reduction** | **~−1,310** |

Note: "moved" LOC reduces the god module but creates a new focused file. The net deletion target (dead code, inlining, consolidation) is ~460 LOC. Combined with movement, the top god modules shrink by ~1,310 LOC total, and new files stay under 300 LOC each.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — add new extracted files to Bucket 3
- [ ] `docs/ENGINEERING_STRATEGY.md` — no changes expected unless new anti-pattern found
- [ ] `docs/INVARIANTS.md` — no changes expected (pure structural refactoring)

## Notes

- Priority order: Slice 1 first (removes dead shims, quick win), then Slices 2–4 (biggest god module), then 5–8 (secondary targets), then 9–10 (governance + cleanup).
- Each slice is independently verifiable and revertible.
- If any slice reveals additional dead code or consolidation opportunities, add a new slice rather than expanding scope.
- The `llm_runtime.py` facade is intentionally kept — it's a real re-export barrel, not a `sys.modules` shim.
