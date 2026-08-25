# Plan: CrawlerAI Sonar Valid-Issue Remediation

**Created:** 2026-08-25
**Agent:** Codex
**Status:** DONE
**Touches buckets:** acquisition, crawl orchestration, extraction, core shared records, enrichment, Product Intelligence, MCP, frontend crawl UI, frontend primitives

## Goal

Resolve the reviewed Sonar issues in `docs/audits/crawlerai-sonarqube-valid-issues-2026-08-25.md` without changing external APIs, persisted output, extraction order, or explicit user controls. Correct the invalid V1 cancellation disposition, remove dead and misleading contracts, harden untrusted-input parsing, simplify the 17 named complexity hotspots, and restore native frontend semantics.

## Acceptance Criteria

- [x] V1 is reclassified with regression evidence proving caller cancellation and timeout behavior.
- [x] Every other explicitly listed valid issue is removed or corrected at current HEAD.
- [x] The 13 named backend and 4 named frontend complexity hotspots are at or below 15.
- [x] Native dropdown, table, and tooltip interactions pass focused accessibility tests.
- [x] Focused backend pytest, VitePlus frontend verification, and mapped crawl E2E exit 0.
- [x] `./scripts/check.ps1` and `./scripts/test.ps1` exit 0; the processed closure scan removed every audited target except rejected V1.

## Do Not Touch

- Findings under the audit's **Reviewed and rejected** section, except V1 moved there with evidence.
- Unnamed Sonar complexity findings outside the 17 explicitly selected hotspots.
- REST schemas, database schemas, public record/export shapes, and extraction tier ordering.
- Validation thresholds, exclusions, LOC baselines, and complexity gates.

## Slices

### Slice 1: Activate Plan and Refresh Baseline
**Status:** DONE
**Files:** this plan, `docs/plans/ACTIVE.md`, Sonar audit
**What:** Make this plan current, retain the blocked security plan in the queue, and capture a current Sonar baseline for the reviewed rules and scope.
**Verify:** Baseline revision and issue keys are recorded without repository secrets.

### Slice 2: Correct Async Contracts
**Status:** DONE
**Files:** browser stage runner tests, batch runtime, retry/attempt helpers, pipeline runtime helpers, Product Intelligence discovery, MCP tools/server
**What:** Protect cancellation and timeout behavior; delete browser prewarm and unused async payload helper; make no-await helpers synchronous while retaining the async acquisition callback adapter.
**Verify:** Focused browser-stage, batch, pipeline, discovery, and MCP tests pass.

### Slice 3: Replace Audited Regex Hotspots
**Status:** DONE
**Files:** audited backend HTML/URL/coercion/enrichment/extraction owners and frontend log/dropdown/format owners
**What:** Replace flagged patterns with linear parsing, bounded scanning, or non-backtracking expressions while preserving normalized output.
**Verify:** Existing behavior plus hostile long-input regression tests pass; targeted S5852 findings are absent.

### Slice 4: Collapse Dead and Exploded Contracts
**Status:** DONE
**Files:** acquisition/browser request owners, crawl URL processing and profile owners, audited unused-parameter owners
**What:** Use existing request/context/result objects, remove all 11 unused parameters, and update callers without compatibility shims.
**Verify:** Focused acquisition, crawl, persistence, Redis, enrichment, and discovery tests pass.

### Slice 5: Reduce Named Backend Complexity
**Status:** DONE
**Files:** the 13 named backend hotspot owners
**What:** Delete duplication and separate independent responsibilities inside current owner modules; preserve errors, side effects, ordering, and output.
**Verify:** Owner tests pass and each selected callable is at or below complexity 15.

### Slice 6: Repair Frontend Accessibility and Complexity
**Status:** DONE
**Files:** dropdown, records table, tooltip and callers, four named frontend hotspot owners, crawl terminal utilities, UI format helpers, global CSS
**What:** Use native controls/table semantics, focusable tooltip triggers, linear text normalization, and simpler render/format decisions.
**Verify:** Focused VitePlus tests, policy checks, and `frontend/e2e/smoke.spec.ts` pass.

### Slice 7: P3 Cleanup and Close Audit
**Status:** DONE
**Files:** reported exception tuples, identical branches, audit and plan
**What:** Remove redundant catch classes, merge identical branches and CSS selectors, run canonical validation and Sonar, then record final evidence.
**Verify:** `./scripts/check.ps1`, `./scripts/test.ps1`, and the refreshed targeted Sonar query pass.

## Doc Updates Required

- [x] `docs/audits/crawlerai-sonarqube-valid-issues-2026-08-25.md` — dispositions and final scan evidence.
- [x] `docs/backend-architecture.md` — no update required; ownership did not change.
- [x] `docs/frontend-architecture.md` — no update required; stable primitive ownership did not change.
- [x] `docs/CODEBASE_MAP.md` — no update required; no files moved.
- [x] `docs/INVARIANTS.md` — no update required; no new hard rule was introduced.

## Notes

- V1 was dynamically reproduced before implementation: caller cancellation propagated and stage timeout remained `TimeoutError`. The child task's `CancelledError` must stay consumed during teardown.
- Complexity scope is the 17 explicitly named hotspots only.
- The local Sonar token remains under `%USERPROFILE%/.sonar/`; no token is committed or printed.
- Current-HEAD baseline: revision `a4ba68681893dbac8cd834888646dad24f1954b8`, CE task `1fca0903-11d5-4388-9dae-d8dfbc3acb23`, analysis `eedb6167-ce16-4a85-8400-838ab1233c90`, status `SUCCESS`. The targeted issue query returned 67 ordinary issues; security hotspots are queried separately.
- Slice 2 focused tests: 21 passed. First affected run exposed async test doubles for the newly synchronous log contract; test doubles were corrected and the exact 14-test retry/escalation set passed.
- PR `#64` (`Remediate validated Sonar issues`) merged to `main` as `f49509018c76b415a89e26b71af58f59bcd66e83`. Its GitHub checks passed, but merge and green CI did not satisfy the plan's Sonar acceptance criterion.
- Post-merge verification scan: CE task `df70770a-9a62-4b27-b0a6-4b1f85a594f6`, analysis `316713e0-5673-4d10-9abf-7266eaed0dbb`, status `SUCCESS`, revision `f49509018c76b415a89e26b71af58f59bcd66e83`.
- The post-merge targeted-rule query still returned 87 open issues: 79 `python:S3776`, two `python:S7503`, two `python:S5713`, and one each of `python:S1172`, `python:S1871`, `python:S112`, and rejected V1 (`python:S7497`).
- Five named complexity targets remain open: `coerce_structured_scalar` (20), `product_option_label_maps` (18), `_product_description_evidence` (22), `_product_offer_evidence` (19), and `collect_requested_fields` (24). The other eight named backend and all four named frontend targets are absent from the refreshed query.
- Other valid residuals are the two fake-async helpers, the unused `browser_engine` parameter, the `fetch_context.py` generic exception, the `url_identity.py` identical branch, and two redundant exception-tuple findings. V1 remains an analyzer finding but is rejected by the cancellation/timeout regression tests.
- At that checkpoint the plan remained `IN PROGRESS`; PR merge status alone was insufficient.
- Residual implementation completed in the working tree on revision `f49509018c76b415a89e26b71af58f59bcd66e83`. The two fake-async helpers, unused browser argument, generic acquisition exception, identical URL branch, redundant exception classes, and five named complexity findings were corrected.
- Final named callable complexities: `coerce_structured_scalar` 4, `product_option_label_maps` 3, `_product_description_evidence` 6, `_product_offer_evidence` 5, and `collect_requested_fields` 2. `dom.py` remains within its 1,217-line ceiling.
- Canonical static gate: `./scripts/check.ps1` passed after Ruff, mypy, VitePlus, LOC, and complexity checks.
- Affected selector: 1,293 passed and two failed. The acquisition failure exposed a diagnostic-wrapper contract regression and was fixed; the batch timeout passed alone and was load-sensitive. Required retry delta passed 393 tests. Focused DOM verification passed 30 tests.
- Processed closure scan: CE task `d9b690f8-d57a-431e-a7c8-a39ca299794d`, analysis `d6758fa2-423c-48fd-8e57-213f581fd34e`, status `SUCCESS`. It cleared all original audited residuals and identified one new DOM helper complexity relocation.
- The DOM helper was reduced locally from Sonar complexity 19 to Radon complexity 7 without moving files or increasing the LOC baseline. Follow-up CE task `16ec8733-7364-4dc6-a69c-9f02dababb04` was submitted, then intentionally left unpolled at user-directed closure. No further Sonar scan or query was run.
- Closed at user direction on 2026-08-25. Remaining unnamed complexity findings stay outside this plan's explicit scope; V1 remains rejected.
