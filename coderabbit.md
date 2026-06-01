# Bug Triage

> **Instructions for agent:** Verify each issue against current code before fixing. Fix only still-valid issues; for invalid ones, note why briefly. Keep changes minimal and validate after each fix.

---

## 🔴 HIGH — Bugs

### BUG-001 · `logfire_span` no-op yields non-None object
**File:** `backend/app/core/logfire_integration.py`
**Problem:** `nullcontext()` yields itself, not `None`, so `span is None` assertions fail when Logfire is disabled.
**Fix:** Use `nullcontext(None)` (both in the `logfire_enabled` branch and the `ModuleNotFoundError` branch).

---

### BUG-002 · Potential PII/token exposure in Logfire span attributes
**File:** `backend/app/services/pipeline/extraction_loop.py`
**Problem:** Full URLs (including query params with tokens/emails) are attached as span attributes. `logfire_span` only truncates, does not redact.
**Fix:** Strip query strings and fragments before logging. Use `normalize_domain(url)` or a hashed URL only. Add a `strip_url_sensitive_parts(url)` helper used consistently across all span attribute sites.

---

## 🟡 MEDIUM — Bugs

### BUG-003 · `<select>` display label blanked when multiple options exist
**File:** `backend/app/services/extract/detail/variants/dom_availability.py` · L120, L195
**Problem:** `_control_display_label` returns `""` for `<select>` with multiple options, causing `axis_value` to be empty and out-of-stock variants to be silently dropped.
**Fix:** For `<select>`, derive display from the currently selected `<option>` value instead of returning `""`.

---

### BUG-004 · DOM axis detection now includes arbitrary `option_values` keys
**File:** `backend/app/services/extract/detail/variants/dom_merge.py`
**Problem:** `_variant_axes_present` now counts any key in `option_values` as an axis, including non-public keys, changing Cartesian expansion behavior vs. previous logic.
**Fix:** Restrict `option_values` axis detection to `public_variant_axis_fields` only.

---

## 🟢 LOW — Bugs

### BUG-005 · Admin LLM model dropdown uses untrimmed value for catalog check
**File:** `frontend/app/admin/llm/page.tsx`
**Problem:** `modelInCatalog` uses `form.model` while other logic uses `form.model.trim()`, causing whitespace variants to be misclassified as custom and duplicated in the dropdown.
**Fix:** Compute `modelInCatalog = recommendedModels.includes(formModel)` using the already-trimmed `formModel`.

---

## 🟡 MEDIUM — Code Quality / Reliability

### QUAL-001 · `_variant_options` star import pollutes extraction_rules public API
**File:** `backend/app/services/config/extraction_rules/__init__.py`
**Problem:** `from ._variant_options import *` exports `re` and all module-level names because `_variant_options.py` has no `__all__`.
**Fix:** Add `__all__` to `_variant_options.py` listing only public constants, or switch to explicit named imports.

---

### QUAL-002 · `__all__` collapsed into long lines in `identity/core.py`
**File:** `backend/app/services/extract/detail/identity/core.py`
**Problem:** Multi-item lines in `__all__` make diffs noisy and increase merge conflict risk.
**Fix:** Restore one-item-per-line format, or apply `ruff`/`black` consistently.

---

### QUAL-003 · Axis inference misses `<select>` controls → cross-axis assignment errors
**File:** `backend/app/services/extract/detail/variants/dom_availability.py` · L195

### QUAL-004 · Circular import risk from new cross-module import
**File:** `backend/app/services/extract/detail/variants/dom_extraction.py` · L53

### QUAL-005 · Cross-ASIN variant URL detector never inspects URL/ASIN
**File:** `backend/app/services/extract/detail/variants/pruning.py` · L244
**Problem:** Function always returns the same result, incorrectly exempting unrelated variants from pruning.

### QUAL-006 · Numeric-size noise rule deletes valid decimal size values
**File:** `backend/app/services/extract/detail/variants/pruning.py` · L439

### QUAL-007 · `normalize_domain(url)` called without null/malformed URL guard
**File:** `backend/app/services/pipeline/extract_records.py` · L250
**Fix:** Guard with `url and is_valid_url(url)` before calling `normalize_domain`.

### QUAL-008 · `len()` on possibly-None extraction result
**File:** `backend/app/services/pipeline/extract_records.py` · L90
**Fix:** Guard with `if result is not None` before `len(result)`.

### QUAL-009 · Metrics container not null-checked before key access
**File:** `backend/app/services/pipeline/extraction_loop.py` · L207
**Fix:** Add `if metrics:` guard.

### QUAL-010 · Telemetry crashes when extraction returns non-sized result
**File:** `backend/app/services/pipeline/record_extraction_stage.py` · L381

---

## 🔁 Inline Fix Instructions (verbatim prompts for agent)

> Apply each fix only if the issue is still present in current code.

**`backend/app/api/crawls.py` · L410**
Add `extra={"run_id": run_id}` to `logger.exception("Run logs websocket stream failed")`.

**`backend/app/api/crawls.py` · L395**
Add `extra={"run_id": run_id}` to the `logger.warning("Run logs snapshot did not reload run; retrying")` call.

**`backend/app/core/config.py` · L215–244**
Replace `issue_count` numeric logging with full `", ".join(password_issues)` detail in both `warn`/`error` log calls.

**`backend/app/core/public_auth.py` · L31–36**
HMAC-based `hash_api_key` invalidates existing `ApiKey.key_hash` rows. Add backwards-compatible SHA-256 fallback in validation, or use a versioned `key_hash` field + migration plan. Do not break existing key lookup.

**`backend/app/core/redis.py` · L91, L94**
Restore `operation_name` structured field to `redis_fail_open` logger call: `extra={"operation_name": operation_name, "exception_type": type(exc).__name__}`.

**`backend/app/main.py` · L201–207**
Create dedicated `public_rate_limit_buckets` + `public_rate_limit_lock` on crawler app state (see `auth_rate_limit_buckets` as precedent). Pass these into `consume_public_rate_limit` so public and general limiters don't share an `OrderedDict`.

**`backend/app/mcp/alert_server.py` · L145–150**
Change error `"message"` field from `type(exc).__name__` to `f"{type(exc).__name__}: {exc}"`. Also log full exception with `logger.exception(...)` before returning.

**`backend/app/models/crawl_settings.py` · L73**
Expand exception handling beyond single type to restore previously handled invalid inputs.

**`backend/app/models/playground.py` · L32**
Change `user: Mapped[Any]` → `Mapped["User"]`. Add `TYPE_CHECKING`-guarded import.

**`backend/app/services/acquisition/browser_diagnostics.py` · L166**
Replace generic substring match for driver-closed detection with a specific check to avoid misclassifying unrelated `AttributeError`s.

**`backend/app/services/acquisition/browser_interstitial.py` · L118**
Remove `PlaywrightTimeoutError` from `except` tuples (it's a subclass of `PlaywrightError`). Result: `except (asyncio.TimeoutError, PlaywrightError)`.

**`backend/app/services/acquisition/playwright_compat.py` · L16–19**
Restore `RuntimeError` to `PLAYWRIGHT_RECOVERABLE_ERRORS` or replace with appropriate specific exceptions. Validate all retry/cleanup paths that depend on this tuple.

**`backend/app/services/acquisition/traversal_types.py` · L32–50**
Change `html_fragments: list[tuple[str, bool]]` → `list[tuple[str | None, bool]]` to match `compose_html` defensive handling.

**`backend/app/services/auth_service.py` · L30–33**
Change `logger.warning(... issue_count=%d, len(issues))` to include `issues` detail text alongside the count.

**`backend/app/services/config/extraction_rules/_detail.py` · L476**
Replace dynamic `__all__ = sorted(name for name in globals() if name.isupper())` with an explicit, enumerated `__all__` list.

**`backend/app/services/config/extraction_rules/_jobs.py` · L5–37**
Add explicit `import re` at top of module. Do not rely on wildcard `from ._common import *` to supply `re`.

**`backend/app/services/config/runtime_settings.py` · L310**
Add `_require_positive("selector_regex_max_pattern_length", self.selector_regex_max_pattern_length)` in `_apply_profile_defaults`.

**`backend/app/services/crawl/batch_runtime.py` · L71–78**
Handle both callable and integer `url_batch_concurrency`: call it if callable, cast to `int` if not, fall back to `_DEFAULT_URL_CONCURRENCY` on `AttributeError`/`TypeError`/`ValueError`.

**`backend/app/services/crawl/service.py` · L230–247**
Gate `_shutdown_browser_runtime_after_kill()` in the local-task branch on runtime ownership + no other active local runs. In the Celery branch, replace direct shutdown with a worker-directed control action (see `app.control.revoke`).

**`backend/app/services/fetch/fetch_context.py` · L271–275**
Tighten patchright probe cap logic: apply cap only on exact vendor match (`expected_vendor == last_vendor`). If `expected_vendor` is empty, keep existing `True` behavior. If non-empty but no match, return `False`.

**`backend/app/services/js_state/state_normalizer/_variant_rows.py` · L232–263**
Add `depth` param (default 0) to `_collect_variant_matrix_rows`. Increment on recursion. Return early when depth hits `JS_STATE_LIST_ITERATION_LIMIT` (or equivalent). Apply check before descending into `node["elements"]`.

**`backend/app/services/js_state/state_normalizer/_variant_rows.py` · L296–302**
Add `"lowstock"` branch: `if lowered == "lowstock": row["availability"] = "in_stock"`, alongside existing `"instock"` and `"outofstock"` branches.

**`backend/app/services/monitor_condition.py` · L100–132**
In `_first_decimal_text`: capture `end` index when first loop breaks, then slice `text[start:end]`. Remove second redundant scan. Preserve `-` prefix handling, `saw_dot`, `saw_digit`, and `return None` when no digit seen.

**`backend/app/services/pipeline/extraction_loop.py` · L103**
Remove `asyncio` from module `__all__`. Update tests to patch via `monkeypatch.setattr(extraction_loop.asyncio, "to_thread", ...)` instead.

**`backend/app/services/product_intelligence/discovery.py` · L1282–1283**
Change `text.replace('"', " ")` to `text.replace('"', '\\"')` so embedded double-quotes are escaped, not stripped. Keep `return f'"{text}"'` wrapper. Validate output against SerpAPI and Google Native.

**`backend/tests/fixtures/loader.py` · L24–25**
Decide: if empty string is intended → remove `pytest.skip(...)`, keep `return ""`. If skip is intended → remove `return ""`. They are mutually exclusive; pick one.

**`backend/tests/regression/test_data_enrichment.py` · L293, L371**
Replace `await asyncio.gather(task)` with `await task` (single-task gather is unnecessary).

**`frontend/components/crawl/crawl-config-screen.prefill.test.tsx` · L166–168**
After `expectDomainProfileLookup(...)`, await a helper or use a `waitFor` wrapper to confirm `listSelectorsMock` has been called with `{ domain: 'example.com' }` before asserting. This fixes the race condition.

**`frontend/components/crawl/markdown-output.tsx` · L20–50**
Replace CDN KaTeX injection (`document.createElement('script'/'link')`) with bundled `katex` package import + CSS import via the app's normal build path. Keep `KaTeXApi`/`browserWindow` handling.

**`frontend/components/crawl/markdown-output.tsx` · L196–218**
Before entering frontmatter parse mode (`index === 0 && trimmed === '---'`), search for a closing `---` at `closingIndex > index`. Only parse as frontmatter if `closingIndex !== -1`. Otherwise treat the line as normal content.