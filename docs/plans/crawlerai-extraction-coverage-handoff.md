# Handoff Prompt - CrawlerAI Extraction Coverage (PR 3)

Paste the block below as the first message in a new chat.

---

Implement `docs/plans/crawlerai-extraction-coverage-plan.md`. Read that plan and
`docs/audits/crawlerai-extraction-coverage-report.md` first - between them they
carry every measurement already taken and every approach already rejected with
numbers. Nothing below needs re-deriving; do not go searching for it again.

## The rule that decides priority

**Fix what is broken across many sites before what is broken on one.**

A single site missing a few fields is acceptable. A single field missing across
many sites is not - that is an architectural gap, and it is what you are here to
close. Prefer a generalization that lifts twenty sites over a rule that rescues
one. Genuinely site-specific edge cases go last, or stay open.

Measured breadth of the current gaps (82 captures, one host per case, so cases
are effectively distinct sites):

| Field | Sites affected | |
| --- | --: | --- |
| `color` | 29 | systemic |
| `title` | 24 | systemic |
| `brand` | 24 | systemic |
| `variants` | 22 | systemic |
| `sku` | 19 | systemic |
| `material` | 18 | systemic |
| `price` | 15 | systemic |
| `variant_count` | 10 | broad |
| `availability` / `style_id` | 9 | broad |
| `rating` / `review_count` | 8 / 7 | broad |
| `currency` / `gender` | 6 / 5 | broad |
| `size` / `size_options` / `condition` / `original_price` | 3-4 | narrow |
| `product_id`, `barcode`, `mpn`, `model_options`, `price_min`, `price_max`, `product_family` | 1-2 | **tail - do last** |

Note this reorders the plan: `sku` (19 sites) is not a named slice at all, and
`material` (18 sites) sits behind narrower work. Follow the breadth, not the
plan order.

## Read this first: what the reference corpus is for

`app/evaluation/reference/` and `docs/audits/crawlerai_defects_run3.json` are
**development guidance, not ground truth, and not a gate.**

- Do not treat assertion counts as a target, a ratchet, or a definition of done.
  Do not add CI corpus gates.
- Do use the corpus to *find* systemic defects - it is how the `sku` finding
  below was found.
- Where the corpus contradicts itself (it does: casing and title length), decide
  the correct contract on its own merits and edit the corpus to match. It is a
  fixture; you may change it.
- Where a capture lacks the evidence, the case stays open. Record it as
  capture-limited. **A missing value is acceptable; a wrong price, stock state,
  colour or sibling product is not.** That ranking is the one hard rule.

Running the harness:

```python
from harness.artifact_quality_cases import (
    load_artifact_quality_cases, audit_artifact_quality_cases,
)
refs = load_artifact_quality_cases("app/evaluation/reference")
res = audit_artifact_quality_cases(refs, backend_root=".", partitions=None)
```

Use the **venv interpreter** (`backend/.venv/Scripts/python.exe`) with
`PYTHONPATH=.` from `backend/`. The system Python is 3.14 and fails unrelated
tests. Current state: 82 cases, 72 failing, 290 assertions. Diff the failure set
before and after a change to see what you moved; do not chase the total.

## Start state

- PR 1 (#65) and PR 2 (#66) are merged. Branch from updated `main`.
- **All inherited review findings are cleared.** PR #66 fixed 8 and rejected 3
  on measurement; the plan records each disposition. Do not re-litigate them,
  and do not re-apply the three rejected ones - their regressions are documented
  with case numbers.
- Captures: `backend/artifacts/runs/3/results` (82, git-ignored).

## Work items, most systemic first

### 1. SKU vs barcode identity selection - 19 sites

The strongest systemic defect found so far. Of 19 sites with a wrong or missing
`sku`, 7 publish a wrong one, and the pattern across them is clean and generic:

| Case | Expected `sku` | Published | Expected all digits? | Published all digits? |
| --- | --- | --- | --- | --- |
| 5 | `HQ7978-103` | `45993954738410` | no | **yes** |
| 31 | `PE1001550` | `100155080614` | no | **yes** |
| 66 | `395205_01` | `4099686132767` | no | **yes** |
| 71 | `4D3032G-PCG` | `198629014314` | no | **yes** |
| 4 | `HJ0139-045` | `21001455` | no | **yes** |
| 2 | `DIME2SP2542BLK` | `DIME2SP2542BLK-S` | no | no |
| 39 | `870543 4GAK3 1360` | `8705434GAK31360` | no | no |

**In 5 of 7, extraction chose a bare digit run over an alphanumeric merchant
SKU.** Merchant SKUs and style codes carry letters and separators; bare digit
runs are barcodes, internal ids, or database keys. So the generic rule is:

- When candidates for `sku` include both a pure-digit string and one containing
  letters or separators, prefer the latter.
- Route checksum-valid GTINs to `barcode` instead of discarding them.
  `validate_gtin()` already exists in
  `backend/app/core/config/locale_format_rules.py`.

**Verified, so do not over-fit to GTIN:** only cases 66 (`4099686132767`) and 71
(`198629014314`) actually pass `validate_gtin`. Cases 5 and 31 are 14- and
12-digit strings that **fail** the checksum - they are internal ids that merely
look barcode-shaped. A GTIN-only rule catches 2 of 5; the digit-shape rule
catches all 5. Build the digit-shape rule and use GTIN validation only to decide
where the rejected value goes.

Case 2 is the parent/variant SKU boundary: there is already a
`parent_sku_is_variant_specific` suppression in `publication_policy.py`, so find
out why it did not fire. Case 39 is separator normalization - low value, do it
only if it falls out naturally.

### 2. Generic selected-state reading - 29 sites

**A decoupling job, not a rule hunt.** Selected state is read only through
`VARIANT_DOM_ATTRIBUTE_CONTROL_SELECTOR` in
`backend/app/core/config/extraction_rules/_variants.py`, which is
`[data-attr-id][data-attr-value], [data-attr-id][data-dvalue]` - one commerce
platform's markup convention. `_attribute_control_selected` in
`backend/app/extraction/collectors/dom.py` reads a `selected` JSON key plus the
`selected`/`active`/`is-selected` classes, and is only ever called on nodes
matching that selector. **Every site that marks selection the standard way is not
read at all.** That is site-specific coupling in generic code and is worth fixing
on its own merits.

Measured: of 33 failing `color`/`size` assertions, 7 carry a standard selected
marker (cases 10, 11, 31, 51, 61, 72, 74), and **all seven captures contain zero
`[data-attr-id]` elements**. Extending the predicate alone therefore changes
nothing - that was tried, measured at +0/-0, and reverted. The collection path is
what must change. The per-strategy table is in the report.

Implement:

- Read the platform-neutral markers on option controls generally:
  `aria-selected`, `aria-checked`, `aria-pressed`, `aria-current`,
  `option[selected]`, `input[checked]`.
- Treat ARIA as tri-state: an explicit `"false"` must return False, not None, so
  the resolver can fail closed instead of treating marked-not-selected as
  unknown.
- Bind the marked option to the same-product variant set, keyed on option axis.
- **Publish only when exactly one option in an axis is marked; fail closed on
  zero or several.** 13 captures mark several nodes - guessing publishes a wrong
  colour.
- Keep the vendor JSON/class path as a fallback *beneath* the standards.
- Do not touch PR 1's URL-axis precedence: a requested URL naming an axis still
  wins over DOM state.

23 of the 33 have the colour present with nothing marking it current. Those stay
open by design.

### 3. Scoped product-description collector - 18 sites (`material`), reusable

Material's real sources are product-description bullet lists and meta-description
prose. Build a collector scoped to the **product root section only**, rejecting
navigation, size guides, reviews and recommendations. The page-wide
fibre-composition regex is already measured at 1 correct / 14 wrong - do not
retry it. Prove the scope with tests showing the collector cannot read outside
the product section. The same scoped section is likely reusable for `condition`
and `gender`.

### 4. Identity display contract - 24 sites each for `title` and `brand`

Previously blocked because the corpus contradicts itself: case 44 wants the
longer title and case 61 the shorter; case 25 wants `Black` from `black` while
case 12 wants `black/...` from `Black/...`. **That blocker is lifted** - the
corpus is guidance. Decide the contract on its own merits, write it into
`docs/BUSINESS_LOGIC.md`, implement it, and edit the contradicting reference
cases to match. State which source is authoritative for a product name and how
display case is decided. No retailer aliases, no per-site casing tables.

### 5. Variant and option completeness - 22 sites

The largest raw cluster, but **measure before building**: check whether the
missing variants are in the captures at all, and in which source (JSON-LD,
first-party JS state, DOM controls). Slice 1's premise did not match what the
captures hold, and this rests on a similar assumption. Record the measurement
either way - it is cheap and prevents building against absent evidence.

### 6. Reconcile the two variant-axis tables - correctness plumbing

`VARIANT_URL_AXIS_PARAMS` and `variant_policy.canonical_variant_axis` disagree:
`colorcode`, `colorproductcode`, `colorname` and `sku` canonicalize to `None`
through the second while resolving correctly through the first, so
`structured_variant_state.py` silently drops axes that `url_identity.py` reads.
Same drift class PR #66 fixed for the regex by deriving it from the table. Derive
or validate one against the other, with a test that fails if they diverge.

### 7. Preserve the price ambiguity signal - correctness plumbing

`_visible_offer_values` in `collectors/dom.py` normalizes price text via
`parse_money` and emits the normalized amount, so by the time the pipeline runs
`money_has_ambiguous_decimal` the separator that made it ambiguous is gone and
the flag can never fire on DOM-sourced prices. Carry the raw matched text through
as the evidence `raw_value`.

**Do not** pass a page-URL locale hint to the collector's `parse_money`. Analysed
and rejected: locale-blind reading is more robust for mixed separators, and the
hint turns a correct `1,234.56` into `1.23456` on a `.de` host using US
formatting. Full reasoning in the plan.

### 8. Tail - do these last, or leave open

Single-site and near-single-site items: option unit normalization (case 77,
`0.05 oz` vs `1.5 g`), Peloton case 40 (confirm whether the capture holds any
commercial evidence before changing logic), Apple case 34 family bounds,
`model_options`, `product_family`, `price_min`/`price_max`, and the
capture-limited colour cases 39, 76, 82. None of these justify a generic rule.
Record them as capture-limited or site-specific and move on.

## Constraints

- No site-specific branches, retailer aliases, or casing tables in generic
  extraction code. `test_extraction_carries_no_retailer_domain_literals` and
  `test_extraction_rules_have_no_matrix_tuned_constants` enforce this.
- No acquisition/browser/traversal changes and no option clicking. Absent source
  artifacts stay capture-limited.
- Every published value must come from an authorized projection with lineage. A
  post-serialization alias trips `PUBLIC_RESOLUTION_DIVERGENCE` and suppresses
  the whole record. The seam for a representation change is
  `CanonicalizationTrace` - `divergence._values_equal` compares against
  `canonical_value`. PR #66 used it to publish `rating`/`review_count`
  numerically; copy that pattern.
- Size policy is repo-wide: `scripts/validation.json` (`maxLines` 800,
  `maxPythonComplexity` 15), enforced by `scripts/check.ps1 -Mode Limits`. The
  per-module budget tables and per-file ledgers were deleted; there is no
  per-file budget to document. Prefer extracting a module over growing one - CC
  15 is easy to trip, and PR #66 had to extract `_hint_target_offer_group` out of
  `_offers` for exactly that reason.
- Amazon case 55 returning no product is **correct** for an anti-automation
  shell.

## Gates

`.\scripts\check.ps1` and `.\scripts\test.ps1` must pass. `git diff --check`
clean. Update `docs/audits/crawlerai-extraction-coverage-report.md` after each
piece of work, including what you measured and rejected - that record is what
stops the agent after you retrying it.

## Ask before

Re-capturing the price-drift cases (9, 18, 45, 47, 71, 73, 74, 80 - live retail
changes, not extraction faults), or anything widening acquisition scope.
