# Plan: Variant Extraction Refactor

**Created:** 2026-05-12
**Agent:** Opus
**Status:** IN PROGRESS
**Touches buckets:** Bucket 4 (Extraction), config/variant_policy

## Goal

Fix variant extraction quality issues where variant rows contain mislabeled axes (e.g., `state` instead of `size`), duplicate/overlapping rows, and rows with no useful signal. The Belk fishing shirt example shows 9 variants with only `{"state": "S 8-10"}` — no price, no URL, no color, axis should be `size`. The page actually has ~12 color swatches AND size buttons, but output captures neither correctly. After this plan, generic axis names are remapped to their semantic equivalent, and low-signal rows are dropped.

**Real page evidence (Belk fishing shirt screenshot):**
- Colors: White + ~12 swatches (greys, blues, greens, corals, reds, navy, black)
- Sizes: S 8-10, M 12-14, L (16-18), XL 20, S, M, L, XL, L 16-18
- Price: $11.25 - $37.50
- The sizes appear to be two groups (Boys 8-20 extended sizes AND generic letter sizes)

## Acceptance Criteria

- [ ] Variants with `state` axis containing size values are remapped to `size`
- [ ] Compound size tokens like "S 8-10", "M 12-14", "L (16-18)" are recognized by `infer_variant_group_name_from_values`
- [ ] Duplicate size rows in different formats are deduplicated (richer wins)
- [ ] Variant rows with only a non-semantic axis and no transport fields are dropped
- [ ] `python -m pytest tests -q` exits 0
- [ ] No new files created

## Do Not Touch

- `detail_extractor.py` — candidate system is correct per INVARIANTS.md Rule 3
- `detail_materializer.py` — finalization across all sources is correct
- `variant_group_validator.py` — DOM group admission is a separate concern
- `variant_dom_cues.py` — scope detection is not the issue here
- `js_state/state_normalizer.py` — upstream source is providing what it has; fix is downstream normalization

## Slices

### Slice 1: Harden `infer_variant_group_name_from_values` for compound size tokens
**Status:** TODO
**Files:** `backend/app/services/extract/shared_variant_logic.py`
**What:**
- Update `_variant_size_value_patterns` (in `config/extraction_rules.py`) or the inference logic to recognize compound size tokens like "S 8-10", "M 12-14", "L (16-18)", "XL 20", "S/M", "2XL"
- Ensure `infer_variant_group_name_from_values(["S 8-10", "M 12-14", "L (16-18)", "XL 20"])` returns `"size"`
**Verify:** `python -m pytest tests -q -k "variant" --no-header`

### Slice 2: Add axis remapping for generic/non-semantic axes in normalization
**Status:** TODO
**Files:** `backend/app/services/extract/variant_record_normalization.py`
**What:**
- In `_sanitize_variant_axes` or a new step called before dedup, detect variant rows where the only axis is a non-semantic key (like `state`, `option_1`, etc.)
- For such rows, run `infer_variant_group_name_from_values` on the collected values
- If inference returns a recognized axis (size, color), remap all rows: move the value from the generic key to the correct axis key
- Remove `state` from `PUBLIC_VARIANT_AXIS_FIELDS` in `config/variant_policy.py` if it serves no legitimate purpose, OR add it to a "generic axes eligible for remap" set
**Verify:** `python -m pytest tests -q -k "variant" --no-header`

### Slice 3: Strengthen duplicate variant row elimination
**Status:** TODO
**Files:** `backend/app/services/extract/variant_record_normalization.py`, `backend/app/services/extract/variant_structural_pruning.py`
**What:**
- In dedup logic, when two rows have the same axis key and one value is a prefix/subset of the other (e.g., "S" vs "S 8-10"), keep the richer one
- Add normalized size comparison: strip parentheses and normalize whitespace before comparing
- Ensure cross-product rows from the same axis don't survive (e.g., if "S 8-10" and "S" both map to size=S after normalization, keep one)
**Verify:** `python -m pytest tests -q -k "variant" --no-header`

### Slice 4: Add minimum-signal quality gate for variant rows
**Status:** TODO
**Files:** `backend/app/services/extract/variant_record_normalization.py`
**What:**
- After axis remapping and dedup, add a final pass that drops rows with no recognized public axis value AND no transport field (price, sku, url, availability, image_url)
- If all rows are dropped, remove `variants` and `variant_count` from record
- This catches the case where axis remap fails and rows are truly garbage
**Verify:** `python -m pytest tests -q -k "variant" --no-header`

### Slice 5: Integration verification
**Status:** TODO
**Files:** None (test-only)
**What:**
- Run full test suite
- Verify the Belk-style input produces correct output (either properly labeled size variants or no variants at all)
- Confirm existing Belk artifact tests still pass
**Verify:** `python -m pytest tests -q`

## Doc Updates Required

- [ ] `docs/INVARIANTS.md` — add note about generic axis remapping contract if the behavior is new
- [ ] `docs/CODEBASE_MAP.md` — no changes needed (no new files)

## Notes

- The `state` axis is currently in `PUBLIC_VARIANT_AXIS_FIELDS`. Need to determine if any legitimate use exists before removing it. If legitimate uses exist, keep it but add it to a "remap-eligible" set.
- The root cause is that DOM extraction or JS state produces variant rows with axis names from the site's internal data model (e.g., Belk uses "state" for size in DOM attributes). The normalization layer should catch this.
- Per INVARIANTS.md Rule 3: variant fields use `finalize_candidate_value` across ALL source candidates. The fix is in normalization (after materialization), not in candidate selection.
- The Belk adapter (`adapters/belk.py`) does NOT extract variants — only scalar fields. Variants come from generic JS state mapper or DOM extraction.
- From the screenshot: the page has both color swatches and size buttons. The DOM extractor finds size buttons but labels them `state`. Color swatches may not be captured because the Belk adapter handles the page first and doesn't pass variant extraction to the generic path.
- The sizes on the page are two groups: extended sizes (S 8-10, M 12-14, L (16-18), XL 20) and letter sizes (S, M, L, XL, L 16-18). These may be from different DOM containers or a single container with mixed formats.
