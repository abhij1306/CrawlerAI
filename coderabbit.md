Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/main.py around lines 50 - 52, The call to configure_logging() is executed at import time; move it into the application's lifespan startup block so startup logging is configured during the lifespan context rather than as an import-side effect. Specifically, remove or comment out the top-level configure_logging() invocation and call configure_logging() at the beginning of the lifespan context manager (the lifespan startup routine referenced in the diff) before any other startup tasks run; this keeps configure_logging() as part of the startup sequence and avoids import-time side effects.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/models/crawl_run.py around lines 104 - 105, In CrawlRun's status-transition code where completed_at is set (the branch that currently does "else: self.completed_at = None"), avoid the redundant assignment by only clearing completed_at when it's non-None (e.g., if self.completed_at is not None: self.completed_at = None) or simply remove the else assignment entirely; this prevents unnecessary attribute dirtying in SQLAlchemy while keeping the terminal-branch assignment behavior intact.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/models/data_enrichment.py around lines 26 - 28, The new ForeignKey on data_enrichment.user_id uses ondelete=CASCADE which may be inconsistent with other user-owned models; verify consistency by searching for other occurrences of ForeignKey(USERS_FK) (e.g., in models like crawl_runs, crawl_records) and confirm they also use ondelete=CASCADE or intentionally differ; if they differ, decide the correct ownership semantics and update data_enrichment.user_id (or the other models) to match; ensure you add a proper DB migration to apply the ondelete behavior and run tests/grep to find any code that assumes enrichment jobs survive user deletion and update that logic accordingly (references: user_id, ForeignKey(USERS_FK, ondelete=CASCADE) in data_enrichment.py).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/models/product_intelligence.py around lines 33 - 35, You changed product intelligence's user_id to nullable with ondelete=SET_NULL in the ProductIntelligence model; add and run an ALTER TABLE migration that converts user_id to NULLABLE and backfills/validates existing rows, update all call sites (job creation services, serializers, API endpoints, e.g., functions/methods that construct or read ProductIntelligence instances and any code referencing job.user_id) to handle None safely, adjust queries that filter by user_id to consider IS NULL or explicit checks, and review authorization logic (any check_authorization/ownership methods that assume job.user_id) to handle orphaned jobs; finally confirm intended semantics for ondelete=SET_NULL vs cascade and document/implement the desired retention policy for ProductIntelligence records when Users are deleted.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/_batch_runtime.py around lines 404 - 407, The current finally block cancels prewarm_task and uses with suppress(Exception): await prewarm_task, but CancelledError derives from BaseException so it will escape; update the suppression to catch asyncio.CancelledError (or use suppress(BaseException)) around the await so that awaiting the cancelled prewarm_task in process_run (the prewarm_task cancel/await block) does not propagate CancelledError; ensure you import asyncio.CancelledError if checking that specific exception.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_interstitial.py around lines 163 - 166, The force=True on locator.click suppresses Playwright actionability checks; add a log entry immediately before the call to locator.click that records that a force-click is being used and relevant context (e.g., the locator or selector string, click_timeout_ms, and any identifying text/attributes) so you can debug when an overlay or wrong element is clicked; locate the call to locator.click in browser_interstitial.py (the site that uses click_timeout_ms and force=True) and insert a logger.debug/info line referencing those symbols before the await locator.click(...) invocation.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_interstitial.py around lines 29 - 33, The fallback exception classes in browser_interstitial.py should mirror Playwright's hierarchy so timeout errors are a subclass of generic Playwright errors; change PlaywrightTimeoutError to inherit from PlaywrightError (i.e., make PlaywrightTimeoutError extend PlaywrightError instead of Exception) so existing except PlaywrightError handlers will also catch timeouts.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_interstitial.py around lines 147 - 152, The fallback logic computing postclick_wait_ms is duplicated; extract it into a single helper (e.g., compute_postclick_wait_ms or get_postclick_wait_ms) that reads crawler_runtime_settings.traversal_location_interstitial_postclick_wait_ms and falls back to crawler_runtime_settings.cookie_consent_postclick_wait_ms, then replace the duplicated inline computation in the current scope and in _dismiss_location_interstitial_by_text to call that helper (or compute once and pass the value into _dismiss_location_interstitial_by_text), and remove the duplicated branch code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_readiness.py around lines 332 - 338, The wrapper function listing_card_signal_count currently duplicates the logic of listing_card_signal_count_impl; change it to delegate instead: import or reference listing_card_signal_count_impl and return await listing_card_signal_count_impl(page, surface=surface) rather than reimplementing the logic, so the wrapper follows the same DRY pattern as other wrappers in this file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_storage_state.py around lines 28 - 29, Extract the hardcoded minimum timeout (0.1) into the config by adding a float setting named min_browser_context_timeout_seconds in the runtime settings module (e.g., app/services/config/runtime_settings.py), then replace the literal 0.1 occurrences in browser_storage_state.py with a reference to that config value (use the config symbol min_browser_context_timeout_seconds). Update both places noted (the max(...) call around line 28 and the other occurrence around lines 50–51) so the service reads the threshold from config rather than using the hardcoded literal.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_storage_state.py around lines 50 - 57, The outer max(0.1, ...) around the whole expression is redundant because _browser_context_timeout_seconds() already returns >= 0.1; change the assignment for resolved_timeout_seconds to only enforce the 0.1 minimum when a user-supplied timeout_seconds is provided (i.e. if timeout_seconds is not None use max(0.1, float(timeout_seconds)), else use float(_browser_context_timeout_seconds())). Update the code that assigns resolved_timeout_seconds accordingly, keeping the variable name and using _browser_context_timeout_seconds() and timeout_seconds as the unique identifiers.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/traversal_card_counting.py around lines 269 - 276, The function is_marginal_card_gain contains hardcoded heuristic thresholds (6, 3, 2, 5) — extract these into configuration values under app/services/config (e.g., listing_min_count_threshold, listing_min_items_multiplier, best_gain_min_multiplier, marginal_gain_divisor) and replace the literals in is_marginal_card_gain with references to those config constants; keep the existing checks and semantics (use crawler_runtime_settings.listing_min_items where used) but read multipliers and numeric thresholds from the new config so they can be tuned without modifying service code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/traversal_card_counting.py at line 48, Move hardcoded tunables into config: add SURFACE_JOB_PREFIX = "job_" and TRAVERSAL_STRONG_COUNT_MIN_THRESHOLD = 3 (alongside listing_min_items) in app/services/config/runtime_settings.py, then import those constants into traversal_card_counting.py and replace the literal checks — use str(surface or "").strip().lower().startswith(SURFACE_JOB_PREFIX) instead of the inline "job_" and use TRAVERSAL_STRONG_COUNT_MIN_THRESHOLD in place of the magic 3 (the places around selector_group assignment and the traversal strong-count logic).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/traversal_card_counting.py around lines 294 - 297, Move the hardcoded floor 8_192 out of traversal_card_counting and into the config module used by other runtime tunables: add a new config constant (e.g., TRAVERSAL_FRAGMENT_MIN_BYTES) under app/services/config/* and read it alongside crawler_runtime_settings.traversal_fragment_max_bytes, then compute fragment_budget = max(config.TRAVERSAL_FRAGMENT_MIN_BYTES, int(crawler_runtime_settings.traversal_fragment_max_bytes)). Update references in traversal_card_counting.py (the fragment_budget calculation) to use the new config constant and ensure any tests or callers that rely on this threshold use the config value.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/traversal_card_counting.py around lines 194 - 206, Replace the hardcoded snapshot/layout magic numbers in traversal_card_counting.py by adding config keys and using them instead of literals: move 1600, 24, 140, 80, and 150 into app/services/config (e.g., MAX_VISIBLE_TEXT_LENGTH, MAX_ANCHOR_LINKS, MAX_ANCHOR_HREF_LEN, MAX_ANCHOR_TEXT_LEN, OVERFLOW_SCROLL_THRESHOLD), export them from the config module, import that config where normalize/visibleText/anchorSummary/overflowContainers are computed, and replace the numeric literals in the visibleText, anchorSummary.slice/map and overflowContainers filter with the corresponding config values so the tunables live in config rather than service code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/traversal_card_counting.py around lines 203 - 206, The current DOM scan uses document.querySelectorAll('*') and calls window.getComputedStyle for each node (assigned to overflowContainers), which is expensive on large pages and when run repeatedly; change the selection to a narrower, likely-scrollable set (e.g., query selectors that target candidates like '[style*="overflow"], [class*="scroll"], .scroll-container, main, body, .content, .modal') and/or perform the check once and cache the result between pagination steps (or debounce it) inside the function that computes overflowContainers so you only call getComputedStyle on the reduced candidate set (refer to the overflowContainers variable and the code that computes it) rather than every DOM node each loop.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/extraction_rules.exports.json at line 3911, The "/p" path marker in extraction_rules.exports.json is overly broad and will match unrelated paths; remove or replace it with a more precise pattern (e.g., change the entry for "/p" to a regex/end-anchor like "/p$" or a query-aware form such as "/p?" or only include it if you have evidence of usage), and ensure you keep the existing more specific markers ("/p/", "/p.", "-p-", "-p.") intact so you don't introduce false positives when matching listing detail pages.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/selectors.exports.json at line 77, The new broad selector "[data-product-id]" duplicates and widens the existing ".grid-item[data-product-id]" rule—grep the codebase for usages of both selectors to determine whether you intentionally need to match non-.grid-item product cards; if you only need grid items remove the "[data-product-id]" entry and keep ".grid-item[data-product-id]"; if you need both keep both but narrow the broad one to avoid nested/metadata matches (e.g., use a direct child or more specific class rather than a bare attribute selector) and update selectors.exports.json accordingly so you do not introduce false positives.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_identity.py around lines 363 - 389, _detail_marker_matches currently searches the entire URL string which allows markers to match in the domain or query (causing false positives); change it to parse the URL (use urllib.parse.urlparse) and run the marker matching against the parsed path (urlparse(url).path) only, keeping the existing boundary logic (marker.endswith("/") special case and the loop) and update any callers or tests that assume full-URL matching (e.g. references to LISTING_DETAIL_PATH_MARKERS and detail_path_hints("ecommerce_detail") should still provide path-prefixed markers or be validated accordingly).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail_identity.py around lines 363 - 389, The docstring and inline comment for _detail_marker_matches are out of sync with the code: update the function docstring (the paragraph explaining valid boundary characters) and the inline comment above the boundary check to include '.' and '&' as valid boundaries (in addition to '/', '?', '#', digit, and end-of-string) so the docs match the implemented check that tests next_char in "/?.#&" or next_char.isdigit().

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_candidate_ranking.py around lines 228 - 232, Replace the two hardcoded thresholds in the support-signal override block with runtime config values: add listing_cohort_support_override_min_records (int) and listing_cohort_support_override_ratio (float) to crawler_runtime_settings (or the existing runtime_settings), then in the function containing the cohort_pass logic (the support-signal override block in listing_candidate_ranking.py) use those values instead of 5 and len(quality_metrics) // 2 (i.e. check len(quality_metrics) >= listing_cohort_support_override_min_records and supported_records >= max(1, ceil(listing_cohort_support_override_ratio * len(quality_metrics))) or an equivalent ratio-based comparison), preserving existing semantics and types.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_card_fragments.py around lines 73 - 75, The docstring for _listing_count_bucket currently omits that None is accepted and treated as 0; update the docstring to explicitly state that None will be interpreted as 0 (e.g., "If count is None it is treated as 0") and ensure the existing bucket description remains (``{0, 1, 2_5, 6_plus}``) so callers know the None-handling behavior and resulting buckets; modify the docstring directly above the function definition for _listing_count_bucket.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/listing_integrity_gate.py around lines 100 - 103, The hardcoded thresholds in the support_override computation should be moved into crawler_runtime_settings and consumed from there: add two settings (e.g., listing_support_override_min_records: int = 5 and listing_support_override_min_ratio: float = 0.5) to crawler_runtime_settings, then replace the inline literals in listing_integrity_gate.py’s support_override logic (currently using 5 and record_count // 2) with comparisons against crawler_runtime_settings.listing_support_override_min_records and crawler_runtime_settings.listing_support_override_min_ratio (apply the ratio to record_count to compute the required support_signal_count threshold), keeping the existing variable names record_count and support_signal_count and preserving the boolean semantics.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/fetch/fetch_context.py around lines 686 - 724, The duplicated cooldown-and-continue logic after a host-block should be extracted into a shared async helper (e.g., _apply_post_block_cooldown_if_needed) that takes engine_index and engine_attempts and returns whether the caller should continue to the next engine; replace the duplicated blocks in the timeout-exception branch and the blocked-result branch with calls to this helper, using crawler_runtime_settings.browser_post_block_cooldown_ms to compute cooldown_ms and awaiting asyncio.sleep when >0, and then continue only if the helper returns True. Also remove or tighten the misleading condition that checks engine_index <= len(engine_attempts) in the timeout branch (since engine_index was already incremented) and rely on the helper to decide continuation; keep existing calls such as note_host_hard_block, _is_vendor_block_reason, _extract_vendor_from_reason, load_host_protection_policy and _extend_browser_engine_attempts_after_block unchanged.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/listing_extractor.py around lines 107 - 115, Move the import of extract_urls out of the function and into the module-level imports: add "from app.services.shared.url_utils import extract_urls" near the top of listing_extractor.py and remove the inline "from app.services.shared.url_utils import extract_urls" inside the fallback block that handles image extraction for ListItem/non-Product payloads; keep the existing logic that uses extract_urls(raw_image, page_url) to set record["image_url"] when available (variables: record, payload, raw_image, page_url, extract_urls).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/pipeline/extraction_loop.py around lines 860 - 864, The pipeline is defensively checking metrics in _ListingIntegritySnapshot but the real fix belongs in the extractor: update the listing_extractor (the code path that builds artifacts["listing_integrity"] inside extract_listing_records) to always set metrics to a dict (coerce or validate and default to {}) before attaching the payload; ensure the extractor does not write non-dict types for the "metrics" key, add validation/logging in the function that constructs the listing_integrity payload, and remove the downstream defensive type handling from _ListingIntegritySnapshot so pipeline assumes a dict.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/shared/field_coerce.py at line 605, The hardcoded field-specific regex patterns in backend/app/services/shared/field_coerce.py (the substitutions that modify the local variable cleaned, e.g., the size "(size...chart)" pattern and the other size/color patterns near lines with similar re.sub calls) should be moved into a config constant (similar to VARIANT_OPTION_VALUE_SUFFIX_NOISE_PATTERNS) under app/services/config/*; add a named config array (e.g., FIELD_SANITIZE_PATTERNS or VARIANT_FIELD_NOISE_PATTERNS) containing these regex strings, update the code in the function that sets/uses cleaned to iterate over that config and apply re.sub for each pattern, and ensure tests/imports are updated to reference the new config symbol instead of hardcoded patterns.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/conftest.py around lines 159 - 165, The fixture _isolate_artifact_storage currently redirects app_settings.artifacts_dir to workspace_tmp_path / "artifacts" but does not ensure the directory exists; update the fixture to explicitly create the artifacts directory (use workspace_tmp_path / "artifacts" and call mkdir with parents=True and exist_ok=True) either before or after monkeypatch.setattr so subsequent tests that write files won't fail due to a missing directory.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_listing_escalation_decision.py around lines 167 - 177, Clarify the tier progression and add/adjust tests to cover chromium's role: update the escalation logic (or tests) so the expected path is explicit (e.g., curl_cffi/httpx → patchright, or curl_cffi/httpx → chromium → patchright) and then add a test that calls _call(method="browser", browser_engine="chromium") to assert the correct behavior; if chromium is terminal assert result["should_retry"] is False and result["reason"] == "no_stronger_tier" (mirroring test_chromium_no_escalation), otherwise assert it escalates to the next tier (e.g., result indicates retry and the next engine is "patchright"). Ensure the helper _call and any escalation map used by the listing escalation decision reflect this clarified tier order.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_state_mappers.py at line 3, Replace the test alias by importing and using the canonical symbol directly: remove the alias `js_state_mapper` and import `state_normalizer` from `app.services.js_state`, then update all references in this test file that use `js_state_mapper` to `state_normalizer`; if this change breaks other tests or code, verify whether the old name maps in docs/CODEBASE_MAP.md and either update the map or add a compatibility import in the module `app.services.js_state` that re-exports `state_normalizer` under the legacy name.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_structure.py around lines 106 - 112, The test lists temporary "high-water marks" for Phase 3 owners (the Path entries like Path("app/services/dom/selector_engine.py"), Path("app/services/extract/detail_materializer.py"), Path("app/services/fetch/fetch_context.py"), Path("app/services/js_state/state_normalizer.py")) but has no mechanism to track their planned reduction after refactor; update test_structure.py to mark these entries as temporary by adding a tracked plan reference (e.g., link to an issue/verify-step or a structured metadata field such as temporary_high_water_marks with target reduction criteria), enforce that each temporary entry includes the owning-slice verify condition and a TODO/issue id, and add an assertion in the test that flags any temporary budget not reduced once its verify step (or issue status) is marked complete so these budgets cannot become permanent by accident.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/platforms.json around lines 827 - 896, The two platform entries ("family": "vtex" and "family": "sap_hybris") both target Whirlpool sites but lack documentation and risk misclassification; first, grep for other Whirlpool domains and confirm domain_patterns/readiness_domains in the vtex and sap_hybris objects have no overlap; second, if geographic split is intentional either consolidate into a single Whirlpool family with a platform_variant field (e.g., "platform": "vtex" or "sap_hybris") or add an explicit priority flag to the existing entries so detection precedence is deterministic; third, add a brief comment in platforms.json describing the geographic split and the chosen resolution (consolidation or priority) and update readiness_domains/domain_patterns accordingly.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/platforms.json around lines 864 - 896, The sap_hybris platform entry (family "sap_hybris") mixes generic Hybris detection (html_regex) with a Whirlpool-only domain allowlist (domain_patterns/readiness_domains), enforces an overly strict readiness_path_patterns ("^/.*\\.html"), and omits adapter_names; fix by either making this a generic Hybris detector or a Whirlpool-specific config: if generic, remove/supplement the Whirlpool-only domains (domain_patterns/readiness_domains) and ensure html_regex is tested/escaped properly; relax readiness_path_patterns to accept extensionless product/PLP routes (e.g., allow "^/.*" or include patterns like "^/p/|^/products/|^/.*\\.html"); and add a clear adapter_names array (e.g., "adapter_names": ["sap_hybris_adapter"] or the appropriate extractor) so extraction strategy is explicit.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/config/platforms.json around lines 827 - 863, The vtex entry currently mixes generic VTEX detection (html_contains/html_regex) with Whirlpool-only domain_patterns; decide scope then fix accordingly: if you want generic VTEX support (family: "vtex"), remove or generalize the domain_patterns array, keep the generic html_contains/html_regex, add an adapter_names field (e.g., ["vtex"] or your extractor name) and narrow readiness_path_patterns to product/category URL patterns (e.g., patterns matching product pages like "/p", "/product", "/products", or regex for "/[^/]+/p" instead of "^/.*$"); if you want Whirlpool-specific config, move this object to a brand-specific config and tighten html_contains/html_regex to include Whirlpool-specific markers and keep domain_patterns as-is and optionally add adapter_names for the Whirlpool adapter.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extraction_context.py around lines 198 - 204, Replace the hardcoded VTEX strings in extraction_context.py with config constants: move the "Product:" prefix and the "/{link_text}/p" URL pattern into a new config module (e.g., app.services.config.vtex_settings) as VTEX_PRODUCT_KEY_PREFIX and VTEX_PRODUCT_URL_TEMPLATE, then update the code that checks the key (str(key).startswith(...)) to use VTEX_PRODUCT_KEY_PREFIX and build the URL using VTEX_PRODUCT_URL_TEMPLATE.format(link_text=link_text) combined with base_origin; ensure imports reference the new config constants and keep existing variable names product_name, link_text, and url.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extraction_context.py around lines 224 - 226, Replace the hardcoded threshold "2" in the ItemList-returning block with the existing runtime setting used elsewhere: use crawler_runtime_settings.listing_min_items (or a similarly named config value) instead of the literal 2, ensuring the code references the same symbol used at line 147; if that symbol isn't in scope, import or pass crawler_runtime_settings into the function so the check and early-return use the shared configuration.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/script_text_extractor.py around lines 42 - 46, Replace the hardcoded regex and attribute in script_text_extractor.py by moving the configurable patterns into a new config module (e.g., app.services.config.script_extraction_config) and loading/compiling them at service init; specifically remove _TEMPLATE_SCRIPT_RE and instead read TEMPLATE_SCRIPT_PATTERNS (list of {"attribute", "regex"}) from the config, compile each regex into a pattern list used by the extractor, and update any use-sites in ScriptTextExtractor (or functions referencing _TEMPLATE_SCRIPT_RE) to iterate over the compiled patterns so different attributes like "data-varname", "data-state" or "data-id" can be tuned via config.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_platform_detection.py at line 87, The test uses a non-reserved domain "www.example-appliances.com" which may be registered and cause flakiness; update the URL string in the test (the literal containing "https://www.example-appliances.com/countertop-appliances/food-processors/food-processor-and-chopper-products") to use an RFC 2606 reserved domain such as "example.com" (e.g., "https://www.example.example.com/..." or "https://www.example.com/...") so the test uses a guaranteed-reserved domain; ensure you update the corresponding assertion or fixture that references this exact URL string in test_platform_detection.py.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Overly broad readiness matching can misclassify unrelated pages as VTEX storefront pages.
   Path: backend/app/services/config/platforms.json
   Lines: 827-827

2. logic error: The new regex only matches a `<script>` tag that is the first direct child inside `<template>` and whose `data-varname` attribute uses double quotes. Valid embedded state blocks can be skipped.
   Path: backend/app/services/script_text_extractor.py
   Lines: 42-42

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Overly broad readiness matching can mark unrelated pages as crawl-ready.
   Path: backend/app/services/config/platforms.json
   Lines: 848-848

2. logic error: Incomplete domain coverage can cause the same brand to be classified by different platform families.
   Path: backend/app/services/config/platforms.json
   Lines: 873-873

3. logic error: VTEX fallback builds product URLs directly from linkText/slug without normalization, so malformed or aliased paths can make emitted listing payloads unusable.
   Path: backend/app/services/extraction_context.py
   Lines: 204-204

4. possible bug: Template script extraction misses valid HTML variants because the regex only accepts double-quoted attributes.
   Path: backend/app/services/script_text_extractor.py
   Lines: 42-42

5. logic error: A catch-all readiness path pattern can misclassify unrelated pages as VTEX storefronts.
   Path: backend/app/services/config/platforms.json
   Lines: 848-848

6. logic error: The template-extraction regex is too restrictive and can skip valid embedded state blocks.
   Path: backend/app/services/script_text_extractor.py
   Lines: 42-42

7. logic error: Clearing `completed_at` whenever the run leaves a terminal state will erase the historical completion timestamp if a finalized run is reopened or corrected later.
   Path: backend/app/models/crawl_run.py
   Lines: 98-98

8. possible bug: The new Python-side `default` duplicates the existing `server_default` for `enrichment_status`, but unlike the server default it is only applied by SQLAlchemy when the ORM omits the field.
   Path: backend/app/models/crawl_run.py
   Lines: 168-168

9. logic error: Changing `user_id` to nullable with `ON DELETE SET NULL` breaks job ownership expectations.
   Path: backend/app/models/product_intelligence.py
   Lines: 33-33

10. race condition: Cancellation from the browser prewarm task can now leak out of cleanup.
   Path: backend/app/services/_batch_runtime.py
   Lines: 406-406

11. logic error: Browser attempt diagnostics can be misreported after coercion.
   Path: backend/app/services/_batch_runtime.py
   Lines: 102-102

12. logic error: Unrelated timeouts can be misclassified as host blocks and trigger incorrect engine rotation.
   Path: backend/app/services/fetch/fetch_context.py
   Lines: 690-690

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.