# Plan: Agentic Browser Playground

**Created:** 2026-06-02
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Bucket 1 (API route registration), Bucket 2 (playground orchestration), Bucket 3 (acquisition + browser runtime), Bucket 7 (LLM admin/runtime), Frontend `/playground`, config under `backend/app/services/config/*`.

## Goal

Add an opt-in agentic browser step to the Playground for sites where sitemap/homepage navigation discovery cannot expose useful ecommerce category URLs. The feature should let a user start a bounded live browser session, give plain-English navigation instructions, watch action progress, and then hand discovered category/detail URLs back into the existing Playground flow. Done means the browser agent only observes and navigates; extraction still happens through normal crawl runs, with visible user controls for LLM, browser session, proxy, and extraction handoff.

## Acceptance Criteria

- [ ] Playground can offer an agentic browser fallback when category discovery returns no useful URLs or when the user manually starts it.
- [ ] Browser sessions are user-owned, isolated, TTL-bound, and killable; stale sessions close without leaking Playwright contexts.
- [ ] LLM action planning runs only when an explicit browser-agent request is made and an active LLM config exists; failures degrade to a visible error/log state.
- [ ] Agent actions are validated against an observed page snapshot/action target list before execution; the executor rejects unsafe selectors, cross-origin surprise navigation, and unsupported actions.
- [ ] The agent can return discovered category/detail URLs into `PlaygroundSession.step_data` without storing extracted records outside normal crawl tables.
- [ ] Starting category/product extraction from agent-discovered URLs creates normal `CrawlRun` rows with explicit `surface`, settings, run IDs, and provenance visible in Playground.
- [ ] UI shows live session status, screenshot preview when enabled, current URL, action log, Stop control, and manual instruction input without hiding the underlying run/job IDs.
- [ ] Tunables live in `backend/app/services/config/*`, not service globals.
- [ ] Browser screenshots obey diagnostics controls; no screenshot capture happens when the relevant capture setting is disabled.
- [ ] Backend component/regression tests cover session lifecycle, planner gating, action validation, handoff to normal crawls, and failure cleanup.
- [ ] Frontend tests cover fallback rendering, action submission, polling, Stop behavior, and handoff into existing category/product selection.
- [ ] Relevant verify commands pass for touched slices.

## Do Not Touch

- `backend/app/services/pipeline/*` - no downstream compensation or parallel extraction path.
- `backend/app/services/publish/*` - agentic browser must not alter verdict/export cleanup.
- Existing extraction ranking/coercion modules - browser agent does not fabricate `price`, `brand`, `variants`, or other fields.
- `DomainMemory` selector learning - do not auto-promote selectors from agent clicks.
- Public API `/api/v1/*` - keep agentic browser as authenticated dashboard/playground behavior only.
- Monitor/alert engines - no special monitor path from agent output; reuse existing downstream creation only.
- Existing sitemap resolver behavior except the minimal call point needed to offer the fallback.

## Proposed Shape

The browser agent is an escalation helper, not a new crawler:

1. Normal Playground discovery runs first: sitemap/homepage/navigation URL discovery.
2. If useful categories are missing, Playground exposes `browser_agent_available`.
3. User starts a browser session from the same input URL.
4. User sends an instruction such as `Open the women's menu and collect sale category links`.
5. Planner receives a compact observable page model and emits one bounded action plan.
6. Executor runs validated actions one at a time, records observations and action logs.
7. Extract URL candidates from the post-action page and action observations.
8. User selects discovered URLs.
9. Playground calls existing `select_category`, `select_products`, or `start_extract` paths to create normal crawl runs.

## Slices

### Slice 1: Contracts, Config, and State Model
**Status:** TODO
**Files:** `backend/app/services/config/browser_agent.py` (new), `backend/app/schemas/browser_agent.py` (new), `backend/app/schemas/playground.py`, `frontend/lib/api/types.ts`.
**What:** Define session states, action schema, observation schema, limits, TTLs, action allowlist, screenshot policy, max steps, max instruction length, max discovered URLs, and API response types. Add typed Playground step-data keys for `browser_agent` without changing the DB model.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/regression/test_config_imports.py tests/component/test_playground_service.py -q`

### Slice 2: Browser Session Manager
**Status:** TODO
**Files:** `backend/app/services/browser_agent/session_manager.py` (new), `backend/app/services/browser_agent/observations.py` (new), tests under `backend/tests/component/test_browser_agent_session.py`.
**What:** Build a user-scoped in-memory session manager over existing `get_browser_runtime()` / `SharedBrowserRuntime.page(...)`. Keep context/page open across turns, update `last_active_at`, support `close_session`, and run bounded cleanup. Reuse existing browser identity/proxy/storage-state rules; do not create a second browser pool.
**Verify:** targeted session tests prove create/get/close, TTL cleanup, user isolation, context close on error, and no screenshot capture when disabled.

### Slice 3: Observe, Plan, Validate, Execute
**Status:** TODO
**Files:** `backend/app/services/browser_agent/planner.py` (new), `backend/app/services/browser_agent/executor.py` (new), `backend/app/services/browser_agent/url_candidates.py` (new), `backend/app/services/llm/payloads.py`, `backend/app/services/config/field_mappings.py`, prompt files under `backend/app/data/prompts/`.
**What:** Add an LLM prompt task for browser actions using the existing `run_prompt_task` path. Observation should prefer an accessibility/role/text target list plus URL/form metadata over full HTML. Validate planner output before execution: action count cap, allowed action types, target IDs from observation, same-page/cross-origin policy, timeout budget, and no arbitrary JavaScript. Executor supports `navigate`, `click`, `fill`, `select`, `press`, `scroll`, `wait`, `extract_urls`, and `screenshot` only when enabled.
**Verify:** planner payload tests, executor tests with fake page, rejection tests for invalid selectors/actions, LLM-disabled and missing-config tests.

### Slice 4: Authenticated API Surface
**Status:** TODO
**Files:** `backend/app/api/browser_agent.py` (new), `backend/app/main.py`, `backend/app/api/playground.py`, `backend/app/services/playground_service.py`, tests under `backend/tests/component/test_browser_agent_api.py`.
**What:** Add dashboard-only endpoints:

- `POST /api/browser-agent/sessions`
- `GET /api/browser-agent/sessions/{id}`
- `POST /api/browser-agent/sessions/{id}/act`
- `GET /api/browser-agent/sessions/{id}/screenshot`
- `DELETE /api/browser-agent/sessions/{id}`
- `POST /api/playground/sessions/{id}/browser-agent/handoff`

The handoff endpoint writes discovered URLs into `PlaygroundSession.step_data.browser_agent` and then delegates to existing selection/extraction helpers. It must not persist extracted data directly.
**Verify:** API tests cover auth, user isolation, session lifecycle, action logs, screenshot policy, handoff, and normal crawl-run creation.

### Slice 5: Playground Integration
**Status:** TODO
**Files:** `frontend/app/playground/page.tsx`, optional extracted `frontend/app/playground/*` components if the page needs splitting, `frontend/lib/api/index.ts`, `frontend/lib/api/types.ts`, frontend tests.
**What:** Add a Browser Agent panel only for states where it is useful: empty `sitemap_listed`, no category URL groups, or explicit user action. Show current URL, status, screenshot preview, action log, instruction input, Stop button, and discovered URL picker. Handoff selected URLs into existing category/product selection UI. Keep it dense and operator-focused; do not make a separate landing page.
**Verify:** `cd frontend; npm run test -- --run` plus targeted type/lint command available in the repo.

### Slice 6: Safety, Observability, and Cleanup
**Status:** TODO
**Files:** `backend/app/services/browser_agent/*`, `backend/app/services/config/browser_agent.py`, `docs/backend-architecture.md`, `docs/frontend-architecture.md`, `docs/CODEBASE_MAP.md`, maybe `docs/INVARIANTS.md` if a new contract is introduced.
**What:** Add structured action logs and diagnostics that explain planner skips/failures without exposing secrets. Redact typed values that look like passwords/tokens. Ensure agent session errors are URL/session-local and cannot fail normal Playground polling. Add shutdown hook cleanup if needed.
**Verify:** redaction tests, cleanup tests, docs updated, and smallest backend/frontend suites passing.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` - add browser-agent API/service/config/frontend owners if new files are created.
- [ ] `docs/backend-architecture.md` - document browser-agent as an observe/navigate Playground helper over existing browser runtime and LLM task path.
- [ ] `docs/frontend-architecture.md` - document new Playground panel and API calls.
- [ ] `docs/INVARIANTS.md` - update only if execution creates a new shared contract beyond existing browser/LLM/Playground rules.

## Key Risks

- **Agent becomes hidden extraction.** Mitigation: agent only returns URL candidates and observations; extraction starts normal `CrawlRun` rows.
- **LLM silently changes behavior.** Mitigation: explicit user action plus active config only; no automatic planner call during ordinary discovery.
- **Browser contexts leak.** Mitigation: TTL cleanup, Stop endpoint, shutdown cleanup, and tests around context close.
- **Selectors become unsafe.** Mitigation: target IDs from observed snapshot, allowlisted action types, no arbitrary JavaScript from the model.
- **Screenshots violate diagnostics controls.** Mitigation: screenshot endpoint returns disabled state unless capture is explicitly enabled for the agent/session.
- **Playground page grows too large.** Mitigation: extract local components only when needed; keep shared API in `lib/api/index.ts`.

## Notes

- Existing invariant says Playground is guided sequencing only. This plan keeps that: browser-agent output is navigation evidence and URL candidates, not extracted product records.
- Existing browser runtime already owns Playwright pooling, fingerprint profile, proxy launch, storage state, popup guard, and teardown. Build on it.
- Existing LLM task runner already owns provider config, budget, retries, cache, parsing, validation, cost logging, and failure categories. Build planner through that path.
- The reference text's separate `/api/browser/sessions` idea is useful, but for Invoro the better boundary is `/api/browser-agent/*` plus a Playground handoff endpoint so the agent does not become a second crawler API.
