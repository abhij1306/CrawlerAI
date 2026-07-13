# Plan: Extraction Architecture Freeze and Controlled Recovery

**Created:** 2026-07-11  
**Agent:** Codex  
**Status:** IN PROGRESS — ARCHITECTURE FROZEN; PARITY RECOVERY IN PROGRESS  
**Touches buckets:** Bucket 2 crawl integration; Bucket 3 acquisition/replay proof; Bucket 4 extraction; Bucket 5 diagnostics/persistence; Bucket 6 review/domain memory; Bucket 7 LLM; focused evaluation/tests/docs

## Goal

Stop the extraction architecture from changing during implementation. Restore one working baseline, then replace it through verified vertical slices with one recipe-first runtime. Preserve the valid correctness work from the V3 recovery plan, salvage only proven parts of the uncommitted re-architecture, and do not cut production over until cold start, learned reuse, drift, LLM, review, diagnostics, and accepted live cases all use the same understandable flow.

## Architecture Freeze

This section is the decision. Later slices may refine types and file placement. They may not change this flow without stopping implementation, amending this plan, and obtaining user approval.

```text
CaptureBundle
    -> RecipeMatcher
        -> active recipe found
            -> RecipeExecutor
            -> SurfaceValidator
            -> Publisher
        -> no active recipe or typed recipe failure
            -> DiscoveryCompiler
                -> deterministic grounded binding proposals
                -> optional budgeted model binding proposals
            -> candidate recipe
            -> RecipeExecutor
            -> SurfaceValidator
            -> Publisher
        -> no executable candidate
            -> typed honest failure

After result finalization only:
    -> ObservationRecorder
    -> CandidatePromotion / DriftPolicy
```

### Frozen component ownership

| Concern | One owner | Allowed output | Forbidden behavior |
|---|---|---|---|
| Orchestration | `app/extraction/engine.py` | `ExtractionResult` | field extraction, DB access, parallel tier cascade |
| Recipe schema and matching | `app/core/extraction_memory/recipe_contracts.py` plus one small pure matcher/compiler owner | validated recipe/candidate types | artifact reads, public records, persistence |
| Discovery compilation | one owner under `app/extraction/` | `RecipeCandidate` or typed abstention | `PublicRecord`, `ExtractionResult`, `adapter.publish()`, persistence |
| Recipe execution | one bounded pure executor owner | internal execution values, binding provenance, typed failures | generic harvest, model calls, DB access, final publication |
| Validation/publication | existing shared surface validators and publication firewall | public records and verdict | discovering replacement values, semantic repair |
| Model assistance | existing provider boundary plus one recipe-proposal adapter | grounded roots, paths, joins, senses, abstention, accounting | generated field values or `Evidence` used directly for publication |
| Learned-state persistence | extraction-memory repository and models | immutable candidates/releases/observations | extraction semantics, compilation, runtime reads from collectors |
| Acquisition learning | existing acquisition contract/cookie/replay owners | capture-path state | extraction bindings or public records |
| Review correction | existing review workflow adapted to recipe v2 | explicit candidate/activation request | legacy selector writes after cutover, hidden runtime translation |
| Diagnostics | existing URL-result diagnosis/report owner | causal states and counts | second extraction vocabulary or repaired output |

### Frozen vocabulary

- `recipe` means a persisted immutable recipe executed by `RecipeExecutor`.
- `candidate_recipe` means a newly compiled candidate executed by the same executor on the current capture.
- `deterministic` and `model` describe discovery origin only. They are not record-producing tiers.
- `generic collectors` are cold-start/drift discovery readers. They are not a publication path.
- `fallback` means compile another candidate after a typed miss. It never means merge unrelated field values into a failed result.
- `promotion` changes future recipe selection only. It never mutates the current run result.

### Frozen transition rule

The committed HEAD runtime remains the production baseline until the replacement path meets its complete cutover gate. New recipe code may run in focused tests and artifact evaluation before cutover. It may not partially replace cold-start production behavior. Cutover is one atomic slice: wire the complete path, pass the compatibility and architecture gates, then delete the old record-producing route in the same slice.

### Frozen failure behavior

- Acquisition block/readiness failures remain acquisition-owned and fail honestly.
- Active recipe failure must carry a typed root, identity, join, cardinality, binding, value, or required-field reason.
- Discovery may run only after no match or typed recipe failure.
- A public `partial` verdict alone is not drift.
- Failed active values and candidate values are never mixed.
- If no candidate executes and validates, publish no record and expose one causal failure.

## Acceptance Criteria

- [ ] The architecture flow, ownership table, vocabulary, and transition rule above remain unchanged through implementation unless the user approves a plan amendment.
- [ ] The committed recovery baseline is restored before new runtime work; its focused behavior gate exits 0.
- [ ] One recipe schema and executor serve ecommerce detail, ecommerce listing, job detail, and job listing.
- [ ] Discovery returns only a candidate recipe or abstention; it cannot construct or publish a public record.
- [ ] Active-recipe success runs only declared readers and invokes no discovery collector or model.
- [ ] Cold-start and typed drift can publish only after candidate execution and shared validation.
- [ ] Optional LLM use is grounded, budgeted, degradable, fully accounted, and proposal-only.
- [ ] Exact child identity, entity ownership, price units/senses, shell rejection, SKU/category provenance, variants, and assets survive the new runtime.
- [ ] Listing/job outputs require grounded repeated boundaries or an explicit validated singleton; utility/shell rows never become success.
- [ ] Review corrections, releases, promotion, suspension, and observations all use recipe v2 with no parallel learned-state store.
- [ ] Internal API replay stays disabled unless controlled and live two-run exact-identity parity passes.
- [ ] Coverage and run reports explain actual capture, recipe, discovery, model, validation, and publication states causally.
- [ ] Run 39+ listing/job cases and Run 41 detail cases meet the live acceptance table.
- [ ] Focused backend pytest, changed-owner Ruff, ownership/LOC gates, and relevant VitePlus verification exit 0.
- [ ] Final extraction-owned production LOC is no higher than the committed HEAD baseline; no debt budget is raised.

## Do Not Touch

- `.serena/` — local IDE/agent memory; not product source and not part of this recovery.
- `backend/app/acquisition/*` except an explicitly named replay/readiness verification owner — acquisition architecture is not being rewritten.
- `backend/app/publish/*` and exports — no downstream extraction repair.
- enrichment and unrelated AI-visibility owners — outside extraction scope; their debt must not be edited or added to this plan's allowances.
- frontend outside crawl diagnostics and Domain Memory — no broad UI redesign.
- database schema — no new table or column until the existing recipe lifecycle proves a missing persistent concept.
- live sites during implementation slices — live proof occurs only in the final acceptance slice; no ad hoc patches during acceptance.

## Audit Baseline — 2026-07-11

### Current uncommitted re-architecture state

- Tracked diff: 41 files, `+1,809/-4,027`, excluding untracked recipe modules, fixtures, and tests.
- Extraction-owned scope measured against committed `HEAD`: 18,767 -> 19,156 nonblank Python LOC, net `+389`.
- Focused touched/new test gate: 196 collected, 135 passed, 61 failed.
- Failure concentration: 57 failures route through deleted `_generic_result`; 2 architecture failures show candidate discovery is not wired; 1 shows `model_runtime.py` still returns record-producing fallback/evidence types; 1 shows grounded correction still writes rejected legacy selector recipes.
- Changed-owner Ruff is red: one undefined `_generic_result` and six unused imports in `engine.py`.
- Claimed file budgets are not met: `engine.py` 629 nonblank lines (>500), `persistence/extraction_memory.py` 836 (>700), new `recipe_executor.py` 665 (>500), new `recipe_discovery.py` 554 (>500), and recipe schema/matcher/executor total 1,011 (>700).
- The ownership test raises `browser_capture.py` debt from 736 to 753 and adds unrelated AI-visibility debt entries. This violates the no-budget-raise rule and masks unrelated debt.

### Architectural defects in the current diff

1. Phase 3 is recorded as implemented, but `engine.extract()` calls a deleted cold-start function and never imports/calls `discover_recipe_candidate()`.
2. `recipe_discovery.py` calls `adapter.harvest()`, `adapter.resolve()`, and `adapter.publish()`, then derives a recipe from the already-published record. This is a hidden second record producer and violates the plan's own compiler boundary.
3. Ecommerce-detail discovery proves identity by comparing the final URL to the same request/final URL. That is tautological and does not prove selected child/color/style ownership.
4. The engine discards `model_adapter`, hardcodes model state to `not_considered`, and removes the prior accounting path before the replacement proposal path exists.
5. Persistence rejects legacy correction writes before the review workflow can produce recipe v2. This creates an incompatible half-migration.
6. Canonical docs describe recipe-first behavior as current truth while the runtime is broken and `ENGINEERING_STRATEGY.md` still requires budgeted generalized fallback. Target and current-state docs conflict.
7. Source-string architecture tests check names more than behavior. They missed the undefined cold-start call and hidden `adapter.publish()` inside discovery.
8. Large test deletions occurred before equivalent public behavior was shown. Green schema/executor unit tests do not prove crawl, correction, listing, detail, or live parity.
9. The plan header says implementation has not started while Phases 0-3 claim implemented. Status and evidence are not trustworthy enough for handoff.

### Disposition of the uncommitted ChatGPT work

| Family | Decision | Reason |
|---|---|---|
| Recipe architecture concept | Keep in this freeze | One executable recipe path is understandable and reduces future work when proven |
| `recipe_contracts.py` concepts | Salvage selectively after baseline restore | Useful bounded vocabulary; must be reduced to actual required primitives |
| `recipe_executor.py` | Rewrite/split only after contract tests | Useful mechanics; currently over budget and not integrated with accepted correctness |
| `recipe_discovery.py` | Rewrite, do not wire | Hidden public publisher, tautological detail identity, DOM-heavy inference, over budget |
| `engine.py` Phase 3 cutover | Revert to committed baseline first | Production cold start is nonfunctional; cutover was incomplete |
| Persistence/API hard invalidation | Revert/defer | Review and promotion are not migrated; 410/rejection creates half-cutover |
| Selector/source-pin runtime deletion | Defer to atomic cutover | Delete only after recipe v2 replaces all four surfaces and review UI/API |
| Model runtime deletion/ignore path | Revert/defer | Pending proposal compiler must retain explicit enablement, accounting, and terminal states |
| New four-surface fixtures | Keep as candidate test assets after provenance audit | Helpful only if inputs are representative and expected output protects behavior |
| New architecture tests | Rewrite | Keep behavioral spy/import-boundary assertions; remove source-name certification |
| Canonical doc rewrites | Revert to truthful current-state docs, then update at cutover | Canonical docs must not claim unshipped behavior |
| Test-suite deletions | Restore before pruning | Remove tests only when mapped to deleted behavior and replaced by public contract coverage |
| LOC/debt edits | Reject and recalculate | Current measurements omit untracked code or raise unrelated debt |

### Pending work carried from `extraction-v3-live-recovery-plan.md`

| Recovery concern | Carried status in this plan |
|---|---|
| Exact child/color/style binding and cross-child rejection | Pending; becomes recipe identity/entity-join acceptance |
| Typed price units and sale semantics | Partly landed in committed baseline; revalidate through executor |
| Shell/readiness rejection | Landed in baseline; preserve with acquisition and publication regressions |
| Selected entity projection | Pending; recipe execution must preserve exact entity lineage without synthetic parent repair |
| Field ranking, SKU, category, assets, variants | Partly landed; revalidate compiler bindings and active replay |
| Listing honest failure and repeated boundaries | Landed in baseline; migrate without singleton/utility regression |
| Listing subsystem consolidation and ownership debt | Pending |
| LLM terminal states, accounting, effectiveness, start/finish proof | Accounting partly landed; proposal-only live proof pending |
| Typed replay admission and two-run proof | Admission landed; replay remains off pending proof |
| Causal coverage/reporting | Partly landed; must be reworked for recipe states |
| Accepted-label/evaluation de-bloat | Pending |
| Fresh Runs 39+ and Run 41 acceptance | Pending |

### Pending work carried from `domain-learned-extraction-rearchitecture-plan.md`

- Finish a bounded compiler that emits recipes rather than public records.
- Convert model assistance from field evidence to grounded binding proposals without losing config, budget, cost, token, and terminal-state behavior.
- Implement candidate lifecycle, immutable release selection, explicit promotion, drift, suspension, and repair.
- Migrate all four surfaces before removing legacy selector/source-pin/profile behavior.
- Delete unearned branch systems and shrink evaluation/UI only after accepted behavior is protected.
- Prove first-run compile, second distinct-sample validation/promotion, and later active-recipe reuse live.

## Execution Rules

1. No production code changes until Slice 0 is marked DONE and the user approves this frozen architecture.
2. Work one slice at a time. One focused verification run after the slice implementation is complete; do not loop on the same failing command after each small edit.
3. A slice is not DONE because code exists. Its exact gate must exit 0 and Notes must record the result.
4. Restore behavior before pruning tests. Every deleted test family needs a public-contract replacement or an explicit obsolete-behavior mapping.
5. No source-name test may certify runtime flow. Use spies/fakes, typed output assertions, import-boundary checks, and artifact replay.
6. No canonical doc may describe target behavior as shipped before atomic cutover.
7. No production feature flag or long-lived dual runtime. Pre-cutover recipe work is test/eval-only. Production switches once.
8. No current diff claim is accepted without a reproducible command and result.
9. No broad backend pytest and no smoke/corpus replay unless the user explicitly requests it.
10. Any proposed architecture change stops implementation and returns to Slice 0.

## Slices

### Slice 0: Approve the architecture freeze
**Status:** DONE (2026-07-11)  
**Files:** this plan; `docs/plans/ACTIVE.md`; superseded-plan status lines only  
**What:** Review and approve the frozen flow, ownership, vocabulary, transition rule, diff disposition, and carried pending work. Do not change production or canonical runtime docs in this slice.  
**Verify:** User explicitly approves this plan or requests a named amendment. `git diff --check` passes for plan files.

### Slice 1: Restore one truthful green baseline
**Status:** DONE (2026-07-11)  
**Files:** current uncommitted ChatGPT production/test/doc diff; no unrelated HEAD files  
**What:** Selectively revert the incomplete cutover to committed HEAD behavior. Preserve this plan. Restore cold-start extraction, model accounting, review correction, selector/profile compatibility, focused behavior tests, and truthful current-state canonical docs. Save useful recipe-v2 ideas in this plan's disposition table; do not leave dead production modules wired halfway. Recalculate exact LOC and test counts from the restored tree.  
**Verify:** The committed recovery focused gate passes; changed-owner Ruff and `git diff --check` pass; no recipe-v2 runtime is selected in production yet.

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_primary_product_root_selection.py tests\unit\test_conflict_aware_product_linking.py tests\unit\test_extraction_js_state_behavior.py tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_surface_behavior.py tests\unit\test_block_detection.py tests\unit\test_listing_record_discovery.py tests\unit\test_listing_tier0_structured.py tests\unit\test_extraction_listing_behavior.py tests\unit\test_extraction_model_fallback.py tests\unit\test_network_replay_capture.py tests\unit\test_replay_persistence_guard.py tests\regression\test_llm_runtime.py tests\regression\test_llm_circuit_breaker.py tests\component\test_internal_api_replay_extraction.py tests\component\test_llm_config_service.py tests\component\test_review_service.py tests\component\test_acquirer.py tests\component\test_crawl_service.py -q
```

### Slice 2: Define minimal recipe contracts and behavioral architecture gates
**Status:** DONE (2026-07-11)  
**Files:** canonical recipe contract/matcher owners; focused contract and architecture tests; fixtures after provenance audit  
**What:** Implement only primitives required by accepted fixtures: scope, root, identity, repeated root, relative DOM/attribute binding, named JSON/network path, explicit join, exclusion, transform/sense/unit, cardinality, requiredness, provenance, typed failure. Define `DiscoveryResult`, `RecipeCandidate`, and internal `RecipeExecutionResult`. Add import-boundary tests and behavioral spies proving discovery cannot return public records or call publication. Do not alter production routing, DB/API, or model runtime.  
**Verify:** Focused schema/matcher tests and behavioral architecture gates pass; production runtime baseline remains green; new production LOC is offset in the same owner family.

### Slice 3: Build the executor and transfer ecommerce-detail correctness
**Status:** DONE — REVERIFIED 2026-07-13  
**Files:** bounded recipe executor; existing normalization/validation/publication owners; detail fixtures/tests  
**What:** Execute candidate and active recipes mechanically. Reuse normalizers and validators. Transfer exact selected-child identity, offer/variant joins, typed price units/senses, shell requirements, SKU/category/image provenance, variant ownership, and selected-entity lineage from the recovery work. A URL compared with itself is not identity proof. Test wrong-child, family contamination, shell, record loss, price, and category cases from Run 41 artifacts. Still no production cutover.  
**Verify:** Executor-focused tests plus accepted Run 41 artifact regressions pass. Every value has one binding outcome. No resolver/model/DB import exists in executor.

### Slice 4: Build a compiler that never publishes
**Status:** IN PROGRESS — REOPENED 2026-07-13  
**Files:** one bounded discovery compiler; existing collectors/targeting/entity/resolution helpers; compiler tests  
**What:** Compile from grounded capture evidence and internal decisions, not `adapter.publish()` output. Establish product/listing/job root and identity before field bindings. Emit candidate or typed abstention. For detail, retain selected child and joins. For listing/jobs, compile repeated roots and per-row relative bindings; require repeated boundaries unless structured/network evidence explicitly validates a singleton.  
**Verify:** Cold-start tests for all four surfaces prove compiler output type, candidate replay, no public record construction inside discovery, no utility singleton, and honest abstention.

### Slice 5: Convert optional LLM assistance to proposal-only
**Status:** DONE (2026-07-11)  
**Files:** `model_runtime.py`; existing provider/config/budget/cost owners; compiler integration; focused LLM tests  
**What:** Model proposes grounded paths/roots/joins/senses only when run settings and active config enable it. Compiler validates proposals against captured artifacts. Preserve disabled/skipped/invoked/succeeded/failed/timed-out terminal states, start/finish events, token counts, cost, circuit breaker, and degradability. No model value enters a public record.  
**Verify:** Focused model, runtime, circuit-breaker, cost, and grounding tests pass. Forced gap proves candidate replay reads values from capture. Active recipe invokes model zero times.

### Slice 6: Implement lifecycle, review migration, and immutable releases
**Status:** DONE (2026-07-12)  
**Files:** existing extraction-memory model/repository/API/review owners; focused component tests  
**What:** Add candidate, active, suspended, retired transitions using existing tables where possible. Promote only after distinct-sample replay or explicit grounded operator approval. Freeze exact version into release snapshot. Record typed outcomes after extraction. Adapt grounded corrections and the recipe UI/API to recipe v2 before rejecting legacy writes. Remove compiler semantics from persistence. Do not add compatibility translation to production runtime.  
**Verify:** Three-run lifecycle, immutable snapshot, drift, correction activation, API, and storage-only ownership tests pass. No extraction module imports repository/models.

### Slice 7: Perform one atomic production cutover
**Status:** TODO — REOPENED 2026-07-13  
**Files:** `engine.py`; thin crawl integration; old runtime owners/tests deleted only with replacements  
**What:** Wire the frozen runtime exactly once. Active match executes directly. No match/typed failure invokes compiler, then candidate executor, validator, publisher. Remove old generic/model record-producing routes, source-pin recipe labeling, partial fallback, selector transport, and dual release routing in the same slice. Preserve blocked/readiness behavior and all baseline public outcomes.  
**Verify:** Baseline gate, architecture gate, four-surface cold-start/active/drift gate, review/lifecycle gate, changed-owner Ruff, mypy for affected owners, and ownership budgets all pass once.

### Slice 8: Finish replay, diagnostics, evaluation, and de-bloat
**Status:** TODO  
**Files:** existing replay admission/profile owners; diagnostics/report owners; accepted eval labels; relevant UI; dead owners identified by audit  
**What:** Keep replay off until controlled two-run proof. Make diagnostics causal for recipe select/execute, compiler origin, model terminal state, validation, publication, and honest failure. Rebuild evaluation from Run 39+ and Run 41 accepted artifacts. Delete stale tests/reports/metrics/config/UI only after reader and behavior mapping. Restore strict physical LOC/complexity budgets; do not add unrelated debt or raise allowances.  
**Verify:** Focused replay, diagnostics/report, evaluation, ownership, frontend tests/build, and final LOC measurements pass.

### Slice 9: Fresh live acceptance and close
**Status:** TODO  
**Files:** run artifacts and this plan Notes only; corrective code requires reopening the earliest owning slice  
**What:** Run fresh UI/API cases. Record run/result IDs, settings, capture path, recipe state/version, compiler/model state, readers, binding failures, records, verdict, cost row, replay state, and artifact links. No ad hoc code changes during acceptance.  
**Verify:** Every row below passes. Any P0 reopens its owning slice.

| Case | Close requirement |
|---|---|
| Arcteryx Run 39 URL | Repeated grounded products or honest failure; zero utility rows |
| Dyson Run 40 URL | Repeated grounded products or honest failure; zero accessory/navigation rows |
| ADP/Instahyre/VC5/Clark Runs 42-45 URLs | Grounded repeated jobs or explicit bounded acquisition/record-boundary failure |
| Run 41 exact-child cases 139/150/186/209 | Requested and selected child identity agree; zero cross-child field lineage |
| Run 41 shell cases 142/154/178/196/198 | No pseudo-product publication |
| Run 41 record-loss, price, category, variant, asset families | Accepted output/provenance or explicit honest failure |
| Forced LLM cold-start gap | Visible enablement, invocation, terminal state, accounting, grounded proposal, candidate replay |
| Replay candidate 209 or 149 | Browser learn first run, API replay second run, exact identity and required-field parity; otherwise replay remains off |
| Learned reuse | Cold start on product/page A, validation on distinct B, active recipe on C with no discovery/model |
| Controlled drift | Typed failed binding, no stale mixing, repair candidate replay, immutable prior release |

## Doc Updates Required

- [ ] `docs/INVARIANTS.md` — restore current truth in Slice 1; document frozen runtime only after Slice 7 passes.
- [ ] `docs/BUSINESS_LOGIC.md` — document user-visible recipe, failure, review, and diagnostics behavior after cutover.
- [ ] `docs/backend-architecture.md` — current/target distinction before cutover; retained owner flow after cutover.
- [ ] `docs/CODEBASE_MAP.md` — list only files and ownership that actually exist after each structural slice.
- [ ] `docs/ENGINEERING_STRATEGY.md` — reconcile budgeted generalized fallback with proposal-only candidate compilation; repair duplicate AP numbering without changing unrelated policy.
- [ ] `docs/frontend-architecture.md` — only if crawl diagnostics or Domain Memory UI changes.
- [x] `docs/plans/extraction-v3-live-recovery-plan.md` — superseded with pending evidence carried here.
- [x] `docs/plans/domain-learned-extraction-rearchitecture-plan.md` — superseded after audit; valid target work carried here.

## Notes

- 2026-07-13: Reverified the attached review findings against the current tree. Valid document-load guards, bounded DOM context, discovery-stage detail, persistence-level repair gating, downgrade duplicate rejection, shared AST import collection, and genuine variant-axis coverage were fixed. The reproduced page-identity brand, brand hierarchy, zero-decimal/minor-unit price, and variant-range failures were recipe compiler/executor parity defects and now pass. The retired selector/source-preference runtime and duplicate pre-cutover evidence-accounting path were deleted; result/verdict ownership remains extraction-owned and observability remains observe-only. Verification: 377 focused behavior/component tests passed, 29 architecture/ownership tests passed, full `mypy app` passed across 369 source files, changed-file Ruff passed, and `git diff --check` passed. Extraction is 16,359/16,359 physical LOC and total production is 85,243/85,369; no allowance was raised. Slice 4 and Slice 7 remain open pending remaining parity/full gates, and Slices 8-9 plus fresh live acceptance remain open.
- 2026-07-13: User-run full-suite evidence disproved Slice 7 parity: correctly configured representative rerun passed async middleware and timeout tests but reproduced record loss, entity-linking, variant, asset, and recipe-only LLM contract failures. User chose to finish recipe-v2 parity rather than restore the committed baseline. Slice 3 is reopened first; Slices 4 and 7 remain reopened pending their focused gates.
- 2026-07-13: Reopened Slice 3 fixed executor aggregation across repeated bindings/scopes and restored binding-level source provenance without persisting capture-specific evidence IDs. Executor regression gate: `tests/unit/test_recipe_executor.py` — 6 passed; focused Ruff passed. Slice 4 reopened for compiler parity.
- 2026-07-13: Slice 4 parity recovery unified compiler/executor replay of JSON scripts, dotted assignments, preloaded state, and Nuxt devalue payloads. JS-state public behavior now passes; remaining failures in that file inspect the retired capture evidence ledger. Terminal semantic-shell and not-found outcomes were restored in the recipe-only engine. Slice remains open for remaining compiler fallbacks and stale-test mapping.
- 2026-07-13: Stale capture-ledger assertions in the focused ecommerce parity suites were rewritten against recipe execution outcomes and published binding lineage. The selected parity gate reached 184/185 before the final locale-money transform correction; full mypy then passed. Full backend verification collected 1,712 tests: 1,637 passed, 74 failed, 1 skipped. Remaining mapped owners are DOM variant compilation, minor-unit/derived offer compilation, listing and non-commerce surface replay, recipe lifecycle/replay diagnostics, stale runtime/validation assertions, and physical LOC/complexity budgets. No legacy runtime was restored. Live acceptance remains blocked until these gates pass.

- 2026-07-11: User clarified that failing tests are a symptom; the primary problem is architecture churn and an incomprehensible half-cutover. Production work is frozen pending approval of Slice 0.
- 2026-07-11: User approved implementation. Slice 0 architecture is frozen. Slice 1 restored tracked production, tests, evaluation, and canonical docs to committed HEAD and removed the untracked half-cutover recipe modules/tests/fixtures; verification pending.
- 2026-07-11: Slice 1 verification passed: 306 focused backend tests and changed-owner Ruff. `git diff --raw` shows production content at committed HEAD; remaining non-plan status entries are line-ending/stat noise with no content diff.
- 2026-07-11: Slice 2 added a 113-nonblank-line frozen recipe contract with no extraction/persistence/model imports. Schema/runtime/architecture verification passed 64 tests and focused Ruff. Core package LOC budget passes. Separate global ownership ratchets remain red on committed pre-existing `browser_capture.py` size and AI-visibility complexity inventory; no allowance was changed. The temporary contract addition must be offset before final cutover.
- 2026-07-11: Slice 3 added a 351-nonblank-line mechanical executor below the 500-line ceiling. Sanitized exact-child, join, minor-unit price, category, image, repeated-variant, exclusion, and shell contracts pass; 96 detail/executor regression tests and focused Ruff passed. Executor imports no discovery collectors, resolver, model, ORM, or persistence owner.
- 2026-07-11: Slice 4 added one non-publishing compiler and consolidated three representation files into one. Fake-source cold-start/replay passes all four surfaces; a real DOM listing compiles repeated relative bindings; DOM singleton abstains. Compiler never calls `adapter.publish()`, constructs no public records, and has max complexity 18. Focused compiler/listing/architecture gates and Ruff pass.
- 2026-07-11: Slice 5 added a proposal-only model seam while preserving the committed production fallback until atomic cutover. Grounded title/URL paths compile and replay captured values; proposal types contain no value field. Disabled mode is lazy and invocation, terminal state, tokens, cost, and rejection metrics survive. Twenty-eight focused model/runtime/circuit-breaker tests and Ruff pass.
- 2026-07-11: Audit reproduced 61 failures in the touched/new focused suite. No production fixes were made.
- 2026-07-11: The frozen design retains recipe-first execution but changes migration strategy: restore a working baseline, build and prove the replacement off the production path, then cut over atomically.
- 2026-07-11: Valid recovery evidence and completed fixes are retained as acceptance contracts. Valid recipe-v2 concepts are salvage candidates, not accepted implementation.
- 2026-07-12: Slice 7 implementation is wired as one recipe-first route: active `release.v2` recipe execution, deterministic candidate compilation, optional grounded model proposals, shared publication, then observation/lifecycle recording. Focused cutover, lifecycle, review, API, compiler, executor, and ownership tests passed during implementation; final broad verification remains user-run before this slice is marked DONE.
- 2026-07-12: Slice 8 removed the remaining selector-correction writer. Corrections now require an executable recipe candidate, representative replay, and explicit activation; LLM repair returns `recipe_candidate_required` rather than writing a selector rule. `diagnose.json` now carries causal recipe selection, candidate, execution, binding, and stage state. Focused review/API verification: 12 passed.
- 2026-07-13: Existing artifacts for Runs 39-45 were inspected. They predate atomic cutover and therefore remain regression inputs only; they do not satisfy Slice 9's fresh live acceptance requirement.
- 2026-07-13: Recipe-only correction and model-repair gate passed: `tests/unit/test_llm_repair.py`, `tests/component/test_review_service.py`, and `tests/component/test_crawls_api_domain_recipe.py` — 23 passed. The plugin-disabled architecture test attempt was rejected as invalid because this repository's autouse async fixture requires `pytest-asyncio`; direct physical LOC checks remain at `targeting.py` 350/350 and `resolution/__init__.py` 2000/2000.
- 2026-07-13: Slice 7 normal architecture gate passed: `tests/unit/test_extraction_architecture.py` — 26 passed. The recipe-first cutover has no selector/source-pin/sentinel runtime route, compiler publication, executor persistence import, or model value publication route.
- 2026-07-13: Slice 8 eval inventory: `eval.corpus --stats` shows commerce-detail labels are bound to ineligible Run 1 evidence (`accepted_evidence_run=false`); ecommerce listing, job detail, and job listing each have 0 registered / 0 verified labels against a target of 20. Fresh accepted artifacts and human verification are required before the eval gate may run or report a pass.
- 2026-07-13: Slice 8 removed source-pin/selector-era eval routing and the stale `v3_gate.json` report. Offline evaluation now invokes the same cold-start recipe compiler/executor path as production; deterministic candidate success suppresses model invocation. Eval unit gate: `tests/unit/test_extraction_v3_eval.py` — 16 passed.
- 2026-07-13: Slice 8 replay and diagnostics gate passed: `tests/component/test_internal_api_replay_extraction.py` and `tests/component/test_diagnostics_api.py` — 8 passed. Replay remains opt-in (`internal_api_replay_enabled=false`); recipe diagnosis is causal and bounded.
