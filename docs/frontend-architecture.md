# Frontend architecture

Current React/Vite+ map. It records ownership and contracts, not history.

## Stack and bootstrap

- Bootstrap: `frontend/src/main.tsx`
- Router and guards: `frontend/src/app/app.tsx`, `auth-guards.tsx`
- Route authority: `frontend/src/app/route-registry.ts`
- Transport/query state: `frontend/src/api/client.ts`, `query-client.ts`, `query-keys.ts`
- Domain API modules: `frontend/lib/api/*.ts`
- UI primitives and patterns: `frontend/components/ui/`

The app is a React data-router SPA. Routes are lazy-loaded from the registry. Next
App Router conventions (`loading.tsx`, `layout.tsx`, bracket folders) are not route
owners. `@/*`, `@lib/*`, and `@ui/*` are configured aliases.

`VITE_API_BASE_URL` is compiled into the bundle. Production builds add a baseline CSP
whose `connect-src` matches the API origin and websocket sibling. Hosting owns
`frame-ancestors`, MIME, referrer, and other response headers.

## Routes

The registry owns `/login`, `/register`, `/dashboard`, `/crawl`, `/crawl/category`,
`/crawl/pdp`, `/crawl/bulk`, `/runs`, `/runs/:run_id`, `/jobs`, `/data-enrichment`,
`/product-intelligence`, `/domain-memory`, `/api-access`, `/admin/users`, and
`/admin/llm`. `/` and unknown routes redirect to `/dashboard`.

Category, PDP, and bulk paths are Crawl Studio shims. `/runs/:run_id` opens the run
workspace. There is no standalone `/selectors` page; selector tools live in Crawl
Studio and Domain Memory.

## Ownership

### Shell and session

`components/layout/` owns shell, sidebar, theme, header context, workspace reset,
and auth-session query. `src/app/` owns bootstrap, route metadata, lazy routes, guards,
and the error boundary.

### API and server state

`src/api/client.ts` owns fetch transport, request IDs, abort handling, and auth-aware
errors. `lib/api/<domain>.ts` owns endpoint methods and domain DTOs. Put genuinely
shared DTOs in `lib/api/types.ts`; response validation belongs in `schemas.ts`.
Call sites import domain modules directly.

React Query owns server state, query keys, cache invalidation, and query retries.
Transport retries are opt-in for rare idempotent operations. Feature components do
not add retry loops.

### Crawl Studio

`components/crawl/crawl-config-screen.tsx` owns the form surface. Focused hooks own
route sync, domain memory, field actions, submission, polling, and Run Event streams.
`lib/crawl/run-profile.ts` owns merging persisted profile sections.

The UI sends the backend’s nested `fetch_profile`, `locality_profile`, and
`diagnostics_profile` contract. It preserves typed field labels and explicit operator
controls. `max_records` is a traversal stop target, not a row-cap implementation.

### Run workspace

`components/crawl/crawl-run-screen.tsx` and `use-run-*` hooks own run state, records,
Run Events, websocket fallback, pause/resume/kill, provenance, and exports. TanStack Query
owns server polling; URL search params own the output tab; temporary interaction state
stays local. Run Event websocket reconnect uses capped backoff with jitter and polling fills
the disconnected interval.

### Operator surfaces

- `app/dashboard`: metrics and recent runs
- `app/runs`: run history
- `app/jobs`: active jobs
- `app/data-enrichment`: enrichment jobs, source records, review
- `app/product-intelligence`: discovery, candidates, matching, review
- `app/domain-memory` and `components/domain-memory/`: profiles, selectors, cookies,
  graph contracts, retained source choices
- `app/api-access`: API-key lifecycle and local MCP setup
- `app/admin/users`, `app/admin/llm`: administration

## Styling and UI policy

Typed primitives live in `components/ui/button.tsx`, `badge.tsx`, `input.tsx`,
`card.tsx`, `table.tsx`, `alert.tsx`, and `dialog.tsx`. `primitives.tsx` is a
compatibility barrel. `patterns.tsx` owns shared operator-page sections;
`components/crawl/records-table.tsx` owns the crawl grid.

`app/globals.css` owns tokens, reset, browser defaults, animations, and small shared
classes. New JSX uses semantic Tailwind tokens (`bg-background`, `text-muted`,
`border-border`, `shadow-card`). Raw CSS-variable utility escapes are blocked by
`frontend/scripts/check-token-escapes.mjs`. Accessibility rules for associated labels
and native controls are global; primitive overrides stay local.

## Backend contracts

Domain API modules call auth, dashboard, crawls, records, provenance, exports,
Run Events/websocket, selectors, Knowledge Graph, users, LLM, jobs, enrichment, product
intelligence, API keys, and `/api/v1/capabilities`. Update the owning module and this
document together when a contract changes.

Important client models:

- `CrawlRun`: `status`, `surface`, `settings`, `requested_fields`, `result_summary`
- `CrawlRecord`: `data`, `raw_data`, `discovered_data`, `source_trace`, optional
  `review_bucket` and `provenance_available`
- provenance: raw/discovered data, source and manifest traces, optional raw HTML path

Cookie-authenticated mutations copy the readable signed `csrf_token` cookie into
`X-CSRF-Token`. Explicit bearer requests do not mix cookie proof.

## Testing and policy checks

Frontend unit tests live beside source files and in `frontend/`; browser tests live in
`frontend/e2e`. Coverage includes API/query behavior, auth, Crawl Studio, run polling
and websocket fallback, selector/domain memory, profiles, output-tab state, enrichment,
API access, shell, and architecture policies.

VitePlus owns format, lint, typecheck, unit execution, and build. Repository policy
scripts additionally run token, route/ownership, feature line-budget, test-LOC, and
bundle-budget checks. Local checks use the repository script; GitHub CI owns full
frontend and Playwright validation.

Companion docs: [INVARIANTS.md](INVARIANTS.md), [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md),
[CODEBASE_MAP.md](CODEBASE_MAP.md), and [backend-architecture.md](backend-architecture.md).
