Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_runtime.py around lines 918 - 924, The _origin_warmup_state_lock function reads and writes the shared _ORIGIN_WARMUP_STATE_LOCKS dict without synchronization, risking races across threads; fix by introducing a module-level threading.Lock (e.g., _ORIGIN_WARMUP_STATE_LOCKS_MUTEX) and acquire it around the get/create/write sequence in _origin_warmup_state_lock so the lookup and possible insertion into _ORIGIN_WARMUP_STATE_LOCKS are atomic, then return the per-loop asyncio.Lock as before. Ensure you import threading and only hold the mutex for the minimal duration while accessing the dictionary.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/assembly/final_cleanup.py around lines 204 - 207, The helper _all_variants_have_zero_stock currently returns False whenever any variant is missing the stock_quantity key because row.get("stock_quantity") yields None which is not in (0, "0"); if this conservative behavior is intentional, add a brief clarifying comment above _all_variants_have_zero_stock stating that missing stock_quantity is treated as unknown (not zero) and therefore prevents the function from returning True, otherwise update the logic to treat missing stock_quantity as zero (e.g., normalize with default) and document that choice in the same comment so future readers know the intended semantics.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/assembly/final_cleanup.py around lines 220 - 236, In _reconcile_variant_derived_parent_fields replace the list comprehension used only to test truthiness with an any(...) over a generator so it short-circuits; specifically change the condition that currently does [row for row in record.get("variants") or [] if isinstance(row, dict)] to use any(isinstance(row, dict) for row in record.get("variants") or []) so the check for any valid variant is efficient and stops at the first match.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/assembly/record_sanitization.py at line 228, The hardcoded set continuation_tokens = {"hilfiger", "originals"} should be moved into the extraction rules/config so it can be configured like DETAIL_BRAND_PREFIX_STOP_TOKENS; update the code that references continuation_tokens in record_sanitization.py to read the tokens from the extraction rules object (with a sensible default identical to the current set if the config key is missing), replace direct uses of continuation_tokens with the configured variable, and add documentation/tests to ensure the new config key is loaded and used at runtime.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/assembly/record_sanitization.py around lines 222 - 238, The early return for numeric brand tokens (when re.fullmatch(r"\d{2,3}", raw_words[0]) is true) skips the path contiguity check and can yield false positives; instead, treat the numeric token like other candidate_tokens: build candidate_tokens from title_parts (using the same continuation logic and max_words / continuation_tokens as used later), call _tokens_appear_contiguously(path_parts, candidate_tokens) to verify contiguity, and only then return the joined raw_words[:take]; update the branch that currently returns raw_words[0] to follow this flow so numeric prefixes are validated against the URL path before returning.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/assembly/record_sanitization.py around lines 271 - 289, The _repair_detail_color_from_description function may overwrite a reliable structured color; update it to consult _field_sources before replacing: fetch record.get("_field_sources") as a dict and if record already has a current color and _field_sources.get("color") exists with any source other than "description_color_repair" (or other description-only marker) then do not replace; only set record["color"] and write field_sources["color"] = ["description_color_repair"] when there is no current color or when existing sources indicate the color already came from description. Reference symbols: _repair_detail_color_from_description, _field_sources, "color", DETAIL_QUOTED_COLOR_PATTERN.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/text/sanitizer.py around lines 448 - 453, The comprehension building protected_identity_tokens repeatedly calls detail_product_text_tokens(record.get("title")), which is wasteful and unclear; pre-compute the title tokens once (e.g., title_tokens = set(detail_product_text_tokens(record.get("title"))) or similar) before the comprehension and then use that variable in the comprehension's condition instead of calling detail_product_text_tokens(record.get("title")) each iteration, keeping the existing filters (len(token) >= _token_min_len_chunk and token not in title_tokens) and preserving use of title_hint and record.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/text/sanitizer.py around lines 513 - 555, The function _trim_description_to_identity_hint currently recomputes hint/protected identity tokens redundantly; change its signature to accept a pre-computed set (e.g., protected_identity_tokens: set[str]) instead of title_hint, update the caller that computes protected_identity_tokens to pass that set into _trim_description_to_identity_hint, and replace all uses of the local hint_tokens variable with the passed protected_identity_tokens (remove the clean_text/title/tokenization logic inside _trim_description_to_identity_hint); ensure null/empty checks still work (return early if description or protected_identity_tokens empty) and preserve the existing logic that uses detail_product_text_tokens, detail_long_text_chunk_has_product_name_shape, and _chunk_has_named_product_signal.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/variants/pruning.py around lines 547 - 552, The helper function _query_dimension_is_tiny is duplicated; extract it to a shared utility (e.g., image_utils) and import it from there in both modules to maintain a single source of truth: create a new function (query_dimension_is_tiny) in a shared module that contains the same regex logic currently in _query_dimension_is_tiny, replace the local definitions in pruning.py and cleanup.py to import and call the shared query_dimension_is_tiny, and remove the duplicated local functions (ensure public name matches callers or update callers to the new name).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_coerce.py around lines 417 - 433, Add a brief docstring to _coerce_simple_string_dict_scalar explaining that this fallback parser naïvely splits on commas and therefore does not support values containing embedded commas (e.g., "{'name': 'Foo, Inc'}"), so callers should prefer JSON parsing when commas in values are possible; include the limitation, expected input shape, and that the function returns None on ambiguous/malformed input.

These are comments left during a code review. Please review all issues and provide fixes.

1. Code Quality: Context acquisition now applies the slot timeout twice, causing requests to exceed the configured maximum wait time.
   Path: backend/app/services/acquisition/browser_pool.py
   Lines: 404-404

2. Code Quality: Outer cancellation can leave the spawned async task running, causing orphaned background work.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 86-86

3. Code Quality: Timeout exceptions from the inner operation now escape instead of being normalized to a timeout result.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 93-93

4. Code Quality: Per-loop locking on globally shared warmup state introduces a cross-loop race condition.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 119-119

5. Code Quality: Loop-keyed lock caching leaks references to old event loops and can grow memory usage over time.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 915-915

6. Code Quality: The new Shopify image-path regex incorrectly rejects valid URLs that include query parameters.
   Path: backend/app/services/config/extraction_rules/_images.py
   Lines: 59-59

7. Code Quality: Canonicalization drops store identity and can merge distinct Shopify images into the same canonical URL.
   Path: backend/app/services/dom/image_extraction.py
   Lines: 154-154

8. Code Quality: Parent availability is used as evidence for derivation, which can cause legitimate parent availability to be removed later.
   Path: backend/app/services/extract/detail/assembly/final_cleanup.py
   Lines: 188-188

9. Code Quality: Using only one variant image to detect derivation can preserve stale parent images after variant cleanup.
   Path: backend/app/services/extract/detail/assembly/final_cleanup.py
   Lines: 82-82

10. Code Quality: Numeric prefixes are incorrectly treated as brands, causing incorrect brand assignment.
   Path: backend/app/services/extract/detail/assembly/record_sanitization.py
   Lines: 210-210

11. Code Quality: Existing color values can be incorrectly overwritten by description-derived fallback data.
   Path: backend/app/services/extract/detail/assembly/record_sanitization.py
   Lines: 250-250

12. Code Quality: Brand fallback logic can misattribute brands by matching arbitrary hostname labels.
   Path: backend/app/services/extract/detail/assembly/record_sanitization.py
   Lines: 232-232

13. Code Quality: An early return short-circuits existing family-matching heuristics and can falsely drop valid images.
   Path: backend/app/services/extract/detail/images/cleanup.py
   Lines: 290-290

14. Code Quality: Converting a regex constant with `str()` can produce a non-matchable pattern and break product-code extraction.
   Path: backend/app/services/extract/detail/images/cleanup.py
   Lines: 57-57

15. Code Quality: Re-tokenizing the same title inside a comprehension causes unnecessary repeated work and degrades sanitization performance.
   Path: backend/app/services/extract/detail/text/sanitizer.py
   Lines: 446-446

16. Code Quality: Repeating the same normalization call per chunk introduces avoidable duplicate processing in long-text parsing.
   Path: backend/app/services/extract/detail/text/sanitizer.py
   Lines: 530-530

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.