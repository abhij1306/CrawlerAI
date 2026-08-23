# Frontend Architecture

> Last updated: 2026-07-22

This document describes the live frontend structure, what it actually calls in the backend, and the remaining client/backend drift that should stay visible.

## 1. Stack and Role

Frontend is a React + Vite+ UI for:

- auth/session handling
- crawl configuration and launch
- run history and record inspection
- selector tooling embedded in Crawl Studio and Domain Memory (no standalone selectors page)
- intelligence surfaces: data enrichment and product intelligence
- dashboard/history/jobs operations
- admin users and LLM configuration

Key client libraries:

- React Router
- React Query
- Lucide icons

Runtime notes:

- Vite+ boots the app through `src/main.tsx`.
- `src/app/app.tsx` owns the React Router data router, nested access guards, and redirect shims.
- `src/app/route-registry.ts` owns lazy route modules, access policy, page metadata, and navigation metadata.
- `src/app/route-registry.ts` is the sole route authority. Files under `app/` are imported explicitly by this registry; Next App Router-only files such as `loading.tsx`, `layout.tsx`, and bracket route folders are dead code and blocked by the crawl architecture check.
- Legacy routing, dynamic-import, link, and image compatibility wrappers have been removed.
- `VITE_API_BASE_URL` is the frontend API base URL.
- Production builds inject a baseline CSP via `<meta http-equiv="Content-Security-Policy">` (the build-only `csp-meta` plugin in `frontend/vite.config.ts`; the dev document is left untouched for HMR). Its `connect-src` mirrors the `VITE_API_BASE_URL` origin plus its `ws(s)://` sibling, so a build pointed at a new API origin must rebuild rather than re-point the same bundle. Remaining production security headers are still owned by the static hosting boundary, not frontend service code — ops callout: the host must keep sending `Content-Security-Policy: frame-ancestors 'none'` (meta CSP cannot express `frame-ancestors`), `X-Content-Type-Options: nosniff`, and `Referrer-Policy: no-referrer`.

## 2. Route Map

The data router in `frontend/src/app/app.tsx` maps the lazy route modules declared in `frontend/src/app/route-registry.ts` (the sole route authority) plus a handful of redirect shims:

- `/` -> redirect to `/dashboard`
- `/login`
- `/register`
- `/dashboard`
- `/crawl`
- `/crawl/category`
- `/crawl/pdp`
- `/crawl/bulk`
- `/runs`
- `/runs/:run_id`
- `/jobs`
- `/data-enrichment`
- `/product-intelligence`
- `/domain-memory`
- `/admin/users`
- `/admin/llm`
- `*` -> redirect to `/dashboard`

Every registry route lazy-imports its page from `app/<route>/page-view.tsx`.

Important route behavior:

- `/crawl` switches between config mode and run workspace based on `run_id`
- `/crawl/category`, `/crawl/pdp`, and `/crawl/bulk` are route shims into `/crawl?...`
- `/runs/:run_id` routes back into the crawl workspace
- the standalone `/selectors` route no longer exists; selector tooling lives in Crawl Studio field configuration and the `/domain-memory` surface

## 3. Main Frontend Subsystems

### 3.1 App shell and auth

Primary files:

- `components/layout/app-shell.tsx`
- `src/app/app.tsx`
- `src/app/route-registry.ts`
- `src/app/auth-guards.tsx`
- `src/main.tsx`
- `components/layout/sidebar.tsx` (rail/expanded sidebar, nav, theme toggle)
- `components/layout/logo-mark.tsx`
- `components/layout/use-workspace-reset.ts`
- `components/layout/auth-session-query.ts`
- `components/layout/top-bar-context.tsx`
- `components/ui/patterns.tsx` for shared operator-page section shells used across non-crawl app surfaces

Responsibilities:

- Vite app bootstrap and lazy route table
- session and admin gating outside the visual shell
- shell layout and nav
- auth-route vs app-route split
- header state
- theme toggle and common shell framing

### 3.2 API contract layer

Primary files:

- `src/api/client.ts`
- `src/api/errors.ts`
- `src/api/query-client.ts`
- `src/api/query-keys.ts`
- `lib/api/auth.ts`
- `lib/api/dashboard.ts`
- `lib/api/crawls.ts`
- `lib/api/data-enrichment.ts`
- `lib/api/product-intelligence.ts`
- `lib/api/domain-memory.ts`
- `lib/api/selectors.ts`
- `lib/api/knowledge.ts`
- `lib/api/admin.ts`
- `lib/api/jobs.ts`
- `lib/api/types.ts`
- `lib/api/schemas.ts`
- `lib/api/shared.ts`

Responsibilities:

- HTTP transport, abort signals, and request IDs
- one query-key factory and application query defaults
- typed domain endpoint modules for backend calls
- direct domain imports (`lib/api/<domain>.ts`) at every call site; the former `lib/api/index.ts` compatibility facade is deleted
- API typing and zod response schemas (`lib/api/schemas.ts`)
- auth-aware fetch wrapper
- URL helpers for selector preview HTML

This layer is the frontend/backend contract chokepoint.

Retry ownership:

- React Query owns query retries.
- Transport-level network retries are opt-in through explicit request options for rare idempotent non-query operations.

### 3.3 Crawl config and dispatch

Primary files:

- `components/crawl/crawl-config-screen.tsx`
- `components/crawl/use-crawl-config.ts`
- `components/crawl/use-crawl-domain-memory.ts`
- `components/crawl/use-crawl-field-actions.ts`
- `components/crawl/use-crawl-route-sync.ts`
- `components/crawl/use-crawl-submission.ts`
- `components/crawl/domain-surface-config.ts`
- `lib/crawl/run-profile.ts`
- `components/crawl/shared.tsx`
- `lib/constants/crawl-defaults.ts`

Responsibilities:

- choose domain/surface tab/mode
- orchestrate focused route, domain-memory, field-action, and submission hooks
- own Crawl Studio form validation and stable manual field arrays through React Hook Form and Zod
- derive surface from the domain/tab dispatch map
- build dispatch payload
- collect advanced settings and additional fields
- merge persisted run-profile sections through one shared helper used by Crawl Studio and Domain Memory
- submit crawl or CSV run

Current UI settings behavior reflects the backend contract:

- `advanced_enabled`
- `advanced_mode`
- `request_delay_ms`
- `max_records` as a target count for stopping after a page, not a strict row cap
- `respect_robots_txt`
- proxy input
- additional fields
- additional fields are dispatched as the operator typed them (trimmed/deduped only); the UI no longer rewrites labels like `Features & Benefits` into snake_case before the backend sees them
- Surface tabs adapt by domain. Forum Thread renders one tab and hides the mode picker.
- Crawl Studio's Generate + Save to Memory flow also wires accepted generated selectors into the Knowledge Graph as operator-selected extraction contracts; this reuses the existing selector suggestion UI rather than adding a separate cold-start LLM workflow.

### 3.4 Run workspace

Primary files:

- `components/crawl/crawl-run-screen.tsx`
- `components/crawl/use-run-workspace.ts`
- `components/crawl/use-run-polling.ts`
- `components/crawl/use-run-log-stream.ts`
- `components/crawl/use-run-records.ts`
- `components/crawl/use-run-actions.ts`
- `components/crawl/shared.tsx`

Responsibilities:

- poll run state while active through TanStack Query `refetchInterval`
- show records, JSON, and logs
- consume websocket logs when available
- show quality/verdict/progress signals
- expose pause/resume/kill and export actions
- keep server state in TanStack Query, URL-owned output-tab state in search params, and temporary UI state local

Important live data features:

- run records use cleaned `data`, `review_bucket`, and `source_trace`
- provenance API is typed and available through `getRecordProvenance`
- log websocket fallback and reconnect are isolated in `use-run-log-stream.ts`
- log websockets reconnect after transient close with capped exponential backoff and jitter
- log polling remains active while the websocket is disconnected, then stops after reconnect
- live run detail, records, and log fallback polling use fast initial intervals and slower long-run intervals
- JSON output polling avoids concurrent table record polling except when the visible view, log terminal, or terminal reconciliation requires table records

### 3.5 Operator surfaces

Primary files:

- `app/dashboard/page-view.tsx`
- `app/runs/page-view.tsx`
- `app/runs/use-runs-page-state.ts`
- `app/runs/run-row.tsx`
- `app/jobs/page-view.tsx`
- `app/data-enrichment/page-view.tsx`
- `app/data-enrichment/data-enrichment-state.ts`
- `app/data-enrichment/enriched-product-view.tsx`
- `app/data-enrichment/source-record-list.tsx`
- `app/data-enrichment/enrichment-components.tsx`
- `app/product-intelligence/page-view.tsx`
- `app/product-intelligence/use-product-intelligence.ts`
- `app/product-intelligence/product-intelligence-components.tsx`
- `app/product-intelligence/product-intelligence-results.tsx`
- `app/product-intelligence/product-intelligence-candidate-card.tsx`
- `app/product-intelligence/product-intelligence-settings-drawer.tsx`
- `app/domain-memory/page-view.tsx`
- `components/domain-memory/` (feature owner for the domain-memory surface: workspace hook, tabs, sidebar)
- `app/admin/users/page-view.tsx`
- `app/admin/llm/page-view.tsx`

Responsibilities:

- dashboard metrics and recent runs
- run history
- active jobs view
- data enrichment record normalization and review
- product discovery and price comparison
- domain-memory management across domains and surfaces, including selector operations (the standalone selectors page was removed)
- admin user management
- LLM provider/config/cost-log management

### 3.6 UI ownership and style policy

Primary files:

- `components/ui/button.tsx`, `badge.tsx`, `input.tsx`, `card.tsx`, `table.tsx`, `alert.tsx`, and `dialog.tsx` for typed primitive owners
- `components/ui/primitives.tsx` as the compatibility barrel plus dropdown, toggle, tooltip, skeleton, and field helpers
- `components/ui/patterns.tsx` for shared operator-page patterns
- `components/ui/table.tsx` for typed table primitives (`Table`, `TableHeader`, `TableRow`, `TableCell`) styled with semantic Tailwind tokens; `components/crawl/records-table.tsx` for the virtualized crawl-records grid
- `app/product-intelligence/product-intelligence-components.tsx`, `product-intelligence-results.tsx`, and `product-intelligence-candidate-card.tsx` for Product Intelligence local UI pieces, result summaries, source-vs-candidate comparison rows, confidence reason chips, and URL selection actions; crawl result screens can prefill Product Intelligence from both listing and ecommerce detail records

Global CSS policy:

- `app/globals.css` owns the design tokens (light/dark), the `@theme inline` bridge that maps them onto Tailwind utilities, reset, shared browser defaults, animations, and the small cross-feature class layer (focus ring, type scale, card/table/terminal classes) only.
- App/auth shell styling lives in `components/layout/` as token-based Tailwind classes (no shell CSS modules).
- Crawl Studio feature components style via the same semantic tokens under `components/crawl/`.
- Table styling lives in `components/ui/table.tsx`; there is no table CSS module.
- New JSX should use semantic Tailwind tokens such as `bg-background`, `text-muted`, `border-border`, and `shadow-card`. Raw `bg-[var(--...)]`, `text-[var(--...)]`, `border-[var(--...)]`, and `shadow-[var(--...)]` escapes are blocked by `frontend/scripts/check-token-escapes.mjs`.
- JSX accessibility rules `label-has-associated-control` and `prefer-tag-over-role` are globally active. Narrow file overrides are allowed only where existing primitives intentionally emulate native controls.

## 4. Live Backend API Usage

The frontend currently uses live backend routes for:

- auth: `/api/auth/*`
- dashboard: `/api/dashboard`
- crawls: `/api/crawls/*`
- records: `/api/crawls/{id}/records`
- provenance: `/api/records/{id}/provenance`
- exports: `/api/crawls/{id}/export/*`
- logs + websocket: `/api/crawls/{id}/logs`, `/api/crawls/{id}/logs/ws`
- selectors: `/api/selectors`, `/api/selectors/suggest`, `/api/selectors/test`, `/api/selectors/preview-html`
- Knowledge Graph: `/api/knowledge/sites`, `/api/knowledge/graph`, `/api/knowledge/contracts/{template_id}`, `/api/knowledge/contracts/{contract_id}/selection`, `/api/knowledge/contracts/selector`
- users: `/api/users`
- llm: `/api/llm/providers`, `/api/llm/configs`, `/api/llm/test-connection`, `/api/llm/cost-log`
- jobs: `/api/jobs/active`
- data enrichment: `/api/data-enrichment/jobs`
- product intelligence: `/api/product-intelligence/discover`, `/api/product-intelligence/jobs`, `/api/product-intelligence/jobs/{id}/matches/{match_id}/review`

## 5. Known Client/Backend Drift

There is still some API-surface drift and it should remain documented:

- The standalone `/selectors` page has been removed; selector tooling lives in Crawl Studio field configuration and the `/domain-memory` surface. Older docs claiming “selectors page missing backend integration” are stale.

## 6. Current Data Contracts That Matter To Frontend

### CrawlRun

The frontend expects:

- `status`
- `surface`
- `settings`
- `requested_fields`
- `result_summary`

### CrawlRecord

The frontend expects:

- `data`
- `raw_data`
- `discovered_data`
- `source_trace`
- optional `review_bucket`
- optional `provenance_available`

### Provenance

The frontend has a typed provenance object:

- `raw_data`
- `discovered_data`
- `source_trace`
- `manifest_trace`
- `raw_html_path`

### Selectors

The selectors UI is built on:

- selector CRUD records, now queryable across all surfaces for a domain when `surface` is omitted
- preview HTML loaded into a same-origin iframe so selector tooling can compute XPath directly from the loaded DOM
- manual test response with count and matched value
- optional LLM suggestion flow from Crawl Studio field configuration

Domain Memory also includes a Knowledge Graph tab. It loads graph-only domains from `/api/knowledge/sites`, renders bounded graph neighborhoods from `/api/knowledge/graph`, fetches page-template contracts, and lets operators choose retained source candidates with graph-version conflict checks. It uses the existing UI primitives and pattern components; it does not add a separate graph canvas dependency.
- a dedicated `/domain-memory` surface for edit/delete/toggle operations

### LLM Admin

The admin LLM UI is built on:

- provider catalog
- config CRUD
- connection tests
- cost log listing

## 7. Testing Surface

Frontend tests currently cover:

- auth session query
- API client behavior
- crawl config screen
- selector helper logic
- crawl run screen
- shared crawl helpers
- run polling
- domain-profile switching and dirty-edit preservation
- selector hydration/cache invalidation
- output-tab URL state
- central request abort/retry behavior
- websocket log reconnect, polling fallback, and reconnect cleanup
- visible-dataset live record polling
- explicit transport retry opt-in and React Query retry ownership
- Data Enrichment, App Shell, and architecture policy checks

There is also Playwright e2e coverage under `frontend/e2e`.

Policy and CI checks:

- `frontend/scripts/check-frontend-architecture.mjs` enforces feature-owner line budgets, the aggregate nonblank test-LOC ratchet, API owner files, and Data Enrichment ownership boundaries.
- VitePlus applies ESLint complexity 15 to every `*.test.*` and `*.spec.*` callable; CI runs `vp check` and architecture policy before build.
- `frontend/scripts/check-bundle-budgets.mjs` enforces JS/CSS route asset budgets after build and is wired into CI.
- `check:policy` runs token, crawl architecture, frontend architecture, and bundle budget checks.

## 8. Architectural Notes

- The frontend is intentionally thin on domain logic; the backend owns crawl semantics.
- `src/api/client.ts` owns transport; `lib/api/*` domain modules own endpoint grouping; call sites import their domain modules directly (the `lib/api/index.ts` facade was removed in audit 7.8).
- Feature components live in top-level `components/<feature>/` directories: `components/domain-memory/` owns the domain-memory surface (moved out of the removed `components/selectors/` parent in audit 7.9).
- Import aliases: `@/*` → `src/*`, `@lib/*` → `lib/*`, `@ui/*` → `components/ui/*` (tsconfig paths + vite resolve.alias). Deep `../../../+` cross-area imports use the aliases; short intra-feature relative imports stay relative.
- `components/crawl/shared.tsx` owns only remaining crawl-wide types and cohesive helpers. Heavy form, table, and terminal components are imported from their direct owners.
- `components/ui/patterns.tsx` now owns the shared operator-page section framing (`SectionCard`, `SurfaceSection`, `MutedPanelMessage`) so dashboard/admin/tool pages do not hand-roll their own section chrome.
- `components/ui/dialog.tsx` owns destructive confirmations; browser `alert()` and `confirm()` are not used in app/components code.
- `components/ui/table.tsx` owns table primitive styling (semantic Tailwind tokens); call sites compose the typed primitives directly.
- When backend record contracts change, update `lib/api/types.ts` and this doc together.

## 9. Companion Docs

- [../AGENTS.md](../AGENTS.md)
- [backend-architecture.md](backend-architecture.md)
- [ENGINEERING_STRATEGY.md](ENGINEERING_STRATEGY.md)
- [INVARIANTS.md](INVARIANTS.md)
