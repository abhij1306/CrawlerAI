# Plan: Final Architecture Improvement and Quality Hardening

**Created:** 2026-06-19
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** all backend runtime ownership buckets, persistence models/migrations, tests, canonical docs

## Goal

Replace duplicated runtime ownership with the final modular-monolith architecture, preserve useful acquisition and product capabilities, reduce LOC and latency debt, then fix the generic failure classes demonstrated by the 94-record `output.json`. No site-specific runtime branches. No live smoke runs until the user executes the final 100-site gate.

## Target Flow

```text
RunCoordinator
  -> UrlProcessor
      -> AcquisitionPlanner
      -> AttemptExecutor
      -> ExtractionEngine
      -> UrlResultRepository + ArtifactRepository
  -> RunAggregator
```

Target packages: `app/api`, `app/core`, `app/crawl`, `app/acquisition`, `app/extraction`, `app/persistence`, `app/connectors`, `app/intelligence`, `app/enrichment`, `app/observability`, and `app/workers`. Delete `app/services` after migration; do not leave a compatibility package.

## Acceptance Criteria

- [ ] Canonical typed `AcquisitionPlan`, `AttemptSpec`, `AttemptResult`, `AcquisitionResult`, `CapabilityRequest`, `ExtractionResult`, `UrlResult`, `ArtifactManifest`, and `RunSummary` interfaces exist at their owning modules.
- [ ] Explicit surface and user-control contracts remain unchanged.
- [ ] One owner remains for acquisition planning, attempt execution, extraction verdicts, URL processing, persistence, and run aggregation.
- [ ] `app/services` and all `app.services` imports are deleted.
- [ ] Public endpoints and record field names remain compatible.
- [ ] HTTP, Patchright, Real Chrome, proxies, warmup, challenge recovery, safe storage state, host memory, API capture, and traversal remain.
- [ ] Persistence stores canonical typed output without semantic repair or verdict recomputation.
- [ ] Artifact writes are atomic, hashed, manifest-last, and replayable.
- [ ] Product intelligence reuses normal acquisition/extraction; enrichment cannot alter extraction facts or verdicts.
- [ ] Explicit variants survive all deterministic evidence paths with row lineage; option controls do not become fake variants.
- [ ] Detail URLs cannot disappear; shells cannot succeed; UI assets cannot become primary images.
- [ ] Price/currency remain atomic; magnitude repair requires corroboration; parent/variant availability cannot contradict publicly.
- [ ] Missing evidence is diagnosed and never fabricated.
- [ ] Acquisition orchestration LOC falls at least 35%; duplicated pipeline/crawl orchestration falls at least 30%; stale extraction/config code falls at least 50%; net production LOC decreases.
- [ ] Extraction remains within 24 files / 5,500 LOC / 400 lines per file / 60 lines per function.
- [ ] No non-data module exceeds 700 lines and no function exceeds 100 lines without a justified allowlist.
- [ ] Full backend pytest passes without running smoke/live commands.
- [ ] Plan remains active as `AWAITING USER 100-SITE GATE` after implementation verification.

## Do Not Touch

- Do not reset, stash, checkout, or discard the existing dirty working tree.
- Do not add hostname/site-name branches to generic runtime modules.
- Do not run smoke scripts, browser probes, or live acceptance.
- Do not redesign frontend behavior or break public endpoints.
- Do not add LangGraph to the hot path or LLM-generated extraction facts.
- Do not replace local artifact storage with global content-addressed storage.

## Slices

### Slice 1: Activate And Freeze Evidence
**Status:** DONE
**Files:** this plan, `docs/plans/ACTIVE.md`, prior extraction plan notes, `output.json`, quality/debt baselines
**What:** Activate this plan, mark the prior plan superseded, preserve dirty-tree inventory, classify the 94-record output failures, and record architecture/LOC/function/duplication baselines.
**Verify:** Active plan points here; baseline records 94 inputs and current dirty-state/LOC metrics.
**Notes:** Verified active-plan pointer, 94-record issue manifest, dirty-tree inventory, and architecture/LOC baseline on 2026-06-19. No live command ran.

### Slice 2: Canonical Contracts
**Status:** DONE
**What:** Add canonical interfaces and tests preventing duplicate acquisition, retry, verdict, persistence, and aggregation owners.
**Verify:** Focused contract and architecture tests pass.
**Notes:** Added immutable versioned contracts and owner allowlists. Red-green verification passed `14` focused tests. Legacy acquisition classes remain explicitly allowlisted only until their cutover slice.

### Slice 3: Core And Configuration Cutover
**Status:** IN PROGRESS
**What:** Move configuration to `app/core/config`, separate settings/policy/data, compose domain settings, and move pure primitives to real owners.
**Verify:** Config/ownership scans and full backend pytest pass.

### Slice 4: Acquisition Cutover
**Status:** TODO
**What:** Move acquisition/fetch mechanics, implement finite planner and single-attempt executor, preserve capabilities, and delete duplicate policy/retry/budget paths.
**Verify:** Acquisition tests and full backend pytest pass; every transition yields an `AttemptResult`.

### Slice 5: Extraction Cutover
**Status:** TODO
**What:** Move the four-surface evidence engine, keep one entry interface, materialize typed records once, and remove semantic public-firewall/coercion/persistence repair.
**Verify:** Architecture, four-surface, and offline replay tests pass.

### Slice 6: Persistence And Artifact Hardening
**Status:** TODO
**What:** Add canonical URL results, record links, atomic hashed manifests, legacy diagnostic export/backfill, and remove obsolete persistence fields after validation.
**Verify:** Migration, idempotency, interrupted-write, manifest, and persistence tests pass.

### Slice 7: Crawl And Worker Cutover
**Status:** TODO
**What:** Establish sole `RunCoordinator` and `UrlProcessor`, replace stage contexts/retry modules, and preserve run controls, discovery, concurrency, leases, and idempotency.
**Verify:** Crawl orchestration, restart/idempotency, and full backend tests pass.

### Slice 8: Remaining Domain Cutover
**Status:** TODO
**What:** Make observability read-only, isolate provider connectors, reuse normal crawl for intelligence, and enforce typed enrichment inputs/outputs.
**Verify:** Focused domain tests and full backend pytest pass.

### Slice 9: Architecture Gate And Deletion
**Status:** TODO
**What:** Delete `app/services`, pass-through wrappers, duplicate owners, stale exports, and implementation-coupled tests. Enforce LOC/import/domain-branch limits.
**Verify:** Zero `app.services` imports/files; architecture and full backend tests pass.

### Slice 10: Variant And Option Correctness
**Status:** TODO
**What:** Exhaust structured objects, prevent DOM/backfill early exits, merge exact variant identities, preserve sellable rows/lineage, and diagnose unexplained variant loss.
**Verify:** Structured, JS-state, network, DOM, cross-source, and option-only regressions pass offline.

### Slice 11: Identity, Shell, And Asset Correctness
**Status:** TODO
**What:** Guarantee canonical detail URLs, reject shells/UI identity pollution, classify asset roles, normalize image URLs, and reject utility assets.
**Verify:** URL, shell, title/brand, placeholder, and image regressions pass offline.

### Slice 12: Offer And Inventory Correctness
**Status:** TODO
**What:** Keep offers atomic, require corroborated magnitude correction, derive coherent parent availability, and diagnose missing requested fields.
**Verify:** Offer, magnitude, availability conflict, and missing-field regressions pass offline.

### Slice 13: Final Retirement And Handoff
**Status:** TODO
**What:** Re-run caller/capability/replacement analysis, delete proven debt, update docs, and run final offline verification. Do not run live tests.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`; architecture/LOC gates pass. Status becomes `IN PROGRESS — AWAITING USER 100-SITE GATE`.

## Final User Gate

The user runs one 100-site smoke after implementation. It must show zero success shells, missing detail URLs, invalid primary assets, contradictory inventory states, or unexplained explicit-variant loss. Where comparable timing exists, p50/p95 may not regress more than 10% from the 94-run baseline.

## Doc Updates Required

- [ ] `AGENTS.md`, `docs/INVARIANTS.md`, `docs/CODEBASE_MAP.md`, `docs/BUSINESS_LOGIC.md`
- [ ] `docs/ENGINEERING_STRATEGY.md`, `docs/backend-architecture.md`
- [ ] Revised architecture feature specification implementation status

## Notes

- Absorbs `docs/feature specs/CrawlerAI_Final_App_Architecture_Simplification_and_Hardening_Plan_REVISED.md` in full.
- Previous extraction work is input, not assumed verified final architecture.
- `output.json` is diagnostic evidence. Only saved capture fixtures are replay evidence.
