# Plan: Services and Tooling Simplification

**Created:** 2026-08-22
**Agent:** Codex
**Status:** DONE
**Touches buckets:** persistence/extraction memory, enrichment, product intelligence, crawl orchestration, observability, public/API services, harness and browser-surface probe tooling

## Goal

Split the remaining oversized backend owners by real responsibility and reduce every non-extraction, non-core/acquisition backend callable to CC 15 or less. Preserve transaction, lock, queue, API, report, and diagnostic behavior. Tooling must share domain vocabulary without becoming a second runtime architecture.

This plan owns Q-LOC-04, Q-LOC-07, Q-LOC-08, Q-LOC-28, Q-LOC-36 and all remaining Q-CC-PY production/tooling findings not assigned to extraction, core/acquisition, or tests.

## Acceptance Criteria

- [x] The named oversized owners materially shrink where responsibility can be separated cleanly; 800 nonblank lines is a review target, not a hard constraint.
- [x] Radon reports no callable above CC 15 in the scoped backend production/tooling paths.
- [x] Learn-once locking, release snapshots, graph/version provenance, observations, job transitions, Celery idempotence, candidate scoring, and report classifications are behavior-equivalent.
- [x] API schemas/status codes, queue boundaries, persistence transaction order, diagnostic keys, and artifact formats do not change.
- [x] Existing owners (`extraction_memory_sources`, enrichment deterministic/diagnostics/repository modules, intelligence discovery/matching/service support, harness modules) are extended before creating files.
- [x] New files, if unavoidable, own one named responsibility and are added to `CODEBASE_MAP.md`; no `_misc`, generic `utils`, or compatibility barrels.
- [x] Net scoped LOC decreases and all cleared debt entries are deleted.
- [x] Focused backend pytest, Ruff, mypy, and `$ship-main` CI pass.

## Do Not Touch

- Extraction algorithm order, browser policy internals, frontend, dependency upgrades, migrations, or public behavior changes.
- Redis/PostgreSQL/Celery concurrency semantics or transaction boundaries without explicit characterization.
- Smoke scripts or corpus/fixture replay gates; AGENTS.md forbids running them unless separately requested.
- Test mega-file splitting; final test-suite plan owns that work.

## Simplification Guardrails

- LOC is a directional signal. Do not split transactional or orchestration code solely to cross a numeric threshold.
- Never game counts by stripping readable formatting/documentation/types/tests, packing statements, generating code, renaming files, or moving code into migrations, fixtures, config, or excluded directories.
- Do not hide control flow behind callbacks, reflection, registries, dynamic imports, data-driven pseudo-code, compatibility layers, or helpers with no independent responsibility.
- Keep transaction boundaries, async order, locks, retries, and side effects visible. A shorter service with hidden behavior is worse.
- New files need a stable business owner and must reduce cognitive load. Prefer deleting duplication and using existing owners.
- Do not weaken tests, artifact comparisons, architecture checks, or measurement rules to obtain favorable numbers.

## Slices

### Slice 0: Resolve assigned review findings

**Status:** DONE
**Files:** `backend/app/acquisition/browser_identity.py`, focused browser identity tests, `backend/tests/unit/test_locale_format_rules.py`

**What:** Verify the three supplied findings against live code. Make geolocation conversion failure-safe and copy permissions before appending. Do not duplicate locale parsing coverage already present.

**Verify:** Run the focused browser identity/context and locale-format unit tests plus Ruff on touched Python files.

### Slice 1: Build the live owner inventory and behavior boundary

**Status:** DONE
**Files:** scoped source, direct tests, `docs/CODEBASE_MAP.md`, this plan

**What:** Recompute LOC/CC, then map every finding to the owner documented in `CODEBASE_MAP.md`. Grep callers and inspect tests for transaction scope, async ordering, locks, retries, idempotence, diagnostics, and serialized outputs. Record exact live files/functions and planned existing destinations in Notes before moving code.

**Verify:** Run the direct learn-once/contract runtime, enrichment, product-intelligence, crawl service/batch, observability, harness support, and browser-surface probe tests as a pre-change baseline.

### Slice 2: Decompose extraction-memory persistence

**Status:** DONE
**Files:** `backend/app/persistence/extraction_memory.py`, `extraction_memory_sources.py`, `contracts.py`, existing extraction-memory core owners, focused persistence/API tests

**What:** Keep the public persistence entry points stable while separating claim/lock/write transactions, recipe compilation/projection, release/selector reads, knowledge queries, and observation recording. Reuse the existing sources/contracts/core extraction-memory modules according to ownership. Preserve session ownership and atomicity; do not hide commits in helpers.

**Verify:** Run `test_learn_once_persistence.py`, `test_learn_once_production_replay.py`, `test_contract_runtime.py`, `test_extraction_memory_api.py`, and related unit tests. Run mypy and confirm stable serialized results and concurrency assertions.

### Slice 3: Thin enrichment and intelligence orchestration

**Status:** DONE
**Files:** `backend/app/enrichment/service.py`, existing enrichment siblings, `backend/app/intelligence/service.py`, `service_support.py`, `matching.py`, `discovery.py`, related tests

**What:** Leave job entry/orchestration in each service. Move deterministic transforms, repository loads, LLM payload application/diagnostics, discovery, polling, and scoring to their established owner. Flatten status-transition logic with explicit state transitions; preserve database write order, retry/idempotence, and result summaries.

**Verify:** Run focused data-enrichment, enrichment-state, product-intelligence, and job-task tests. Confirm both service files materially simplify and all scoped callables meet CC; document any cohesive owner that remains above the LOC target.

### Slice 4: Simplify crawl/API/observability production owners

**Status:** DONE
**Files:** remaining live CC>15 files under `backend/app/crawl`, `api`, `connectors`, `observability`, `workers`, `tasks.py`, related tests

**What:** Work owner by owner. Convert long verdict/report/request-shaping branches into named predicates or data tables within the existing domain. Preserve API envelopes, status transitions, logging, metrics, run-summary keys, callback order, and public authentication. Avoid cross-owner helpers.

**Verify:** Run the direct focused test file(s) for each owner group plus Ruff/mypy. Re-scan after every group and delete only cleared debt entries.

### Slice 5: Split harness and browser-surface probe tooling

**Status:** DONE
**Files:** `backend/harness/support.py`, existing `backend/harness/*`, `backend/browser_surface_probe/core.py`, `report_rendering.py`, relevant regression tests

**What:** Separate parsing/input shaping, quality/failure classification, probe loop/runtime collection, and report rendering into existing tooling owners. Preserve CLI/API entry points and artifact schemas. Do not move runtime behavior into harness code or run smoke/corpus commands.

**Verify:** Run `tests/regression/test_harness_support.py` and `test_browser_surface_probe.py`; compare collected test counts and representative report objects; run scoped Ruff/mypy/LOC/CC.

### Slice 6: Reconcile docs, debt, and diff

**Status:** DONE
**Files:** `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, architecture tests/debt ledgers, this plan

**What:** Document final owners. Remove cleared exceptions without raising limits. Inspect import direction, async/transaction boundaries, net LOC, and test fidelity. Confirm no generated artifacts or smoke outputs entered the diff.

**Verify:** Run focused architecture tests, `git diff --check`, and inspect full diff plus final live scoped inventory.

### Slice 7: `$ship-main`

**Status:** DONE
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local checks, commit/push, open a non-draft PR, wait for every required CI job, fix on the same branch, merge only when green and mergeable, then synchronize local `main` with `--ff-only` and prune safely.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark `DONE` and advance `ACTIVE.md`.

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — final service/tool ownership.
- [x] `docs/backend-architecture.md` — package responsibility changes.
- [x] `docs/INVARIANTS.md` — reviewed; no stable runtime contract changed.

## Notes

- The migration file reported over 800 lines is intentionally not part of this plan. Its classification/exclusion belongs to the final quality-guardrails plan; do not rewrite immutable migration history for LOC.
- Implementation started on 2026-08-23; Slices 0-3 are complete and later slices are recorded below.
- 2026-08-23: User assigned this queued plan explicitly. Activated it and added Slice 0 for the separately assigned review findings. Live verification found both browser-identity findings valid. The requested `12.50` with `de-DE` locale regression already exists in `test_lone_decimal_separator_keeps_machine_price_shape_across_locales`, so no duplicate assertion will be added.
- Slice 0 verify: 20 focused browser-context and locale-format tests passed; Ruff passed on all three reviewed files. Invalid latitude, longitude, or accuracy now leaves geolocation unset, and permission augmentation copies the existing list before assignment.
- Slice 1 baseline (2026-08-23): non-extraction/core/acquisition production scan found 44 callables above CC 15. Owners: `api/crawls.py` (1); `crawl/` (20 across crud, domain memory, runtime helpers, profiles, review, sitemap/site-link owners); `enrichment/` (6); `evaluation/` (3 including the `ModelPrediction` aggregate); `intelligence/` (7); `observability/` (3); `persistence/` (5); and `tasks.py` (1). Tool scan found 16 callables above CC 15 across `harness/{artifact_quality_cases,quality_evaluator,support}.py`; `browser_surface_probe` has no live CC violation.
- Oversized live owners are `crawl/batch_runtime.py` 709, `enrichment/service.py` 905, `intelligence/service.py` 761, `persistence/extraction_memory.py` 1,394, `harness/support.py` 1,463, and `browser_surface_probe/core.py` 2,037 nonblank lines. Existing destinations are extraction-memory sources/core contracts plus a narrow persistence owner if needed; enrichment deterministic/LLM diagnostics/repository owners; intelligence discovery/matching/service-support owners; crawl/observability/publish domain owners; harness quality/artifact owners; and browser-probe reporting/signal/target owners.
- Slice 1 behavior boundary: preserve PostgreSQL session ownership, learn-once row locks and lock-timeout translation, immutable release snapshots, per-URL manifests, observation failure degradation, Celery task-id idempotence and state writes, candidate polling concurrency/order, API envelopes/status codes, diagnostic/report keys, and harness/probe artifact shapes. Baseline passed 47 extraction-memory/contract tests, 159 enrichment/intelligence/job tests, 137 crawl/observability/publish tests, and 59 harness/probe tests (402 total).
- Slice 2: `persistence/extraction_memory.py` shrank from 1,394 to 752 nonblank lines. Release compilation/loading (347), knowledge projections (169), Sentinel observations (123), and source-preference shaping (176 total in the extended source owner) now have named owners. The extraction-memory family has zero callables above CC 15; transaction locks, commits, manifests, and purge stay visible in the main writer/orchestrator. Cache size moved to canonical config. Focused mypy passed; 53 persistence/contract/API tests passed; oversized/complexity architecture checks, scoped Ruff, and `git diff --check` passed.
- Slice 3: `enrichment/service.py` shrank 905→708 and `intelligence/service.py` 761→684 nonblank lines. LLM application/prompt/diagnostic shaping moved to `llm_diagnostics.py`; deterministic size and Shopify taxonomy/repository paths were flattened in their existing owners. Candidate polling moved to the named `candidate_polling.py` owner after extending `service_support.py` proved it would become oversized; scoring/support remains 658 lines. Brand normalization moved to the existing registry. Both packages now have zero CC>15 and no new >700 owner. Focused mypy passed; 43 then 45 enrichment/architecture tests and 156 then 115 intelligence tests passed after staged moves; scoped Ruff and `git diff --check` passed.
- Slice 4: all 44 scoped production callables above CC 15 were simplified in their existing API, crawl, enrichment, evaluation, intelligence, observability, persistence/publish, and task owners. Focused production verification passed 148 tests; Ruff and full-app mypy passed.
- Slice 5: harness parsing/classification moved to `site_sets.py`, `challenge_classifier.py`, and the existing quality owner. Browser-probe collection, target diagnostics, rendering, and value coercion now have named owners. `harness/support.py` shrank 1,463→1,026 and `browser_surface_probe/core.py` 2,037→520 nonblank lines. All tooling callables are CC 15 or lower; 65 focused tests, Ruff, and mypy passed.
- Slice 6: all five named oversized roots shrank by 2,870 nonblank lines in aggregate. Cleared oversized and complexity debt entries were removed; exact full-tree LOC ratchets were reconciled to the readable implementation and focused regressions. Architecture ownership, size, and complexity checks pass without exclusions or weakened scanners.
- Closeout review findings: nine findings were live and fixed with focused coverage. Empty LLM categories remain backfillable; probe targets reject encoded/local DNS answers; country aliases and token matching are canonical; direct artifact mappings and all reopened IDs are retained; knowledge projections are ordered and template-layer scoped; both documentation findings were corrected. The diagnose/run-report request was skipped: `diagnose.json` is intentionally bounded, and `run_report` derives from persisted bounded artifacts; making it unbounded would change the protected diagnostic/artifact contract rather than repair a dropped in-memory handoff. The first combined review run passed 85 of 86 tests; after correcting its unsupported country fixture, all 51 impacted regression/component tests passed.
- Slice 7: PR #56 (`https://github.com/abhij1306/CrawlerAI/pull/56`) passed Backend CI twice (2,122 passed, 1 skipped), CodeQL, gitleaks, Playwright smoke, CodeFactor, and repository review checks at `5ece5b96`. The merge commit is recorded in the final handoff because GitHub creates it only after this plan content is merged.
- PR review closeout: six additional live findings were fixed. Geolocation now rejects non-finite/out-of-range coordinates and negative accuracy; settings-only batches use their resolved URL for count/domain; canonical selector fields are normalized at release read; Markdown-link punctuation is stripped; Sentinel confirmation counts distinct URL results; and obsolete CodeQL compatibility globals were removed. The review-save concurrency suggestion was not changed: it predates this refactor, and closing it correctly requires a new domain/surface serialization contract or lock row, which this plan explicitly excludes without separate characterization. Affected focused tests passed 84 plus the five Sentinel lifecycle cases.
