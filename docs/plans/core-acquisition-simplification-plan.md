# Plan: Core and Acquisition Simplification

**Created:** 2026-08-22
**Agent:** Codex
**Status:** QUEUED
**Touches buckets:** core record/coercion helpers, acquisition/browser runtime, fetch policy, URL and source-capability logic

## Goal

Remove high branching and duplicated decisions from backend core and acquisition code while preserving security, URL admission, browser lifecycle, pacing, retry, proxy, block detection, and extraction-input behavior. Put tables/tunables in `core/config`, keep decisions in their existing domain owner, and make every scoped callable CC 15 or less.

This plan owns all Q-CC-PY findings under `backend/app/core`, `backend/app/acquisition`, and `backend/app/robots_policy.py`/`url_safety.py` that remain in the live scan. It also lowers existing 700-line debt where those modules are touched, without making the repository-wide 800 gate its concern.

## Acceptance Criteria

- [ ] Radon reports no callable above CC 15 in the scoped production paths.
- [ ] Existing source/proxy/browser admission, SSRF, public-target, block classification, engine attempt, timeout, cleanup, and storage-state behavior is preserved.
- [ ] Brand/field coercion keeps identical accepted inputs, canonical values, error/None behavior, and ordering.
- [ ] Static heuristic tables, regexes, thresholds, and field maps move to an existing `app/core/config/*` owner; service modules contain no new tunables.
- [ ] No generic `utils`, strategy framework, policy duplicate, compatibility shim, or tiny-helper forest is introduced.
- [ ] Existing focused tests remain unchanged unless a test asserted a private implementation detail.
- [ ] Scoped LOC and CC debt entries only decrease or disappear.
- [ ] Focused backend pytest, Ruff, mypy, and `$ship-main` CI pass.

## Do Not Touch

- Extraction evidence/resolution/publication semantics, persistence schema, worker orchestration, exports, frontend, or dependencies.
- Browser concurrency limits, timeouts, proxy selection, or retry counts as a side effect of refactoring.
- New browser engines or site-specific rules.
- Broad test-module splitting.

## Simplification Guardrails

- LOC is a diagnostic goal, not a quota. Keep a cohesive owner intact when splitting would scatter one decision across files.
- Do not reduce LOC through blank-line/comment/docstring/type/test deletion, statement packing, minification, generated indirection, file-extension tricks, or moving logic outside scanned roots.
- Do not replace explicit branches with reflection, dynamic dispatch, opaque rule/config blobs, nested expressions, compatibility shims, or tiny helpers that retain the same decision graph.
- Tables belong in config only when they are truly static policy/tunables; moving executable service logic into config is metric gaming.
- A refactor must make admission, lifecycle, or coercion behavior easier to explain and test. Readability wins over a smaller number.
- Never loosen SSRF/security checks, runtime tests, architecture measurements, or debt thresholds to claim simplification.

## Slices

### Slice 1: Characterize security and runtime boundaries

**Status:** TODO
**Files:** scoped core/acquisition tests, `docs/INVARIANTS.md`, this plan

**What:** Recompute live CC by file and group findings by public owner. Search callers before extracting. Identify observable decisions for URL safety, public auth, browser admission, page readiness, block evidence, identity/context options, attempt plans, storage state, traversal, and cleanup. Add characterization only where risky behavior lacks coverage.

**Verify:** Run focused URL safety, security, fetch, browser context/readiness, proxy, traversal, and record-normalization tests before changes; record baseline results and inventory in Notes.

### Slice 2: Simplify core field, URL, and record coercion

**Status:** TODO
**Files:** `backend/app/core/shared/field_coerce_text.py`, `field_coerce_dispatch.py`, `field_coerce.py`, existing price/URL/text owners, `backend/app/core/records/*`, `backend/app/core/config/*`

**What:** Replace long heuristic ladders with named ordered rule data plus small domain predicates. Keep one dispatch owner and existing specialized coercers. Consolidate repeated URL/brand/decimal/variant comparison logic at its current owner. Preserve first-match ordering and distinguish missing, rejected, and normalized values. Move only static data/tunables to config.

**Verify:** Run focused field coercion, normalization, divergence, schema, URL identity, and security tests. Run Ruff/mypy and scoped CC. Specifically verify `infer_brand_from_product_url`, `infer_brand_from_page_identity`, and `coerce_field_value` at CC ≤15.

### Slice 3: Simplify browser admission and content classification

**Status:** TODO
**Files:** `backend/app/acquisition/browser_detail.py`, `browser_block_detection.py`, `browser_readiness.py`, `browser_page_helpers.py`, `browser_listing_visual.py`, `platform_policy.py`, `source_capabilities.py`, related config/tests

**What:** Name domain predicates for URL identity, chrome/shell rejection, product content, detail/listing readiness, block evidence, and source capabilities. Use ordered verdict assembly rather than interleaved flag mutation. Preserve diagnostic evidence and outcome precedence. Do not add downstream extraction compensation.

**Verify:** Run focused browser detail, block, readiness, listing visual, page helper, platform/source-capability, and fetch runtime tests. Compare before/after classifications on existing parametrized cases.

### Slice 4: Simplify browser lifecycle and fetch policy

**Status:** TODO
**Files:** remaining CC>15 modules under `backend/app/acquisition`, especially capture, identity, page flow, storage state, internal replay, traversal helpers, fetch policy/context; focused tests

**What:** Flatten attempt planning, context/page lifecycle, JSON repair, navigation, storage persistence, replay, and traversal predicates without reordering side effects. Keep `fetch_context.py` as fetch owner and `browser_policy.py` as policy owner; remove any duplicate post-block extension path still present. Use explicit state/result objects already defined in the package.

**Verify:** Run focused fetch runtime, browser context, acquisition policy, traversal, cookie/storage, and cleanup tests after each owner group. Run Ruff/mypy and final scoped CC; no result above 15.

### Slice 5: Reconcile ownership and debt

**Status:** TODO
**Files:** `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, relevant architecture tests/config, this plan

**What:** Update docs only for moved responsibility. Remove cleared debt entries and avoid increasing any cap. Inspect imports, side-effect ordering, exception paths, and net LOC. Reject extractions that merely hide branching.

**Verify:** Run architecture tests and `git diff --check`; inspect full diff and the final live scoped inventory.

### Slice 6: `$ship-main`

**Status:** TODO
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local checks, commit/push, open a non-draft PR, wait for all required CI, fix failures on the same branch, merge only green/mergeable work, then synchronize and verify local `main`.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark `DONE` and advance `ACTIVE.md`.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` — only for changed ownership.
- [ ] `docs/backend-architecture.md` — core/acquisition responsibility changes.
- [ ] `docs/INVARIANTS.md` — only if a contract clarification is required.

## Notes

- This plan is behavior-preserving simplification. A predicate extraction must reduce mental work or establish one owner; raw function-length or LOC reduction is insufficient.
- No implementation has started.
