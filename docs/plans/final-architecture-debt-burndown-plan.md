# Plan: CrawlerAI Debt Burn-Down And Crawl Quality Fix

## Summary

Goal: make backend smaller and more correct. Not prettier. Not more fixtures.

Implement by debugging real failure classes, deleting duplicate paths, and shrinking bloated modules. New code must replace more code than it adds.

Current measured state:
- `backend/app`: 64,957 lines / 309 Python files
- Biggest bloat: `acquisition` 16,739 LOC, `core` 14,773 LOC, `crawl` 9,609 LOC
- Current hard debt: 6 modules over 700 lines, 25 functions over 100 lines
- Active-plan blockers: Slice 6 legacy persistence fields, Slice 9 LOC/function gates, Slice 13 final verification

## Hard Rules

- No broad “quality fixture manifest” work.
- No site-specific runtime branches.
- No downstream cleanup in publish/export/persistence for extraction bugs.
- No new compatibility layer.
- No new package unless it deletes or replaces a larger one.
- Every slice must reduce or hold net production LOC.
- Tests must be targeted regressions around broken behavior, not snapshot hoards.

## Quantitative Gates

Required before handoff:
- `backend/app` production LOC below 58,109, the pre-rebuild baseline.
- Stretch target: below 55,000 LOC.
- `acquisition` below 12,000 LOC.
- `crawl` below 7,500 LOC.
- `core` below 12,500 LOC.
- Zero non-data modules over 700 lines.
- Zero functions over 100 lines unless the allowlist has written justification and is smaller than today.
- Remove at least 25% of current production Python files where they are wrappers, pass-throughs, stale config, or duplicate owners.
- Full offline pytest passes.

## Slice 1: Debt Map And Deletion Pass

Start with deletion, not refactor.

Find and remove:
- pass-through wrappers
- unused config exports
- dead adapter/connector leftovers
- compatibility aliases
- duplicate normalizers
- duplicate acquisition/browser policy helpers
- stale tests tied to deleted internals

Verify:
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_final_architecture_ownership.py -q
```

Acceptance:
- production LOC drops
- no `app.services`
- no new long files/functions

## Slice 2: Persistence Field Retirement

Finish active Slice 6.

Retire active use of:
- `raw_data`
- `discovered_data`
- `source_trace`
- `raw_html_path`

Move remaining readers to canonical artifact/result readers. Keep migration/backfill only if needed for old DB rows.

Verify:
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_replay_persistence_guard.py tests\unit\test_final_architecture_ownership.py -q
```

Acceptance:
- persistence stores canonical result only
- no semantic repair in persistence
- legacy-field allowlist shrinks

## Slice 3: Acquisition LOC Collapse

Shrink the largest owner first.

Targets:
- `acquisition/browser_runtime.py`
- `acquisition/fetch/fetch_context.py`
- `acquisition/runtime.py`
- `acquisition/browser_detail.py`

Delete or merge duplicate logic around:
- browser escalation
- block classification
- warmup
- retry budget
- fetch context shaping
- browser settle/capture handoff

Keep only one path:
`AcquisitionPlanner -> AttemptExecutor -> CaptureBundle -> ExtractionEngine`

Verify:
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\component\test_acquirer.py tests\component\test_crawl_fetch_runtime.py tests\unit\test_acquisition_planner_executor.py -q
```

Acceptance:
- acquisition below 12,000 LOC
- no function over 100 lines in acquisition
- browser fallback always has `AttemptResult`
- no requested-field browser trigger path returns

## Slice 4: Crawl Runtime Collapse

Shrink orchestration.

Targets:
- `crawl/batch_runtime.py`
- `crawl/pipeline/extraction_loop.py`
- `crawl/pipeline/persistence.py`
- `crawl/pipeline/run_progress.py`

Delete duplicate state handling. Keep owners:
- `RunCoordinator`: run lifecycle
- `UrlProcessor`: one URL workflow
- repository/persistence: storage only

Fix session/transaction boundaries while shrinking.

Verify:
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\regression\test_batch_runtime.py tests\component\test_crawl_service.py -q
```

Acceptance:
- crawl below 7,500 LOC
- batch failure stays URL-local
- no duplicate records on retry/restart
- run progress computed from one source

## Slice 5: Output Bug Debugging

Use attached crawl output as debug list, not fixture inventory.

Debug and fix shared causes for:
- blocked page marked success: Dick’s “Oops” shell
- missing root URL on product rows
- missing brand/price/currency/image/availability with no diagnostic
- title polluted by URL filename, product ID, nav text, or SEO boilerplate
- primary image chosen from placeholder/UI/logo/payment/loader assets
- parent availability contradicting variants
- variant rows missing identity/offer fields when evidence exists
- category text winning as brand
- impossible `0.00` or 100x price drift

Likely owners:
- acquisition shell/block classifier
- extraction candidate admission
- detail identity/title resolver
- asset role classifier
- offer resolver
- variant resolver
- confidence scorer

Verify with small regression tests per fixed shared cause. Use 1-2 examples each. No giant fixture file.

## Slice 6: Core And Config Shrink

Shrink `core` by deleting stale config/data glue.

Targets:
- `core/config/runtime_settings.py`
- `core/config/extraction_rules/*`
- duplicate field coercion / record normalizer paths

Rules:
- config values stay in `app/core/config`
- duplicated generated exports go
- one owner for public field validation
- no semantic record repair outside extraction

Verify:
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\unit\test_extraction_architecture.py tests\unit\test_final_architecture_ownership.py -q
```

Acceptance:
- `core` below 12,500 LOC
- runtime settings split or trimmed
- stale extraction/config code reduced

## Slice 7: Intelligence And Enrichment Trim

Keep product features. Delete bloat.

Targets:
- `intelligence/matching.py`
- `intelligence/discovery.py`
- `enrichment/shopify_catalog.py`
- `enrichment/service.py`
- `enrichment/deterministic.py`

Actions:
- split scorer into small pure feature functions only if net LOC drops
- remove unused enrichment wrappers
- keep Shopify taxonomy data separate from runtime logic
- remove duplicate flatteners/material parsers

Verify:
```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests\component\test_product_intelligence.py tests\component\test_data_enrichment.py -q
```

Acceptance:
- no enrichment/intelligence function over 100 lines
- no independent product-detail scraper
- LLM cannot override deterministic conflicts

## Slice 8: Final Gate

Run final offline suite only.

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
```

Then update plan docs:
- mark old active plan superseded
- mark this plan awaiting user 100-site gate
- record final LOC/file/function counts
- record remaining justified exceptions, if any

Do not run live smoke.

## Public API / Contract Changes

None intended.

Allowed internal changes:
- remove legacy persistence fields from active readers
- shrink allowlists in architecture tests
- delete dead compatibility symbols
- keep public endpoint response field names stable

## Test Strategy

Use tests to prove behavior, not archive outputs.

Required test groups:
- architecture ownership and LOC gate tests
- persistence canonical reader tests
- acquisition fallback/block/shell tests
- extraction identity/title/image/offer/variant tests
- batch idempotency/retry tests
- full offline backend pytest

No broad crawl-output fixture dump. Add only minimal regressions for the shared bug being fixed.