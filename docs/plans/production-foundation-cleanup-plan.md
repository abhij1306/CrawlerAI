# Plan: Production Foundation and Cleanup

**Created:** 2026-08-22
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** repository instructions, dependency locks, CI workflows, extraction/LLM/fetch dead code, quality-tool configuration

## Goal

Make the production baseline reproducible and green while deleting confirmed waste. Start by updating vulnerable/outdated dependencies in controlled batches and closing only demonstrably stale GitHub PRs. Then use the locked backend environment in CI, add already-supported format/check/unit gates, remove callerless code and exact duplication, and correct stale tooling documentation. Keep dependency changes minimal and preserve runtime behavior.

This plan covers Q-CI-LOCK, Q-CI-FE-AUDIT, Q-CI-PYJWT, Q-CI-BE-FMT, Q-CI-FE-CHECK, Q-CI-FE-UNIT, Q-DEP-BE-01, Q-DEP-FE-01 through Q-DEP-FE-03, Q-DEAD-01 through Q-DEAD-04, Q-DUP-01, Q-PYLINT-AP22, and Q-DOC-NEXT from the evidence report.

## Acceptance Criteria

- [x] Backend CI installs exactly `backend/uv.lock` with the dev extra and audits that resolved environment.
- [x] The unexplained `PYSEC-2025-183` ignore is removed unless the locked graph newly proves it is required and the reason is documented.
- [x] The `cryptography` fixed release is admitted with focused Fernet, JWT, cookie, and configuration tests passing.
- [x] `vp pm audit -- --audit-level=high` exits 0 after the smallest compatible frontend dependency/override change; unrelated majors are not bundled.
- [x] Every open PR is reviewed with `gh-axi`; only clearly superseded, duplicate, abandoned automation, or obsolete/conflicting PRs are closed, each with an explanatory comment and readback confirmation.
- [x] Active human work and any PR containing unique unmerged changes remain open.
- [x] Backend format checking and frontend `vp check` plus unit tests are blocking CI steps.
- [x] Confirmed callerless wrappers/helpers are deleted; the test-only browser context wrapper is either folded into the production spec owner or retained with a documented contract reason.
- [x] Exact JS-state/metadata helper clones are consolidated only where inputs, outputs, and error behavior match.
- [x] Dormant Pylint size/complexity configuration is removed if no committed caller uses Pylint; no second lint stack is added.
- [x] `AGENTS.md` identifies the frontend as React + Vite+, not Next.js.
- [x] Focused backend pytest and VitePlus verification exits 0.
- [ ] Required GitHub CI is green and the PR is merged through `$ship-main`.

## Do Not Touch

- Extraction precedence, evidence resolution, publication projections, or retry policy — this plan removes unreachable code only.
- Frontend framework, router architecture, or UI behavior — dependency remediation is minimal and compatibility-focused.
- `@testing-library/jest-dom`, `jsdom`, `@types/node`, `lucide-react`, TypeScript, or Vite+ major upgrades unless a high advisory cannot be fixed without one; if so, stop and make a separate plan.
- Broad dependency refreshes or formatting churn unrelated to changed files.
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

### Slice 6: `$ship-main`

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
- `gh-axi` review on 2026-08-23 found PRs #51, #43, and #42 open. #51 retains unique human-authored CodeQL test-support work. #43 and #42 retain still-applicable GitHub Action upgrades. None met the plan's proof threshold for closure, so all remain open.
- `collect_ecommerce_detail` and the reported JS-state/metadata clones were already removed/consolidated by the completed extraction-runtime work on the live base. Current focused jscpd reports zero exact clones between `js_state.py` and `metadata.py`. This slice deleted callerless `parse_json_ld`, `harvest_js_state_objects`, and `browser_policy.extend_browser_engine_attempts_after_block`; fetch-context remains the sole block-extension owner. Browser context tests now call `build_playwright_context_spec` directly and the test-only dictionary wrapper is gone.
- No committed workflow or script invoked Pylint. Its dependency, configuration, transitive-only packages, and stale inline directives were removed. Ruff remains the single lint/format owner. Vulture's sole 100% finding is Pydantic's required `model_post_init(self, __context)` framework parameter in `persistence/export/schema.py`; it is not dead code.
- The frontend unit suite initially exposed CPU contention from unrestricted `vmThreads` workers. `maxWorkers: 4` makes the existing assertions and timeouts deterministic without weakening them; exact `vp test` then passed all 221 tests.
- Local verification: frozen backend sync and audit; locked Ruff check and format over 631 files; 49 collector tests, 27 security/config/LLM tests, 49 fetch/context tests (one timing-sensitive case reconfirmed alone), 14 auth/logout tests, and 77 extraction/browser-context tests; frontend `vp check`, 221 unit tests, build, and high audit. One fetch timeout-budget case failed only during concurrent local test processes and passed immediately alone. CI owns the full backend suite.
