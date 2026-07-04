# Plan: Frontend Live-Run Reliability And Debt

**Created:** 2026-07-04
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** Frontend live run workspace, frontend API contract layer, operator surfaces, frontend architecture gates

## Goal

Fix live-run operational risk and reduce frontend ownership debt. Done means transient log WebSocket disconnects reconnect without losing fallback polling, live run polling avoids avoidable request fan-out, query retry ownership is single-layered, high-debt frontend owners are split by responsibility, and guardrails prevent the same drift.

## Acceptance Criteria

- [x] Live run logs reconnect after transient WebSocket close with capped backoff and polling fallback.
- [x] Live run record polling only polls the visible dataset except where terminal/log record sync requires table records.
- [x] Ordinary query GET requests are not retried by the transport layer.
- [x] Frontend API methods are split into domain modules while callers keep working.
- [x] Data Enrichment, Runs, and App Shell large-owner debt is reduced through focused hooks/components.
- [x] Accessibility lint rules are globally re-enabled with only narrow justified overrides.
- [x] Frontend architecture and bundle/chunk budgets are enforced by policy checks.
- [x] Focused VitePlus and Playwright verification exits 0.

## Do Not Touch

- `backend/**` — no backend API contract changes.
- Extraction/acquisition docs and plans — this is frontend-only remediation.

## Slices

### Slice 1: Plan Registration
**Status:** DONE
**Files:** `docs/plans/frontend-live-run-debt-plan.md`, `docs/plans/ACTIVE.md`
**What:** Register this implementation plan and replace the completed active pointer.
**Verify:** Plan file exists and ACTIVE points here.

### Slice 2: Live-Run Transport And Polling
**Status:** DONE
**Files:** `frontend/components/crawl/use-run-log-stream.ts`, `frontend/components/crawl/use-run-records.ts`, `frontend/components/crawl/use-run-workspace.ts`, `frontend/lib/constants/timing.ts`, crawl run tests
**What:** Add reconnect state with exponential backoff/jitter, keep logs polling only while disconnected, add adaptive polling intervals, and avoid table+JSON polling unless the visible/log/terminal paths need table records.
**Verify:** `vp test components/crawl/crawl-run-screen.test.tsx`

### Slice 3: Retry Ownership And API Modules
**Status:** DONE
**Files:** `frontend/src/api/client.ts`, `frontend/src/api/client.test.ts`, `frontend/src/api/query-client.test.ts`, `frontend/lib/api/*`
**What:** Make query retry ownership live in React Query, add explicit transport retry opt-in, split API methods by domain, and keep a short compatibility facade during caller migration.
**Verify:** `vp test src/api/client.test.ts src/api/query-client.test.ts`

### Slice 4: Feature Owner Splits
**Status:** DONE
**Files:** Data Enrichment page modules, Runs page modules, App Shell hook
**What:** Extract Data Enrichment query/mutation/prefill/detail/source components, Runs state/actions hook, and App Shell reset hook without changing user-visible behavior.
**Verify:** focused affected component tests plus `vp check --fix`

### Slice 5: Guardrails And Browser Coverage
**Status:** DONE
**Files:** frontend policy scripts/tests, Vite lint config, Playwright specs, CI workflow
**What:** Re-enable a11y lint rules, add architecture and bundle budget checks, add mocked browser scenarios for failure, authorization, major route flows, and large lists.
**Verify:** `vp test lib/check-crawl-architecture.test.ts`, `vp build`, `vp exec playwright test --config playwright.config.ts`

## Doc Updates Required

- [x] `docs/frontend-architecture.md` — update API module ownership, live-run polling/reconnect behavior, tests, and policy gates.
- [x] `docs/ENGINEERING_STRATEGY.md` — no update needed; no new stable anti-pattern added.

## Notes

- Fallow audit was used as an advisory gate for introduced complexity and architecture drift.
- React Doctor remains advisory. Baseline improved from 61/100 to 62/100; remaining top issues are whole-query-result subscriptions and prop-synced state effects.
