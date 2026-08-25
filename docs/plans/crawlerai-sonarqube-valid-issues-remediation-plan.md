# Plan: CrawlerAI Sonar Valid-Issue Remediation

**Created:** 2026-08-25
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** acquisition, crawl orchestration, extraction, core shared records, enrichment, Product Intelligence, MCP, frontend crawl UI, frontend primitives

## Goal

Resolve the reviewed Sonar issues in `docs/audits/crawlerai-sonarqube-valid-issues-2026-08-25.md` without changing external APIs, persisted output, extraction order, or explicit user controls. Correct the invalid V1 cancellation disposition, remove dead and misleading contracts, harden untrusted-input parsing, simplify the 17 named complexity hotspots, and restore native frontend semantics.

## Acceptance Criteria

- [ ] V1 is reclassified with regression evidence proving caller cancellation and timeout behavior.
- [ ] Every other explicitly listed valid issue is removed or corrected at current HEAD.
- [ ] The 13 named backend and 4 named frontend complexity hotspots are at or below 15.
- [ ] Native dropdown, table, and tooltip interactions pass focused accessibility tests.
- [ ] Focused backend pytest, VitePlus frontend verification, and mapped crawl E2E exit 0.
- [ ] `./scripts/check.ps1` and `./scripts/test.ps1` exit 0, and the refreshed Sonar scan has no targeted open issue.

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
**Status:** TODO
**Files:** audited backend HTML/URL/coercion/enrichment/extraction owners and frontend log/dropdown/format owners
**What:** Replace flagged patterns with linear parsing, bounded scanning, or non-backtracking expressions while preserving normalized output.
**Verify:** Existing behavior plus hostile long-input regression tests pass; targeted S5852 findings are absent.

### Slice 4: Collapse Dead and Exploded Contracts
**Status:** TODO
**Files:** acquisition/browser request owners, crawl URL processing and profile owners, audited unused-parameter owners
**What:** Use existing request/context/result objects, remove all 11 unused parameters, and update callers without compatibility shims.
**Verify:** Focused acquisition, crawl, persistence, Redis, enrichment, and discovery tests pass.

### Slice 5: Reduce Named Backend Complexity
**Status:** TODO
**Files:** the 13 named backend hotspot owners
**What:** Delete duplication and separate independent responsibilities inside current owner modules; preserve errors, side effects, ordering, and output.
**Verify:** Owner tests pass and each selected callable is at or below complexity 15.

### Slice 6: Repair Frontend Accessibility and Complexity
**Status:** TODO
**Files:** dropdown, records table, tooltip and callers, four named frontend hotspot owners, crawl terminal utilities, UI format helpers, global CSS
**What:** Use native controls/table semantics, focusable tooltip triggers, linear text normalization, and simpler render/format decisions.
**Verify:** Focused VitePlus tests, policy checks, and `frontend/e2e/smoke.spec.ts` pass.

### Slice 7: P3 Cleanup and Close Audit
**Status:** TODO
**Files:** reported exception tuples, identical branches, audit and plan
**What:** Remove redundant catch classes, merge identical branches and CSS selectors, run canonical validation and Sonar, then record final evidence.
**Verify:** `./scripts/check.ps1`, `./scripts/test.ps1`, and the refreshed targeted Sonar query pass.

## Doc Updates Required

- [ ] `docs/audits/crawlerai-sonarqube-valid-issues-2026-08-25.md` — dispositions and final scan evidence.
- [ ] `docs/backend-architecture.md` — only if an internal ownership contract materially changes.
- [ ] `docs/frontend-architecture.md` — only if primitive contracts need stable documentation.
- [ ] `docs/CODEBASE_MAP.md` — not expected; no files move.
- [ ] `docs/INVARIANTS.md` — not expected; no new hard rule planned.

## Notes

- V1 was dynamically reproduced before implementation: caller cancellation propagated and stage timeout remained `TimeoutError`. The child task's `CancelledError` must stay consumed during teardown.
- Complexity scope is the 17 explicitly named hotspots only.
- The local Sonar token remains under `%USERPROFILE%/.sonar/`; no token is committed or printed.
- Current-HEAD baseline: revision `a4ba68681893dbac8cd834888646dad24f1954b8`, CE task `1fca0903-11d5-4388-9dae-d8dfbc3acb23`, analysis `eedb6167-ce16-4a85-8400-838ab1233c90`, status `SUCCESS`. The targeted issue query returned 67 ordinary issues; security hotspots are queried separately.
- Slice 2 focused tests: 21 passed. First affected run exposed async test doubles for the newly synchronous log contract; test doubles were corrected and the exact 14-test retry/escalation set passed.
