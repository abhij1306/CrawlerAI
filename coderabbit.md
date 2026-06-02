


- Increased crawler/browser concurrency defaults and added timing instrumentation for browser context acquisition and lifecycle.
- Added origin warmup deduping and bounded challenge recovery activity by deadline.
- Expanded variant extraction heuristics for embedded payloads and JS state normalization.
- Refactored frontend records table to custom sticky header + fixed column widths.

<QODO_CONFIRM>
{
  "identifier": "security-all",
  "text": "0 Security vulnerabilities",
  "ctaText": "Resolve all",
  "doneCtaText": "✓ All resolved",
  "prompt": "Resolve all security suggestions",
  "type": "resolve_all",
  "suggestionIdentifiers": []
}
</QODO_CONFIRM>

<QODO_CONFIRM>
{
  "identifier": "bugs-all",
  "text": "4 Potential bugs",
  "ctaText": "Resolve all",
  "doneCtaText": "✓ All resolved",
  "prompt": "Resolve all bug suggestions",
  "type": "resolve_all",
  "suggestionIdentifiers": [
    "bug_001_storage_state_domain_indent",
    "bug_002_recycle_active_context_threshold",
    "bug_003_origin_warmup_dedupe_memory_growth",
    "bug_004_frontend_table_semantics_a11y"
  ]
}
</QODO_CONFIRM>

<QODO_SUGGESTION>
{
  "identifier": "bug_001_storage_state_domain_indent",
  "description": "**Potential syntax/logic error in `load_storage_state_for_domain` block (indentation/parenthesis mismatch)**\n\n- Description: The `await cookie_store.load_storage_state_for_domain(...)` call appears mis-indented in the PR diff, which would either fail to parse or change control flow so domain storage state is not loaded correctly.\n- PR Git Diff Pointer:\n```diff\n@@\n                 if not storage_state and allow_domain_storage_state:\n                     storage_state = await cookie_store.load_storage_state_for_domain(\n                         domain,\n                         browser_engine=self.browser_engine,\n-                    )\n+                )\n```\n- Evidence: In the current file content, the call must be indented under the `if not storage_state...` block and closed at the same indentation level; otherwise Python will raise `IndentationError`/`SyntaxError` or skip the assignment.\n- How to Fix: Ensure the closing parenthesis aligns with the `storage_state = await ...` line and the call remains inside the `if not storage_state and allow_domain_storage_state:` block.\n",
  "filePath": "c:\\Projects\\pre_poc_ai_crawler\\backend\\app\\services\\acquisition\\browser_pool.py",
  "severity": "high",
  "prompt": "Fix indentation/parenthesis mismatch around load_storage_state_for_domain in SharedBrowserRuntime.page"
}
</QODO_SUGGESTION>

<QODO_SUGGESTION>
{
  "identifier": "bug_002_recycle_active_context_threshold",
  "description": "**Browser recycle guard uses `> 1` active contexts, allowing recycle with 1 active context**\n\n- Description: `_should_recycle_browser()` now returns `False` only when `self._active_contexts > 1`, which still allows recycling while exactly one context is active, risking closing the browser under an in-use context.\n- PR Git Diff Pointer:\n```diff\n@@\n         if not getattr(self._browser, \"is_connected\", lambda: True)():\n             return True\n-        if self._active_contexts > 1:\n+        if self._active_contexts > 1:\n             return False\n```\n- Evidence: `SharedBrowserRuntime.page()` increments `_active_contexts` before calling `_ensure()`, and `_ensure()` may call `_close_locked()` when `_should_recycle_browser()` is true; with `_active_contexts == 1` this guard does not prevent recycle.\n- How to Fix: Change the condition to `if self._active_contexts > 0: return False` (or equivalent) so any active context prevents recycling.\n",
  "filePath": "c:\\Projects\\pre_poc_ai_crawler\\backend\\app\\services\\acquisition\\browser_pool.py",
  "severity": "high",
  "prompt": "Prevent browser recycling when any active context exists by adjusting _should_recycle_browser guard"
}
</QODO_SUGGESTION>

<QODO_SUGGESTION>
{
  "identifier": "bug_003_origin_warmup_dedupe_memory_growth",
  "description": "**Origin warmup dedupe state can grow unbounded when TTL is 0 and many unique hosts are seen**\n\n- Description: When `origin_warmup_dedupe_ttl_seconds` is `0.0`, `_begin_origin_warmup()` clears `_ORIGIN_WARMUP_RECENT` but `_ORIGIN_WARMUP_IN_FLIGHT` can still accumulate if `_finish_origin_warmup()` is not reached (e.g., task cancellation before `finally`), causing memory growth and permanent dedupe blocks.\n- PR Git Diff Pointer:\n```diff\n+_ORIGIN_WARMUP_STATE_LOCK = asyncio.Lock()\n+_ORIGIN_WARMUP_IN_FLIGHT: set[tuple[str, str, str, str]] = set()\n+_ORIGIN_WARMUP_RECENT: dict[tuple[str, str, str, str], float] = {}\n@@\n+async def _begin_origin_warmup(key: tuple[str, str, str, str]) -> bool:\n+    ...\n+    async with _ORIGIN_WARMUP_STATE_LOCK:\n+        ...\n+        if key in _ORIGIN_WARMUP_IN_FLIGHT:\n+            return False\n+        ...\n+        _ORIGIN_WARMUP_IN_FLIGHT.add(key)\n+        return True\n```\n- Evidence: `_maybe_warm_origin_before_navigation()` calls `_begin_origin_warmup()` and relies on `await _finish_origin_warmup(warmup_key)` in `finally`, but cancellations can bypass parts of `finally` if not shielded, leaving keys in `_ORIGIN_WARMUP_IN_FLIGHT` indefinitely.\n- How to Fix: Ensure `_finish_origin_warmup()` runs even under cancellation (e.g., `try/finally` with `asyncio.shield` for the cleanup) and consider bounding `_ORIGIN_WARMUP_IN_FLIGHT` size or adding a monotonic timestamp-based eviction.\n",
  "filePath": "c:\\Projects\\pre_poc_ai_crawler\\backend\\app\\services\\acquisition\\browser_runtime.py",
  "severity": "medium",
  "prompt": "Harden origin warmup dedupe cleanup against cancellation and bound in-flight state growth"
}
</QODO_SUGGESTION>

<QODO_SUGGESTION>
{
  "identifier": "bug_004_frontend_table_semantics_a11y",
  "description": "**Custom header uses `role=row/columnheader` outside a table, risking broken accessibility and layout**\n\n- Description: The header is rendered as a `div` with ARIA roles while the body is a real `<table>`, which can confuse screen readers and may break sticky alignment because header and body are separate layout contexts.\n- PR Git Diff Pointer:\n```diff\n@@\n-      <Table\n+      <div\n         ref={setContainerRef}\n         onScroll={(event) => setScrollTop(event.currentTarget.scrollTop)}\n         className=\"scrollbar-stable relative max-h-[calc(100vh-276px)] w-full overflow-auto\"\n       >\n-        <TableHeader ...>\n+        <div role=\"row\" className=\"... flex ...\" ...>\n+          <div role=\"columnheader\" ...>\n+            <input type=\"checkbox\" ... />\n+          </div>\n+          ...\n+        </div>\n+        <table ...>\n```\n- Evidence: `frontend/components/ui/table.tsx` provides a wrapper that keeps header and body within the same `<table>` element; this PR bypasses it and mixes ARIA table roles with native table markup.\n- How to Fix: Render the header as a proper `<thead><tr><th>...</th></tr></thead>` inside the same `<table>` (or use a fully div-based grid with consistent roles for both header and body).\n",
  "filePath": "c:\\Projects\\pre_poc_ai_crawler\\frontend\\components\\crawl\\records-table.tsx",
  "severity": "medium",
  "prompt": "Fix records table header/body semantics by using a native thead or consistent div-based table roles"
}
</QODO_SUGGESTION>

<QODO_CONFIRM>
{
  "identifier": "quality-all",
  "text": "2 Code quality issues",
  "ctaText": "Resolve all",
  "doneCtaText": "✓ All resolved",
  "prompt": "Resolve all quality suggestions",
  "type": "resolve_all",
  "suggestionIdentifiers": [
    "qual_001_slot_timeout_setting_mismatch",
    "qual_002_concurrency_defaults_risk"
  ]
}
</QODO_CONFIRM>

<QODO_SUGGESTION>
{
  "identifier": "qual_001_slot_timeout_setting_mismatch",
  "description": "**Context-slot wait timeout reuses `acquisition_attempt_timeout_seconds`, coupling unrelated budgets**\n\n- Description: `_browser_context_slot_timeout_seconds()` uses `crawler_runtime_settings.acquisition_attempt_timeout_seconds`, which likely governs overall acquisition attempts, not semaphore slot waits; this can cause premature slot timeouts under load.\n- PR Git Diff Pointer:\n```diff\n+def _browser_context_slot_timeout_seconds() -> float:\n+    return max(\n+        0.1,\n+        float(crawler_runtime_settings.acquisition_attempt_timeout_seconds),\n+    )\n```\n- Evidence: `SharedBrowserRuntime.page()` now wraps `self._semaphore.acquire()` in `asyncio.wait_for(..., timeout=_browser_context_slot_timeout_seconds())`, so this setting directly controls pool contention behavior.\n- How to Fix: Introduce a dedicated runtime setting (e.g., `browser_context_slot_timeout_seconds`) or derive it from `browser_context_timeout_ms` with a clear relationship.\n",
  "filePath": "c:\\Projects\\pre_poc_ai_crawler\\backend\\app\\services\\acquisition\\browser_pool.py",
  "severity": "medium",
  "prompt": "Decouple browser context slot wait timeout from acquisition_attempt_timeout_seconds by adding a dedicated setting"
}
</QODO_SUGGESTION>

<QODO_SUGGESTION>
{
  "identifier": "qual_002_concurrency_defaults_risk",
  "description": "**Large default concurrency increases risk of resource exhaustion without backpressure tuning**\n\n- Description: Defaults were raised significantly (`system_max_concurrent_urls` 8→20, `batch_url_concurrency`/`url_batch_concurrency` 1→20, HTTP connections 50→100), which can overload CPU/memory, browser instances, or upstream sites if not coordinated with rate limiting.\n- PR Git Diff Pointer:\n```diff\n--- a/backend/app/core/config.py\n+++ b/backend/app/core/config.py\n@@\n-    browser_pool_size: int = 2\n+    browser_pool_size: int = 4\n@@\n-    http_max_connections: int = 50\n-    http_max_keepalive_connections: int = 20\n+    http_max_connections: int = 100\n+    http_max_keepalive_connections: int = 40\n@@\n-    system_max_concurrent_urls: int = 8\n+    system_max_concurrent_urls: int = 20\n--- a/backend/app/services/config/runtime_settings.py\n+++ b/backend/app/services/config/runtime_settings.py\n@@\n-    batch_url_concurrency: int = 1\n-    url_batch_concurrency: int = 1\n+    batch_url_concurrency: int = 20\n+    url_batch_concurrency: int = 20\n```\n- Evidence: `SharedBrowserRuntime` uses a semaphore sized by `settings.browser_pool_size`, and HTTP client pools typically allocate per-connection resources; raising all these defaults together multiplies concurrent work.\n- How to Fix: Keep conservative defaults and gate higher concurrency behind environment-specific config, plus add metrics/logging for queue depth, slot timeouts, and HTTP pool saturation.\n",
  "filePath": "c:\\Projects\\pre_poc_ai_crawler\\backend\\app\\core\\config.py",
  "severity": "medium",
  "prompt": "Re-evaluate increased concurrency defaults and add backpressure/observability to prevent resource exhaustion"
}
</QODO_SUGGESTION>

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/browser_runtime.py around lines 771 - 772, The code is marking origins as recently warmed (_ORIGIN_WARMUP_RECENT) even when warmups are skipped or fail; change the flow so the recent-stamp is only written on a confirmed successful warmup. Update _finish_origin_warmup to either return a boolean success flag or add a separate helper (e.g., mark_origin_warmup_recent) and call that only from the successful completion path (the place that currently signifies a real warmup success), and remove any unconditional stamping from exception/early-return paths that call _finish_origin_warmup; adjust all callers (the paths currently invoking _finish_origin_warmup and then writing _ORIGIN_WARMUP_RECENT) to check the success flag or call the explicit marker only on success.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/structured_payloads.py around lines 511 - 516, The one-size predicate assigned to has_one_size only checks payload.get("sizeName") and should also consider payload.get("size_name"); update the expression that defines has_one_size to treat either payload.get("sizeName") or payload.get("size_name") as the size value (and ensure the chosen value is not in (None, "", [], {})), so payloads like {"isOneSize": True, "size_name": "One Size"} pass into variant recovery; reference the has_one_size assignment and the payload.get("isOneSize")/payload.get("sizeName") keys when making the change.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/structured_payloads.py around lines 438 - 445, The block that calls _structured_variants_from_product_payload when _embedded_payload_has_variant_options(...) can emit the same structured variants a second time because Product/ProductGroup paths already add the same variants; to fix this, before calling _structured_variants_from_product_payload or before add_candidate(candidates, "variants", ...), check whether a "variants" candidate has already been added for this payload (e.g., inspect candidates for an existing "variants" entry or compare rows) and skip resolving/adding duplicates; update the code around _embedded_payload_has_variant_options, _structured_variants_from_product_payload, _variant_axes_from_rows, resolve_variants, and add_candidate to prevent emitting the same variants/variant_count twice when in_variant_context is false.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/field_candidates/variant_rows.py around lines 439 - 444, _payload_is_single_size_variant currently only checks camelCase keys (isOneSize and sizeName); update it to also consider snake_case keys used elsewhere. Modify the function to treat payload.get("size_name") the same as payload.get("sizeName") and payload.get("is_one_size") the same as payload.get("isOneSize") when deciding single-size (so both size_name and sizeName, and is_one_size and isOneSize are checked before falling back to the type=="simple" logic). Ensure you reference the existing function name _payload_is_single_size_variant and preserve the final type check using payload.get("type").

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/js_state/helpers.py around lines 194 - 201, The primary availability branch in availability_value is returning raw string values (e.g., "out-of-stock", "unavailable") instead of normalizing them; update the availability_value function to apply the same alias normalization used for boolean-style keys by mapping "out-of-stock", "unavailable" (and the other aliases like "0","false","no") to "out_of_stock" before returning; locate the logic around normalized_available and the primary return path in availability_value and ensure both branches use the same normalization map so downstream "out_of_stock" checks succeed.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/component/test_browser_context.py around lines 1811 - 1876, The shared phase_timings_ms is used by both the holding task and the timed-out task; split them so each page call gets its own timing dict: create phase_timings_ms_first and phase_timings_ms_second, pass phase_timings_ms_first into the first task's runtime.page call (inside _hold_page) and pass phase_timings_ms_second into the timed-out async with runtime.page; then assert phase_timings_ms_first contains context_open_ms and context_close_ms while phase_timings_ms_second contains context_slot_wait_ms and does NOT contain context_open_ms or context_close_ms (or assert browser_start_ms is absent) to clearly verify the timeout-path timings in test_shared_browser_runtime_bounds_context_slot_wait.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/records-table.tsx around lines 166 - 212, The header currently built with a div row ("role='row'") and multiple div columnheaders (in the JSX that uses HEADER_HEIGHT, SELECT_COLUMN_WIDTH, IMAGE_COLUMN_WIDTH, headerCellStyle, hasImageCol, dataColumns, PRICE_KEYS, humanizeFieldName) is disconnected from the table body which uses real table/tbody/tr/td elements; update the header to be part of the same table semantics by rendering it inside a <table> with a <thead> and matching <th> cells (or alternatively add explicit aria-labelledby/aria-colindex attributes that link each header div to its corresponding table column/cells), ensure headerCellStyle and pinnedDataLeft logic still apply to the <th> elements, and keep the select-all checkbox behavior on the first header cell so screen readers can correctly associate header labels with body cells.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/crawl/records-table.tsx around lines 267 - 274, The className contains redundant "sticky z-20" when inline styles from stickyBodyStyle already set position: 'sticky' and zIndex: 20; update the className expression in records-table.tsx (the block using isFirstData, stickyBodyStyle, fixedColumnStyle, PRICE_KEYS, colKey) to remove "sticky z-20" while preserving "bg-background" for isFirstData, leaving the inline stickyBodyStyle to control stickiness and z-index.
