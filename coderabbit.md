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