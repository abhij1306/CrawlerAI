# Bug Triage — AI Crawler PR Review

---

## 🔴 SECURITY — High Priority

### SEC-001 · Legacy API Keys Break Auth
**File:** `backend/app/core/public_auth.py` · Lines 54–60
**Issue:** Legacy SHA-256 hash fallback removed; any key stored with the old hash returns 401.
**Fix:** Compute legacy hash alongside new hash in `session.scalar(select(...))`. If a legacy match is found, re-hash and update the row in the same transaction (dual-check-and-migrate).

---

### SEC-002 · SSRF via Internal API Replay
**File:** `backend/app/services/acquisition/acquirer.py` · Lines 220–254
**Issue:** `internal_api_endpoints` URLs are persisted and replayed with no origin/IP validation — SSRF primitive.
**Fix:** Enforce same-origin constraint, HTTPS-only, block private IP ranges, no redirects, cap timeouts/size in `replay_internal_api_endpoints`.

---

## 🟠 BUGS — Medium/High Priority

### BUG-001 · Nav Tree Silently Drops Children
**File:** `backend/app/services/crawl/sitemap_resolver.py`
**Issue:** `children_for()` returns a new `[]` when `children` isn't a list but doesn't write it back to `node["children"]`, so appends are lost.
**Fix:** `node["children"] = []` when type is wrong; return the stored reference.

---

### BUG-002 · `category_only` Filter Too Strict
**File:** `backend/app/services/crawl/sitemap_resolver.py`
**Issue:** `_looks_like_category_url()` misses common patterns like `/women/shoes`; UI shows no categories.
**Fix:** Relax token matching or use scoring-based filtering; add logging for empty results.

---

### BUG-003 · `internal_api_endpoints` Not Normalized in `CrawlRunSettings`
**File:** `backend/app/models/crawl_settings.py` · Lines 426, 472
**Issue:** `profile()` and `normalized()` copy raw endpoint lists, bypassing `normalize_internal_api_endpoints()`. Empty-list overrides silently dropped (truthy check only).
**Fix:** Call `normalize_internal_api_endpoints()` in both methods; change `if self.data.get(...)` to `if ... is not None` to preserve explicit empty lists.

---

### BUG-004 · Dispatcher `dispatch()` Changed to `@staticmethod`
**File:** `backend/app/services/dispatch/celery_dispatcher.py`, `local_dispatcher.py`
**Issue:** Breaks `RunDispatcher` protocol/ABC interface; causes mypy and runtime inconsistencies.
**Fix:** Revert to `async def dispatch(self, ...)` — keep `self` even if unused.

---

### BUG-005 · `run_id` Removed from Websocket Log Context
**File:** `backend/app/api/crawls.py` · Lines 308–342
**Issue:** `extra={"run_id": run_id}` stripped from warning/exception logs; impossible to correlate errors to a run.
**Fix:** Restore `run_id` in `extra`. Also change path params to `/{run_id:int}/kill`, `/{run_id:int}/cancel`, `/{run_id:int}/logs/ws` for consistency and to return 404 on non-integer IDs.

---

### BUG-006 · Replay Branch Skips `PolicyMiddleware.after_fetch`
**File:** `backend/app/services/acquisition/acquirer.py` · Lines 220–254
**Issue:** Early return on `replay_payload` leaks state set in `before_fetch`.
**Fix:** `await policy_middleware.after_fetch(...)` immediately before returning the `AcquisitionResult` in the replay branch.

---

### BUG-007 · `_endpoint_list` Accepts Any HTTP Method
**File:** `backend/app/services/acquisition/policy.py` · Lines 203–222
**Issue:** No allowlist enforcement; raw dicts stored without normalization break deduplication.
**Fix:** Normalize `method = str(...).strip().upper()`; skip if not in `INTERNAL_API_ENDPOINT_ALLOWED_METHODS`; persist normalized dict.

---

### BUG-008 · `RuntimeError` in `_RECOVERABLE_ERRORS` Too Broad
**Files:** `backend/app/services/acquisition/traversal_helpers.py` · Line 35
`backend/app/services/acquisition/traversal_recovery.py` · Line 24
**Issue:** `RuntimeError` is too generic — swallows programming errors silently.
**Fix:** Remove `RuntimeError` from both tuples; catch `PlaywrightError`/`PlaywrightTimeoutError` or a narrow custom `RecoverableAcquisitionError` only.

---

### BUG-009 · `save_domain_run_profile` Missing `existing_record` → Upsert Conflict
**File:** `backend/app/services/crawl/profile/acquisition_contract.py` · Lines 269–277
**Issue:** Follow-up write omits `existing_record`, causing insert instead of upsert → unique-constraint violation.
**Fix:** Pass `existing_record=existing` to `save_domain_run_profile` call.

---

### BUG-010 · Unsafe `float()` Cast on `raw_network_payload_count`
**File:** `backend/app/services/crawl/profile/acquisition_contract.py` · Lines 84–89
**Issue:** `float("abc")` raises `ValueError`.
**Fix:** Wrap in `try/except (ValueError, TypeError)`, fall back to `0.0`.

---

### BUG-011 · Unsafe `int()` Cast on `raw_source_run_id`
**File:** `backend/app/services/crawl/profile/acquisition_contract.py` · Lines 188–193
**Issue:** Direct `int()` on non-numeric string raises `ValueError`.
**Fix:** `try: int(val)` → `except: try: int(float(val))` → `except: fallback to 1`.

---

### BUG-012 · Endpoint Merge Replaces Instead of Merges
**File:** `backend/app/services/crawl/profile/merge.py` · Lines 197–207
**Issue:** `explicit_endpoints or saved_endpoints` fully replaces learned endpoints.
**Fix:** Union/merge both lists; explicit entries take precedence for conflicts, preserved entries stay.

---

### BUG-013 · `internal_api_replay` Always Uses `client.get()`
**File:** `backend/app/services/acquisition/internal_api_replay.py` · Lines 95–148
**Issue:** `method` is parsed but ignored; POST/PUT/etc. endpoints always replay as GET.
**Fix:** Use generic `client.request(method, url, timeout=...)` instead of `client.get()`.

---

### BUG-014 · Content Hash Failure Treated Incorrectly
**File:** `backend/app/services/monitor_scheduler_service.py` · Lines 78–83
**Issue:** `content_hash is None` when a prior hash existed should be treated as changed; currently it may not be.
**Fix:** Set `changed = had_prior_hash`; do not overwrite `state.last_content_hash` when hash is `None`.

---

## 🟡 CODE QUALITY — Low Priority

### QUAL-001 · Lazy-Import Globals Not Concurrency-Safe
**Files:** `backend/app/services/dispatch/celery_dispatcher.py`, `monitor_scheduler_service.py` · Lines 33–41
**Issue:** Global `None` + check-and-set pattern races under concurrent workers.
**Fix:** Use `functools.lru_cache` or a `threading.Lock` (double-checked lock) around import + assignment.

---

### QUAL-002 · `operation_name` Dropped from Redis Failure Logs
**File:** `backend/app/core/redis.py` · Lines 81–118
**Issue:** `operation_name` accepted but not logged; `schedule_fail_open` doesn't forward it.
**Fix:** Add `"operation_name": operation_name` back to `extra` in `logger.warning`; forward it in `schedule_fail_open`.

---

### QUAL-003 · `__all__` Exports Private Symbols / Incomplete
**Files:**
- `backend/app/core/redis.py` · Line 24 — exports only `_last_disable_log_at` (private)
- `backend/app/core/telemetry.py` · Line 26 — exports only `_LOGGING_CONFIGURED` (private)
- `backend/app/main.py` · Line 354 — exports only `RATE_LIMIT_BUCKETS`
- `backend/app/services/dom/selector_engine.py` · Line 85 — exports `_CANDIDATE_CLEANUP` (private)

**Fix:** Either remove `__all__` or update to list actual public symbols only. Remove all private (`_`-prefixed) names.

---

### QUAL-004 · Alert MCP Error Loses Exception Message
**File:** `backend/app/mcp/alert_server.py`
**Issue:** Error response returns only `type(exc).__name__`, stripping diagnostic detail.
**Fix:** Return sanitized `f"{type(exc).__name__}: {exc}"` or add a server-side correlation ID.

---

### QUAL-005 · BAN-B410 Suppression Comments Not Specific Enough
**Files:** `backend/app/services/dom/selector_engine.py` · Lines 13–14
`backend/app/services/dom/xpath_service.py` · Lines 9–10
**Fix:** Update suppression comment to state: lxml is used in **HTML parsing mode** (`lxml.html.fromstring`), not arbitrary XML; parsing is scoped to trusted/sanitized input.

---

### QUAL-006 · Duplicated `selected_urls` Logic in Playground Schemas
**File:** `backend/app/schemas/playground.py` · Lines 14–33
**Issue:** `PlaygroundSessionCreate` and `PlaygroundSelectCategoryRequest` duplicate identical URL normalization.
**Fix:** Extract `_normalize_selected_urls(url, urls) -> list[str]` helper; both validators call it.

---

### QUAL-007 · `getattr` Used on Always-Present `nav_tree` Attribute
**File:** `backend/app/services/playground_service.py` · Lines 181, 318
**Issue:** `getattr(resolution, "nav_tree", None)` is defensive where `SitemapResolutionResult.nav_tree` always exists.
**Fix:** Replace with direct `resolution.nav_tree`.

---

## 🖥️ FRONTEND

### FE-001 · Branch Labels Don't Toggle Expansion
**File:** `frontend/app/playground/page.tsx` · Lines 1171–1180
**Fix:** Wire branch `onClick` to toggle-expand function instead of returning `undefined`.

---

### FE-002 · Duplicate React Keys in List/Quote Renderers
**Files:** `frontend/components/crawl/markdown-output.tsx` · Lines 350–354, 377–381
**Fix:** Use `index` (or `${item}-${index}`) as key in both `quote.map` and `items.map`.

---

### FE-003 · No Client-Side Guard in `createPlaygroundSession`
**File:** `frontend/lib/api/index.ts` · Lines 350–351
**Fix:** Validate `payload.url` or `payload.urls.length > 0` before `apiClient.post`; throw if neither present.

---

### FE-004 · Stateful `/g` Regex Shared Across Calls
**File:** `frontend/lib/ui/syntax.ts` · Lines 5–6
**Issue:** Module-level `tokenRegex` with `/g` flag retains `lastIndex` between calls → skipped tokens.
**Fix:** Reset `tokenRegex.lastIndex = 0` at top of each function, or create `new RegExp(...)` per call.

---

### FE-005 · Duplicate React Keys in `syntaxHighlightJsonNodes`
**File:** `frontend/lib/ui/syntax.ts` · Lines 117–135
**Fix:** Use `${index}-${line}` as span key instead of raw `line` content.

---

*Total: 2 Security · 14 Bugs · 7 Quality · 5 Frontend = **28 issues***
