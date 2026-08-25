# Plan: CrawlerAI Ecommerce Data Accuracy

**Created:** 2026-08-25
**Agent:** Codex
**Status:** QUEUED
**Branch:** `codex/crawlerai-data-accuracy`
**Base:** current `main` when implementation starts
**Touches buckets:** offline evaluation, product targeting, selected state, title/brand resolution, offers, publication, diagnostics, focused tests

## Goal

Fix wrong or misleading ecommerce-detail output before expanding field breadth. This PR owns 47 of the 165 observed defects: product identity/page state, selected variant state, commercial fields, and core title/brand identity. Done means the 82-case reference evaluation proves CrawlerAI stays on the requested product, honors explicit selected state, publishes truthful commercial values, and suppresses unsupported values instead of guessing.

## Evaluation Inputs and Owned Baseline

Canonical references:

- `backend/app/evaluation/reference/crawlerai_eval_compact.json`
- `backend/app/evaluation/reference/crawlerai_defects_compact.json`
- matching ignored captures under `backend/artifacts/runs/`

Owned defect partitions:

| Area | Defects | Cases | Case IDs |
| --- | ---: | ---: | --- |
| `product_identity_and_page_state` | 3 | 3 | 1, 34, 55 |
| `selected_variant_state` | 2 | 2 | 28, 79 |
| `commercial_fields` | 26 | 12 | 1, 21, 26, 28, 34, 55, 61, 67, 72, 78, 79, 81 |
| `core_identity_fields` | 16 | 15 | 10, 11, 20, 21, 27, 31, 34, 40, 46, 55, 56, 61, 71, 73, 79 |

The remaining 118 defects belong to the extraction-coverage PR. All 82 cases remain non-regression coverage in this PR.

## Acceptance Criteria

- [ ] Reference validation proves 82 unique IDs, 59 failing cases, 165 defect entries, and only the intentional normalized-URL duplicate for Zara cases 24 and 62.
- [ ] `backend/harness/artifact_quality_cases.py` consumes the two compact references directly, maps every case to its latest matching capture, reports the selected capture hashes, and fails unavailable, ambiguous, or mismatched cases instead of skipping them. Do not add a third manifest or runner.
- [ ] Assertions support exact values, forbidden values, dynamic/locale-sensitive semantics, eval-only selection/family semantics, and per-PR defect partitions. `record.json` and `diagnose.json` are never extractor inputs.
- [ ] StockX case 1 binds to Nike Dunk Low Retro White Black Panda/DD1391-100, not the jacket/category sibling.
- [ ] Apple case 34 remains a configurable iPhone 16 family. It publishes the family title and truthful USD 699–799 bounds without collapsing to iPhone 16 Plus. Model-row recovery remains PR 2 scope.
- [ ] Amazon case 55 binds the requested Punch Pop ASIN product instead of publishing the generic URL slug/title.
- [ ] Zappos case 28 honors color `318988`; J.Crew case 79 honors `fit=Classic` and the requested color state. Canonicalization cannot silently switch either selection.
- [ ] All 26 commercial defects pass when the captured source supports the value. Volatile/locale-sensitive assertions test source selection, atomic price/currency pairing, sale/original semantics, availability normalization, and truthful omission rather than permanent live snapshots.
- [ ] All 16 core identity defects pass. The only observed wrong title, Birkenstock case 11, resolves to `Arizona Birko-Flor in Color Black`; missing brands use product evidence rather than host guessing.
- [ ] The new reference supersedes old audit title expectations. Nintendo, Peloton, Sony, Nike, and Net-a-Porter are protected as current correct outputs unless a frozen reference assertion says otherwise.
- [ ] `variant_count == len(variants)` after final serialization. Projected entities that do not serialize cannot inflate the count.
- [ ] A variant/platform/internal ID is never published as top-level product SKU merely because it is available. Correct identifier recovery remains PR 2 scope.
- [ ] Every published value retains selected or derived lineage; rejected conflicts remain visible in field state and diagnosis.
- [ ] Three warm full-replay runs keep extraction p95 within 20% of the pre-change baseline unless the owner approves a measured exception.
- [ ] `.\scripts\check.ps1` and `.\scripts\test.ps1` pass once after implementation is complete.

## Do Not Touch

- `frontend/**`, endpoints, database schema, persistence repair, exports, enrichment cleanup, listing, jobs, and automobiles.
- Variant/option breadth, product identifier coverage, secondary attributes, ratings, and reviews — PR 2 scope.
- Acquisition/browser interaction, traversal, option clicking, or new capture strategies. Missing source artifacts remain capture-limited.
- Site-specific branches in generic extraction code, a new field registry, a parallel eval runner, scheduled/CI corpus gates, or LLM value generation.

## Slices

### Slice 1: Make the 82-Case Evaluation Executable

**Status:** TODO
**Files:** `backend/app/evaluation/reference/**`, `backend/harness/artifact_quality_cases.py`, focused harness tests
**What:** Extend the existing artifact-quality harness to load both compact files directly. Map the latest captures, including the two Zara captures and six later retry captures. Use `record.json`/`diagnose.json` only to locate captures; extractor input is `page.html` plus standalone state/network artifacts that were actually captured. Add field projection, forbidden values, semantic constraints, defect partitions, selected-capture hashes, and mean/p50/p95 extraction timing. Keep full replay manual.
**Verify:** Focused runner tests cover all assertion modes, partition selection, duplicate handling, missing capture, hash mismatch, and deterministic summaries.

### Slice 2: Repair Product Targeting and Family State

**Status:** TODO
**Files:** existing collectors, entity assembly, targeting, resolution, validation, focused tests
**What:** Trace cases 1, 34, and 55 to the earliest bad evidence/admission/binding decision. Keep network/embedded objects untrusted until URL/product/style evidence binds them. Represent configurable family pages without choosing an arbitrary child. Delete any superseded fallback branch exposed by the fixes.
**Verify:** Focused targeting/entity tests plus the three-case identity partition.

### Slice 3: Honor Explicit Selected State

**Status:** TODO
**Files:** URL identity, JS-state/network binding, selected/default variant resolution, focused tests
**What:** Preserve query/path-selected color, fit, style, SKU, and model evidence through canonical URL handling and entity selection. Explicit selection outranks unrelated defaults but never bypasses same-product checks.
**Verify:** Zappos and J.Crew regression tests plus selected-state partition.

### Slice 4: Correct Commercial Semantics

**Status:** TODO
**Files:** existing offer collectors, normalization/config, offer resolution/rollup, validation, focused tests
**What:** Map current/sale, original/compare-at, currency, and availability from one compatible subject/source. Prefer selected/default offer over aggregate minimum. Publish bounds separately. Treat coming-soon distinctly when source evidence supports it. Roll up availability only from a complete same-product set.
**Verify:** Focused offer, locale, price-unit, availability, lineage, and 12-case commercial partition tests.

### Slice 5: Correct Core Title/Brand and Serialization

**Status:** TODO
**Files:** title/brand evidence and ranking owners, config-owned pollution rules, publication, focused tests
**What:** Rank product identity and semantic role before generic collector priority. Prefer source-backed product titles/brands without destructive global suffix stripping or host-derived brand guesses. Compute variant count from serialized rows.
**Verify:** Focused title, brand, publication, field-state, diagnosis, and 15-case core-identity partition tests.

### Slice 6: Close PR 1

**Status:** TODO
**Files:** `docs/audits/crawlerai-data-accuracy-report.md`, this plan, durable docs only if contracts changed
**What:** Record all 47 owned defects before/after, non-regressions, capture-limited cases, and timing. Run repository gates once. Mark this plan done only after PR review and merge.
**Verify:** Full 82-case manual replay requested by the implementation assignment; `.\scripts\check.ps1`; `.\scripts\test.ps1`; `git diff --check`.

## Doc Updates Required

- [ ] `docs/audits/crawlerai-data-accuracy-report.md` — before/after evidence.
- [ ] `docs/BUSINESS_LOGIC.md` — only if user-visible semantics change beyond current contracts.
- [ ] `docs/backend-architecture.md` — only if durable ownership changes.
- [ ] `docs/CODEBASE_MAP.md` and `docs/INVARIANTS.md` — not expected; update only for real ownership/contract changes.

## Notes

- This plan replaces the accuracy half of the former combined 63-case plan.
- `price_min` and `price_max` already exist. Fix their evidence/selection only where the new evaluation proves a defect.
- Accuracy wins over coverage. A missing value is preferable to a wrong sibling, variant ID, price, currency, or stock state.
- PR 2 must branch from updated `main` only after this PR merges.
