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
- Do use the corpus to *find* systemic defects - it is how the pooled-subject
  finding below was found.
- **Publish what the site exposes and nothing else.** Do not invent a value, do
  not suppress one the site stated, and do not add shape heuristics that decide
  a value "looks wrong". Where the corpus wants a value the site never exposed,
  the corpus is wrong.
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

### 1. Identifier roles: publish what the site exposes, invent nothing

**The governing rule for every identifier: show what the site exposes. Never
create a value the site did not state, and never suppress one it did.**

`sku`, `mpn`, `gtin`/`barcode`, `product_id` and `style_id` are distinct roles
that may hold all-different, all-same, or partly-overlapping values. If a site
declares one string as both its SKU and its MPN, publish it as both - that is
the truth about the page, not a duplicate to clean up. Do not merge the fields,
and do not add shape heuristics that second-guess which role a value "really"
belongs to.

Three approaches were investigated and **must not be built**. Each was measured,
and each violates the rule above:

- *Preferring an alphanumeric candidate over a bare digit run for `sku`.*
  Measured +0/-0, and it is invented policy: when a site's product node says the
  SKU is `100155080614`, that is the SKU. The reference corpus disagreeing is the
  corpus's opinion, not a defect.
- *Suppressing a checksum-valid GTIN from `sku`/`mpn` and routing it to
  `barcode`.* Regresses 4 sites - cases 22 and 38 genuinely expect a GTIN **as**
  the `sku`, and case 71 expects one **as** the `mpn`. Sites really do use a
  trade item number as their SKU.
- *Treating `mpn == sku` as duplication to remove.* 11 of 82 sites publish one
  value in both roles, and in every case checked the JSON-LD declares both
  `/sku` and `/mpn` with that value. That output is already correct.

#### The real defect: contradictory values pooled onto one subject

Per-variant identifiers are collected at **product** scope, so a single product
subject asserts many mutually exclusive values for a single-valued field and
resolution then picks one by rank. Case 5 is the clearest: fourteen distinct
`[data-sku]` swatch values all attach to subject `15125c86` at product scope, and
`45993954738410` is published as *the product's* SKU. The site never said that.
It said that is one variant's SKU.

Measured across the corpus - one product subject carrying more than two distinct
values for a single-valued field:

| Fact | Sites | Worst single subject |
| --- | --: | --: |
| `product.title` | **66** | 35 distinct values |
| `product.sku` | 4 | **82** distinct values |
| `product.brand` | 2 | 23 distinct values |

This is the highest-breadth structural defect found so far and it sits upstream
of the `title` (24 sites) and `sku` (19 sites) gaps: resolution is choosing a
winner from a candidate set that should never have been pooled onto one subject.

Two directions, in order of preference:

1. **Scope the evidence correctly at collection.** A `[data-sku]` on a swatch or
   option control is variant evidence - emit it against that variant subject,
   not the product. This is the fix that matches "publish what the site
   exposes".
2. **Fail closed on contradiction.** Where a single-valued field on one subject
   has irreconcilable candidates and nothing distinguishes them, publish
   nothing. A missing SKU is acceptable; another product's SKU is not.

`title` behaves differently from the identifiers - a page legitimately offers
many title candidates (`h1`, `og:title`, JSON-LD `name`) and ranking among them
is correct. Do not apply a fail-closed rule to it blindly; first check whether
its 66 sites are genuine alternates for one product or pooled siblings.

Related and already known: case 2 publishes `DIME2SP2542BLK-S` where the parent
SKU is `DIME2SP2542BLK`. `publication_policy.py` already has a
`parent_sku_is_variant_specific` suppression - find out why it does not fire.
Most likely the same root cause: the variant SKUs are labelled `product.sku`, so
the `variant_skus` set that guard consults is empty.

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

**Completed 2026-08-27.** Full replay moved 70 / 284 to 70 / 257. Variant
assertions moved 83 to 57, `variant_count` 10 to 8, and `size_options` 4 to 3.
The extractor now preserves distinct structured siblings, links compatible
cross-source identifiers, publishes variant GTIN as `barcode`, admits explicit
`ProductGroup.hasVariant` child paths, and removes parent diagnostic shells.
The remaining cases lack a captured matrix, disagree with the captured row
count, or are the case-77 unit-normalization tail. Details and per-case counts
are in `docs/audits/crawlerai-extraction-coverage-report.md`.

### 6. Reconcile the two variant-axis tables - correctness plumbing

**Completed 2026-08-27.** URL identity and structured endpoint parsing now use
one configured raw-axis table. Public option canonicalization consumes the
publishable subset, so `sku` remains identity rather than becoming an option.

### 7. Preserve the price ambiguity signal - correctness plumbing

**Completed 2026-08-27.** DOM offers retain the matched source amount in
evidence `raw_value` while resolution continues to use the locale-blind
canonical amount. The ambiguity diagnostic now fires in five captures without
changing any published commercial field. A `.de` regression proves that US
mixed-separator formatting is not reinterpreted through page locale.

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

**Audited 2026-08-27.** Cases 34, 39, 40, 76, 77, and 82 are documented in the
evidence report. Their remaining values require absent evidence, unsafe family
composition, a site-schema-specific multi-market join, or an unbound/approximate
unit conversion, so they stay missing. Case 2 exposed one generic identifier
bug: an explicitly declared, correctly shaped GTIN was suppressed solely for a
bad checksum. Checksum failure is now diagnostic/ranking-only; malformed lengths
still reject. Full replay moved 70 / 257 to 70 / 256 and barcode failures moved
1 to 0.

Single-site and near-single-site items: option unit normalization (case 77,
`0.05 oz` vs `1.5 g`), Peloton case 40 (confirm whether the capture holds any
commercial evidence before changing logic), Apple case 34 family bounds,
`model_options`, `product_family`, `price_min`/`price_max`, and the
capture-limited attribute cases 39, 76, 82. None of these justify a generic rule.
Record them as capture-limited or site-specific and move on.

### 9. Close audit

**Completed 2026-08-27.** The close audit found four generic upstream defects
after item 8: selected `hasVariant` roots discarded their ProductGroup parent;
option-group/default diagnostic shells counted as sellable matrix rows; a
URL-less Product could not bind through its sole same-resource Offer URL; and a
product-root URL conflict recursively read nested child URLs. The fixes recover
complete source-backed fields without widening acquisition or adding a site
schema. Final replay at that checkpoint was 70 failing cases out of 82 / 228
fixture disagreements; unresolved values
are absent, ambiguous, source/reference disagreements, or the documented
single-site joins. The plan is complete.

### 10. Post-close correction audit

**Completed 2026-08-27.** The stricter completion audit found six remaining
generic defects in explicit same-product data: ID-plus-option leaves were not
sellable; nested `traits` and typed GTIN arrays were unread; selected
ProductGroup aliases did not propagate to children; variant `gtin8/12/13/14`
keys were ignored; valid uppercase colors and explicit colors beside malformed
URL shade values were suppressed; and `StrikethroughPrice` was treated as a
second current price.

The fixes recover case 1's 24 explicit state variants, case 11's three declared
ProductGroup children, case 16's complete SKU/barcode matrix, case 58 and 65
variant barcodes, case 63 and 68 explicit colors, and case 65's current/original
price roles. The same 82 local captures now measure **69 failing cases / 204
fixture disagreements**. No live crawl was run. Remaining matrix differences
are source-limited or reference/source disagreements documented in the audit
report.

Canonical verification after the correction audit passed:
`.\scripts\check.ps1`; `.\scripts\test.ps1` selected 57 backend files and passed
all 760 tests. Final replay remained 69 failing cases / 204 fixture
disagreements.

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
