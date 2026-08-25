# Plan: CrawlerAI Source-Backed Extraction Coverage

**Created:** 2026-08-25
**Revised:** 2026-08-25 after the data-accuracy PR merged and run 3 was analysed
**Agent:** Codex
**Status:** QUEUED — start in a fresh session from updated `main`
**Branch:** `codex/crawlerai-extraction-coverage`
**Base:** updated `main` after the data-accuracy PR merges
**Touches buckets:** deterministic collectors, variants/options, product identifiers, attributes, ratings/reviews, offer/commercial completion, publication, diagnostics, focused tests

## Goal

Recover deterministic, source-backed fields the current extractor still misses, and close the option/variant completeness gaps. Every accuracy, product-boundary, selected-state, lineage, and performance guarantee from the data-accuracy PR must survive unchanged.

## What Changed Before This Plan Starts

The data-accuracy PR pulled several PR 2 items forward because they were the largest generic clusters and were blocked on missing publication wiring rather than on extraction quality. Already delivered:

- **Product attribute publication.** `rating`, `review_count`, `materials`, `gender`, `condition`, `style_id`, and `barcode` had no fact-to-field path at all. They are now wired end to end (surface, publication, collector), including JSON-LD `aggregateRating`, `audience`, `gtin8/12/13/14`, and `productGroupID`.
- **schema.org enumeration mapping** (`https://schema.org/Male` becomes `Men`).
- **Audience gender from the requested PDP path**, path-only, `unisex` first.
- **Parent SKU suppression narrowed** to values not declared at product scope.
- **Identity display contracts**: trademark symbols, host-derived site-name suffixes, identifier field labels.
- **Run 3 regressions**: the `215.00` to `2.15` price rescale, and Rockler's unpublished availability.

Measured effect on the owned replay: **303 to 205 non-variant failing assertions** (run 1/2 captures 303 to 196; run 3 captures 207 to 205). Both sides were measured with variant assertions inert, so the comparison is like for like; see Baseline for the restated absolute total.

## Baseline

- Fresh live crawl: `backend/artifacts/runs/3` (82 captures).
- External analysis: `docs/audits/crawlerai_run3_comparison.md`, `docs/audits/crawlerai_defects_run3.json` (146 defects, 54 failing cases).
- Local owned replay against run-3 captures: **288 failing assertions, 72 cases**, of which **83 are variant assertions** that the harness had never actually run (the gate required `variants` in a case's `expected`/`constraints`, but it is a top-level key). PR 1 fixed the gate; the 83 failures are pre-existing and are Slice 2 work.
- Non-variant assertions are 205. The counts differ from the external defect set because the harness also asserts regression-protection fields it does not score.
- Reproduce with `audit_artifact_quality_cases(refs, backend_root=..., partitions=None)` against `crawlerai_eval_html_grounded_v3_2.json`.

Remaining assertions by field:

| Field | Count | Field | Count |
| --- | ---: | --- | ---: |
| `color` | 29 | `currency` | 6 |
| `title` | 25 | `gender` | 5 |
| `brand` | 25 | `size` | 4 |
| `sku` | 19 | `size_options` | 4 |
| `material` | 18 | `condition` | 3 |
| `price` | 15 | `original_price` | 3 |
| `variant_count` | 10 | `product_id` | 2 |
| `availability` | 9 | `barcode`, `mpn`, `model_options` | 1 each |
| `rating` | 8 | `price_max`, `price_min`, `product_family` | 1 each |
| `style_id` | 7 | | |
| `review_count` | 7 | | |
| `variants` | 83 | | |

## Approaches Already Measured and Rejected

Do not retry these blind. Each was measured against the failing cases:

| Approach | Result |
| --- | --- |
| `dt`/`dd` and `th`/`td` spec-table collector | 3 exact matches across **all** attribute fields — not worth a collector |
| Page-wide fibre-composition regex for `material` | 1 correct, **14 wrong** — the first composition-shaped match is usually unrelated |
| `title` tokens for `gender` | 9 correct, 0 wrong — superseded by the URL-path rule (15 correct, 0 wrong) |
| Preferring the longer title candidate | Reference expectations contradict each other: case 44 wants the longer, case 61 the shorter |
| Casing normalization for `color`/`brand` | Expectations point in both directions: case 25 wants `Black` from `black`, case 12 wants `black/...` from `Black/...` |

## Inherited Review Findings (verified, not yet fixed)

Raised on PR 1 and deliberately deferred: each concerns code that predates that PR's
work, and none arrived with a reproduction. Confirm with a failing case before
changing offer or variant selection semantics.

| Location | Concern |
| --- | --- |
| `core/records/title_normalization.py` two-segment pipe rule | Strips a trailing segment on word count/length alone, so `Jacket | Red` can lose a colour before URL corroboration runs |
| `extraction/entities.py` selected group merging | Selected URL evidence is appended to every matching candidate; multiple structured variants can each absorb the same selected shell |
| `extraction/resolution/variant_rollup.py` selected price | The selected-variant price aggregate ignores `existing_fact_keys`, so it can overwrite a resolved primary offer price |
| `extraction/collectors/dom.py` `parse_money` | Called without a locale hint, so `1.234` and `1,234` both admit as `1234` before page locale is known |
| `extraction/collectors/jsonld.py` selected variant | Compares resource identity only, so variants differing solely by `?style=` query can all be marked selected |
| `config/extraction_rules/_variants.py` DOM axes | `colorcode`/`colorproductcode` are absent from `VARIANT_DOM_URL_AXIS_PARAM_PATTERN`, dropping the style axis |
| `harness/artifact_quality_cases.py` projection | `asin` falls back to `product_id` and `style_id` to `mpn`, letting one field satisfy another's assertion |
| Reference case 79 | Asserts `rating`/`review_count` as exact values while every other case treats them as volatile |

## Slices

### Slice 1: Selected State From the DOM (largest cluster)

**Status:** TODO
**Owns:** `color` 29, `size` 4, part of `variant_count`
**Why first:** 19 of 20 previously analysed missing colours encode **no** colour axis anywhere in the requested or served URL, and structured sources expose several colours at once (case 11 offers White, Black and Dark Brown under one `hasVariant`). Choosing among them requires reading which option the page marks as selected.
**What:** Read explicit selected-option state from the rendered DOM — `aria-selected`, `aria-checked`, `[selected]`, `checked`, and the platform-neutral current-option patterns already present in the captures. Bind it to the same-product variant set and publish only when exactly one option is marked. Fail closed on zero or multiple.
**Still out of scope:** clicking options, new capture strategies, or any acquisition change. If the capture does not mark a selection, the case stays open.
**Verify:** Focused selected-state tests plus the colour/size partitions; no regression in the URL-axis precedence rules from PR 1.

### Slice 2: Variant and Option Completeness

**Status:** TODO
**Owns:** `variants` 83, `variant_count` 10, `size_options` 4, `model_options` 1
**What:** Nike is 25 vs 24, H&M 10 vs 50, New Balance 48 vs 146, and case 25 collapses seven sizes to one. Recover complete same-product matrices from structured and first-party state; allow one-axis DOM controls only when each option is purchasable with option-level evidence. Add option **unit** normalization (MAC case 77 returns `0.05 oz` where the reference expects `1.5 g`).
**Verify:** Variant resolution/publication tests plus the affected cases and existing correct variant cases.

### Slice 3: Material and Remaining Attributes

**Status:** TODO
**Owns:** `material` 18, `condition` 3, `gender` 5
**What:** Material's real sources are product-description bullet lists and meta-description prose. Build a **scoped product-description collector** (product root section only) rather than the page-wide regex that already measured 1 correct / 14 wrong. Reject navigation, size guides, reviews and recommendations.
**Verify:** Focused scope tests proving the collector cannot read outside the product section, plus the attribute partition.

### Slice 4: Commercial Completion

**Status:** TODO
**Owns:** `price` 15, `availability` 9, `currency` 6, `original_price` 3, bounds 2
**What:** Peloton (case 40) publishes no price, currency, availability or SKU because its capture holds no commercial evidence — confirm whether that is a capture gap or an unread first-party payload before changing logic. Apple case 34 family bounds remain unresolved. Re-capture the price-drift cases (9, 18, 45, 47, 71, 73, 74, 80) before treating them as defects; they are live retail changes, not extraction faults.
**Verify:** Offer/commercial tests plus the commercial partition, with the PR 1 sibling-availability and price-rescale guards intact.

### Slice 5: Identity Display Contract

**Status:** TODO
**Owns:** `title` 25, `brand` 25
**What:** These need a **generic display/semantic contract**, not more rules. The reference expectations contradict each other on casing and on title length, so the contract must state which source is authoritative for a product name and how display case is decided, before any code changes. Produce the contract first; if no truthful generic contract exists, record these as permanently capture-limited rather than adding retailer aliases or casing tables.
**Verify:** Whatever the contract specifies, plus no regression in the trademark, site-suffix and identifier-label rules from PR 1.

### Slice 6: Type Contract and Close

**Status:** TODO
**What:** `rating` and `review_count` publish as strings, like `price`, while the canonical detail schema declares them numeric. Coercing at serialization trips the `PUBLIC_RESOLUTION_DIVERGENCE` guard, so the change belongs at fact-value normalization and needs a deliberate contract decision. Then record all before/after evidence, capture-limited cases, preserved PR 1 behaviour, and timing.
**Verify:** Full 82-case replay; `.\scripts\check.ps1`; `.\scripts\test.ps1`; `git diff --check`.

## Do Not Touch

- `frontend/**`, endpoints, database schema, listing, jobs, automobiles, downstream value repair, enrichment cleanup, or LLM value generation.
- Acquisition/browser/traversal and option clicking. Report absent source artifacts; do not expand capture scope inside this PR.
- Site-specific branches in generic extraction, a generic metadata blob collector, parallel eval runners, scheduled replay, or CI corpus gates.
- PR 1 targeting, selected-state, title/brand, commercial, and attribute rules except to fix a directly reproduced regression without weakening their tests.

## Working Method That Produced the PR 1 Results

Measure candidate sources against the failing cases **before** writing code, and record correct/wrong counts. Three of the largest clusters turned out to be missing wiring rather than extraction quality, and two obvious-looking rules were rejected on measurement. Prefer a rejected approach with numbers over an untested plausible one.

## Doc Updates Required

- [ ] `docs/audits/crawlerai-extraction-coverage-report.md` — before/after evidence, including measured-and-rejected approaches.
- [ ] `docs/BUSINESS_LOGIC.md` — only if public field semantics change, e.g. the rating/review-count numeric type decision.
- [ ] `docs/backend-architecture.md` and `docs/CODEBASE_MAP.md` — only for real ownership moves.

## Notes

- Accuracy wins over fabricated coverage. Missing is acceptable when evidence is absent or ambiguous; a wrong price, stock state or sibling product is not.
- Extraction-package LOC/complexity budgets in `backend/app/core/config/extraction_semantic_surface.toml` are downward ratchets and are currently saturated. Prefer extracting a module over growing one, and document any budget change in the architecture test.
- Amazon case 55 returning no product is correct behaviour for an anti-automation shell, not a defect to fix.
