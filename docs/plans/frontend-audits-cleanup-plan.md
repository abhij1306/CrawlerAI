# Plan: Frontend Audits and Cleanup

**Created:** 2026-06-15
**Agent:** Gemini
**Status:** IN PROGRESS
**Touches buckets:** frontend

## Goal

Resolve and clean up 14 identified frontend issues, including Next.js remnants, React Router unsafe API usages, code-splitting, bundle size optimization, and state management refactoring.

## Acceptance Criteria

- [ ] All 49 files have `'use client'` directive removed.
- [ ] ESLint guard `'no-restricted-syntax'` in `eslint.config.mjs` prevents adding it back.
- [ ] Global KaTeX imports removed, KaTeX loaded dynamically in markdown preview.
- [ ] Dead Next.js route folders and comments deleted.
- [ ] Route files standard named as `page-view.tsx`.
- [ ] Unsafe React Router imports replaced in navigation helper.
- [ ] Bundle chunking / code splitting configured in router and Vite.
- [ ] barrel file refactor for primitives.tsx.
- [ ] API named exports cleaned up.
- [ ] Crawl config screen refactored to use TanStack Query for remote lookups.
- [ ] `@google/design.md` and `react-doctor.config.json` cleaned up.
- [ ] `npm run lint` passes.
- [ ] `npm run typecheck` passes.
- [ ] `npm run build` passes.
- [ ] `npm test` passes.

## Do Not Touch

Backend files and backend tests are untouched per instructions.

## Slices

### Slice 1: React Router, Navigation & ESLint
- Remove unsafe React Router internals in `navigation.ts`.
- Remove `'use client'` directives from 49 files and add ESLint rule.
- Delete dead Next.js route folders and `react-doctor.config.json`. Remove devDependency `@google/design.md`.

### Slice 2: KaTeX & Vite build optimization
- Make KaTeX CSS/JS dynamically load on demand.
- Implement Vite code-splitting and aliases.
- Rename page files to `page-view.tsx` and moveSelectorsManagePage.

### Slice 3: Component & State Refactor
- Split `primitives.tsx` and update exports.
- Clean up `lib/api/index.ts` named exports.
- Refactor profile/selectors lookup to TanStack Query.
- CSS Modules refactoring.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — if selectors manage page file moved

## Notes
- None yet.
