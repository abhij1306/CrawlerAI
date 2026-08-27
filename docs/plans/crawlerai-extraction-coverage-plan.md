# Plan: CrawlerAI Source-Backed Extraction Coverage

**Created:** 2026-08-25
**Revised:** 2026-08-27 after the run-5 version comparison and Amazon regression analysis
**Agent:** Codex
**Status:** COMPLETE — core slices and run-5 regression hardening verified
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
| Merging selected variant state only on a single unambiguous candidate (carried finding #8) | **Regression.** A style-axis selection legitimately spans a whole colourway: case 67's `dwvar_..._style=M108022W` matches 16 size groups. Skipping the merge took case 67's price from `169.99` to `199.99` and lost its colour. The match count already tracks selection specificity - a size-specific selection matches exactly one group - so the existing behaviour is correct by construction |
| Gating the selected-variant price aggregate on `existing_fact_keys` | **Regression** in cases 25 and 67: both expect the selected variant's price, and the guard publishes the page-level price instead. The override is intentional - a selected variant's price is more specific. The unused parameter was removed and the intent documented instead |
| Passing a page-URL locale hint to `parse_money` in the DOM collector | **Rejected on analysis.** The reviewer's example (`1.234` vs `1,234`) is already read correctly without a hint: a three-digit final group is a thousands group either way. The hint only changes mixed-separator values, where the locale-blind "last separator wins" reads the formatting the page actually used - the country rule would turn a correct `1,234.56` into `1.23456` on a `.de` host that uses US formatting |

## Inherited Review Findings (complete set from PR 1)

All 14 CodeRabbit findings raised on PR 1, with disposition. Six were fixed in that
PR; the rest are carried here. Nothing was silently dropped.

| # | Location | Finding | Status |
| --: | --- | --- | --- |
| 1 | `config/extraction_rules/_variants.py` DOM axes | `colorcode`/`colorproductcode` are absent from `VARIANT_DOM_URL_AXIS_PARAM_PATTERN`, so the style axis is dropped and different selected variants can compare equal in `target_offer_group_id` | **Fixed** (carried-findings PR) |
| 2 | `core/shared/field_coerce_text.py` identifier labels | A label with no space after the delimiter (`SKU:BT-1MW`) was not stripped | Fixed in PR 1 (known label words only, so `ABC:123` survives) |
| 3 | Reference case 71 rating constraint | `volatile` mode was price-shaped: it required a positive value **and** a currency, so a legitimate `0.0` rating could never pass | Fixed in PR 1 (constraint mode is field-aware) |
| 4 | Reference case 79 | Asserts `rating`/`review_count` as exact values while every other case treats them as volatile, contradicting the reference's own rule | **Fixed** — owner chose volatile; case 79 now matches the other 24 |
| 5 | `collectors/jsonld_attributes.py` numeric types | `text_value` stringifies `rating`/`review_count`; the canonical contract declares them numeric | **Fixed** — owner chose numeric; published via `CanonicalizationTrace`, which the divergence gate compares against |
| 6 | `collectors/jsonld_attributes.py` locators | Gender read from `audience` pointed at the product node; image locators re-indexed after filtering; a scalar `image` addressed `/image/0` | Fixed in PR 1 (also reads `audience` in array form) |
| 7 | `collectors/jsonld.py` offer grouping (~L275-291) | Product-scope offers with no offer URL but a hint URL normalizing to the target page all share the `offer:target` group instead of getting distinct fallback groups, merging distinct offers | **Fixed** — the target group is claimed only when exactly one URL-less offer can claim it |
| 8 | `extraction/entities.py` selected group merging (~L636) | Selected URL evidence is appended to every matching candidate before the source group is removed, so one selected shell can attach to several variants | **Rejected on measurement** — see the rejected-approaches table; regresses case 67 |
| 9 | `harness/artifact_quality_cases.py` projection | `asin` falls back to `product_id` and `style_id` to `mpn`, letting a value published under one field satisfy another field's assertion | **Fixed** — fallbacks removed; unmasked two real misses (cases 16, 68) |
| 10 | `harness/artifact_quality_cases.py` `_variant_failures` | Never ran: the gate needs `variants` in `expected`/`constraints` but it is a top-level case key, so 31 cases' variant assertions were skipped | Fixed in PR 1 — exposed **83** pre-existing failures |
| 11 | `harness/artifact_quality_cases.py` `_numeric_path_part` | Malformed capture directory names mapped to `0` and ranked alongside real captures | Fixed in PR 1 (non-numeric directories are skipped) |
| 12 | `docs/audits/crawlerai_defects_run3.json` case 55 | Counts anti-automation suppression as a `MISSING_PRODUCT_RESULT` defect, but no product output is the correct contract | **Fixed** — entry removed, derivable counts regenerated (146 -> 145 defects), `corrections` block added to the artifact |
| 13 | `core/records/url_identity.py` re-export | Compatibility re-export retained after title normalization moved to its owner | Fixed in PR 1 (removed; callers point at `title_normalization`) |
| 14 | `docs/BUSINESS_LOGIC.md` rating/review types | Public semantics record string publication for values the canonical schema declares numeric | **Fixed** — updated with #5 |

Two further suggestions were **rejected with reasons** and should not be re-applied
blind:

- Gating the explicit `" - a - b"` size form on a declared size axis breaks
  `test_jsonld_variant_name_recovers_explicit_size_segment`, which deliberately trusts
  that form without `variesBy`. Only the looser comma fallback is gated.
- Protocol `...` bodies flagged as ineffectual statements: a docstring-only body
  implicitly returns `None` and breaks the declared return types. `...` is correct.

Also carried from other reviewers (same rule applies — confirm with a failing case
before changing offer or variant selection semantics):

| Location | Concern |
| --- | --- |
| `core/records/title_normalization.py` two-segment pipe rule | Strips a trailing segment on word count and length alone, so a genuine colour or edition can be lost before URL corroboration runs — **Fixed** — the trailing segment is now dropped only when the page host corroborates it as the site's own name |
| `extraction/resolution/variant_rollup.py` selected price | The selected-variant price aggregate ignores `existing_fact_keys` and can overwrite a resolved primary offer price — **Rejected on measurement** (cases 25, 67); the unused `existing_fact_keys` parameter was removed and the intent documented |
| `extraction/collectors/dom.py` `parse_money` | Called without a locale hint, so `1.234` and `1,234` both admit as `1234` before page locale is known — **Rejected on analysis**; see the rejected-approaches table |
| `extraction/collectors/jsonld.py` selected variant (~L724) | Compares resource identity only, so variants differing solely by a `?style=` query can all be marked selected — **Fixed** — selection now requires the URL variant axes to match, the same rule `target_offer_group_id` applies |

## Slices

### Slice 1: Selected State From the DOM (largest cluster)

**Status:** DONE (2026-08-27). Generic DOM selected-state markers now bind
only to an existing same-product matrix and fail closed on ambiguity. Cases 51
and 61 recovered; unmarked and matrix-less captures remain missing.
Selected state is currently read only through one commerce platform's markup
(`VARIANT_DOM_ATTRIBUTE_CONTROL_SELECTOR` = `[data-attr-id][data-attr-value]`),
so pages using the platform-neutral standards are not read at all. Fix that
coupling. Of the 33 failing `color`/`size` assertions, 7 carry a standard
selected marker, 23 have the value present with nothing marking it as current
(stay open by design — guessing publishes a wrong colour), and 3 are
capture-limited. Full measurement in
`docs/audits/crawlerai-extraction-coverage-report.md`.
**Owns:** `color` 29, `size` 4, part of `variant_count`
**Why first:** 19 of 20 previously analysed missing colours encode **no** colour axis anywhere in the requested or served URL, and structured sources expose several colours at once (case 11 offers White, Black and Dark Brown under one `hasVariant`). Choosing among them requires reading which option the page marks as selected.
**What:** Read explicit selected-option state from the rendered DOM — `aria-selected`, `aria-checked`, `[selected]`, `checked`, and the platform-neutral current-option patterns already present in the captures. Bind it to the same-product variant set and publish only when exactly one option is marked. Fail closed on zero or multiple.
**Still out of scope:** clicking options, new capture strategies, or any acquisition change. If the capture does not mark a selection, the case stays open.
**Verify:** Focused selected-state tests plus the colour/size partitions; no regression in the URL-axis precedence rules from PR 1.

### Slice 2: Variant and Option Completeness

**Status:** DONE (2026-08-27). The full replay moved from 70 failing cases /
284 assertions to 70 / 257. Variant assertions moved 83 to 57,
`variant_count` 10 to 8, and `size_options` 4 to 3; `model_options` stayed at
1. The remaining mismatches lack a captured same-product matrix, disagree with
the source row count, or are the single-site case-77 unit conversion. See the
audit report for the per-case evidence.
**Owns:** `variants` 83, `variant_count` 10, `size_options` 4, `model_options` 1
**What:** Nike is 25 vs 24, H&M 10 vs 50, New Balance 48 vs 146, and case 25 collapses seven sizes to one. Recover complete same-product matrices from structured and first-party state; allow one-axis DOM controls only when each option is purchasable with option-level evidence. Add option **unit** normalization (MAC case 77 returns `0.05 oz` where the reference expects `1.5 g`).
**Verify:** Variant resolution/publication tests plus the affected cases and existing correct variant cases.

### Slice 3: Material and Remaining Attributes

**Status:** DONE (2026-08-27). The scoped rendered-detail collector recovered
eight material cases while rejecting navigation, guides, reviews,
recommendations, and unrelated overlays. Structured product condition/gender
and unanimous JSON-LD offer condition are wired; ambiguous or merely textual
condition/gender remains missing.
**Owns:** `material` 18, `condition` 3, `gender` 5
**What:** Material's real sources are product-description bullet lists and meta-description prose. Build a **scoped product-description collector** (product root section only) rather than the page-wide regex that already measured 1 correct / 14 wrong. Reject navigation, size guides, reviews and recommendations.
**Verify:** Focused scope tests proving the collector cannot read outside the product section, plus the attribute partition.

### Slice 4: Commercial Completion

**Status:** DONE (2026-08-27). Raw DOM price provenance is preserved. URL-less
schema Products bind through one same-resource Offer URL. Selected ProductGroup
children admit their parent matrix. Remaining commercial disagreements are
source drift, absent/unbound evidence, or ambiguous selection; no acquisition
or site-schema join was added.
**Owns:** `price` 15, `availability` 9, `currency` 6, `original_price` 3, bounds 2
**What:** Peloton (case 40) publishes no price, currency, availability or SKU because its capture holds no commercial evidence — confirm whether that is a capture gap or an unread first-party payload before changing logic. Apple case 34 family bounds remain unresolved. Re-capture the price-drift cases (9, 18, 45, 47, 71, 73, 74, 80) before treating them as defects; they are live retail changes, not extraction faults.
**Verify:** Offer/commercial tests plus the commercial partition, with the PR 1 sibling-availability and price-rescale guards intact.

### Slice 5: Identity Display Contract

**Status:** DONE (2026-08-27). The semantic title and explicit-brand contract is
documented and implemented. Source spelling/case is preserved; no retailer
aliases or fixture-driven display synthesis was added.
**Owns:** `title` 25, `brand` 25
**What:** These need a **generic display/semantic contract**, not more rules. The reference expectations contradict each other on casing and on title length, so the contract must state which source is authoritative for a product name and how display case is decided, before any code changes. Produce the contract first; if no truthful generic contract exists, record these as permanently capture-limited rather than adding retailer aliases or casing tables.
**Verify:** Whatever the contract specifies, plus no regression in the trademark, site-suffix and identifier-label rules from PR 1.

### Slice 6: Type Contract and Close

**Status:** DONE (2026-08-27). `rating` publishes as a float and `review_count`
as an int via `CanonicalizationTrace`; the divergence guard compares against
`canonical_value`. All slice evidence, rejected approaches, capture/source
limits, replay measurements, and final repository gates are recorded in the
companion report.
**What:** `rating` and `review_count` publish as strings, like `price`, while the canonical detail schema declares them numeric. Coercing at serialization trips the `PUBLIC_RESOLUTION_DIVERGENCE` guard, so the change belongs at fact-value normalization and needs a deliberate contract decision. Then record all before/after evidence, capture-limited cases, preserved PR 1 behaviour, and timing.
**Verify:** Full 82-case replay; `.\scripts\check.ps1`; `.\scripts\test.ps1`; `git diff --check`.

### Post-close correction audit

**Status:** DONE (2026-08-27). A requirement-by-requirement audit after the
original close found additional generic source-reading defects. Direct product
state now materializes ID-plus-option leaves and nested `traits`/typed GTINs;
selected ProductGroup ownership propagates to child relations; JSON-LD variant
`gtin8/12/13/14` keys publish as barcodes; explicit named colors survive opaque
code filtering and malformed URL shade values; and schema.org
`StrikethroughPrice` is original price rather than current price.

The same existing 82 local captures moved from **70 failing cases / 228 fixture
disagreements** to **69 / 204**. This was deterministic replay, not a new crawl.
The remaining variant differences are absent/blank evidence, commercial data
declared only for one color, unrelated offer families, explicit source row-count
differences, or capture-time price/availability changes. No value was filled
from the reference.

### Post-close run-5 regression hardening

**Status:** DONE and verified (2026-08-27).

The corrected 81-to-79 version comparison uses **78 aligned products**. It
shows a real aggregate improvement, not a broad rollback:

- average populated top-level fields: **9.88 -> 12.88** (**+30.4%**)
- products with variants: **39 -> 45**
- total variant rows: **561 -> 751** (**+33.9%**)
- brand: **64 -> 69**; price: **68 -> 70**; currency: **69 -> 71**
- availability: **62 -> 66**; description: **71 -> 74**; SKU: **43 -> 49**
- newly broad fields include materials (34 products), colors (32), and
  ratings/reviews (28)

This pass fixes only reproduced regressions:

- Shopify MCP tool metadata could become a product description. MCP paths are
  now rejected as context noise. Sneaker Politics and Technics replay with
  their real product descriptions again.
- Zadig admitted sibling style families as variants (5 -> 15). Explicit parent
  SKU family evidence now excludes sibling SKU families; replay returns the
  five requested-style variants.
- Brilliant Earth lost explicit brand, SKU, MPN, offer price, currency, and
  availability because locale-prefixed JSON-LD ownership was rejected and
  title-derived `Secret` beat the site identity. Same-host locale-prefixed
  product URLs now retain target ownership; page-title site identity is
  available to brand resolution. Replay restores `Brilliant Earth`,
  `BE1D13065-14KY`, and the explicit offer.
- Amazon repeatedly acquired a title-only semantic shell. The extraction
  rebuild had also deleted platform-adapter production while leaving adapter
  config and artifact contracts behind. The Amazon platform adapter is restored
  as an evidence producer; its output still passes through Harvest -> Resolve
  -> Publish. Acquisition remains owned by the global curl -> Patchright ->
  Chrome ladder; the adapter adds no Amazon-specific browser policy. Exact
  run-5 result 229 replay remains correctly empty, while synthetic rich Amazon
  HTML proves adapter-to-publication coverage.

Final verification:

- `scripts/check.ps1`: passed Ruff, formatting, mypy, frontend checks, LOC, and
  complexity.
- focused regression coverage includes Amazon evidence publication, adapter
  architecture, brand identity, and both retained and excluded variant-family
  cases.
- repository-selected retry delta: **1,008 passed**; no frontend or E2E tests
  were selected.
- PR review hardening closed the remaining regression edges: selected URL axes
  now gate singleton JSON-LD offers; same-slug recommendation URLs cannot own
  the target; full-IRI `ProductGroup` types work; prose percentages and
  construction require material terms; only valid, product-unique GTINs can
  displace SKU as a derived variant ID; scalar JSON-LD pointers and replayed
  adapter metadata preserve source provenance; and DOM variant controls must
  sit inside verified, non-excluded product roots. The mapped retry delta passed
  **767 tests**.
- Amazon localized prices such as `€1.299,99` and `R$ 1.299,99` now retain the
  full amount through the shared price-token path and normalize to `1299.99`.
- one explicitly requested live Amazon detail crawl was run as run 7/result
  256. Global HTTP escalation reached browser acquisition, returned HTTP 200
  with usable content, and published one partial record in 10.05 seconds. The
  adapter supplied SKU `B0CSP8GZ5R`, brand `ZAP CASE`, price `289.00`, currency
  `INR`, and the primary image. No Amazon-specific acquisition override ran.
  The live run exposed a generic URL-title bug: a suffix after `/dp/<opaque-id>`
  was treated as product identity. Offline replay of the saved live page after
  the route fix publishes `Zapcase Back Case Cover for Motorola Moto G62 5G`
  instead of `ref=pd ci mcx mh mcx views 2 image`.

Not changed in this regression-only pass:

- StockX changed input target, so it is not a same-product regression.
- live price/stock differences and ROAM availability are observations, not code
  regressions.
- the large New Balance, H&M, and Ralph Lauren variant expansions need source
  validation before any reduction.
- five reported parent-SKU losses were `not_requested`; variant SKU promotion
  was not widened. North Face already replays with its captured SKU.
- `product_id` coverage remains separate new work; it was not used to inflate
  this pass.
- Uniqlo remains a separate missing acquisition result. No Uniqlo-specific
  behavior was added while the active request was Amazon.

## Do Not Touch

- `frontend/**`, endpoints, database schema, listing, jobs, automobiles, downstream value repair, enrichment cleanup, or LLM value generation.
- Acquisition/browser/traversal and option clicking, except the explicitly
  requested generic Amazon regression restoration above. Report other absent
  source artifacts; do not expand capture scope further inside this pass.
- Site-specific branches in generic extraction, a generic metadata blob collector, parallel eval runners, scheduled replay, or CI corpus gates.
- PR 1 targeting, selected-state, title/brand, commercial, and attribute rules except to fix a directly reproduced regression without weakening their tests.

## Working Method That Produced the PR 1 Results

Measure candidate sources against the failing cases **before** writing code, and record correct/wrong counts. Three of the largest clusters turned out to be missing wiring rather than extraction quality, and two obvious-looking rules were rejected on measurement. Prefer a rejected approach with numbers over an untested plausible one.

## Doc Updates Required

- [x] `docs/audits/crawlerai-extraction-coverage-report.md` — before/after evidence, including measured-and-rejected approaches.
- [x] `docs/BUSINESS_LOGIC.md` — only if public field semantics change, e.g. the rating/review-count numeric type decision.
- [x] `docs/backend-architecture.md` and `docs/CODEBASE_MAP.md` — only for real ownership moves.

## Notes

- Accuracy wins over fabricated coverage. Missing is acceptable when evidence is absent or ambiguous; a wrong price, stock state or sibling product is not.
- Size policy is repo-wide and lives in `scripts/validation.json` (`maxLines` 800, `maxPythonComplexity` 15), enforced in CI by `scripts/check.ps1 -Mode Limits`. The per-module LOC/complexity tables that used to sit in `extraction_semantic_surface.toml`, and the per-file debt ledgers in the architecture tests, were removed in favour of that single blanket rule. Prefer extracting a module over growing one; there is no per-file budget to document any more.
- An Amazon anti-automation shell must still publish no product. The restored
  adapter consumes successful global acquisition output; it does not own or
  alter acquisition escalation.
