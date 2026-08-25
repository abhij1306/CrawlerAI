# CrawlerAI Ecommerce Detail Reference Evaluation

These files are the canonical planning and replay references for the 82-case ecommerce-detail evaluation captured on 2026-08-23:

- `crawlerai_eval_compact.json` — independently supported expected fields and dynamic constraints.
- `crawlerai_defects_compact.json` — 165 observed defects from the latest evaluated run, grouped by root-cause area.

The reference data is not acquired input. Replay must use the matching ignored `backend/artifacts/runs/*/results/*/page.html` capture and any state/network artifacts that were actually captured. Never use `record.json` or `diagnose.json` as extractor input.

## Evaluation projection

- `material` maps to the public `materials` field.
- `size_options` and `model_options` assert variant dimensions/rows; they are not top-level public fields.
- `product_family` is an evaluation semantic. It requires truthful family representation, price bounds, and model variants when source evidence supports them; it is not a new public boolean.
- `selected_fit` asserts selected variant state. Publish it only through the configured public variant axis.
- `style_id`, `asin`, and `product_id` remain distinct product-level identifier expectations. They must not be satisfied by a variant ID or internal entity ID.
- `constraints.mode=volatile` and `locale_sensitive` assert extraction/selection semantics. They do not freeze a live price or inventory snapshot forever.

Case IDs are stable. Cases 24 and 62 intentionally cover two captures of the same Zara path, one with the `v1` query and one without it.
