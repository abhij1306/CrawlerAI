# Plan: Test-Suite Decomposition, Quality Guardrails, and CodeQL Closeout

**Created:** 2026-08-22
**Agent:** Codex
**Status:** QUEUED
**Touches buckets:** backend and frontend tests, architecture-policy scanners, quality-debt ledgers, CI workflows, immutable migration classification, CodeQL alerts/issues

## Goal

Split mega-test modules by public behavior, clear remaining test/tool complexity, and replace raise-only debt handling with honest repository quality guardrails. Preserve the exact collected behavior and make focused verification practical. Treat LOC as trend evidence rather than a quota, enforce behavior/static/security checks that cannot be gamed, and finish by resolving every open CodeQL alert or associated issue with evidence.

This plan owns Q-LOC-01 through Q-LOC-03, Q-LOC-05, Q-LOC-06, Q-LOC-09 through Q-LOC-13, Q-LOC-16, Q-LOC-18 through Q-LOC-22, Q-LOC-26, Q-LOC-31, Q-LOC-33, Q-LOC-37, Q-GATE-LOC, Q-GATE-CC, Q-CC test findings, and the classification of Q-LOC-14. Production violations found at startup are routed back to their owning plan rather than exempted.

## Acceptance Criteria

- [ ] Mega-test modules materially shrink through behavior-based ownership; 800 nonblank lines is a review target, not a hard reason to fragment a cohesive suite.
- [ ] Every backend test/tool callable is CC 15 or less.
- [ ] Frontend test LOC is measured and ratcheted honestly; included test callables contain no CC>15 findings.
- [ ] Test collection counts and parametrized case IDs for each original mega-file are preserved or increased only by explicit new characterization.
- [ ] Shared fixtures live in narrowly named support/conftest owners and do not hide assertions, business logic, or mutable cross-test state.
- [ ] Immutable Alembic migrations are explicitly classified and excluded from maintainability LOC only by a narrow path rule; runtime/tool/test source receives no exemption.
- [ ] One documented counting method is used by local architecture tests and CI. Backend follows AP-28: nonblank physical lines, not normalized AST output.
- [ ] Backend/frontend CC max 15 and existing lint, format, type, test, architecture, audit, and security checks are blocking; LOC is reported and cannot regress without an explicit ownership rationale.
- [ ] No line-count result is achieved through formatting tricks, code packing, generated indirection, excluded-path moves, weakened tests, or arbitrary file shards.
- [ ] Every open GitHub CodeQL alert and bot-associated issue is inspected; valid findings are fixed and verified, and only proven false positives/test-only/unreachable findings are dismissed with an accurate reason and comment.
- [ ] CodeQL remains enabled with its existing query/security coverage, the final CodeQL run is green, and GitHub readback shows no unresolved alert/issue from the starting inventory.
- [ ] Existing full backend pytest remains CI-owned; local work uses focused split files. Frontend unit, policy, build, and required CI are green.
- [ ] `$ship-main` completes with all required CI green.

## Do Not Touch

- Production behavior, public contracts, runtime owners, dependency versions, or feature implementation, except the narrow owner-correct fix required for a validated CodeQL finding.
- Test deletion, assertion weakening, broad fixture autouse, reordered global state, or reduced parameter coverage to meet LOC.
- Rewriting/splitting applied migration history.
- Smoke scripts, live crawling, or corpus replay.
- Metric exceptions, exclusions, or suppressions added merely to manufacture a pass.
- CodeQL workflow/query disablement, severity reduction, blanket suppression, mass dismissal, or issue closure without alert-state readback.

## Simplification Guardrails

- LOC is a diagnostic and improvement goal, not a hard completion constraint. A cohesive test owner may remain above a target when splitting would obscure behavior.
- Never lower LOC by deleting useful blank lines, comments, docstrings, types, assertions, fixtures, or cases; packing statements; minifying parametrization; generating tests; renaming extensions; or moving code into excluded/unscanned paths.
- Never hide complexity in fixture factories, `conftest` autouse state, dynamic test generation, opaque data tables, wrappers, reflection, or helpers that contain the same branching as the original test.
- Split only by public behavior/owner. Shared support must express reusable setup or assertions and remain directly understandable.
- Preserve collected cases, parameter IDs, assertion strength, isolation, and failure readability even when that costs lines.
- Quality and security tools are evidence mechanisms. Do not tune scanners, exclusions, severities, or workflows around inconvenient findings.

## Slices

### Slice 1: Define honest measurement and baseline collection

**Status:** TODO
**Files:** `backend/tests/unit/test_final_architecture_ownership.py`, `test_extraction_architecture.py`, `frontend/scripts/check-frontend-architecture.mjs`, `frontend/vite.config.ts`, CI workflows, this plan

**What:** Recompute the live repo inventory. Choose and document nonblank physical lines for Python/test LOC per AP-28; keep frontend's existing physical-line policy only if one unified implementation would create drift, and state the distinction. LOC output is a review trend/ratchet, not a forced absolute gate. Use Radon `cc_visit` with explicit `complexity > 15`; do not use Radon grade buckets or `--min C`. Capture baseline pytest collection counts/node IDs for each mega-file and frontend test counts before moving anything. Do not enable blocking gates yet.

**Verify:** Run collection-only commands for the exact target files, existing architecture tests, frontend architecture script, and a report-only scan. Store counts in Notes, not generated repository artifacts.

### Slice 2: Split acquisition, crawl, and browser mega-tests

**Status:** TODO
**Files:** `backend/tests/component/test_crawl_fetch_runtime.py`, `test_browser_context.py`, `test_crawl_service.py`, `test_sitemap_resolver.py`, `backend/tests/regression/test_batch_runtime.py`, narrowly named support/conftest modules

**What:** Split by the public owner or behavior under test: HTTP/fetch planning, browser lifecycle/context, crawl dispatch/state, batch concurrency/control, sitemap/category discovery. Keep fixtures near their consumers; share only stable setup vocabulary. Preserve marks, parameter IDs, async fixtures, monkeypatch scope, and test order independence.

**Verify:** Run pytest collection before/after for these files, then focused pytest on all resulting modules. Counts and case IDs must reconcile.

### Slice 3: Split extraction and persistence mega-tests

**Status:** TODO
**Files:** `backend/tests/unit/test_extraction_contract_behavior.py`, `test_extraction_js_state_behavior.py`, `test_extraction_runtime_behavior.py`, `test_extraction_integrity_behavior.py`, `test_extraction_variant_behavior.py`, `test_extraction_asset_behavior.py`, `test_evaluation_phase4.py`, `test_crawl_run_95_regressions.py`, `backend/tests/component/test_learn_once_persistence.py`, `test_contract_runtime.py`, support modules

**What:** Split by public contracts, collectors, runtime facade, integrity, variants/assets, evaluation gate, and persistence/release behavior. Preserve grounded cases, fixture provenance, test marks, parameter IDs, and assertion strength. Do not reshape production imports to make tests convenient.

**Verify:** Reconcile collection/node IDs and run focused pytest on every resulting module plus extraction architecture tests.

### Slice 4: Split remaining service, public API, harness, and frontend mega-tests

**Status:** TODO
**Files:** `backend/tests/component/test_product_intelligence.py`, `test_public_api.py`, `backend/tests/regression/test_harness_support.py`, `test_data_enrichment.py`, `frontend/components/crawl/crawl-run-screen.test.tsx`, support files

**What:** Split by endpoint/resource or visible behavior: discovery/scoring/review, API auth/extract/batch/domain info, harness parsing/classification/artifacts, enrichment job stages, and crawl-run polling/log/output/action views. Preserve database fixtures, mock boundaries, role/auth cases, fake timers, query clients, and accessibility assertions.

**Verify:** Reconcile backend pytest collection and frontend test names/counts; run all resulting focused pytest and `vp test <path>` files plus `vp check`.

### Slice 5: Clear test/tool CC and classify migrations

**Status:** TODO
**Files:** remaining test/tool CC>15 functions, scanner path rules, architecture docs/tests

**What:** Split multi-behavior test functions into named cases without losing assertions. Extract assertion helpers only when they express a reusable domain expectation. Add a narrow immutable-migration exclusion such as `backend/alembic/versions/**` to maintainability LOC; migrations remain covered by migration-drift/upgrade checks. Do not exempt harness, probes, tests, or runtime code.

**Verify:** Scoped pytest/VitePlus tests pass; CC scanners show zero in-scope test/tool violations, LOC reports show honest before/after movement, and the only structural exclusion is the documented immutable migration path.

### Slice 6: Enable honest blocking quality gates

**Status:** TODO
**Files:** backend architecture tests/config, frontend lint/architecture policy, `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-playwright-smoke.yml`, relevant docs

**What:** Delete cleared `COMPLEX_FUNCTION_DEBT` and raised complexity budgets, then enforce CC ≤15 in blocking CI. Replace raise-only LOC debt with a transparent report plus no-regression ratchet tied to coherent owners; lower/remove line-budget exceptions when real simplification permits, but do not force arbitrary splits or formatting manipulation. Keep tighter existing feature budgets where they remain useful and green. Any LOC increase needs an explicit ownership rationale in the PR, not a silent ceiling raise.

**Verify:** Run focused architecture/policy tests, Ruff check/format, mypy, `vp check`, frontend policy, and `vp build`. Confirm temporary CC and LOC-regression samples fail the correct gates, then remove them. Confirm a large but unchanged cohesive file does not fail merely because of its absolute size. Let CI run full suites.

### Slice 7: Resolve and close open CodeQL findings

**Status:** TODO
**Files:** GitHub CodeQL alerts/issues, `.github/workflows/codeql.yml`, narrowly affected production/test owners for validated findings

**What:** Use `npx -y gh-axi` for repository state and `gh-axi api` for the code-scanning alerts endpoint. Snapshot every open alert and any GitHub issue created from CodeQL, including number, rule, severity, path, commit, and state. Triage one finding at a time. Fix valid findings in their canonical owner with focused regression/security tests. Dismiss only when the evidence proves `false_positive`, `used_in_tests`, or a genuinely unreachable/won't-fix case, using the accurate GitHub dismissal reason and a specific comment. Close associated issues only after the alert is fixed/dismissed and read back. Never mass-dismiss, suppress the query, reduce severity, or disable CodeQL to reach zero.

**Verify:** Re-run the CodeQL workflow and wait for completion. Read back the alerts API and issue list. The starting inventory must have no unresolved entries; each closed/dismissed item must have recorded evidence, disposition, and linked fixing commit/PR where applicable.

### Slice 8: Final program reconciliation

**Status:** TODO
**Files:** `docs/ENGINEERING_STRATEGY.md`, `docs/backend-architecture.md`, `docs/frontend-architecture.md`, `docs/CODEBASE_MAP.md`, this plan, `docs/plans/ACTIVE.md`

**What:** Document exact scope/counting/exclusions and focused-test ownership. Confirm the productionization finding register is resolved or explicitly superseded by live evidence. Check all six plan Notes/PRs, remove stale queue entries, and ensure no plan gamed LOC/CC or security measurements.

**Verify:** `git diff --check`; inspect full diff; run the final report-only inventory and record zero violations plus exact commands in Notes.

### Slice 9: `$ship-main`

**Status:** TODO
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local static/build checks, commit/push, open a non-draft PR with exact checks and collection reconciliation, wait for every required CI job, fix failures on the same branch, merge only when green and mergeable, then switch to `main`, pull `--ff-only`, prune safely, and verify local HEAD equals remote `main`.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark this plan `DONE`; update `ACTIVE.md` to `No active plan.`

## Doc Updates Required

- [ ] `docs/ENGINEERING_STRATEGY.md` — canonical LOC trend/ratchet, CC gate, anti-gaming rules, and migration exclusion.
- [ ] `docs/backend-architecture.md` — split test ownership only if durable guidance belongs there.
- [ ] `docs/frontend-architecture.md` — frontend test/policy gate behavior.
- [ ] `docs/CODEBASE_MAP.md` — new named support owners if any.

## Notes

- Recommended execution order is last, after the four production simplification plans. It is still self-contained: it recomputes the live tree and refuses metric workarounds for unfinished production debt.
- Local backend full-suite execution remains prohibited by AGENTS.md. Required full-suite evidence comes from CI during `$ship-main`.
- No implementation has started.
