# CrawlerAI Codebase Map

Use this only to find the owning subsystem. Detailed behavior lives in the architecture docs and
hard constraints live in `INVARIANTS.md`.

## Runtime entrypoints

| Concern | Owner |
| --- | --- |
| FastAPI application and router registration | `backend/app/main.py` |
| Celery application and tasks | `backend/app/core/celery_app.py`, `backend/app/tasks.py` |
| Database and migrations | `backend/app/core/database.py`, `backend/app/core/migrations.py`, `backend/alembic/` |
| Frontend bootstrap and route registry | `frontend/src/main.tsx`, `frontend/src/app/route-registry.ts` |
| Local static validation and fixes | `scripts/check.ps1` |
| Affected test selection and execution | `scripts/test.ps1`, `scripts/validation.json` |

Support outside `backend/app/`:

| Concern | Owner |
| --- | --- |
| Explicit initial-admin command | `backend/bootstrap_admin.py` |
| ECR enhanced-scan policy | `backend/ecr_scan_gate.py` |
| Acceptance harness and site sets | `backend/harness/`, `backend/test_site_sets/` |
| Browser-surface probe | `backend/browser_surface_probe/` |
| Container and release workflows | `.github/workflows/`, root Docker/Compose files |

## Backend ownership

All paths below are relative to `backend/app/`.

| Subsystem | Canonical owner |
| --- | --- |
| API route adapters | `api/` |
| Public API v1 routes and auth | `api/public/`, `core/public_auth.py`, `connectors/public_api/` |
| Request/response schemas | `schemas/` |
| ORM models | `models/` |
| Runtime configuration and policy data | `core/config/` |
| Database, Redis, auth, rate limits, SSRF, telemetry | `core/` |
| Crawl creation, profiles, lifecycle, category discovery | `crawl/` |
| Per-URL pipeline and persistence orchestration | `crawl/pipeline/` |
| HTTP/browser acquisition, traversal, cookies | `acquisition/` |
| Evidence collection, entities, resolution, publication | `extraction/` |
| URL-result, record, export, and extraction-memory persistence | `persistence/` |
| Operator review | `crawl/review/` |
| LLM connectors and runtime | `connectors/llm/` |
| Platform-specific deterministic evidence adapters | `connectors/*_adapter.py`, `connectors/adapter_registry.py` |
| Product Intelligence | `intelligence/` |
| Data enrichment | `enrichment/` |
| Diagnosis, reports, metrics | `observability/` |
| Local MCP adapter over public REST | `mcp_server/` |
| Offline evaluation and benchmark gates | `evaluation/` |

## Main backend flows

Run execution:

```text
api/crawls.py
  -> crawl/ingestion_service.py
  -> crawl/crud.py + crawl/service.py
  -> tasks.py or local dispatch
  -> crawl/batch_runtime.py
  -> crawl/pipeline/
  -> acquisition/ -> extraction/ -> persistence/
```

Ecommerce-detail extraction:

```text
extraction/engine.py
  -> collectors/adapters/documents
  -> entities.py + targeting.py
  -> resolution/
  -> validation.py + result_building.py
  -> publication.py
```

Extraction memory:

```text
models/extraction_memory.py
  <-> persistence/extraction_memory*.py
  <- api/knowledge.py + crawl/review/
  -> immutable release snapshot + per-URL manifest
```

## Backend owner details

| Concern | Owner |
| --- | --- |
| Crawl settings normalization | `crawl/ingestion_service.py`, `schemas/crawl.py`, `models/crawl_settings*.py` |
| URL orchestration and isolation | `crawl/batch_runtime.py` |
| Fetch policy and attempt execution | `acquisition/policy.py`, `acquisition/executor.py`, `acquisition/fetch/` |
| Shared HTTP clients and redirect handling | `acquisition/runtime.py`, `core/url_safety.py` |
| Browser lifecycle and stages | `acquisition/browser_runtime.py`, `browser_pool.py`, `browser_stage_runner.py` |
| Traversal | `acquisition/traversal.py`, `acquisition/traversal_*` |
| Cookie/storage lifecycle | `acquisition/cookie_store.py`, `run_cookie_storage.py`, `cookie_http_export.py` |
| Surface contracts | `extraction/surfaces.py`, `extraction/contracts.py` |
| Listing extraction | `extraction/listing*.py` |
| Detail harvest | `extraction/pipeline.py`, `extraction/collectors/` |
| Product/variant/offer/asset graph | `extraction/entities.py`, `extraction/targeting.py` |
| Product and variant identity correlation | `core/records/product_identity.py`, `core/records/variant_identity.py`, `extraction/entities.py` |
| Detail title display normalization (site-name suffix, marketplace prefixes, trademark notation) | `core/records/title_normalization.py` |
| Product attribute value normalization (identifier labels, GTIN digits, schema.org enums, audience gender from URL path) | `core/records/attribute_normalization.py` |
| JSON-LD product-level fact emission (identity, images, attributes, aggregateRating) | `extraction/collectors/jsonld_attributes.py` |
| JSON-LD offer and price-specification fact emission | `extraction/collectors/jsonld_offer_facts.py` |
| JSON-LD selected-root and sole-offer target ownership | `extraction/collectors/jsonld_targeting.py` |
| Detail publish/suppress policy | `extraction/publication_policy.py` |
| Fact resolution | `extraction/resolution/` |
| Findings and publication | `extraction/validation.py`, `result_building.py`, `publication.py` |
| Public field coercion | `core/shared/field_coerce*.py` |
| URL-result artifacts | `persistence/url_result_artifacts.py` |
| Public record/export shaping | `persistence/record_artifacts.py`, `record_export_service.py`, `persistence/export/` |
| Domain execution profiles | `crawl/profile/` |
| Selector execution | `core/records/selectors_runtime.py` |
| Run report and diagnosis | `observability/run_report.py`, `observability/diagnose.py` |

## Ambiguous backend basenames

| Name | Meaning |
| --- | --- |
| `contracts.py` | acquisition attempt contracts, crawl DTOs, extraction contracts, or persistence artifact references; use the subsystem path |
| `extraction_memory.py` | config vocabulary, ORM models, or persistence repository; use `core/config/`, `models/`, or `persistence/` |
| `service.py` | crawl lifecycle, enrichment jobs, or Product Intelligence jobs |
| `types.py` | acquisition fetch state, LLM results, or crawl pipeline types |

## Frontend ownership

All paths below are relative to `frontend/`.

| Concern | Canonical owner |
| --- | --- |
| Bootstrap, route registry, guards, error boundary | `src/app/`, `src/main.tsx` |
| HTTP transport and query client | `src/api/` |
| Domain endpoint modules and DTOs | `lib/api/` |
| Shell, sidebar, theme, session | `components/layout/` |
| UI primitives and operator patterns | `components/ui/` |
| Crawl Studio form and dispatch | `components/crawl/crawl-config-screen.tsx`, focused crawl hooks |
| Run workspace, polling, logs, records, exports | `components/crawl/crawl-run-screen.tsx`, `components/crawl/use-run-*` |
| Crawl settings/profile helpers | `lib/crawl/` |
| Dashboard and run history | `app/dashboard/`, `app/runs/` |
| Jobs and enrichment | `app/jobs/`, `app/data-enrichment/` |
| Product Intelligence | `app/product-intelligence/` |
| Domain profiles, selectors, cookies, graph contracts | `app/domain-memory/`, `components/domain-memory/` |
| API keys and MCP setup | `app/api-access/` |
| User and LLM administration | `app/admin/users/`, `app/admin/llm/` |
| Global tokens/reset/animations | `app/globals.css` |
| Browser tests | `e2e/` |

## Tests

- Backend tests: `backend/tests/unit/`, `component/`, `services/`, `regression/`.
- Frontend tests: colocated `*.test.ts(x)` plus `frontend/e2e/`.
- Shared test vocabulary may live in clearly named `*_test_support.py` or test-support TSX modules; assertions remain in collected test files.
- Local scope is selected by `scripts/validation.json`. GitHub CI owns full suites.

## Routing rules

- Behavior or output semantics: `BUSINESS_LOGIC.md`, then the owning implementation.
- Hard runtime/engineering rule: `INVARIANTS.md`.
- Backend implementation detail: `backend-architecture.md`.
- Frontend implementation detail: `frontend-architecture.md`.
- File ownership or moves: this map.
- Plans and historical audits are not ownership sources.
