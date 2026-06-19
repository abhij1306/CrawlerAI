# CrawlerAI Full Backend Extraction Rebuild Audit and Plan

Status: implemented against the active architecture contract.

## Final Contract

Extraction now uses one deterministic engine for exactly four explicit surfaces:

- `ecommerce_listing`
- `ecommerce_detail`
- `job_listing`
- `job_detail`

The backend rejects `auto`, does not infer or switch surfaces, and uses the selected
surface as authoritative.

## Completed Gates

- All four surfaces call `app.services.extraction.engine.extract`.
- Selectolax/Lexbor is isolated behind `app/services/extraction/documents.py`.
- Legacy extraction owners were deleted: `extract/**`, `extraction_v2/**`, `js_state/**`,
  `dom/**`, `listing_extractor.py`, `structured_sources.py`, `network_payload_mapper.py`,
  `extraction_context.py`, `surface_resolver.py`, selector self-heal/auto-learn/suggestions.
- Adapters no longer return public records; old adapter implementations were deleted.
- Selector runtime is CSS-only recipe CRUD; XPath, regex selectors, self-heal, and
  automatic recipe writes are gone.
- Acquisition uses bounded HTTP-to-browser escalation with one browser retry per URL.
- Successful extraction requires evidence, decisions, replay, and lineage.
- Generated config exports and export loader were deleted.
- Removed direct dependencies: `aiohttp`, `cssselect`, `dateparser`, `extruct`, `glom`,
  `jmespath`, `lxml`, `price-parser`, `psutil`, `regex`, `w3lib`, and related stubs.

## Size Gates

```text
extraction_engine_files=26
extraction_engine_loc=2934
extraction_related_prod_loc=9514
extraction_related_test_loc=3040
```

Original audited scope:

```text
extraction-related production LOC: 47,072
extraction-related test LOC:       44,383
```

Result:

```text
production reduction: >79%
test reduction:       >93%
```

## Acceptance Set

Implemented in `backend/tests/acceptance/test_replay_sites.py`.

```text
1. ecommerce_detail  https://acceptance.test/products/aeron-chair
2. ecommerce_listing https://acceptance.test/collections/chairs
3. job_detail        https://acceptance.test/jobs/staff-backend-engineer
4. job_listing       https://acceptance.test/careers
5. wrong-surface     https://acceptance.test/products/not-a-job as job_detail
```

The acceptance set asserts accurate fields/counts, evidence, decisions, replay,
lineage, selected-surface preservation, variant parent subject IDs, and wrong-surface
rejection.

## Verification

Focused verification only, per project instruction not to run the full suite:

```text
pytest tests/acceptance/test_replay_sites.py \
  tests/unit/test_extraction_architecture.py \
  tests/unit/test_extraction_pipeline.py \
  tests/unit/test_pipeline_browser_retry_budget.py \
  tests/unit/test_replay_persistence_guard.py \
  tests/component/test_selectors_runtime.py \
  tests/component/test_selectors_api.py \
  tests/component/test_browser_context.py \
  tests/component/test_record_export_service.py -q

140 passed
```

Architecture scans:

```text
legacy extraction import scan: no matches
generated config export scan: no matches
removed dependency import scan: no matches
extraction parser scan: only documents.py imports selectolax.lexbor
surface inference scan: no matches
```
