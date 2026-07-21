# CrawlerAI — Full-Stack Audit Report

**Date:** 2026-07-21 · **Commit:** `f2f8755` · **Scope:** backend (`backend/app`, 370 py files, ~96k LOC) + frontend (`frontend/{app,src,components,lib}`, 187 ts/tsx, ~26.5k LOC)
**Method:** 7 parallel read-only audit agents (backend: security, scalability, dead-code/duplication, maintainability; frontend: security, dead-code/duplication, maintainability/scalability). Every finding verified against source with file:line evidence. No code was modified.

---

## Executive Summary

CrawlerAI has **strong foundations**: Argon2id password hashing, pinned-HS256 JWT with token-version invalidation, HMAC-hashed API keys, per-route auth dependencies (verified on all 102 router-mounted API routes; the unauthenticated infrastructure/docs endpoints are covered in §1.13), a solid IP-filter in `url_safety.py`, strict TypeScript with zero `any`, a single well-built API transport, virtualized record tables, 1,726 backend + 138 frontend tests with zero skips.

The audit found **87 issues: 3 critical, 24 high, 38 medium, 21 low, 1 info** (counts derived from the numbered findings in §§1–7).

**The three things to fix first:**

1. **CRITICAL — SSRF via redirect following (backend security).** URL safety is validated once at crawl-creation; every fetch transport (httpx, curl_cffi, Playwright) then follows redirects without re-validating. A crawl URL that 302s to `169.254.169.254` or an internal service returns its content through records/exports. The otherwise-solid SSRF guard is fully bypassed.
2. **CRITICAL — O(N²) run-summary JSONB rewrite (backend scalability).** The full URL list + growing verdict list live in `result_summary` and are rewritten + re-read on every per-URL commit. A 10k-URL run generates ~10GB of UPDATE traffic; runs have no URL cap.
3. **CRITICAL — Celery redelivery can execute a run twice concurrently (backend scalability).** `acks_late` with no `visibility_timeout` configured (Redis default 3600s) equal to the 3600s hard task limit, plus no lease/idempotency guard (the `queue_owner`/`lease_expires_at` columns exist but are unused). Redelivery restarts the run from URL 1.

**Other headline items:**
- Raw crawled HTML served unsanitized as `text/html` from the authenticated API origin (2 endpoints) → XSS that can mint API keys (account takeover). No CSP anywhere.
- Frontend renders attacker-controlled crawled URLs as `<a href>` without scheme validation at 6 sites → click-triggered stored XSS (React 19 still renders `javascript:` hrefs).
- 182 confirmed dead backend symbols, including **88 of 257 runtime settings fields never read by any code** (operators set env vars that silently do nothing), 8 dead API routes, and 3 dead files. Frontend has 21 unused exports and a half-migrated Badge variant system.
- Config-placement violations: bot-vendor header tokens hardcoded in 3 acquisition files while `core/config/block_signatures.py` exists; match thresholds hardcoded in `intelligence/matching.py`.
- Browser session state (cookies + localStorage of crawled sites) stored **unencrypted** in JSONB and shared cross-tenant.
- Docs drift is real: `CODEBASE_MAP.md` lists 4+ nonexistent files; `INVARIANTS.md` cites deleted v1 architecture; `frontend-architecture.md` failed 5/5 spot checks.

---

## Severity Index

This index lists all 3 critical and all 24 high findings (entries 1–27). The remaining 38 medium, 21 low, and 1 info findings are numbered in §§1–7; totals everywhere in this report derive from those numbered findings.

| # | Severity | Area | Finding |
|---|----------|------|---------|
| 1 | CRITICAL | BE sec | Fetch transports follow redirects without re-validating targets (SSRF → cloud metadata/internal read) |
| 2 | CRITICAL | BE scale | Run-summary JSONB fully rewritten + re-read per URL — O(N²) DB traffic |
| 3 | CRITICAL | BE scale | Celery visibility_timeout unset; no lease guard — duplicate concurrent run execution |
| 4 | HIGH | BE sec | Raw crawled HTML served unsanitized as text/html from API origin (XSS → API-key takeover) |
| 5 | HIGH | BE sec | DNS-rebinding TOCTOU: validated IPs discarded, fetch re-resolves later |
| 6 | HIGH | BE sec | Playwright navigation/subresource SSRF — no host validation in route interception |
| 7 | HIGH | BE scale | Per-URL DB round-trip storm (~20–35 queries/URL; has_table introspection per profile load) |
| 8 | HIGH | BE scale | CPU-heavy selectolax analysis synchronous on event loop in hot HTTP path |
| 9 | HIGH | BE scale | DB pool (5+10/process) undersized vs designed concurrency (~17 connections/run) |
| 10 | HIGH | BE scale | PI/Enrichment jobs run as API-process BackgroundTasks; sequential candidate polling |
| 11 | HIGH | BE scale | Unbounded run inputs (no URL cap, no max_records cap, full CSV in memory + JSONB) |
| 12 | HIGH | BE dead | 88/257 CrawlerRuntimeSettings fields never read — dead config surface |
| 13 | HIGH | BE dead | 8 API routes with zero callers (incl. 2 deprecated aliases) |
| 14 | HIGH | BE dead | 48 confirmed dead module-level functions (~1.5–2k LOC) |
| 15 | HIGH | BE maint | `extraction/resolution/__init__.py` — 2,044-LOC god-package, ~50 functions |
| 16 | HIGH | BE maint | 4 god-object classes (21–29 methods; BrowserAttemptRunner worst) |
| 17 | HIGH | BE maint | Config-placement violations: bot-vendor tokens hardcoded in acquisition service code |
| 18 | HIGH | BE maint | Hardcoded match thresholds in intelligence/matching.py bypass config |
| 19 | HIGH | BE maint | Layering inversion: ORM models import from persistence/acquisition/extraction |
| 20 | HIGH | BE maint | api/knowledge.py: 625 LOC, 25 raw SQL statements, 6-item Any-tuple helper |
| 21 | HIGH | BE maint | Real circular dependency (record_extraction_stage ↔ extraction_loop) via 4 deferred imports |
| 22 | HIGH | FE sec | Crawled/search URLs rendered as href without scheme validation (6 sites) — click-XSS |
| 23 | HIGH | FE dead | Half-migrated Badge variant system: dead `badge-variants.ts` + 5th status taxonomy |
| 24 | HIGH | FE dead | Duplicate ConfirmDialog: two full parallel implementations, both live |
| 25 | HIGH | FE dead | Run-status/tone mapping duplicated across 5 independent tables |
| 26 | HIGH | FE maint | docs/frontend-architecture.md materially stale (5/5 spot checks wrong) |
| 27 | HIGH | FE maint | app/ai-visibility/page-view.tsx — 956-LOC untested god-page, wrong API layer |

(Remaining medium/low findings are listed per section below.)

---

## 1. Backend — Security

Audited ~70 files across auth, API keys, SSRF defenses, injection, secrets, web hardening, dependencies. Route-auth baseline: all 102 route handlers mounted via APIRouter under `app/api/` were programmatically checked for auth deps (only `/api/auth/login` and `/api/auth/register` are intentionally open). Outside that set, 4 infrastructure endpoints defined directly in `main.py` (`/health/live`, `/health/ready`, `/api/health`, `/api/metrics`) plus FastAPI's default `/docs` and `/openapi.json` are unauthenticated by design — see §1.13. JWT expiry enforcement and IP-filter encodings verified live in the project venv.

### 1.1 CRITICAL — SSRF: fetch transports follow redirects without re-validating targets
- **Files:** `acquisition/runtime.py:274-275,308,381-388`, `crawl/crud.py:75`, `core/url_safety.py`, `acquisition/fetch/planned_http.py`
- **Evidence:** `ensure_public_crawl_targets()` runs only at crawl creation (`crud.py:75`). Fetch path uses `follow_redirects=True` (httpx) and `allow_redirects=True` (curl_cffi) with no `url_safety` import anywhere in `acquisition/` except `internal_api_replay.py` and `variant_endpoint_expansion.py`. Only `sitemap_resolver.py` validates redirect chains — and only after the fetch.
- **Impact:** Any tenant points a crawl at a URL that 302s to `http://169.254.169.254/latest/meta-data/...`, `http://127.0.0.1:6379/`, or internal RFC1918 services; content is persisted and readable via records/exports/artifact preview. Cloud credential theft in a multi-tenant SaaS.
- **Fix:** Disable auto-redirects in fetchers; re-validate each `Location` with `validate_public_target()` before following; add connect-time IP filtering (custom httpx transport / egress firewall). **Effort: M.**

### 1.2 HIGH — Stored/reflected XSS: raw crawled HTML served unsanitized as text/html from the authenticated API origin; no CSP anywhere
- **Files:** `api/review.py:53-75` (`/{run_id}/artifact-html` → `HTMLResponse(artifacts.html)`), `api/selectors.py:186-235` (`GET /api/selectors/preview-html?url=...`, one-click), `crawl/review/__init__.py:102-114`, `core/records/selectors_runtime.py:58-64`, `main.py:271-282`
- **Impact:** Attacker page crawled by victim (or attacker-sent preview-html link) executes JS under the API origin. HttpOnly blocks cookie theft, but JS can call `POST /api/api-keys` which returns a **plaintext** API key → persistent account takeover surviving token expiry. `X-Frame-Options: DENY` does not stop direct navigation.
- **Fix:** Sanitize HTML (bleach/nh3) or serve previews with `Content-Security-Policy: sandbox` / `script-src 'none'` / separate origin; add app-wide CSP. **Effort: S.**

### 1.3 HIGH — SSRF DNS-rebinding TOCTOU
- **Files:** `crawl/crud.py:75`, `core/url_safety.py:56-142`, `acquisition/runtime.py:308,381`, `browser_page_flow.py:82`
- **Evidence:** `validate_public_target` returns `ValidatedTarget(resolved_ips=...)`; the only call site discards it. Fetch re-resolves DNS minutes later (queue/dispatch window). No IP pinning anywhere.
- **Fix:** Pin validated IPs into the fetch (`--resolve` equivalent / Playwright host-resolver-rules) or re-validate immediately before fetch and compare. **Effort: M.**

### 1.4 HIGH — Browser navigation SSRF via Playwright
- **Files:** `browser_page_flow.py:82`, `browser_route_blocking.py:15-29`, `browser_recovery.py:137`
- **Evidence:** `page.goto(url)` follows redirects natively; the only route handler blocks media/tracker resource types, never hosts/IPs. Crawled pages can embed subresources pointing at internal hosts (confused deputy).
- **Fix:** Intercept document requests, abort non-public targets; run browser fleet with egress blocked to link-local/RFC1918. **Effort: M.**

### 1.5 MEDIUM — Blind SSRF in robots.txt/sitemap fetching
- **Files:** `crawl/sitemap_resolver.py:224-225,421-422,519-556` (validates chain AFTER the redirected fetch), `crawl/robots_policy.py:162-167` (no validation at all)
- **Fix:** `follow_redirects=False`, validate each hop before requesting; one shared hardened redirect helper. **Effort: S.**

### 1.6 MEDIUM — Browser session state stored unencrypted at rest, shared cross-tenant
- **Files:** `models/domain_memory.py:33-44` (`storage_state` plaintext JSONB, no `user_id`), `acquisition/cookie_store.py:76-150`, `core/security.py:92-101` (Fernet used only for LLM keys)
- **Impact:** DB dump exposes live session tokens for every crawled domain; tenant A reuses clearance cookies captured during tenant B's crawl.
- **Fix:** Encrypt `storage_state` with existing `encrypt_secret`; scope rows by `user_id` or document the shared trust model. **Effort: M.**

### 1.7 MEDIUM — CSV formula injection in exports
- **Files:** `persistence/record_export_service.py:264-282,298-352`, `ai_visibility/exports.py:52-62`
- **Fix:** Prefix cells matching `^[=+\-@\t\r]` with `'` in one shared CSV helper. **Effort: S.**

### 1.8 MEDIUM — Unbounded upload/URL-list sizes
- **Files:** `api/crawls.py:196` (`await file.read()` no cap), `ingestion_service.py:62` (full CSV duplicated into settings JSONB), `crawl/utils.py:42-54`, `schemas/crawl.py:31` (`urls` no max_length)
- **Fix:** 5–10MB upload cap, URL-count cap, stop storing raw `csv_content`. **Effort: S.** (See also 2.6.)

### 1.9 LOW — Rate limiting is in-memory per-process
- **Files:** `main.py:97-113`, `core/rate_limit.py:35-64`, `api/public/rate_limit.py:42-113`
- **Impact:** Effective limit = configured × worker count; restart resets buckets (login brute-force: 10/min → 20/min at 2 workers).
- **Fix:** Move hot counters to Redis (already a dependency). **Effort: M.**

### 1.10 LOW — `validate_proxy_endpoint` dead; per-run proxies never validated; proxy creds plaintext in run settings JSONB
- **Files:** `core/url_safety.py:81` (zero call sites), `models/crawl_settings.py:137-166`, `schemas/crawl.py:570-589` (masking only on serialization)
- **Fix:** Validate user proxies at creation; encrypt/redact creds at rest. **Effort: S.**

### 1.11 LOW — WebSocket log stream: no Origin header check
- **Files:** `api/crawls.py:403-410`. Largely mitigated by SameSite=Lax cookie; Bearer path unbound.
- **Fix:** Reject handshakes with Origin outside `get_frontend_origins()`. **Effort: S.**

### 1.12 LOW — No password policy; `UserUpdate.role` unconstrained
- **Files:** `schemas/user.py:9-16`, `api/auth.py:80-102` (registration off by default)
- **Fix:** `min_length=12`; `role: Literal['admin','user']`. **Effort: S.**

### 1.13 LOW — Unauthenticated `/api/metrics`, `/docs`, health endpoints
- **Files:** `main.py:572-593` (`/health/live`, `/health/ready`, `/api/health`, `/api/metrics` defined directly on the app), `main.py:143` (FastAPI default `/docs` + `/openapi.json`). These sit **outside** the 102 router-mounted routes in this section's auth baseline — total unauthenticated surface = login, register, these 4 infra endpoints, and the docs pair. Recon value for a multi-tenant SaaS.
- **Fix:** Bind metrics to localhost/shared secret; `docs_url=None` outside dev. **Effort: S.**

### 1.14 LOW — Dependency hygiene
- passlib 1.7.4 unmaintained (legacy pbkdf2 fallback only, rehashes to Argon2id on login — minimal risk). uv.lock pins current (joserfc 1.7.3, cryptography 49.0.0, fastapi 0.139.2) but checked-out `.venv` is older — ensure deploys use `uv sync --locked`.

### 1.15 Verified non-issues (do not re-flag)
Raw SQL via `text()` uses bound params/module constants only; no subprocess/shell/eval/exec/pickle/unsafe-yaml anywhere; Celery JSON serializers only; artifact path traversal guarded (`is_relative_to`); proxy display redaction thorough; API keys HMAC-SHA256 + 256-bit entropy; JWT HS256-pinned with enforced exp and token_version; cookie HttpOnly+SameSite=Lax; root `.env` git-ignored; pagination same-origin enforced; internal API replay re-validates and forbids redirects.

---

## 2. Backend — Scalability & Performance

Deployment facts (docker-compose): worker `--concurrency=2` prefork, `REDIS_STATE_ENABLED=false`, single Postgres 15 + Redis 7. Defaults: `system_max_concurrent_urls=8`, DB pool 5+10 with 10s timeout, `job_max_wall_seconds=3600`, WS poll 250ms.

### 2.1 CRITICAL — Run-summary JSONB fully rewritten + re-read on every per-URL commit (O(N²))
- **Files:** `crawl/batch_runtime.py:273-280,387,490,612-619`, `crawl/pipeline/run_progress.py:108-122`, `models/crawl_run.py:157-161`
- **Evidence:** `resolved_url_list` + growing `url_verdicts` stored in `result_summary`; `update_summary` rebuilds the whole dict (entire JSONB dirty → full column rewrite per commit); `session.refresh(run)` re-reads it per URL.
- **Impact:** 10k URLs → ~1MB blob rewritten per URL ≈ **~10GB UPDATE traffic (+WAL) and ~10GB re-read per run**; 100k URLs (uncapped, see 2.6) stalls the run. Same blob serialized to frontend on every poll/WS snapshot.
- **Fix:** Move `resolved_url_list`/`url_verdicts` out of `result_summary` (side table or reconstruct from `crawl_url_results`); small fixed-size progress patches; throttle progress commits; replace per-URL `refresh` with status-only SELECT. **Effort: M.**

### 2.2 CRITICAL — Celery: no visibility_timeout; hard task limit == Redis default visibility (3600s); no lease/idempotency guard
- **Files:** `core/celery_app.py:40-51`, `tasks.py:47-50`, `core/config/runtime_settings.py:114`, `crawl/batch_runtime.py:574-576,607`, `models/crawl_run.py:92-99`
- **Evidence:** `acks_late=True` + no `broker_transport_options` → Redis default 3600s visibility == `job_max_wall_seconds=3600`. Redelivered task sees status RUNNING and reprocesses; `queue_owner`/`lease_expires_at`/`claim_count` columns exist but are **never read/written**; progress state constructed fresh → restart from URL 1.
- **Impact:** Duplicate concurrent execution (doubled target load, flapping commits); crash at URL 9000 of 10k restarts at URL 1. Raising the wall limit via env makes duplicates guaranteed.
- **Fix:** `visibility_timeout ≥ 2× job_max_wall_seconds`; implement claiming with the existing lease columns; skip completed URLs on re-entry. **Effort: M.**

### 2.3 HIGH — Per-URL DB round-trip storm (~20–35 queries/URL)
- **Files:** `crawl/pipeline/record_extraction_stage.py:85,236-238,256,432-434`, `persistence/extraction_memory.py:1008-1021`, `crawl/profile/repository.py:14-45`, `crawl/profile/acquisition_contract.py:158,187,286`, `crawl/pipeline/persistence.py:241`, `crawl/pipeline/runtime_helpers.py:50-51`, `crawl/pipeline/extraction_loop.py:516`
- **Evidence:** release payload loaded **twice** per URL (`session.get` + deepcopy each); `_has_domain_run_profiles_table` introspection query on every profile load (up to 4×/URL) plus 1–2 identical profile upserts; per-record `flush()`; per-log-event commits (~5–8/URL).
- **Impact:** 10k-URL run → ~200–350k queries, ~50–80k commits; ~70k queries pure redundancy. First DB CPU bottleneck at ~100 URL-RPS.
- **Fix:** Cache release payload + domain profile per run; cache has_table at process start; bulk record inserts; batch log writes into per-URL commit; debounce contract upserts. **Effort: M.**

### 2.4 HIGH — CPU-heavy HTML analysis synchronous on the event loop in hot HTTP path
- **Files:** `acquisition/runtime.py:308-321` (`analyze_html`, `_content_aware_http_blocked`, `resolve_platform_runtime_policy` in coroutine), `extraction/documents.py:194-270` (sha256 + LexborHTMLParser + visible_text walk + `lower()` copy), `acquisition/browser_readiness.py:689-694`
- **Impact:** 5–100ms event-loop block per HTTP fetch; one large page stalls all 8 in-flight URLs + DB awaits in the process. Browser paths already offload via `asyncio.to_thread` — HTTP path does not.
- **Fix:** Wrap in `asyncio.to_thread`; don't retain `html` + `lowered_html` + parser. **Effort: S.**

### 2.5 HIGH — DB connection pool undersized; parent session pins a connection idle-in-transaction
- **Files:** `core/config/__init__.py:134-137` (pool 5+10, 10s timeout), `crawl/batch_runtime.py:381-387`, `crawl/events.py:31,233-236`
- **Evidence:** Demand per process ≈ 1 parent + 8 URL sessions + 8 detached log writers = 17 > 15 capacity. Parent session opens txn via `refresh` then blocks in `asyncio.wait` (up to URL timeout).
- **Impact:** `QueuePool limit reached` TimeoutErrors at peak concurrency → per-URL failures; idle-in-transaction parent holds back vacuum for the run's wall time.
- **Fix:** Release parent txn before awaiting; size pool to (URL concurrency + log writers + margin); batch log inserts. **Effort: S.**

### 2.6 HIGH — Unbounded run inputs
- **Files:** `schemas/crawl.py:32` (`urls` no max_length; contrast `CategoryDiscoveryRequest` cap 50), `api/crawls.py:196`, `ingestion_service.py:62-63`, `models/crawl_settings.py:19-28,326-331` (`max_records` no maximum)
- **Impact:** 100k+ URL runs (multi-MB settings rows feeding 2.1); one traversal can extract unbounded records; large CSV fully buffered in API memory.
- **Fix:** Hard caps on URLs/run, upload size, `max_records`; store URL lists outside the run row. **Effort: S.**

### 2.7 HIGH — Product Intelligence / Data Enrichment jobs run as API-process BackgroundTasks
- **Files:** `api/product_intelligence.py:79`, `api/data_enrichment.py:48`, `intelligence/service.py:549-577,596-618`, `intelligence/service_support.py:279-302`, `enrichment/service.py:212-260,309`
- **Evidence:** Jobs run in uvicorn (die with process, stuck `running`); PI polls candidates **sequentially** (up to 30s each, 15 candidates/product → ~150 crawl runs per 10-product job); per-candidate summary = 3 COUNT queries; enrichment is classic N+1 (per-product `session.get` ×2 + commit + optional LLM call).
- **Fix:** Move to Celery; poll concurrently or drive off run-complete callbacks; batch-load with IN queries; grouped-count summary. **Effort: M.**

### 2.8 MEDIUM — Per-host pacing is per-process in-memory
- **Files:** `acquisition/rate_limiter.py:9-10`, `acquisition/policy_middleware.py:31`. Effective per-host rate = configured × process count; protected-host backoff not shared.
- **Fix:** Redis-backed per-host schedule (SET NX PX / Lua token bucket). **Effort: M.**

### 2.9 MEDIUM — WebSocket log stream polls DB every 250ms per client
- **Files:** `api/crawls.py:420-449`, `crawl/log_stream.py:31-41`, `core/config/runtime_settings.py:311`. 4 qps/client of join queries; 25 viewers = 100 qps on the API pool.
- **Fix:** Adaptive interval or Redis pub/sub push with DB backfill. **Effort: S.**

### 2.10 MEDIUM — Log caps bypassed when Redis state disabled (the compose default)
- **Files:** `crawl/events.py:118-119,225-228`, `core/config/__init__.py:50,92-93`. With `REDIS_STATE_ENABLED=false`, every info+ log row persists (INSERT+refresh+commit) — 50–100k rows per 10k-URL run; the 1000-row/run safety valve never applies.
- **Fix:** In-process fallback counter; drop per-row refresh. **Effort: S.**

### 2.11 MEDIUM — All per-URL asyncio Tasks created up front
- **Files:** `crawl/batch_runtime.py:354-359`. 100k URLs → 100–300MB of live Task objects for the run's lifetime.
- **Fix:** Worker-pool pattern (N consumers pulling from an index iterator). **Effort: S.**

### 2.12 MEDIUM — Public API-key auth: 2 SELECTs + UPDATE with COMMIT per request
- **Files:** `core/public_auth.py:48-77,90-114`, `main.py:155-199`. Same-row `last_used_at` write serializes concurrent same-key traffic.
- **Fix:** Cache validated principals (short TTL); throttle `last_used_at`; pass user via `request.state`. **Effort: S.**

### 2.13 MEDIUM — Per-record storage amplification (~3–4× record size)
- **Files:** `crawl/pipeline/persistence.py:229-239,412-452`. `data` + `raw_data` + `discovered_data` + `source_trace` (embeds page-level `browser_diagnostics` per record — 200× for a 200-record page).
- **Fix:** Move page-level diagnostics to `crawl_url_results`/diagnose.json; slim per-record trace. **Effort: M.**

### 2.14 MEDIUM — On-disk artifacts grow unboundedly; run deletion leaves them; no retention job
- **Files:** `persistence/url_result_artifacts.py:51-57`, `crawl/crud.py:172-179`, `acquisition/browser_capture.py:663-668`. ~0.5–2MB HTML per URL → 5–20GB per 10k-URL run on the shared volume; only the admin reset cleans up.
- **Fix:** Delete `runs/{run_id}/` on `delete_run`; beat-scheduled retention sweeper; sample `page.html` retention. **Effort: S.**

### 2.15 LOW — `_find_contract` full-table scan + per-template query
- **Files:** `persistence/extraction_memory.py:1316-1326`, `api/knowledge.py:539`. O(#templates) queries per lookup.
- **Fix:** Index contracts by id / single join. **Effort: S.**

### 2.16 LOW — Robots.txt fetch creates fresh httpx client per fetch
- **Files:** `crawl/robots_policy.py:162-167`. Cached per domain but no keep-alive reuse across domains.
- **Fix:** Reuse shared client. **Effort: S.**

**Verified positives:** `prefetch_multiplier=1`; browser pool semaphores; bounded network capture; 1MB diagnose.json cap; streaming exports; indexed record pagination; robots cache with single-flight; LLM cache TTLs; extraction/artifact I/O offloaded via `to_thread`; no `time.sleep`/sync-HTTP in async paths (one cookie-store sleep correctly wrapped).

---

## 3. Backend — Dead Code & Duplication

Method: vulture 2.16 (conf 60/80) + repo-wide grep verification of every candidate (backend/frontend/docs/scripts). **182 confirmed dead symbols, 26 suspected, 3 dead files, 15 duplicate blocks (~205 copy-pasted LOC).**

### 3.1 HIGH — 88 of 257 CrawlerRuntimeSettings fields never read anywhere
- **File:** `core/config/runtime_settings.py` (+ validator name-lists at lines 415-620)
- **Evidence:** zero repo-wide reads for e.g. `browser_connection_rtt_ms`, `block_min_html_length`, `auto_detect_surface`, `fingerprint_*` (10), `proxy_failure_*` (5), `llm_confidence_threshold`, `js_gate_phrases`, `worker_max_concurrent_jobs`. `PERFORMANCE_PROFILES` machinery (lines 23-37) effectively dead — its three profile outputs are never read.
- **Impact:** ~1/3 of documented operator tunables silently do nothing.
- **Fix:** Delete all 88 fields + validator string lists; wire or delete PERFORMANCE_PROFILES; scrub `.env.example`. **Effort: M.**

### 3.2 HIGH — 8 API routes with zero callers (incl. 2 deprecated aliases)
- **Files:** `api/crawls.py:292-307` (POST `/llm-commit`), `api/crawls.py:367-382` (POST `/cancel`, alias of `/kill`), `api/crawl_domain.py:95` (stacked-decorator alias), `api/dashboard.py:95-100` (`/metrics`), `api/knowledge.py:304-313,443-458`, `api/api_keys.py:47` (DELETE), `api/dashboard.py:79-92` (`/reset-data-enrichment`)
- Orphaned service wrappers kept alive only by these: `commit_llm_suggestions` (crawl/crud.py:318), `build_operational_metrics` (dashboard_service.py:451), `reset_data_enrichment` (dashboard_service.py:151).
- **Fix:** Delete 8 routes + 3 wrappers. **Effort: S.**

### 3.3 HIGH — 48 confirmed dead module-level functions (~1.5–2k LOC, 30 files)
- Includes: 8 unused accessors in `acquisition/platform_policy.py` (`browser_first_domains`, `platform_js_state_extractors`, …), `ensure_default_admin` (superseded by `bootstrap_admin_user`, main.py:124), `selector_payload_from_rules`, `shutdown_robots_policy`, `run_grounded_repair`, `reset_knowledge_graph`, dead helpers in `events.py`/`runtime_helpers.py`/`field_coerce.py` etc. (The full 48-symbol list with per-symbol grep evidence was verified during the audit session; representative sample quoted here.) No dynamic-dispatch risk found.
- **Fix:** Delete all 48; update CODEBASE_MAP descriptions. **Effort: M.**

### 3.4 MEDIUM — api/knowledge.py compat surface: 4/10 endpoints unwired; 2 test-only
- Live: GET `/sites`, GET `/contracts`, PUT `/contracts/{id}/selection`. Dead or test-only: `/graph`, `/contracts/{template_id}`, `/contracts/selector` (frontend client methods exist but are never called in production), `/entities/{id}`, DELETE `/sites/{domain}` (no refs at all), `/memory`, `/purge` (tests only). ~300 of 625 LOC serve no production caller.
- **Fix:** Delete `/entities/{id}` + DELETE `/sites/{domain}`; wire-or-delete the rest; delete 3 unused frontend client methods. **Effort: M.**

### 3.5 MEDIUM — `core/exceptions.py`: 12 of 14 exception classes never raised/caught
- Only `CrawlerConfigurationError` is used (`crawl/utils.py:20`). 8 dead leaves + 4 bases referenced only by dead leaves.
- **Fix:** Reduce to `CrawlerError` + `CrawlerConfigurationError`. **Effort: S.**

### 3.6 MEDIUM — 9 dead methods (5 on CrawlRun model)
- `models/crawl_run.py`: `is_terminal`, `can_transition_to`, `set_status`, `get_setting`, `update_settings` (zero call sites; real path is `transition_status`). Also `BatchRunProgressState.from_run`, `DocumentStore.artifact_ids`, `ArtifactRepository.reference_exists`, `CrawlRunSettings.has_llm_config_snapshot`.
- **Fix:** Delete all 9. **Effort: S.**

### 3.7 MEDIUM — 3 dead files + 2 test-only evaluation modules
- Dead: `core/config/detail_extraction_constants.py` (91 LOC), `core/shared/number_coerce.py` (10 LOC, duplicates `persistence/run_summary.py:4 as_int`), `mcp/__init__.py` (empty, name-collides with live `mcp_server/`).
- Suspected: `evaluation/baseline.py` (302 LOC; docs note it reads the wrong artifact filename) and `evaluation/llm_repair.py` (222 LOC) — referenced only by their own tests.
- **Fix:** Delete 3 files; wire-or-delete the evaluation pair. **Effort: S.**

### 3.8 MEDIUM — Hardcoded `CASCADE_*` flags keep legacy fallback branches permanently dead
- **Files:** `core/config/cascade.py:70-114` (all `Final[bool] = True`, not env-backed), `extraction/adapters.py:106-115,210-239`. Flag-OFF branches run only in monkeypatched tests; comments admit ON/OFF produce byte-identical records.
- **Fix:** Remove flags + legacy else-branches + toggle tests (or make them honest env config). **Effort: M.**

### 3.9 MEDIUM — Duplication: identical helpers copy-pasted 3×
- `_browser_context_timeout_seconds` identical at `browser_pool.py:654`, `browser_pool_page.py:190`, `browser_storage_state.py:27`; `_set_task_id` identical at `crawl/service.py:41`, `workers/celery_dispatcher.py:22`, `workers/local_dispatcher.py:28`; `_load_run_with_normalized_status` at `celery_dispatcher.py:35`, `local_dispatcher.py:111` + 0.90-similar at `crawl/service.py:149`.
- **Fix:** Hoist into `acquisition/browser_pool.py` / `workers/base.py`. **Effort: S.**

### 3.10 MEDIUM — Duplication: ai_visibility provider `execute()` boilerplate ×3 (~80 LOC)
- **Files:** `ai_visibility/anthropic.py:102-151`, `openrouter.py:85-139`, `gemini.py:153-190` (0.83 similarity; identical timeout/error-mapping/status-classify blocks).
- **Fix:** Extract shared `_execute_post()` provider-http helper. **Effort: S.**

### 3.11 MEDIUM — Duplication: product_intelligence ≡ data_enrichment parallel subsystems
- Identical 9-field JobResponse DTOs (`schemas/product_intelligence.py:72-83` ≡ `schemas/data_enrichment.py:27-38`), identical SourceRecordInput/JobCreate shapes, 6-column shared ORM core (`models/` pair). Every job-lifecycle change must be made twice.
- **Fix:** Shared `BaseJobResponse`/`BaseJobCreate` (optionally one jobs table with kind column). **Effort: M-L.**

### 3.12 LOW — 9 smaller copy-pasted helpers (~70 LOC)
- `should_escalate_to_browser_async` ×2, `_serialize_feedback_row` ×2, `_looks_like_locale_segment` ×2, `_pipeline_acquisition_event_logger` (0.98), `_emit_popup_event` ×2, `_record_timing` (0.90), `_RECOVERABLE_ERRORS` ×2, `_clean_str`-family ×4, `slug_tokens`/`_query_tokens`.
- **Fix:** Point each at a single owner module. **Effort: S.**

### 3.13 LOW — Dead constants/aliases/imports (9 symbols) + 5 dead Settings fields
- `AI_VISIBILITY_SYSTEM_INSTRUCTION` (dead alias), `ECOMMERCE_LISTING_HTML_ARTIFACT_IDS` (back-compat alias), `RECORD_NOT_FOUND_RESPONSE`, 5 dead constants in `field_coerce.py`, unused imports in `main.py:10`, dead attribute `browser_capture.py:114`. Settings: `backend_host`, `backend_port`, `acquisition_cache_dir`, `crawl_log_file_dir`, `browser_context_timeout_seconds` — all unread (still in `.env.example`).
- **Fix:** Delete; scrub env examples. **Effort: S.**

### 3.14 LOW — Suspected-dead: test-only routes/symbols
- Test-only routes: 3 record-export formats, `/api/selectors/summary`, `/api/ai-visibility/runs/{id}/executions`, POST+GET `/api/api-keys` (no frontend UI exists — whole key-management surface unexposed), 2 dashboard reset routes. Script-only `type_text_like_human` (used only by unreferenced smoke script).
- **Fix:** Wire into frontend/ops or delete route + test together. Keep public `/api/v1/*`, health, metrics — external by design. **Effort: M.**

---

## 4. Backend — Maintainability

Full-tree AST scans over all 370 app files + 134 test files; 48 files verified line-by-line. Largest files: `extraction/resolution/__init__.py` (2044), `persistence/extraction_memory.py` (1326), `extraction/collectors/dom.py` (1149), `extraction/engine.py` (1127), `core/config/extraction_rules/_detail.py` (1032). 10 files >800 LOC.

### 4.1 HIGH — `extraction/resolution/__init__.py`: 2,044-LOC god-package
- ~50 top-level functions; `resolve()` 160 lines; untyped dict-shaped signatures throughout. This is the semantic authority per INVARIANTS §3/§17 — every extraction change is review-hostile and merge-conflict-prone.
- **Fix:** Split by concern (variants/offers/lineage/decisions) alongside existing ranking/price_units/assets modules; add type aliases. **Effort: 2–3d.**

### 4.2 HIGH — 4 god-object classes (21–29 methods)
- `BrowserAttemptRunner` (29 methods, ~15 mutable state fields — proxy loop + engine attempts + budget + host policy + diagnostics), `CrawlRunSettings` (28), `SharedBrowserRuntime` (25), `HtmlNode` (21).
- **Fix:** Extract AttemptPlan/budget/diagnostics collaborators; split settings validators from normalization. **Effort: 2–4d per class.**

### 4.3 HIGH — Config-placement violations: bot-vendor tokens hardcoded in service code
- **Files:** `acquisition/runtime.py:71-81` (`_BOT_VENDOR_HEADER_MARKERS`: datadome/cloudflare/akamai/perimeterx), `acquisition/browser_recovery.py:305`, `acquisition/browser_block_detection.py:286-288` — while `core/config/block_signatures.py:43-167` already owns vendor markers. INVARIANTS §1 names exactly these as violation signatures.
- **Fix:** Move all into `block_signatures.py`. **Effort: 0.5d.**

### 4.4 HIGH — Hardcoded match thresholds bypass config
- **Files:** `intelligence/matching.py:253` (bare `0.45` GTIN gate while siblings use config constants; same number exists with different meaning at `config/product_intelligence.py:366`), `matching.py:423-427` (score_label cutoffs 0.85/0.60/0.40), `matching.py:554`.
- **Fix:** Add `MATCH_GTIN_MIN_TITLE_SIM` + label cutoffs to config; import. **Effort: 0.5d.**

### 4.5 HIGH — Layering inversion: ORM models import from persistence/acquisition/extraction
- **Files:** `models/crawl_run.py:33` (→ `persistence.run_summary`), `models/crawl_settings.py:9,12` (→ `acquisition.runtime_plan`, `extraction.surfaces`). Models are the bottom of the stack; this raises circular-import risk and makes models unsafe for tooling imports.
- **Fix:** Move helpers to core/ or call from service layer. **Effort: 1d.**

### 4.6 HIGH — api/knowledge.py fat API module
- 625 LOC, 25 raw SQL statements (peers have 0), `_memory_rows` returns `tuple[Any ×6]` (INVARIANTS §13 violation signature), 82-line handler assembling projections.
- **Fix:** Move query/projection helpers into `persistence/extraction_memory.py` returning a typed projection. **Effort: 1d.**

### 4.7 HIGH — Real circular dependency worked around by 4 deferred imports
- **Files:** `crawl/pipeline/record_extraction_stage.py:219,253,362,437` ↔ `extraction_loop.py:40`; second managed cycle `core/shared/field_coerce.py` ↔ `field_coerce_dispatch.py` (dynamic module-attribute reads).
- **Impact:** Import order is load-bearing; refactors can turn worker startup into ImportError; static analysis sees one direction only.
- **Fix:** Move the shared call surface into a third module; explicit registry for field_coerce. **Effort: 1–2d.**

### 4.8 MEDIUM — 52 `except Exception` handlers swallow errors (no raise, no log)
- 138 total; worst concentrations: `browser_recovery.py` (13; silent at :394,497,514,520,707,779), `core/listing_cards.py:181-265` (5 silent), `browser_detail.py:564-608`, `browser_accessibility.py:132,144`, `enrichment/service.py:235`. Zero bare `except:` (good).
- **Impact:** Failures in the hardest-to-debug crawl paths vanish without diagnostics — undermines INVARIANTS §10.
- **Fix:** Add context logging/diagnostics entries in the 52 sites. **Effort: 1d.**

### 4.9 MEDIUM — Docs drift: CODEBASE_MAP.md
- Bucket 6 lists 4 nonexistent files (`review/__init__.py`, `selector_auto_learn.py`, `selector_suggestions.py`, `selector_self_heal.py`); wrong paths (`selectors_runtime.py` → actually `core/records/`; `domain_memory_service.py` → actually `crawl/`); missing `test_site_sets/commerce_browser_heavy.json`; duplicate `crawls.py` rows; pipeline/publish path shorthand wrong.
- **Fix:** Rewrite Bucket 6; 1 hour. **Effort: XS.**

### 4.10 MEDIUM — Docs drift: INVARIANTS.md cites deleted v1 architecture
- §9 cites nonexistent `core/config/domain_memory.py`/`CONTRACT_STALE_FAILURE_COUNT` (live: `config/cascade.py:131`, `crawl/profile/acquisition_contract.py:26`); §3 names deleted files (`detail_extractor.py`, `backfill_detail_price_from_html`, `field_value_core.py`, `CandidateSet`).
- **Fix:** Update §9 owners; rewrite §3 signatures against v2 (harvest→resolve→publish). **Effort: 2–3h.**

### 4.11 MEDIUM — Near-zero behavioral coverage: enrichment, intelligence, workers, mcp_server
- 134 test files / 1,726 tests, but: enrichment=1 test file, intelligence=1, workers=0 behavioral (only file-existence assertion), mcp_server=1. `intelligence/matching.py` (749 LOC) and `enrichment/service.py` (760 LOC) encode core business rules.
- **Fix:** Component tests for the matching ladder + enrichment state transitions; dispatcher smoke test. **Effort: 2–3d.**

### 4.12 MEDIUM — 25 duplicate module basenames
- `contracts.py` ×5, `service.py` ×4, `types.py` ×3, `extraction_memory.py` ×3, `llm.py` ×3, `selectors.py` ×3; near-identical `config/selector_runtime.py` vs `core/records/selectors_runtime.py`.
- **Fix:** Rename worst pairs; canonical-owner notes in CODEBASE_MAP. **Effort: 0.5d.**

### 4.13 MEDIUM — Pipeline boundary stays dict-shaped despite `pipeline/types.py`
- `types.py:12-18` (`records: list[dict]`, `url_metrics: dict[str, Any]`), `persistence.py:138,328,171-456`; frozen extraction contracts drop to dict at the boundary. ~10% of 1,700 core-path functions missing hints (crawl/pipeline worst at 20%); 162 functions expose bare `Any` (124 in acquisition/).
- **Fix:** Typed PublicRecord at the RecordWriter boundary; tighten crawl/pipeline hints first. **Effort: 1–2d.**

### 4.14 LOW — Global autouse fixtures monkeypatch DNS/Redis/tempfile/storage for all 1,726 tests
- `tests/conftest.py:154,161,173,184,196`. Tests can't opt into real wiring; regressions in real storage/network paths invisible.
- **Fix:** Marker-gated/opt-in heavy patches. **Effort: 1d.**

### 4.15 LOW — 5 functions >150 lines
- `projection_field_states` (194, `extraction/result_building.py:321`), `commerce_detail_projection` (180, `extraction/publication.py:82`), `resolve` (160), `_acquire_browser_retry_result` (154, `retry/stage.py:135`), `_variant` (152, `collectors/jsonld.py:522`).
- **Fix:** Decompose by field family / decision tables. **Effort: 1–2d.**

**Verified non-issues:** zero bare excepts; zero skipped/xfail tests; curl_fetch correctly offloads; extraction/ doesn't import mutable extraction memory (§17 holds); single-writer artifact rule holds; most API modules thin (0 SQL outside knowledge.py).

---

## 5. Frontend — Security

Auth architecture verified sound: JWT in httpOnly SameSite=Lax cookie, frontend never touches it (zero `access_token` refs, no tokens in storage/URLs/WS params). No `dangerouslySetInnerHTML`/`innerHTML`/`eval`/`new Function` anywhere. `pnpm audit --prod` clean.

### 5.1 HIGH — Crawled/search-derived URLs rendered as href without scheme validation (6 sites) — click-XSS
- **Files:** `app/product-intelligence/product-intelligence-results.tsx:222,240` (`data.url` from extracted page content), `product-intelligence-candidate-card.tsx:81,176,208`, `app/data-enrichment/source-record-list.tsx:29`, `enriched-product-view.tsx:238`, `components/crawl/run-terminal-shell.tsx:35` + `app/runs/run-row.tsx:53` (defense-in-depth only — backend constrains run.url)
- **Evidence:** Correct guards exist elsewhere in the same codebase (`records-table.tsx:111 isSafeHttpUrl`, `run-page-status.tsx:22`). React 19 renders `javascript:` hrefs (dev warning only).
- **Impact:** A crawled page planting `"url": "javascript:..."` executes in the app origin on click with the victim's full session — can call every API incl. admin reset. Highest-risk surface for an app rendering attacker-controlled web data.
- **Fix:** Apply existing `isSafeHttpUrl()` (`lib/format/domain.ts:18`) at the 6 sites; shared `<SafeExternalLink>` component. **Effort: 0.5d.**

### 5.2 MEDIUM — CSV formula injection in client-side Product Intelligence export
- **Files:** `app/product-intelligence/product-intelligence-export.ts:60-73` (quotes escaped; `= + - @ tab CR` prefixes not neutralized; rows from crawled candidate data).
- **Fix:** Prefix-escape in `csvCell` + unit test. **Effort: S.**

### 5.3 MEDIUM — No logout capability (frontend UI or backend endpoint)
- **Files:** `components/layout/sidebar.tsx`, `app-shell.tsx` (zero `logout|sign-out` matches), `backend/app/api/auth.py:80-147` (only register/login/me). Cookie is httpOnly → JS can't clear it either.
- **Fix:** `POST /api/auth/logout` clearing cookie (+ bump token_version), sidebar button clearing React Query session cache. **Effort: M.**

### 5.4 MEDIUM — Live secrets in working-tree `.env` backing a public preview deployment
- **Files:** `/code/abhij1306/CrawlerAI/.env` (live JWT_SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD, DEFAULT_ADMIN_PASSWORD), `frontend/.env.local` (public preview origin whitelisted in FRONTEND_ORIGINS). Verified NOT git-tracked, no `.env` in history.
- **Fix:** Rotate all four for the preview environment; per-environment secrets; keep `BOOTSTRAP_ADMIN_ONCE=true`. **Effort: S.**

### 5.5 LOW — No CSP (or any security headers) on the SPA document
- **Files:** `frontend/index.html` (inline theme script needs hash/nonce), `vite.config.ts`. Backend headers cover API responses only; SPA served separately.
- **Fix:** CSP at the SPA serving layer: `default-src 'self'; img-src 'self' https: data:; script-src 'self' + hash; frame-ancestors 'none'`. **Effort: M.**

### 5.6 LOW — Crawled image URLs fetched without referrer policy on PI cards
- **Files:** `app/product-intelligence/product-intelligence-components.tsx:25-32` (no `referrerPolicy`, no scheme check; contrast correct `record-thumbnail.tsx:82`).
- **Fix:** `referrerPolicy="no-referrer"` + http(s) gate. **Effort: S.**

### 5.7 LOW — Raw backend error detail rendered in UI
- **Files:** `src/api/client.ts:113-119,184-203`, `app/login/page-view.tsx:28,67`. Rendered as text (no XSS) but no allow-list; 5xx internals can reach the DOM.
- **Fix:** Map status codes to friendly messages; keep 5xx bodies out of DOM. **Effort: S.**

### 5.8 Verified clean
Token storage, DOM-XSS sinks (HTML-string syntax highlighter is test-only; production uses createElement), storage contents (only UI prefs + prefill payloads), open redirects (all static paths), dependencies (`pnpm audit` clean; note nonstandard `vite: npm:@voidzero-dev/vite-plus-core` alias override — supply-chain watch item).

---

## 6. Frontend — Dead Code & Duplication

Import-graph trace from `src/main.tsx`: **164/164 non-test files reachable; all 12 app/ page-views routed.** No dead files or orphaned routes. Real problems: 21 confirmed unused exports, a half-migrated Badge variant system, 7 duplicate blocks (~300 LOC), 8 dead CSS rules, 1 unused devDep.

### 6.1 HIGH — Half-migrated Badge variant system (dead `badge-variants.ts` + variant machinery)
- **Files:** `components/ui/badge.tsx:41-44,49-63,100-108`, `components/ui/badge-variants.ts` (58 LOC)
- All 34 `<Badge>` call sites use legacy `tone`/`flat` props — the variant switch, 4 union arms, 10 re-exports (`statusBadge`, `runStatusBadge`, …) are unreachable. `runStatusBadge` uses a draft/queued/analyzing vocabulary matching nothing else — a 5th parallel status taxonomy and a trap for future developers.
- **Fix:** Migrate call sites to the variant API OR delete it. Half-migrated is the worst state. **Effort: S–M.**

### 6.2 HIGH — Duplicate ConfirmDialog (two live parallel implementations)
- **Files:** `components/ui/confirm-dialog.tsx:22-98` (native `<dialog>`, 1 call site: app-shell) vs `components/ui/dialog.tsx:124-197` (Radix, 3 call sites). Incompatible APIs, divergent a11y behavior.
- **Fix:** Port app-shell to the Radix version; delete `confirm-dialog.tsx`. **Effort: S.**

### 6.3 HIGH — Run-status/tone/label mapping duplicated across 5 tables
- Canonical: `lib/ui/status.ts` (live). Duplicates: `components/ui/history-drawer.tsx:17-25` (`STATUS_TONE_MAP`, missing paused/killed/proxy_exhausted → wrong 'neutral'), `app/ai-visibility/page-view.tsx:939-957` (local `statusTone` with invented 'cancelled'/'degraded'), `badge-variants.ts` (dead). Only the jobs page correctly reuses the canonical module.
- **Fix:** Generic `statusTone()` export in `lib/ui/status.ts`; delete local maps. **Effort: S.**

### 6.4 MEDIUM — 9 zero-reference exports (ts-prune verified)
- `card.tsx:56,68` (CardTitle, CardDescription), `field.tsx:79` (FieldProps), `input.tsx:27` (inputVariants/textareaVariants), `table.tsx:115` (TableProps), `tooltip.tsx:117` (TooltipProvider no-op), `src/api/ai-visibility.ts:137,149` (`getProject`, `deleteProject` — dead backend wrappers suggesting unwired features).
- **Fix:** Delete (or wire the two API wrappers); add knip/ts-prune CI gate. **Effort: S.**

### 6.5 MEDIUM — PrefillPayload DTO triplicated for the same sessionStorage handoff
- **Files:** `components/crawl/crawl-run-prefill.ts:5-14` (write side) vs `app/data-enrichment/data-enrichment-state.ts:6-9` and `app/product-intelligence/product-intelligence-utils.ts:22-27` (read sides). Divergent optionality; blind JSON.parse casts.
- **Fix:** Define once, import in readers, validate on read. **Effort: S.**

### 6.6 MEDIUM — Duplicate helpers with divergent behavior
- `surfaceLabel`: `crawl-config-logic.ts:145-157` vs `domain-memory/utils.ts:11-16` (different fallbacks). `parseOptionalClampedNumber`: `crawl-config-logic.ts:115-121` vs `domain-memory/utils.ts:192-197` (different NaN semantics — careless unification would change runtime behavior).
- **Fix:** Hoist to lib/, pick one semantic each. **Effort: S.**

### 6.7 MEDIUM — Unused devDependency: `msw`
- `package.json:51` — zero importers anywhere (tests stub fetch manually).
- **Fix:** Remove or adopt. **Effort: XS.**

### 6.8 LOW — Duplicate ActionButton components
- `app/jobs/page-view.tsx:187-215` vs `components/crawl/shared.tsx:135-151` (divergent danger styling for same semantics).
- **Fix:** Promote one to components/ui. **Effort: S.**

### 6.9 LOW — 8 dead CSS rules in `app/globals.css`
- `.code-block` (+print override), `.field-error`, `.field-hint`, `.field-label-required::after`, `.type-heading-1/2`, two `.bg-zinc-*` remnants — zero source references (field-* now Tailwind utilities).
- **Fix:** Delete ~60–80 lines. **Effort: S.**

### 6.10 LOW — Config rot
- `vite.config.ts` lint override targets nonexistent `src/routing/image.tsx`; `route-registry.ts:26` declares dead `'Memory'` nav-group (absent from `groupOrder` → a route assigned to it would silently never render).
- **Fix:** Delete both. **Effort: XS.**

### 6.11 INFO — Export modifiers on module-internal symbols
- `data-enrichment-state.ts:28,36` (INITIAL_STATE, reducer used only in-file). Cosmetic.

---

## 7. Frontend — Maintainability & Scalability

Health baseline: strict TS (`tsc --noEmit` clean, 0 explicit `any` in 22.3k non-test LOC), single fetch chokepoint (abort signals, request IDs, opt-in retry), 65 React Query call sites vs 1 hand-rolled page, virtualized records table, 138/138 unit tests passing, lazy routes + vendor chunking + bundle budgets. Largest files: `crawl-run-screen.test.tsx` (1416), `app/ai-visibility/page-view.tsx` (956), `components/crawl/log-terminal.tsx` (949), `lib/api/types.ts` (848), `app/admin/llm/page-view.tsx` (650).

### 7.1 HIGH — docs/frontend-architecture.md materially stale (5/5 spot checks wrong)
- Lists dead `/selectors` route, omits live `/data-enrichment` `/product-intelligence` `/ai-visibility`; references deleted `crawl.module.css`; wrong filenames (`page.tsx` vs actual `page-view.tsx`); stale `previewSelectors` drift note; API-layer file list omits `lib/api/schemas.ts` and `src/api/ai-visibility.ts`.
- **Fix:** Rewrite §2/§3 from `route-registry.ts`; doc-date review trigger on route changes. **Effort: S.**

### 7.2 HIGH — God-page: `app/ai-visibility/page-view.tsx` (956 LOC, 0 tests)
- 9 useState + 6 queries + 5 mutations + ~700 LOC JSX in one component; imports API module from the wrong layer (`src/api/` vs documented `lib/api/*` ownership); inline query key bypassing the `queryKeys` factory; largest page is the least tested.
- **Fix:** Move module to `lib/api/`; extract `use-ai-visibility` hook + form component; hook-level tests. **Effort: M (1–2d).**

### 7.3 MEDIUM — Hand-maintained API types already drifted from FastAPI
- **Files:** `lib/api/types.ts` (848 LOC, no codegen): `CrawlRun` lacks `run_health` (backend always sends it); `ReviewPayload` requires `selector_memory`/`selector_suggestions` no backend schema emits (runtime `undefined` where type says present); `crawlsApi.getReview/reviewHtml/saveReview` have zero callers. 42 fields typed `Record<string, unknown>`.
- **Fix:** Generate types from OpenAPI (openapi-typescript) or expand zod coverage; delete dead review surface. **Effort: M.**

### 7.4 MEDIUM — admin/llm hand-rolls useReducer + fetch-in-useEffect (second data-fetching paradigm)
- **File:** `app/admin/llm/page-view.tsx:47-57,116-152,174-188,244-260` — duplicated server state, manual refetch after mutations, no caching/abort; 650 LOC doing what ~250 LOC of React Query would. No tests.
- **Fix:** Rewrite with useQuery/useMutation + invalidation. **Effort: M (1d).**

### 7.5 MEDIUM — 28-prop drilling bus through CrawlTerminalTabContent
- **Files:** `components/crawl/crawl-run-screen.tsx:308-340` → `crawl-terminal-tab-content.tsx:12-40` (pure pass-through re-dealing to 4 leaf tabs); workspace orchestrates 14 hooks.
- **Fix:** Per-tab view-model objects or leaf tabs consuming hooks directly. **Effort: M (1d).**

### 7.6 MEDIUM — Log-stream render scalability
- **Files:** `use-run-log-stream.ts:172-181` (setState per WS line), `log-terminal.tsx:630-631` (all groups rendered, no windowing, up to 2000 lines), dual 1s clocks (`use-run-polling.ts:29-39` re-renders the whole 14-hook workspace; `use-log-terminal-state.ts:143`).
- **Impact:** Chatty multi-URL runs degrade the core monitoring screen exactly when it matters.
- **Fix:** 100–250ms buffered flush / `useDeferredValue`; window the group list; one shared clock. **Effort: M (1–2d).**

### 7.7 MEDIUM — Architecture policy budgets exempt exactly the largest files
- **Files:** `scripts/check-frontend-architecture.mjs:7-12`, `check-crawl-architecture.mjs:6-34` — budget 11 of 187 files; none cover ai-visibility (956), log-terminal (949), admin/llm (650), form-fields (599). Both scripts pass today while the worst offenders grow.
- **Fix:** Default 400-LOC cap with explicit exceptions; budget the 4 big files now. **Effort: S.**

### 7.8 MEDIUM — API facade migration stalled at 0%
- `lib/api/index.ts:12-22` spreads 10 domain modules into one flat `api` object (name collisions silently overwrite); 23 files use the facade, 0 import domain modules directly. Inline query keys persist in 2 newer modules.
- **Fix:** Commit to namespaced facade or execute direct-import migration; route all keys through queryKeys. **Effort: S–M.**

### 7.9 LOW — Misleading feature ownership + brittle deep-relative imports
- `app/domain-memory/page-view.tsx` is a 7-LOC shim → `components/selectors/domain-memory/*` (parent dir reflects a deleted page). 271 imports use `../../`+, 33 use `../../../`+; `@/` alias covers only `src/` (39 uses).
- **Fix:** Rename dir; extend alias (`@lib`, `@ui`). **Effort: S.**

### 7.10 LOW — Telemetry bypasses central client with relative URL
- `lib/telemetry/events.ts:3,48` posts to relative `/api/telemetry/events` → silently 404s in split-origin deploys (try/catch swallows). Also: records-table height constants duplicated with CSS vars; onScroll setState per event.
- **Fix:** Prefix with `getApiBaseUrl()`; derive row height at mount. **Effort: S.**

### 7.11 Strengths to preserve
One fetch chokepoint; strict typing; 138 unit + 6 e2e tests, 0 skipped; windowed records table; lazy routes + bundle budgets; token policy enforced (0 raw `var()` escapes); contexts use `useSyncExternalStore`.

---

## 8. Cross-Cutting Themes

1. **Attacker-controlled data is the core business — treat it as hostile everywhere.** The SSRF redirect hole (1.1), unsanitized HTML serving (1.2), unvalidated hrefs (5.1), and CSV formula injection (1.7/5.2) are one theme: the trust boundary between crawled content and users is enforced in some places and forgotten in others. Fix pattern: centralize (one redirect-validating fetch helper, one SafeExternalLink, one CSV cell sanitizer) rather than patching sites one by one.
2. **Config discipline is the project's own top rule — and its biggest gap.** 88 dead settings fields (3.1) + hardcoded vendor tokens (4.3) + hardcoded match thresholds (4.4) + hardcoded CASCADE flags (3.8) all cut against AGENTS.md rule 1. A "config audit pass" (delete dead, hoist stray) pays down rule-1 debt in one sweep.
3. **Half-finished migrations are worse than no migration.** Badge variants (6.1), API facade (7.8), CASCADE cutover (3.8), field-* CSS classes (6.9), knowledge.py compat routes (3.4), the dead lease columns (2.2). Each leaves two systems to maintain. Pick one side and finish.
4. **Docs are liabilities when stale.** All three canonical docs failed spot checks (4.9, 4.10, 7.1). These docs are load-bearing for agent/human navigation — schedule a quarterly drift pass or generate the mechanical parts.
5. **The per-URL hot path carries the scaling risk.** Findings 2.1–2.5 and 2.11–2.13 all live in the URL-processing loop. One focused "hot-path week" (JSONB diet, query caching, pool sizing, to_thread offload, task worker-pool) removes the first 5 scaling ceilings at once.

## 9. Prioritized Remediation Roadmap

**P0 — Security fixes (days, low risk):**
1. Re-validate redirect targets in all fetchers + Playwright navigation (1.1, 1.3, 1.4, 1.5)
2. Sanitize/sandbox served crawled HTML + add CSP (1.2)
3. `isSafeHttpUrl` on the 6 frontend href sites (5.1)
4. CSV formula-escape both export paths (1.7, 5.2)
5. Rotate preview secrets; add logout endpoint + button (5.3, 5.4)

**P1 — Scaling ceilings (1–2 weeks):**
6. Run-summary JSONB diet (2.1) + input caps (2.6)
7. Celery visibility_timeout + lease claiming (2.2)
8. Per-run caching of release payload/profile; kill has_table introspection; batch log/record writes (2.3)
9. `to_thread` offload in HTTP hot path (2.4); pool sizing + parent-session txn release (2.5)
10. PI/Enrichment jobs → Celery (2.7); artifact retention + delete-on-run-delete (2.14)

**P2 — Dead-code sweep (1 week, mechanical):**
11. Delete 182 confirmed dead symbols + 8 routes + 3 files + 88 settings fields (§3)
12. Frontend: delete 21 unused exports, ConfirmDialog dupe, dead CSS, msw (§6)
13. Consolidate status mappings + badge decision (6.1–6.3)

**P3 — Structural (weeks, schedule per subsystem):**
14. Split `extraction/resolution/__init__.py` (4.1); tame BrowserAttemptRunner (4.2)
15. Break the pipeline circular dependency (4.7); typed pipeline boundary (4.13)
16. knowledge.py query layer (4.6/3.4); models layering inversion (4.5)
17. Frontend: ai-visibility + admin/llm refactors with tests (7.2, 7.4); OpenAPI type codegen (7.3); log-stream rendering (7.6)
18. Config sweep: vendor tokens → block_signatures; thresholds → config (4.3, 4.4)
19. Docs drift pass: CODEBASE_MAP, INVARIANTS, frontend-architecture (4.9, 4.10, 7.1)
20. Test coverage for enrichment/intelligence/workers (4.11)

## 10. Appendix

- **Per-agent structured results:** the 7 audit agents (be-security, be-deadcode, be-scale, be-maintain, fe-security, fe-deadcode, fe-maintain) produced structured JSON outputs in the audit session; those session artifacts are not committed. This report is the self-contained evidence record — every finding cites repository-relative file:line references verifiable against commit `f2f8755`.
- **Backend totals:** 370 py files / ~96k LOC; 134 test files / 1,726 tests; 105 API routes; 10 files >800 LOC; 138 `except Exception` (52 silent); 0 bare excepts; 0 skipped tests; 182 confirmed dead symbols; 25 duplicate module basenames.
- **Frontend totals:** 187 ts/tsx / 26,461 LOC (22,318 non-test); 22 unit test files (138 tests, all pass) + 2 e2e specs; 0 explicit `any`; `tsc --noEmit` clean; `pnpm audit` clean; 164/164 files reachable from entry; 21 unused exports; 7 duplicate blocks (~300 LOC).
- **Method note:** findings marked CONFIRMED were verified by two independent methods (tool + grep) or by direct code reading with quoted evidence; SUSPECTED items are labeled as such. No code was modified during the audit.
