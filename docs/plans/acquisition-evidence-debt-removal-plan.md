# Acquisition And Evidence Debt Removal Plan

**Status:** IN PROGRESS
**Started:** 2026-06-15
**Scope:** Acquisition retry ownership, browser timeout lifecycle, extraction evidence integrity, and deterministic crawl-output quality gates.

## Goal

Remove the retry loop and timeout ownership defects exposed by the latest 75-URL crawl. Deepen the existing extraction candidate system so `CandidateSet` is the real evidence and decision owner, not a shadow serialization step. Add deterministic run-quality gates that expose extraction defects before a run is treated as healthy.

This is a shared-runtime repair. Do not add one-site bypasses.

## Baseline Evidence

Latest persisted run is `run_id=1` with **75 URLs**, not 77:

- 69 success
- 4 blocked
- 2 error
- 23 URLs escalated to browser; 19 of those succeeded
- 13 deterministic audit flags: 10 high, 3 medium
- 73 page trace artifacts; the 2 error URLs have no trace artifact

Non-success records:

| Index | Domain | Verdict | Observed class |
|---|---|---|---|
| 45 | mytheresa.com | error | Patchright identity mismatch, then forced Chrome entered browser -> HTTP -> browser loop and exhausted timeout |
| 46 | mrporter.com | blocked | challenge/block |
| 47 | net-a-porter.com | blocked | challenge/block |
| 56 | decathlon.com | error | Cloudflare path, then real Chrome timeout |
| 68 | aesop.com | blocked | challenge/block |
| 69 | rh.com | blocked | challenge/block |

Evidence graph baseline across 69 successful records:

- 69 records contain `_evidence_graph`
- 5,126 graph nodes
- 2,056 rejected candidates across 67 records
- 0 conflicts
- 0 non-empty review buckets
- 8 validation findings across 3 records
- Candidate nodes commonly have empty `evidence`, empty `metadata`, and `confidence=0.0`
- `_field_evidence_summary` hardcodes `conflict_count=0` and empty finding links

Output-quality signals requiring follow-up:

- `dom_skipped_with_variant_cues`
- `variant_candidate_dropped`
- reproducible missing high-value fields on non-blocked pages
- duplicated title text
- LLM audit diagnosis contradicts deterministic audit flags

## Root Causes

### Acquisition

1. Pipeline retry code decides the retry and directly calls the full generic `acquire()` flow again.
2. A targeted forced-real-Chrome retry is not browser-only. On browser timeout it falls back to HTTP, sees the same vendor block, then escalates to Chrome again.
3. Retry admission checks remaining URL time, but the nested acquisition creates a fresh acquisition deadline. Budget is fragmented and overcommitted.
4. URL processing, acquisition, browser attempt, browser stage, and capture workers each own timeout/cancellation behavior. Nested cancellation produces incomplete traces and leaked asynchronous exceptions.
5. Error URLs do not persist a causal trace.

### Evidence

1. Candidate values first live in parallel dictionaries. `CandidateSet` is populated afterward by observing mutations.
2. Candidate admission does not retain useful source locality such as JSON path, response ID, selector, or source fragment reference.
3. Resolver decisions, semantic conflicts, rejection reasons, transformations, and validator findings are not linked into one decision ledger.
4. Review data is emitted from placeholders, so real rejected candidates and findings do not produce reviewable summaries.
5. The raw graph stores full values without a clear size policy, while the visible run trace gives no useful graph-health summary.

## Architecture Decisions

1. **One retry decision owner, one attempt execution owner.**
   Pipeline may decide that stronger acquisition is justified and state why. Fetch/acquisition runtime executes the typed attempt and owns fallback policy, deadline, and result.

2. **Targeted forced-engine retries are one-shot.**
   A post-extraction forced-real-Chrome retry must not fall back to HTTP or recursively escalate. Normal `auto` acquisition keeps its existing browser-first fallback behavior.

3. **One absolute URL deadline.**
   All child work receives the same deadline or an explicitly smaller phase budget derived from it. No nested flow creates a fresh budget that can outlive the URL deadline.

4. **One cancellation owner per browser attempt.**
   Child stages clean up cooperatively and return typed stage failures. Outer layers do not repeatedly cancel the same work.

5. **CandidateSet becomes the canonical admission and decision ledger.**
   Deterministic tiers admit candidates through one interface at discovery time. Delete the shadow `_append_candidate_evidence` path and parallel decision summaries after migration.

6. **Collect compact evidence always; project it selectively.**
   Do not build a lazy graph after extraction. That loses rejected candidates already seen. Keep a compact always-on ledger, reference large source artifacts by ID/hash, and emit bounded review/trace projections.

7. **Deterministic audit owns run-quality truth.**
   LLM diagnosis may explain deterministic findings when enabled. It must not claim success when deterministic flags show defects.

## Acceptance Criteria

### Acquisition And Browser Lifecycle

- A targeted forced-real-Chrome retry performs at most one browser attempt and zero HTTP fallback attempts.
- Retry execution receives the remaining absolute URL deadline. It cannot create a fresh 110-second acquisition budget.
- Mytheresa replay has no browser -> HTTP -> browser loop.
- Decathlon replay ends as either success or one typed terminal block/timeout with full trace.
- All processed URLs, including errors and timeouts, persist a trace artifact.
- Focused timeout stress tests produce zero unhandled future exceptions, `TargetClosedError` leaks, or closed-pipe cleanup errors.
- Normal `auto` browser-first acquisition still permits HTTP fallback where policy allows it.

### Evidence And Review

- Candidate admission for deterministic tiers records source type, extraction tier, entity scope, and a source locator/reference.
- `CandidateSet` is the only owner of admitted candidate identity and resolver outcome.
- Semantic conflicts are computed from distinct normalized candidate values; conflict count is not hardcoded.
- Selected and rejected candidate IDs have explicit decision reasons.
- Validator findings link to relevant evidence IDs.
- Review bucket is derived from actual conflicts, linked findings, low-confidence winners, and meaningful semantic rejections.
- Public/exported record shape remains unchanged. Raw graph remains internal.
- Graph projections use bounded previews and artifact references for large values.
- A fixture benchmark shows no more than 10% median extraction-only latency regression after graph deepening.

### Crawl Output Quality

- Exact 75-URL manifest is rerun and summarized by deterministic failure class.
- Reproducible `variant_candidate_dropped` and `dom_skipped_with_variant_cues` flags are eliminated.
- Reproducible duplicate-title defect is eliminated.
- Missing high-value fields on non-blocked successful pages either pass after upstream fixes or produce a specific deterministic finding.
- Blocked pages remain typed blocked. No CAPTCHA, proxy, or anti-bot bypass is added.
- Full relevant test suites pass.

## Do Not Touch

- Do not patch publishing, export, or downstream consumers to hide bad acquisition/extraction values.
- Do not change public data shape.
- Do not add site-specific adapters unless a shared-runtime fix is proven insufficient and separately approved.
- Do not add CAPTCHA solving or silently change proxy behavior.
- Do not change explicit user controls: `surface`, traversal intent, proxy settings, or `llm_enabled`.
- Do not make LLM extraction primary.
- Do not resume the paused aggressive-deletion plan during this work.

## Slice 1 - Lock The Failure Baseline

**Purpose:** Turn current failures into deterministic tests before changing runtime behavior.

**Files:**

- `backend/tests/regression/test_pipeline_core.py`
- `backend/tests/component/test_crawl_fetch_runtime.py`
- `backend/tests/regression/test_browser_expansion_runtime.py`
- `backend/tests/regression/test_batch_runtime.py`
- Existing run audit fixtures/helpers

**Work:**

1. Add Mytheresa-shaped regression fixture:
   - HTTP vendor block
   - Patchright detail identity mismatch
   - forced real Chrome timeout or success
   - assert current recursive fallback sequence is rejected
2. Add Decathlon-shaped blocked-to-Chrome terminal failure fixture.
3. Add test requiring trace persistence for timeout/error verdicts.
4. Add test proving normal `auto` browser-first fallback remains supported.
5. Capture exact 75-URL run manifest and baseline deterministic audit summary as a replay reference, without storing volatile page bodies.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/regression/test_pipeline_core.py tests/component/test_crawl_fetch_runtime.py tests/regression/test_browser_expansion_runtime.py tests/regression/test_batch_runtime.py -q
```

**Exit criteria:** New regression tests expose the retry loop, missing error trace, and cancellation leak risks.

## Slice 2 - Consolidate Retry Intent And Deadline Ownership

**Purpose:** Remove browser -> HTTP -> browser recursion and fresh nested budgets.

**Files:**

- `backend/app/services/pipeline/retry/stage.py`
- `backend/app/services/fetch/types.py`
- `backend/app/services/fetch/fetch_context.py`
- `backend/app/services/acquisition/policy.py`
- Relevant config owner under `backend/app/services/config/`
- Slice 1 tests

**Work:**

1. Define or deepen the existing typed acquisition request/intent with:
   - requested engine/tier
   - reason
   - fallback permission
   - absolute deadline or remaining budget
2. Make pipeline retry code return/pass intent. Stop rebuilding an unrestricted generic acquisition request.
3. Execute forced-real-Chrome post-extraction retry as browser-only and one-shot.
4. Derive all retry admission and phase budgets from the URL deadline.
5. Preserve generic `auto` fallback behavior for initial acquisition.
6. Delete redundant retry branches and duplicated budget checks after the new contract owns them.

**Verify:** Run Slice 1 command.

**Exit criteria:** Mytheresa-shaped replay cannot enter HTTP after targeted Chrome begins. Retry cannot outlive URL deadline.

## Slice 3 - Make Browser Cleanup Deterministic

**Purpose:** Remove nested cancellation races and make terminal failures observable.

**Files:**

- `backend/app/services/fetch/browser_attempt.py`
- `backend/app/services/acquisition/browser_stage_runner.py`
- `backend/app/services/acquisition/browser_capture.py`
- `backend/app/services/crawl/batch_runtime.py`
- `backend/app/services/observability/run_trace.py`
- `backend/app/services/pipeline/persistence.py`
- Browser lifecycle regression tests

**Work:**

1. Assign one cancellation owner to each browser attempt.
2. Make navigation, readiness, capture, and close stages use derived phase budgets and typed failures.
3. Reserve deadline budget for capture, trace finalization, and browser close.
4. Await and consume child-task failures during cancellation.
5. Persist terminal trace before propagating error/timeout verdict.
6. Delete duplicate outer timeout/cancel wrappers where the attempt owner now covers them.
7. Add stress regression for repeated timeout and close paths.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/regression/test_browser_expansion_runtime.py tests/regression/test_batch_runtime.py tests/component/test_crawl_fetch_runtime.py -q
```

**Exit criteria:** Error pages have traces. Focused stress run has no leaked task/future or browser-close errors.

## Slice 4 - Make CandidateSet The Real Admission Ledger

**Purpose:** Replace the shadow evidence graph with one canonical candidate owner.

**Files:**

- `backend/app/services/extract/contracts.py`
- `backend/app/services/extract/detail/assembly/candidate_collection.py`
- Deterministic tier collectors under `backend/app/services/extract/detail/`
- `backend/app/services/extract/detail/resolution.py`
- `backend/tests/regression/test_evidence_graph.py`
- `backend/tests/unit/test_extraction_contracts.py`
- Relevant extraction regression tests

**Work:**

1. Deepen candidate admission to require:
   - field
   - value or bounded value reference
   - source type/tier
   - source locator/reference
   - entity scope
   - confidence/quality signals when known
2. Admit candidates at discovery time. Stop watching dictionary mutations afterward.
3. Make candidate IDs stable within record assembly and usable by resolver/validator links.
4. Migrate adapter, structured source, JS state, and DOM collection paths.
5. Delete `_append_candidate_evidence` and redundant candidate identity structures after migration.
6. Add bounded previews and artifact references for large values.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/regression/test_evidence_graph.py tests/unit/test_extraction_contracts.py tests/regression/test_variant_offer_completeness.py tests/regression/test_price_currency_context.py -q
```

**Exit criteria:** Every deterministic candidate passes through CandidateSet once. Source locality exists. Shadow ledger path is deleted.

## Slice 5 - Link Resolution, Validation, And Review

**Purpose:** Make evidence explain actual decisions and defects.

**Files:**

- `backend/app/services/extract/contracts.py`
- `backend/app/services/extract/detail/resolution.py`
- `backend/app/services/extract/detail/validation.py`
- `backend/app/services/export/schema.py`
- `backend/app/services/review/evidence.py`
- `backend/app/services/observability/run_trace.py`
- Evidence/review component tests

**Work:**

1. Record selected candidate IDs, rejected IDs, resolver rule, and rejection reason.
2. Compute semantic conflicts from distinct normalized values.
3. Link validation findings and transformations to evidence IDs.
4. Derive review bucket from defined reviewability rules.
5. Keep raw graph internal and add a bounded evidence-health summary to run trace/review projection.
6. Remove hardcoded conflict/finding placeholders and parallel field evidence summaries.
7. Add graph size and extraction-only latency benchmark fixture.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/regression/test_evidence_graph.py tests/unit/test_extraction_contracts.py tests/component/test_review_service.py -q
```

**Exit criteria:** Synthetic adapter-versus-JSON-LD conflict produces linked conflict/rejection/finding data and a reviewable summary.

## Slice 6 - Repair Deterministic Output Debt

**Purpose:** Fix upstream defects already visible in the 75-URL run.

**Files:**

- `backend/app/services/extract/detail/assembly/tiers.py`
- `backend/app/services/extract/detail/assembly/record_assembly.py`
- Existing variant mapping/normalization owners
- Existing title normalization owner
- `backend/app/services/observability/run_audit.py`
- Focused extraction tests

**Work:**

1. Fix DOM completion decision when variant cues remain unresolved.
2. Fix variant candidates that are collected but dropped from final record.
3. Fix duplicate-title normalization at the owning upstream stage.
4. Make non-blocked missing high-value fields produce explicit deterministic findings.
5. Make LLM audit explanation consume deterministic findings and never contradict them.
6. Do not treat block pages as extraction defects.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/regression/test_variant_offer_completeness.py tests/regression/test_price_currency_context.py tests/regression/test_evidence_graph.py tests/unit/test_extraction_contracts.py -q
.\.venv\Scripts\python.exe run_extraction_smoke.py
```

**Exit criteria:** Reproducible output-quality flags are fixed or converted into precise actionable findings.

## Slice 7 - Acceptance Crawl And Debt Deletion

**Purpose:** Prove the architecture against the same workload and remove superseded paths.

**Files:**

- Exact 75-URL acceptance manifest
- `docs/INVARIANTS.md`
- `docs/BUSINESS_LOGIC.md`
- `docs/CODEBASE_MAP.md`
- `docs/plans/extraction-evidence-graph-plan.md`
- This plan

**Work:**

1. Run focused suites, smoke tests, then exact 75-URL acceptance crawl.
2. Compare acquisition verdicts, attempt sequences, traces, audit flags, output defects, graph links, graph size, and extraction latency against baseline.
3. Delete superseded retry, timeout, candidate-summary, and placeholder graph paths.
4. Correct prior evidence-graph completion claims to point at this follow-up debt plan and measured acceptance results.
5. Update canonical docs with the final single-owner contracts.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

**Exit criteria:** Acceptance criteria pass, superseded paths are deleted, canonical docs match runtime behavior, and this plan is marked complete.

## Execution Order

Execute slices in order. Slice 1 is required before runtime edits. Slices 2 and 3 repair acquisition ownership. Slices 4 and 5 repair evidence ownership. Slice 6 uses the repaired evidence system to close output defects. Slice 7 is the only completion gate.

Do not begin implementation until this plan is approved.
