# Plan: Extraction Runtime Simplification

**Created:** 2026-08-22
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** extraction contracts, collectors, entity graph, engine, detail pipeline, result building, extraction configuration

## Goal

Reduce extraction production modules to clear owners and bring every touched callable to cyclomatic complexity 15 or less without changing records, evidence lineage, variant completeness, retry requests, or publication semantics. Keep one Harvest → Resolve → Publish engine. Prefer deletion and movement into existing owners over new abstractions.

This plan owns Q-LOC-15, Q-LOC-17, Q-LOC-23 through Q-LOC-25, Q-LOC-29, Q-LOC-30, Q-LOC-32, Q-LOC-34, and all Q-CC-PY findings under `backend/app/extraction` plus extraction rule config.

## Acceptance Criteria

- [x] Oversized extraction/config owners materially shrink where a coherent split exists; 800 nonblank lines is a review target, not a reason to damage ownership.
- [x] Radon reports no callable above CC 15 in `backend/app/extraction`.
- [x] `extract()` remains the single engine facade; no parallel pipeline or compatibility facade is introduced.
- [x] Adapter → structured source → DOM order remains intact, DOM still runs when variant cues require it, JS-state traversal does not stop after the first object, and all enabled backfills remain reachable.
- [x] Public extraction contracts, evidence/source trace, entity relationships, deterministic ordering, retry shape, and record projections are behavior-equivalent.
- [x] Existing focused extraction tests remain semantically intact; characterization tests are added only for unprotected risky seams.
- [x] Net production LOC decreases or each added line has clear ownership leverage; complexity is removed, not shifted into tiny helpers.
- [ ] Focused backend pytest, Ruff, mypy, architecture tests, and `$ship-main` CI pass.

## Do Not Touch

- Acquisition/browser runtime, persistence schema, publish/export compensation, LLM enablement rules, or frontend behavior.
- Site-specific extractors, browser interaction fallbacks, or new pipeline layers.
- Field names, validation policy, evidence ranking, or public DTOs except import-only moves that preserve API symbols.
- Test-module splitting; owned by the final test-suite plan.

## Simplification Guardrails

- LOC is evidence, not the objective. Do not force an arbitrary split when the original owner remains the clearest design.
- Never reduce line counts by removing useful whitespace/comments/docstrings/types/tests, combining statements, minifying expressions, moving code to excluded paths, changing extensions, or generating opaque code.
- Never hide branches in dynamic dispatch, reflection, registries/config blobs, wrappers, lambdas, comprehensions, or tiny pass-through helpers. Complexity must disappear, not relocate.
- New modules must correspond to stable domain responsibilities and have direct callers. No `_misc`, `utils`, compatibility barrel, or file-per-function layout.
- Preserve readable formatting and domain language even when this increases LOC. A lower count with higher cognitive load is a regression.
- Do not weaken architecture tests, extraction invariants, fixtures, assertions, or debt measurement to make metrics pass.

## Slices

### Slice 1: Characterize contracts and compute the live extraction inventory

**Status:** DONE
**Files:** extraction architecture/contract/runtime/variant tests, `backend/app/core/config/extraction_semantic_surface.toml`, this plan

**What:** Read `docs/INVARIANTS.md` Rules 1–5 and relevant backend architecture sections. Recompute nonblank LOC and Radon CC for `backend/app/extraction` and `core/config/extraction_rules`. Search callers/imports before moving symbols. Capture tests protecting output order, evidence provenance, variants, price/brand flags, retries, and failure classifications. Record the exact live inventory in Notes; later commits must ratchet it down.

**Verify:** Run `tests/unit/test_extraction_architecture.py`, `test_extraction_contract_behavior.py`, `test_extraction_runtime_behavior.py`, `test_extraction_variant_behavior.py`, and `test_extraction_integrity_behavior.py` before changes.

### Slice 2: Split declarative detail rules and frozen contracts by existing responsibility

**Status:** DONE
**Files:** `backend/app/core/config/extraction_rules/_detail.py`, existing `_detail_sections.py`, `_variants.py`, `_images.py`, `_control_roles.py`, `_extra_exports.py`, `backend/app/extraction/contracts.py`, `surfaces.py`, contract tests

**What:** Move rule families into their existing config owners and leave `_detail.py` as declarative composition. Separate field-contract tables, record/result contracts, and surface lookup only where import direction stays acyclic. Preserve exported names at their canonical owner; update callers directly instead of adding a compatibility barrel. Create a new sibling only if no listed owner fits, then update `CODEBASE_MAP.md`.

**Verify:** Run focused contract, surface, and extraction architecture tests; run Ruff and mypy for changed modules; confirm both former oversized files materially simplify and touched callables are CC ≤15. If either remains above the LOC target, record why keeping it cohesive is simpler.

### Slice 3: Simplify structured and DOM collectors

**Status:** DONE
**Files:** `backend/app/extraction/collectors/dom.py`, `js_state.py`, `jsonld.py`, `_helpers.py`, `backend/app/extraction/json_walk.py`, narrowly justified collector siblings, collector tests

**What:** Keep each collector public entry in place. Separate DOM variant-control/CSS-recipe work, JS-state object-walk/network-row/variant predicates, and JSON-LD product/graph/variant-option work along real data boundaries. Reuse `json_walk.py` and `_helpers.py` where they already own the concept. Use guard clauses and named domain predicates, not one-line helper fragmentation. Explicitly preserve complete object walking and DOM fallback for variant cues.

**Verify:** Run JS-state, variant, asset, listing, integrity, and validation behavior tests. Compare collected evidence/order on existing fixtures. Run live LOC/CC scans for collector files.

### Slice 4: Simplify entity construction and result state projection

**Status:** DONE
**Files:** `backend/app/extraction/entities.py`, `result_building.py`, `field_states.py`, `resolution/*`, relevant tests

**What:** Separate entity identity/grouping, link construction, primary-root scoring, evidence-state projection, and retry-request shaping only where existing resolution/field-state owners fit. Preserve frozen types, deterministic stable ordering, parent/variant/offer links, unpublished reasons, and retry semantics. Remove duplicate branches revealed by the split.

**Verify:** Run contract, integrity, variant, asset, validation, and runtime tests; run mypy. Assert before/after representative results are equal, not merely similar.

### Slice 5: Thin the engine and detail pipeline

**Status:** DONE
**Files:** `backend/app/extraction/engine.py`, `pipeline.py`, `replay.py`, `validation.py`, `publication.py`, `result_building.py`, focused tests

**What:** Keep `extract()` and detail harvest/normalization entry points as orchestration. Move recipe replay to `replay.py`; move validation/quality predicates to the existing validation owner; keep publication projection with publication. Delete the callerless `collect_ecommerce_detail` wrapper if the foundation plan has not already done so. Flatten `_assess`, normalization, quality-flag, and failure-classification branches while preserving sequence and error behavior.

**Verify:** Run extraction runtime, integrity, contract, listing, validation, model-fallback, and architecture tests. Run Ruff, mypy, and the final extraction LOC/CC scan; no scoped CC violation may remain, and any owner above the LOC target must have a concrete cohesion rationale.

### Slice 6: Reconcile architecture and diff quality

**Status:** DONE
**Files:** `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, `docs/INVARIANTS.md` only if wording must clarify an unchanged contract, architecture debt ledgers, this plan

**What:** Update ownership maps for real moves. Delete cleared entries from the LOC/CC debt ledgers; never raise them. Review imports for cycles/private cross-owner access. Confirm tests were not weakened and the change is easier to explain than the old shape.

**Verify:** Run `git diff --check`, the focused architecture tests, and inspect the complete diff plus live inventory.

### Slice 7: `$ship-main`

**Status:** IN PROGRESS
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Create/use a feature branch, run only focused static/build checks locally, commit and push, open a non-draft PR with exact checks, wait for all required CI, fix failures on the same branch, merge only when green and mergeable, then synchronize local `main` with `--ff-only` and prune safely.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark this plan `DONE` and advance `ACTIVE.md`.

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — moved/new extraction owners.
- [x] `docs/backend-architecture.md` — extraction package layout.
- [x] `docs/INVARIANTS.md` — no wording change needed; implementation preserves the existing contracts.

## Notes

- Independent execution rule: remeasure live files and skip already-cleared findings. Do not depend on unmerged work from another plan.
- The report counted physical lines; AP-28 and existing tests use nonblank physical lines. This plan records nonblank LOC as trend evidence. It is not a hard completion constraint.
- Slice 1 baseline (2026-08-22): 20,679 nonblank Python lines across `app/extraction` and `app/core/config/extraction_rules`; 57 `app/extraction` callables exceed CC 15. Largest owners are `collectors/dom.py` 1,069, `engine.py` 1,059, `_detail.py` 1,026, `collectors/js_state.py` 914, `collectors/jsonld.py` 871, `contracts.py` 856, `entities.py` 850, `result_building.py` 824, and `pipeline.py` 781.
- Baseline CC violations by owner: result building 5; JS state 2; pipeline 6; price units 1; validation 6; replay 1; engine 3; publication 2; derived resolution 3; variant rollup 4; entities 7; collector helpers 2; decisions 2; offers 1; JSON-LD 2; listing records 2; variants 2; DOM 3 (including class aggregate); targeting 2; listing tier 0 1; assets 2. Exact live command: `.\\.venv\\Scripts\\python.exe -m radon cc app/extraction -s -a`.
- Baseline contract protection: cascade order (`test_detail_cascade_seam_orders_floors`, `test_detail_cascade_invokes_registry_floors_in_order`); provenance/accounting (`test_adapter_artifact_flows_through_evidence_engine`, `test_evidence_is_immutable`); variant completeness and later-object backfill (`test_dom_option_controls_do_not_materialize_sellable_variants`, `test_js_state_later_product_object_backfills_missing_variant_rows`); price/brand policy (`test_visible_dom_offer_normalizes_locale_price_grouping`, `test_host_title_brand_is_not_manufacturer_truth`); deterministic ordering (`test_order_and_duplicate_independence`); failures (`test_zero_record_result_has_failure_taxonomy_and_diagnostics`).
- Slice 1 verify: 232 passed across the five specified architecture/contract/runtime/variant/integrity test modules.
- Slice 2: `_detail.py` shrank from 1,026 to 699 nonblank lines by moving description/long-text and DOM-section policy into `_detail_sections.py`; the former wildcard compatibility barrel was removed. `contracts.py` shrank from 856 to 787 by moving fact-set and field-contract classification policy to the existing `variant_policy.py` and `field_mappings.py` owners. No extraction module/file was added.
- Slice 2 verify: 145 focused contract/runtime/surface/architecture tests passed; Ruff passed for changed config/contracts/orchestration modules; mypy passed for all changed Python modules.
- Slice 3: collector CC violations are cleared. Key reductions: JS/network row 41→10, JS variant recognition 23→7, helper subject identity 23→7, helper brand role 19→6, JSON-LD product 20→13, JSON-LD option parsing 16→1, DOM recipe evidence 18→10, DOM image selection 16→5, and `DomCollector` 16→3. Existing collector entry points and evidence order remain unchanged.
- Slice 3 verify: 209 JS-state/variant/asset/listing/integrity/validation tests passed; Ruff and mypy passed for all four changed collector modules; Radon reports no collector callable above CC 15. Collector owners remain cohesive despite exceeding the 800-line review target: their added named helpers directly serve one public collector entry and avoid cross-owner/private imports.
- Slice 4: entity construction, targeting, resolution, field-state projection, and retry shaping now have no callable above CC 15. Key reductions include result field states 46→11, price-unit repair 37→7, variant price reconciliation 25→14, variant inheritance 22→12, scalar resolution 22→15, variant resolution 19→4, and entity identity/group/offer linking paths to CC 15 or less. The larger entity/result owners remain cohesive because their helpers are direct domain steps of the same frozen projection and graph contracts; no new module or cross-owner private import was added.
- Slice 4 verify: 273 contract/integrity/variant/asset/validation/runtime/field-state/targeting tests passed; mypy passed for all ten changed entity/result/resolution modules; Radon reports no scoped violation.
- Slice 5 blocker (2026-08-22): Radon now reports zero callables above CC 15 (57→0), Ruff and focused mypy pass, and 320 focused behavior tests pass. The architecture test still fails only its extraction physical-LOC ratchet: 17,873 actual versus 17,029 allowed (+844). The added lines are readable named domain steps required to decompose the 57 branch-heavy callables; removing them through statement packing, tiny indirection, excluded-path moves, or test changes would violate this plan's guardrails. Slice 6 also forbids raising the LOC ledger. User direction is required to choose which constraint changes before implementation can safely continue.
- User authorized proceeding with the measured LOC ratchet. Final manifest reconciliation corrected the post-validation inventory to 17,909 nonblank lines. The default CC ceiling is lowered from 20 to 15; all cleared per-module CC exceptions are deleted, while the existing stricter resolver ceiling of 8 remains.
- Slice 5: engine assessment/failure classification, detail normalization and flags, replay artifact construction, validation checks, publication projection, and listing boundary/value selection now use named domain steps. The callerless `collect_ecommerce_detail` wrapper and three additional callerless listing/job helpers were deleted.
- Slice 5 verify: all 321 focused runtime/integrity/contract/variant/asset/listing/validation/model-fallback/architecture tests pass after ratchet reconciliation; Ruff passes for extraction/config scope; mypy passes for 54 changed source modules; Radon reports zero callables above CC 15.
- Slice 6: ownership maps now name the moved detail-section, field-classification, fact-family, replay, validation, collector, and resolution responsibilities. No import cycle, private cross-owner dependency, parallel pipeline, or invariant wording change was introduced.
- Slice 6 verify: 321 focused tests passed; repo-wide Ruff, focused mypy (54 modules), Ruff format check, architecture ratchets, and `git diff --check` passed. Final extraction inventory is 42 modules, 17,909 nonblank lines, and zero Radon callables above CC 15.
- Slice 7 blocker (PR #48): 11 CI checks pass. Backend CI fails only the dependency audit because `cryptography==49.0.0` is newly vulnerable and requires 50.0.0. Playwright smoke fails only the frontend dependency audit because locked `undici`, `react-router`, and `nanoid` versions have new high-severity advisories. No extraction test, lint, type, CodeQL, Gitleaks, review-bot, or deployment check failed. Dependency upgrades cross this plan's explicit scope and need user authorization before they can be added to PR #48.
- User confirmed dependency updates were already intended and explicitly authorized updating all backend/frontend dependencies plus closing the superseded stale dependency PRs before PR #48 continues.
- Dependency reconciliation: backend lock advanced 52 packages, including `cryptography` 50.0.0 and current build tooling; frontend direct/transitive packages and Vite+/Vitest overrides advanced to the latest policy-admissible compatible releases. Redis remains 6.4 because Celery 5.6 constrains it below 6.5. Ruff's historical default rule surface is now explicit so Ruff 0.16 does not silently turn a dependency update into an unrelated 731-finding policy expansion.
- Dependency verify: backend lock/sync, Ruff, mypy (381 modules), and PyPI vulnerability audit pass; frontend supply-chain install, peer check, high-severity audit, Vite+ check (220 files), and production build pass. Vite+ 0.2.9's root-local formatter pattern requirement removed redundant parent-directory ignores.
- First post-update CI run: dependency audits and Playwright smoke passed. Full backend CI exposed stale global LOC/oversized/complexity ledgers plus a fresh-run public API touch bug. The ledgers now match the live 88,837-line app inventory and remove all 21 cleared extraction complexity debts. Public API cold-cache touch now uses an explicit never-touched sentinel instead of assuming system monotonic uptime exceeds the 300-second throttle.
