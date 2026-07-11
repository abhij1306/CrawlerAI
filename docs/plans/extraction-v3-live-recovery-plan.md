# Plan: Extraction V3 Branch Recovery — Correctness, Live Proof, and De-bloat

**Created:** 2026-07-11
**Revised:** 2026-07-11
**Agent:** LUNA (implementation), Codex (audit and plan author)
**Status:** SUPERSEDED FOR EXTRACTION ARCHITECTURE — evidence and completed fixes retained; remaining extraction instructions replaced by `domain-learned-extraction-rearchitecture-plan.md`

> **Historical execution record only. Do not continue any `IN PROGRESS` or `TODO` slice below as an active extraction instruction.**

**Touches buckets:** Bucket 2 crawl pipeline; Bucket 3 acquisition/browser/replay; Bucket 4 extraction; Bucket 5 diagnostics/persistence only for truthful state; Bucket 7 LLM; focused backend evaluation/tests; crawl and Domain Memory UI visibility

## Goal

Recover the feature branch from evidence-backed failures without preserving code merely because it exists. The accepted runtime evidence window is **Runs 39, 40, and 41 onward only**. Fix wrong-product detail output, price corruption, record loss, category absence, job-listing failures, opaque LLM failures, and unproven replay at their earliest owners. At the same time, audit every major branch addition against a user-visible contract and delete or consolidate unproven parallel machinery. Done means the accepted artifacts replay through the real pipeline, fresh live runs meet explicit contracts, LLM and replay are visible and accountable, and retained production code has one owner per concern.

## Hard Evidence Boundary

- Use Runs **39, 40, 41, 42, 43, 44, and 45** as the initial evidence set.
- Do not cite, label, gate, or claim acceptance from any crawl before Run 39.
- New runs created while executing this plan may be added to the evidence table only after their settings, result IDs, artifacts, and observable outcomes are recorded in Notes.
- The external artifact audit is canonical input for Run 41:
  - `run41/run41_artifact_audit.md`
  - `run41/run41_audit_summary.json`
  - `run41/run41_result_ledger.csv`
  - `run41/run41_endpoint_table.md`
  - `run41/run41_endpoint_ledger.csv`
- Do not commit entire copied site payloads as tests. Reduce each regression to the smallest sanitized HTML/JSON fragment that still reproduces the real pipeline decision.

## Execution Rules for LUNA

- Work one slice at a time. Mark it `IN PROGRESS`, record the pre-change failure, run the listed verification, then mark it `DONE`.
- No production change before Slice 0 is complete. Slice 0 must write the keep/rewrite/delete decision table into Notes.
- Fix the earliest responsible owner. Publication, persistence, export, and UI may expose truth; they may not repair extraction values.
- Preserve explicit `surface`, traversal, proxy, browser, network-capture, and `llm_enabled` controls.
- No domain-specific production branches for any audited site. Site names may appear only in focused artifact tests and Notes.
- Grep before adding. Extend an existing owner. This plan does not authorize a new service, pipeline, candidate system, config module, report format, or plan file.
- Automated tests make no hosted LLM calls and no live site calls. Use bounded adapters and sanitized artifact fragments.
- Do not run broad backend pytest or smoke scripts. Use focused commands only.
- Do not raise semantic file budgets to make checks pass. Split only when ownership is genuinely distinct; otherwise delete/consolidate.
- After each slice, record `git diff --shortstat main` and production-only numstat in Notes. New production LOC requires an explicit retained contract and must be offset by deletion before close.

## Current Evidence

### Listings and LLM: Runs 39, 40, 42–45

| Run/result | Artifact evidence | Required outcome |
|---|---|---|
| 39/112, Arcteryx ecommerce listing | One utility row from `/help/sizing/footwear`; `listing_dom_floor`; marked successful; LLM not considered | Never publish a utility singleton. Produce repeated products or an honest classified failure |
| 40/113, Dyson ecommerce listing | One accessory/footer row survived while real product cards were omitted; marked successful; LLM not considered | Never let accessory/navigation evidence make a listing successful |
| 42/210, ADP job listing | Browser `usable_content`; one anchor, rejected structural; captured JSON is analytics/component assets, not jobs; zero records; LLM disabled | Classify listing shell/no rows truthfully. Do not call arbitrary JSON listing evidence |
| 43/211, Instahyre job listing | Browser snapshot contains search shell/filter UI, no job cards; 29 anchors all shell/cross-host; three metadata endpoints only; LLM failed as `RuntimeError` in 41.9 ms | Do not send an unready/non-job shell to extraction as a usable listing. Preserve real provider failure cause |
| 44/212, VC5 job listing | Page contains a public Bullhorn `JobBoardPost` endpoint and JS-rendered click-handler cards; no network artifact; 49 anchors, 48 shell; LLM failed in 57.6 ms | Wait for rendered repeated cards or capture/map the public response when capture is enabled; ground ID, title, location, and apply URL |
| 45/213, Clark job listing | Saved page still says `Searching...`; 67 anchors all shell; no network artifact; LLM failed in 38.7 ms | Readiness must wait for jobs, explicit no-results, or timeout; loading shell is not usable listing content |

### Run 41 external artifact audit

- 96 ecommerce-detail results, independently classified as **59 correct, 27 partial, 4 wrong-product, 5 shell, and 1 uncertain**.
- 812 exchanges across 58 results. Audit found only **2 replayable-PDP candidate groups**, 89 supplemental groups, and 160 rejected product-like/suspected groups.
- Selected-child/family contamination: results **139, 150, 186, 209**.
- Terminal shell or URL pseudo-product: **142, 154, 178, 196, 198**.
- Record/entity loss: **124, 146, 194**.
- Weaker evidence wins or strong evidence is discarded: **118, 120, 127, 134, 144, 147, 155, 163, 166, 175, 181, 193, 194, 195, 199**.
- SKU semantic confusion: result **117** publishes an opaque platform variant ID while explicit SKU/style evidence exists.
- Category is absent in **96/96** public records despite trustworthy category evidence in representative artifacts.
- Only six records publish `original_price`; **four are materially wrong or misassigned**: **115, 117, 144, 167**.
- Variant coverage is present in 48/96 and additional images in 63/96, but zero currently conflates not-applicable, unknown, and failed capture.
- Run 41 LLM: 33 invocations, 31 failed, one no-match, one produced evidence; every reported cost is zero.
- Adding Runs 43–45 gives 36 observed invocations: **34 failed, one no-match, one produced evidence**. Current useful-evidence rate is 1/36; failure rate is 34/36.
- `report.json` emits 107 root-cause signatures, but many are duplicate projections of the same event (`finding`, `field`, and `field_reason`). Do not treat that as 107 independent defects.

### Run 41 replay candidates

| Result | Candidate | Admission decision |
|---|---|---|
| 149 | Todd Snyder exact product `.json`; no currency | Supplemental by default. Replay-eligible only with independently trusted currency and successful live anonymous verification |
| 209 | J.Crew family endpoint containing selected child `CI939` and color `BR8825`; complete fields/377 variants but sibling risk | Best full replay candidate only after exact child/color binding and live anonymous verification |
| 116, 129, 136, 151, 175 | Exact or product-scoped responses missing required fields, split across calls, or HTML-in-JSON | Supplemental only; never a complete replay source |

Recommendations, related products, review/UGC, availability-only, variant-only, promotions, analytics, localization, and session-dependent exchanges remain non-replayable even when JSON and product-like.

## 14k LOC Audit and Retention Position

Current `main...HEAD` diff: **143 files, +15,018/-1,135, net +13,883**. Current worktree differs only by this plan and the untracked Run 41 audit folder.

| Area | Added | Deleted | Net | Audit position |
|---|---:|---:|---:|---|
| Backend production | 5,467 | 748 | 4,719 | Material runtime growth. Must earn retention through accepted artifact and live contracts |
| Frontend | 487 | 23 | 464 | Keep only truthful visibility used by retained runtime features |
| Backend tests | 4,241 | 315 | 3,926 | Valuable volume, but mostly synthetic; cannot substitute for accepted artifact and live tests |
| Evaluation | 2,859 | 0 | 2,859 | Non-runtime, but oversized for eight stale labels outside the accepted evidence window; release gates are not trustworthy until relabeled |
| Docs | 1,751 | 47 | 1,704 | Contains overlapping plans/audits. Do not add another document; close or mark superseded material in-place |
| Other | 213 | 2 | 211 | Review with owner; not a runtime justification |

Conclusion: raw 14k is not all runtime bloat; about 60% is tests, evaluation, and docs. But roughly **5.2k net backend/frontend production lines** remain, and that is not reasonable to retain unchanged while P0 wrong-product, price, listing, LLM, and replay contracts fail.

Initial family decisions, to be confirmed in Slice 0:

| Family | Current size/evidence | Required disposition |
|---|---|---|
| Listing runtime | 1,779 new lines across the original listing files; fresh listing cases fail or false-succeed | **Rewrite/consolidate landed.** Keep `listing_records.py`, `listing_tier0.py`, and `network_listing.py`; deleted unproven `listing_generalized.py` and route any eligible model backfill through shared runtime |
| Evaluation harness | 2,859 new lines plus 718-line test module; accepted evidence window not represented | **Quarantine then shrink.** No release/cutover decision from stale labels. Retain only machinery exercised by new accepted labels and delete frozen reports/tests with no decision value |
| LLM generalized path | Actual calls occur, but 34/36 fail, useful evidence 1/36, cost zero | **Rewrite call boundary.** One provider/accounting owner, classified errors, grounded backfill only |
| Replay/profile/UI | Hundreds of runtime/test/UI lines; no two-run live proof yet; Run 41 now supplies two candidates | **Conditional keep.** Retain only if controlled and live two-run gates pass; otherwise default off and delete unused endpoint-memory complexity |
| Extraction memory/profile metrics | Large persistence/dashboard/UI growth; not the direct cause of field correctness | **Audit and trim.** Keep fields/operators consumed by a retained workflow; delete cutover/profile state that no accepted gate reads |
| Detail representation/targeting | Run 41 shows both broad success and severe wrong-child/root failures | **Keep and repair in place.** Do not add a parallel graph/resolver |

## Acceptance Criteria

- [ ] No plan, test label, release gate, or acceptance claim relies on a crawl before Run 39.
- [ ] Results 139, 150, 186, and 209 bind title, offer, image, availability, and variants to one exact selected child/color/style or fail closed on ambiguity.
- [ ] Results 115, 117, 144, and 167 preserve correct major-unit current/original-price semantics. No heuristic division occurs in publish/export.
- [ ] Results 142, 154, 178, 196, and 198 cannot publish product-shaped records from terminal shells or URL-only identity.
- [ ] Results 124 and 146 retain a grounded product record; result 194 retains a grounded title, or each emits an evidence-linked blocking reason from the real owner.
- [ ] Strong same-product evidence outranks URL slug, utility copy, recommendation text, and null for all RC4 fixtures.
- [ ] Public SKU accepts explicit SKU/style/product-code semantics and rejects opaque platform IDs without corroboration.
- [ ] Category publishes with provenance for API-category and breadcrumb positives; unknown remains null. It is no longer absent across every positive fixture.
- [ ] Variant/additional-image coverage exposes `complete`, `partial`, `not_applicable`, or `unknown`; zero is not silently treated as complete.
- [ ] Runs 39 and 40 cannot succeed from one utility/navigation/accessory row. DOM-only listing success requires repeated boundaries.
- [ ] Runs 42–45 end as grounded repeated jobs or honest readiness/acquisition/extraction failures. A loading/search shell is never `usable listing content`.
- [ ] Every actual LLM call has safe start/finish logs, classified terminal outcome, latency, and one accounting row including failures/timeouts. Skips have explicit reasons and no cost row.
- [ ] A forced deterministic miss with a fake configured adapter invokes exactly once and publishes only grounded gap-fill evidence.
- [ ] Arbitrary captured JSON never suppresses recovery and never becomes listing or replay evidence by existence alone.
- [ ] Replay passes controlled capture/learn/replay parity and one live anonymous two-run proof using result 209 or 149 semantics. Otherwise it defaults off and unused persistence/UI layers are deleted.
- [ ] Run reports show causal families without triple-counting the same event as independent root causes.
- [ ] Every retained major branch family has an owner, accepted regression, live observable result where applicable, and keep/rewrite/delete decision in Notes.
- [ ] All changed production files remain within current semantic budgets without raising budgets.
- [ ] Final backend/frontend production net LOC is lower than the Slice 0 baseline. No unproven parallel runtime path remains.
- [ ] Focused pytest, changed-file Ruff, focused VitePlus tests, and frontend build when frontend changes all exit 0.

## Do Not Touch

- Publish/export code for field repairs — AP-12 requires graph/target/resolution correction before publication.
- Authentication, proxy identity, cookie memory, and unrelated browser challenge behavior.
- Replay SSRF, public-origin, anonymous-access, method/body, content-type, response-size, and identity security gates except to make them stricter.
- Explicit user controls for surface, traversal, browser, proxy, network capture, or LLM.
- Product Intelligence and Data Enrichment — separate workflows.
- Hosted services or live sites from automated tests.
- New broad corpus/smoke runners. Reuse the existing focused test and evaluation owners.
- Semantic budget configuration — do not increase thresholds to accommodate this branch.

## Slices

### Slice 0: Lock accepted artifacts and decide keep/rewrite/delete
**Status:** DONE (2026-07-11)
**Files:** this plan Notes; existing focused test modules; existing evaluation labels/reports only
**What:**

1. Record exact branch/worktree numstat, module line counts, and semantic-budget violations.
2. Add a Notes table for each major family: contract, owner, accepted evidence, failing evidence, production LOC, decision (`keep`, `rewrite`, `delete`, `conditional`), and deletion target.
3. Mark all evaluation labels/reports outside the Run 39+ evidence window ineligible for release/cutover decisions. Do not delete yet; identify readers first.
4. Add minimal sanitized reproductions for P0 Run 41 cases into existing tests: exact-child contamination, shell acceptance, record loss, and price-unit corruption.
5. Add minimal Runs 39/40 singleton and Runs 44/45 unready-listing reproductions to existing listing/readiness tests.
6. Run tests before production edits. Record expected contract failures; unrelated failures block implementation.

**Verify:** focused tests reproduce every P0 family and list the exact failing assertion in Notes.

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_primary_product_root_selection.py tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_js_state_behavior.py tests\unit\test_block_detection.py tests\unit\test_listing_record_discovery.py tests\unit\test_extraction_listing_behavior.py -q
```

### Slice 1: Bind exact child/color/style before resolution
**Status:** IN PROGRESS
**Files:** `backend/app/extraction/entities.py`; `backend/app/extraction/targeting.py`; `backend/app/extraction/resolution/`; existing URL identity/config owners only if required; existing focused tests
**What:**

1. Parse explicit requested child/style/color identity through the existing URL-identity owner.
2. Select the child entity before resolving title, offers, images, availability, and variants.
3. Require every selected field lineage to descend from that child or an explicitly linked parent/family fact that cannot vary by child.
4. Reject family minimum prices, sibling titles, sibling images, and cross-color availability.
5. If multiple children remain compatible, emit an ambiguity finding and fail closed for affected fields; never mix siblings.
6. Pin cases: Zara 139/186, Apple 150, J.Crew 209. For J.Crew, `CI939` + `BR8825` must select `set_products/2` before field arbitration.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_primary_product_root_selection.py tests\unit\test_conflict_aware_product_linking.py tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_js_state_behavior.py -q
```

### Slice 2: Preserve typed price units and sale semantics
**Status:** IN PROGRESS
**Files:** existing price collection/normalization owner under `backend/app/extraction/`; `backend/app/extraction/resolution/`; existing price config only for real source metadata; focused tests
**What:**

1. Carry source unit semantics (`major`, `minor`, or `unknown`) with price evidence before numeric normalization.
2. Normalize once. Never infer division merely because a number looks 100× too large.
3. Keep current price and compare-at/original price typed separately through variant and parent aggregation.
4. Require shared currency/unit context and plausibility before publishing original price.
5. Pin: 115 `18500 -> 185.00` once; 117 `21500 -> 215.00`; 167 `27110000 -> 271100.00`; 144 `$32` is current price, not original-only.
6. Remove any downstream magnitude repair made redundant by correct evidence normalization.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_extraction_js_state_behavior.py tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_surface_behavior.py -q
```

### Slice 3: Reject terminal shells and reconcile browser readiness
**Status:** DONE (2026-07-11)
**Files:** `backend/app/acquisition/browser_readiness.py`; existing block/shell owner; `backend/app/extraction/engine.py` or validation owner only for evidence threshold; focused acquisition tests
**What:**

1. Separate navigation status, rendered-content usability, and final acquisition disposition.
2. Detail pages require at least two trustworthy same-entity product signals before URL-derived identity can contribute. URL-only identity never clears blocked/404/access-denied/soft-shell gates.
3. Listing pages are not usable while a loading/search indicator remains and zero repeated boundaries exist. Wait for repeated rows, explicit no-results, or bounded timeout.
4. Preserve anomalous raw status for results 184/203/205 while reporting rendered success explicitly; do not rewrite status.
5. Pin shells 142/154/178/196/198 and loading/search shells 43/45.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_block_detection.py tests\component\test_acquirer.py tests\component\test_crawl_service.py tests\unit\test_extraction_runtime_behavior.py -q
```

### Slice 4: Preserve selected entities across the public record boundary
**Status:** IN PROGRESS
**Files:** `backend/app/extraction/entities.py`; `backend/app/extraction/targeting.py`; `backend/app/extraction/result_building.py`; `backend/app/extraction/publication.py` only to enforce projection divergence, not synthesize values; focused tests
**What:**

1. Trace where the exact selected product disappears for Target 124, Zappos 146, and New Balance title 194.
2. A product with exact URL identity plus two corroborating title signals must survive target selection and projection or emit one evidence-linked blocking reason.
3. Do not construct replacement records in persistence/publication.
4. Add projection-divergence assertion when authorized selected facts exist but the public record drops them.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_primary_product_root_selection.py tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_surface_behavior.py tests\unit\test_url_result_persistence.py -q
```

### Slice 5: Correct field ranking, SKU semantics, and category provenance
**Status:** IN PROGRESS
**Files:** existing collectors; `backend/app/extraction/resolution/`; `backend/app/extraction/validation.py`; canonical field mapping/policy config; focused tests
**What:**

1. For the same bound product, explicit structured/H1/meta/network values outrank URL slugs and utility boilerplate. URL title remains review-only and cannot beat readable exact title evidence.
2. Reject descriptions such as buyer-protection, recommendation, routine, navigation, and generic utility copy when cleaner same-product prose exists.
3. Public SKU accepts only semantically named SKU/style/product-code evidence or corroborated equivalents. Result 117 must reject opaque variant ID `45993954771178` as SKU and preserve explicit SKU/style types.
4. Admit category from selected-product API taxonomy, structured category, and product breadcrumb evidence with provenance. Do not infer category from arbitrary URL tokens.
5. Pin RC4 cases plus positive category cases 136/209 and one DOM breadcrumb; retain a negative no-category case.
6. Delete duplicated field repair logic exposed by the tests.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_surface_behavior.py tests\unit\test_extraction_js_state_behavior.py tests\unit\test_primary_product_root_selection.py -q
```

### Slice 6: Fix listing acquisition, boundaries, and honest failure
**Status:** DONE (2026-07-11)
**Files:** `backend/app/acquisition/browser_readiness.py`; existing listing visual/capture owner; `backend/app/extraction/listing_records.py`; `backend/app/extraction/listing_tier0.py`; `backend/app/extraction/network_listing.py`; `backend/app/extraction/result_building.py`; listing tests
**What:**

1. Default `discover_listing_records(... allow_singleton=False)` and remove unconditional singleton calls from Tier 0.
2. DOM-only listing success requires at least two repeated boundaries. A singleton requires explicit structured/network identity corroboration outside DOM discovery.
3. Support repeated click-handler containers with stable IDs only when title and identity are grounded. Prefer rendered rows after correct settle.
4. When network capture is enabled, map repeated job arrays with explicit IDs/URLs. When disabled, do not silently enable it; rely on rendered rows or return a clear recovery/settings reason.
5. Runs 44/45: wait for public job rendering or explicit no-results. VC5 must use rendered Bullhorn-backed cards or its observed response; Clark must not snapshot `Searching...` as usable.
6. Runs 42/43: analytics, component assets, job-function metadata, and location metadata are not job rows. Return honest shell/no-row diagnostics.
7. Replace `has_network_json` recovery gating with accepted network-listing evidence count. Preserve one-retry loop guards and `browser_only` behavior.
8. Runs 39/40: reject utility/accessory singleton false success.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_listing_record_discovery.py tests\unit\test_listing_tier0_structured.py tests\unit\test_extraction_listing_behavior.py tests\unit\test_extraction_surface_behavior.py tests\component\test_crawl_service.py -q
```

### Slice 7: Consolidate the 1,779-line listing subsystem
**Status:** IN PROGRESS — listing-local model runtime deleted; final ownership gate still has unrelated pre-existing debt
**Files:** `backend/app/extraction/listing_records.py`; `listing_tier0.py`; `network_listing.py`; `engine.py`; `model_runtime.py`; listing tests/config budgets
**What:**

1. Preserve only these owners: boundary discovery/diagnostics; deterministic structured/DOM mapping; network row mapping; shared model runtime.
2. Remove listing-local provider invocation, duplicate grounding/flat-map logic, and recipe-store orchestration that is not proven by Runs 39/40/42–45.
3. Any LLM listing backfill must call shared `model_runtime.py` after deterministic boundaries/repeated network entities exist. It cannot invent boundaries, identities, or URLs.
4. Consolidate duplicate row/evidence builders and URL identity helpers into their existing canonical owner; do not create replacement modules.
5. Bring all retained listing files below current semantic budgets without raising budgets. Delete `listing_generalized.py` when it has no unique retained responsibility, then update imports/tests/docs.
6. Record before/after listing production LOC and explain every retained public function.

**Verify:** Slice 6 focused suite stays green, architecture ownership tests pass, and listing production LOC decreases materially.

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_listing_record_discovery.py tests\unit\test_listing_tier0_structured.py tests\unit\test_extraction_listing_behavior.py tests\unit\test_extraction_architecture.py tests\unit\test_final_architecture_ownership.py -q
```

### Slice 8: Repair LLM call boundary, accounting, and effectiveness
**Status:** IN PROGRESS — terminal states, provider-error classification, token propagation, and one cost row per invoked extraction landed; live effectiveness and full start/finish event proof remain
**Files:** `backend/app/crawl/pipeline/record_extraction_stage.py`; `backend/app/extraction/engine.py`; `backend/app/extraction/model_runtime.py`; `backend/app/connectors/llm/generalized_extraction.py`; `provider_client.py`; `tasks.py`; `cost_logging.py`; existing diagnostics/log schema; crawl UI only if needed
**What:**

1. Use one shared provider-call boundary. Remove direct generalized calls that bypass cost logging and crawl events.
2. Persist exact terminal states: `contract_satisfied`, `disabled`, `config_missing`, `not_eligible`, `invoked_produced_evidence`, `invoked_no_match`, `timed_out`, `provider_error`, `invalid_response`, `budget_limited`.
3. Preserve safe provider error category/status and bounded message. Stop collapsing failures to bare `RuntimeError`/`ValueError` or parsing `Error: ...` strings as model JSON.
4. Every actual call emits safe start/finish crawl logs and one accounting row, including failure/timeout. No prompt, response body, cookie, token, authorization, or API key is logged.
5. Add a fake configured adapter forced-miss case: one call, grounded gap-fill accepted, unsupported values rejected, stronger deterministic facts unchanged.
6. Surface persisted requested/invoked/outcome in the current crawl summary/log UI; never infer invocation from the toggle.
7. Reconcile Runs 41 and 43–45 outcomes. A sub-100-ms local/config error must be classified separately from provider timeout/service failure.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_extraction_model_fallback.py tests\regression\test_llm_runtime.py tests\regression\test_llm_circuit_breaker.py tests\component\test_llm_config_service.py tests\component\test_crawl_service.py -q
```

If frontend code changes:

```powershell
cd frontend
vp test components/crawl/crawl-run-screen.test.tsx
```

### Slice 9: Add typed endpoint admission and prove replay twice
**Status:** IN PROGRESS — typed admission landed; replay defaults off until controlled/live two-run proof exists
**Files:** `backend/app/acquisition/internal_api_replay.py`; browser capture endpoint typing owner; profile acquisition contract only if retained; focused replay tests; Domain Memory UI only for truthful retained state
**What:**

1. Classify endpoints as complete PDP candidate, exact supplemental, availability-only, variants/offers-only, recommendation, review/UGC, analytics, config/localization, promotion, auth/session, or unrelated.
2. Complete replay admission requires HTTPS, safe origin, anonymous reproducibility, exact requested-product/child proof, sufficient required fields, stable method/body, supported content type/size, and no unresolved sibling risk.
3. Keep 116/129/136/151/175 supplemental. Reject all negative Run 41 endpoint-ledger classes.
4. Controlled two-run test: capture/learn on Run A, replay on distinct Run B, exact selected identity and required output parity.
5. Live candidate order: J.Crew 209 first after Slice 1 exact-child binding; Todd Snyder 149 second with independent currency. Record request independence and two-run result.
6. If neither live candidate passes, default replay off and delete endpoint persistence/profile/UI complexity that has no other verified consumer. Domain Memory must show no verified endpoint, never a ghost candidate.

**Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\component\test_internal_api_replay_extraction.py tests\unit\test_network_replay_capture.py tests\unit\test_replay_persistence_guard.py tests\component\test_acquirer.py -q
```

If frontend code changes:

```powershell
cd frontend
vp test app/domain-memory/page-view.test.tsx
```

### Slice 10: Make coverage and reports causal, not noisy
**Status:** IN PROGRESS
**Files:** existing diagnostics/run-report owner; extraction contracts/result building; dashboard/UI only if persisted schema changes; focused tests
**What:**

1. Add explicit variant and additional-image coverage state: `complete`, `partial`, `not_applicable`, `unknown`.
2. Keep raw evidence disposition detail, but fold the run report by causal event/family so one missing field is not counted independently as finding + field + field_reason.
3. Preserve evidence links and affected result counts for RC1–RC9.
4. UI/logs must show listing readiness stop reason, LLM terminal state, and replay verification state from persisted truth.
5. Do not add a third diagnostics model. Extend the current `diagnose.v2`/run-report owner.

**Verify:** focused diagnostics/component tests assert stable causal counts and UI states.

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_url_result_persistence.py tests\component\test_dashboard_service.py tests\component\test_crawl_service.py -q
```

### Slice 11: Rebuild the accepted gate and delete unearned branch code
**Status:** IN PROGRESS — docs and listing branch cleanup started; accepted-label/evaluation audit remains
**Files:** existing `backend/eval/` owners; accepted labels/reports; dead runtime/tests/docs identified in Slice 0; canonical docs
**What:**

1. Rebuild release/cutover labels using only Runs 39+ and newly verified runs. Old labels may remain historical but cannot contribute to pass/fail metrics.
2. Retain evaluation functions only when an accepted label or current release decision exercises them. Delete stale frozen reports, duplicate scoring projections, and tests that only assert removed implementation details.
3. Delete or consolidate every Slice 0 family marked `delete`/`rewrite`. Remove unused persistence fields, dashboard aggregation, profile state, frontend panels, config, and compatibility paths together with their readers.
4. Correct `docs/CODEBASE_MAP.md`; it currently names listing owner files that do not exist. Describe only real retained owners.
5. Mark overlapping unverified plans superseded/paused in place. Do not create another plan.
6. Record final total and production-only LOC against Slice 0. Final production net must decrease, all semantic budgets pass, and no accepted behavior may regress.

**Verify:** accepted focused gate passes and architecture tests prove one owner per concern.

### Slice 12: Fresh live acceptance and close
**Status:** TODO
**Files:** plan Notes and new run artifacts; no ad hoc production edits during acceptance
**What:**

Run fresh cases from the UI/API. For each, record run/result ID, settings, collector, record count, verdict, LLM state/cost row, replay state, and artifact links.

| Case | Close requirement |
|---|---|
| Arcteryx Run 39 URL | Repeated products or honest failure; zero utility rows |
| Dyson Run 40 URL | Repeated products or honest failure; zero accessory/navigation rows |
| ADP Run 42 URL | Grounded jobs or explicit shell/no-job-payload reason |
| Instahyre Run 43 URL | Grounded jobs only if public data renders; otherwise honest access/readiness reason, plus classified LLM outcome when enabled |
| VC5 Run 44 URL | Repeated grounded jobs from rendered/public Bullhorn data; ID/title/location/apply URL agree |
| Clark Run 45 URL | Repeated grounded jobs or explicit bounded readiness failure; never saved while `Searching...` |
| Run 41 exact-child detail cases | No cross-child field lineage; prices and identity match selected child |
| Run 41 shell cases | No pseudo-product publication |
| LLM forced live gap | Visible invocation/outcome/accounting; deterministic evidence remains primary |
| Replay 209 or 149 | Browser learn first run, API replay second run, same selected identity and required-field parity; otherwise replay remains off |

Any P0 failure keeps the plan `IN PROGRESS`. Add a narrowly owned corrective slice before code changes. Do not waive live failure because unit tests pass.

**Final Verify:**

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_primary_product_root_selection.py tests\unit\test_conflict_aware_product_linking.py tests\unit\test_extraction_js_state_behavior.py tests\unit\test_extraction_runtime_behavior.py tests\unit\test_extraction_surface_behavior.py tests\unit\test_block_detection.py tests\unit\test_listing_record_discovery.py tests\unit\test_listing_tier0_structured.py tests\unit\test_extraction_listing_behavior.py tests\unit\test_extraction_model_fallback.py tests\unit\test_network_replay_capture.py tests\unit\test_replay_persistence_guard.py tests\regression\test_llm_runtime.py tests\regression\test_llm_circuit_breaker.py tests\component\test_internal_api_replay_extraction.py tests\component\test_llm_config_service.py tests\component\test_acquirer.py tests\component\test_crawl_service.py -q
.\.venv\Scripts\python.exe -m ruff check app
```

If frontend production code changed:

```powershell
cd frontend
vp test components/crawl/crawl-run-screen.test.tsx app/domain-memory/page-view.test.tsx
vp check --fix
vp build
```

## Doc Updates Required

- [x] `docs/BUSINESS_LOGIC.md` — accepted listing, LLM, replay, and detail fail-closed behavior
- [x] `docs/backend-architecture.md` — retained canonical owners and call flow
- [x] `docs/frontend-architecture.md` — only retained crawl/Domain Memory visibility
- [x] `docs/INVARIANTS.md` — only genuinely new contracts; do not duplicate existing Rules 3 and 7
- [x] `docs/CODEBASE_MAP.md` — remove nonexistent listing owners and map retained real files
- [ ] `docs/ENGINEERING_STRATEGY.md` — only if a new reusable anti-pattern remains after applying AP-12 through AP-15
- [x] `docs/plans/crawlerai-extraction-v3-confidence-tiered-plan.md` — mark further expansion paused/superseded until this recovery is DONE
- [x] Existing listing/replay review plans — mark status accurately; do not leave overlapping work appearing active

## Notes

- 2026-07-11: Revised evidence window is Runs 39, 40, and 41 onward. All older-run references removed.
- 2026-07-11: Run 41 external analysis fully reconciled into RC1–RC9, endpoint admission, acceptance criteria, and Slices 1–5/9/10.
- 2026-07-11: Fresh Runs 42–45 all failed job listing. Runs 43–45 invoked LLM and returned opaque `RuntimeError`; Runs 44/45 prove readiness/capture gaps, not merely anchor heuristics.
- 2026-07-11: LOC audit finds 60% of added lines are non-production, but about 5.2k net backend/frontend production lines remain. Retention is conditional on accepted evidence and live proof.
- 2026-07-11: Slice 0 baseline focused suite passed 145 tests. The baseline did not reproduce every live artifact defect, so sanitized contract regressions were added alongside the fixes rather than claiming false pre-change failures.
- 2026-07-11: Retention table: detail targeting/resolution/diagnostics **keep and repair in place** (`targeting.py`, `resolution/`, `result_building.py`, `model_runtime.py`); listing boundary/structured/network owners **keep** (`listing_records.py`, `listing_tier0.py`, `network_listing.py`); listing-local generalized/recipe orchestration **delete** (`listing_generalized.py` and its tests); replay/profile **conditional** (`internal_api_replay.py` admission landed, live parity pending); evaluation expansion **paused** until Run 39+ labels exist.
- 2026-07-11: Slices 1–6 focused verification is green in the recorded suites. Slice 7 removed 653 production lines and its extraction architecture gate passes; the final ownership gate still reports pre-existing AI-visibility debt plus two unrelated oversized modules, so Slice 7 remains in progress.
- 2026-07-11: Recovery-owner production delta versus `HEAD`: `+719/-813`, net `-94`; no semantic budget was raised. Changed-file Ruff passes for the touched backend modules. Concurrent unrelated worktree edits are excluded from this checkpoint.
- 2026-07-11: Generalized model results now carry input/output token counts through runtime metrics; the pipeline records one safe cost-log row for each actual invocation, including classified failure/timeout states. No hosted call was made by tests.
- 2026-07-11: Sol review was requested after the implementation slice but the service returned a usage-limit error before producing a review. Local review and architecture gates remain required; no Sol approval is claimed.
- 2026-07-11: Final focused checkpoint: changed-owner Ruff passed; 39 focused architecture/listing/model/report/replay tests passed. The extraction architecture gate is green. The separate final-ownership ratchet remains red on pre-existing AI-visibility complexity and unrelated oversized modules (`acquisition/browser_capture.py`, `persistence/extraction_memory.py`); no budget was raised to mask it.
- 2026-07-11: Fresh live acceptance, replay two-run proof, full live LLM effectiveness/start-finish event proof, accepted-label rebuild, and frontend verification remain open. Plan stays `IN PROGRESS`.
