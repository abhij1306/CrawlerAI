# Plan: CrawlerAI Security Remediation and Deployment Failure Fixes

**Created:** 2026-08-24
**Agent:** Codex
**Status:** BLOCKED
**Touches buckets:** security/config, authentication, acquisition, tenant persistence, public API/MCP, deployment/runtime, containers, CI, operations

## Goal

Make CrawlerAI safe and mechanically deployable before AWS infrastructure is created. Close the validated High and Medium findings, fix known container/startup failures, preserve deterministic extraction behavior, and produce focused evidence for a production GO/NO-GO review. This plan must finish before `crawlerai-aws-codex-implementation-plan.md` starts.

## Current Verdict and Audit Basis

**Verdict: NO-GO.** Revision `595b9b7cc77777b294277e461cb2e755056d4e9b` has 5 High and 10 Medium validated findings. Deployment is also blocked by command resolution, database configuration, bootstrap, frontend-container, and environment-posture defects.

- Codex Security scan: `b30c34b7-5532-4a88-88b5-1e884c3f950c`
- Coverage: partial. Source review covered auth/session, public API/MCP, outbound acquisition, persistence/isolation, deployment/runtime, supply chain, and frontend.
- Backend OSV dependency audit: no known vulnerabilities.
- Frontend high-severity package audit: no known vulnerabilities.
- Not yet proven: built container OS packages, live AWS controls, live Cloudflare controls, backup restore, or production traffic behavior.
- No full test suite was run during planning. Each slice names focused verification; CI/ship-main owns broad validation later.

## Severity and Release Gates

- **P0:** Exploitable path to internal/cloud resources or a direct security-boundary bypass. Fix immediately.
- **P1:** High-impact tenant, identity, secret, datastore, or resource-control defect. Must close before AWS work.
- **P2:** Defense-in-depth and deployment correctness required before production traffic.
- **P3:** Operational proof and external-control closeout.
- AWS implementation may start only after every P0/P1 item is fixed, focused tests pass, and a container scan gate is operational.
- Production traffic may start only after every accepted P2 item is fixed or has a named owner, expiry, compensating control, and written risk acceptance. P3 production checks must pass.

## Validated Findings Register

| ID | Priority | Finding | Evidence anchor | Required acceptance proof |
| --- | --- | --- | --- | --- |
| SEC-01 | P0 | DNS rebinding bypasses outbound URL validation | `backend/app/core/url_safety.py`, `backend/app/acquisition/runtime.py`, `backend/app/acquisition/browser_proxy_bridge.py` | HTTP, curl, proxy, and browser paths bind connections to approved public IPs; mixed/private/rebound DNS tests fail closed. |
| SEC-02 | P0 | Screenshot capture disables browser SSRF interception | `backend/app/acquisition/browser_fetch_runner.py` | Screenshot-enabled redirects and subresources cannot reach private, loopback, link-local, or metadata targets. |
| SEC-03 | P1 | Admin bootstrap promotes/reactivates an existing account | `backend/app/core/auth_service.py`, `backend/app/main.py` | Bootstrap is create-only, durably consumed, restart-safe, and cannot promote an existing identity. |
| SEC-04 | P1 | Domain cookie state crosses user boundaries | `backend/app/models/domain_memory.py`, `backend/app/acquisition/cookie_store.py` | Two users crawling one domain cannot read or replay each other's state; migration/backfill has a safe disposition. |
| SEC-05 | P1 | Compose publishes unauthenticated Redis/Celery broker | `docker-compose.yml`, `backend/app/core/celery_app.py` | Production rejects plaintext/unauthenticated Redis; local Redis is not host-published by default. |
| SEC-06 | P2 | Cookie-authenticated unsafe mutations lack CSRF checks | `backend/app/core/dependencies.py`, `backend/app/api/auth.py` | Unsafe cookie-auth requests require valid Origin plus CSRF proof; bearer-only API requests remain usable. |
| SEC-07 | P2 | Proxy-aware rate limiting misidentifies clients | `backend/app/core/rate_limit.py` | CIDR-aware right-to-left trusted-hop parsing passes Cloudflare → ALB → ECS spoofing tests. |
| SEC-08 | P1 | Ordinary users mutate globally consumed extraction memory | `backend/app/api/crawl_domain.py`, `backend/app/api/knowledge.py`, `backend/app/models/domain_memory.py` | Memory is workspace-scoped, or global promotion is admin-only and audited; cross-user poisoning tests pass. |
| SEC-09 | P2 | Invalid public API keys reach DB before rate limiting | `backend/app/main.py`, `backend/app/core/public_auth.py` | Redis-backed IP/global pre-auth limit bounds DB lookups for unique invalid keys. |
| SEC-10 | P1 | Non-loopback MCP has no inbound client authentication | `backend/app/mcp_server/config.py`, `backend/app/mcp_server/server.py` | Non-loopback startup fails closed unless per-client auth maps callers to distinct principals. First release remains loopback-only. |
| SEC-11 | P1 | HTTP, robots, and sitemap bodies are unbounded | `backend/app/acquisition/runtime.py`, `backend/app/crawl/robots_policy.py`, `backend/app/crawl/sitemap_resolver.py` | Fixed, chunked, misleading-length, and compressed responses stop at centralized byte budgets. |
| SEC-12 | P1 | Request limits happen after parser/spooling | `backend/app/main.py`, `backend/app/api/crawls.py` | ASGI receive limits reject oversized JSON/multipart before parsing or disk spooling; edge limits match. |
| SEC-13 | P1 | Compose forces development security posture | `docker-compose.yml`, `backend/app/core/config/__init__.py` | Production fails on development mode, placeholders, or local origins; secure cookies/docs/metrics/HSTS contract is tested. |
| SEC-14 | P1 | Proxy credentials persist and appear in debug logs | `backend/app/crawl/profile/normalization.py`, `backend/app/crawl/crud.py`, acquisition logging | Sentinel credentials never appear in rows, API data, diagnostics, logs, or exception strings. |
| SEC-15 | P1 | Run cookie files are plaintext and outlive runs | `backend/app/acquisition/cookie_store.py`, `backend/app/crawl/crud.py`, `backend/app/tasks.py` | Cookie state is encrypted, mode-restricted, tenant/run-owned, and removed on deletion/retention cleanup. |

## Acceptance Criteria

- [x] SEC-01 through SEC-15 have focused regression tests and are closed or explicitly rejected with evidence.
- [x] No service starts in production with placeholder secrets, development posture, insecure Redis, unsafe proxy trust, or non-loopback unauthenticated MCP.
- [x] API, migration, worker, scheduler, and frontend images start with their production commands as non-root users.
- [x] Fresh-database migration plus one-time admin bootstrap succeeds; restarts cannot rerun bootstrap or modify an existing user.
- [x] `DATABASE_URL` is built safely from deployment components or supplied directly through centralized config; credentials are URL-encoded.
- [x] API liveness, readiness, worker health, and scheduled cleanup have separate, observable contracts.
- [x] Existing API & MCP UI is extended and tested; no duplicate API-key UI is introduced.
- [x] Backend and frontend lockfile audits remain green.
- [ ] Built backend and frontend images produce SBOMs and have no unresolved fixable/unclassified High or Critical findings under the approved policy; live ECR enhanced classification remains required.
- [x] Focused backend pytest and VitePlus frontend verification commands exit 0.
- [ ] Final readiness record includes live Cloudflare/AWS evidence, restore evidence, rollback steps, owner, and GO/NO-GO verdict.

## Do Not Touch

- `backend/app/extraction/**` — do not change deterministic extraction order or semantics while fixing platform security.
- `backend/app/publish/**` — do not compensate downstream for acquisition defects.
- Eval corpora and `TEST_SITES.md` — evidence inputs, not remediation targets.
- `docs/plans/crawlerai-extraction-accuracy-plan.md` — separate active work owned by the current plan.
- Existing API & MCP route/page ownership — extend `frontend/app/api-access/**`; do not create a parallel surface.
- Invoro source/state — reference lessons only. Never edit or point CrawlerAI Terraform at Invoro state.

## Slices

### Slice 0: Freeze Baseline and Decisions

**Status:** DONE
**Files:** `docs/audits/crawlerai-security-and-deployment-readiness-2026-08-24.md`, relevant focused test manifests
**What:** Persist the 15-finding register, audit limitations, package-audit outputs, deployment failure inventory, and owner decisions. Record whether deployment is single-tenant or multi-tenant; default to multi-tenant-safe. Record first-release MCP as local/loopback only. Record exact production hostnames later without storing secrets.
**Verify:** Audit document links each SEC ID to an owner, target slice, evidence command, and disposition.

### Slice 1: Bind Outbound Requests to the Security Decision

**Status:** DONE
**Files:** `backend/app/core/url_safety.py`, `backend/app/core/config/*`, `backend/app/acquisition/runtime.py`, `backend/app/acquisition/browser_proxy_bridge.py`, `backend/app/acquisition/browser_fetch_runner.py`, `backend/app/acquisition/browser_page_flow.py`, focused acquisition/security tests
**What:** Make URL validation and connection establishment one operation. Resolve once, reject any disallowed answer, pin approved IPs while retaining HTTP Host and TLS SNI, and revalidate every redirect. Apply equivalent connect-time denial to HTTP, curl, browser, and proxy paths. Install browser SSRF interception regardless of screenshot/resource settings. Deny loopback, RFC1918, link-local, multicast, IPv6 local ranges, decimal/encoded aliases, and cloud metadata. Keep network policy in `core/config`, not service constants. Do not rely on security groups alone because workers require internet egress.
**Verify:** Run focused SSRF tests covering DNS rebinding, mixed answers, redirect chains, screenshot mode, browser subresources, IPv4/IPv6 aliases, and metadata endpoints.

### Slice 2: Bound Ingress and Untrusted Upstream Data

**Status:** DONE
**Files:** `backend/app/main.py`, `backend/app/core/config/*`, `backend/app/api/crawls.py`, `backend/app/acquisition/runtime.py`, `backend/app/crawl/robots_policy.py`, `backend/app/crawl/sitemap_resolver.py`, focused resource-limit tests
**What:** Add an ASGI receive wrapper that counts bytes before JSON/multipart parsing and spooling. Set smaller route-specific budgets. Stream upstream bodies; enforce advertised, compressed, and decoded limits; stop reads at the cap; use tighter robots/sitemap budgets; avoid persistence/retry after an oversize result. Match limits later at Cloudflare and ALB.
**Verify:** Focused tests reject oversized fixed-length, chunked, multipart, misleading-length, and compression-bomb cases before excessive memory/disk use.

### Slice 3: Repair Tenant and Learned-State Isolation

**Status:** DONE
**Files:** `backend/app/models/domain_memory.py`, migrations, `backend/app/acquisition/cookie_store.py`, `backend/app/acquisition/browser_pool_page.py`, `backend/app/api/crawl_domain.py`, `backend/app/api/knowledge.py`, services/config, focused isolation tests
**What:** Add user/workspace ownership to durable cookie and extraction memory, query/cache keys, uniqueness constraints, loaders, and writers. Default cross-run domain cookie reuse off in production unless cookies are proven non-sensitive and tenant-scoped. Make global extraction-policy promotion admin/curator-only with audit history. Define a migration policy for legacy global rows: quarantine, deliberate owner assignment, or deletion; never silently expose them to all tenants.
**Verify:** Two-principal tests prove records, caches, cookies, selectors, profiles, and contract choices cannot cross boundaries. Normal users cannot mutate global policy.

### Slice 4: Fix Identity, Bootstrap, CSRF, and Abuse Controls

**Status:** DONE
**Files:** `backend/app/core/auth_service.py`, `backend/app/core/dependencies.py`, `backend/app/core/public_auth.py`, `backend/app/core/rate_limit.py`, `backend/app/api/auth.py`, `backend/app/main.py`, migrations, focused auth/API tests
**What:** Replace startup mutation with an explicit create-only bootstrap command and durable consumed record. Fail if the email exists. Remove bootstrap password after success. Add strict Origin/Referer plus synchronizer or signed double-submit protection for cookie-authenticated unsafe methods; preserve bearer-only public API behavior. Parse configured trusted CIDRs and walk forwarding headers from the application peer outward. Add Redis-backed pre-auth IP/global limits before API-key DB lookup, then per-key limits after authentication.
**Verify:** Focused tests cover restart, existing-user conflict, concurrent bootstrap, CSRF, bearer exemption, spoofed forwarding chains, dynamic ALB peers, and invalid-key floods.

### Slice 5: Make MCP Fail Closed and Complete the Existing API UI

**Status:** DONE
**Files:** `backend/app/mcp_server/config.py`, `backend/app/mcp_server/server.py`, `backend/app/mcp_server/client.py`, public API capability metadata, `frontend/app/api-access/**`, existing MCP/API tests and docs
**What:** First release supports stdio or loopback MCP only. Reject non-loopback bind without an implemented inbound auth system that maps every MCP caller to a distinct API principal. Never expose one shared backend key through an anonymous listener. Replace stale `railway-ready` capability copy with config-derived neutral deployment metadata. Extend the existing API & MCP page with copy-safe endpoint examples, key reveal-once behavior, revocation state, loopback MCP setup, and explicit hosted-MCP limitation. Do not recreate the page.
**Verify:** Non-loopback no-auth startup fails; separate client principals cannot share credentials; API-key create/list/revoke and UI tests pass; examples match live route contracts.

### Slice 6: Repair Secret Storage and Retention

**Status:** DONE
**Files:** `backend/app/crawl/profile/normalization.py`, `backend/app/crawl/crud.py`, acquisition logging/diagnostics, `backend/app/acquisition/cookie_store.py`, `backend/app/tasks.py`, migrations, focused secret tests
**What:** Store only encrypted proxy-secret references, not URL userinfo. Use the canonical redactor in logs, diagnostics, exceptions, task arguments, and API serialization. Encrypt browser cookie files with the application encryption key, create them with restrictive permissions, bind them to tenant/run/engine, delete every variant with run deletion, and sweep orphans/expired files. Mount cookie/artifact storage only in services that need it. Rotate any credential suspected of prior persistence.
**Verify:** Sentinel secrets never appear in DB rows, logs, API responses, task payloads, diagnostics, or exceptions. Encrypted cookie state is removed on delete and retention sweep.

### Slice 7: Fix Container and Process Startup Failures

**Status:** DONE
**Files:** `backend/app/core/config/*`, `backend/app/init_db.py`, `backend/Dockerfile`, `docker-compose.yml`, new production compose override if retained, `frontend/Dockerfile`, frontend server config, focused startup tests/scripts
**What:** Keep config in `backend/app/core/config/*`. Accept either a complete `DATABASE_URL` or deployment components and build a URL with correctly encoded credentials. Stop overriding the image command with bare `python`, `uvicorn`, or `celery`; invoke `.venv/bin/*` explicitly or set a controlled image `PATH`. Remove forced `APP_ENV=development`; separate local and production manifests. Add a minimal non-root frontend static image with SPA fallback and security headers. Use `/health/live` for process liveness, `/health/ready` for deploy smoke, and an explicit worker ping. Run migration as a one-off task, then run the create-only bootstrap once; API tasks set bootstrap false. Use a verified Celery pool model: default first release to one `--pool=solo` worker process per ECS task and scale task count for concurrency.
**Verify:** Build and start each image; migrate a fresh DB; bootstrap once; restart API; confirm no promotion; enqueue and finish one crawl; confirm liveness/readiness/worker checks and frontend SPA routing.

### Slice 8: Replace Warning-Prone Dependencies and Harden Images

**Status:** DONE
**Files:** `backend/app/core/security.py`, `backend/pyproject.toml`, `backend/uv.lock`, async subprocess lifecycle owners/tests, both Dockerfiles
**What:** Remove Passlib and its Python `crypt` deprecation path. Keep Argon2 as the default and implement only the bounded legacy PBKDF2 verifier needed for migration; rehash on successful login. Close and await subprocess transports before event-loop shutdown so pytest no longer emits `PytestUnraisableExceptionWarning`. Convert backend to a multi-stage, digest-pinned build; keep compiler headers and curl out of runtime; retain non-root operation and browser dependencies. Digest-pin the frontend base image too.
**Verify:** Focused password migration tests pass; warning-focused async test emits no unraisable/event-loop warning; image history shows no compiler toolchain; containers run non-root.

### Slice 9: Add Supply-Chain and Release Gates

**Status:** DONE
**Files:** `.github/workflows/*`, dependency manifests, release scripts, security docs
**What:** Retain Node 24-compatible pinned Actions. Add lockfile checks, backend OSV audit, frontend audit, Gitleaks, CodeQL, SBOM generation, image scan, and ECR enhanced-scan enforcement. Block fixable or unclassified High/Critical findings. Require an explicit reviewed boolean for no-fix High/Critical exceptions; default false. Use the ECR credential helper with temporary `DOCKER_CONFIG` and `AWS_ECR_DISABLE_CACHE=true` to avoid plaintext Docker credential warnings. Publish evidence, never secrets.
**Verify:** A safe image passes; a fixture with a High finding blocks release; workflow permissions are least-privilege and action references are immutable.

### Slice 10: Production Readiness Closeout

**Status:** BLOCKED
**Files:** runbooks, security/readiness audit, Cloudflare/AWS evidence references
**What:** After AWS plan implementation, verify Cloudflare Full (strict), proxied DNS, WebSocket/SSE behavior, API no-cache, edge rate/body limits, and Cloudflare-only origin ingress. Verify RDS backups/restore, Redis TLS/auth, EFS encryption/access points, log retention/redaction, alarms, secret rotation, least-privilege task roles, migration failure behavior, deploy rollback, and demo shutdown/start procedures. Perform a restore drill and one controlled rollback. Update GO/NO-GO with residual risks and expiry dates.
**Verify:** Evidence-backed checklist has no open P0/P1, no unaccepted P2, successful restore/rollback, and named operational owners.

## Focused Verification Matrix

Use the smallest relevant command for each slice. Exact test node IDs may be adjusted to existing owners after grep.

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
uv run --frozen --extra dev pytest tests -q -k "ssrf or url_safety or screenshot or body_limit"
uv run --frozen --extra dev pytest tests -q -k "bootstrap or csrf or rate_limit or public_api_key"
uv run --frozen --extra dev pytest tests -q -k "tenant or domain_memory or cookie_store or proxy_secret"
uv run --frozen --extra dev pytest tests -q -k "mcp or health or celery or init_db or password"
uv run --frozen --extra dev python -m pip_audit --vulnerability-service osv

cd C:\Projects\CrawlerAI\frontend
vp test --run app/api-access
vp pm audit -- --audit-level=high
```

Do not substitute a full local suite for focused slice evidence. Broad suite and end-to-end release checks run in CI during ship-main.

## Doc Updates Required

- [x] `docs/backend-architecture.md` — trust boundaries, bootstrap, MCP, worker/scheduler, storage, health contracts.
- [x] `docs/frontend-architecture.md` — production static container and existing API & MCP UI behavior.
- [x] `docs/CODEBASE_MAP.md` — new middleware, commands, container/runtime owners.
- [x] `docs/INVARIANTS.md` — outbound request binding, tenant memory, secret lifecycle, explicit MCP exposure.
- [x] `docs/ENGINEERING_STRATEGY.md` — record connect-time SSRF enforcement and create-only bootstrap anti-patterns.
- [x] `.env.example` and operator runbook — document names and generation rules only; no values.

## Notes

- 2026-08-24 Slice 1 complete: HTTPX and curl pin approved IPs. All browser traffic uses a local enforcing SOCKS bridge that validates every target and connects to the approved IP while leaving TLS hostname validation end-to-end in Chromium. Browser HTTP/HTTPS upstream proxies fail closed. Focused SSRF, browser protocol, and launch verification passed (76 tests); focused Ruff passed.
- 2026-08-24 Slice 2 complete: pure ASGI fixed/chunked receive limits run before parsers; general/public/CSV budgets are config-owned. HTTPX streams and caps advertised, downloaded, and decoded bytes; curl caps its write buffer; robots and sitemap use tighter budgets and pinned transports. Fixed, chunked, compressed, and legitimate controls passed in 84 focused tests; focused Ruff passed.
- 2026-08-24 Slice 3 partial: durable domain cookies now require `user_id`, browser/handoff paths resolve ownership from `run_id`, recipe diagnostics use the run owner, and the migration deletes unowned legacy cookie/profile rows. Global contract/profile promotion is admin-only; ordinary runs return learned state locally without persisting it globally. 123 isolation/profile/API behavior tests passed, Ruff passed, and Alembic reports one head (`20260824_0002`). Slice remains IN PROGRESS because the architecture gate reports `cookie_store.py` newly over 800 LOC plus aggregate production/test LOC ratchets; split by ownership before marking done.
- 2026-08-24 Slice 3 complete: cookie HTTP export moved to its own cohesive owner, returning `cookie_store.py` below 800 lines. All 126 focused isolation/profile/API/architecture tests pass; focused Ruff passes; Alembic has one head. LOC ratchets record the measured security implementation (+358 production, +549 tests) while per-file ceilings remain unchanged.
- 2026-08-24 Slice 4 complete: startup identity mutation was replaced by a create-only durable bootstrap command; cookie mutations now enforce signed double-submit CSRF and exact origin; forwarding trust is CIDR/right-to-left; public API pre-auth Redis limits precede key lookup. Focused backend/frontend, Ruff, VitePlus, architecture, and Alembic verification passed. SEC-03, SEC-06, SEC-07, and SEC-09 closed.
- 2026-08-24 Slice 5 complete: MCP defaults to per-principal stdio and optional SSE accepts only literal loopback addresses; existing API Access UI now exposes copy-safe capabilities, extract, stdio, loopback, one-time reveal, and revoke flows. Focused backend/frontend, Ruff, VitePlus, architecture, and Alembic verification passed. SEC-10 closed.
- 2026-08-24 Slice 6 complete: proxy URL userinfo now persists only as endpoint-bound encrypted references and is restored only for acquisition; a canonical redactor protects API, diagnostics, logs, tracebacks, and task boundaries. Per-run cookie files are encrypted, owner/run/engine-bound, mode-restricted, deleted with runs, and swept when orphaned/expired. Beat no longer mounts cookie/artifact storage. Focused secret, cookie, cleanup, architecture, Ruff, Compose, and Alembic verification passed. SEC-14 and SEC-15 closed.
- 2026-08-24 Slice 7 complete: centralized config now accepts a complete database URL or safely encoded deployment components and rejects insecure production database/Redis/origin posture. Local and production Compose contracts use explicit venv processes, one-off migration/bootstrap, steady-state bootstrap disablement, solo Celery, liveness/readiness/ping checks, and a non-root static SPA image. 43 focused startup tests, 49 config/architecture tests, Ruff, VitePlus build, both Compose renders, both real image builds, frontend health/SPA/header checks, fresh migration/bootstrap/restart proof, API readiness, worker ping, and one completed queued crawl passed. SEC-05 and SEC-13 closed.
- 2026-08-24 Slice 8 complete: Passlib, bcrypt, types-Passlib, and psycopg2 build dependencies were removed from the lock. Argon2id remains the writer and a bounded standard-library PBKDF2 verifier migrates legitimate legacy hashes while rejecting malformed, oversized, and excessive-work hashes. Browser/driver/bridge closures are joined before event-loop teardown. All image bases are digest-pinned; the backend is multi-stage and its non-root runtime has working Chromium but no compiler, curl, or libpq headers. The strict warning/password/container/architecture gate passed 105 tests; Ruff, lock check, image builds, image inspection, and runtime Chromium launch passed.
- 2026-08-24 Slice 9 complete: existing frozen backend/frontend audits, Gitleaks, and CodeQL remain blocking; explicit lock checks were added. Pinned Node 24-capable Actions now build both images, publish SPDX JSON SBOMs, and block fixable High/Critical findings. A reusable OIDC ECR enhanced-scan gate validates immutable digests through a temporary credential-helper config and fails closed on missing, fixable, unclassified, or unreviewed no-fix High/Critical findings. Eight ECR policy cases and four workflow contracts pass; actionlint, Ruff, architecture gates, OSV/frontend audits, final SBOM generation, real image scans, and non-root/Chromium probes pass. Current final images have zero fixable High/Critical Trivy findings; live ECR classification remains a production closeout gate.
- 2026-08-24 Slice 10 blocked at its declared precondition. `crawlerai-aws-codex-implementation-plan.md` remains QUEUED with every slice TODO and no `infra/aws/` stack exists. Read-only AWS identity succeeds, but that proves access only; no deployed RDS/Redis/EFS/ECS/ALB, Cloudflare control evidence, restore drill, rollback drill, or named operational owners exist. `CRAWLERAI_AWS_OWNER_RUNBOOK.md` now defines the fail-closed evidence register and drill procedures. Current decision remains NO-GO. Starting or provisioning the separate AWS plan requires explicit scope and live-change authorization.

- Do **not** copy Invoro `.env` wholesale. Reusing its database password was detected during planning. Generate unique CrawlerAI JWT, encryption, admin, database, Redis, metrics, API, proxy, and provider credentials.
- CrawlerAI consumes `DATABASE_URL`; Invoro Terraform injects PostgreSQL components. Slice 7 must reconcile this in centralized config before AWS deployment.
- `BOOTSTRAP_ADMIN_ONCE=false` plus disabled registration on a fresh database creates no usable admin. The one-off create-only bootstrap task is mandatory.
- Current MCP/API feature and UI already exist. Work extends and hardens them.
- TAC entitlement lookup was unavailable because its connector was not authenticated. The local canonical scan completed; this does not reduce the source findings.
- If remediation changes a public API contract, update the UI examples and contract tests in the same slice.
