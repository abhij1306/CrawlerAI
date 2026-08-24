# Backend architecture

Current backend map. Keep it factual. Hard cross-cutting rules belong in
`INVARIANTS.md`.

## Stack and entrypoints

- FastAPI: `backend/app/main.py`
- Celery: `backend/app/core/celery_app.py`, `backend/app/tasks.py`
- Async SQLAlchemy and migrations: `backend/app/core/database.py`, `backend/app/core/migrations.py`, `backend/alembic/`
- Redis: `backend/app/core/redis.py`
- Acquisition: `backend/app/acquisition/`
- Deterministic extraction: `backend/app/extraction/`
- Persistence and artifacts: `backend/app/persistence/`
- Run orchestration: `backend/app/crawl/`

Extraction is deterministic first: adapter, structured source, then DOM. LLM is
opt-in; ecommerce detail uses it only to adjudicate grounded evidence.

## API ownership

Routers are registered in `app/main.py`:

| Surface | Owner |
| --- | --- |
| auth, users, dashboard | `app/api/auth.py`, `users.py`, `dashboard.py` |
| crawl creation/control/logs/records | `app/api/crawls.py`, `records.py`, `run_access.py` |
| domain profiles, recipes, selector learning, cookie memory | `app/api/crawl_domain.py` |
| review and artifacts | `app/api/review.py` |
| selectors | `app/api/selectors.py` |
| Knowledge Graph | `app/api/knowledge.py` |
| LLM administration | `app/api/llm.py` |
| enrichment and product intelligence | `app/api/data_enrichment.py`, `product_intelligence.py` |
| API keys and public extraction | `app/api/api_keys.py`, `app/connectors/public_api/`, `app/api/public/` |
| jobs, health, metrics | `app/api/jobs.py`, `app/main.py`, `app/core/metrics.py` |

`/api/api-keys` serves the `/api-access` console and keys authenticate `/api/v1`.
`GET /api/crawls/{run_id}/export/discoverist` is an external contract.

## Runtime flow

```text
API -> crawl/ingestion_service.py -> crawl/crud.py/service.py
    -> local dispatcher or Celery -> crawl/batch_runtime.py
    -> acquisition -> extraction -> persistence/artifacts -> run summary
```

`crawl/batch_runtime.py` owns URL-level orchestration. Each URL uses an owned
SQLAlchemy session. A URL failure rolls back its transaction, records diagnostics,
and does not poison later URLs. Mixed-result runs remain exportable.

`category_discovery.py`, `sitemap_resolver.py`, and `site_link_discovery.py` discover
URLs; they do not create crawl records directly.

## Crawl settings

Request schemas are in `app/schemas/crawl.py`; stored models/views are in
`app/models/crawl_settings.py` and `crawl_settings_views.py`.

Execution shaping uses nested `fetch_profile`, `locality_profile`, and
`diagnostics_profile`. Other important settings are proxy endpoints, timeout, delay,
robots policy, URL concurrency, explicit traversal mode, `max_records`,
`llm_enabled`, extraction contract, and runtime/config snapshots. `max_records` is a
traversal stop target, not a database row cap. Quick and Advanced modes are UI-only.

Single-URL defaults resolve as generic UI defaults, saved `DomainRunProfile` values,
explicit user edits, then backend normalization/snapshotting. Per-URL acquisition
contract reuse resolves as explicit settings, saved `(domain, surface)` profile, then
defaults. Saved profiles contain execution defaults only: no selectors, proxy secrets,
LLM config/budgets, requested fields, cookies, auth state, or user identity.

## Acquisition and browser runtime

Ownership is in `app/acquisition/`:

- `acquirer.py`, `executor.py`: coordination
- `runtime.py`, `http_client.py`: shared HTTP clients and bounded fallback
- `browser_runtime.py`, `browser_pool.py`, `browser_page_flow.py`: browser lifecycle
- `browser_fetch_runner.py`, `browser_stage_runner.py`: browser stages
- `traversal.py` and `traversal_*`: explicit listing traversal
- `cookie_store.py`, `run_cookie_storage.py`, `cookie_http_export.py`: cookie state
- `policy.py`, `policy_middleware.py`: acquisition policy

HTTP is shallow: one curl attempt, one HTTPX fallback, then browser escalation only
when policy/evidence and budget allow. Shared HTTP clients carry no persistent cookie
state. Redirect-chain cookies are per-call. Browser-to-HTTP handoff is sanitized and
origin-scoped.

Browser contexts reload engine-scoped per-run storage first, then filtered
engine-scoped domain cookie memory. `chromium`, `patchright`, and `real_chrome` do
not replay each other’s cookies/localStorage. Challenge-only bot-defense state is
dropped; blocked runs do not write domain memory or snapshots. Storage snapshots are
encrypted and bound to user, run, and engine. Proxy persistence stores credential-free
endpoints plus encrypted secret references.

Traversal is explicit. The shared browser runtime is Patchright; native Chrome is an
explicit escalation lane when configured and available.

## Extraction and persistence

Extraction ownership is in `app/extraction/`:

- `engine.py`, `pipeline.py`, `cascade.py`: orchestration and tier order
- `adapters.py`, `documents.py`, `json_walk.py`: source parsing
- `listing.py`, `listing_records.py`, `listing_tier0.py`: listing extraction
- `entities.py`, `field_states.py`, `targeting.py`: field/entity state
- `validation.py`, `result_building.py`, `publication.py`: validation and output
- `contracts.py`, `surfaces.py`: typed contracts and surface rules
- `replay.py`, `sentinel.py`: controlled replay and regression support

Acquisition produces evidence; extraction consumes it. Missing fields continue through
all applicable deterministic tiers before any explicitly enabled surface-specific LLM
path. Ecommerce-detail LLM is adjudication-only and never invents field or variant data.
Persist source trace, provenance, and artifact references with results.

Persistence ownership is in `app/persistence/`: URL results, record artifacts,
diagnostic manifests, extraction-memory observations/releases, and export projections.
Data enrichment (`app/enrichment/`) reads persisted ecommerce detail records and writes
enrichment rows. Product intelligence (`app/intelligence/`) owns discovery, candidate
jobs, matching, and review.

## Configuration, security, operations

Runtime configuration is centralized in `app/core/config/`; services do not own
tunables or secrets. Auth/security owners are `app/core/security.py`,
`dependencies.py`, `public_auth.py`, `rate_limit.py`, and `url_safety.py`.

Browser sessions use an HttpOnly access cookie and signed double-submit CSRF cookie;
unsafe cookie-authenticated requests require allowed exact Origin (or Referer fallback)
and matching `X-CSRF-Token`. Bearer requests do not use this cookie CSRF contract.
Forwarded identity is trusted only from configured proxy peers. Public API traffic is
rate-limited before key lookup and again per key.

Outside development, interactive API docs are disabled, metrics require bearer auth,
startup rejects unsafe placeholder database/Redis/frontend endpoints, and bootstrap
creates only a new identity through the one-off `bootstrap_admin.py` flow.

Container roles are separate: migration, create-only bootstrap, API, worker, and beat.
Production images run non-root with locked dependencies and no build toolchain.

## Testing

Backend tests are under `backend/tests/` (`unit`, `component`, `services`, `regression`).
Architecture and contract checks include `tests/unit/test_extraction_architecture.py`.
Use the repository validation script for affected local checks; GitHub CI owns full
backend, integration, and E2E suites. Do not document a local full-suite requirement.

Companion docs: [INVARIANTS.md](INVARIANTS.md), [BUSINESS_LOGIC.md](BUSINESS_LOGIC.md),
[CODEBASE_MAP.md](CODEBASE_MAP.md), and [frontend-architecture.md](frontend-architecture.md).
