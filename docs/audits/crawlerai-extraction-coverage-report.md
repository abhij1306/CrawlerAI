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
