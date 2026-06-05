Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_runtime.py at line 119, The global _ORIGIN_WARMUP_STATE_LOCK is bound to a single event loop and will raise RuntimeError if awaited from other loops; replace the module-scoped asyncio.Lock with a per-event-loop lock factory (e.g., a get_origin_warmup_state_lock() helper that uses asyncio.get_running_loop() and a WeakKeyDictionary or dict keyed by loop to create/return an asyncio.Lock for that loop) and update all call sites that currently await _ORIGIN_WARMUP_STATE_LOCK (the places referenced in the diff) to call the helper so each event loop gets its own Lock instance.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/crawl/utils.py around lines 133 - 136, The CSV-derived URLs are being appended raw to candidates, bypassing normalization and tracking-param stripping; update the code that handles parse_csv_urls results so each URL is passed through normalize_target_url (and/or strip_tracking_params) before extending candidates, only add non-empty normalized results and avoid duplicates (e.g., by checking existence in candidates) to keep CSV targets consistent with other URL sources; refer to parse_csv_urls, normalize_target_url, strip_tracking_params, and the candidates list when making the change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/structured_payloads.py around lines 197 - 207, The current _structured_property_value function returns str(values) for iterable inputs, producing Python list literals with brackets/quotes; change this to return a user-friendly joined string instead (e.g., use a delimiter like "; " to join the cleaned values), keeping the existing behavior of returning None when no cleaned items are present and still calling _clean_structured_markup_text(value) for non-iterables; update the return for list/tuple/set cases in _structured_property_value accordingly.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/structured_payloads.py around lines 66 - 76, _breadcrumb_item_name currently calls _clean_structured_markup_text on item.get("name") or item.get("title") without checking for blank, while earlier it uses is_blank(name) before cleaning; update _breadcrumb_item_name to apply the same is_blank check to the final candidate value (the result of item.get("name") or item.get("title")) and return None if blank, otherwise call _clean_structured_markup_text on that value so the blank-checking behavior is consistent for both paths.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/jobs/page-view.tsx at line 33, Either remove the unnecessary skipcq: JS-0067 suppression or replace it with a one-line explanatory comment immediately above it that states why the check must be suppressed for this component (for example: "Suppress JS-0067 because this page component intentionally mixes data-fetching and render logic for UX cohesion"). Locate the suppression in frontend/app/jobs/page-view.tsx (the page component, e.g., PageView) and update that single-line comment; do not alter other logic.