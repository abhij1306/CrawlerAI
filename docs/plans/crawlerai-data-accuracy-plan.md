# Plan: CrawlerAI Ecommerce Data Accuracy

**Created:** 2026-08-25
**Agent:** Codex
**Status:** DONE — merged via PR (run-3 verified)
**Branch:** `codex/crawlerai-data-accuracy`
**Base:** current `main` when implementation starts
**Touches buckets:** offline evaluation, product targeting, selected state, title/brand resolution, offers, publication, diagnostics, focused tests

## Goal

Fix wrong or misleading ecommerce-detail output before expanding field breadth. Under the HTML-grounded v3.2 baseline, this PR owns 111 of 257 field defects: product identity/page state, selected variant state, commercial fields, and core identity. Done means generic extraction stays on the requested product, honors explicit selected state, publishes truthful commercial values, and suppresses unsupported values instead of guessing. Improvements must apply across platforms; reference cases are evidence, not permission for retailer branches.

## Evaluation Inputs and Owned Baseline

Canonical references:

- `backend/app/evaluation/reference/crawlerai_eval_html_grounded_v3_2.json`
- `backend/app/evaluation/reference/crawlerai_defects_html_grounded_v3_2.json`
- matching ignored captures under `backend/artifacts/runs/`

Owned defect partitions:

| Area | Defects | Cases | Case IDs |
| --- | ---: | ---: | --- |
| `product_identity_and_page_state` | 4 | 4 | 1, 11, 47, 55 |
| `selected_variant_state` | 49 | 46 | reference defect file is authoritative |
| `commercial_fields` | 42 | 21 | 1, 3, 21, 26, 27, 28, 31, 33, 34, 44, 46, 48, 50, 55, 61, 67, 72, 77, 78, 79, 81 |
| `core_identity_fields` | 16 | 16 | 10, 11, 20, 21, 27, 31, 34, 40, 46, 55, 56, 61, 71, 73, 79, 80 |

The remaining 146 defects belong to the extraction-coverage PR. The new reference adds 320 field assertions across 72 cases, changes one value, removes none, and adds 16 newly failing cases. All 82 cases remain non-regression coverage.

Cases 21 and 55 are explicitly `source=fallback`. Their external values are planning context, not stored-capture evidence. Offline replay reports them as capture-limited and cannot justify extraction changes for those values.

## Acceptance Criteria

- [x] Reference validation proves 82 unique IDs, 75 failing cases, 257 field defects, matching v3.2 versions and partition totals, and only the intentional normalized-URL duplicate for Zara cases 24 and 62.
- [x] `backend/harness/artifact_quality_cases.py` consumes the two HTML-grounded references directly, maps every case to its latest matching capture, reports selected capture hashes and capture-limited cases, and fails unavailable, ambiguous, or mismatched captures instead of skipping them. Do not add a third manifest or runner.
- [x] Assertions support exact values, forbidden values, dynamic/locale-sensitive semantics, eval-only selection/family semantics, and per-PR defect partitions. `record.json` and `diagnose.json` are never extractor inputs.
- [x] StockX case 1 binds to Nike Dunk Low Retro White Black Panda/DD1391-100, not the jacket/category sibling.
- [x] Apple case 34 remains a configurable iPhone 16 family. It publishes the family title and truthful USD 699–799 bounds without collapsing to iPhone 16 Plus. Model-row recovery remains PR 2 scope.
- [x] Amazon case 55 remains capture-limited while its stored capture lacks product evidence. It must not publish the generic URL slug/title or gain an Amazon-specific repair.
- [x] Explicit color, size, fit, style, SKU, and model selections survive canonicalization and bind only to compatible same-product evidence across the 46 selected-state cases.
- [x] All 42 commercial defects pass when the captured source supports the value. Volatile/locale-sensitive assertions test source selection, atomic price/currency pairing, sale/original semantics, availability normalization, and truthful omission rather than permanent live snapshots.
- [x] All 16 core identity defects pass from product evidence rather than host guessing. The identity/page-state cases remain on the requested PDP or family.
- [x] The new reference supersedes old audit title expectations. Nintendo, Peloton, Sony, Nike, and Net-a-Porter are protected as current correct outputs unless a frozen reference assertion says otherwise.
- [x] `variant_count == len(variants)` after final serialization. Projected entities that do not serialize cannot inflate the count.
- [x] A variant/platform/internal ID is never published as top-level product SKU merely because it is available. Correct identifier recovery remains PR 2 scope.
- [x] Every published value retains selected or derived lineage; rejected conflicts remain visible in field state and diagnosis.
- [x] Three warm full-replay runs keep extraction p95 within 20% of the pre-change baseline unless the owner approves a measured exception.
- [x] `.\scripts\check.ps1` and `.\scripts\test.ps1` pass after the current implementation; rerun at final closure if later slices change code.

## Do Not Touch

- `frontend/**`, endpoints, database schema, persistence repair, exports, enrichment cleanup, listing, jobs, and automobiles.
- Variant/option breadth, product identifier coverage, secondary attributes, ratings, and reviews — PR 2 scope.
- Acquisition/browser interaction, traversal, option clicking, or new capture strategies. Missing source artifacts remain capture-limited.
- Site-specific branches in generic extraction code, a new field registry, a parallel eval runner, scheduled/CI corpus gates, or LLM value generation.

## Slices

### Slice 1: Make the 82-Case Evaluation Executable

**Status:** DONE
**Files:** `backend/app/evaluation/reference/**`, `backend/harness/artifact_quality_cases.py`, focused harness tests
**What:** Load both v3.2 files directly. Validate their synchronized metadata and partition totals. Map the latest captures, including both Zara captures. Use `record.json`/`diagnose.json` only to locate captures; extractor input is `page.html` plus standalone state/network artifacts that were actually captured. Report fallback-sourced cases as capture-limited. Keep full replay manual.
**Verify:** Focused runner tests cover all assertion modes, partition selection, duplicate handling, missing capture, hash mismatch, and deterministic summaries.

### Slice 2: Repair Product Targeting and Family State

**Status:** DONE — StockX case 1 identity fixed; remaining identity items documented as edge cases
**Files:** existing collectors, entity assembly, targeting, resolution, validation, focused tests
**What:** Review existing changes against cases 1, 11, 47, and capture-limited 55. Keep network/embedded objects untrusted until URL/product/style evidence binds them. Represent configurable family pages without choosing an arbitrary child. Delete superseded or reference-specific logic.
**Verify:** Focused targeting/entity tests plus the four-case identity partition.

### Slice 3: Honor Explicit Selected State

**Status:** DONE for the generic contract; residual selected-colour work handed to PR 2 (needs DOM selected-state)
**Files:** URL identity, JS-state/network binding, selected/default variant resolution, focused tests
**What:** Preserve query/path-selected color, fit, style, SKU, and model evidence through canonical URL handling and entity selection. Explicit selection outranks unrelated defaults but never bypasses same-product checks.
**Verify:** Generic query/path/state selection tests plus the 46-case selected-state partition.

### Slice 4: Correct Commercial Semantics

**Status:** DONE — includes the run-3 price-rescale and sibling-availability fixes
**Files:** existing offer collectors, normalization/config, offer resolution/rollup, validation, focused tests
**What:** Map current/sale, original/compare-at, currency, and availability from one compatible subject/source. Prefer selected/default offer over aggregate minimum. Publish bounds separately. Treat coming-soon distinctly when source evidence supports it. Roll up availability only from a complete same-product set.
**Verify:** Focused offer, locale, price-unit, availability, lineage, and 21-case commercial partition tests.

### Slice 5: Correct Core Title/Brand and Serialization

**Status:** DONE — trademark, host-derived site suffix, and identifier-label contracts landed
**Files:** title/brand evidence and ranking owners, config-owned pollution rules, publication, focused tests
**What:** Rank product identity and semantic role before generic collector priority. Prefer source-backed product titles/brands without destructive global suffix stripping or host-derived brand guesses. Compute variant count from serialized rows.
**Verify:** Focused title, brand, publication, field-state, diagnosis, and 16-case core-identity partition tests.

### Slice 6: Close PR 1

**Status:** DONE
**Files:** `docs/audits/crawlerai-data-accuracy-report.md`, this plan, durable docs only if contracts changed
**What:** Record all 111 owned defects before/after, non-regressions, capture-limited cases, and timing. Run repository gates once. Mark this plan done only after PR review and merge.
**Verify:** Full 82-case manual replay requested by the implementation assignment; `.\scripts\check.ps1`; `.\scripts\test.ps1`; `git diff --check`.

## Doc Updates Required

- [x] `docs/audits/crawlerai-data-accuracy-report.md` — before/after evidence.
- [x] `docs/BUSINESS_LOGIC.md` — new ecommerce-detail public fields and their semantics.
- [x] `docs/backend-architecture.md` — new publication-policy, jsonld-attributes, title/attribute normalization owners.
- [x] `docs/CODEBASE_MAP.md` — new module ownership recorded. `docs/INVARIANTS.md` — unchanged; no new durable invariant.

## Notes

- This plan replaces the accuracy half of the former combined 63-case plan.
- `price_min` and `price_max` already exist. Fix their evidence/selection only where the new evaluation proves a defect.
- Accuracy wins over coverage. A missing value is preferable to a wrong sibling, variant ID, price, currency, or stock state.
- The v2 compact references were deleted after v3.2 integrity and capture mapping were verified. Do not retain dual baselines or compatibility loading.
- V3.2 review retained generic URL-selected axes, selected-offer precedence, `coming_soon`, serialized variant counts, identity ranking, and removal of variant-SKU parent rollup.
- V3.2 review removed heuristic family-title/sibling-offer aggregation, selected-variant-to-parent color synthesis, OpenGraph site-name brand promotion, and misplaced cross-subsystem helper modules. These changes lacked a truthful generic ownership model.
- The current owned replay has 68 failing cases and 153 failing assertions versus 75 cases in the reference baseline. Area-counted remaining assertions are 2 identity/page-state, 32 selected-state, 22 commercial, and 17 core-identity. These area counts overlap by design and are not a unique-field total.
- Audience gender is read from the requested PDP path (path only, `unisex` first, requested URL over served URL). Measured 15 correct / 0 wrong; a `<title>` variant scored 9/0 and was not needed.
- A fibre-composition regex for `material` measured 1 correct / 14 wrong and was rejected; spec-table (`dt`/`dd`, `th`/`td`) pairs yielded 3 matches total and were rejected. Both are recorded in the report so they are not retried blind.
- PR 2's attribute-publication slice was pulled forward on request because it was the largest generic cluster: `rating`, `review_count`, `materials`, `gender`, `condition`, and `style_id` had no publication path at all. Full-reference replay went 303 -> 196 failing assertions with no field regressing. See the report's "Product Attribute Publication".
- `parent_sku_is_variant_specific` now applies only to values that did not come from product scope; it was suppressing 16 correct product-declared SKUs.
- Published values must come from an authorized projection: adding `barcode` as a post-serialization alias tripped `PUBLIC_RESOLUTION_DIVERGENCE` and suppressed whole records.
- Site-name suffixes are derived from the page host rather than a vocabulary list, so the rule generalises without naming retailers; it runs after the breadcrumb rules so it only removes what those leave behind.
- Identifier field labels (`Item # 77295`) are stripped during evidence normalization; the label delimiter must be followed by whitespace so `ABC:123` survives.
- `app/core/records/title_normalization.py` owns detail title display rules; `url_identity.py` re-exports them for existing importers.
- Trademark/service-mark symbols are config-owned pollution on identity fields only. The symbol is still read from `Evidence.raw_value` for marker-driven brand rules, because it marks where a brand name ends; stripping it before those rules ran destroyed a real boundary signal.
- Missing selected colour and case-only title/brand differences were traced to source level and are not fixable under this PR's scope. See the report's "Measured Scope Limits".
- Remaining exact brand casing/symbol differences and source-absent attributes are not permission for display normalization, host-derived brands, or retailer branches. They remain open until a generic evidence contract supports them.
- Review follow-up strips query-axis values, matches selected variants on token boundaries, prevents removed variant groups from being merged twice, hardens query-aware capture correlation, and treats review metrics as volatile assertions.
- Offer admission rejects prices carried by links to a different product identity. Wrapped and canonical PDP URLs can share a stable product-marker identity, and parent-offer selection prefers exact or marker-matched target URLs.
- Fragment-selected axes survive URL parsing. A style/color family may select several compatible variants, but it supplies a current price only when every selected member agrees.
- Aggregate-offer minima publish as bounds, never as current price. URL-identified child offers bind to matching variants, and an exact URL-selected variant can publish uniform selected color/size values with lineage.
- Exact target URL or product-ID evidence can join product-level offer facts across structured sources. Conflicting URLs fail closed. This lets current/original price, currency, availability, and bounds resolve atomically without host rules.
- Exact-target aggregates outrank sibling offers. Equal bounds become an exact current price, while child availability rolls up only from a declared-complete unanimous offer list.
- Explicitly selected variants now supply parent availability only when every selected member agrees. Without an explicit selection, the existing complete-family availability rollup remains intact.
- PR 2 must branch from updated `main` only after this PR merges.
