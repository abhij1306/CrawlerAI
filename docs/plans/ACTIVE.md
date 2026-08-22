# Active Plan

**Current:** Extraction runtime simplification → `docs/plans/extraction-runtime-simplification-plan.md`
**Status:** IN PROGRESS
**Started:** 2026-08-22
**Last slice completed:** Slice 6 — Reconcile architecture and diff quality

## Queue

1. Production foundation and cleanup — `docs/plans/production-foundation-cleanup-plan.md`
2. Core and acquisition simplification — `docs/plans/core-acquisition-simplification-plan.md`
3. Services and tooling simplification — `docs/plans/services-tooling-simplification-plan.md`
4. Frontend simplification — `docs/plans/frontend-simplification-plan.md`
5. Test-suite decomposition, quality guardrails, and CodeQL closeout — `docs/plans/test-suite-strict-gates-plan.md`

The queue order minimizes overlap. Each plan is self-contained: remeasure its live scope at startup, preserve behavior, use focused local verification, and finish with `$ship-main` before advancing this file.
