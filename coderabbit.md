These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Propagating cancellation from cleanup changes timeout failures into cancellation errors and breaks stage timeout behavior.
   Path: backend/app/services/acquisition/browser_stage_runner.py
   Lines: 98-98

2. logic error: Using global merged URL hints instead of surface-specific hints can misclassify anchor density and select the wrong page HTML.
   Path: backend/app/services/acquisition/browser_page_helpers.py
   Lines: 106-106

3. type error: Invalid numeric config now propagates as a string fallback, causing later runtime type failures where integers are required.
   Path: backend/app/services/dom/section_extraction.py
   Lines: 24-24

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/sitemap_resolver.py around lines 872 - 884, Extract the duplicated _text_has_token implementation into a single shared utility function (e.g., text_has_token) in a new or existing common utils module, replace the duplicate definitions in both sitemap_resolver.py and the other crawl module with an import from that utility, remove the duplicate local function definitions, update any callsites to the new imported name if you rename it, and run tests/lint to ensure imports and references are correct.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/text/sanitizer.py at line 62, Replace the manual re.compile(...) blocks in this module with the shared compile_regex_patterns helper from app.services.shared.regex_patterns: import compile_regex_patterns (already suggested) and call it wherever pattern tuples are constructed (the places flagged around lines 64-88, 117-119, 132-134, 202 and the existing import at line 62), ensuring you pass the same pattern list and case-insensitive option so the behavior and fallback to an empty tuple remain identical; remove the duplicated manual compilation logic and use the single helper for CLEANUP/EXCLUSION/NON_TEXT style pattern variables used by the sanitizer functions.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/playground_service.py around lines 58 - 59, The classifier that returns "detail" for any surface ending with "_detail" is fine, but run creation still hardcodes ECOMMERCE_DETAIL_SURFACE (used in the code paths that create detail runs), causing non-ecommerce detail surfaces (e.g., content_detail, article_detail) to be routed incorrectly; update the run creation logic (the code that currently substitutes ECOMMERCE_DETAIL_SURFACE at creation—refer to the run creation sites around where detail runs are constructed) to use the incoming surface value (or a small mapping from incoming surface → extractor surface) instead of the hardcoded ECOMMERCE_DETAIL_SURFACE so that each *_detail surface is preserved and the correct extractor surface is used.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_playground_service.py around lines 571 - 585, The test test_classify_input_url_treats_non_ecommerce_detail_surfaces_as_detail currently only asserts that _classify_input_url(url) == "detail"; extend it to also verify downstream behavior by asserting that when start_discover or the detail run creation is invoked for these URLs it does not use surface="ecommerce_detail" (e.g., mock or inspect start_discover / run creation and assert the surface arg != "ecommerce_detail" or that the created run.surface == "detail"). Update the test to exercise the code path that calls start_discover/run creation and add an assertion that the surface used is not "ecommerce_detail".

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @docs/plans/site-link-category-discovery-plan.md around lines 45 - 57, Update the stale verification metadata in the plan: change the Verify for the site_link_discovery run to reflect 5 tests passed (replace "3 passed" with "5 passed" for `tests/component/test_site_link_discovery.py`) and correct the Crawl Studio API verify path to `backend/tests/component/test_crawls_category_discovery_api.py` (and its pass count if needed) so the Verify lines match the current test filenames and results referenced elsewhere in the diff.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/dom/section_extraction.py around lines 25 - 38, The fallback "or CONSTANT" is redundant here: update the assignments for _max_section_blocks and _max_section_chars to just use _safe_int(CONSTANT, default=CONSTANT) without the "or CONSTANT" tail; locate the two expressions that call _safe_int for DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS and DETAIL_LONG_TEXT_MAX_SECTION_CHARS and remove the "or ..." fallback, and ensure the constants DETAIL_LONG_TEXT_MAX_SECTION_BLOCKS and DETAIL_LONG_TEXT_MAX_SECTION_CHARS are indeed non-zero positive integers (or adjust defaults) before making this simplification.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/finalization.py around lines 87 - 92, The parameter field_names is annotated too broadly as object; change its type to a more specific iterable of strings (e.g., Iterable[str] | None or Sequence[str] | None) in the finalize_candidate_fields signature and related type imports, then keep the existing runtime handling that treats non-iterables as empty (no logic change)—update the annotation on finalize_candidate_fields and any local variables or type hints that reference field_names to match the selected Iterable[str] | None type to improve clarity and type safety.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/url_utils.py around lines 66 - 79, The use of urlencode(..., doseq=True) in variant_url_with_param is unnecessary because we only build single-string query values (variant_id) and parse_qsl returns single-value pairs; remove the doseq=True argument so call becomes urlencode(query) to simplify intent and avoid confusion while keeping the same output; update the call in variant_url_with_param (where parsed, query, and composed are created) accordingly.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/record_overlay.py around lines 32 - 44, The deep merge in overlay_record currently recurses unbounded; add a max_depth parameter (e.g., max_depth: int = 10) to overlay_record and check at the start of the function that if max_depth <= 0 the function stops deep recursion (e.g., fall back to non-recursive assignment/merge or return field_value), and in the recursive call inside the block that sets merged[normalized_field] pass max_depth=max_depth-1 so recursion decrements the counter; keep other params (skip_fields, overwrite_fields, skip_private, deep_structured) unchanged and ensure any other internal recursive calls also propagate the decremented max_depth.