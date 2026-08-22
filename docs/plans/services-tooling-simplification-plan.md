# Plan: Services and Tooling Simplification

**Created:** 2026-08-22
**Agent:** Codex
**Status:** QUEUED
**Touches buckets:** persistence/extraction memory, enrichment, product intelligence, crawl orchestration, observability, public/API services, harness and browser-surface probe tooling

## Goal

Split the remaining oversized backend owners by real responsibility and reduce every non-extraction, non-core/acquisition backend callable to CC 15 or less. Preserve transaction, lock, queue, API, report, and diagnostic behavior. Tooling must share domain vocabulary without becoming a second runtime architecture.

This plan owns Q-LOC-04, Q-LOC-07, Q-LOC-08, Q-LOC-28, Q-LOC-36 and all remaining Q-CC-PY production/tooling findings not assigned to extraction, core/acquisition, or tests.

## Acceptance Criteria

- [ ] The named oversized owners materially shrink where responsibility can be separated cleanly; 800 nonblank lines is a review target, not a hard constraint.
- [ ] Radon reports no callable above CC 15 in the scoped backend production/tooling paths.
- [ ] Learn-once locking, release snapshots, graph/version provenance, observations, job transitions, Celery idempotence, candidate scoring, and report classifications are behavior-equivalent.
- [ ] API schemas/status codes, queue boundaries, persistence transaction order, diagnostic keys, and artifact formats do not change.
- [ ] Existing owners (`extraction_memory_sources`, enrichment deterministic/diagnostics/repository modules, intelligence discovery/matching/service support, harness modules) are extended before creating files.
- [ ] New files, if unavoidable, own one named responsibility and are added to `CODEBASE_MAP.md`; no `_misc`, generic `utils`, or compatibility barrels.
- [ ] Net scoped LOC decreases and all cleared debt entries are deleted.
- [ ] Focused backend pytest, Ruff, mypy, and `$ship-main` CI pass.

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

### Slice 1: Build the live owner inventory and behavior boundary

**Status:** TODO
**Files:** scoped source, direct tests, `docs/CODEBASE_MAP.md`, this plan

**What:** Recompute LOC/CC, then map every finding to the owner documented in `CODEBASE_MAP.md`. Grep callers and inspect tests for transaction scope, async ordering, locks, retries, idempotence, diagnostics, and serialized outputs. Record exact live files/functions and planned existing destinations in Notes before moving code.

**Verify:** Run the direct learn-once/contract runtime, enrichment, product-intelligence, crawl service/batch, observability, harness support, and browser-surface probe tests as a pre-change baseline.

### Slice 2: Decompose extraction-memory persistence

**Status:** TODO
**Files:** `backend/app/persistence/extraction_memory.py`, `extraction_memory_sources.py`, `contracts.py`, existing extraction-memory core owners, focused persistence/API tests

**What:** Keep the public persistence entry points stable while separating claim/lock/write transactions, recipe compilation/projection, release/selector reads, knowledge queries, and observation recording. Reuse the existing sources/contracts/core extraction-memory modules according to ownership. Preserve session ownership and atomicity; do not hide commits in helpers.

**Verify:** Run `test_learn_once_persistence.py`, `test_learn_once_production_replay.py`, `test_contract_runtime.py`, `test_extraction_memory_api.py`, and related unit tests. Run mypy and confirm stable serialized results and concurrency assertions.

### Slice 3: Thin enrichment and intelligence orchestration

**Status:** TODO
**Files:** `backend/app/enrichment/service.py`, existing enrichment siblings, `backend/app/intelligence/service.py`, `service_support.py`, `matching.py`, `discovery.py`, related tests

**What:** Leave job entry/orchestration in each service. Move deterministic transforms, repository loads, LLM payload application/diagnostics, discovery, polling, and scoring to their established owner. Flatten status-transition logic with explicit state transitions; preserve database write order, retry/idempotence, and result summaries.

**Verify:** Run focused data-enrichment, enrichment-state, product-intelligence, and job-task tests. Confirm both service files materially simplify and all scoped callables meet CC; document any cohesive owner that remains above the LOC target.

### Slice 4: Simplify crawl/API/observability production owners

**Status:** TODO
**Files:** remaining live CC>15 files under `backend/app/crawl`, `api`, `connectors`, `observability`, `workers`, `tasks.py`, related tests

**What:** Work owner by owner. Convert long verdict/report/request-shaping branches into named predicates or data tables within the existing domain. Preserve API envelopes, status transitions, logging, metrics, run-summary keys, callback order, and public authentication. Avoid cross-owner helpers.

**Verify:** Run the direct focused test file(s) for each owner group plus Ruff/mypy. Re-scan after every group and delete only cleared debt entries.

### Slice 5: Split harness and browser-surface probe tooling

**Status:** TODO
**Files:** `backend/harness/support.py`, existing `backend/harness/*`, `backend/browser_surface_probe/core.py`, `report_rendering.py`, relevant regression tests

**What:** Separate parsing/input shaping, quality/failure classification, probe loop/runtime collection, and report rendering into existing tooling owners. Preserve CLI/API entry points and artifact schemas. Do not move runtime behavior into harness code or run smoke/corpus commands.

**Verify:** Run `tests/regression/test_harness_support.py` and `test_browser_surface_probe.py`; compare collected test counts and representative report objects; run scoped Ruff/mypy/LOC/CC.

### Slice 6: Reconcile docs, debt, and diff

**Status:** TODO
**Files:** `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, architecture tests/debt ledgers, this plan

**What:** Document final owners. Remove cleared exceptions without raising limits. Inspect import direction, async/transaction boundaries, net LOC, and test fidelity. Confirm no generated artifacts or smoke outputs entered the diff.

**Verify:** Run focused architecture tests, `git diff --check`, and inspect full diff plus final live scoped inventory.

### Slice 7: `$ship-main`

**Status:** TODO
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local checks, commit/push, open a non-draft PR, wait for every required CI job, fix on the same branch, merge only when green and mergeable, then synchronize local `main` with `--ff-only` and prune safely.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark `DONE` and advance `ACTIVE.md`.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — final service/tool ownership.
- [ ] `docs/backend-architecture.md` — package responsibility changes.
- [ ] `docs/INVARIANTS.md` — only if a stable runtime contract needs clarification.

## Notes

- The migration file reported over 800 lines is intentionally not part of this plan. Its classification/exclusion belongs to the final quality-guardrails plan; do not rewrite immutable migration history for LOC.
- No implementation has started.
