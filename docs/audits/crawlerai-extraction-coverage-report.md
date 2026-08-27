# CrawlerAI Extraction Coverage — Evidence Report

Companion to `docs/plans/crawlerai-extraction-coverage-plan.md`. Records
before/after evidence for each change, including the approaches measured and
rejected. Newest section last.

## Pass 0: Carried Review Findings (2026-08-25)

Clears the review findings inherited from PR 1 before any coverage slice
starts, so slice measurements are not taken against a corpus with known
assertion defects in it.

### Baseline

Reproduced the documented start state before changing anything:

```
cases=82  failing_cases=72  assertions=288   (variants 83)
```

### Result

```
cases=82  failing_cases=72  assertions=290
```

The +2 is fully accounted for and contains **no extraction regression**:

| Movement | Cause |
| --- | --- |
| case 79 `rating`/`review_count` moved from `expected` to `constraints` | Finding #4 — same underlying miss, restated in the volatile form the other 24 cases use. Net zero. |
| cases 16 and 68 `style_id` newly failing | Finding #9 — both publish those values as `mpn`, and the harness was crediting `mpn` to `style_id`. Real misses, previously masked. |

### Fixed

| # | Change | Evidence |
| --: | --- | --- |
| 1 | `VARIANT_DOM_URL_AXIS_PARAM_PATTERN` is derived from `VARIANT_URL_AXIS_PARAMS` instead of hand-maintained beside it | The two had drifted: `colorcode`, `colorproductcode` and the `*displaycode` keys resolved bare but not in `dwvar_*`/`attribute_*` form, so a prefixed style axis was dropped and variants differing only by style compared equal in `target_offer_group_id`. Regression test asserts the prefixed forms resolve; it fails without the fix (axes came back empty). |
| 4 | Reference case 79's `rating`/`review_count` moved to `constraints` with `mode: volatile` | It was the only case of 25 asserting them exactly. Owner's decision. |
| 5, 14 | `rating` publishes as a float and `review_count` as an int, via `CanonicalizationTrace` | The canonical record declares them numeric (`NORMALIZER_DECIMAL_FIELDS` / `NORMALIZER_INTEGER_FIELDS`) but evidence arrives as source text. `CanonicalizationTrace` is the lineage-carrying seam and `divergence._values_equal` compares against `canonical_value`, so this is not the post-serialization alias that trips `PUBLIC_RESOLUTION_DIVERGENCE`. An unparseable value stays published as its source text. `BUSINESS_LOGIC.md` updated; `price` deliberately stays a string. |
| 7 | The target offer group is claimed only when exactly one URL-less offer can claim it | An offer with no URL of its own falls back to the page hint URL, so several such offers all normalized onto one group. Demonstrated: two product-scope offers priced `10.00`/in-stock and `18.00`/out-of-stock published the mixed record `price=10.00, availability=out_of_stock` — one offer's price beside the other's availability. |
| 9 | Harness `asin`→`product_id` and `style_id`→`mpn` projection fallbacks removed; `style_id` now requests itself | Unmasked two real misses (cases 16, 68). |
| 12 | `crawlerai_defects_run3.json` case 55 entry removed, derivable counts regenerated | Anti-automation suppression is the correct contract, not a `MISSING_PRODUCT_RESULT` defect. 146 → 145 defects, 54 → 53 failing cases. The artifact now carries a `corrections` block naming what was recomputed and what cannot be re-derived from the file alone. |
| — | Two-segment pipe titles drop the trailing segment only when the page host corroborates it | Shape alone cannot separate `"Product | Site"` from `"Product | Colourway"`; both are short. The URL-corroborated stripper already ran, but *after* the shape rule had discarded the segment. |
| — | JSON-LD selected-variant detection requires the URL variant axes to match | Resource identity alone marked every sibling selected, so the selected set was ambiguous and no variant-scoped value could publish. Demonstrated: two variants differing only by `?style=` published `color=None`; with the fix, the requested variant's `Red`/`20.00`. |

### Measured and rejected

Recorded in full in the plan's rejected-approaches table. Summary:

- **Finding #8** (merge selected state only on a single unambiguous candidate) —
  regresses case 67. A style-axis selection legitimately spans a colourway:
  `dwvar_..._style=M108022W` matches 16 size groups. Skipping the merge moved
  case 67's price from `169.99` to `199.99` and lost its colour. Match count
  already tracks selection specificity, so current behaviour is correct.
- **Gating the selected-variant price on `existing_fact_keys`** — regresses
  cases 25 and 67, which expect the selected variant's price. The override is
  intentional. The unused parameter was removed and the intent documented.
- **A page-URL locale hint for `parse_money` in the DOM collector** — the
  reviewer's `1.234`/`1,234` example is already read correctly without one, and
  the hint only changes mixed-separator values, where it can turn a correct
  `1,234.56` into `1.23456` on a `.de` host that uses US formatting.

### Still open

- Findings #2, #3, #6, #10, #11, #13 were fixed in PR 1.
- `canonical_variant_axis` and `VARIANT_URL_AXIS_PARAMS` disagree
  (`colorcode`, `colorproductcode`, `colorname`, `sku` canonicalize to `None`).
  A separate drift on the `structured_variant_state.py` path, not touched here.
- The DOM collector normalizes price text before the pipeline's
  `money_has_ambiguous_decimal` can see it, so the ambiguity flag cannot fire on
  DOM-sourced prices. Noted while rejecting the locale-hint change.

## Slice 1 pre-measurement: Selected State From the DOM (2026-08-25)

**Status: measured, not implemented.** The measurement is recorded as evidence
about the *captures*, not as a target. The reference corpus is development
guidance, not ground truth, so nothing below should be read as an assertion
count to hit.

### What the slice assumed

Slice 1 owns `color` 29 and `size` 4, on the reasoning that structured sources
expose several colours at once and that choosing among them requires reading
which option the page marks as selected.

### What the captures actually contain

All 33 failing `color`/`size` assertions were measured against every standard
selected-state marker — `aria-selected`, `aria-checked`, `aria-pressed`,
`aria-current`, `option[selected]`, `input[checked]`, `[data-selected]`, and
`selected`/`active` class tokens — comparing each marked node's text and value
attributes against the expected value.

| Outcome | Count | Cases |
| --- | --: | --- |
| Reachable via some selected marker | **7** | 10, 11, 31, 51, 61, 72, 74 |
| Expected value present in the capture, but no selected marker carries it | 23 | 1, 2, 4, 5, 6, 8, 9, 10, 12, 19, 20, 25, 26, 27, 29, 30, 35, 38, 56, 57, 67, 78, 79 |
| Expected value absent from the capture entirely | 3 | 39, 76, 82 — capture-limited |

Per-strategy, no single marker is close to load-bearing:

| Strategy | Unique hit | Hit among many | No match | Absent |
| --- | --: | --: | --: | --: |
| `class*=selected` | 2 | 1 | 13 | 17 |
| `option[selected]` | 0 | 2 | 7 | 24 |
| `aria-checked` | 0 | 2 | 0 | 31 |
| `aria-current` | 1 | 0 | 13 | 19 |
| `aria-selected` | 0 | 0 | 13 | 20 |
| `input[checked]` | 0 | 0 | 10 | 23 |
| `class*=active` | 0 | 1 | 25 | 7 |
| `[data-selected]` | 0 | 0 | 1 | 32 |

### Why the ceiling is 7, not 29

The 23 "present but unmarked" cases have the expected colour somewhere in the
HTML with **no element marking it as the current selection**. Selected state is
what distinguishes the requested colour from its siblings, so where the capture
does not mark a selection, no DOM rule can choose correctly — and guessing would
publish a wrong colour, which the plan ranks worse than publishing none.

The four cases that publish a *wrong* colour today (9, 29, 30, 67) are **not**
among the 7 reachable, so DOM selected state does not fix them either.

### Why the existing predicate cannot be extended into the win

`_attribute_control_selected` already reads a control's `selected` JSON key and
`selected`/`active`/`is-selected` classes, but it is only ever called on nodes
matching `VARIANT_DOM_ATTRIBUTE_CONTROL_SELECTOR`
(`[data-attr-id][data-attr-value]`). **All seven** reachable captures contain
zero `[data-attr-id]` elements, so no predicate change reaches them. Extending
the predicate with the ARIA and native markers was implemented and measured at
**+0 / -0** for exactly this reason, and was reverted rather than shipped
unexercised.

Capturing the 7 therefore requires a new collection path keyed on selected-state
markers and bound to the same-product variant set — a materially larger piece of
work than the slice describes, for 7 of 33 assertions.

### The architectural defect this exposes

The count is not the point. What the measurement surfaced is that CrawlerAI
reads selected state through **one commerce platform's markup convention**:
`VARIANT_DOM_ATTRIBUTE_CONTROL_SELECTOR` is
`[data-attr-id][data-attr-value], [data-attr-id][data-dvalue]`, a Salesforce
Commerce Cloud pattern. Pages that mark selection with the platform-neutral
standards — `aria-selected`, `aria-checked`, `aria-pressed`, `aria-current`,
`option[selected]`, `input[checked]` — are simply not read, whatever their
markup quality.

That is site-specific coupling in generic extraction code, which this codebase
rules out on principle. It should be fixed because it is wrong, independent of
how many reference assertions move: a correct extractor reads the web standard
for "this option is currently chosen", and falls back to vendor conventions,
not the other way round.

### Recommendation

Implement generic selected-state reading (see the handoff prompt for the shape).
The 3 capture-limited cases (39, 76, 82) should be recorded as capture-limited.
The 23 unmarked cases stay open by design: where a capture does not mark a
selection, choosing among siblings would publish a wrong colour, and a missing
value is preferable to a wrong one.

## Breadth analysis and the SKU identity defect (2026-08-25)

Prioritization principle for the remaining work: **a single site missing a few
fields is acceptable; a single field missing across many sites is not.** Breadth
across sites, not assertion count, decides order.

The 82 captures are effectively one host per case, so failing-case counts read
directly as sites affected:

| Field | Sites | Field | Sites |
| --- | --: | --- | --: |
| `color` | 29 | `variant_count` | 10 |
| `title` | 24 | `availability` / `style_id` | 9 |
| `brand` | 24 | `rating` / `review_count` | 8 / 7 |
| `variants` | 22 | `currency` / `gender` | 6 / 5 |
| `sku` | 19 | `size`, `size_options`, `condition`, `original_price` | 3-4 |
| `material` | 18 | `barcode`, `mpn`, `model_options`, bounds, `product_family` | 1-2 |
| `price` | 15 | | |

This reorders the plan: `sku` affects 19 sites and is not a named slice at all,
while several named slices are 1-4 site tails.

### SKU: a bare digit run outranks the merchant SKU

Of the 19 sites, 7 publish a wrong `sku`, and in **5 of those 7** the published
value is a pure-digit string while the expected value is alphanumeric:

| Case | Expected | Published | Published is all digits |
| --- | --- | --- | --- |
| 5 | `HQ7978-103` | `45993954738410` | yes |
| 31 | `PE1001550` | `100155080614` | yes |
| 66 | `395205_01` | `4099686132767` | yes |
| 71 | `4D3032G-PCG` | `198629014314` | yes |
| 4 | `HJ0139-045` | `21001455` | yes |
| 2 | `DIME2SP2542BLK` | `DIME2SP2542BLK-S` | no - variant SKU on the parent |
| 39 | `870543 4GAK3 1360` | `8705434GAK31360` | no - separator normalization |

Merchant SKUs and style codes carry letters and separators; bare digit runs are
barcodes, internal ids or database keys. Preferring an alphanumeric candidate
over a pure-digit one is generic, needs no site knowledge, and covers 5 sites.

**Historical measurement, superseded by the identifier-role contract below:**
only cases 66 and 71 pass
`validate_gtin`. Cases 5 and 31 are 14- and 12-digit values that *fail* the
checksum - barcode-shaped internal ids, not barcodes. A GTIN-only rule would
catch 2 of the 5; the digit-shape rule catches all 5. Use GTIN validation only to
decide whether an untyped digit run should populate `barcode`; an explicitly
declared GTIN keeps its stated role.


## Identifier roles and pooled subjects (2026-08-25, corrected)

Governing rule confirmed with the owner: **publish what the site exposes; invent
nothing and suppress nothing it stated.** `sku`, `mpn`, `gtin`/`barcode`,
`product_id` and `style_id` are distinct roles whose values may be all
different, all the same, or partly overlapping. Agreement between roles is a
fact about the page, not duplication to be cleaned up.

For an explicitly declared GTIN, checksum validation is a diagnostic and
candidate-ranking signal. It does not suppress a digits-only value with a valid
GTIN length; malformed lengths remain invalid and cannot publish as `barcode`.

### Measured and rejected under that rule

| Approach | Result |
| --- | --- |
| Prefer an alphanumeric `sku` candidate over a bare digit run | +0/-0, and invented policy. If the product node says the SKU is `100155080614`, that is the SKU. |
| Suppress a checksum-valid GTIN from `sku`/`mpn`, route to `barcode` | Regresses 4 sites. Cases 22 and 38 expect a GTIN **as** the `sku`; case 71 expects one **as** the `mpn`. |
| Treat `mpn == sku` as duplication | Not a defect. 11 of 82 sites publish one value in both roles because the JSON-LD declares both `/sku` and `/mpn` with it. |

The earlier "SKU vs barcode" framing in this report is superseded: the digit-run
pattern is real, but preferring against it is a judgement the extractor is not
entitled to make.

### The defect that survives: contradictory values pooled onto one subject

Per-variant identifiers are collected at product scope, so one product subject
asserts many mutually exclusive values for a single-valued field and resolution
picks a winner by rank. Case 5: fourteen distinct `[data-sku]` swatch values all
attach to one product subject, and one of them is published as the product's SKU
- something the site never stated.

One product subject carrying more than two distinct values for a single-valued
field:

| Fact | Sites | Worst single subject |
| --- | --: | --: |
| `product.title` | 66 | 35 distinct values |
| `product.sku` | 4 | 82 distinct values |
| `product.brand` | 2 | 23 distinct values |

This sits upstream of the `title` (24 sites) and `sku` (19 sites) gaps. Preferred
fix is to scope swatch/option evidence to its variant subject at collection;
failing closed on irreconcilable candidates is the fallback. `title` is a genuine
multi-candidate field and must be checked separately before any fail-closed rule
is applied to it.

## Identifier collection scope (2026-08-27)

Implemented the preferred upstream fix for DOM option controls. A `data-sku`
attached to a generic option control is now emitted as `variant.sku` on its own
variant subject with a `product_variant` relation. A product-level `data-sku`
node remains `product.sku`. Commercial size/SKU controls retain their existing
variant collector.

Exact non-URL identifier values now link one variant across source roles without
merging the roles themselves. This is needed when a DOM control labels a value
as its SKU while a structured source exposes the same value as the variant ID.
Both facts survive under their stated roles; the entity graph no longer creates
a duplicate variant.

### Before and after

The same 82 captures were replayed before and after. A pooled subject means one
product subject carries more than two distinct values for the named fact.

| Fact | Before sites / worst subject | After sites / worst subject | Result |
| --- | ---: | ---: | --- |
| `product.sku` | 4 / 82 | **1 / 3** | Variant-control leakage removed from cases 4, 5 and 77. |
| `product.title` | 65 / 35 | 65 / 35 | Intentionally unchanged; these are legitimate competing product-name sources, so title ranking remains enabled. |
| `product.brand` | 2 / 23 | 2 / 23 | Unchanged and outside identifier-control ownership. |

Case 47 is the one remaining `product.sku` row above the measurement threshold.
It contains three genuine product-scope candidates: JSON-LD `4147C002`,
microdata `EOS R5 BODY`, and visible DOM `SKU EOS R5 BODY`. None is variant
evidence, so collection scope must not suppress it.

The corpus result moved from 72 failing cases / 290 assertions to 72 / 288. The
same cases fail; case 4 recovered its `variant_count` and variant-list count
assertions because its six option identifiers no longer materialize as six
extra parent-scoped candidates. This is evidence about movement, not a gate.
Case 5 still publishes `19468100030` as the product SKU because its JSON-LD
explicitly declares that value at product scope. The fixture's preferred style
code does not authorize suppressing what the site stated.

### Performance and rejected implementation

The first correct implementation ran the full compound option-control selector
twice on every page. It preserved correctness but increased mean replay time
from 244 ms to **981 ms**, so it was rejected. The final collector first checks
for any `[data-sku]`, runs the compound selector only when needed, and reuses one
node set for suppression and variant emission.

Final replay timing was mean 249 ms, p50 186 ms, p95 692 ms, versus baseline
mean 244 ms, p50 177 ms, p95 580 ms. Focused identity, entity-linking,
publication and DOM-variant tests passed (70 tests).

Later current-code verification samples varied from 533 ms to 1212 ms mean.
Profiling the slowest observed case placed 4.60 of 5.81 seconds in the existing
JS-state embedded-payload scanner and 0.49 seconds in the entire DOM collector;
the option-identifier path was not the bottleneck. The immediately repeated
optimized sample above is therefore the relevant before/after comparison, while
the wider replay timing should not be treated as stable benchmark data.

Canonical validation passed: `scripts/check.ps1`; `scripts/test.ps1` selected 55
backend test files and passed all 685 tests (no frontend or E2E tests selected).

## Generic DOM selected state (2026-08-27)

Implemented a platform-neutral collection path for `aria-selected`,
`aria-checked`, `aria-pressed`, `aria-current`, native `option[selected]` and
native `input[checked]`. ARIA values are tri-state: explicit false emits false.
The existing vendor JSON/data/class path remains a lower-confidence fallback
and is ignored for an axis when standard state is present.

Selection signals do not create variants. Entity linking binds them only to an
existing same-product variant matrix. One distinct marked value per axis is
required; duplicate responsive controls for the same value are collapsed, but
conflicting states or several marked values fail closed. An unlabelled native
option/radio may infer its axis only when its value occurs on exactly one axis
in that product's matrix. Requested URL axes retain precedence, while a DOM
selection may refine another axis.

### Before and after

The same 82 captures moved from 72 failing cases / 288 failed assertions to 72
/ **286**. `color` failures moved from 28 to **26**; all other failure counts
remain unchanged. Cases 51 and 61 now publish the uniquely marked, site-stated
colors `Newport - Navy Gloss / Slate Trim` and `White/Track Unit TRK`.

The seven previously measured captures break down as follows:

| Cases | Outcome |
| --- | --- |
| 51, 61 | Existing matrices bind uniquely; selected color now publishes. |
| 10, 11, 31 | No same-product variant matrix exists, so DOM state cannot synthesize one. |
| 72 | Several marked vendor values and no compatible matrix axis; fails closed. |
| 74 | The product color marker is explicitly false; zero selected values fails closed. |

The generic path also selected the requested striped variant in case 24. This
exposed a stale reference assertion: the capture states sale price `$2.98` and
`out_of_stock`, and the reference's own four striped variant examples already
said `out_of_stock`, while its product assertion said `in_stock`. The product
availability fixture was corrected to match the captured site. This is not
counted as extractor coverage movement.

## Scoped product-description material collection (2026-08-27)

Added deterministic material collection from verified product roots. The
collector reads explicit `Material`, `Fabric`, and `Composition` label/value
structures first, then composition, construction, and component clauses inside
product-description blocks. Page metadata is considered only after a rendered
product root with product-positive evidence has been verified. It does not scan
page-wide prose.

Product-root scoping is now shared by rendered detail collectors. Navigation,
size/fit guides, reviews, recommendations, related products, and generic
overlays remain excluded. A product-details modal is admitted when its context
also carries a positive product/detail role; previously a body-level
`modal-background` class could reject an otherwise valid `<main>` root.

Tests prove that material strings in navigation, size guides, reviews, and
recommendations cannot publish, and that meta-description material cannot
publish without a verified product root.

### Before and after

The same 82 captures moved from 72 failing cases / 286 failed assertions to
**71 / 278**. Material failures moved from **18 to 10**; every other field count
was unchanged. Exact recoveries were cases 8, 11, 31, 37, 41, 51, 61, and 71.

The ten remaining reference mismatches are cases 2, 4, 6, 19, 28, 33, 39, 56,
72, and 73. Several now publish broader wording that the captured site actually
states—for example `heavyweight cotton`, `everyday cotton fabric`,
`premium 500 GSM Aegean Turkish cotton`, and `97% polyester, 3% polyethylene`—
rather than the fixture's preferred normalized phrase. Those stay mismatches;
the extractor does not rewrite exposed wording to satisfy the fixture. Cases
without a safely bounded material statement remain empty.

An instrumented replay of the 18 material cases spent 0.415 seconds in the new
collector, 23.04 ms per case and 3.6% of total extraction time. Full-corpus
timing remained dominated by the previously documented variable JS-state scan.

## Identity display contract (2026-08-27)

The public contract now treats `title` as the selected target's semantic product
name, not a display string assembled from brand, colour, size, gender,
condition, or identifiers. Source spelling, case, and punctuation remain as the
site stated them. Resolution orders a target-confirmed schema.org
`Product`/`ProductGroup` name, visible product heading, admitted structured-state
name, product metadata, document title, then URL-derived fallback. Existing
pollution and product-identity rejection rules still run before that order.

`brand` now preserves a valid explicit target-scoped manufacturer, designer,
private-label, or vendor value. Host, title, and URL derivation can fill an
otherwise empty brand, but can no longer expand, shorten, recase, or replace an
explicit value. This keeps `Fellow` instead of deriving `Fellow Products`, and
keeps the source's `Levi Strauss & Co.` instead of replacing it with `Levi`.

Rendered and microdata brand candidates now share product-context boundaries.
Review, recommendation, and related-product components cannot supply a product
brand through either the dedicated DOM collector or the requested-field DOM
path. Case 69's review-platform value `gap` is therefore removed; the capture
does not expose a safely target-scoped replacement, so the brand remains
missing.

### Measured approaches

A collector-only precedence (`jsonld` before all other title sources) was
rejected before implementation. Against the identity partition it moved title
failures from 24 to 26: four reference mismatches became exact, but six
previously matching display-title assertions changed. Collector class was too
coarse to distinguish a semantic product name from generic embedded state.

The implemented semantic-role order deliberately follows the public contract,
not reference-score maximization. On the same 82 captures, the full replay moved
from 71 failing cases / 278 failed assertions to **70 / 284**. Title reference
mismatches moved from 24 to **30** and brand mismatches from 25 to **26**; every
non-identity field count stayed unchanged.

Five title assertions now exactly match (cases 33, 37, 57, 61, and 75). Eleven
previously matching assertions now disagree because the reference prefers a
composite or alternate display source (cases 3, 4, 7, 25, 28, 29, 36, 38, 47,
48, and 65). Examples include source-declared `Arrival 5\" Shorts` rather than
adding colour, `Millennium Falcon` rather than adding the identifier, and
`Premium Linen Shirt` rather than adding audience gender. These are reference
contract differences, not missing site evidence, so no fixture or extractor
alias was added.

Brand movement likewise reflects stricter provenance. Case 50 now publishes
the explicit `Fellow`; case 64 publishes explicit `Levi Strauss & Co.`; case 69
drops review markup; and case 27 no longer invents `Shape Tape Concealer` as a
brand from its URL. Missing brands whose only candidate belongs to an
unconfirmed product subject remain missing. The reference corpus was not edited
to convert those policy differences into passes.

Focused title-ranking, identity, brand-role, and scope tests passed (77 tests).
The replay timing was mean 546 ms, p50 318 ms, p95 1376 ms. This slice adds only
small evidence metadata and bounded ancestry checks; the full timing remains
dominated by the already documented variable embedded-state scan.

## Variant and option completeness (2026-08-27)

Capture contents were measured before changing variant behavior. The missing
rows did not form one generic extraction gap. Some captures expose complete
structured matrices, some expose only partial axes, and some contain offers or
controls that cannot safely be bound into same-product variants.

### Source inventory

| Case | Captured source evidence | Result |
| --- | --- | --- |
| 1 | Two DOM selection signals; no variant matrix. | Remains empty. |
| 11 | Three product offers and DOM controls; no variant relation or matrix. | Remains empty. |
| 20 | 22 complete JSON-LD/JS variants; two additional URL-only rows are not publishable. | Publishes 22, not the reference's 24. |
| 22 | Eleven color variants; no collected size matrix. | Publishes the 11 stated colors. |
| 25 | Seven JSON-LD variants share a product-level SKU but have distinct GTINs and sizes. | Fixed: 1 to 7. |
| 34 | Two offers, but no variant facts or same-product relation. | Remains empty. |
| 44 | Eleven offers, but no relation authorizes treating six of them as variants. | Remains empty. |
| 61 | Ten color variants and five DOM size controls; no purchasable 10-by-5 combination matrix. | Remains at 10; no Cartesian product is invented. |
| 67 | 147 JSON-LD variant subjects. Hidden width variants can share public color and size while retaining distinct SKUs. | Fixed: 48 to all 147 source rows; the reference says 146. |
| 72 | Thirteen explicit JSON-LD `ProductGroup.hasVariant` children, each with its own product path. | Fixed: 1 to 13. |
| 77 | 82 JSON-LD variants plus one JS parent-placeholder row. | Fixed: 81 to 82; unit wording remains source ounces. |
| 81 | Three complete variants. | Already correct; preserved. |

Case 29 is another important accuracy check. First-party state exposes 15
distinct IDs, SKUs, and GTINs across three color families and five sizes. The
old five-row output merged mutually exclusive variants solely because their
public size labels matched. The extractor now publishes all 15 stated rows,
even though the reference expects five.

### Generic fixes

Nested JSON-LD `hasVariant` rows now remain distinct during provisional
collection. A repeated product-level SKU can no longer collapse siblings before
their GTIN and option evidence reaches entity linking. Entity linking merges
exact stable IDs or GTINs across collectors, and compatible shared SKUs when
the options do not conflict. Conflicting identifiers preserve separate
variants; matching public option labels alone do not merge them.

Variant GTIN evidence now publishes under the public `barcode` role. When a
source supplies no explicit variant ID, a unique barcode is preferred to a
shared SKU as the stable public ID. An explicit JSON-LD `product_variant`
relation authorizes a `hasVariant` child whose canonical product path differs
from the parent; unrelated URL-derived candidates still use the existing
cross-product guard.

The URL and structured-endpoint paths now share one configured raw-axis map.
`colorcode`, `colorname`, `colorproductcode`, the display-code forms, and `sku`
therefore resolve identically in both consumers. SKU remains transport identity,
not a public option axis; generic JSON-LD and DOM option canonicalization still
rejects it as an option label.

A structured row whose sole option repeats the semantic product title and has
no direct variant commercial decision is treated as the parent/default
diagnostic row, not as an additional sellable variant. Parent-inherited or
reconciled offer values do not turn that shell into direct variant evidence.

### Before and after

The full 82-capture replay moved from **70 failing cases / 284 assertions** to
**70 / 257**. Variant assertions moved from **83 to 57**, `variant_count` from
**10 to 8**, and `size_options` from **4 to 3**; `model_options` stayed at 1.
The final variant/options-only audit has 12 cases and 32 assertions remaining.

Those remaining assertions are deliberately open. Cases 1, 11, 22, 34, 44,
and 61 lack the captured relations or complete purchasable matrix needed for
the reference output. Case 20 exposes 22 source-backed rows rather than 24.
Case 67 exposes 147 rather than 146. Case 77 states `0.04 oz` and `0.05 oz`;
converting those to the reference's `1.3 g` and `1.5 g` is the documented
single-site tail item and was not added as a generic extraction rule.

Final replay timing was mean 648 ms, p50 491 ms, p95 1716 ms. As in the earlier
measurements, this is dominated by variable embedded-state scanning rather than
the bounded variant identity comparisons.

## Raw DOM price provenance and ambiguity (2026-08-27)

The rendered-DOM offer collector previously parsed a matched price immediately
and passed only that normalized amount into `Evidence`. The later normalization
stage therefore saw values such as `1299.00`, not the captured `1,299.00`, and
could never attach its mixed-separator `ambiguous_decimal` diagnostic to a DOM
price.

DOM offer evidence now keeps the locale-blind parsed amount as its canonical
value while carrying the matched source amount as `raw_value`. Evidence IDs,
offer grouping, resolution, and public prices still use the canonical amount.
The pipeline parses that canonical value as before but checks decimal ambiguity
against the raw boundary value.

No page-URL locale hint was added to DOM collection. A regression test uses a
US-formatted `$1,299.56` value on a `.de` page and still publishes `1299.56`.
Passing the page locale into the collector would reinterpret that captured
format incorrectly, as documented in the rejected-approaches table.

### Before and after

Across the 82 captures, 24 cases now retain DOM price text that differs from the
canonical amount. Five cases gain the previously unreachable ambiguity
diagnostic: 8, 19, 47, 52, and 72. Examples include `28,600.00`, `$2,799.00`,
`186,000.00`, and `9,700.00` alongside their unchanged canonical values.

This is provenance/correctness plumbing, not a coverage claim. The full replay
remains **70 failing cases / 257 assertions**. Commercial failures remain
`price` 16, `availability` 10, `currency` 6, `original_price` 3, and one each
for `price_min` and `price_max`. Final timing was mean 547 ms, p50 429 ms, p95
1612 ms.

Final verification also caught a preceding variant-lineage regression. A
parent/default JS row whose sole option repeats the product title was admitted
when its repeated raw price normalized through a direct derived fact. The
default-shell rejection is now structural and does not depend on repeated
commercial data. Case 77 again publishes its 82 actual structured variants;
an explicit optionless child with its own identity and offer remains
publishable.

## Tail evidence audit and explicit GTIN checksums (2026-08-27)

The final named tail cases were inspected in both extracted evidence and raw
captured HTML. No site-specific recovery rule was added.

| Case | Captured evidence | Disposition |
| --- | --- | --- |
| 34 | Two independent JSON-LD aggregate offers expose `699–729` and `799–929` USD on the same page, but no source relation binds model labels into one variant family. | Keep the resolved `699–729` offer. Do not reinterpret the second model's low price as the first model's family maximum or synthesize model variants. |
| 39 | The expected `White/Black` wording is absent. The capture carries style code `1360` in asset names and unbound selected-state controls. | Color remains missing; no code-to-color inference. |
| 40 | First-party state contains prices for every market, equipment family, and package. Recovering the expected US basics package requires a schema-specific join across locale, URL family, `basicsPackages`, and `cfuPackages`; no stock state is present. | Leave commercial fields missing. Presence in a multi-market catalog does not prove the selected offer or availability. |
| 76 | The expected `1.7 oz / 50 ml` wording is absent from the capture. | Size remains missing. |
| 77 | All 82 structured variants state `0.04 oz` or `0.05 oz`. A generic FAQ mentions `0.05 oz / 1.5 g`; `1.3 g` is absent and the FAQ is not bound per shade. | Preserve the source ounce values; no approximate or cross-scope unit rewrite. |
| 82 | Expected size `1.5-2 inches` is absent. GTIN `555551397708` is explicit and already publishes when requested. | Size remains missing; barcode behavior is correct. |

The remaining barcode failure was instead case 2. Its JSON-LD explicitly
declares `gtin12=114410600165`, but the check digit fails and the previous
generic invalidity set suppressed the only stated GTIN. Under the corrected
identifier-role contract, checksum failure remains a diagnostic and lowers
candidate rank; it does not erase an explicit GTIN with a supported digit
length. Malformed lengths still fail closed, and a checksum-valid competing
candidate outranks an invalid one.

Case 2 now publishes the source-declared barcode. The full replay moves from
**70 failing cases / 257 assertions** to **70 / 256**; barcode failures move
from **1 to 0** and every other field count is unchanged. Timing was mean 307
ms, p50 224 ms, p95 738 ms.

## Close audit: structured roots, offer ownership, and diagnostic shells (2026-08-27)

The numbered handoff items were exhausted, then the remaining narrow fields
were audited against their captured evidence. This found four generic upstream
defects. None required acquisition, interaction, retailer literals, or a
site-schema join.

1. Root selection could identify a target `hasVariant` child, but the JSON-LD
   collector then skipped every child path without admitting its declared
   ProductGroup parent. The parent and its explicit matrix are now admitted.
2. First-party state can expose an option-group shell (for example, colour only)
   beside more-specific commercial leaves (colour plus size). A non-commercial
   strict option subset is diagnostic, not an additional sellable row. The same
   applies to parent/default diagnostic shells when matrix completeness is
   checked for parent availability rollup.
3. A schema Product with no own URL remained detached even when its sole Offer
   URL named the requested product resource. That explicit schema relation now
   supplies target ownership. Several or cross-resource offer URLs still fail
   closed.
4. Embedded product-root URL conflict detection recursively searched nested
   objects. A breadcrumb, asset, or recommendation URL could therefore reject
   the correct parent product. Only the root's own configured URL field now
   participates.

### Source-backed movement

Case 61's capture contains 50 explicit ProductGroup children, each with SKU,
colour, size, price, currency, and availability. The earlier inventory in this
report described ten colour rows plus five controls and incorrectly concluded
that no 50-row matrix existed. With parent admission, the extractor initially
published those 50 leaves plus ten colour-group shells; generic subset
eligibility removes the shells and publishes exactly the 50 stated leaves.
The remaining fixture example is corrupted (`H�tel`) and disagrees with the
captured `Hôtel`; no source text is rewritten for it.

Cases 27 and 31 now bind their URL-less schema Products through sole
same-resource Offers. This restores their explicit identifiers and commercial
or attribute evidence. Case 9 publishes the unanimous Offer-level
`RefurbishedCondition`. Case 77's 82 real variants now roll up their unanimous
availability despite one rejected parent diagnostic row. Case 1's admitted
product state now publishes its explicit `condition=New`, `gender=men`, and
`styleId=DD1391-100`; nested URLs no longer reject the root.

From the item-8 state, the same 82 captures move from **70 failing cases / 256
fixture disagreements** to **70 / 228**. The unchanged failing-case count is
expected: most cases disagree on several independent fields, and the reference
is development guidance rather than a gate.

### Remaining dispositions

- Identifier disagreements mainly ask for URL-derived or reformatted roles the
  source did not declare, or prefer a style code over an explicit SKU. The
  extractor preserves the declared role and formatting. Peloton case 40 remains
  the documented schema-specific multi-market/package join.
- Commercial drift cases 9, 18, 45, 47, 71, 73, 74, 79, and 80 publish the
  captured source price, not the older fixture value. Case 26 states
  `out_of_stock` and no original price; case 78's variants state `in_stock`
  while the fixture says out of stock; case 81 exposes no source original
  price. These are not repaired toward the fixture.
- Cases with several variant offers but no source-selected member keep product
  price or availability missing when a family aggregate is not semantically
  valid. Case 34's independent family bounds and case 40's unbound catalog are
  unchanged.
- Remaining material, condition, gender, size, and identity gaps either lack a
  safely bounded statement or would require title/category/URL inference already
  rejected by the source-backed contract.

Final replay timing was mean 652 ms, p50 469 ms, p95 1628 ms. As before, timing
is dominated by the variable embedded-state scan; the new operations are
bounded root/row comparisons.

Repository verification at the item-9 checkpoint passed: `scripts/check.ps1`;
`scripts/test.ps1` selected 57 backend test files and passed all 754 tests;
`git diff --check` was clean apart from Git's existing line-ending warning for
`metadata.py`.

## Post-close correction audit — 2026-08-27

This audit used deterministic replay of the same 82 captures under
`backend/artifacts/runs/3`; it did not run acquisition or a live crawl. The
earlier phrase "70 cases / 228" meant 70 **failing** cases out of 82 and is
corrected here.

Six additional generic defects remained in explicit same-product sources:

1. Direct state variant leaves with an explicit ID and public option were
   rejected unless they also carried SKU, GTIN, or URL. Nested `traits` and
   typed GTIN arrays were not read. Case 1 now publishes all 24 stated leaves.
2. A selected ProductGroup's target ownership aliases stopped at the parent.
   Propagating those authorized aliases to `product_variant` relations recovers
   case 16's explicit SKU/barcode rows while keeping unrelated roots excluded.
3. JSON-LD child keys `gtin8`, `gtin12`, `gtin13`, and `gtin14` were supported
   only at product scope. Variant-scope mapping recovers all explicit barcodes
   in cases 58 and 65.
4. Uppercase five-letter colors such as `BROWN` were mistaken for opaque codes,
   and a malformed repeated URL query could override explicit `color=Cedar`
   with the token `color`. Named colors and explicit source values now survive;
   case 63 and case 68 matrices are complete.
5. A schema.org price specification explicitly typed
   `StrikethroughPrice` was emitted as another current price. It now publishes
   as `original_price`; case 65 keeps `69.97` current and `75.00` original.
6. A selected top-level Product and its matching ProductGroup child could remain
   separate. Selected child ownership now joins the explicit parent matrix;
   case 11 publishes its three stated colors plus parent gender/style evidence.

The full replay moved from **70 failing cases / 228 fixture disagreements** to
**69 / 204**. Field disagreement counts are: availability 8, brand 24, color
23, condition 1, currency 4, gender 2, material 11, model options 1, original
price 3, price 14, price bounds 2, product family 1, product ID 2, rating 6,
review count 5, size 4, size options 2, SKU 16, style ID 6, title 30, variant
count 5, and variant assertions 34.

Remaining variant cases were checked against raw capture evidence. Cases 20,
29, and 67 explicitly contain 22, 15, and 147 rows rather than the reference's
24, 5, and 146. Cases 34 and 44 expose independent offers without a same-product
variant relation. Case 2 has barcodes only for the selected product, case 52
declares one blank SKU, and case 29 declares commercial facts only for one of
three colors. Cases 18, 26, 45, 61, 68, 74, 77, and 78 disagree with captured
price, availability, spelling, or units. These stay source-backed or missing;
none justify inference, suppression, or reference-driven repair.

Final corrected replay timing was mean 282 ms, p50 217 ms, p95 704 ms. The
canonical verification passed: `scripts/check.ps1` passed Ruff, mypy,
VitePlus, LOC, and complexity; `scripts/test.ps1` selected 57 backend files and
passed all 760 tests.
