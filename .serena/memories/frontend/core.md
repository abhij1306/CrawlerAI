# Frontend Core
- React 19 + Vite SPA under `frontend/`; bootstrap `src/main.tsx`, router `src/app/app.tsx`, route metadata/access in `src/app/route-registry.ts`.
- Server state: TanStack Query. Forms: React Hook Form + Zod where applicable. Routing: React Router.
- API chokepoint: `src/api/*`, `lib/api/index.ts`, `lib/api/types.ts`.
- Crawl config ownership: `components/crawl/crawl-config-screen.tsx` plus focused `use-crawl-*` hooks.
- Run workspace ownership: `components/crawl/crawl-run-screen.tsx` plus focused `use-run-*` hooks.
- Shared primitives: `components/ui/*`; shared operator-page patterns: `components/ui/patterns.tsx`.
- CSS ownership: global tokens/utilities in `app/globals.css`; shell CSS under `components/layout`; feature CSS near feature owner.
- Use semantic Tailwind tokens; raw CSS-variable utility escapes are blocked.
- Canonical detail: `docs/frontend-architecture.md`.