# Plan: Core and Acquisition Simplification

**Created:** 2026-08-22
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** core record/coercion helpers, acquisition/browser runtime, fetch policy, URL and source-capability logic

## Goal

Remove high branching and duplicated decisions from backend core and acquisition code while preserving security, URL admission, browser lifecycle, pacing, retry, proxy, block detection, and extraction-input behavior. Put tables/tunables in `core/config`, keep decisions in their existing domain owner, and make every scoped callable CC 15 or less.

This plan owns all Q-CC-PY findings under `backend/app/core`, `backend/app/acquisition`, `backend/app/crawl/robots_policy.py`, and `backend/app/core/url_safety.py` that remain in the live scan. It also lowers existing 700-line debt where those modules are touched, without making the repository-wide 800 gate its concern.

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

**Status:** DONE
**Files:** scoped core/acquisition tests, `docs/INVARIANTS.md`, this plan

**What:** Recompute live CC by file and group findings by public owner. Search callers before extracting. Identify observable decisions for URL safety, public auth, browser admission, page readiness, block evidence, identity/context options, attempt plans, storage state, traversal, and cleanup. Add characterization only where risky behavior lacks coverage.

**Verify:** Run focused URL safety, security, fetch, browser context/readiness, proxy, traversal, and record-normalization tests before changes; record baseline results and inventory in Notes.

### Slice 2: Simplify core field, URL, and record coercion

**Status:** DONE
**Files:** `backend/app/core/shared/field_coerce_text.py`, `field_coerce_dispatch.py`, `field_coerce.py`, existing price/URL/text owners, `backend/app/core/records/*`, `backend/app/core/config/*`

**What:** Replace long heuristic ladders with named ordered rule data plus small domain predicates. Keep one dispatch owner and existing specialized coercers. Consolidate repeated URL/brand/decimal/variant comparison logic at its current owner. Preserve first-match ordering and distinguish missing, rejected, and normalized values. Move only static data/tunables to config.

**Verify:** Run focused field coercion, normalization, divergence, schema, URL identity, and security tests. Run Ruff/mypy and scoped CC. Specifically verify `infer_brand_from_product_url`, `infer_brand_from_page_identity`, and `coerce_field_value` at CC ≤15.

### Slice 3: Simplify browser admission and content classification

**Status:** DONE
**Files:** `backend/app/acquisition/browser_detail.py`, `browser_block_detection.py`, `browser_readiness.py`, `browser_page_helpers.py`, `browser_listing_visual.py`, `platform_policy.py`, `source_capabilities.py`, related config/tests

**What:** Name domain predicates for URL identity, chrome/shell rejection, product content, detail/listing readiness, block evidence, and source capabilities. Use ordered verdict assembly rather than interleaved flag mutation. Preserve diagnostic evidence and outcome precedence. Do not add downstream extraction compensation.

**Verify:** Run focused browser detail, block, readiness, listing visual, page helper, platform/source-capability, and fetch runtime tests. Compare before/after classifications on existing parametrized cases.

### Slice 4: Simplify browser lifecycle and fetch policy

**Status:** DONE
**Files:** remaining CC>15 modules under `backend/app/acquisition`, especially capture, identity, page flow, storage state, internal replay, traversal helpers, fetch policy/context; focused tests

**What:** Flatten attempt planning, context/page lifecycle, JSON repair, navigation, storage persistence, replay, and traversal predicates without reordering side effects. Keep `fetch_context.py` as fetch owner and `browser_policy.py` as policy owner; remove any duplicate post-block extension path still present. Use explicit state/result objects already defined in the package.

**Verify:** Run focused fetch runtime, browser context, acquisition policy, traversal, cookie/storage, and cleanup tests after each owner group. Run Ruff/mypy and final scoped CC; no result above 15.

### Slice 5: Reconcile ownership and debt

**Status:** DONE
**Files:** `docs/CODEBASE_MAP.md`, `docs/backend-architecture.md`, relevant architecture tests/config, this plan

**What:** Update docs only for moved responsibility. Remove cleared debt entries and avoid increasing any cap. Inspect imports, side-effect ordering, exception paths, and net LOC. Reject extractions that merely hide branching.

**Verify:** Run architecture tests and `git diff --check`; inspect full diff and the final live scoped inventory.

### Slice 6: `$ship-main`

**Status:** IN PROGRESS
**Files:** all and only changes belonging to this plan

**What:** Invoke `$ship-main`. Preserve unrelated work, branch safely, run focused local checks, commit/push, open a non-draft PR, wait for all required CI, fix failures on the same branch, merge only green/mergeable work, then synchronize and verify local `main`.

**Verify:** Record PR URL, merge commit, final branch, local/remote HEAD equality, and retained untracked files. Mark `DONE` and advance `ACTIVE.md`.

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — only for changed ownership.
- [x] `docs/backend-architecture.md` — core/acquisition responsibility changes.
- [ ] `docs/INVARIANTS.md` — only if a contract clarification is required.

## Notes

- This plan is behavior-preserving simplification. A predicate extraction must reduce mental work or establish one owner; raw function-length or LOC reduction is insufficient.
- Activated 2026-08-23 as Plan 3 after the user declared Plan 2 implemented.
- Slice 1 baseline found 62 CC>15 callables across 38 files: 31 under `app/core` and 31 under `app/acquisition`. Peaks are brand URL inference (86), browser-detail candidate admission (56), field coercion dispatch (54), page-identity brand inference (39), and two CC 35 record/browser classifiers. Existing callers were found before extraction; the public boundaries remain the current URL-safety, public-auth, field-coercion, record-projection, fetch, browser admission/readiness, source-capability, storage, and traversal owners.
- Slice 1 focused baseline passed 252 cases in 81.29s across URL safety/security/public auth, fetch transport/escalation/proxy/timeout/network capture, browser detail/readiness/storage, domain cookie memory, platform/source capability, brand inference, record confidence/divergence, URL identity/assets, and crawl schema tests. No characterization gap required a new test before refactoring.
- Slice 2 reduced all 31 live `app/core` CC>15 callables to zero. The CC 86/39 brand ladders now use ordered identity predicates; the CC 54 field coercer remains the single dispatch owner with named structural/identity/numeric/mapping stages. Record normalization, confidence, divergence, URL identity, JS-state scope, schema shaping, option sanitization, contract matching, recipe compilation, public auth, and secret validation were flattened in their existing owners. Static host-brand labels/suffixes moved to `core/config/public_record_policy.py`. Focused closeout passed 200 cases in 46.86s; follow-up typing fixes preserved behavior. Ruff passes and mypy reports no issues in 362 source files.
- Slice 3 cleared all 15 CC>15 callables in browser admission/content-classification owners. Candidate admission is now explicit text/match/navigation/location/expandability predicates; block detection separates product identity, marker collection, hard/shell/provider/captcha verdict groups; readiness separates detail/listing/shell signals and surface verdict assembly. Platform detection, source capabilities, listing visual snapshots, and primary HTML choice stay in their original owners with flatter stages. Focused closeout passed 107 cases; Ruff and mypy (362 files) pass.
- Slice 4 cleared the remaining 16 acquisition CC>15 callables. Navigation attempts, HTTP/browser handoff, capture close/JSON repair, browser identity, storage persistence, cookie selection, replay, diagnostics, and traversal predicates keep their original side-effect order. Focused acquisition closeout passed 228 cases after the final owner split; the wider core/acquisition verification passed another 93 cases. Ruff passes and mypy reports no issues in 364 source files.
- Slice 5 moved static HTML classification to `browser_content_signals.py` and detail candidate admission to `browser_detail_candidates.py`; live readiness and click orchestration remain in their prior owners. The scoped live inventory is now 0 callables above CC 15. All scoped complexity-debt entries were removed; `browser_readiness.py` and `browser_result_builder.py` left oversized debt, and no oversized/complexity cap increased. AP-30 aggregate ownership ratchets were reconciled to acquisition 17,622, core 21,101, and total app 85,728 with an explicit owner-split rationale. Architecture verification passed 36 cases; `git diff --check` passes.
