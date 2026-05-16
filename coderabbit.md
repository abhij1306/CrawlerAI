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

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.