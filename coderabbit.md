These are comments left during a code review. Please review all issues and provide fixes.

1. logic error: Detail requests now scan every page instead of returning the matched job immediately.
   Path: backend/app/services/adapters/oracle_hcm.py
   Lines: 100-100

2. possible bug: Export list now includes symbols that are not defined by the package.
   Path: backend/app/services/config/extraction_rules/_extra_exports.py
   Lines: 206-206

3. possible bug: A newly added runtime threshold has no effect because nothing in the config layer uses it.
   Path: backend/app/services/config/runtime_settings.py
   Lines: 374-374

4. logic error: Running DOM availability reconciliation twice can leave the final variant list out of sync with normalization.
   Path: backend/app/services/extract/detail/assembly/final_cleanup.py
   Lines: 98-98

5. logic error: Reusing the same parsed DOM after mutation can return stale cached variant data.
   Path: backend/app/services/extract/detail/variants/dom_extraction.py
   Lines: 539-539

Validate the correctness of each issue sequentially. For each issue that is correct, implement a fix. Please make the fixes concise and address all issues comprehensively and don't impact anything else.