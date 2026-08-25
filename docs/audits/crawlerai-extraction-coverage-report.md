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

**Status: measured, not implemented.** The measurement contradicts the slice's
premise strongly enough that it should be re-scoped before any code is written.

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

### Recommendation

Re-scope before implementing. The 3 capture-limited cases should be recorded as
such. Slice 2 (`variants` 83) should be checked for the same premise gap before
it is started, since it rests on the same assumption about what the captures
hold.
