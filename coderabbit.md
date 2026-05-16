These are comments left during a code review. Please review all issues and provide fixes.

1. possible bug: Counting ecommerce cards from unflattened HTML can miss shadow-DOM products and block readiness detection.
   Path: backend/app/services/acquisition/browser_readiness.py
   Lines: 248-248

2. logic error: Cookie-consent traffic is now incorrectly filtered out as noise.
   Path: backend/app/services/config/network_capture.py
   Lines: 11-11

3. logic error: New Relic requests are now filtered out as noise and may hide relevant network activity.
   Path: backend/app/services/config/network_capture.py
   Lines: 15-15

4. possible bug: Empty network candidates can be added as valid rows and break downstream listing processing.
   Path: backend/app/services/extraction_runtime.py
   Lines: 391-391

5. logic error: Single-source fallback now skips candidate ranking and can return the wrong listing set by order alone.
   Path: backend/app/services/extraction_runtime.py
   Lines: 199-199

6. possible bug: Successful browser retries no longer emit the standard extraction outcome log.
   Path: backend/app/services/pipeline/extraction_loop.py
   Lines: 757-757

7. logic error: Ecommerce listing readiness incorrectly rejects category-card pages that should count as valid listing content.
   Path: backend/tests/services/test_browser_expansion_runtime.py
   Lines: 1369-1369

8. possible bug: The added noise-domain tests can pass without the production filter excluding those payloads.
   Path: backend/tests/services/test_crawl_fetch_runtime.py
   Lines: 214-214

9. possible bug: The new listing retry test can miss a regression where browser traversal still gets enabled.
   Path: backend/tests/services/test_pipeline_core.py
   Lines: 1547-1547

10. logic error: Converting dicts to a frozenset of values can silently drop mapping semantics.
   Path: backend/app/services/extract/listing_integrity_gate.py
   Lines: 257-257

11. logic error: Flattening the theme tokens breaks the previous light/dark contract and can make token lookups fail.
   Path: docs/design.md
   Lines: 15-15

These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Audience normalization can become empty when the expected Shopify attribute is missing.
   Path: backend/app/services/data_enrichment/shopify_catalog.py
   Lines: 282-282

2. possible bug: LLM enrichment can break at runtime if the production call site still uses the old prompt-task signature.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 702-702

3. possible bug: The new test expectations indicate already-enriched records are now accepted, so the old rejection behavior may be removed without updating all validation paths.
   Path: backend/tests/services/test_data_enrichment.py
   Lines: 76-76

4. possible bug: Timeout handling only covers one exception path, which can miss real provider timeouts.
   Path: backend/tests/services/test_llm_runtime.py
   Lines: 330-330

5. logic error: Transparent surfaces now expose the global background grid across the app.
   Path: frontend/app/globals.css
   Lines: 134-134

6. logic error: Terminal containers and terminal JSON now use mismatched backgrounds, breaking readability.
   Path: frontend/app/globals.css
   Lines: 155-155

7. possible bug: Forcing all shared radius tokens to zero breaks component clipping and containment assumptions.
   Path: frontend/app/globals.css
   Lines: 241-241

8. logic error: The mono font variable now points to a different font family than the app expects.
   Path: frontend/app/layout.tsx
   Lines: 18-18

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.
Fix the following issues. The issues can be from different files or can overlap on same lines in one file.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @backend/tests/services/test_llm_runtime.py around lines 363 - 413, Update test_run_prompt_task_returns_timeout_when_provider_exceeds_call_timeout to also assert a cost log was created with outcome="error" and error_category == llm_runtime.LLMErrorCategory.TIMEOUT: after calling llm_runtime.run_prompt_task(query the DB via the provided db_session for the CostLog model or use any helper like get_cost_logs_for_run to locate logs for the invocation and assert one exists with outcome="error" and error_category "TIMEOUT"); also increase timeout_seconds from 0.01 to 0.1 for CI stability. Ensure references to llm_runtime, LLMErrorCategory.TIMEOUT, db_session and CostLog (or the project’s cost-log helper) are used so the test finds the created cost log.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/globals.css around lines 1423 - 1442, There are duplicate JSON syntax highlighting rules: the selectors .syntax-key, .syntax-string, .syntax-number, .syntax-boolean, .syntax-null, and .syntax-punct appear twice; remove the second duplicate block and instead add font-style: italic to the first .syntax-null rule (update the initial .syntax-null declaration to include italic) so the styles are consolidated and the redundant block is deleted.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/app/layout.tsx around lines 18 - 27, The monoFont declaration uses localFont with four Adwaita Mono files referenced in monoFont.src and a misleading CSS variable name '--font-jetbrains-mono'; verify that the files referenced by monoFont.src actually exist in the repository and either rename the CSS variable to something accurate (e.g., '--font-adwaita-mono') or add a clear inline comment next to the monoFont/variable usage explaining why the JetBrains name is kept for compatibility with globals.css, and update any usages of the CSS variable (e.g., in globals.css or layout consumption) to match the chosen name.

- Verify each finding against current code. Fix only still-valid issues, skip the rest with a brief reason, keep changes minimal, and validate.

In @frontend/components/ui/primitives.tsx around lines 326 - 334, The toggle knob translation is asymmetric: in frontend/components/ui/primitives.tsx the span controlling knob position uses checked ? 'translate-x-[18px]' : 'translate-x-[2px]'; update the checked translation to 'translate-x-[19px]' so the Knob (15×15) sits with 2px gaps on both sides (unchecked translate-x-[2px], checked translate-x-[19px]) to produce symmetric spacing; locate the span within the Toggle/primitive component and replace the literal translation token accordingly.