These are comments left during a code review. Please review all issues and provide fixes.

1. Code Quality: The error path may fall through instead of aborting, which can lead to using uninitialized state after an exception.
   Path: backend/app/api/data_enrichment.py
   Lines: 45-45

2. Code Quality: The bad-request exception handler may continue execution instead of stopping, leading to downstream runtime errors.
   Path: backend/app/api/data_enrichment.py
   Lines: 51-51

3. Code Quality: Exception handling now depends on a helper side effect, and if it does not raise, control flow continues into invalid state.
   Path: backend/app/api/playground.py
   Lines: 100-100

4. Code Quality: Exception handling may no longer abort execution, which can lead to using uninitialized values after an error path.
   Path: backend/app/api/product_intelligence.py
   Lines: 56-56

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/dashboard_service.py around lines 403 - 416, The _reset_postgres_identities function currently injects sequence_name into an ALTER SEQUENCE via an f-string (session.execute(text(f"ALTER SEQUENCE {sequence_name} RESTART WITH 1"))), which is fragile; replace that step with a server-side call that avoids interpolating identifiers by name — e.g. call setval(pg_get_serial_sequence(:table_name, 'id'), 1, false) using a bound parameter for table_name (session.execute(text("SELECT setval(pg_get_serial_sequence(:table_name, 'id'), 1, false)"), {"table_name": table_name})), so you never construct SQL identifiers in Python and remove the f-string usage of sequence_name.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/text/sanitizer.py around lines 769 - 779, The check in _materials_extract_trailing_composition currently returns "" when no composition is found anywhere, which callers treat as a valid replacement; add a short inline comment above the branch that returns "" clarifying that an empty string intentionally signals "discard this editorial block entirely" (distinct from returning None which means "leave original text because composition exists in head"), so future readers understand the semantic difference between returning "" and None in _materials_extract_trailing_composition and why callers check `is not None`.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/variants/dom_extraction.py at line 538, The current cache_key uses hash(str(soup)) which can be very expensive for large DOMs; update the cache key construction in the block that sets cache_key = (str(page_url or ""), id(js_state_objects), hash(str(soup))) to use a cheaper signature: either id(soup) if the BeautifulSoup instance is immutable in this pipeline, or a compact fingerprint such as hashing soup.title + a hash of the concatenated string of the first N significant elements (e.g., first 20 tags/text nodes) instead of the whole string; additionally add a TODO or small profiler hook to measure cost before/after the change so we can confirm it’s not a bottleneck.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/extract/detail/variants/pruning.py at line 328, Add a short clarifying comment explaining that the conditional checking token == "mens" (in pruning.py where the irregular plural is handled) intentionally matches the irregular plural "mens" to map it to "men" (keep the existing "# nosec B105" since this isn't a secret), so future readers understand the special-case and why the security suppression is present.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/monitor_webhook_service.py at line 111, The except tuple currently catches both httpx.RequestError and httpx.TimeoutException redundantly; remove httpx.TimeoutException and keep only httpx.RequestError in the except clause to rely on httpx's exception hierarchy (i.e., change "except (httpx.RequestError, httpx.TimeoutException) as exc:" to "except httpx.RequestError as exc:" in the webhook dispatch/HTTP call block in monitor_webhook_service.py).

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/product_intelligence/discovery.py around lines 921 - 929, The _normalize_slug_token function naively strips plural-like suffixes and thus mangles words like "series" and "business"; update it to skip stemming for known exceptions by adding a small whitelist of invariant nouns (e.g., "series", "business", "news", "analysis", "species") and check the original token against that set before applying the existing -ies/-es/-s rules, or alternatively replace the naive logic with a call to a stable stemming/pluralization helper (e.g., an inflection/pluralization library) and fall back to the current rules only when the helper indicates a valid singular form; reference _normalize_slug_token for changes and ensure casefolding is preserved.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/product_intelligence/discovery.py around lines 1276 - 1280, The _quoted helper currently escapes internal double quotes with backslashes which some search providers (e.g., Google) will treat literally; change _quoted to sanitize internal quotes instead of escaping them—locate the _quoted function and replace the replace('\"','\\\"') step with logic that removes or replaces internal double-quote characters (e.g., drop or replace with a space) before wrapping the value in quotes, preserving the empty-string behavior when input is blank.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/monitors/monitor-snapshot-table.tsx around lines 105 - 112, The anchor rendering the external link (href={record.source_url}) using monitorHostPath currently sets rel="noreferrer"; update the <a> element in monitor-snapshot-table.tsx so the rel attribute includes "noopener" as well (e.g., rel="noreferrer noopener") to explicitly prevent window.opener access; ensure this change is applied on the anchor that uses monitorHostPath(record.source_url) and preserves target="_blank" and existing classes.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/api/run_access.py around lines 17 - 18, The function raise_http_from_value_error is a redundant wrapper around raise_http_from_exception; remove raise_http_from_value_error and update callers (notably get_accessible_run_or_404) to call raise_http_from_exception(status_code=..., exc=...) directly so behavior is unchanged; ensure no other references to raise_http_from_value_error remain (or add a small alias back only if used widely), and run tests/typechecks to confirm no import/name errors.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/services/acquisition/playwright_compat.py at line 16, Remove the overly broad RuntimeError from the PLAYWRIGHT_RECOVERABLE_ERRORS tuple so only Playwright-specific exceptions are treated as recoverable; update the tuple to include only PlaywrightError and PlaywrightTimeoutError (remove RuntimeError) in the declaration of PLAYWRIGHT_RECOVERABLE_ERRORS to ensure generic runtime errors propagate normally.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/monitors/monitor-detail-tabs.tsx at line 50, The onChange handler currently uses a type assertion (value as MonitorDetailTab) which circumvents type safety; replace the assertion with a runtime type check: implement a type guard function like isMonitorDetailTab(value: unknown): value is MonitorDetailTab (checking against the MonitorDetailTab union/enum values), then change the handler to onChange={(value) => { if (isMonitorDetailTab(value)) setTab(value); else /* handle unexpected value e.g. log or set default */ }} so setTab is only called with validated MonitorDetailTab values and no cast is needed.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/monitors/monitor-form-state.ts around lines 1 - 4, The SubmitState type is currently internal; export it so external modules can import and annotate state using this helper by adding the export modifier to the type definition (i.e., make the declaration "export type SubmitState = { error: string; submitting: boolean; }") and update any consuming modules to import SubmitState from monitor-form-state.ts as needed.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/monitors/monitor-format.ts around lines 1 - 5, The formatMonitorValue function can throw or produce odd results when JSON.stringify encounters circular references or when value contains functions/symbols; update formatMonitorValue to guard the object branch by attempting serialization inside a try/catch, and on failure return a safe fallback (e.g., a descriptive placeholder like '[circular]' or use a non-throwing serializer/inspect) and explicitly handle functions and symbols by returning their String(value) or a clear label; ensure the function never throws and always returns a concise string for values passed to formatMonitorValue.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/ui/confirm-dialog.tsx around lines 40 - 61, The dialog currently has no Escape key handling; add a keydown listener (mounted in the component where dialogRef is defined) that listens for the Escape key and calls the component's close handler (e.g., the onClose prop or existing close function) to close the dialog, ensure the dialogRef is focused when mounted so Escape works, and remove the listener on unmount/cleanup; reference dialogRef and the component's close/onClose handler when implementing this change.