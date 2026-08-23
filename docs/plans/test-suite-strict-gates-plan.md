# Plan: Test-Suite Decomposition, Quality Guardrails, AI Visibility Removal, and CodeQL Closeout

**Created:** 2026-08-22
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** AI Visibility backend/frontend feature surface and persistence, PostgreSQL bootstrap and migrations, Logfire observability, backend and frontend tests, architecture-policy scanners, quality-debt ledgers, CI workflows, CodeQL alerts/issues

## Goal

Delete AI Visibility as a product feature, reset the development database onto one clean migration using the canonical `crawlerai` database name, and complete first-party Logfire observability for `abhij1306/crawlerai`. Then split remaining mega-test modules by public behavior, clear remaining test/tool complexity, and replace raise-only debt handling with honest repository quality guardrails. Preserve the exact collected behavior of retained tests and make focused verification practical. Treat LOC as trend evidence rather than a quota, enforce behavior/static/security checks that cannot be gamed, and finish by resolving every open CodeQL alert or associated issue with evidence.

This plan owns Q-LOC-01 through Q-LOC-03, Q-LOC-05, Q-LOC-06, Q-LOC-09 through Q-LOC-13, Q-LOC-16, Q-LOC-18 through Q-LOC-22, Q-LOC-26, Q-LOC-31, Q-LOC-33, Q-LOC-37, Q-GATE-LOC, Q-GATE-CC, Q-CC test findings, and the classification of Q-LOC-14. Production violations found at startup are routed back to their owning plan rather than exempted.

## Acceptance Criteria

- [x] Mega-test modules materially shrink through behavior-based ownership; 800 nonblank lines is a review target, not a hard reason to fragment a cohesive suite.
- [x] AI Visibility has no backend route, runtime/provider package, schema, model export, config, frontend route/UI/API client, navigation entry, query key, dedicated test, or canonical-doc ownership entry.
- [x] Alembic contains one clean-start migration matching the retained ORM schema and no AI Visibility tables; the reset `crawlerai` database upgrades to its head.
- [x] Application, Compose, test, and documentation database defaults consistently use `crawlerai`; no `crawl_db`, `test_db`, or alternate database name remains.
- [x] Logfire is installed with FastAPI, Celery, and system-metrics support, safely disabled without credentials, and verified against `abhij1306/crawlerai` on the US endpoint without exposing its token.
- [x] Every backend test/tool callable is CC 15 or less.
- [x] Frontend test LOC is measured and ratcheted honestly; included test callables contain no CC>15 findings.
- [ ] Test collection counts and parametrized case IDs for each retained original mega-file are preserved or increased only by explicit new characterization; intentionally deleted AI Visibility tests are recorded separately.
- [x] Shared fixtures live in narrowly named support/conftest owners and do not hide assertions, business logic, or mutable cross-test state.
- [x] Immutable Alembic migrations are explicitly classified and excluded from maintainability LOC only by a narrow path rule; runtime/tool/test source receives no exemption.
- [x] One documented counting method is used by local architecture tests and CI. Backend follows AP-28: nonblank physical lines, not normalized AST output.
- [x] Backend/frontend test/tool CC max 15 and existing lint, format, type, test, architecture, audit, and security checks are blocking; LOC is reported and cannot regress without an explicit ownership rationale.
- [x] No line-count result is achieved through formatting tricks, code packing, generated indirection, excluded-path moves, weakened tests, or arbitrary file shards.
- [ ] Every open GitHub CodeQL alert and bot-associated issue is inspected; valid findings are fixed and verified, and only proven false positives/test-only/unreachable findings are dismissed with an accurate reason and comment.
- [ ] CodeQL remains enabled with its existing query/security coverage, the final CodeQL run is green, and GitHub readback shows no unresolved alert/issue from the starting inventory.
- [ ] Existing full backend pytest remains CI-owned; local work uses focused split files. Frontend unit, policy, build, and required CI are green.
- [ ] `$ship-main` completes with all required CI green.

## Do Not Touch

- Production behavior, public contracts, runtime owners, dependency versions, or feature implementation, except the narrow owner-correct fix required for a validated CodeQL finding.
- Unrelated PostgreSQL databases; reset targets only the explicitly validated `crawlerai` database.
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

### Slice 1: Delete AI Visibility and reset the schema baseline

**Status:** DONE
**Files:** `backend/app/ai_visibility/`, `backend/app/api/ai_visibility.py`, `backend/app/schemas/ai_visibility.py`, `backend/app/models/ai_visibility.py`, `backend/app/core/config/ai_visibility.py`, router/model registrations, AI Visibility tests, `backend/alembic/versions/`, database defaults, `frontend/app/ai-visibility/`, `frontend/lib/api/ai-visibility.ts`, route/query/navigation/policy registrations, canonical docs

**What:** Remove the product surface end to end. Delete backend routes, services, provider adapters/parsers, scoring/export/runtime code, schemas, model exports, and config. Delete frontend route, page components, hook, API client, and dedicated tests; remove all navigation, route-registry, query-key, status, and architecture-policy references. Delete dedicated backend tests and obsolete dead-route expectations. Because the user explicitly authorized a destructive clean-start reset, replace the migration chain with one current-schema baseline that contains no AI Visibility tables. Normalize every application/Compose/test/documentation database default to `crawlerai`, validate the target name, drop and recreate only that database, then upgrade it to the single head. Remove canonical documentation and quality-debt entries made obsolete by deletion. Preserve generic LLM infrastructure unrelated to AI Visibility.

**Verify:** AI Visibility search returns only this plan's historical record; alternate database-name search returns no matches; Alembic reports one head and one migration file; the recreated `crawlerai` database reports that head and contains no AI Visibility tables. Run focused router/model/migration/architecture tests, `vp check --fix`, and `vp build`.

### Slice 2: Complete and verify Logfire observability

**Status:** DONE
**Files:** `backend/pyproject.toml`, `backend/uv.lock`, `backend/app/core/logfire_integration.py`, config/tests, ignored `.logfire` credentials, README only if stable setup guidance changes

**What:** Extend the existing first-party Logfire path with the `system-metrics` extra and one-time system metrics instrumentation. Keep FastAPI and Celery instrumentation, disabled-under-tests behavior, header capture off, argument inspection off, URL-query redaction, and credential-optional startup. Authenticate/select only `abhij1306/crawlerai` at `https://logfire-us.pydantic.dev`, never print or commit a token, and verify the project URL before sending a representative request/span. Do not add browser telemetry or prompt/tool-content capture.

**Verify:** Focused Logfire tests and Ruff pass; CLI `whoami` resolves to the exact target; one representative backend request/span appears in that project with service name `crawlerai-backend`.

### Slice 3: Define honest measurement and baseline collection

**Status:** DONE
**Files:** `backend/tests/unit/test_final_architecture_ownership.py`, `test_extraction_architecture.py`, `frontend/scripts/check-frontend-architecture.mjs`, `frontend/vite.config.ts`, CI workflows, this plan

**What:** Recompute the live repo inventory. Choose and document nonblank physical lines for Python/test LOC per AP-28; keep frontend's existing physical-line policy only if one unified implementation would create drift, and state the distinction. LOC output is a review trend/ratchet, not a forced absolute gate. Use Radon `cc_visit` with explicit `complexity > 15`; do not use Radon grade buckets or `--min C`. Capture baseline pytest collection counts/node IDs for each mega-file and frontend test counts before moving anything. Do not enable blocking gates yet.

**Verify:** Run collection-only commands for the exact target files, existing architecture tests, frontend architecture script, and a report-only scan. Store counts in Notes, not generated repository artifacts.

### Slice 4: Split acquisition, crawl, and browser mega-tests

**Status:** DONE
**Files:** `backend/tests/component/test_crawl_fetch_runtime.py`, `test_browser_context.py`, `test_crawl_service.py`, `test_sitemap_resolver.py`, `backend/tests/regression/test_batch_runtime.py`, narrowly named support/conftest modules

**What:** Split by the public owner or behavior under test: HTTP/fetch planning, browser lifecycle/context, crawl dispatch/state, batch concurrency/control, sitemap/category discovery. Keep fixtures near their consumers; share only stable setup vocabulary. Preserve marks, parameter IDs, async fixtures, monkeypatch scope, and test order independence.

**Verify:** Run pytest collection before/after for these files, then focused pytest on all resulting modules. Counts and case IDs must reconcile.

### Slice 5: Split extraction and persistence mega-tests

**Status:** DONE
**Files:** `backend/tests/unit/test_extraction_contract_behavior.py`, `test_extraction_js_state_behavior.py`, `test_extraction_runtime_behavior.py`, `test_extraction_integrity_behavior.py`, `test_extraction_variant_behavior.py`, `test_extraction_asset_behavior.py`, `test_evaluation_phase4.py`, `test_crawl_run_95_regressions.py`, `backend/tests/component/test_learn_once_persistence.py`, `test_contract_runtime.py`, support modules

**What:** Split by public contracts, collectors, runtime facade, integrity, variants/assets, evaluation gate, and persistence/release behavior. Preserve grounded cases, fixture provenance, test marks, parameter IDs, and assertion strength. Do not reshape production imports to make tests convenient.

**Verify:** Reconcile collection/node IDs and run focused pytest on every resulting module plus extraction architecture tests.

### Slice 6: Split remaining service, public API, harness, and frontend mega-tests

**Status:** DONE
**Files:** `backend/tests/component/test_product_intelligence.py`, `test_public_api.py`, `backend/tests/regression/test_harness_support.py`, `test_data_enrichment.py`, `frontend/components/crawl/crawl-run-screen.test.tsx`, support files

**What:** Split by endpoint/resource or visible behavior: discovery/scoring/review, API auth/extract/batch/domain info, harness parsing/classification/artifacts, enrichment job stages, and crawl-run polling/log/output/action views. Preserve database fixtures, mock boundaries, role/auth cases, fake timers, query clients, and accessibility assertions.

**Verify:** Reconcile backend pytest collection and frontend test names/counts; run all resulting focused pytest and `vp test <path>` files plus `vp check`.

### Slice 7: Clear test/tool CC and classify migrations

**Status:** DONE
**Files:** remaining test/tool CC>15 functions, scanner path rules, architecture docs/tests

**What:** Split multi-behavior test functions into named cases without losing assertions. Extract assertion helpers only when they express a reusable domain expectation. Add a narrow immutable-migration exclusion such as `backend/alembic/versions/**` to maintainability LOC; migrations remain covered by migration-drift/upgrade checks. Do not exempt harness, probes, tests, or runtime code.

**Verify:** Scoped pytest/VitePlus tests pass; CC scanners show zero in-scope test/tool violations, LOC reports show honest before/after movement, and the only structural exclusion is the documented immutable migration path.

### Slice 8: Enable honest blocking quality gates

**Status:** DONE
**Files:** backend architecture tests/config, frontend lint/architecture policy, `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-playwright-smoke.yml`, relevant docs

**What:** Delete cleared `COMPLEX_FUNCTION_DEBT` and raised complexity budgets, then enforce CC ≤15 in blocking CI. Replace raise-only LOC debt with a transparent report plus no-regression ratchet tied to coherent owners; lower/remove line-budget exceptions when real simplification permits, but do not force arbitrary splits or formatting manipulation. Keep tighter existing feature budgets where they remain useful and green. Any LOC increase needs an explicit ownership rationale in the PR, not a silent ceiling raise.

**Verify:** Run focused architecture/policy tests, Ruff check/format, mypy, `vp check`, frontend policy, and `vp build`. Confirm temporary CC and LOC-regression samples fail the correct gates, then remove them. Confirm a large but unchanged cohesive file does not fail merely because of its absolute size. Let CI run full suites.

### Slice 9: Resolve and close open CodeQL findings

**Status:** IN PROGRESS
**Files:** GitHub CodeQL alerts/issues, `.github/workflows/codeql.yml`, narrowly affected production/test owners for validated findings

**What:** Use `npx -y gh-axi` for repository state and `gh-axi api` for the code-scanning alerts endpoint. Snapshot every open alert and any GitHub issue created from CodeQL, including number, rule, severity, path, commit, and state. Triage one finding at a time. Fix valid findings in their canonical owner with focused regression/security tests. Dismiss only when the evidence proves `false_positive`, `used_in_tests`, or a genuinely unreachable/won't-fix case, using the accurate GitHub dismissal reason and a specific comment. Close associated issues only after the alert is fixed/dismissed and read back. Never mass-dismiss, suppress the query, reduce severity, or disable CodeQL to reach zero.

**Verify:** Re-run the CodeQL workflow and wait for completion. Read back the alerts API and issue list. The starting inventory must have no unresolved entries; each closed/dismissed item must have recorded evidence, disposition, and linked fixing commit/PR where applicable.

### Slice 10: Final program reconciliation

**Status:** TODO
**Files:** `docs/ENGINEERING_STRATEGY.md`, `docs/backend-architecture.md`, `docs/frontend-architecture.md`, `docs/CODEBASE_MAP.md`, this plan, `docs/plans/ACTIVE.md`

**What:** Document exact scope/counting/exclusions and focused-test ownership. Confirm the productionization finding register is resolved or explicitly superseded by live evidence. Check all six plan Notes/PRs, remove stale queue entries, and ensure no plan gamed LOC/CC or security measurements.

**Verify:** `git diff --check`; inspect full diff; run the final report-only inventory and record zero violations plus exact commands in Notes.

### Slice 11: `$ship-main`

**Status:** TODO
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local static/build checks, commit/push, open a non-draft PR with exact checks and collection reconciliation, wait for every required CI job, fix failures on the same branch, merge only when green and mergeable, then switch to `main`, pull `--ff-only`, prune safely, and verify local HEAD equals remote `main`.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark this plan `DONE`; update `ACTIVE.md` to `No active plan.`

## Doc Updates Required

- [x] `docs/ENGINEERING_STRATEGY.md` — canonical LOC trend/ratchet, CC gate, anti-gaming rules, and migration exclusion.
- [x] `docs/backend-architecture.md` — split test ownership only if durable guidance belongs there.
- [x] `docs/frontend-architecture.md` — frontend test/policy gate behavior.
- [x] `docs/CODEBASE_MAP.md` — new named support owners if any.
- [x] Remove AI Visibility ownership, route, UI, and behavior references from canonical docs.

## Notes

- Activated 2026-08-23 after the extraction runtime simplification plan was implemented and merged.
- User explicitly added complete AI Visibility deletion before test-suite decomposition.
- User then explicitly authorized resetting/recreating only `crawlerai`, replacing the migration history with one baseline, normalizing all database names to `crawlerai`, and completing Logfire installation for `abhij1306/crawlerai`. This supersedes the earlier immutable-history/forward-removal-migration approach.
- Slice 1 removed 8,061 feature/test/UI lines before the baseline migration squash. Nine backend and three frontend AI Visibility test modules were intentionally deleted with the feature. `crawlerai` was the only database dropped/recreated; it upgraded to sole head `20260703_0001`, Alembic found no schema drift, 25 public tables exist, and zero use the removed prefix. Focused backend verification passed 77 tests; frontend App Shell passed 6 tests; `vp check --fix`, frontend architecture policy, `vp build`, Ruff, and `git diff --check` passed.
- Slice 2 retained the existing safe FastAPI/Celery/crawl-span owner, added `logfire[system-metrics]`, and instruments system metrics once per configured process. CLI credentials and the ignored local token now match `https://logfire-us.pydantic.dev/abhij1306/crawlerai`. Live readback showed `crawlerai-backend`, `GET /health/live`, status 200 at 08:25:40 on 2026-08-23. Header capture and argument inspection remain off; tests still disable export by default.
- Slice 3 live inventory: backend tests are 162 Python files / 53,997 nonblank physical lines; backend root/probe tools are 17 files / 3,625 lines; frontend tests are 38 files / 5,206 nonblank physical lines. Seventeen backend test modules and one frontend test exceed the 800-line review target. Exact `cc_visit` scanning at `complexity > 15` found 16 backend test/tool callables; frontend blocking CC is not yet implemented. Existing backend application architecture tests passed 60 cases; frontend architecture policy and the 36-case crawl-run-screen suite passed.
- Slice 3 retained-case baseline totals 875 backend cases across the 19 named files plus 36 frontend cases. Case-name/parameter-ID SHA-256 fingerprints: crawl fetch `7ff6b483ac8a369c5b7a00582530421f7b9400c36ca942cd3d08eeeb4d4477bd` (99); browser context `33ab28813df1589c9ce7263764ae205fe85ed37ee5d2104ee4ff4c8b48824077` (92); crawl service `2e3680645d45cb5e266f79330290a8c99820f451ce116b3151b420f40aaa2a22` (40); sitemap `e6e1bb71a2c792b6449b337c5cc076e338df6e90307a2ed4ffaff5fadae5ec23` (25); batch `a3cb7afae38ecce22bdeeb5c754836b4ed0bdbd94b2eea8b87857510a11adffd` (39); extraction contract `024b855646e49301d806271fd2d621426a455bc5d0bfa2665c0cf5f826bce253` (72); JS state `c4115bab91db73f816cec29b5efe2fb84da261a2c2b24ca84cc05ce505995554` (37); extraction runtime `c0fb4f8e6223a2efaf12a5f7d17a39cd246d91832641b497aa49ef3a6d2c82ff` (40); integrity `eddab5891e22615a57fd37ec8691b399396829155932a2368ceb0b255e7f83cc` (64); variants `28169a5e003b138112299c64b4f84717312892ba25b4d52aac49f88471101d4f` (29); assets `2a24f7c34f02c03183a691fa09eb71e108dc2983d51059288945682a6643ee8f` (31); evaluation `3cfcbaf44bd8e0da144477d83d3851433e25e943206305ea1c131e5d87d65dd7` (23); run-95 `56ccf468f5aa0157712cb8bf8c57fd4d0d1c4563dbe370f06b6c6c8359c399e7` (22); learn-once `8a80736d3c6819d85f793ace8bc7277c59bf713fa0ec58f6d807f7637f0c4ee2` (17); contract runtime `73f30e4f4df946251db74376db3457a7672c4a745288aa2f38a208e4dbc2aed3` (27); product intelligence `0abdf61bde872bbbafe29ab9a1e16532f38ccf9a96951a8c1d6c923ceaec761c` (103); public API `d84125747b370aeea2a74345c8d9c8c54891f7cd8ae6f69edd3ea142b1ef7130` (37); harness `a73f6a0359f2cb5c0177f62ed7a5b60c2370d0c911be7a149ff8d69822d3f608` (45); enrichment `69aad459b2c6b31fab93481312203680e7f7b2d7136de3c07f378b3b67e7738d` (33); frontend crawl-run screen `a5eebb14ac71012052dd1fe8271f71d4a5c10fae1e58900f00eee41dfe773319` (36).
- Slice 4 replaced five 806–3,720-line mega-modules with 27 behavior-named test owners and five setup-only support owners. All resulting files are at most 730 nonblank lines. The split adds 537 honest import/support lines while removing no case or assertion. All five baseline fingerprints match exactly (295 cases). Focused execution passed 293 unchanged cases on the first run; the two control-request parameters exposed their pre-existing timing margin on the now-clean local database, so their in-flight fake wait increased from 0.2s to 1.0s without changing assertions; the complete 11-case owner then passed. Ruff, 33 application architecture tests, and `git diff --check` pass.
- Slice 5 replaced ten 698–1,639-line extraction/evaluation/persistence modules with 24 behavior test owners and six narrow support owners. The canonical `extraction_pipeline_test_support.py` remains the single shared extraction vocabulary; redundant generated wrappers were deleted. Largest resulting file is 724 nonblank lines. Honest support/import overhead is 413 lines (10,139→10,552) with no assertion/case removal. All ten baseline fingerprints match exactly and all 362 cases pass. Ruff, 60 extraction/application architecture tests, and `git diff --check` pass.
- Slice 6 replaced four 926–3,213-line backend mega-modules with 22 behavior test owners and four setup-only support owners. Backend nonblank lines moved 5,922→5,986; the largest owner is 481 lines. All 218 case names and parameter IDs match the four baseline sets, and all 218 focused cases pass. The 1,264-line crawl-run screen suite became five visible-behavior owners plus one mock/lifecycle support owner (1,361 total nonblank lines, largest behavior owner 421); all 36 named cases pass sequentially. A single parallel invocation produced five unchanged 5-second timeouts under concurrent transform load, while each affected owner passed alone. `vp check --fix` passes with no lint or type errors.
- Slice 7 reduced the live backend test/tool Radon inventory from 16 baseline violations (14 after feature deletion/file moves) to zero at exact `complexity > 15`, including the browser-surface probe's CC 78 `build_findings` and CC 26 target classifier. Probe behavior stayed green (20 cases); 49 focused changed-owner tests and 63 architecture tests pass. Immutable migrations are the only maintainability-LOC exclusion and remain covered by Alembic drift/upgrade checks.
- Slice 8 added blocking backend test/tool CC 15 and exact nonblank LOC ratchets (tests 55,204; root/browser-probe tools 3,723), frontend test complexity 15 and nonblank LOC ratchet (4,642), full-backend Ruff CI scope, and frontend lint/type/policy CI before build. Backend Ruff, mypy (362 files), 63 architecture tests, and Alembic check pass. Frontend `vp check`, all architecture policies, and production build pass. CI database service names now use canonical `crawlerai` in both workflows.
- Slice 9 starting inventory was 33 open CodeQL alerts and zero associated open issues. Fourteen import-cycle instances were individually dismissed as false positives after confirming their return edges are `TYPE_CHECKING`-only or confined to the documented call-time `resolve_browser_pool()` import. Two resolution facade import-style guards and two compatibility test seams were individually classified with `used in tests`; one asyncio `await` alert was dismissed as a false positive because it joins cleanup. Five duplicate-import test findings and the unnecessary-delete finding were fixed locally. Nine remaining stale alerts point to those fixes, already-deleted AI Visibility/old split-test paths, or current explicit compatibility exports and await the new default-branch CodeQL analysis.
- Local backend full-suite execution remains prohibited by AGENTS.md. Required full-suite evidence comes from CI during `$ship-main`.
