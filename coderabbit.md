Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/models/crawl_settings.py around lines 431 - 434, The hardcoded string "host_memory_ttl_seconds" in the condition and assignment should be replaced with the ttl_key variable to maintain consistency with how the runtime settings key is used elsewhere in the code. Specifically, in both the condition checking if fetch_profile contains the key and in the assignment to profile, use the ttl_key variable (which represents crawler_runtime_settings.host_memory_ttl_seconds_key) instead of the literal string so that if the runtime setting key changes, this code will automatically use the updated key.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/variants/pruning.py around lines 699 - 712, The threshold calculation in the condition on line 711 uses len(title_tokens) which includes duplicate tokens, but should use len(unique_title_tokens) for semantic consistency since shared_unique counts unique overlapping tokens. Replace the len(title_tokens) parameter in the max() function call with len(unique_title_tokens) to ensure both sides of the threshold comparison use the same deduplication logic.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/js_state/state_normalizer/_variant_rows.py around lines 127 - 133, The loop iterating through JS_STATE_OPTION_GROUP_VALUE_KEYS breaks on the first truthy list returned by as_list(group.get(value_key)), but this list may contain only non-dict placeholders rather than valid variant rows. This causes valid dict rows in other keys to be skipped. Modify the break condition to check not just whether values is truthy, but whether it contains at least one valid dict item (variant row). This ensures the loop continues checking subsequent keys until it finds a list with actual valid dict rows, rather than stopping at the first non-empty list regardless of its contents.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/pipeline/extract_records.py around lines 329 - 376, The hardcoded field-name tuples in the functions _detail_record_has_product_signal and _detail_record_has_strong_product_signal violate the coding guideline that configuration and policy constants belong in app/services/config/* rather than service code. Extract the field-name lists from both functions (the "price", "original_price", "sku", etc. tuples in _detail_record_has_product_signal and the similar tuple in _detail_record_has_strong_product_signal) into constants defined in app/services/config/, then import and use those constants in place of the hardcoded tuples in extract_records.py.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/pipeline/extract_records.py around lines 365 - 376, The current implementation of _detail_record_has_strong_product_signal is too permissive and allows records with only weak singleton fields like currency, availability, or description to pass as having strong product signals. Refactor the logic to require either real commerce data (price or original_price must be present) OR a combination of identity data plus supporting context (such as having both a title field and at least one of description, variants, or availability). Update the any() condition to enforce these stricter requirements instead of accepting any single non-empty field from the current list.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/pipeline/extract_records.py around lines 321 - 345, The early return statement in the titleless row check (when title is falsy, returning based on _detail_record_has_strong_product_signal) bypasses the detail_record_rejection_reason check, allowing identity mismatches and wrong-product URLs to leak through. Restructure the logic so that the detail_record_rejection_reason call executes before the titleless row early return, ensuring identity rejection is applied to all records regardless of whether they have a title. This can be done by moving the detail_record_rejection_reason check to the beginning of the function or rearranging the conditional logic so the early return for titleless rows comes after the identity rejection check.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/regression/test_crawl_engine.py around lines 58 - 70, Add a negative test case after the existing test_extract_records_keeps_detail_row_without_title_when_product_signal_exists function to verify that extract_records properly rejects titleless detail rows that contain only weak product signals. Create a new test function that calls extract_records with adapter_records containing only one weak signal field such as currency, availability, or description (without strong signals like sku and price), then assert that such rows are either empty or do not appear in the result to ensure shell rows with insufficient signal strength are filtered out.

These are comments left during a code review. Please review all issues and provide fixes.

1. incorrect condition logic: Single-word brand extraction is incorrectly disabled for non-numeric brands, causing brand inference regressions.
   Path: backend/app/services/extract/detail/assembly/record_sanitization.py
   Lines: 294-294

2. logic error: Existing color values can be incorrectly clobbered by lower-confidence title-derived color guesses.
   Path: backend/app/services/extract/detail/assembly/record_sanitization.py
   Lines: 539-539

3. logic error: Ignoring query parameters in product URL matching can misclassify different products as the same item.
   Path: backend/app/services/extract/variant_identity_merge.py
   Lines: 234-234

4. logic error: Counting unfiltered variant entries can trigger offer-stripping logic on too few real variants.
   Path: backend/app/services/extract/variant_normalization/backfill.py
   Lines: 268-268

5. api mismatch: Offer removal uses a narrower identity definition and can delete valid variant offers.
   Path: backend/app/services/extract/variant_normalization/backfill.py
   Lines: 281-281

6. logic error: Replacing existing variants with low-identity DOM rows can drop previously captured variant evidence.
   Path: backend/app/services/extract/detail/variants/dom_extraction.py
   Lines: 279-279

7. logic error: Variant rows carrying stock-state information can be incorrectly pruned because availability is no longer considered a preserving signal.
   Path: backend/app/services/extract/variant_structural_pruning.py
   Lines: 401-401

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/price/core.py around lines 355 - 367, The function _backfill_variant_currency_from_parent unconditionally propagates parent currency to all variants without respecting the stricter gating logic applied earlier in the pipeline by _enforce_variant_currency_context using _variant_can_inherit_parent_offer. This causes variants that should not inherit the parent currency (representing different products) to be incorrectly overwritten. Apply the same _variant_can_inherit_parent_offer check within _backfill_variant_currency_from_parent before assigning currency to selected_variant and variants to align with the earlier gating logic in backfill.py, or add clear documentation explaining why the localized override scenario intentionally bypasses URL-based gating constraints.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/variant_normalization/backfill.py around lines 271 - 298, The _variant_has_offer_identity function in backfill.py checks 5 fields (sku, variant_id, url, image_url, barcode) but inconsistent definitions exist in resolution.py and validation.py that check different field combinations, causing unpredictable offer inheritance behavior. Extract the offer identity check logic into a single canonical helper function in variant_identity_merge.py (which already handles variant identity logic), then replace all three implementations across backfill.py, resolution.py, and validation.py with imports and calls to this centralized definition to ensure consistent behavior across all code paths.