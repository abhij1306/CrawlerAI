# Requirements: Variant Extraction Refactor

## Problem Statement

The variant extraction pipeline produces low-quality variant rows with:
1. **Axis mislabeling** — size values land in non-semantic axes like `state` instead of `size`
2. **Duplicate/overlapping rows** — same product option appears multiple times in different formats (e.g., "S 8-10" and "S" as separate variants)
3. **Missing transport fields** — variant rows contain only a mislabeled axis value with no price, URL, SKU, or availability
4. **Cross-product pollution** — unrelated axis values from different groups get merged into flat rows without proper grouping

Example (Belk): A shirt with 4 sizes produces 9 variant rows, each containing only `{"state": "S 8-10"}` or `{"state": "S"}` — no price, no URL, no SKU, and the axis is `state` instead of `size`.

## Functional Requirements

### REQ-1: Axis Name Resolution
- REQ-1.1: When a variant group's axis name resolves to a non-semantic key (e.g., `state`, `option_1`), the system must attempt value-based axis inference before persisting
- REQ-1.2: If all values in a group match known size patterns, the axis must be remapped to `size`
- REQ-1.3: If all values in a group match known color patterns, the axis must be remapped to `color`
- REQ-1.4: The `state` axis must not appear in public output when its values are recognizable as size or color

### REQ-2: Duplicate Variant Row Elimination
- REQ-2.1: Variant rows that are strict subsets of richer rows (same axis values, fewer transport fields) must be pruned
- REQ-2.2: When the same logical size appears in multiple formats (e.g., "S 8-10" and "S"), the richer representation must win
- REQ-2.3: Cross-product rows from unrelated axis groups must not produce N×M flat rows when only N+M distinct options exist

### REQ-3: Minimum Variant Row Quality
- REQ-3.1: A variant row must contain at least one recognized public axis value (size, color, etc.) OR at least one transport field (price, sku, url, availability)
- REQ-3.2: Variant rows containing only a single non-semantic axis value with no transport fields must be dropped
- REQ-3.3: When all variant rows in a cluster fail quality checks, the entire `variants` field must be removed rather than persisting garbage

### REQ-4: Value-Based Axis Inference Hardening
- REQ-4.1: The `infer_variant_group_name_from_values` function must handle compound size tokens (e.g., "S 8-10", "M 12-14", "L (16-18)")
- REQ-4.2: Size inference must recognize child/youth size patterns with numeric ranges
- REQ-4.3: The inference must run as a fallback when the resolved axis name is generic/non-semantic

### REQ-5: Variant Normalization Pipeline Ordering
- REQ-5.1: Axis remapping must occur before deduplication
- REQ-5.2: Deduplication must occur before structural pruning
- REQ-5.3: Quality gate must run after all normalization steps

## Acceptance Criteria

- [ ] Belk-style variants with `state` axis containing size values are remapped to `size`
- [ ] Duplicate size rows in different formats are deduplicated to the richer representation
- [ ] Variant rows with only a non-semantic axis and no transport fields are dropped
- [ ] Existing passing tests remain green (`pytest tests -q` exits 0)
- [ ] No new files created outside existing variant extraction modules
- [ ] Changes stay within Bucket 4 (Extraction) ownership
