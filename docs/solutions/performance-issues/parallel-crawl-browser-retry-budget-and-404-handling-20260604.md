---
module: Crawl Acquisition Runtime
date: 2026-06-04
problem_type: performance_issue
component: service_object
symptoms:
  - Parallel crawl URLs appeared stuck after browser escalation
  - Patchright and real Chrome retries could consume most of a URL budget
  - 404 SPA shells could escalate to browser instead of failing cleanly
root_cause: logic_error
resolution_type: code_fix
severity: high
tags: [parallel-crawl, browser-retry, url-budget, http-404, ui-logs]
---

# Parallel Crawl Retry and 404 Handling

## Symptom

Large parallel commerce crawls completed, but some URL rows looked stuck or took much longer than the rest. Browser fallback was especially expensive when HTTP failed, Patchright failed, then real Chrome launched near the end of the per-URL budget.

Another bad path existed for non-retryable HTTP statuses: a `404` response that looked like a JavaScript shell could still trigger browser escalation before the non-retryable status guard ran.

## Root Cause

The acquisition escalation decision checked shell heuristics before honoring non-retryable HTTP statuses. That made `404`/other non-retryable `4xx` responses eligible for browser work in some cases.

Empty extraction browser retry also did not account for the browser render timeout plus the URL timeout buffer, so retries could start without enough remaining URL budget to finish cleanly.

Parallel UI grouping depended on logs attaching to the correct URL. Terminal failure logs did not always carry the explicit `[url:...]` prefix used by the frontend grouping logic.

## Fix

- Non-retryable HTTP statuses now short-circuit browser escalation before shell heuristics.
- Empty extraction browser retry now skips when the remaining URL budget cannot cover browser render time plus timeout buffer.
- Non-retryable `4xx` detail results with zero records now return a clean URL `error` verdict with `failure_reason=non_retryable_http_status`.
- URL failure logs now include `[url:...]` so the parallel UI can attach terminal errors to the correct row.
- Parallel crawl regression test timing was made deterministic so concurrency checks do not rely on incidental scheduling.

## Verification

Run from `backend/`:

```powershell
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests/component/test_crawl_fetch_runtime.py -q
.\.venv\Scripts\python.exe -m pytest tests/regression/test_pipeline_core.py -m regression -q
.\.venv\Scripts\python.exe -m pytest tests/regression/test_batch_runtime.py -m regression -q
```

Observed passing results:

- `test_crawl_fetch_runtime.py`: 82 passed
- `test_pipeline_core.py -m regression`: 58 passed
- `test_batch_runtime.py -m regression`: 28 passed, 3 deselected

## Notes

Keep concurrency and browser timeout tuning in `.env` / `app/services/config/*`. Do not add hardcoded per-site browser retry behavior in acquisition or pipeline code.
