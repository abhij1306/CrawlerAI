# Plan: PR 53 Review Findings

**Created:** 2026-08-23
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** acquisition browser finalization, core decimal normalization, core brand inference, focused tests, GitHub review threads

## Goal

Resolve every actionable review thread left on merged PR #53, add regression coverage for the four CodeAnt findings, request a fresh CodeRabbit review on a follow-up PR, address validated follow-up findings, and land the fixes with green CI.

## Acceptance Criteria

- [ ] Verified extractability fast-finalizes only successful 2xx browser responses.
- [ ] Plain integral price strings remain valid when cents interpretation is disabled, while negative decimal fields remain rejected.
- [ ] Direct product-URL brand inference recognizes every configured ecommerce detail path marker.
- [ ] Focused acquisition, normalization, brand, Ruff, mypy, and architecture checks pass.
- [ ] The two fixed CodeQL threads and four CodeAnt threads on PR #53 have evidence-backed replies and are resolved.
- [ ] A follow-up PR receives `@coderabbitai review`; validated findings are fixed or explicitly answered.
- [ ] Follow-up PR CI passes and the work is merged into synchronized local `main`.

## Do Not Touch

- Extraction evidence ownership, persistence, publication, retries, proxy policy, frontend, or dependencies.
- Unrelated PR #53 review suggestions or broader normalization redesign.
- Site-specific rules.

## Slices

### Slice 1: Characterize reviewed behavior
**Status:** DONE
**Files:** existing focused tests and the four named production owners
**What:** Reproduce all four CodeAnt cases, confirm the two CodeQL alerts are fixed, and identify the narrowest existing test owners.
**Verify:** New regression tests fail for the reviewed cases before production changes; current CodeQL alerts 390 and 391 are closed/fixed.

### Slice 2: Fix acquisition finalization
**Status:** DONE
**Files:** `backend/app/acquisition/browser_page_helpers.py`, existing focused browser result/page-helper tests
**What:** Require 2xx status for every readiness-based fast-finalization path so HTTP error shells reach normal classification.
**Verify:** Focused browser finalization tests pass and CC remains at or below 15.

### Slice 3: Fix decimal and brand normalization
**Status:** DONE
**Files:** `backend/app/core/records/normalizers/__init__.py`, `backend/app/core/shared/field_coerce_text.py`, focused normalization/brand tests
**What:** Admit context-free integral price strings without cent conversion, reject negative plain decimal values, and use all configured detail markers in direct URL brand inference.
**Verify:** Focused normalization, value-walk, recipe-transform, brand, and resolution tests pass; scoped CC remains at or below 15.

### Slice 4: Review, ship, and close threads
**Status:** IN PROGRESS
**Files:** plan/docs only as required, GitHub PR/review state
**What:** Run focused static checks, open a follow-up PR, invoke `@coderabbitai review`, validate and resolve feedback, wait for green CI, merge, synchronize `main`, and resolve/reply to PR #53 threads.
**Verify:** Record follow-up PR URL, CodeRabbit outcome, CI result, merge commit, thread state, and local/remote HEAD equality.

## Doc Updates Required

- [x] `docs/INVARIANTS.md` — clarified successful-status fast-finalization and numeric normalization.
- [ ] `docs/backend-architecture.md` — not required unless ownership moves.
- [ ] `docs/CODEBASE_MAP.md` — not required unless ownership moves.

## Notes

- PR #53 contains six inline threads: two CodeQL clear-text logging findings already fixed by commit `a4fa676c`, plus four CodeAnt findings covering fast-finalize status, integral price admission, negative decimal admission, and configured detail-marker coverage.
- The four CodeAnt behaviors predated PR #53, but the user explicitly requested that they now be resolved rather than left as behavior-preserving follow-up debt.
- Slice 1 added four focused regression groups. Before production changes, 33 cases fail and 23 pass: three HTTP-error fast-finalize cases, 25 non-`/dp/` configured detail markers, three plain integral prices, and two ASCII negative decimal fields fail exactly as reviewed. The successful 2xx, `/dp/`, explicit-cent, and Unicode-minus controls pass.
- Slice 2 changed the existing readiness fast-finalize gate to require a 2xx response before any readiness or verified-extractability shortcut. HTTP error pages now reach normal classification. The focused browser readiness/block suite passes and the owner remains CC 15.
- Slice 3 removed the obsolete context-free short-integer rejection, applied the existing non-negative contract to the plain numeric decimal shortcut, and expanded direct brand inference from the first detail marker to the complete configured marker tuple. The focused closeout passed 117 cases; Ruff and scoped mypy pass; every touched callable remains CC 15 or lower.
- Follow-up review on PR #54 found one valid boundary issue: broad marker substrings could match unrelated segments such as `productivity`. Marker policy now exposes exact normalized path segments from config; brand inference uses set intersection, and two negative regressions cover the false-positive paths. The expanded focused closeout passes 119 cases; full Ruff and mypy pass; CC remains 15.
- The requested CodeRabbit review completed and found one valid data-integrity risk: admitting bare integral prices also admitted unrelated embedded fragments such as `SKU 10`. Short embedded integers now require an explicit price token, currency code, or currency symbol; bare numeric strings remain valid. The final focused closeout passes 120 cases, architecture passes 36, full Ruff/mypy pass, and all touched callables remain CC 15 or lower.
