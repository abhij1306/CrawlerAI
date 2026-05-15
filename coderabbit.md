Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_detail_extractor_structured_sources.py around lines 369 - 426, The test test_extract_ecommerce_detail_prefers_localized_jsonld_price_over_state_variants indexes rows[0] without asserting the number of returned rows; add an explicit assertion (e.g., assert len(rows) >= 1 or assert len(rows) == 1) right after calling extract_records so failures surface as clear test assertions instead of IndexError, and apply the same row-count assertion pattern to other tests that index rows (e.g., other ecommerce_detail tests referenced around the same test group) to harden them.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_runtime.py around lines 126 - 133, The imported constants BROWSER_CAPTURE_MAX_NETWORK_PAYLOADS, BROWSER_CAPTURE_MAX_NETWORK_PAYLOAD_BYTES, BROWSER_CAPTURE_QUEUE_SIZE, and BROWSER_CAPTURE_WORKERS are unused except being re-exported via __all__; either remove these imports if not needed or keep them but add a concise comment above the imports explaining they are intentionally re-exported for public API/backwards-compatibility (and reference __all__), so future readers understand the intent; update import list in browser_runtime.py and ensure __all__ remains consistent with the chosen approach.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_fetch_support.py around lines 104 - 107, The dict construction for behavior diagnostics is not null-safe; replace dict(behavior_diagnostics) with a null-safe fallback (e.g., dict(behavior_diagnostics or {})) in the same block where "host_policy_snapshot" and other keys are assembled in browser_fetch_support.py so that behavior_diagnostics being None won't raise a TypeError; keep the same pattern used for host_policy_snapshot and ensure any downstream consumers still receive an empty dict when diagnostics are absent.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_fetch_support.py around lines 23 - 27, The variable page_title is pre-initialized to "" before the try/except, so remove the redundant reassignment inside the except; in the block where you call clean_text(await page.title()) (symbols: page_title, clean_text, page.title()), replace the except Exception handler's body with a simple pass (or remove the except body entirely) so the initial "" remains as the fallback.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_fetch_support.py around lines 72 - 75, The code currently accesses finalized["content_type"] and finalized["blocked"] directly which can raise KeyError; change these to use finalized.get("content_type", "") and finalized.get("blocked", False) and wrap as before (e.g., content_type=str(finalized.get("content_type", "")) and blocked=bool(finalized.get("blocked", False))) to match the defensive pattern used elsewhere (see usages of finalized and finalized_status_code); if those keys are truly guaranteed add a brief comment explaining the invariant instead of changing access.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_dom_variant_options.py around lines 156 - 157, The code currently always overwrites entry["stock_quantity"] when stock_quantity is not None, unlike availability/url/image_url which only set when the existing entry value is empty; update the assignment for stock_quantity to follow the same pattern (only set when entry.get("stock_quantity") is empty/falsey or None) so it doesn't unconditionally overwrite existing DOM-agnostic values—modify the conditional around stock_quantity in extract/detail_dom_variant_options.py (the block that writes entry["stock_quantity"]) to mirror the logic used for availability, url, and image_url.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_coerce_price.py around lines 26 - 40, The generator building CURRENCY_CODE_PATTERN uses redundant str() conversions when you've already checked isinstance(code, str); update the comprehension inside CURRENCY_CODE_PATTERN to avoid unnecessary casts: where you call re.escape(str(code)) and len(str(code)) replace those with re.escape(code) and len(code) (and likewise remove the initial str(code) conversion in the inner generator so it yields code directly), keeping the isinstance(code, str) and the 3-character length check; this targets the CURRENCY_CODE_PATTERN expression and the use of CURRENCY_CODES.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_coerce_price.py around lines 15 - 25, CURRENCY_SYMBOL_PATTERN builds a joined regex from CURRENCY_SYMBOL_MAP keys but redundantly calls str() twice; to fix, convert each key to str only once in the inner generator and remove the outer str() in the sorted call so you call sorted((str(symbol) for symbol in dict(CURRENCY_SYMBOL_MAP or {}).keys() if symbol), key=len, reverse=True) then re.escape over those results — update the expression around CURRENCY_SYMBOL_PATTERN, keeping re.escape, sorted(..., key=len, reverse=True) and the fallback r"(?!)".

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/log-terminal.tsx around lines 971 - 976, The onKeyDown handler incorrectly checks for an empty string (e.key === '') which never matches; change the condition in the handler that calls toggleGroup(group.key) to check for the space key (e.key === ' ') in addition to Enter (e.key === 'Enter') so keyboard toggling works as intended — update the inline handler where toggleGroup(group.key) is invoked to use e.key === ' ' instead of e.key === ''.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/records-table.tsx around lines 42 - 59, The virtualization calculations (startIndex, endIndex, windowedRecords, topSpacerPx, bottomSpacerPx) are computed but never applied; replace the full-list rendering so the table/body maps over windowedRecords (not records) and render two spacer divs (or rows) above and below the mapped window with inline heights of topSpacerPx and bottomSpacerPx to preserve scroll space, and ensure the scroll container uses setContainerRef and a scroll handler that calls setScrollTop(e.currentTarget.scrollTop) to update startIndex as the user scrolls; update any existing container element to attach ref={setContainerRef} and onScroll so virtualization updates correctly.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Browser diagnostics can report the wrong proxy bridge usage state.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 1112-1112

2. logic error: Custom token pricing from configuration is discarded for unsupported providers.
   Path: backend/app/services/config/llm_runtime.py
   Lines: 131-131

3. possible bug: Replacing `_settings_config` with `settings_config` may alter settings loading.
   Path: backend/app/services/config/product_intelligence.py
   Lines: 257-257

4. possible bug: Import-time copies of runtime values can become stale and ignore later configuration changes.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 586-586

5. logic error: Variant backfilling can duplicate and inflate existing variants when DOM rows are expanded unnecessarily.
   Path: backend/app/services/extract/detail_dom_extractor.py
   Lines: 1078-1078

6. possible bug: Removing the retry-sleep wrapper breaks the module’s retry-delay contract.
   Path: backend/app/services/fetch/fetch_context.py
   Lines: 123-123

7. logic error: Extracted variant-option logic may change how variant axes are normalized.
   Path: backend/app/services/js_state/state_normalizer.py
   Lines: 683-683

8. integration bug: The new public `aggregate_verdict` helper is already exported from the publish package, so this is not a real breakage.
   Path: backend/app/services/publish/verdict.py
   Lines: 21-21

9. logic error: Multi-image fields now lose all but the first URL.
   Path: backend/app/services/shared/field_coerce.py
   Lines: 1168-1168

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.