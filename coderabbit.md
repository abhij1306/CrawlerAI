Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/fetch/planned_http.py at line 305, The except clause at the end of the HTTP error handling block in the planned_http.py file is catching RuntimeError along with httpx.HTTPError and OSError, which is too broad and may mask legitimate programming errors. Remove RuntimeError from the exception tuple in the except statement, keeping only httpx.HTTPError and OSError. If the code documentation indicates that specific RuntimeError subclasses are raised for recoverable network conditions, handle those separately with a distinct except clause rather than grouping them with transient network errors.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/fetch/planned_http.py around lines 424 - 425, The early return of None when _run_handoff_curl fails skips remaining cookie engines, which is inconsistent with how missing cookies are handled at line 415 using continue. Replace the return None statement with continue to try remaining engines when _run_handoff_curl fails, maintaining consistency with the missing cookies handling pattern. Alternatively, if the fail-fast behavior is intentional and network errors should halt processing, add a comment explaining this design choice.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/connectors/public_api/extraction_service.py around lines 82 - 90, The async function `_create_public_run` lacks an explicit return type annotation while the similar helper function `_load_public_record_or_fail` includes one (`-> CrawlRecord`). Add a return type annotation to the `_create_public_run` function signature to maintain consistency with other helper functions and improve type safety. The return type should likely be `CrawlRun` or an appropriate type based on what this function returns.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/connectors/public_api/extraction_service.py around lines 111 - 118, The `_run_public_extraction` function lacks a return type annotation while the similar helper function `_load_public_record_or_fail` includes one (`-> CrawlRecord`). Add an explicit return type annotation to the `_run_public_extraction` function signature after the closing parenthesis of the parameters to match the pattern used in `_load_public_record_or_fail` and improve type consistency across the decomposed helper functions. Determine the appropriate return type based on what the function actually returns.

Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/browser_settle.py around lines 21 - 56, The probe method in the _ReadinessSnapshotCache class uses an assert statement to check if analysis is not None, which can be stripped in optimized Python builds (-O flag), compromising production safety. Replace this assert statement with an explicit guard clause that raises a RuntimeError, matching the pattern already used later in the same method where self.analysis is checked for None and raises RuntimeError with a descriptive message for browser readiness analysis failure.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/traversal_steps.py around lines 286 - 296, The `page.goto` call and the subsequent `wait_for_transition` call lack try/except error handling for navigation failures like TimeoutError, unlike other pagination mechanisms that use `click_with_retry`. Wrap both the `page.goto` call and the `wait_for_transition` call in a try/except block to catch any Playwright-related exceptions (including TimeoutError), and return a failure step status on error instead of letting the exception propagate up and terminate traversal unexpectedly.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/crawl/site_link_discovery.py around lines 347 - 356, The _looks_like_locale_segment function has boolean logic that is correct but lacks explicit parentheses to clearly show operator precedence and improve readability. Add explicit parentheses to group the conditions: wrap the first condition checking len(cleaned) == 2 and cleaned.isalpha() in parentheses, then wrap the second condition checking len(cleaned) == 5 with the remaining checks in parentheses, separating both groups with the or operator for clear precedence.