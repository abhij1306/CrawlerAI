# Frontend Architecture Productionization Closure

**Closed:** 2026-06-20
**Status:** DONE
**Scope:** Productionize current frontend boundaries without changing intended product behavior.

## Completed

- Native React Router data router, lazy route registry, nested session/admin guards, and route metadata ownership.
- Removed Vite/Next-style routing, dynamic, image, and navigation compatibility modules.
- Central request transport with typed errors, request IDs, abort support, bounded GET retry, and no default mutation retry.
- Central TanStack Query defaults and query-key factory. Removed remaining ad hoc query keys.
- Propagated TanStack Query abort signals through crawl run, records, logs, recipes, history, domain-profile, and selector requests.
- Removed page-local Zustand state and dependency. Output-tab state is URL-owned.
- Reduced `crawl-run-screen.tsx` and `crawl-config-screen.tsx` to orchestration owners.
- Split run polling, log transport, records, actions, recipe actions, panel errors, output state, and presentation owners.
- Split crawl submission, domain-memory hydration, field actions, route synchronization, advanced settings, and presentation owners.
- Removed render-time domain/profile state updates. Domain identity changes reset stale profile and selector state before new hydration.
- Preserved explicit profile edits when delayed saved-profile requests resolve.
- Fixed React Router synchronization, bulk-prefill restoration, selector cache invalidation, and legacy `/crawl/bulk` routing.
- Reduced `shared.tsx` coupling by importing terminal, table, and form-field components from direct owners.
- Removed dead `run_config` output-tab handling and unreachable records retry logic.
- Added safe HTTP(S) link validation for backend-provided run and record URLs.
- Replaced raw backend error text in run status panels with user-safe messages while retaining telemetry at the query owner.
- Disabled production source maps. Production output contains no `.map` assets.
- Strengthened architecture checks for orchestration ownership, dynamic crawl-screen imports, and React Router-owned history writes.
- Removed unused dependencies and obsolete API/routing/store files.

## Final ownership boundaries

- `src/app/*`: router, route/access metadata, guards, error boundary, session context.
- `src/api/*`: transport, errors, query defaults, query keys.
- `lib/api/index.ts`: typed endpoint facade and runtime contract validation.
- `components/crawl/crawl-config-screen.tsx`: config-workspace composition only.
- `components/crawl/use-crawl-*.ts`: route sync, domain memory, field operations, and submission side effects.
- `components/crawl/crawl-run-screen.tsx`: run-workspace composition only.
- `components/crawl/use-run-*.ts`: server resources, transport, mutations, reconciliation, and local URL/view state.
- Extracted crawl components: presentation only.

## Validation

- `npm run typecheck`: passed, exit 0.
- `npm run lint`: passed, exit 0, including token and crawl-architecture checks.
- `npm test -- --run`: passed, 18 files and 112 tests.
- `npm run build`: passed, 2,075 modules transformed.
- Largest production JS chunks: `vendor` 178.34 kB / 56.35 kB gzip, `vendor-other` 136.23 kB / 40.50 kB gzip, `router` 98.19 kB / 32.51 kB gzip.
- Lazy crawl chunks: config 56.50 kB / 15.03 kB gzip; run 56.15 kB / 17.09 kB gzip.
- CSS: application 93.10 kB / 17.06 kB gzip.
- No chunk-size warnings, duplicate dependency warnings, or production source-map files.

## Deliberately deferred

- Generated OpenAPI types/client: excluded by the assigned scope; it requires a backend/CI contract decision and was explicitly listed as non-required speculative scope.
- One shared table/JSON records cache: current views use different bounded limits and reconciliation behavior. Merging safely requires an API pagination/infinite-query contract change; current owners are isolated and tested.
- CSS-only selector retirement: XPath/regex remain active backend/user contracts. Removing them would change intended behavior.
- Physical `src/features` relocation: current ownership is explicit without a high-risk path-only rewrite.
- Splitting `log-terminal.tsx` and `form-fields.tsx`: both remain large but cohesive, directly owned, and test-covered. Further splitting is maintainability work, not a production blocker.
- New Storybook, Lighthouse CI, broad Playwright/axe infrastructure, and bundle-analysis dependencies: explicitly outside scope.

These items do not invalidate current ownership boundaries, type safety, route behavior, request safety, or production validation.
