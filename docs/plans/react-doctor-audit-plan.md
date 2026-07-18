# Plan: React Doctor Audit Fixes

**Created:** 2026-07-18
**Agent:** Antigravity (Gemini 3.5 Flash)
**Status:** DONE
**Touches buckets:** `frontend/app`, `frontend/components`, `frontend/lib`

## Goal

Resolve the high-impact bugs, performance problems, accessibility gaps, and security warnings found by the `react-doctor` tool. Done looks like a cleaner React 19 codebase, stable effect registration, supply chain hardening, and optimized render performance.

## Acceptance Criteria

- [x] All high-priority bugs (fresh dependencies, prop derived into useState, chained effect state changes) are resolved.
- [x] Render loops in Records Table and selection hook use Set-based lookups for O(1) performance.
- [x] Supply chain security guidelines configured in `pnpm-workspace.yaml`.
- [x] Frontend tests and policy checks pass.

## Do Not Touch

- `backend/*` — Changes are frontend configurations and UI optimization only.

## Slices

### Slice 1: Configuration & Workspace Security
**Status:** DONE
**Files:**
- `frontend/pnpm-workspace.yaml`
**What:** Add `minimumReleaseAge: 10080` and `trustPolicy: no-downgrade` to harden package installation security.
**Verify:** `vp build` in `frontend` succeeds.

### Slice 2: Critical Bugs & React Hooks
**Status:** DONE
**Files:**
- `frontend/components/crawl/use-run-polling.ts`
- `frontend/components/ui/confirm-dialog.tsx`
**What:** Fix `useTerminalSync` fresh dependency recreated on every render by capturing `queries` in a ref outside the effect and removing it from effect dependencies. Fix escape event listener in confirm dialog to use a stable ref for `onCancel` and `pending` callbacks.
**Verify:** Run `vp test components/crawl/use-run-polling.test.tsx` and verify tests pass.

### Slice 3: State Lifecycle & Rendering
**Status:** DONE
**Files:**
- `frontend/app/ai-visibility/domain-workspace.tsx`
- `frontend/app/data-enrichment/enriched-product-view.tsx`
**What:** Sync `repetitions` state when prop changes in domain-workspace. Avoid chained effect state update in enriched-product-view by resetting state directly in render on key change.
**Verify:** `vp build` passes.

### Slice 4: Performance Optimizations
**Status:** DONE
**Files:**
- `frontend/components/crawl/records-table.tsx`
- `frontend/components/crawl/use-run-record-selection.ts`
- `frontend/components/crawl/use-run-log-stream.ts`
**What:** Convert array checks to `Set.has` inside render/filter loops. Lazily initialize ref value for `Date.now()`.
**Verify:** `vp build` passes.

## Doc Updates Required

- None

## Notes
- Completed all slices successfully. All hooks and optimizations validated with VitePlus tests and builds passing perfectly.

