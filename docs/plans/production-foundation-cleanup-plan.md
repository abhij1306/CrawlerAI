# Plan: Production Foundation and Cleanup

**Created:** 2026-08-22
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** repository instructions, dependency locks, CI workflows, extraction/LLM/fetch dead code, quality-tool configuration, local runtime/bootstrap, auth shell, database and cache setup

## Goal

Make the production and local-development baseline reproducible, current, green, and easy to start while deleting confirmed waste. Use locked audited dependencies, deterministic CI, explicit runtime ports, reusable local Redis, a rebuilt local database/environment, and one verified `start.bat` path that launches API, Celery, and frontend. Keep crawl behavior stable while completing the requested account-session shell with login/logout controls.

This plan covers Q-CI-LOCK, Q-CI-FE-AUDIT, Q-CI-PYJWT, Q-CI-BE-FMT, Q-CI-FE-CHECK, Q-CI-FE-UNIT, Q-DEP-BE-01, Q-DEP-FE-01 through Q-DEP-FE-03, Q-DEAD-01 through Q-DEAD-04, Q-DUP-01, Q-PYLINT-AP22, and Q-DOC-NEXT from the evidence report.

## Acceptance Criteria

- [x] Backend CI installs exactly `backend/uv.lock` with the dev extra and audits that resolved environment.
- [x] The unexplained `PYSEC-2025-183` ignore is removed unless the locked graph newly proves it is required and the reason is documented.
- [x] The `cryptography` fixed release is admitted with focused Fernet, JWT, cookie, and configuration tests passing.
- [x] `vp pm audit -- --audit-level=high` exits 0 after the compatible frontend dependency refresh.
- [x] Every open PR is reviewed with `gh-axi`; only clearly superseded, duplicate, abandoned automation, or obsolete/conflicting PRs are closed, each with an explanatory comment and readback confirmation.
- [x] Active human work and any PR containing unique unmerged changes remain open.
- [x] Backend format checking and frontend `vp check` plus unit tests are blocking CI steps.
- [x] Confirmed callerless wrappers/helpers are deleted; the test-only browser context wrapper is either folded into the production spec owner or retained with a documented contract reason.
- [x] Exact JS-state/metadata helper clones are consolidated only where inputs, outputs, and error behavior match.
- [x] Dormant Pylint size/complexity configuration is removed if no committed caller uses Pylint; no second lint stack is added.
- [x] `AGENTS.md` identifies the frontend as React + Vite+, not Next.js.
- [x] Focused backend pytest and VitePlus verification exits 0.
- [x] PRs #42, #43, and #51 are reviewed, resolved by explicit apply/discard decisions, closed with comments, and read back closed.
- [x] All direct and locked backend/frontend dependencies and GitHub Actions are updated to the newest compatible verified releases; unused-dependency audits are clean or every exception is documented.
- [x] Local backend `.venv`, frontend installation, and bounded project cache directories are rebuilt from locks; the CrawlerAI database is reset and migrated without touching unrelated databases.
- [x] Local runtime uses backend port 8001 and frontend port 3001 consistently across config, scripts, tests, docs, health checks, and browser URLs.
- [x] `start.bat` launches the backend API, Redis-backed Celery workers, and frontend successfully with Redis/Celery enabled, reusing a healthy compatible Redis endpoint when available.
- [x] The app shell shows the active account and logout control in the bottom sidebar area while preserving the top-bar theme toggle and current single-account scope.
- [ ] Required GitHub CI is green and the PR is merged through `$ship-main`.

## Do Not Touch

- Extraction precedence, evidence resolution, publication projections, or retry policy — this plan removes unreachable code only.
- Frontend framework and router architecture — dependency updates may cross majors only when the live package manager reports them and focused compatibility checks pass; do not redesign routing.
- Extraction, crawl, persistence, queue, or retry semantics — startup and dependency work must not change domain behavior.
- Unrelated databases, Docker volumes, containers, or user files — reset only resolved CrawlerAI targets; reuse compatible shared Redis without taking ownership of unrelated container lifecycle.
- Broad formatting churn unrelated to changed files.
- Repository-wide LOC trend/ratchet and CC enforcement — owned by the final quality-guardrails plan.
- Active or ambiguous pull requests — age alone is not proof of staleness.

## Simplification Guardrails

- LOC is a diagnostic and a simplification goal, not a hard success condition. Prefer a cohesive 850-line owner over two arbitrary files with worse navigation.
- Never lower measured LOC by deleting useful blank lines, comments, docstrings, type annotations, or tests; combining statements; minifying or compressing expressions; abusing generated code; changing file extensions; or moving code into excluded/unscanned paths.
- Never hide complexity with dynamic dispatch, reflection, metaprogramming, configuration blobs, compatibility wrappers, pass-through helpers, or tiny functions that only move branches elsewhere.
- A split must create a clear domain owner, remove duplication, flatten control flow, or improve testability. If it does not reduce cognitive load, do not keep it.
- Judge success by simpler behavior-preserving code, fewer responsibilities and branches, deleted waste, direct imports, and clearer tests. Record LOC/CC movement as evidence, not as the design objective.
- Do not weaken checks, tests, audit thresholds, or PR review criteria to manufacture a green result.

## Slices

### Slice 1: Update dependencies and close stale PRs

**Status:** DONE
**Files:** `backend/pyproject.toml`, `backend/uv.lock`, `frontend/package.json`, frontend lockfile, open GitHub pull requests

**What:** Use `npx -y gh-axi` and `pr list/view/checks` to inventory open PRs before changing dependencies. Classify a PR as stale only with concrete evidence: its change is already on `main`, a newer PR supersedes it, it is a duplicate/outdated bot upgrade, or it cannot merge and contains no unique work. Close qualifying PRs one at a time with a concise reason, then read them back; do not close active or ambiguous human work. Re-run backend and frontend dependency audits/outdated reports. Admit the smallest fixed `cryptography` release and minimal compatible frontend fixes for `react-router-dom`, `undici`, and `nanoid`. Do not bundle unrelated majors or broad maintenance updates.

**Verify:** Re-run `gh-axi pr list` and record each closure/reason plus remaining active PRs. From `backend`, sync the updated lock and run security/auth tests plus the locked audit. From `frontend`, run the high audit, `vp check`, focused affected tests, and `vp build`.

### Slice 2: Reconfirm the live baseline and delete dead code

**Status:** DONE
**Files:** `backend/app/extraction/pipeline.py`, `backend/app/connectors/llm/prompt_rendering.py`, `backend/app/acquisition/fetch/browser_policy.py`, `backend/app/acquisition/fetch/fetch_context.py`, `backend/app/acquisition/browser_identity.py`, direct focused tests

**What:** Re-run repository-wide reference searches for `collect_ecommerce_detail`, `parse_json_ld`, `harvest_js_state_objects`, `extend_browser_engine_attempts_after_block`, and `build_playwright_context_options`. Delete the first three findings only if still callerless. Keep the fetch-context implementation as the sole block-extension owner. For the browser context wrapper, compare its observable result with `build_playwright_context_spec`; fold tests into the production owner only if behavior is equivalent. Preserve existing tests unless they only assert a deleted private implementation.

**Verify:** From `backend`, run focused pytest for extraction pipeline behavior, LLM prompt rendering, fetch behavior, and `tests/component/test_browser_context.py`; run `rg` again and confirm no unintended references or dead imports remain.

### Slice 3: Consolidate proven clones and remove decorative tooling

**Status:** DONE
**Files:** `backend/app/extraction/collectors/js_state.py`, `backend/app/extraction/collectors/metadata.py`, the existing nearest shared owner, `backend/pyproject.toml`, `AGENTS.md`

**What:** Compare the jscpd-reported collector clones semantically. Move only truly identical parsing/walking behavior to the existing `_helpers.py` or `json_walk.py` owner; do not create a generic utilities layer. Confirm Pylint has no workflow/script caller, then delete its unused dependency/config rather than enabling a redundant lint stack. Correct the frontend stack statement in `AGENTS.md`.

**Verify:** From `backend`, run the affected collector tests, `uvx --from ruff==0.15.22 ruff check app tests`, and `uvx --from vulture==2.16 vulture app --min-confidence 100 --exclude .venv` with any known framework false positive explicitly accounted for.

### Slice 4: Make CI deterministic and enforce existing checks

**Status:** DONE
**Files:** `.github/workflows/backend-ci.yml`, `.github/workflows/frontend-playwright-smoke.yml`, dependency files changed in Slice 1

**What:** Replace ad hoc backend `pip install -e ".[dev]"` resolution with `uv sync --frozen --extra dev`. Audit the locked environment and remove the stale PyJWT ignore unless current locked evidence requires it. Add Ruff format checking with the locked Ruff version. Add `vp check` and `vp test` before frontend build/e2e. Keep existing Playwright smoke and bundle-budget behavior.

**Verify:** From `backend`, run frozen sync, focused security/auth tests, locked Ruff check/format, and locked-environment audit. From `frontend`, run the high audit, `vp check`, focused tests, and `vp build`.

### Slice 5: Reconcile docs and review the complete diff

**Status:** DONE
**Files:** `docs/backend-architecture.md`, `docs/frontend-architecture.md`, `docs/CODEBASE_MAP.md` only if ownership changed, this plan, `docs/plans/ACTIVE.md`

**What:** Document only durable CI/toolchain or ownership changes. Record exact package/audit decisions and verification in Notes. Confirm net code/config complexity decreased, no compatibility shim was added, no unrelated lock upgrades slipped in, and all acceptance criteria are checked.

**Verify:** `git diff --check`; inspect the full diff and dependency-lock delta; confirm the plan has no unchecked acceptance criterion except shipping.

### Slice 6: Reconcile and close superseded pull requests

**Status:** DONE
**Files:** GitHub PRs #42, #43, #51 and current PR #57 notes

**What:** Review each PR diff against current main and the current branch. Apply useful changes into #57 or document why they are discarded. Comment and close each requested PR, then read back its closed state.

**Verify:** `gh-axi pr view 42`, `43`, and `51` all report closed; plan Notes record the apply/discard decision.

### Slice 7: Refresh and audit all dependencies

**Status:** DONE
**Files:** backend and frontend manifests/locks, GitHub Actions workflows, dependency-audit configuration

**What:** Inventory direct and transitive outdated packages, update all compatible dependencies, evaluate every direct major individually, update action versions, and run unused-dependency audits. Remove unused direct packages only with repository-wide import/script evidence. Keep reproducible locks.

**Verify:** backend lock/sync/audit plus focused security/runtime tests; frontend install/audit/check/test/build; unused audit reports clean or documented framework/tooling exceptions.

### Slice 8: Normalize ports and startup ownership

**Status:** DONE
**Files:** `start.bat`, `.env`/example config, Vite and backend runtime config, Docker/health/test/docs references

**What:** Make 8001 the backend port and 3001 the frontend port everywhere that represents the local app contract. Audit and simplify `start.bat` so it validates prerequisites and starts API, Celery, and frontend with Redis/Celery enabled. Reuse an already-running compatible Redis endpoint when safe.

**Verify:** reference scan finds no stale local 8000/3000 contracts; launched API/frontend health checks succeed on 8001/3001 and Celery reports a live Redis-backed worker.

### Slice 9: Rebuild local installations and database

**Status:** DONE
**Files:** exact local `.venv`, `frontend/node_modules`, project cache directories, resolved CrawlerAI PostgreSQL database/schema

**What:** Resolve exact targets, stop only project-owned processes, delete bounded caches/installations, rebuild from committed locks, reset only the CrawlerAI database, and apply migrations. Do not delete source artifacts or unrelated Docker volumes/containers.

**Verify:** fresh frozen backend sync, fresh frontend install, migration head/current equality, database health, and clean dependency audits.

### Slice 10: Add account session control

**Status:** DONE
**Files:** frontend app shell/sidebar/auth owners and focused tests

**What:** Replace the bottom sidebar utility area with a compact account section that preserves theme control and provides login state plus logout. Reuse existing auth/session API and routing; do not add account switching.

**Verify:** focused shell/auth tests cover logged-in display, logout mutation/session clearing, login navigation, and theme control; `vp check` passes.

### Slice 11: Final runtime and documentation reconciliation

**Status:** DONE
**Files:** architecture/setup docs, this plan, changed config/scripts

**What:** Run the app through `start.bat`, verify API/frontend/Redis/Celery and logout behavior, inspect full dependency and code diffs, and record the exact rebuilt resources and retained unrelated resources.

**Verify:** focused backend/frontend checks, dependency and unused audits, `git diff --check`, live health checks, and complete acceptance checklist except shipping.

### Slice 12: `$ship-main`

**Status:** IN PROGRESS
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Inspect branch, worktree, remotes, and upstream; preserve unrelated files. Create a feature branch if needed, run only the focused static/build checks above locally, commit and push, open a non-draft PR with exact checks, wait for every required CI job, fix failures on the same branch, merge only when green and mergeable, then switch to `main`, pull `--ff-only`, prune the merged local branch when safe, and verify local HEAD equals remote `main`.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and intentionally retained untracked files in Notes. Mark this plan `DONE`, then point `docs/plans/ACTIVE.md` to the next queued plan.

## Doc Updates Required

- [x] `AGENTS.md` — correct frontend stack.
- [x] `docs/backend-architecture.md` — locked CI/audit behavior if durable architecture guidance changes.
- [x] `docs/frontend-architecture.md` — CI/toolchain behavior if changed.
- [x] `docs/CODEBASE_MAP.md` — no update required; no shared helper owner moved.

## Notes

- Evidence baseline: report commit `bfc76636`; live planning checkout was `7ea5a61d` on 2026-08-22. Re-run audits and GitHub state because advisories, lock resolution, and PR status are time-sensitive.
- The code-simplification rule applies: delete or consolidate only when behavior boundaries are known; do not optimize for line count alone.
- Live dependency state already contained the planned minimal fixes: `cryptography==50.0.0`, `react-router-dom==7.18.2`, `undici==8.10.0`, and `nanoid==3.3.18`. Backend OSV audit and frontend high audit both report no known vulnerabilities, so no unrelated runtime dependency changed. `pip-audit==2.10.1` replaced unused Pylint in the locked dev extra so CI audits the exact frozen environment.
- Scope expanded by the user on 2026-08-23 after PR #57 opened. Shipping paused. New work covers full compatible dependency refresh, unused-dependency audit, local environment/database rebuild, cache cleanup, 8001/3001 ports, verified Redis/Celery startup, and sidebar login/logout controls.
- PR #51 was discarded because current CodeQL is green and its test-only private wildcard exports required raising the test LOC budget. PR #43 was discarded because its exact CodeQL 4.37.3 pin is stale while the maintained v4 line is green. PR #42 was closed as superseded; its setup-python major update is now owned by #57. All three received explanatory comments and closed-state readback.
- `collect_ecommerce_detail` and the reported JS-state/metadata clones were already removed/consolidated by the completed extraction-runtime work on the live base. Current focused jscpd reports zero exact clones between `js_state.py` and `metadata.py`. This slice deleted callerless `parse_json_ld`, `harvest_js_state_objects`, and `browser_policy.extend_browser_engine_attempts_after_block`; fetch-context remains the sole block-extension owner. Browser context tests now call `build_playwright_context_spec` directly and the test-only dictionary wrapper is gone.
- No committed workflow or script invoked Pylint. Its dependency, configuration, transitive-only packages, and stale inline directives were removed. Ruff remains the single lint/format owner. Vulture's sole 100% finding is Pydantic's required `model_post_init(self, __context)` framework parameter in `persistence/export/schema.py`; it is not dead code.
- The frontend unit suite initially exposed CPU contention from unrestricted `vmThreads` workers. `maxWorkers: 4` makes the existing assertions and timeouts deterministic without weakening them; exact `vp test` then passed all 221 tests.
- Initial GitHub CI failed before dependency installation because the advertised `astral-sh/setup-uv@v9` tag was not resolvable. The final refresh pins the official v10.0.1 commit SHA and uv 0.12.5; the same PR is being reverified.
- Local verification: frozen backend sync and audit; locked Ruff check and format over 631 files; 49 collector tests, 27 security/config/LLM tests, 49 fetch/context tests (one timing-sensitive case reconfirmed alone), 14 auth/logout tests, and 77 extraction/browser-context tests; frontend `vp check`, 221 unit tests, build, and high audit. One fetch timeout-budget case failed only during concurrent local test processes and passed immediately alone. CI owns the full backend suite.
- Dependency refresh now pins current GitHub Action SHAs, uv 0.12.5, pnpm 11.23.0, and react-hook-form 7.86.0. Backend direct imports now declare Pydantic and OpenTelemetry explicitly. Deptry and Knip report no unexplained dependency issues; OSV and pnpm audits report no known vulnerabilities. Redis client 6.4.0 remains the newest Celery-compatible release because Celery 5.6.3 constrains Redis below 6.5. Vite+ intentionally supplies its aliased Vite core.
- Local installations were deleted and rebuilt from `uv.lock` and `pnpm-lock.yaml`. Generated project cache/build directories were bounded to the workspace. CrawlerAI now owns `crawlerai-db-1` on host port 5433; its fresh schema contains 25 tables at revision `20260703_0001`. No unrelated database or volume was reset. A compatible Redis endpoint on localhost:6379 is reused through isolated logical DB 1.
- Local API/UI contracts are 8001/3001 across runtime config, Docker, CI, Playwright, tests, and docs. `start.bat` validates installs, reuses healthy dependencies or starts missing CrawlerAI Docker services, migrates the database, and starts two uniquely named Celery workers without killing browser processes from other projects.
- Live `start.bat` verification passed: backend and frontend returned 200; both Celery workers returned `pong`; CrawlerAI bootstrapped one admin; live login/session/logout returned 200/200/204 and the post-logout session check returned 401. Repository-wide case-insensitive search reports zero references to the superseded product name.
