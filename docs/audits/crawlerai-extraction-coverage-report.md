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

**Measured caution against over-fitting to GTIN:** only cases 66 and 71 pass
`validate_gtin`. Cases 5 and 31 are 14- and 12-digit values that *fail* the
checksum - barcode-shaped internal ids, not barcodes. A GTIN-only rule would
catch 2 of the 5; the digit-shape rule catches all 5. Use GTIN validation only to
decide whether the rejected value should populate `barcode`.
