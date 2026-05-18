# Plan: UCP Compliance Audit

**Created:** 2026-05-18
**Agent:** Codex
**Status:** COMPLETE
**Touches buckets:** API + Bootstrap, Acquisition + Browser Runtime, Extraction, Publish + Persistence, Config, Frontend

## Goal

Add a persisted UCP Compliance Audit feature that shows a merchant what agent-readable commerce signals exist, what is missing, and which gaps block or weaken UCP readiness. The audit uses the seven dimensions from `UCP-audit-plan.md`, but it is a separate audit/report subsystem, not a new crawl surface. Done means users can create an audit job, inspect a seven-dimension report, export JSON/Markdown, and continue later with monitoring/API integration.

## Acceptance Criteria

- [x] UCP audit plan is active in `docs/plans/ACTIVE.md`
- [x] Backend config and deterministic dataclasses exist under `backend/app/services/ucp_audit/`
- [x] D-UCP1 manifest discovery fetches configured manifest path through existing HTTP acquisition/fetch path
- [x] D-UCP2 Product JSON-LD schema scoring reuses `structured_sources.parse_json_ld`
- [x] D-UCP3 metafield coverage and D-UCP4 taxonomy checks consume schema diagnostics without re-acquisition
- [x] D-UCP5 variant fidelity reads existing public flat variant data only
- [x] D-UCP6 policy readability accepts upstream HTTP policy facts and does not fetch
- [x] D-UCP7 agent-view delta uses existing acquisition paths and no direct browser driver
- [x] D-UCP1 hard gate caps overall score when manifest discovery fails
- [x] Persisted audit job/report models and API routes exist
- [x] Frontend `/ucp-audit` dashboard exists with history, score cards, findings, and exports
- [x] Docs updated for ownership, contracts, and frontend/API routes
- [x] `python -m pytest tests -q` exits 0

## Do Not Touch

- `adapters/*` — UCP audit consumes extracted/public signals, not platform adapters
- `pipeline/persistence.py` and `publish/*` — do not compensate downstream for audit findings
- Existing crawl `surface` behavior — UCP audit is not a crawl surface unless a later plan explicitly changes that
- Data enrichment taxonomy source files — reuse Shopify taxonomy/attribute infrastructure; do not add local product synonym maps
- LLM runtime — UCP primitive checks are deterministic; LLM remains out of scope unless a later opt-in slice adds advisory copy

## Slices

### Slice 0: Config + Package Base
**Status:** DONE
**Files:**
- `backend/app/services/config/ucp_audit.py`
- `backend/app/services/ucp_audit/__init__.py`
- `backend/app/services/ucp_audit/types.py`
- `backend/tests/services/ucp_audit/*`

**What:**
Add UCP-owned config constants and shared dataclasses. Keep manifest path, capability names, JSON-LD field paths, critical attributes, status labels, dimension IDs, scoring weights, thresholds, and finding codes in config only.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_config_imports.py tests/services/ucp_audit -q`

### Slice 1: D-UCP1 Manifest Discovery
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/discovery.py`
- `backend/tests/services/ucp_audit/test_discovery.py`

**What:**
Fetch the configured UCP manifest path through the existing HTTP fetch path. Return observational facts only: found/not found, valid/invalid, declared/missing capabilities, raw manifest, and errors. 404 is not exceptional.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_discovery.py -q`

### Slice 2: D-UCP2 Product JSON-LD Schema Score
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/product_schema.py`
- `backend/tests/services/ucp_audit/test_product_schema.py`

**What:**
Score Product JSON-LD completeness from supplied HTML only. Reuse `structured_sources.parse_json_ld`. Return required/recommended/UCP field coverage plus diagnostic passthrough for downstream catalog and variant checks.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_product_schema.py -q`

### Slice 3: D-UCP3/D-UCP4 Catalog Checks
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/catalog_checks.py`
- `backend/tests/services/ucp_audit/test_catalog_checks.py`

**What:**
Compute critical attribute coverage from JSON-LD `additionalProperty` diagnostics and taxonomy consistency from raw product category/type values. Reuse existing Shopify taxonomy loading path; no local product synonym maps. Dedup is lowercase + strip only.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_catalog_checks.py -q`

### Slice 4: D-UCP5/D-UCP6 Compliance Checks
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/compliance_checks.py`
- `backend/tests/services/ucp_audit/test_compliance_checks.py`

**What:**
Score variant fidelity from public flat variant records and policy readability from upstream-provided facts. This slice does not recrawl, fetch policy pages, or mutate crawl records.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_compliance_checks.py -q`

### Slice 5: D-UCP7 Agent-View Delta
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/agent_delta.py`
- `backend/tests/services/ucp_audit/test_agent_delta.py`

**What:**
Compare default HTTP structured extraction against browser-rendered extraction using existing acquisition infrastructure. Do not instantiate browser drivers directly. Agent UA override is config-only for now because acquisition does not expose per-request headers.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_agent_delta.py -q`

### Slice 6: Scoring Engine
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/scoring.py`
- `backend/tests/services/ucp_audit/test_scoring.py`

**What:**
Aggregate seven dimensions into a compliance report. Apply D-UCP1 hard gate: if discovery score is zero, cap the overall score at the configured maximum regardless of weights.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_scoring.py -q`

### Slice 7: Persisted Audit Jobs + Report Storage
**Status:** DONE
**Files:**
- `backend/app/models/ucp_audit.py`
- `backend/app/models/__init__.py`
- `backend/app/schemas/ucp_audit.py`
- `backend/alembic/versions/[timestamp]_ucp_audit.py`
- `backend/app/services/ucp_audit/service.py`

**What:**
Add persisted audit job, page result, and report rows. Job stores user, domain, status, options, summary, and completed timestamp. Page results store per-URL dimension payloads and findings. Final report stores overall score, dimension scores, findings, and Markdown/JSON payloads.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit tests/services/test_config_imports.py -q`

### Slice 8: API Routes + Background Execution
**Status:** DONE
**Files:**
- `backend/app/api/ucp_audit.py`
- `backend/app/main.py`
- `backend/tests/services/ucp_audit/test_api.py`

**What:**
Add authenticated routes:
- `POST /api/ucp-audit/jobs`
- `GET /api/ucp-audit/jobs`
- `GET /api/ucp-audit/jobs/{job_id}`
- `GET /api/ucp-audit/jobs/{job_id}/export.json`
- `GET /api/ucp-audit/jobs/{job_id}/export.md`

Use background task pattern like Product Intelligence for first version. Access control mirrors Product Intelligence/Data Enrichment.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_api.py -q`

### Slice 9: Report Builder
**Status:** DONE
**Files:**
- `backend/app/services/ucp_audit/reporting.py`
- `backend/tests/services/ucp_audit/test_reporting.py`

**What:**
Build JSON and Markdown reports from one `UCPComplianceReport`. Markdown includes executive summary, dimension scores, and findings.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/ucp_audit/test_reporting.py -q`

### Slice 10: Frontend Dashboard
**Status:** DONE
**Files:**
- `frontend/app/ucp-audit/page.tsx`
- `frontend/app/ucp-audit/ucp-audit-page.tsx`
- `frontend/app/ucp-audit/use-ucp-audit.ts`
- `frontend/app/ucp-audit/ucp-audit-components.tsx`
- `frontend/lib/api/index.ts`
- `frontend/lib/api/types.ts`
- `frontend/components/layout/app-shell.tsx`

**What:**
Add UCP Audit operator page with domain input, job creation, history, overall score cards, seven-dimension table, findings table, and JSON/Markdown export buttons. Use existing UI primitives and API client layer.

**Verify:** Inspect `frontend/package.json`, then run the smallest matching type/test command.

### Slice 11: Docs + Broad Verification
**Status:** DONE
**Files:**
- `docs/CODEBASE_MAP.md`
- `docs/BUSINESS_LOGIC.md`
- `docs/backend-architecture.md`
- `docs/frontend-architecture.md`
- `docs/INVARIANTS.md`
- `docs/plans/ACTIVE.md`

**What:**
Document UCP audit as a separate report subsystem. Add ownership map, API/frontend route notes, and invariant that UCP audit reuses acquisition/extraction and does not mutate crawl surface or downstream persistence semantics.

**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q`

## Doc Updates Required

- [x] `docs/CODEBASE_MAP.md` — add UCP audit backend/frontend ownership
- [x] `docs/BUSINESS_LOGIC.md` — add UCP audit job/report behavior
- [x] `docs/backend-architecture.md` — add API, service, and persistence section
- [x] `docs/frontend-architecture.md` — add `/ucp-audit` route and API usage
- [x] `docs/INVARIANTS.md` — add UCP audit contract if API/persistence implementation changes runtime behavior

## Notes

- 2026-05-18: Slices 0-6 implemented and targeted tests passed: `tests/services/ucp_audit -q` reported 16 passed. `tests/services/test_config_imports.py -q` reported 33 passed.
- 2026-05-18: `tests/services/test_structure.py -q` currently fails on pre-existing private imports in `extract/variant_normalization/common.py`; not caused by UCP audit files.
- 2026-05-18: Slices 7-11 implemented. Targeted UCP backend tests passed: `tests/services/ucp_audit tests/services/test_config_imports.py -q` reported 56 passed. Frontend `npm run lint` and `npm run build` passed. Full backend `tests -q` passed with 1725 passed and 16 skipped.
