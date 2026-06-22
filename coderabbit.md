These are comments left during a code review. Please review all issues and provide fixes.

1. incorrect condition logic: Generic listing cards without price are always prevented from producing product URLs, causing valid products to be dropped.
   Path: backend/app/extraction/listing.py
   Lines: 186-186

2. logic error: Multiple valid image candidates can be discarded entirely when none match positive scope tokens.
   Path: backend/app/extraction/collectors/dom.py
   Lines: 72-72

3. incorrect condition logic: A broad subset check can misclassify valid one-word titles as truncated.
   Path: backend/app/extraction/pipeline.py
   Lines: 230-230

4. logic error: A heuristic title flag is promoted to hard invalidation, causing valid title evidence to be dropped.
   Path: backend/app/extraction/resolution.py
   Lines: 333-333

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/shared/material_terms.py around lines 68 - 82, The percentage_material_parse function assumes that DATA_ENRICHMENT_MATERIAL_PERCENTAGE_RE has named groups called "material" and "percent", but this assumption is never validated. If the config pattern does not include these named groups, the match.group("material") call on line 79 will raise a runtime error. To fix this, add defensive handling when accessing the named groups from matches, either by checking if the groups exist before accessing them or by wrapping the group access in a try-except block to catch AttributeError or IndexError exceptions that would occur if the expected named groups are not present in any of the patterns.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/collectors/js_state.py around lines 297 - 304, The `_first` function recursively searches through nested dictionaries without any depth limit, which could cause a RecursionError on deeply nested structures. Add a depth parameter to the `_first` function signature with a default value and a maximum recursion depth limit (e.g., a reasonable constant like 100), then add a check at the beginning of the function that returns None if the current depth exceeds the limit. When making the recursive call to `_first` within the function, increment the depth parameter by one to track the recursion level.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/extraction/documents.py around lines 20 - 25, In the safe_css method, add logging when exceptions are caught to aid debugging. Currently, the exception handler silently returns an empty tuple without recording any error information. Add a logger statement in the except block to capture and log the exception details before returning the empty tuple, ensuring that selector parsing failures and other errors are recorded for troubleshooting purposes.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/records/field_url_normalization.py around lines 188 - 200, The regex patterns in the remove_patterns tuple are being recompiled on every iteration of the loop when used with re.fullmatch at line 200, causing performance issues and potential runtime errors from invalid patterns. Pre-compile the patterns once when creating the remove_patterns tuple by using re.compile() on each pattern string from PUBLIC_RECORD_DETAIL_CANONICAL_QUERY_PATTERNS, then update the re.fullmatch call to use the compiled pattern objects directly instead of the string patterns.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/field_mappings.py around lines 305 - 333, Add a clarifying comment above or between the ECOMMERCE_INTEGER_IDENTIFIER_FACT_TYPES and ECOMMERCE_TYPED_STRING_FACT_TYPES frozensets to document their relationship. The comment should explain that ECOMMERCE_INTEGER_IDENTIFIER_FACT_TYPES represents a strict subset of ECOMMERCE_TYPED_STRING_FACT_TYPES where integer identifiers receive special int→str conversion handling before general string-type validation is applied. This will make the implicit relationship explicit for future maintainers.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/records/url_identity.py around lines 94 - 107, Add a docstring to the conflicting_product_asset_urls function that explains the detection logic and its purpose. The docstring should clarify that the function identifies assets as conflicting only when they share some (but not all) identity tokens with the product values, and explain that this conditional approach prevents false positives when no assets match product identity at all. Include descriptions of the parameters (product_values and asset_urls) and the return value (frozenset of conflicting URLs), making the non-obvious conditional logic explicit for future maintainers.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/runs/page-view.tsx around lines 259 - 268, The preloadCrawlRunRoute() function is being called repeatedly whenever queryData?.items changes in the useEffect, causing unnecessary preload calls. Create a useRef to track whether the preload has already been completed, then add a conditional check inside the useEffect to call preloadCrawlRunRoute() only once. After the first successful preload, update the ref to indicate completion so subsequent useEffect runs skip this call. You can remove queryData?.items from the dependency array or keep it but guard the preloadCrawlRunRoute() call with your ref check.