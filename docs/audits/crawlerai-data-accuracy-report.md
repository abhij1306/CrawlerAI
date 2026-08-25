# CrawlerAI Data Accuracy Review — HTML-Grounded v3.2

**Date:** 2026-08-25  
**Status:** implementation in progress

## Baseline

- 82 unique evaluation cases; 80 HTML-grounded and 2 fallback/capture-limited cases.
- 75 failing cases and 257 field defects in the canonical v3.2 references.
- PR 1 owns four area totals: 4 product identity/page state, 49 selected state, 42 commercial, and 16 core identity defects.
- Zara cases 24 and 62 are the only normalized-URL duplicate. Both remain independent assertions and map deterministically to their captures.
- The former v2 compact references were deleted after version, count, partition, duplicate, and capture mapping checks passed.

## Prior Work Review

Retained generic behavior:

- query/path selected axes and selected-offer precedence;
- `coming_soon` availability;
- product title/URL identity ranking;
- base-PDP and variant-suffixed URL compatibility;
- serialized `variant_count` truthfulness;
- removal of variant-SKU-to-parent-product rollup.

Removed behavior without a truthful generic contract:

- conjunction-based family title detection;
- sibling parent-offer aggregation;
- selected-variant color synthesis into the parent product;
- OpenGraph site name promotion to manufacturer brand;
- misplaced commercial and variant-selection helper ownership.

## Implemented Generic Changes

- The harness now reads only the two v3.2 references and captured extractor inputs. It reports fallback cases and capture hashes and validates all reference invariants.
- URL-selected color, fit, style, SKU, and path axes are config-owned and survive entity assembly.
- A unique structured variant can bind to URL-selected state across differing source-subject aliases. Matching fails closed on zero or multiple candidates.
- Product representations can merge when a base PDP and its identity-bearing variant suffix refer to the same product.
- Clean extracted titles are no longer penalized for a site suffix already removed during normalization, and URL-derived title shells receive a review penalty.
- Selected offers can supply the current display price while incomplete variant sets do not invent aggregate bounds.
- Product color mappings cover standard structured, microdata, OpenGraph product, and DOM evidence without host rules.
- Variant identity primitives now live under `core/records`; entity assembly remains within repository size and complexity limits.
- Query-selected axes are whitespace-normalized, selected-state correlation uses alphanumeric token boundaries, and removed variant groups cannot participate in a second merge.
- Capture matching prefers compatible query state and now requires strong token or product-slug relation before fuzzy fallback. Review metrics use volatile constraints instead of frozen snapshots.
- DOM prices inside links to a different product URL are rejected before offer ownership. This prevents deeply nested cross-product cards from competing with the current PDP.
- Canonical and wrapped PDP paths can bind through the same host and final product-marker identity. Parent-offer selection then prefers target-matched offer URLs over unidentified siblings.
- URL fragment axes are preserved. Multi-member style/color selections retain every compatible member and publish a selected price only when those members agree.
- Aggregate `lowPrice` is a lower bound rather than a current price. Nested offers bind to same-product variants by exact URL, exact URL selection outranks unidentified offers only when selected state supports it, and uniform selected color/size values can publish with lineage.
- Product-level offers from different structured sources can share one target identity only through an exact requested URL/marker or exact product ID. This joins compatible current/original price, currency, availability, and bounds while rejecting conflicting sibling URLs.
- An exact-target aggregate outranks sibling offer URLs. Equal aggregate bounds publish as an exact current price, and availability rolls up only when declared `offerCount` matches a complete child list with one unanimous state.
- Title cleanup remains narrow: only a terminal audience suffix is treated as pollution; no broad multi-segment title heuristic was added.

## Current Replay

The owned-partition replay has 68 failing cases and 153 failing assertions, down from
69 cases / 161 assertions before the identity display contracts landed. Remaining
area-counted assertions are:

| Area | Baseline defects | Remaining assertions |
| --- | ---: | ---: |
| Product identity/page state | 4 | 2 |
| Selected variant state | 49 | 32 |
| Commercial fields | 42 | 22 |
| Core identity | 16 | 17 |

### Identity display contract (this slice)

Trademark and service-mark symbols (`®`, `™`, `℠`) are legal notation attached to a
name rather than part of it, and sources disagree on whether they appear at all: the
same product arrives as `Millennium Falcon® 75192` in the DOM heading and
`Millennium Falcon 75192` in JSON-LD. `DETAIL_IDENTITY_TRADEMARK_SYMBOL_PATTERN` is now
config-owned and applied to published title and brand values only; descriptions and
other prose keep their source punctuation.

The symbol still carries real information — it marks where a brand name ends — so the
marker-driven brand rules read the pre-normalization `Evidence.raw_value` instead of the
published title, and `infer_brand_from_title_marker` strips the symbol from the brand it
returns. Without that split, normalizing the title silently destroyed the boundary
signal and `brand_from_product_url` stopped recovering a URL-corroborated brand.

Fixed: case 45, 48 (title + brand), 76 titles; case 44 and 56 brands. No case regressed.

### Host-derived site-name suffix (this slice)

A trailing separator-delimited segment that merely repeats the site's own name
(`... | Karen Millen ROW`, `... - Apple`, `... | Canon U.S.A., Inc.`) is boilerplate
rather than product identity. The previous rule recognised it through a small
whitelist of terminal words, so it missed most sites and could not grow without
becoming a retailer table.

`strip_detail_title_site_suffix` now derives the site name from the page host:
`host_identity_keys` collapses the registrable host and each meaningful label to
alphanumeric keys, and a trailing segment is dropped when its key equals, extends, or
abbreviates one of them. That covers a regional or legal tail (`Karen Millen ROW`,
`Canon U.S.A., Inc.`) and an abbreviated site name (`B&H` for `bhphotovideo`), while a
trailing style code (`- DIME2SP2542BLK`) or colourway (`- Contour Silver`) does not
match the host and is preserved. No retailer is named anywhere in the rule.

It runs after the existing marketplace-prefix and breadcrumb rules, so those still see
the full title; running it first defeated the three-segment breadcrumb rule and
regressed case 49.

### Identifier field labels (this slice)

A DOM cell often delivers an identifier together with its own label (`Item # 77295`)
because label and value share a container. The label is page furniture, never part of
the identifier, so `strip_identifier_label_prefix` removes a leading alphabetic label
terminated by `#` or `:` **and** followed by whitespace. The whitespace requirement
keeps a genuine identifier such as `ABC:123` intact. Applied to product/variant SKU and
MPN facts during evidence normalization. This recovered both `sku` and `mpn` on case 41.

### Ownership move

Title display rules moved out of `url_identity.py` into
`app/core/records/title_normalization.py`, which now owns host-derived site boilerplate,
marketplace prefixes, breadcrumb separators, and trademark notation. `url_identity.py`
re-exports them, so importers are unchanged. This kept both modules inside their LOC
budgets and gives title display a single owner. The move was verified behaviour-neutral
against the replay (identical failure set).

Area assertions are regression-aware and overlap; they are not a unique-field count. Core identity exceeds its original defect count because replay also protects previously correct title/brand fields in affected cases.

Three warm full replays produced p95 extraction times of 1698.571 ms, 859.509 ms, and 1103.838 ms. The first run includes process warm-up. No pre-change v3.2 timing snapshot exists, so the plan's 20% comparison cannot be claimed.

The latest post-selected-availability replay measured 760.276 ms p95. It is a single observation under variable local load, not a replacement for the three-run closeout gate and not a stable performance comparison.

Cases 21 and 55 remain capture-limited. No external fallback value was used as extractor input.

## Product Attribute Publication (PR 2 slice, pulled forward)

The largest cluster in the full v3.2 reference was not a resolution defect: five
standard product attributes had **no publication path at all**. `rating`,
`review_count`, `materials`, `gender`, and `condition` were absent from the
fact -> field map, and `product.material` was an allowed fact type that nothing
published. Every assertion on them therefore failed regardless of source quality.

Measured against the captures before building anything, JSON-LD alone carried the
expected value for 25/30 ratings, 26/30 review counts, 15/30 materials and 8/26
genders, which justified a structured-source slice rather than DOM heuristics.

What landed, all source-driven and platform-neutral:

- product-level attribute facts (`product.rating`, `product.review_count`,
  `product.material`, `product.gender`, `product.condition`, `product.style_id`)
  with surface, publication, and collector support;
- JSON-LD harvesting of the nested `aggregateRating` node and of `audience`
  gender, alongside the flat attribute keys;
- schema.org enumeration mapping, so `https://schema.org/Male` publishes as `Men`
  and `NewCondition` as `New` - only the final token of the enumeration carries
  meaning, in bare or URL form;
- `gtin8/12/13/14` mapped to the GTIN fact, and that fact published as `barcode`,
  which is the name the canonical ecommerce-detail schema uses (`gtin` was never a
  canonical detail field);
- `productGroupID` published as `style_id`.

### Parent SKU suppression was too broad

`parent_sku_is_variant_specific` suppressed any product SKU that also appeared in a
variant, which silently dropped 16 correct values. The rule exists to stop a variant
SKU being promoted to the parent, so it now applies only to values that did not come
from product scope: a SKU the product node itself declares is the product's own
identifier even when one of its variants repeats it.

### An alias is not a publication path

The first attempt published `barcode` by copying the `gtin` value onto the record
after serialization. That produced `PUBLIC_RESOLUTION_DIVERGENCE`
(`unauthorized_public_field`) and suppressed whole records, because every published
value must come from an authorized projection carrying lineage. The fix was to map
the fact to the field properly. Worth recording: the divergence guard did exactly
its job and caught the shortcut.

### Result

| Field | Before | After |
| --- | ---: | ---: |
| `review_count` | 30 | 7 |
| `rating` | 30 | 8 |
| `style_id` | 22 | 7 |
| `material` | 30 | 18 |
| `sku` | 26 | 18 |
| `gender` | 26 | 20 |
| `barcode` | 6 | 1 |
| `gender` | 26 | 5 |
| **All fields** | **303** | **196** |

Full-reference replay across both PR 2 slices: 303 -> 196 non-variant failing
assertions, 78 -> 68 failing cases. No field regressed. See "Correction: Variant
Assertions Were Never Being Checked" for the restated absolute totals. Two `style_id` and two `sku` edge cases are documented below.

### Ownership moves

Publishing six new attributes pushed `jsonld.py` and `publication.py` past their
line baselines, which are downward ratchets. Rather than grow either module,
product-level fact emission moved to `collectors/jsonld_attributes.py`, the
publish/suppress rule to `publication_policy.py`, and attribute value normalization
to `core/records/attribute_normalization.py`. All three moves were verified
behaviour-neutral against the replay (identical failure set).

## Audience Gender From the Requested Path (PR 2 slice)

With structured gender exhausted (18 of 26 captures expose none), the remaining
question was whether a non-structured source could be trusted. Four candidates were
measured against the failing cases before writing any code:

| Candidate source | Correct | Wrong |
| --- | ---: | ---: |
| `<title>` tokens | 9 | 0 |
| URL path tokens | 14 | 1 |
| URL path, `unisex` first, path-only | 15 | 0 |
| Composition regex for `material` (for comparison) | 1 | 14 |

The retailer's own PDP path is an explicit audience statement, so
`audience_gender_from_path` reads it, with two rules that the measurement forced:

- **path only** - a query string carries variant and tracking state that often names
  an unrelated department;
- **`unisex` outranks a gendered marker** - a unisex product is frequently reachable
  under a gendered department.

A third rule came from case 12, where the site redirected
`/chuck-taylor-...-unisex-high-top-shoe/` to `/...-womens-high-top-shoe/`. The
requested path states the product the caller asked for, so it wins and the served URL
is only a fallback - the same precedence already used for selected variant axes.

Result: 15 assertions fixed, **no regressions**. Gender 26 -> 5.

### Material was measured and rejected

The same method killed the obvious material rule. A fibre-composition regex
(`100% Cotton`, `Polyester 100%`) scored 1 correct against 14 wrong, because the first
composition-shaped match on a page is usually unrelated. Material's real sources in
these captures are description bullets and meta-description prose, which need a
scoped product-description collector rather than a page-wide pattern. Left open
deliberately.

### Spec tables were measured and rejected

`<dt>/<dd>` and `<th>/<td>` pairs were re-measured against the current failures and
yielded 3 exact matches across all attribute fields combined - not enough to justify a
collector. The earlier note suggesting this as an opportunity is superseded.

## Run 3 Regression Fixes

A fresh live crawl (`backend/artifacts/runs/3`, 82 captures) was analysed in
`docs/audits/crawlerai_run3_comparison.md`. Against run-3 captures the owned replay
started at 207 non-variant failing assertions and ends at **205**, with the two named engineering
regressions fixed and nothing new failing.

### Price rescaled to a hundredth of its value (case 5, P0)

DTLR published `2.15` for a `$215.00` shoe. The page states the price three ways:
Shopify `ProductJson` in cents (`21500`), a JSON-LD offer (`215.0`), and DOM text
(`$215.00`). Twelve derived facts correctly produced `215.00`; one produced `2.15`
and won publication.

`repair_price_unit` rescales a value only when it looks integral and a peer
corroborates the result, but `Decimal("215.0")` is integral, and the corroboration
test reuses the parent/variant price-spread ratio (max 2x). A junk sibling DOM price
of `4` sat within 2x of `2.15`, so the rescale was "corroborated".

The fix is a source-shape guard rather than a tolerance change: **a value whose raw
text printed its own fractional digits is already stating major units and is never a
minor-unit candidate.** The guard accepts one or two fractional digits (`215.0`,
`215.00`) and requires the digits before the separator to equal the parsed whole
amount, so a grouping separator such as `21.500` (which parses to 21500) is still
eligible for repair. Genuine minor-unit integers (`21500`) still repair.

### Availability resolved but never published (case 41)

Rockler resolved `in_stock` on a structured offer while price and currency resolved
on the DOM offer, and only the primary offer reaches the record. `sibling_offer_availability_facts`
now lets the primary offer inherit an availability it never stated, when the product's
other offers agree on exactly one value.

It fails closed twice: on any disagreement, and on **any product that has variants**.
The first attempt omitted the variant guard and gave case 78 a wrong `in_stock` where
the selected size was out of stock - a wrong stock state is worse than an absent one,
so variants (which carry their own stock state) now block inheritance entirely.

### Not regressions

- **Amazon case 55 returning no product is correct.** The capture is an anti-automation
  shell page and `HTTP_SHELL_TITLE` blocks it. Publishing the URL slug as a product,
  which the previous run did, is the defect; truthful omission is the fix. The
  behaviour is pinned by `test_url_slug_is_not_published_from_anti_automation_shell`.
- **Cases 9, 18, 45, 47, 71, 73, 74, 80** are live price drift between captures, not
  extraction changes. Case 45 (Fender) is the only previously clean case now failing
  and its sole failure is a price change. These need re-capture, not logic changes.

### Still open from run 3

- **Peloton case 40** publishes no price, currency, availability or SKU because the
  capture contains no commercial evidence at all - a capture/coverage gap, not a
  resolution defect.
- **MAC case 77** size options changed from gram to ounce units; option unit
  normalization is unowned.
- **Apple case 34** family bounds remain unresolved.

## Correction: Variant Assertions Were Never Being Checked

Review of this PR found that `_variant_failures` never ran. The gate is
`"variants" in fields`, but `_requested_fields` only returns members of a case's
`expected`/`constraints` maps, and the variant specification is a **top-level** case
key. Thirty-one cases declare one, so every variant count, required-field and example
assertion in the reference was silently skipped.

The harness now admits `variants` explicitly. Enabling it exposes **83 additional
failing assertions** that were always failing but invisible.

This changes the reported totals, so they are restated precisely:

| Measure | Before | After |
| --- | ---: | ---: |
| Non-variant assertions (measured both sides) | 303 | 205 |
| Variant assertions (never previously checked) | not run | 83 |
| **True current total** | — | **288** |

The 303 to 205 improvement stands: both sides were measured with variant assertions
inert, so the comparison is like for like. What was wrong was the **absolute** figure,
which understated the true failure count. The 83 variant failures are pre-existing and
are the first item of PR 2 work.

## Review Findings Addressed

Fixed after verification against current code:

- `_variant_size` no longer infers a size from a comma-less product name; the fallback
  split had returned the whole name.
- JSON-LD gender read from an `audience` node records `<path>/audience/<key>`, and
  `audience` is now read in both its object and **array** forms.
- Image locators keep the source list index, and a scalar `image` addresses
  `<path>/image`.
- The volatile constraint mode was price-shaped: it required a positive value **and** a
  currency, so case 71's legitimate `0.0` rating could never pass. It is now
  field-aware — money needs a positive value and a currency, a rating or review count
  only needs a real non-negative number.
- `strip_identifier_label_prefix` handles a label with no space after the delimiter
  (`SKU:BT-1MW`) for known label words only, so `ABC:123` is still preserved.
- CodeQL high (`py/incomplete-url-substring-sanitization`): the harness test fake
  matched a host by substring and now compares the parsed hostname.
- The dead `url_identity` re-export was removed and callers point at the owning module.

Rejected after verification, with reasons:

- **Gating the `" - a - b"` size form on a declared size axis.** This breaks
  `test_jsonld_variant_name_recovers_explicit_size_segment`, which deliberately trusts
  the explicit three-segment form without `variesBy`. The concern was raised without a
  failing case; only the looser comma fallback is gated.
- **Protocol `...` bodies read as ineffectual statements.** A docstring-only body
  implicitly returns `None` and breaks the declared return types. `...` is the correct
  idiom; the finding is a false positive.

Deferred to PR 2 with reasons recorded in that plan: the two-segment pipe rule, selected
group merging in `entities.py`, selected-variant price aggregation versus
`existing_fact_keys`, DOM `parse_money` locale, JSON-LD selected-variant identity
comparison, the `colorproductcode` DOM axis, the `asin`/`style_id` projection
fallbacks, and reference-data inconsistencies in case 79. Each concerns code that
predates this session's work, and none arrived with a reproduction; changing offer or
variant selection semantics without one risks exactly the regressions this plan
guards against.

## Documented Edge Cases

Deliberately left open; each needs a source contract that the current evidence does
not support:

- **style_id case 22** (`406329_02` expected, `406329` published) and **case 67**
  (`M108022W` expected, `M1080V15_RU-FTW-825428` published): `productGroupID` is the
  family identifier, which is coarser or differently composed than the expected style
  code on some platforms.
- **sku case 2** (`DIME2SP2542BLK-S` published for `DIME2SP2542BLK`) and **case 4**
  (`21001455` for `HJ0139-045`): the product node declares a variant-specific or
  internal SKU. Distinguishing it from a true product SKU needs a cross-source
  agreement rule.
- **rating/review_count** (8/7 remaining) and **material** (18): no JSON-LD source in
  those captures; recovery needs the DOM spec-table collector noted below.
- **gender** (5 remaining): neither a structured source nor an audience marker in the requested path.
- **`material` (18 remaining)**: description bullets and meta-description prose; needs a scoped description collector, not a page-wide regex.
- **`rating` and `review_count` publish as strings**, like `price`, while the
  canonical detail schema declares them numeric. Coercing at serialization would
  trip the divergence guard (the record value would no longer match its authorized
  projection), so the fix belongs at fact-value normalization and is left for a
  deliberate type-contract change. The evaluation compares numerically, so this is
  invisible there but visible to consumers.

## Measured Scope Limits

Two remaining clusters were investigated to source level and are recorded here so they
are not re-litigated as extraction defects:

- **Missing selected colour (20 assertions).** 19 of the 20 cases encode no colour axis
  anywhere in the requested or served URL, and the structured sources that do carry a
  colour expose several (case 11 publishes `White`, `Black`, and `Dark Brown` under one
  `hasVariant` set). Choosing among them needs DOM selected-state detection, which the
  plan places outside this PR ("Do Not Touch": acquisition, option clicking, new capture
  strategies). Only case 2 exposes a colour generically, via a `<dt>Color</dt><dd>` pair;
  13 of 89 captures contain such spec pairs, so a definition-list/spec-table collector is
  a real generic opportunity but belongs with the coverage PR that also owns the
  `material`, `gender`, and identifier fields those same tables carry.
- **Case-only title/brand differences.** Four colour assertions and several brand
  assertions differ from the capture only by letter case, and they disagree on direction
  (case 25 expects `Black` from a source `black`; case 12 expects `black/new found bloom`
  from a source `Black/New Found Bloom`). No casing rule can satisfy both, so these stay
  open pending the generic display contract the plan already calls for, rather than a
  casing table or retailer aliases.

## Open Work

- Exact title/brand display differences need a generic semantic/display contract, not retailer aliases or casing tables.
- Missing selected attributes and identifiers need source-owned coverage. They must not be synthesized from a selected child into parent facts.
- Remaining wrong price/availability cases need compatible offer-subject evidence and atomic source selection.
- Configurable family bounds remain open where the capture does not prove a complete same-product offer set.

Selected variant availability now outranks mixed sibling state only when every selected member agrees. The retained generic change reduced remaining commercial assertions from 24 to 22 without changing the 69-case failure count; those repaired cases still fail other owned assertions.

The repository static gate passed. The first affected-test selection found the reference directory lacked a production mapping; `scripts/validation.json` now maps it to `test_artifact_quality_cases.py`. The required retry-delta backend and frontend tests passed. Focused harness, identity, ranking, and architecture tests also passed.
