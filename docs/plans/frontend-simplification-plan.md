# Plan: Frontend Simplification

**Created:** 2026-08-22
**Agent:** Codex
**Status:** DONE
**Touches buckets:** crawl terminal/workspace, API contract types, data enrichment, product intelligence, domain memory, UI primitives, frontend architecture policy

## Goal

Reduce the oversized frontend production owners and every frontend callable above complexity 15 while preserving rendered behavior, accessibility, request payloads, server-state ownership, polling, route/search state, and component contracts. Use existing hooks/components/domain API modules; do not redesign the UI.

This plan owns Q-LOC-27, Q-LOC-35, Q-FE-ARCH-800, Q-CC-FE-01 through Q-CC-FE-08, and any additional live frontend CC>15 findings discovered when the committed max-15 rule is evaluated.

## Acceptance Criteria

- [x] `components/crawl/log-terminal.tsx` and `lib/api/types.ts` materially shrink through clearer ownership; 800 physical lines is a review target, not a forced split.
- [x] Oxlint complexity max 15 passes across frontend production `.ts/.tsx` sources.
- [x] Log grouping, coverage, expansion, filtering, scrolling, terminal reconciliation, and accessibility behavior is preserved.
- [x] API types are owned by existing domain API modules without duplicate declarations, circular imports, runtime additions, or wire-contract changes.
- [x] Data Enrichment, Crawl Run, Product Intelligence, Domain Memory, run summary/config dispatch, and dropdown behavior remain equivalent.
- [x] Server state remains in React Query, URL state remains in search params, and temporary view state remains local; no synchronized duplicate state is introduced.
- [x] Existing tests remain semantically intact; new characterization covers only previously unprotected branches.
- [x] `vp check`, focused `vp test` files, architecture policy, `vp build`, and `$ship-main` CI pass.

## Do Not Touch

- Visual redesign, CSS/theme tokens, route map, backend API semantics, dependency upgrades, or broad component rewrites.
- Playwright test architecture or the mega `crawl-run-screen.test.tsx` split; the final test-suite plan owns test decomposition.
- New state libraries, component frameworks, generic hooks, or index-barrel compatibility exports.
- Changes to user-visible labels or workflow unless needed to preserve existing behavior after extraction.

## Simplification Guardrails

- LOC is a diagnostic goal, not a hard acceptance gate. Keep a cohesive component/type owner when extraction would worsen discoverability.
- Do not reduce lines by deleting useful whitespace/comments/types/tests, compressing JSX, combining statements, nesting ternaries, minifying objects, generating code, or moving code to ignored/unscanned paths.
- Do not hide complexity in custom hooks, memo callbacks, schema/config blobs, dynamic component maps, barrels, or one-use helpers. State and branching must become simpler.
- Extract only stable UI responsibilities: pure derivation, stateful effects, domain API contracts, or presentational sections. Avoid file-per-component fragmentation.
- Preserve accessible, readable JSX even when it uses more lines. Smaller rendered source with worse clarity is failure.
- Never weaken lint, accessibility rules, architecture policy, tests, or type precision to improve metrics.

## Slices

### Slice 1: Establish the live frontend behavior and complexity inventory

**Status:** DONE
**Files:** `frontend/vite.config.ts`, architecture script, named production files and direct tests, this plan

**What:** Add/evaluate the Oxlint `complexity: ['error', 15]` rule in a temporary or working branch state to obtain the full 16–20 inventory; the report only verified eight functions above 20. Map each finding to an existing owner/hook. Capture direct tests for state, payload, rendering, keyboard/accessibility, and polling behavior before edits.

**Verify:** Run `vp check`, the relevant focused `vp test <path>` commands, and `node scripts/check-frontend-architecture.mjs`; record baseline violations in Notes.

### Slice 2: Thin the crawl log terminal and workspace

**Status:** DONE
**Files:** `frontend/components/crawl/log-terminal.tsx`, `log-terminal-utils.ts`, `use-log-terminal-state.ts`, existing terminal/workspace components/hooks, focused tests

**What:** Move pure grouping, coverage, filtering, and row-view derivation to the existing utility owner. Move stateful effects/actions to the existing terminal hook. Use existing presentational components for rendering sections. Keep `LogTerminal` as composition and preserve stable keys, scroll/expansion behavior, ARIA, and diagnostic output. Simplify `CrawlRunWorkspace` through existing workspace hooks/components rather than adding a new controller.

**Verify:** Run `vp test components/crawl/log-terminal-utils.test.ts components/crawl/log-terminal.test.tsx components/crawl/run-terminal-shell.test.tsx components/crawl/crawl-run-screen.test.tsx` and `vp check`; measure LOC/CC.

### Slice 3: Split API types by domain owner

**Status:** DONE
**Files:** `frontend/lib/api/types.ts`, existing `lib/api/crawls.ts`, `records` owner if present or closest domain owner, `jobs.ts`, `data-enrichment.ts`, `product-intelligence.ts`, `domain-memory.ts`, schemas/tests

**What:** Move domain-specific DTOs next to their API methods. Keep only genuinely shared transport/cross-domain contracts in `types.ts`. Update all imports directly and delete duplicate/re-export compatibility paths. Preserve type names and wire shapes at call sites; type-only moves must not change runtime bundles.

**Verify:** Run `vp check`, `vp test lib/check-crawl-architecture.test.ts` plus affected API/feature tests, architecture policy, and `vp build`. Confirm `types.ts` materially simplifies and no cycle/barrel appears; document a cohesive reason if it remains above the LOC target.

### Slice 4: Reduce page, hook, and primitive complexity

**Status:** DONE
**Files:** `app/data-enrichment/page-view.tsx`, `components/crawl/run-summary.tsx`, `crawl-config-logic.ts`, `crawl-run-screen.tsx`, `components/ui/dropdown.tsx`, `app/product-intelligence/use-product-intelligence.ts`, `components/domain-memory/knowledge-graph-tab.tsx`, plus all live CC16–20 owners

**What:** Delegate to existing reducers/hooks/selectors/components. Replace optional-payload ladders with typed field maps where ordering and omission semantics remain explicit. Split derived selectors by metric family. Separate polling/create/review concerns using existing Product Intelligence owners. Extract dropdown positioning predicates without altering interaction. Do not move complexity into JSX callbacks or clever expressions.

**Verify:** Run each owner's focused tests, `vp check`, and the committed max-15 lint. Test payload equality, route/search state, query invalidation, keyboard interaction, and accessibility where relevant.

### Slice 5: Tighten frontend policy and reconcile docs

**Status:** DONE
**Files:** `frontend/vite.config.ts`, `scripts/check-frontend-architecture.mjs`, `docs/frontend-architecture.md`, this plan

**What:** Commit the max-15 complexity rule only after zero violations. Lower cleared `log-terminal.tsx` and `types.ts` line budgets to honest measured headroom; do not force a split or manipulate formatting solely to remove an exception. Update architecture docs for moved type/component ownership. Inspect production and test bundle behavior.

**Verify:** Run `vp check`, focused tests, `node scripts/check-frontend-architecture.mjs`, `vp build`, and `git diff --check`; inspect the complete diff and final inventory.

### Slice 6: `$ship-main`

**Status:** DONE
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local checks, commit/push, open a non-draft PR, wait for all required CI, fix failures on the same branch, merge only when green/mergeable, then synchronize local `main` and verify it equals remote.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark `DONE` and advance `ACTIVE.md`.

## Doc Updates Required

- [x] `docs/frontend-architecture.md` — final component/hook/type ownership.
- [ ] `docs/CODEBASE_MAP.md` — only if the mapped frontend API owner list changes.

## Notes

- Physical LOC is retained as trend/ratchet evidence for the existing frontend architecture script. It is not permission to trade readability for a smaller count.
- 2026-08-23 baseline correction: the committed max-15 rule covered test files only. The production rule was added during Slice 4 before taking the live production inventory.
- 2026-08-23 baseline: `log-terminal.tsx` was 972 physical lines, `lib/api/types.ts` was 831, and the frontend architecture gate passed with budgets of 1020 and 875 respectively.
- 2026-08-23 baseline: terminal, workspace, and crawl-architecture focused tests passed (4 files, 14 tests). The requested `run-terminal-shell.test.tsx` path is not a collected test file in the live tree.
- 2026-08-23 Slice 2: moved terminal metrics, coverage, confidence, duration, expanded-row, summary, payload, and URL-label derivation into `log-terminal-display.ts`; `log-terminal.tsx` fell from 972 to 716 physical lines. `CrawlRunWorkspace` already delegates data, actions, polling, selection, and rendering to named owners, so no extra controller was added. `vp check`, three collected focused files (9 tests), architecture policy, and `git diff --check` passed.
- 2026-08-23 Slice 3: moved Product Intelligence, Data Enrichment, Knowledge Graph, selector response, and LLM administration DTOs beside their API methods. Updated consumers to import owners directly; no compatibility exports remain. `lib/api/types.ts` fell from 831 to 498 physical lines. `vp check`, three focused files (13 tests), architecture policy, and `vp build` passed.
- 2026-08-23 Slice 4: enabled the production max-15 rule and reduced all 15 live violations without exclusions. Split derivation/rendering by existing domain owners for Data Enrichment, Crawl Run, Product Intelligence, Domain Memory, run summaries, config dispatch, dropdowns, and terminal rows. Focused suites passed (17 files, 110 tests); one overloaded aggregate run timed out in a terminal test, which passed in isolation and in the smaller seven-file crawl suite.
- 2026-08-23 Slice 5: lowered `log-terminal.tsx` and `lib/api/types.ts` budgets from 1020/875 to 820/525, updated architecture ownership docs, and passed `vp check`, frontend architecture policy, `git diff --check`, focused tests, and `vp build`.
- 2026-08-23 Slice 6: opened PR #55 (`https://github.com/abhij1306/CrawlerAI/pull/55`); all 13 CI checks passed before the plan-closing documentation commit.
