# Conventions
- Keep one concern with one owning subsystem; search before adding new files/functions.
- Prefer focused hooks for orchestration and keep page components composition-oriented.
- Server state belongs in TanStack Query; URL-owned state in search params; transient display state local.
- API contracts/types stay in `src/api/*` and `lib/api/*`.
- Shared UI primitives belong in `components/ui`; feature-specific composition stays with the feature.
- Use semantic Tailwind tokens rather than raw CSS-variable utility escapes.
- Preserve explicit crawl controls and backend contract semantics; do not silently rewrite user intent.
- Refactors should delete duplication and compatibility shims rather than add parallel paths.