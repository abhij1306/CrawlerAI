# Invoro

**AI commerce intelligence platform for deterministic extraction, review, monitoring, and agent-ready export**

[![Python](https://img.shields.io/badge/Python-3.12%2B-blue?logo=python)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20%2B-green?logo=node.js)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.116%2B-009688?logo=fastapi)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16%2B-black?logo=next.js)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15%2B-4169E1?logo=postgresql)](https://www.postgresql.org/)
[![Redis](https://img.shields.io/badge/Redis-7%2B-DC382D?logo=redis)](https://redis.io/)
[![License](https://img.shields.io/badge/License-AGPLv3-blue.svg)](LICENSE)

</div>

Invoro extracts structured data from ecommerce, job, content, article, forum-thread, and tabular targets. It prefers deterministic evidence first: platform adapters, structured sources, JS state, network payloads, and DOM selectors. LLM calls are optional backfill only.

## Features

| Area                   | What it does                                                                                                                                        |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| HTTP-first acquisition | Starts with `curl-cffi`, escalates to Patchright/Playwright only when blocking, hydration, or browser-only content requires it.                     |
| Tiered extraction      | Runs `adapter -> structured source -> JS state -> DOM -> confidence scoring -> optional LLM gap fill`.                                              |
| Surface-aware crawling | Supports ecommerce, jobs, content pages, article feeds/pages, forum threads, and tabular surfaces.                                     |
| Domain memory          | Stores reusable run profiles, cookie state, learned selectors, acquisition evidence, and field feedback by normalized `(domain, surface)`.          |
| Review workflow        | Lets operators inspect crawl records, artifact HTML, selector candidates, field winners, and promote domain selectors.                              |
| Exports                | Produces JSON, CSV, artifact bundles, and Discoverist-style exports from persisted crawl records.                                                   |
| Product Intelligence   | Discovers matching products, scores candidates, launches candidate crawls, reviews matches, and can create monitors from accepted jobs.             |
| Data enrichment        | Builds ecommerce enrichment jobs from persisted detail records with deterministic taxonomy, attribute, and pricing normalization.                   |
| Product monitors       | Schedules recurring crawl runs, diffs tracked fields, stores snapshots/events, and emits in-app notifications.                                      |
| Agentic Delta alerts   | Adds single-product price/availability alerts with sandboxed conditions, test polling, history, and webhook delivery logs.                          |
| Public API v1          | Exposes API-key authenticated extraction with auto/content/article/forum routing, domain lookup, capabilities, and alert endpoints under `/api/v1`. |
| MCP wrappers           | Provides a hosted FastMCP server for product extraction tools and a stdio alert wrapper over public alert endpoints.                                |
| Orchestration          | Groups projects and workflows around normal crawl runs; current workflow supports competitive pricing snapshots and monitor promotion.              |
| UCP audit              | Runs deterministic UCP compliance audits, stores report artifacts, and exports JSON/Markdown repair roadmaps.                                       |
| Observability          | Uses structured logs, correlation IDs, health checks, Prometheus metrics, run logs, and artifact capture.                                           |

## Architecture

Core runtime flow:

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
  -> Review, enrichment, monitors, alerts, API, and MCP
```

## Tech Stack

| Layer         | Tools                                                                              |
| ------------- | ---------------------------------------------------------------------------------- |
| Backend API   | FastAPI, Uvicorn, Pydantic v2, SQLAlchemy 2, asyncpg, Alembic                      |
| Workers       | Celery, Redis                                                                      |
| Acquisition   | `curl-cffi`, Patchright/Playwright                                                 |
| Extraction    | BeautifulSoup4, selectolax, lxml, extruct, JMESPath, glom                          |
| Frontend      | Next.js 16, React 19, Tailwind CSS v4, Radix UI, TanStack Query, Recharts, Zustand |
| Testing       | pytest, Vitest, Playwright, MSW                                                    |
| Observability | structlog, prometheus-client                                                       |

## Prerequisites

- Python 3.12+
- Node.js 20+
- PostgreSQL 15+
- Redis 7+

## Quickstart

```powershell
cp .env.example .env
```

Edit `.env` before first run. Minimum local values:

| Variable                                              | Required | Default/example                                                   | Notes                                              |
| ----------------------------------------------------- | -------- | ----------------------------------------------------------------- | -------------------------------------------------- |
| `DATABASE_URL`                                        | Yes      | `postgresql+asyncpg://postgres:postgres@localhost:5432/invoro`    | PostgreSQL database.                               |
| `REDIS_URL`                                           | Yes      | `redis://localhost:6379/0`                                        | Queue, scheduler, and cache dependency.            |
| `JWT_SECRET_KEY`                                      | Yes      | `replace-with-64-byte-random-secret`                              | Replace for real use.                              |
| `ENCRYPTION_KEY`                                      | Yes      | `replace-with-32-byte-minimum-secret`                             | Replace for real use.                              |
| `DEFAULT_ADMIN_EMAIL`                                 | Yes      | `admin@example.com`                                               | Bootstrap admin identity.                          |
| `DEFAULT_ADMIN_PASSWORD`                              | Yes      | `replace-with-strong-admin-password`                              | Replace before login.                              |
| `CELERY_DISPATCH_ENABLED`                             | No       | `false`                                                           | Keep `false` for simple local in-process runs.     |
| `LEGACY_INPROCESS_RUNNER_ENABLED`                     | No       | `true`                                                            | Lets local crawls run without Celery worker setup. |
| `ANTHROPIC_API_KEY`, `GROQ_API_KEY`, `NVIDIA_API_KEY` | No       | empty                                                             | Only needed for enabled LLM backfill tasks.        |

### Backend

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\pip install -e ".[dev]"
.\.venv\Scripts\python init_db.py
.\.venv\Scripts\python run_dev_server.py
```

API: `http://127.0.0.1:8000`

### Frontend

```powershell
cd frontend
npm install
npm run dev
```

UI: `http://127.0.0.1:3000`

### One-Shot Windows Start

```powershell
.\start.bat
```

## Main Routes

| Route                   | Purpose                                                                     |
| ----------------------- | --------------------------------------------------------------------------- |
| `/dashboard`            | Run summary, recent jobs, and metrics.                                      |
| `/crawl`                | Crawl Studio for single, batch, CSV, and review workflows.                  |
| `/product-intelligence` | Product discovery, candidate review, and monitor creation.                  |
| `/monitors`             | Recurring extraction monitors with events, history, snapshots, and exports. |
| `/alerts`               | Product price/availability alerts with optional webhooks.                   |
| `/projects`             | Orchestration projects and competitive pricing workflows.                   |
| `/ucp-audit`            | UCP compliance audit jobs and repair-roadmap exports.                       |
| `/admin/llm`            | Runtime LLM provider configuration, test connection, and cost log.          |
| `/admin/users`          | Admin user management.                                                      |

## API Surfaces

| Prefix                                         | Purpose                                                                             |
| ---------------------------------------------- | ----------------------------------------------------------------------------------- |
| `/api/crawls`                                  | Run creation, status, records, logs, domain recipes, and exports.                   |
| `/api/selectors`                               | Selector CRUD, suggestions, tests, and preview HTML.                                |
| `/api/review`                                  | Review payload, artifact HTML, and field mapping save.                              |
| `/api/data-enrichment`                         | Enrichment job creation and result lookup.                                          |
| `/api/product-intelligence`                    | Discovery, jobs, match review, and monitor creation.                                |
| `/api/monitors`                                | Monitor CRUD, run-now, events, history, snapshots, and exports.                     |
| `/api/alerts`                                  | Console-auth alert CRUD, test poll, history, and webhook deliveries.                |
| `/api/orchestration`                           | Projects, templates, workflow runs, promotion, and price comparison results.        |
| `/api/ucp-audit`                               | Audit job lifecycle and JSON/Markdown report export.                                |
| `/api/v1`                                      | API-key authenticated public extraction, domain, capabilities, and alert endpoints. |
| `/api/health`, `/health/live`, `/health/ready` | Health checks.                                                                      |
| `/api/metrics`                                 | Prometheus metrics.                                                                 |

## Public API and MCP

Create API keys in the UI or through `/api/api-keys`. Public routes use bearer auth:

```powershell
curl -H "Authorization: Bearer <api-key>" http://127.0.0.1:8000/api/v1/capabilities
```

Hosted MCP server:

```powershell
cd backend
$env:CRAWLERAI_API_KEY='<set-api-key-in-shell>'
$env:CRAWLERAI_API_BASE_URL='http://127.0.0.1:8000/api/v1'
.\.venv\Scripts\python.exe -m app.mcp_server.server
```

Alert stdio wrapper:

```powershell
cd backend
$env:CRAWLERAI_API_KEY='<set-api-key-in-shell>'
$env:CRAWLERAI_API_BASE_URL='http://127.0.0.1:8000/api/v1'
.\.venv\Scripts\python.exe -m app.mcp.alert_server
```

## Development

Backend checks:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Frontend checks:

```powershell
cd frontend
npm run lint
npm run test
npm run test:e2e
```

Use the smallest relevant check for local slices. Run broader smoke or acceptance checks when changing shared acquisition, extraction, persistence, monitor, or API behavior.

## Project Layout

```text
backend/
  app/
    api/              FastAPI route modules
    core/             app config, auth helpers, database, metrics, telemetry
    mcp/              stdio alert wrapper
    mcp_server/       hosted FastMCP wrapper over public API v1
    models/           SQLAlchemy models
    schemas/          Pydantic request/response schemas
    services/         acquisition, extraction, crawl, enrichment, monitors, alerts
  tests/              unit, integration, smoke, and acceptance tests

frontend/
  app/                Next.js App Router pages
  components/         shared UI and domain components
  lib/                API clients, types, utilities, state
  e2e/                Playwright tests

docs/
  INVARIANTS.md       hard runtime contracts
  CODEBASE_MAP.md     ownership map
  BUSINESS_LOGIC.md   user-visible rules and workflow semantics
  ENGINEERING_STRATEGY.md
  plans/              active and queued plan docs
```

## Engineering Rules

- Fix extraction defects upstream, not in publishers or exports.
- Keep runtime strings, thresholds, tokens, fields, and tunables in `backend/app/services/config/*`.
- Respect explicit user controls for surface, traversal, proxy, browser, and `llm_enabled`.
- Use LLMs only when both run settings and active config allow them.
- Reuse existing owners before adding new files or abstractions.

## Safety

Invoro is for educational and research use. You are responsible for target-site terms, robots.txt, rate limits, privacy law, copyright, and permission before crawling at scale.

## License

GNU Affero General Public License v3.0. See [LICENSE](LICENSE).
