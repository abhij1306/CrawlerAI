# Plan: MCP Server And Public API

**Created:** 2026-05-20
**Agent:** Codex
**Status:** DONE
**Touches buckets:** API + Bootstrap, Crawl Ingestion + Orchestration, Domain Memory, Config, Docs

## Goal

Expose a lightweight public HTTP API and HTTP MCP surface that can run on one small server without browser rendering, Celery workers, Redis, or scheduled watch infrastructure. Done means external developers can create/revoke API keys, call HTTP-only single-product extraction, inspect domain readiness, and use MCP tools (`extract_product`, `check_domain`, `list_capabilities`) through the same public API contract. Delta/watch APIs stay queued behind the active Agentic Delta Engine plan and are not part of the lightweight public launch.

## Lightweight Public Launch Constraints

- Public API v1 must run in a single FastAPI process plus Postgres.
- Public API v1 must not require Celery, Redis, Playwright, browser workers, scheduler loops, or webhook workers.
- Public extraction must force HTTP-only acquisition for public requests. Do not silently fall back to browser.
- Allowed extraction evidence for public launch: adapters, structured HTML sources, JSON-LD, microdata, OpenGraph, embedded JS state already present in fetched HTML, and cached DOM selectors that work from HTTP HTML.
- If a URL requires rendering or background execution, return a structured `BROWSER_REQUIRED` or `WORKER_REQUIRED` error.
- `options.max_wait_seconds` for public extraction is capped by config, target default 10 seconds.
- Batch extraction, watches, scheduled polling, and webhook dispatch are deferred. Routes may return structured `NOT_IMPLEMENTED` only if needed for forward-compatible docs.
- MCP must be HTTP-facing for hosted use and must call the public API. It must not import crawl, monitor, or extraction services directly.

## Verified Repo Facts At Plan Creation

- `backend/app/main.py` registers legacy routers directly. No `/api/v1` router exists.
- `backend/app/core/dependencies.py` has JWT/cookie/Bearer auth via `get_current_user`; no API-key dependency exists yet.
- `backend/app/models/api_key.py` already exists in the dirty worktree and is exported from `backend/app/models/__init__.py`; migration `backend/alembic/versions/20260520_0006_agentic_delta_engine.py` creates `api_keys`.
- `backend/app/models/monitor.py`, `backend/app/schemas/monitor.py`, and `backend/app/services/config/monitor_settings.py` already contain dirty Delta Engine/watch fields such as `condition`, `webhook_url`, `poll_interval_seconds`, `last_known_values`, `condition_met`, `MonitorWebhookDelivery`, and watch constants.
- `docs/plans/agentic-delta-engine-plan.md` is still `IN PROGRESS` and unverified. Treat watch business logic as a dependency, not complete.
- Existing console monitor API is `backend/app/api/monitors.py` at `/api/monitors`; public watch API is deferred until Delta Engine is complete and verified.
- Existing run creation path is `create_crawl_run_from_payload()` in `backend/app/services/crawl/ingestion_service.py`; monitor scheduler already uses it. Lightweight public extraction must not rely on asynchronous dispatch. Use the same crawl/pipeline semantics inline or add a narrow public extraction service wrapper that creates a run and processes one URL in-process.
- Existing extraction run records are `CrawlRun` and `CrawlRecord` in `backend/app/models/crawl_run.py`; public extraction responses should read persisted `CrawlRecord.data` after a normal run completes.
- Existing domain memory models are `DomainMemory` and `DomainRunProfile` in `backend/app/models/domain_memory.py`; domain-readiness API should query these owners, not acquisition internals.
- Existing app-level rate limiter in `backend/app/main.py` is IP keyed and returns only `Retry-After`; public API needs API-key scoped buckets and `X-RateLimit-*` headers.
- Tests live under `backend/tests`; relevant current tests include `test_health_api.py`, `test_monitors_api_e2e.py`, `test_monitoring_pipeline.py`, `test_crawl_service.py`, `test_crawl_schemas.py`, and `test_records_api.py`.

## Acceptance Criteria

- [x] `/api/v1/*` responses use the spec envelope: success `{status,data,meta}` and error `{status,error,meta}`.
- [x] API key auth accepts `Authorization: Bearer <api_key>` for `/api/v1/*`, maps to an active user, updates `last_used_at`, and rejects missing/inactive/invalid keys with structured errors.
- [x] Public API rate limits are keyed by API key, not IP, and return `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and `X-RateLimit-Reset` on every `/api/v1/*` response.
- [x] `POST /api/v1/extract` runs HTTP-only single-URL ecommerce detail extraction, waits up to the configured public timeout, and returns typed product fields from persisted public `CrawlRecord.data`.
- [x] `POST /api/v1/extract` rejects non-HTTP(S) URLs, unsupported surfaces, bad field names, and overlong timeouts with stable machine error codes.
- [x] Public extraction never starts browser rendering, scheduler work, Celery tasks, or webhook work.
- [x] Public extraction returns `BROWSER_REQUIRED`, `WORKER_REQUIRED`, `TIMEOUT`, `EXTRACTION_FAILED`, `INVALID_SURFACE`, or `URL_UNREACHABLE` through the standard error envelope when applicable.
- [x] Batch extraction endpoints are deferred or return structured `WORKER_REQUIRED`; they do not create workers in the lightweight launch.
- [x] `GET /api/v1/domains/{domain}` returns known/surface/last crawled/selector/acquisition-profile metadata from existing domain memory and crawl records.
- [x] Public watch endpoints are deferred until the active Agentic Delta Engine plan is verified.
- [x] HTTP MCP server is stateless: it reads `CRAWLERAI_API_KEY` and `CRAWLERAI_API_BASE_URL`, calls `/api/v1`, and returns structured tool results/errors for `extract_product`, `check_domain`, and `list_capabilities`.
- [x] OpenAPI exposes `/api/v1` schemas and documents machine error codes.
- [x] Focused required tests passed; full suite intentionally skipped by user request.

## Do Not Touch

- `detail_extractor.py`, `listing_extractor.py`, `pipeline/*` extraction bodies — public API must reuse normal crawl/extraction semantics.
- `publish/*` and export cleanup — no downstream repair for public API shape.
- `MonitorJob`, watch routes, scheduler loops, webhook delivery, and polling behavior — deferred to Agentic Delta Engine.
- Celery worker topology, browser worker containers, Playwright runtime, Redis queue requirements, RDS/ECS production topology — out of lightweight public launch.
- OAuth/team-scoped tokens/ACP payment flows/SDKs — out of v1 scope.
- Jobs/content/automobile surfaces — v1 public extraction is ecommerce only.
- Existing dashboard JWT auth routes — API keys are additive for public API.

## Slices

### Slice 1: Plan Creation And Queue
**Status:** DONE
**Files:** `docs/plans/mcp-api-plan.md`, `docs/plans/ACTIVE.md`
**What:** Save this plan as queued future work. Keep Agentic Delta Engine as the active plan because Delta work is already under development and is a dependency for the MCP/API watch surface.
**Verify:** `Get-Content docs\plans\ACTIVE.md` keeps `docs/plans/agentic-delta-engine-plan.md` as Current and lists `docs/plans/mcp-api-plan.md` in Queue.

### Slice 2: API Key Auth And Public Envelope
**Status:** DONE
**Files:** `backend/app/models/api_key.py`, `backend/app/schemas/api_key.py`, `backend/app/services/api_key_service.py`, `backend/app/api/api_keys.py`, `backend/app/core/dependencies.py`, `backend/app/api/public/common.py`, `backend/app/main.py`, `backend/alembic/versions/20260520_0006_agentic_delta_engine.py` or a new follow-up migration, `backend/tests/services/test_public_api_auth.py`
**What:** Finish the existing dirty `ApiKey` foundation. Add secure key generation with one-time plaintext return, SHA-256 hash storage, prefix display, revoke/list endpoints for console/admin use, and `get_current_api_key_user` dependency. Add public envelope helpers and exception handlers for `/api/v1`. Keep all status/error strings, public timeout values, browser-disabled switches, and rate-limit constants in `app/services/config/*`; extend `runtime_settings.py` or create a focused public API config only if no existing config owner fits.
**Details:** API key format should include a recognizable prefix such as `cai_` only in generation/config, never as a validation hardcode inside routes. Store only hash and prefix. Do not decrypt because keys are not encrypted. `ApiKey.user_id=None` must fail public auth. API key auth should not accept dashboard JWTs on `/api/v1`.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_api_auth.py tests/services/test_health_api.py -q`

### Slice 3: API-Key Rate Limits
**Status:** DONE
**Files:** `backend/app/main.py`, `backend/app/services/config/runtime_settings.py`, `backend/app/api/public/rate_limit.py`, `backend/tests/services/test_public_api_rate_limit.py`
**What:** Add lightweight `/api/v1` rate limiting that runs after API-key resolution and before endpoint work. Extraction endpoints get 60/min with 10x burst for 5 seconds; domain/capability reads get a cheaper read bucket. Include `X-RateLimit-*` headers on success and error. Keep existing IP limiter behavior for non-public API unchanged.
**Details:** Use in-memory buckets like existing `CrawlerAppState`. Do not introduce Redis for launch. Public rate-limit key is `api_key.id`, not client IP. Public rate limiter must not leak raw key material into bucket keys or logs.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_api_rate_limit.py tests/services/test_health_api.py -q`

### Slice 4: HTTP-Only Single Extraction API
**Status:** DONE
**Files:** `backend/app/api/public/extract.py`, `backend/app/schemas/public_api.py`, `backend/app/services/public_api/extraction_service.py`, `backend/app/services/config/public_api.py` if needed, `backend/app/main.py`, `backend/tests/services/test_public_extract_api.py`
**What:** Implement `POST /api/v1/extract` by creating a normal single-URL `crawl` run with public settings that force HTTP-only acquisition and disable browser, traversal, LLM, screenshots, diagnostics-heavy capture, and worker-only paths. Before writing the endpoint, explicitly audit the inline extraction path for FastAPI async safety. If the route is `async def` and the reused extraction path contains blocking calls such as `requests.get`, `time.sleep`, synchronous DB work, or other sync I/O, run that path in a thread pool with `asyncio.run_in_executor` / FastAPI threadpool helpers, or make the route/service boundary sync-safe. Then execute the one URL inline inside the API process, load the first successful `CrawlRecord`, and shape `record.data` into the spec response.
**Details:** Map public `surface="ecommerce"` to internal `ecommerce_detail`. Preserve requested fields exactly; if omitted, use existing ecommerce detail defaults rather than inventing a new field set. Public settings must explicitly set fetch mode to HTTP-only using the existing nested settings contract. Do not call Celery or scheduler dispatch. Prefer an existing in-process run path if one exists; otherwise add a small `public_api/extraction_service.py` wrapper that reuses existing crawl creation and single-run processing primitives without new extraction logic. `options.use_cache` is a documented no-op in v1: accept it, ignore it silently, and do not add a `NOT_IMPLEMENTED_OPTION` error code for cache behavior. `crawl_method` comes from source trace/acquisition diagnostics when present, else `http` or `unknown`. Price must remain numeric if persisted numeric; do not parse/repair price in this service. If extraction diagnostics show browser/rendering required, return `BROWSER_REQUIRED`. Error mapping: bot block -> `BOT_BLOCK`, timeout -> `TIMEOUT`, no public record -> `EXTRACTION_FAILED`, target validation -> `URL_UNREACHABLE` or `INVALID_URL`.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_extract_api.py tests/services/test_crawl_service.py tests/services/test_records_api.py -q`

### Slice 5: Deferred Batch Contract
**Status:** DONE
**Files:** `backend/app/api/public/extract.py`, `backend/app/schemas/public_api.py`, `backend/tests/services/test_public_batch_extract_api.py`
**What:** Add only a forward-compatible batch endpoint contract for lightweight launch. It must return a structured `NOT_IMPLEMENTED` / `WORKER_REQUIRED` error and must not create Celery jobs, scheduler jobs, batch mapping tables, or background workers.
**Details:** Keep request validation for max URL count and schema shape if cheap. Do not add a durable batch table in this launch slice. This preserves API shape without creating infra spend.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_batch_extract_api.py -q`

### Slice 6: Public Domain Info API
**Status:** DONE
**Files:** `backend/app/api/public/domains.py`, `backend/app/services/public_api/domain_info_service.py`, `backend/app/schemas/public_api.py`, `backend/tests/services/test_public_domain_api.py`
**What:** Implement `GET /api/v1/domains/{domain}` from existing `DomainMemory`, `DomainRunProfile`, and recent `CrawlRun/CrawlRecord` rows.
**Details:** Normalize domain through `app.services.domain_utils.normalize_domain`. `known=true` if selector memory, run profile, or a prior completed crawl exists. `has_cached_selectors=true` only when `DomainMemory.selectors` has active selector entries for ecommerce detail. `acquisition_profile` maps from `DomainRunProfile.acquisition_contract`/fetch defaults: browser required if proven browser/rendering required; http preferred if profile exists without browser requirement; unknown otherwise. This endpoint is read-only and must not probe the target domain live.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_domain_api.py tests/services/test_domain_memory_service.py -q`

### Slice 7: Deferred Watch Contract
**Status:** DONE
**Files:** `backend/app/api/public/watches.py`, `backend/app/schemas/public_api.py`, `backend/tests/services/test_public_watch_api.py`
**What:** Keep public watch routes out of the lightweight launch unless a placeholder is needed for docs or MCP capability discovery. If routes are added, they must return structured `NOT_IMPLEMENTED` / `WORKER_REQUIRED` and must not create monitor jobs, scheduler loops, Celery jobs, webhook deliveries, or background pollers.
**Details:** Do not call `MonitorSchedulerService`. Do not mutate `MonitorJob`. Do not expose `watch_product`, `get_watch_status`, `cancel_watch`, or `list_watches` as active MCP tools until Agentic Delta Engine is complete and hosted worker infrastructure is approved.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_watch_api.py -q`

### Slice 8: Lightweight HTTP MCP Server
**Status:** DONE
**Files:** `backend/app/mcp_server/__init__.py`, `backend/app/mcp_server/config.py`, `backend/app/mcp_server/client.py`, `backend/app/mcp_server/server.py`, `backend/app/mcp_server/tools.py`, `backend/pyproject.toml`, `backend/tests/services/test_mcp_server.py`
**What:** Add a stateless hosted HTTP MCP server that exposes only lightweight launch tools and calls `/api/v1` through an authenticated HTTP client. Use `fastmcp` as the MCP server framework; it is built on the official Python `mcp` SDK and provides HTTP+SSE transport without hand-rolled JSON-RPC. Do not implement a custom JSON-RPC transport unless `fastmcp` proves unusable and that blocker is documented first.
**Details:** Env config: `CRAWLERAI_API_KEY` required, `CRAWLERAI_API_BASE_URL` default `https://api.crawlerai.com/api/v1`. Active tool mapping: `extract_product -> POST /extract`; `check_domain -> GET /domains/{domain}`; `list_capabilities -> local static capability response from config`. Deferred tools must be absent or return `WORKER_REQUIRED`, not silently pretend watches are available. MCP errors must carry API `code` and `message`; never return Python tracebacks. Add the dependency in `backend/pyproject.toml` during this slice rather than vendoring or copying protocol code.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_mcp_server.py -q`

### Slice 9: OpenAPI And Docs
**Status:** DONE
**Files:** `backend/app/main.py`, `docs/backend-architecture.md`, `docs/CODEBASE_MAP.md`, `docs/BUSINESS_LOGIC.md`, optional `docs/api/public-api.md`, optional generated OpenAPI artifact if project already stores one
**What:** Ensure FastAPI OpenAPI includes lightweight `/api/v1` request/response models and examples. Document public API auth, response envelope, rate limits, HTTP-only extraction, deferred batch/watch behavior, domain endpoint, MCP server setup, deployment assumptions, and error codes. Update canonical docs for any new files and behavior rules.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_api_auth.py tests/services/test_public_extract_api.py tests/services/test_public_watch_api.py tests/services/test_mcp_server.py -q`

### Slice 10: Full Verification And Closure
**Status:** DONE
**Files:** `docs/plans/mcp-api-plan.md`, `docs/plans/ACTIVE.md`
**What:** Run focused public API/MCP tests and required dependent tests. Full backend suite intentionally skipped by explicit user request.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_public_api_auth.py tests/services/test_public_api_rate_limit.py tests/services/test_public_extract_api.py tests/services/test_public_batch_extract_api.py tests/services/test_public_domain_api.py tests/services/test_public_watch_api.py tests/services/test_mcp_server.py tests/services/test_health_api.py tests/services/test_crawl_service.py tests/services/test_records_api.py tests/services/test_domain_memory_service.py tests/services/test_agentic_delta_engine.py -q`

## Doc Updates Required

- [x] `docs/backend-architecture.md` — add `/api/v1`, API key auth, HTTP-only public extraction, domain info, deferred watch/batch contracts, and lightweight HTTP MCP server notes.
- [x] `docs/CODEBASE_MAP.md` — add public API route/service/schema owners, API key service, and MCP server package.
- [x] `docs/BUSINESS_LOGIC.md` — document public API as HTTP-only adapter over normal crawl semantics, deferred watch behavior, and API-key rate-limit behavior.
- [x] `docs/INVARIANTS.md` — no update needed; public API uses existing extraction/watch invariants and adds no new shared runtime contract.
- [x] `docs/feature specs/mcp-api.md` — updated v1 narrowing for cache no-op, 10s cap, and deferred batch/watch behavior.

## Notes

- Slice 1 verification updated on 2026-05-20: `Get-Content docs\plans\ACTIVE.md` keeps Agentic Delta Engine active and lists this MCP/API plan first in Queue.
- This plan is queued future work. Agentic Delta Engine remains active because its watch capability is part of the MCP/API public surface.
- Updated for lightweight public launch on 2026-05-20: no browser render, no Celery workers, no Redis requirement, no scheduled watches, no webhooks, no active batch jobs in v1 launch.
- Public watch API depends on Agentic Delta Engine slices for condition evaluation, webhook delivery, and test polling. It stays deferred until that plan is complete and worker infrastructure is approved.
- `surface="ecommerce"` in the public spec maps to internal `ecommerce_detail` for product extraction and watches.
- MCP server must stay a client of the public REST API. If a proposed implementation imports crawl or monitor services directly into MCP tools, reject it.
- Do not add API-key strings, timeout numbers, field defaults, or error-code maps inside route files. Put them under `app/services/config/*`.
- Slice 4 must explicitly check FastAPI event-loop safety before inline extraction implementation. Blocking extraction work must not run directly inside an `async def` route.
- `options.use_cache` is accepted and silently ignored in v1. Document it as a no-op; do not add a dedicated cache-not-implemented error code.
- Slice 8 should use `fastmcp` on top of the official `mcp` SDK for HTTP+SSE transport. Do not hand-roll MCP JSON-RPC.
- Implementation completed on 2026-05-20 for Railway-style deployment: `backend/Procfile` includes `web` and `mcp` process types, public API v1 is single-process FastAPI + Postgres, and hosted MCP uses FastMCP over the public REST API.
- Verification passed on 2026-05-20: `.\.venv\Scripts\python.exe -m compileall app -q`.
- Verification passed on 2026-05-20: `.\.venv\Scripts\python.exe -m pytest tests/services/test_public_api_auth.py tests/services/test_public_api_rate_limit.py tests/services/test_public_extract_api.py tests/services/test_public_batch_extract_api.py tests/services/test_public_domain_api.py tests/services/test_public_watch_api.py tests/services/test_mcp_server.py -q` reported 11 passed.
- Verification passed on 2026-05-20: `.\.venv\Scripts\python.exe -m pytest tests/services/test_health_api.py tests/services/test_crawl_service.py tests/services/test_records_api.py tests/services/test_domain_memory_service.py tests/services/test_agentic_delta_engine.py -q` reported 43 passed.
- Verification passed on 2026-05-20: `uv run python -c "from app.mcp_server.server import build_server; server=build_server(); print(type(server).__name__)"` printed `FastMCP`.
- Full backend suite was not run by explicit user request.
