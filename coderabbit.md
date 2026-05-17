These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Unauthorized websocket clients are accepted before being closed, weakening the endpoint's auth rejection behavior.
   Path: backend/app/api/crawls.py
   Lines: 185-185

2. logic error: The reconciliation fallback can still return an empty page even when the run summary says records should exist.
   Path: backend/app/api/records.py
   Lines: 66-66

3. possible bug: Startup will fail if the renamed service import is not re-exported by the package.
   Path: backend/app/main.py
   Lines: 50-50

4. possible bug: App startup can break if the new LLM client import path is not publicly exposed.
   Path: backend/app/main.py
   Lines: 51-51

5. possible bug: Importing from a non-existent module path will break module loading at runtime.
   Path: backend/app/models/crawl_settings.py
   Lines: 9-9

6. logic error: The new status guard can reject legitimate local dispatches.
   Path: backend/app/services/dispatch/local_dispatcher.py
   Lines: 123-123

7. possible bug: Moving the candidate helper import can break selector fallback behavior if the new module contract does not match the old one.
   Path: backend/app/services/dom/selector_engine.py
   Lines: 63-63

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/export/schema.py around lines 72 - 78, The validator behavior changed to model_post_init; keep the early-exit explicit by preserving the return when record_url is missing and add a short clarifying comment above the early-return in the model_post_init method to indicate this is an intentional short-circuit before URL parsing; ensure validation of the parsed URL still checks parsed.scheme in {"http","https"} and parsed.netloc and raises ValueError("record url must be an absolute http(s) URL") when invalid (referencing model_post_init, record_url, urlparse, parsed.scheme, parsed.netloc).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/listing_extractor.py around lines 1071 - 1075, In _dom_listing_stage the deduplication set skipped_urls is checked but never updated, so duplicate URLs still get appended to records; after computing url = str(record.get("url") or "") and before records.append(record) add logic to insert the accepted url into skipped_urls (e.g., skipped_urls.add(url)) so subsequent iterations will be skipped; ensure you use the same normalized url string used in the check to maintain consistent deduplication.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/access_service.py around lines 28 - 38, The function require_accessible_record currently raises LookupError when the record is missing but calls require_accessible_run which raises ValueError for missing/inaccessible runs, causing inconsistent exception types; pick a single exception (e.g., convert the record-missing branch to raise ValueError with RECORD_NOT_FOUND_DETAIL or introduce a module-level custom exception like AccessDeniedError and replace both require_accessible_record and require_accessible_run to raise that) and update the raise in require_accessible_record (and require_accessible_run if you add a custom type) so callers can uniformly catch one exception type; be sure to update any docstrings/tests that reference the old exceptions.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/batch_runtime.py around lines 44 - 48, The code is calling the private runtime._ensure() which couples this module to internals; change the call site in batch_runtime.py to use a public API (e.g., runtime.ensure() or runtime.prewarm()) and update the browser runtime implementation to expose that public method (add ensure()/prewarm() that wraps the existing _ensure() logic). At the call site (get_browser_runtime and runtime usage), replace runtime._ensure() with runtime.ensure()/runtime.prewarm(), and if you need backward compatibility, check for the public method (hasattr(runtime, "ensure") or "prewarm") and fall back to the private _ensure() only as a temporary bridge while you add the public method to the browser runtime class.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/batch_runtime.py around lines 91 - 93, The current use of "or 1" coerces a returned 0 into 1, incorrectly treating "no traversal" as one page; change the logic to check for None explicitly: call settings_view.max_pages() and settings_view.max_scrolls(), assign them to temporaries, then set max_pages = int(value) if value is not None else 1 and likewise for max_scrolls, and finally compute traversal_pages = max(max_pages, max_scrolls) so that a numeric 0 is preserved but a missing (None) value still defaults.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/crud.py around lines 114 - 115, Add the required blank line(s) before the top-level async function definition "list_runs": ensure there are two blank lines separating the previous top-level function's end (the "return run" line) and the "async def list_runs(...)" declaration so the file conforms to PEP 8 spacing for top-level functions.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/crud.py around lines 103 - 108, Replace the redundant expression in the result_summary construction: change the url_count calculation from max(1, len(urls) or 1) to max(1, len(urls)). Locate the result_summary dict (the url_count key) in the function where result_summary is built and remove the "or 1" so the code becomes max(1, len(urls)), preserving the minimum-of-one behavior.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/events.py around lines 37 - 43, The lazy init of the global _detached_log_write_semaphore in get_detached_log_write_semaphore is not thread-safe; fix by making initialization atomic: either create the semaphore at module import (set _detached_log_write_semaphore = asyncio.Semaphore(_DETACHED_LOG_WRITE_CONCURRENCY) at top-level) or guard the lazy init with a thread-safe lock (use a threading.Lock around the check-and-set in get_detached_log_write_semaphore) to avoid race conditions when called from multiple threads.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/events.py around lines 98 - 102, The _format_message function declares a correlation_id parameter that is never used; remove the unused parameter from the signature (change def _format_message(message: str) -> str) and update all call sites that currently pass a correlation_id (they are passing None) to call _format_message with only the message argument; keep the existing body logic unchanged and run type checks/tests to ensure no remaining references to the removed parameter.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/ingestion_service.py around lines 82 - 99, The function create_crawl_run_from_csv is missing a return type annotation; add an explicit return type that matches the tuple you return (the created crawl run and the URL count) — e.g. annotate with -> tuple[CrawlRun, int] or -> Tuple[models.CrawlRun, int] depending on project typing conventions, and add the necessary typing import (tuple or Tuple) and any model type import so the signature of create_crawl_run_from_csv, which calls create_crawl_run and dispatch_run, accurately reflects its return value.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/ingestion_service.py around lines 74 - 79, The function create_crawl_run_from_payload is missing a return type annotation; update its signature to include the correct return type returned by dispatch_run (likely CrawlRun) and import CrawlRun where types are collected so the async def reads e.g. async def create_crawl_run_from_payload(...) -> CrawlRun. Ensure the import for CrawlRun is added at the top of the module and verify dispatch_run's return type to match the annotation.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/profile/acquisition_contract.py around lines 107 - 115, The list comprehension that builds "missing" repeatedly constructs set(covered_fields) on each iteration, which is wasteful; in the block that builds "field_coverage" (inside acquisition_contract.py) compute covered_set = set(covered_fields) once (e.g., just above where "field_coverage" is assembled) and then use "if field not in covered_set" in the comprehension (also reuse the already-created list(requested_fields or []) by assigning it to a local variable if desired). This change targets the "field_coverage" dict and the variables requested_fields and covered_fields.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/profile/acquisition_contract.py around lines 183 - 187, The inline fallback `int(profile.get("source_run_id") or 0) or 1` is hard to read; pull the logic into a clear variable (e.g., source_run_id) before the call: read profile.get("source_run_id"), if present convert to int, else fall back to existing.source_run_id if available, otherwise use 1, then pass source_run_id into the call (keep existing_record=existing etc.). This replaces the convoluted chained ors with an explicit, readable assignment in acquisition_contract.py.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/profile/merge.py around lines 17 - 18, The helper _default_run_settings currently calls normalize_crawl_settings({}) each time, which can be redundant and costly; change it to compute and cache the normalized default once (e.g., a module-level constant like _CACHED_DEFAULT_RUN_SETTINGS computed by calling normalize_crawl_settings({}) at import time) and have _default_run_settings return that cached dict, or alternately modify callers (e.g., merge logic that iterates sections) to accept and reuse a single normalized settings object passed in rather than calling _default_run_settings repeatedly; reference _default_run_settings and normalize_crawl_settings when making the change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/profile/repository.py around lines 33 - 37, The current string check on ProgrammingError to detect a missing "domain_run_profiles" table is fragile; change the error handling to either catch sqlalchemy.exc.NoSuchTableError instead of ProgrammingError, or (preferably) pre-check table existence with sqlalchemy.inspect(session.bind).has_table("domain_run_profiles") before running the query; if you keep exception handling, replace the string match with catching NoSuchTableError (import from sqlalchemy.exc) and then call session.rollback() and return None in that branch, leaving other exceptions re-raised.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/structured_payloads.py around lines 43 - 56, The _gender_from_text function currently collects canonical gender matches into matches and returns a single canonical only if all matches dedupe to one; otherwise it returns None for ambiguous multi-gender inputs—add an inline comment inside _gender_from_text (near the matches collection and return) stating that the function intentionally returns None when multiple distinct canonical genders are found (e.g., both "men" and "women"), while allowing duplicates of the same canonical (e.g., "mens" and "men's") to resolve to that canonical; reference the DETAIL_GENDER_TERMS mapping, the local matches list, and the final return logic so future maintainers understand this ambiguity-handling behavior.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/structured_values.py around lines 121 - 126, The boolean expression that detects shipping/inventory payloads is hard to read; add a concise clarifying comment immediately above the computation/return that explains the intent (e.g., "reject size candidates coming from shipping/inventory estimation payloads: require both SHIPPING_DATE_FIELD and SPECIAL_DAYS_FIELD and at least one of IS_AVAILABLE_FIELD or IS_INVENTORY_ONLY_FIELD to treat as inventory payload"). Reference the symbols used in the condition (SHIPPING_DATE_FIELD, SPECIAL_DAYS_FIELD, IS_AVAILABLE_FIELD, IS_INVENTORY_ONLY_FIELD, inventory_payload_keys) so future readers understand why the set containment and intersection checks are done and what scenario this guards against.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/variant_rows.py around lines 332 - 336, The code builds variant_url using f"{page_url}?variant={variant_id}" which breaks when page_url already has query params and may bypass absolute_url behavior; update the logic around variant_url (and where coerce_field_value and absolute_url are used) to parse page_url, merge or set the "variant" query parameter using a URL parser/encoder (e.g., urllib.parse.parse_qsl + urlencode) to produce a correct URL, then pass that composed URL to absolute_url only if it is relative (or skip absolute_url when the composed URL is already absolute); ensure you update the branch that assigns row["url"] (the variant_url/variant_id/page_url handling) so it uses the parsed-and-encoded URL instead of string concatenation.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/network_listing_mapper.py around lines 374 - 385, The regex in listing_identity_from_url (the pattern /([A-Z]\d{6}-\d{3})(?:/|$)) is retailer-specific and unclear to future maintainers; add a short doc comment immediately above the listing_identity_from_url function that explains the purpose of the pattern, what it matches (e.g., uppercase-letter + 6 digits + hyphen + 3 digits SKU format), which retailer or feed it comes from, and why the fallback segment extraction is used, and include an example input URL and expected output to make intent and edge-cases explicit.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/network_listing_mapper.py at line 88, Remove the redundant fallback in the loop over network_payloads: replace the use of list(network_payloads or []) with list(network_payloads) (or simply iterate directly over network_payloads) in the loop that references the network_payloads variable so the unnecessary "or []" is eliminated; ensure this change is applied where the for payload in ... loop appears (and relies on the earlier early return that guarantees network_payloads is truthy).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/structured_listing_handler.py around lines 221 - 224, Cache the repeated dict lookup into a local variable before testing: retrieve payload.get("itemListElement") into a name like item_list and then use isinstance(item_list, list) and item_list to avoid calling payload.get twice; apply the same change to the other occurrence referenced around the block handling itemListElement (the second check at lines 233-236) so both checks use the cached variable instead of duplicate payload.get calls.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/structured_listing_handler.py at line 173, The function _typed_listing_payloads is a generator but lacks a return type annotation; update its signature to include the generator return type (e.g., -> Iterator[dict[str, Any]]) and add "Iterator" to the typing imports (alongside Any) so the annotation resolves.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/budget.py around lines 9 - 36, The code uses str(int(run_id)) in reserve_run_llm_call/_reserve which will raise if run_id is a non-integer type; add explicit validation/conversion up-front: if run_id is not None attempt to convert it to an int in a try/except (catch ValueError/TypeError), assign the result to a local run_id_int, and if conversion fails return True (fail-open) or otherwise proceed; then replace str(int(run_id)) with str(run_id_int) inside _reserve to avoid repeated coercion and exceptions.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/circuit_breaker.py around lines 128 - 142, The _resolved_failure_threshold() function should stop using Pydantic model introspection and simply read the configured value directly from llm_runtime_settings.circuit_failure_threshold (or via getattr(llm_runtime_settings, "circuit_failure_threshold", <DEFAULT>)), fall back to a sensible default constant (use the same numeric default currently expected), then coerce to int, return max(1, int(value)) and return None on TypeError/ValueError; update the implementation in _resolved_failure_threshold to use this direct access and fallback logic instead of type(llm_runtime_settings).model_fields.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/config_service.py around lines 119 - 139, The hard-coded task_type list in snapshot_active_configs should be derived from the payload adapter registry to avoid drift; import the exported SUPPORTED_TASK_TYPES (which should be created from _PAYLOAD_ADAPTERS.keys() in payloads.py) and use that as the default when task_types is None, while keeping the existing calls to resolve_active_config and serialize_config_snapshot intact; update snapshot_active_configs to accept an optional task_types param but fallback to SUPPORTED_TASK_TYPES from payloads.py.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/cost_logging.py around lines 58 - 60, The current except block rolls back the entire SQLAlchemy session (session.rollback()) when persisting LLMCostLog fails, which will discard any other caller-staged changes; to fix, isolate the cost-log write by using a savepoint (begin a nested transaction around creating and adding the LLMCostLog and commit/rollback only that nested transaction), or alternatively perform the cost-log write on a separate short-lived session, and/or re-raise the SQLAlchemyError after logging so callers can act on the failure; update the code that handles LLMCostLog persistence (the block that catches SQLAlchemyError and calls session.rollback()) to implement one of these isolation strategies and ensure only the cost-log operation is rolled back, not the caller's broader session work.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/errors.py around lines 50 - 56, The checks using ERROR_PREFIX currently use raw.startswith(ERROR_PREFIX) which is case-sensitive and will miss variants like "error:"; update the logic in the block that examines raw (the variable named raw) to perform case-insensitive prefix matching (e.g., compare raw.lower().startswith(ERROR_PREFIX.lower())) for both the CLIENT_ERROR branch that also checks _DETERMINISTIC_CLIENT_ERROR_CODES and the subsequent PROVIDER_ERROR branch so that ERROR_PREFIX is matched regardless of case while preserving the existing code-paths that return LLMErrorCategory.CLIENT_ERROR and LLMErrorCategory.PROVIDER_ERROR.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/prompt_rendering.py around lines 87 - 100, The list-branch in safe_truncate_for_prompt currently appends a string summary to a possibly heterogeneous list (truncated), producing a mixed-type list; change this to return structured metadata instead: build truncated = [safe_truncate_for_prompt(item, max_str_len=max_str_len, max_list_items=max_list_items) for item in value[:max_list_items]] and if len(value) > max_list_items return {"items": truncated, "_truncated": len(value) - max_list_items} else return truncated; update any callers of safe_truncate_for_prompt to handle the new dict shape (check for a dict with "items" key) so prompt rendering/serialization remains predictable.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/llm/provider_client.py around lines 40 - 43, The nested acquisition of _groq_client_lock, _anthropic_client_lock, _nvidia_client_lock, and _aws_client_lock should be replaced with independent acquisitions to avoid lock-order deadlocks; iterate over each lock and its related globals (e.g., _groq_client_lock with _groq_client and _groq_client_timeout, similarly for _anthropic_client/_anthropic_client_timeout, _nvidia_client/_nvidia_client_timeout, _aws_client/_aws_client_timeout), and inside each async with lock: check the corresponding client global (globals()["<client_ref>"]) for not None and not is_closed, then close and reset the client and its timeout independently before releasing the lock. Ensure you reference the existing symbols (_groq_client_lock, _anthropic_client_lock, _nvidia_client_lock, _aws_client_lock and _groq_client, _anthropic_client, _nvidia_client, _aws_client and their *_timeout counterparts) so the change is localized and avoids changing lock ordering semantics.