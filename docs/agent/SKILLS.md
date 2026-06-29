# Agent Skills — CrawlerAI

Use the matching recipe for the task. Keep fixes in the owning subsystem.
If paths moved, update this file after confirming ownership in `docs/CODEBASE_MAP.md`.

---

## Run Tests

```powershell
cd backend
$env:PYTHONPATH='.'

.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_pipeline.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_architecture.py -q
.\.venv\Scripts\python.exe -m pytest tests/unit/test_final_architecture_ownership.py -q
.\.venv\Scripts\python.exe -m pytest tests/test_harness_support.py -q

.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Use the smallest relevant verify step first, then broaden if shared behavior changed.

---

## Fix an Extraction Bug

1. Add a failing test first when practical.
2. Trace the earliest bad source:
   - structured: `structured_sources.py`
   - adapter: `adapters/[platform].py`
   - JS state: `js_state_mapper.py`
   - network payload: extraction network mapper + `core/config/network_payload_specs.py`
   - DOM: `app/extraction/pipeline.py` and extraction collectors
   - alias or eligibility: `core/config/field_mappings.py`, `core/records/field_policy.py`
   - normalization: `core/records/*` coercion owners
3. Fix it there. Do not patch downstream.
4. Run the smallest matching extraction unit/replay test.
5. Run `pytest tests -q`
6. Update the active plan slice if one exists.

Never fix extraction bugs in `pipeline/core.py`, `publish/verdict.py`, or `publish/metrics.py`.

---

## Add a New Extraction Field

1. Identify the surface.
2. Add aliases in `core/config/field_mappings.py`.
3. Add eligibility in `core/records/field_policy.py`.
4. Add extraction at the right owner:
   - structured: `structured_sources.py`
   - detail DOM: `detail_extractor.py`
   - listing DOM: `listing_extractor.py`
   - platform-specific: `adapters/[platform].py`
5. Add normalization in `field_value_core.py` if needed.
6. Add a focused extraction test.
7. Update `docs/backend-architecture.md` only if the field is significant and user-facing.

---

## Add a New Platform Connector

1. Add metadata to `core/config/platforms.json`.
2. Create a provider module under `connectors/` only when it produces artifacts from documented/public platform APIs.
3. Route product-detail URLs through normal acquisition and extraction; connectors must not publish public records or set verdicts.
4. Add payload specs in `core/config/network_payload_specs.py` if needed.
5. Add focused offline tests and replay fixtures. Live smoke remains the final user-run gate for this architecture plan.

Do not hardcode platform names in generic runtime paths.

---

## Add a New API Route

1. Put the route in the correct `app/api/` router.
2. Add request or response schemas in `app/schemas/[resource].py` if needed.
3. Keep business logic in the owning service, not the route handler.
4. Add auth dependencies.
5. Add a focused API test.
6. Update `docs/backend-architecture.md` if the route changes the public surface.

---

## Delete Dead Code

1. Grep all callers.
2. Delete the dead symbol or file.
3. Delete tests that only verify that dead private implementation.
4. Run `pytest tests -q`
5. Remove stale doc references.
6. Do not leave re-export stubs.

---

## Modify Selector Self-Heal

- Owner: selector/domain-memory code under `app/crawl` and `app/core/records`
- Run only when requested fields are still missing.
- Persist only validated improvements.
- Do not synthesize if existing domain memory already satisfies the request.

Trace: `crawl/pipeline/*` -> selector runtime -> `crawl/domain_memory_service.py`

Test: `tests/services/test_selector_pipeline_integration.py`

---

## Modify Review or Domain Memory

- Review persistence owner: `review/__init__.py`
- Approved schema source of truth: `ReviewPromotion`
- Domain memory owner: `domain_memory_service.py`
- Scope: normalized `(domain, surface)` only

If review-save behavior changes, verify later loads still read the persisted snapshot.

---

## Diagnose a URL Result

1. Open the run-level `report.json` and follow the URL's direct diagnosis link.
2. Read only that result's `diagnose.json` first.
3. Check collector/stage outcomes, each field's winner and rejected candidates, firewall action, and the variant-drop ledger.
4. Use the existing `FieldEvidenceState` and rejection reason to identify the owning extraction stage.
5. Treat any diagnosis that requires source-code or `page.html` inspection to explain a missing/wrong field as a diagnostics defect. Fix the publisher or evidence flow before debugging around it.

`page.html` is the captured input for replay. It is not the primary diagnosis index.

---

## Refine a Knowledge Graph Contract

1. Resolve the normalized domain with `GET /api/knowledge/sites`.
2. Read the bounded graph and template contracts. Do not perform unbounded graph scans.
3. Select only a retained source candidate with `PUT /api/knowledge/contracts/{id}/selection`, including template, surface, canonical field, and `expected_version`.
4. On a version conflict, refresh site/graph/contracts before retrying. Never overwrite against stale state.
5. For an AI-generated field, use Crawl Studio's existing Generate + Save to Memory flow. The accepted CSS selector is then synced as an operator contract; generation alone does not activate it.
6. Verify the next matching run records `hit`, `fallback`, `stale_source`, or `override_miss`. Historical records remain unchanged.

Extraction runtime consumes frozen contracts and never calls an LLM.

---

## Update Docs After Implementation

| Change | Doc |
|---|---|
| File ownership or moves | `docs/CODEBASE_MAP.md` |
| Runtime contract | `docs/INVARIANTS.md` |
| User-visible behavior | `docs/BUSINESS_LOGIC.md` or `docs/backend-architecture.md` |
| Engineering rule or anti-pattern | `docs/ENGINEERING_STRATEGY.md` |
| Plan progress | active plan file + `docs/plans/ACTIVE.md` |

Do not use docs as changelogs.

---

## Add a New Surface Type

1. Update `services/field_policy.py`
2. Update `services/field_value_core.py`
3. Update `app/schemas/crawl.py`
4. Update `core/config/field_mappings.py`
5. Update frontend surface selection
6. Update `docs/backend-architecture.md`

---

## Modify Run Status or State Machine

Owner: `app/models/crawl_domain.py`

Update:
- `CrawlStatus`
- `_ALLOWED_TRANSITIONS`
- `TERMINAL_STATUSES`
- `ACTIVE_STATUSES`

Do not split status logic across files.

---

## Add a New Export Format

1. Add export method in `services/record_export_service.py`
2. Add route in `app/api/records.py`
3. Add response content-type handling
4. Add frontend API method and types
5. Update `docs/backend-architecture.md`
