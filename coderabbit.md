These are comments left during a code review. Please review all issues and provide fixes.

1. Code Quality: Recycling can be starved under continuous concurrency, preventing the configured context-creation recycle threshold from taking effect.
   Path: backend/app/services/acquisition/browser_pool.py
   Lines: 195-195

2. Code Quality: Timeout handling now masks inner coroutine timeout errors and can cause silent misbehavior instead of surfacing real failures.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 86-86

3. Code Quality: Truthiness-based stock mapping can misclassify non-boolean `isOutOfStock` values as out of stock.
   Path: backend/app/services/extract/field_candidates/variant_rows.py
   Lines: 406-406

4. Code Quality: Accepting untyped `sizeOptions.options` as variants can cause runtime type errors when list items are not objects.
   Path: backend/app/services/extract/field_candidates/variant_rows.py
   Lines: 334-334

5. Code Quality: A conditional gate causes bridge variant rows to be skipped whenever any primary variant rows already exist.
   Path: backend/app/services/js_state/state_normalizer/_variant_rows.py
   Lines: 38-38

6. Code Quality: Raising a different timeout exception type can break caller-side timeout handling contracts.
   Path: backend/app/services/acquisition/browser_pool.py
   Lines: 414-414

7. Code Quality: Forcing a minimum pool size of one overrides explicit zero configuration and changes runtime behavior.
   Path: backend/app/services/acquisition/browser_pool.py
   Lines: 833-833

8. Code Quality: Broad timeout catching masks real operation failures by treating them as normal “no result” states.
   Path: backend/app/services/acquisition/browser_recovery.py
   Lines: 86-86

9. Code Quality: A module-level async lock can bind to the wrong event loop and crash when reused across loops.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 120-120

10. Code Quality: Keys are marked as recently warmed even when warmup is skipped, causing incorrect deduplication.
   Path: backend/app/services/acquisition/browser_runtime.py
   Lines: 747-747

11. Code Quality: Variant extraction is executed twice for the same payload path, producing duplicate candidates.
   Path: backend/app/services/extract/field_candidates/structured_payloads.py
   Lines: 435-435

12. Code Quality: Truthiness-based stock mapping can misclassify string/encoded boolean values and produce the wrong availability status.
   Path: backend/app/services/extract/field_candidates/variant_rows.py
   Lines: 397-397

13. Code Quality: Single-size payload detection is incomplete because it only recognizes one size field naming variant.
   Path: backend/app/services/extract/field_candidates/variant_rows.py
   Lines: 439-439

14. Code Quality: Wrapping dictionary-form axis rows with list coercion can collapse multiple variants into one malformed row.
   Path: backend/app/services/js_state/state_normalizer/_variant_rows.py
   Lines: 60-60

15. Code Quality: Hardcoded header height can desynchronize virtualized row calculations and cause incorrect visible-row rendering during scroll.
   Path: frontend/components/crawl/records-table.tsx
   Lines: 132-132

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.