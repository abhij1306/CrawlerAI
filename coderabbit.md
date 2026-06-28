Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/fetch/browser_attempt_runner.py around lines 197 - 200, The deadline budget math in BrowserAttemptRunner is mixing monotonic clocks by using time.perf_counter() in the remaining time checks while the rest of the file uses asyncio.get_running_loop().time(). Update the logic in the affected deadline calculations (including the remaining_before_spec path and the later budget checks) to use the same loop-time source consistently, likely by threading the loop clock through the relevant methods and comparing only against that same clock.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/fetch/browser_attempt_runner.py around lines 158 - 159, The retry budget exhaustion check in BrowserAttemptRunner only breaks the current engine loop, so run() can still move on to the next proxy and _run_proxy_attempt() may launch another browser attempt after exhaustion is already known. Update run() to stop the outer proxy loop as soon as retry_budget_exhausted is set, and add a guard at the start of _run_proxy_attempt() (or the proxy iteration in run()) so no further attempts are scheduled once the retry budget is exhausted.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/acquisition/source_capabilities.py around lines 22 - 27, AcquisitionResultLike is missing the browser_outcome field that attach_source_capability_diagnostics now reads, so the protocol contract must be expanded to require it. Update the AcquisitionResultLike Protocol to include browser_outcome with the same shape used by the diagnostic code, and make sure any downstream callers or test doubles that implement this protocol are updated accordingly so terminal-shell classification is always available.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/config/extraction_rules/_detail.py around lines 132 - 134, The DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN regex is too broad in its percent branch and is incorrectly flagging valid lowercase ingredient descriptions like vitamin c15% complex. Tighten the pattern in _detail.py so the % case only matches a stronger missing-separator signal, such as a percentage immediately running into the next token, while preserving the oz branch behavior. Keep the change localized to DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN and verify the downstream description-evidence logic no longer discards legitimate lowercase shorthand.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/records/url_identity.py at line 73, The shared parent path codes are being added too broadly in URL identity matching, which can cause a shared collection/style segment to short-circuit before a terminal product-code redirect is recognized. Update the logic in `url_identity.py` around `_path_identity_codes(...)`, `parent_codes`, `candidate_codes`, and the `False` return checks near the comparison branch so that shared ancestor codes do not block a real change in the last product-like path token. Prioritize the terminal path code comparison first, and only treat shared codes as a match when they are not masking a distinct final product code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/app/core/shared/field_coerce_text.py around lines 230 - 245, The brand-segment check in field_coerce_text.py only compares first_token against the path, so a truncated leading segment can still be returned. Update the logic around leading_segment, first_token, and matching_path_part to validate the full slug_tokens(leading_segment) prefix against the relevant path segment before returning leading_segment. Keep the existing stop-token handling, but ensure the return only happens when the entire leading brand segment matches the path structure, not just its first slug token.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/harness/artifact_quality_cases.py around lines 561 - 579, The fallback status logic in the attempt-scanning loop is order-dependent, so a selected attempt with a non-integer status can prevent later usable httpx/curl statuses from being considered. Update the status resolution in the relevant artifact quality helper (the loop using selected_attempt_id, attempt_status, and fallback_status) so it first scans all attempts or otherwise tracks the best fallback independently of encounter order, then only returns the selected attempt’s status when appropriate and preserves any valid transport-based fallback.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/harness/artifact_quality_cases.py around lines 181 - 188, The acquisition merge in artifact_quality_cases.py is only shallow, so nested diagnostic data can be overwritten and later helpers like _acquisition_status_code() and _browser_outcome() lose fields they depend on. Update the acquisition construction to deep-merge the nested dicts from summary_acquisition and debug_acquisition, preserving existing subkeys such as acquisition_diagnostics and browser_diagnostics instead of replacing whole nested objects; keep the fix localized around the acquisition assembly logic.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/pyproject.toml around lines 91 - 125, The full-app Pylint baseline is disabling high-signal correctness checks that should remain enabled. Update the pylint ignore list in pyproject.toml to remove the entries for used-before-assignment, not-callable, and unsubscriptable-object while keeping the other legacy-style suppressions unchanged, so the baseline still catches runtime bug patterns in new code.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_source_capabilities.py around lines 114 - 126, Expand the coverage in test_blocked_browser_outcomes_remain_terminal_shells so it also exercises the blocked=True path in build_source_capability_diagnostics, not just the browser_outcome parameterized cases. Strengthen the assertions around affected_field_families to verify the full detail-family contract from DETAIL_FIELD_FAMILIES via _materialize_detail, rather than only checking for "title", so regressions in blocked handling or incomplete family tuples are caught.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_url_identity_assets.py around lines 69 - 76, Add the missing @pytest.mark.unit decorator to the new no-matching-peer test so it is included in marker-selected unit runs; update the test function test_color_params_do_not_reject_all_assets_without_a_matching_peer in the same test module to match the other unit tests’ marker usage.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @docs/INVARIANTS.md around lines 86 - 87, Clarify the public `variant_id` contract in the invariants text by making its placement explicit in the `variants` row schema described alongside `PUBLIC_VARIANT_AXIS_FIELDS` and `variant_count`; currently the allowlist omits `variant_id` while the prose references it as part of the exported contract. Update the wording to state whether `variant_id` is permitted as a row-level field, a top-level field, or intentionally excluded, and keep the rest of the public boundary rules in `INVARIANTS.md` consistent with that choice.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/unit/test_latest_commerce_artifact_integrity.py around lines 120 - 165, The integrity tests are still validating against the fallback artifact cases instead of the committed manifest, so regressions in the replay fixture can slip through. Update the `artifact_cases`-backed assertions in `test_latest_commerce_artifacts_are_integrity_clean` and `test_brooklinen_case_has_no_duplicate_or_feed_variants` to exercise the committed `FIXTURE` manifest (the same source used by `load_artifact_quality_cases` in `test_latest_commerce_artifact_manifest_is_valid_and_offline`) rather than `_fallback_artifact_cases()`, keeping the existing `audit_artifact_quality_cases` and `validate_artifact_quality_cases` checks intact.

These are comments left during a code review. Please review all issues and provide fixes.

1. incorrect condition logic: A successful browser page can be misclassified as not ready when readiness probes are absent, causing false blocked outcomes.
   Path: backend/app/acquisition/fetch/planned_http.py
   Lines: 642-642

2. incorrect condition logic: Optional probe data is treated as mandatory evidence, which can incorrectly classify usable pages as challenge pages.
   Path: backend/app/acquisition/browser_readiness.py
   Lines: 624-624

3. logic error: Blocked-state classification regresses by no longer reliably treating low-content challenge shells as blocked.
   Path: backend/app/extraction/replay.py
   Lines: 227-227

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.

Code Review — working-tree diff (latest commerce artifact integrity)
I ran 8 finder angles + direct verification of the top candidates. The conventions angle found no governing CLAUDE.md. Findings ranked most-severe first; correctness before cleanup.

Correctness
1. terminal_shell shell-detection is dead in production — only works in the replay harness — source_capabilities.py:117
attach_source_capability_diagnostics reads getattr(result, "browser_outcome", None), but the production PageAcquisitionResult dataclass (acquirer.py:75-93) has no browser_outcome attribute — that value lives in browser_diagnostics["browser_outcome"] (this diff even deleted the fallback that read it in replay.py). So in prod shell_outcome is always "", and terminal_shell can only fire via blocked or status>=400. A non-blocked low_content_shell is classified as a normal observation: _materialize_detail does not suppress it and detail fields are marked not_present_in_captured_sources instead of source_unavailable. The new INVARIANTS.md rule and the engine terminal_shell guard pass in tests/harness (which pass browser_outcome explicitly) but are silently non-functional live. Fix: read browser_diagnostics.get("browser_outcome") in the attach helper (ideally via PageEvidence).

2. detail_urls_conflict early-True drops legitimate same-product redirects on the success path — engine.py:408 / url_identity.py:163
_materialize_detail now returns () whenever detail_urls_conflict(requested_url, canonical_url) is true. The new early-True fires when both URLs contain an 8–48 char mixed alpha+digit path code that don't substring-match. A real same-product canonical/migration redirect that rewrites the code (e.g. /products/old-AB12345678 → /products/new-CD87654321) is treated as a cross-product conflict and the entire successfully-fetched record is suppressed. Previously such cases fell through to the semantic-token overlap ratio.

3. Same early-True can discard legitimate same-product variants — js_state.py:333, js_state.py:352
_variant_url_conflicts / _product_url_conflicts call the same detail_urls_conflict. For retailers where color/size variants of one product carry distinct per-variant URL codes, those variants now hit the early-True and are dropped, shrinking valid variant sets. (Intended for sibling-product leakage; over-broad for true variants.)

4. _acquisition_status_code is order-dependent — can miss the real HTTP status — artifact_quality_cases.py:555
If selected_attempt_id points at an attempt whose status_code is null and the curl/httpx fallback attempt appears after it in the list, the loop returns None at the selected attempt before fallback_status was ever set (fallback is only collected from attempts scanned before the selected one). The 404 is missed → terminal_shell/http_error stay False → the regression gate fails to flag the error body. Fix: scan all attempts to collect the fallback before returning the selected one's status.

5. DETAIL_DESCRIPTION_MISSING_SEPARATOR_PATTERN rejects lowercase-glued percentages inconsistently — _detail.py:132
(?<=[a-z])\d{1,3}% flags niacinamide10% (lowercase e before digits) and the resolver drops the description, yet the diff's own "good" test uses C15%/A2% (uppercase prefix → no match). A compact-but-valid ingredient description like "...niacinamide10% complex..." is wrongly rejected while the uppercase equivalent passes — an arbitrary case split.

6. _url_color_ids regex consumes its trailing separator — url_identity.py:175 (in _url_color_ids)
The (?:^|/)colors?/(?P<id>\d{2,})(?:[_./?#]|$) match consumes the trailing /, so a path like /colors/123/colors/456/img.jpg yields only 123 — the second colors/456 has no preceding / left for the ^|/ anchor. A wrong-color asset can slip through _color_product_asset_conflicts. Low frequency, but a silent false-negative. Fix: use a lookahead (?=[_./?#]|$) instead of consuming the separator.

Cleanup
7. _forbidden_variant_materials and _forbidden_variant_ids are identical except the dict key — artifact_quality_cases.py:378-395
Copy-paste differing only by "material" vs "variant_id". Collapse into _forbidden_variant_field(variants, field, forbidden).

8. _browser_outcome / _acquisition_blocked re-hand-roll logic PageEvidence already owns — artifact_quality_cases.py:539
The two-level browser_outcome fallback and block classification are duplicated here (a third divergent copy — and the harness casefolds while PageEvidence lowers). Use PageEvidence.from_browser_diagnostics(...).browser_outcome / .indicates_block. This is the same logic the diff deleted from replay.py, so the gate now diverges from production semantics — directly relevant to finding #1.

9. _color_product_asset_conflicts is the third copy of an asset-conflict helper in the same file — url_identity.py:303
Structurally identical to _semantic_product_asset_conflicts and _short_numeric_product_asset_conflicts (extract product family → extract per-asset family → require an anchoring peer → reject only disjoint). Factor into one _asset_conflicts_by_family(product_values, asset_urls, extractor) taking the id-extractor as a parameter, so the "require a matching peer before rejecting" rule lives in one place.

Highest priority: #1 — the headline feature of this slice (terminal-shell suppression / source_unavailable marking) does not actually run in production, only in the test harness, so the new regression gate cannot catch its own gap. #2/#3 are the inverse risk: the new conflict guard is aggressive enough to drop valid records. I'd resolve those two before merge.

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Using a different monotonic clock for remaining-time calculation can falsely exhaust retry budget.
   Path: backend/app/acquisition/fetch/browser_attempt_runner.py
   Lines: 194-194

2. logic error: Inconsistent clock source in budget checks can cause incorrect retry loop termination.
   Path: backend/app/acquisition/fetch/browser_attempt_runner.py
   Lines: 439-439

3. incorrect condition logic: URLs with any code-like path tokens are now treated as conflicting too aggressively, causing false cross-product conflicts.
   Path: backend/app/core/records/url_identity.py
   Lines: 161-161

4. logic error: Brand inference can return an entire title segment rather than a brand-only value.
   Path: backend/app/core/shared/field_coerce_text.py
   Lines: 257-257

5. logic error: Srcset parsing fails for comma-separated candidates without spaces, leading to malformed URL extraction.
   Path: backend/app/extraction/collectors/dom.py
   Lines: 245-245

6. incorrect condition logic: The invariant logic currently flags the expected sparse-record condition as a failure.
   Path: backend/harness/artifact_quality_cases.py
   Lines: 365-365

7. logic error: Early return in selected-attempt handling can drop valid fallback status codes and misclassify acquisition outcomes.
   Path: backend/harness/artifact_quality_cases.py
   Lines: 430-430

8. code quality: Set-to-tuple conversion introduces nondeterministic ordering that can make invariant results flaky.
   Path: backend/harness/artifact_quality_cases.py
   Lines: 450-450

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.