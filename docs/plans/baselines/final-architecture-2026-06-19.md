# Final Architecture Baseline — 2026-06-19

Source: current dirty working tree plus root `output.json`. No smoke or live command was run.

## Repository Shape

```text
backend/app/services: 243 Python files / 51,784 LOC
backend/app total:     305 Python files / 58,109 LOC
files importing app.services across backend/app + backend/tests: 266
dirty/untracked paths before plan activation: 31
```

Focused package baseline:

```text
acquisition:          42 files / 13,234 LOC
pipeline:             15 files /  3,088 LOC
crawl:                19 files /  4,282 LOC
extraction:           24 files /  3,953 LOC
config:               42 files /  7,526 LOC
observability:         7 files /  1,643 LOC
product_intelligence:  6 files /  2,744 LOC
data_enrichment:       6 files /  2,401 LOC
```

Static AST scan found multiple functions over 100 lines. Largest runtime functions include browser acquisition, browser settlement, detail expansion, challenge recovery, traversal, batch processing, persistence, and product matching. Exact-block fallback found duplication in traversal selectors, JSON-LD parsing, and surface materialization. `jscpd` was unavailable because `npx jscpd` resolved to an incompatible `cpd` binary; near-clone metrics must be rerun with a compatible scanner before final retirement.

## 94-Record Output Baseline

```text
url:          69 present / 25 missing
title:        94 present /  0 missing
brand:        63 present / 31 missing
price:        72 present / 22 missing
currency:     73 present / 21 missing
image_url:    75 present / 19 missing
description:  84 present / 10 missing
availability: 66 present / 28 missing
sku:          57 present / 37 missing
variants:     23 records / 459 total rows
```

Variant row completeness:

```text
sku 385/459; size 392/459; color 339/459
price 358/459; currency 358/459; availability 356/459
url 17/459; image_url 2/459; variant_id 37/459
```

Detected generic failure classes:

- 25 missing parent URLs.
- Product identity polluted by shell, navigation, tab, or category text.
- Placeholder, loader, discount, email, payment, quote, and logo assets selected as primary images.
- Parent out-of-stock state conflicts with in-stock variants.
- Missing brand/offer/image/availability metadata without explicit diagnostics.
- Price magnitude drift and category-as-brand mapping.
- Explicit variant evidence either absent from output or materially incomplete.

## Dirty Tree Preservation

The pre-existing dirty set included generic variant collection/entity/materialization changes, acquisition replay filtering, config changes, persistence/public-boundary changes, tests, harness changes, and frontend log presentation changes. The implementation must preserve and audit these changes. No reset, stash, checkout, or destructive overwrite is allowed.
