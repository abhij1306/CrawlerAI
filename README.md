# CrawlerAI

**Deterministic commerce and jobs crawler with review, enrichment, and export workflows**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20%2B-green?logo=node.js)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?logo=postgresql)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7%2B-DC382D?logo=redis)](https://redis.io/)
[![License](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)

CrawlerAI extracts structured data from ecommerce and job targets. It prefers deterministic evidence first: platform adapters, structured sources, JS state, network payloads, and DOM selectors. LLM calls are opt-in backfill only.

## Features

| Area | What it does |
| --- | --- |
| HTTP-first acquisition | Starts with `curl-cffi`, escalates to Patchright/Playwright only when blocking, hydration, or browser-only content requires it. |
| Tiered extraction | Runs `adapter -> structured source -> JS state -> DOM -> confidence scoring -> optional LLM gap fill`. |
| Surface-aware crawling | Supports ecommerce listings/details and job listings/details. |
| Domain memory | Stores reusable run profiles, cookie state, learned selectors, acquisition evidence, and field feedback by normalized `(domain, surface)`. |
| Review workflow | Lets operators inspect crawl records, artifact HTML, selector candidates, field winners, and promote domain selectors. |
| Product Intelligence | Discovers matching product URLs, scores candidates, launches candidate crawls, and reviews matches. |
| Data enrichment | Builds ecommerce enrichment jobs from persisted detail records with deterministic taxonomy, attribute, and pricing normalization. |
| Public API v1 | Exposes API-key authenticated extraction, domain lookup, and capabilities under `/api/v1`. |
| Observability | Uses structured logs, correlation IDs, health checks, Prometheus metrics, run logs, and run trace diagnostics. |

## Architecture

```text
User/API request
  -> Crawl run settings
  -> Acquisition policy
  -> HTTP or browser fetch
  -> Extraction loop
     -> adapters
     -> structured sources
     -> JS state and network payloads
     -> DOM selectors
  -> Confidence scoring
  -> Optional LLM backfill
  -> Persist crawl records
  -> Review, enrichment, Product Intelligence, public API, and exports
```

## Quickstart

```powershell
cp .env.example .env
```

### Backend

```powershell
cd backend
uv sync --frozen --extra dev
.\.venv\Scripts\python init_db.py
.\.venv\Scripts\python run_dev_server.py
```

API: `http://127.0.0.1:8001`

### Logfire

Backend Logfire telemetry is opt-in and uses FastAPI, Celery, system-metrics,
and crawl-pipeline instrumentation. For local CLI authentication to the US
Logfire instance and project:

```powershell
cd backend
.\.venv\Scripts\logfire.exe --base-url='https://logfire-us.pydantic.dev' auth
.\.venv\Scripts\logfire.exe --base-url='https://logfire-us.pydantic.dev' projects use --org 'abhij1306' 'crawlerai'
```

Enable export with `LOGFIRE_ENABLED=true`. Containers, CI, and deployments must
provide the `LOGFIRE_TOKEN` secret. Keep `LOGFIRE_CAPTURE_HEADERS=false` unless
header capture is explicitly required and reviewed for sensitive data.
In the `abhij1306/crawlerai` Live view, filter by
`service_name = 'crawlerai-backend'`.

### Frontend

```powershell
cd frontend
vp install
vp dev
```

UI: `http://127.0.0.1:3001`

### Start everything

After the frozen backend and frontend installs exist, run from the repository root:

```powershell
.\start.bat
```

The script reuses healthy PostgreSQL/Redis endpoints, starts missing local Docker
services, applies migrations, then launches the API, frontend, and configured Celery
workers. CrawlerAI PostgreSQL is exposed on 5433; API and UI use 8001 and 3001.

## Main Routes

| Route | Purpose |
| --- | --- |
| `/dashboard` | Run summary, recent jobs, and metrics. |
| `/crawl` | Crawl Studio for single, batch, CSV, and review workflows. |
| `/runs` | Crawl run history. |
| `/product-intelligence` | Product discovery, candidate review, and batch crawl handoff. |
| `/data-enrichment` | Ecommerce enrichment jobs and results. |
| `/selectors` | Selector suggestion, testing, and review. |
| `/selectors/manage` | Domain memory and learned profile inspection. |
| `/run-trace` | Acquisition and extraction trace diagnostics. |
| `/admin/llm` | Runtime LLM provider configuration, test connection, and cost log. |
| `/admin/users` | Admin user management. |

## API Surfaces

| Prefix | Purpose |
| --- | --- |
| `/api/crawls` | Run creation, status, records, logs, domain recipes, and exports. |
| `/api/selectors` | Selector CRUD, suggestions, tests, and preview HTML. |
| `/api/review` | Review payload, artifact HTML, and field mapping save. |
| `/api/data-enrichment` | Enrichment job creation and result lookup. |
| `/api/product-intelligence` | Discovery, jobs, match review, and candidate crawl workflow. |
| `/api/jobs` | Active worker and queue visibility. |
| `/api/v1` | API-key authenticated public extraction, domains, and capabilities. |
| `/api/health`, `/health/live`, `/health/ready` | Health checks. |
| `/api/metrics` | Prometheus metrics. |

## Public API and MCP

Create API keys in the UI or through `/api/api-keys`. Public routes use bearer auth:

```powershell
curl -H "Authorization: Bearer <api-key>" http://127.0.0.1:8001/api/v1/capabilities
```

Hosted MCP server:

```powershell
cd backend
$env:CRAWLERAI_API_KEY='<set-api-key-in-shell>'
$env:CRAWLERAI_API_BASE_URL='http://127.0.0.1:8001/api/v1'
.\.venv\Scripts\python.exe -m app.mcp_server.server
```

## Development

During implementation:

```powershell
.\scripts\check.ps1 -Scope Backend
# or: .\scripts\check.ps1 -Scope Frontend
```

Before completion or push:

```powershell
.\scripts\check.ps1
```

The local static gate fixes and verifies formatting/lint, type checks, architecture, dependency and
dead-code policy, the exported backend-to-frontend OpenAPI contract, and LOC/complexity limits.
Run `.\scripts\test.ps1` separately for mapped affected tests. The pre-push hook runs the static
gate in non-mutating check-only mode.

Full suites are CI-only. Do not run the full backend suite locally. GitHub CI remains the exhaustive
authority for backend, frontend, strict API contract, build, measured coverage, and full E2E
validation through the stable `CI / Required` result.

## Project Layout

```text
backend/
  app/
    api/              FastAPI route modules
    core/             config, auth, database, rate limits, metrics, telemetry
    acquisition/      HTTP/browser acquisition, traversal, cookie state
    crawl/            run creation, profiles, orchestration, pipeline
    extraction/       evidence collection, resolution, publication
    persistence/      records, artifacts, exports, extraction memory
    enrichment/       on-demand derived product data
    intelligence/     product discovery and deterministic matching
    mcp_server/       hosted FastMCP wrapper over public API v1
    models/           SQLAlchemy models
    schemas/          Pydantic request/response schemas
  alembic/versions/   single clean-start baseline migration
  tests/              unit, integration, smoke, and acceptance tests

frontend/
  app/                page-level route views
  components/         shared UI and domain components
  lib/                API clients, types, utilities, state
  src/                Vite entry and router

docs/
  INVARIANTS.md       hard runtime contracts
  CODEBASE_MAP.md     ownership map
  BUSINESS_LOGIC.md   user-visible rules and workflow semantics
  backend-architecture.md
  frontend-architecture.md
  plans/              active and queued plan docs
```

## Engineering Rules

- Fix extraction defects upstream, not in publishers or exports.
- Keep runtime strings, thresholds, tokens, fields, and tunables in `backend/app/core/config/*`.
- Respect explicit user controls for surface, traversal, proxy, browser, and `llm_enabled`.
- Use LLMs only when both run settings and active config allow them.
- Reuse existing owners before adding new files or abstractions.

## Safety

CrawlerAI is for educational and research use. You are responsible for target-site terms, robots.txt, rate limits, privacy law, copyright, and permission before crawling at scale.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
