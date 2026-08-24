# CrawlerAI Security and Deployment Readiness — 2026-08-24

## Verdict and Scope

**NO-GO.** Revision `595b9b7cc77777b294277e461cb2e755056d4e9b` has fifteen validated findings and known deployment failures. This record tracks remediation under `docs/plans/crawlerai-security-remediation-and-deployment-fix-plan.md`.

The source review covered authentication/session handling, public API/MCP, outbound acquisition, persistence/isolation, deployment/runtime, supply chain, and frontend behavior. It did not prove built-image operating-system packages, live AWS or Cloudflare controls, backup restoration, or production traffic behavior.

Codex Security scan: `b30c34b7-5532-4a88-88b5-1e884c3f950c`.

## Fixed Decisions

- Deployment contract is multi-tenant-safe. Durable cookies, acquisition memory, and extraction memory must not cross principals.
- First-release MCP is stdio or loopback-only. A non-loopback listener must fail closed until per-client inbound authentication exists.
- Production hostnames remain deployment inputs. This repository stores names and validation rules, never secret values.
- Local Compose is a development convenience only. Production posture must fail closed on development mode, placeholder secrets, insecure Redis, or local origins.
- Migration and create-only bootstrap are one-off operations. API startup must not mutate an existing identity.

## Findings Register

| ID | Owner | Target slice | Evidence command / artifact | Disposition |
| --- | --- | --- | --- | --- |
| SEC-01 | acquisition + `core/url_safety.py` | 1 | `pytest tests/component/test_url_safety.py tests/component/test_ssrf_redirects.py -q` plus pinned-connect regression tests | CLOSED |
| SEC-02 | browser acquisition | 1 | screenshot redirect/subresource SSRF regression tests | CLOSED |
| SEC-03 | authentication/bootstrap | 4 | `pytest tests/component/test_auth_service.py -q` plus bootstrap command tests | CLOSED |
| SEC-04 | domain cookie persistence | 3 | `pytest tests/component/test_domain_cookie_memory.py -q` plus two-principal tests | CLOSED |
| SEC-05 | Redis/Celery runtime | 7 | production config and Compose startup tests | CLOSED |
| SEC-06 | session authentication | 4 | cookie Origin/CSRF and bearer-exemption tests | CLOSED |
| SEC-07 | rate limiting/proxy trust | 4 | `pytest tests/unit/test_rate_limit_redis.py -q` plus forwarding-chain tests | CLOSED |
| SEC-08 | extraction memory/API authorization | 3 | two-principal memory and admin-promotion tests | CLOSED |
| SEC-09 | public API authentication | 4 | `pytest tests/component/test_public_api_login_and_auth_limits.py tests/component/test_public_api_rate_limits.py -q` | CLOSED |
| SEC-10 | MCP transport | 5 | `pytest tests/component/test_mcp_server.py -q` | CLOSED |
| SEC-11 | acquisition/robots/sitemap | 2 | bounded fixed/chunked/compressed upstream tests | CLOSED |
| SEC-12 | ASGI ingress | 2 | pre-parser JSON and multipart receive-limit tests | CLOSED |
| SEC-13 | runtime configuration | 7 | production config rejection and container startup tests | CLOSED |
| SEC-14 | proxy profile/diagnostics | 6 | sentinel secret persistence/log/API/task tests | CLOSED |
| SEC-15 | run cookie artifacts | 6 | encryption, permission, ownership, delete, and sweep tests | CLOSED |

## Dependency Audit Baseline

- Backend OSV audit at planning time: no known vulnerabilities.
- Frontend high-severity package audit at planning time: no known vulnerabilities.
- Built backend/frontend images produce SPDX JSON SBOMs. Current Trivy evidence has zero fixable High/Critical findings in both final images.
- Reusable ECR enhanced-scan enforcement is implemented; live AWS execution awaits the production role/repositories from the AWS plan.

## Deployment Failure Inventory

- Compose overrides image commands with executables that are not reliably on runtime `PATH`.
- Deployment supplies database components while application config expects `DATABASE_URL`; credential URL encoding is not proven.
- Fresh databases can start with registration disabled and no usable administrator.
- API startup bootstrap can mutate an existing account and is not a durable one-time operation.
- Frontend lacks a verified non-root production static image, SPA fallback, and host security-header contract.
- Compose forces development posture and exposes local Redis to the host.
- Liveness, readiness, worker health, migration, bootstrap, and scheduled cleanup are not separate deployment contracts.

## Release Gates

AWS implementation stays blocked until all P0/P1 findings are fixed, focused tests pass, and image scanning blocks unresolved fixable or unclassified High/Critical findings. Production traffic stays blocked until every accepted P2 item is fixed or has named, expiring risk acceptance and all live P3 checks pass.

## Evidence Log

Remediation slices append exact commands and results here. A finding moves from `OPEN` only after its malicious trigger no longer reproduces and its legitimate control still passes.

### 2026-08-24 — Slice 1 partial evidence

- `pytest tests/component/test_url_safety.py tests/component/test_ssrf_redirects.py tests/component/test_ssrf_robots_sitemap.py tests/component/test_acquisition_offload_analysis.py -q` — PASS, 48 tests.
- Focused Ruff check over changed acquisition/security files and tests — PASS.
- HTTPX connects to an approved IP while preserving Host and TLS SNI. Curl uses a per-hop `CURLOPT_RESOLVE` entry. Mixed public/private DNS answers fail closed. Screenshot mode now installs the browser route guard, and browser documents/subresources are DNS-validated before continuation.
- Follow-up browser boundary: every runtime now launches through a local SOCKS bridge. The bridge revalidates the requested host and opens the approved IP directly (or sends the approved IP to a validated SOCKS upstream). Private targets never reach `open_connection`. Browser HTTP/HTTPS upstream proxies fail closed.
- Final Slice 1 focused gate: 76 SSRF, browser protocol, browser launch, and URL-safety tests passed; focused Ruff passed. SEC-01 and SEC-02 are CLOSED.

### 2026-08-24 — Slice 2 evidence

- Focused ingress/upstream gate: 84 request-limit, URL-safety, redirect, robots, sitemap, and public middleware tests passed; focused Ruff passed.
- Advertised fixed-length, chunked, and gzip-decoded oversize triggers return/raise before materialization past the configured ceiling. Bodies exactly at the limit remain usable.
- SEC-11 and SEC-12 are CLOSED.

### 2026-08-24 — Slice 3 partial evidence

- Two users can persist distinct cookies for one domain and only load their own ciphertext. Missing ownership fails closed.
- Browser page reuse, browser-to-curl handoff, cookie listings, and domain-recipe diagnostics derive/filter by the owning run user.
- Ordinary API callers receive 403 for global contract, grounded-correction, and run-profile promotion. Ordinary crawl runs cannot persist global profiles.
- Migration chain `20260824_0002` through `20260824_0004` deletes unowned cookie/profile state, adds durable bootstrap replay protection, and purges legacy plaintext proxy secrets.
- 123 focused behavior tests passed; Ruff and `alembic heads` passed. Architecture gate has three open ratchet failures, so SEC-04 and SEC-08 remain OPEN pending the required ownership split and a green focused gate.
- Ownership split completed. The combined 126-test behavior/architecture gate and focused Ruff now pass. SEC-04 and SEC-08 are CLOSED.

### 2026-08-24 — Slices 4–7 evidence

- Identity bootstrap, CSRF, forwarding trust, and pre-auth abuse gates passed; SEC-03, SEC-06, SEC-07, and SEC-09 closed.
- MCP stdio/loopback fail-closed and API UI gates passed; SEC-10 closed.
- Proxy sentinel and encrypted run-cookie lifecycle gates passed; SEC-14 and SEC-15 closed.
- Startup/config gates passed: 43 focused tests, 49 config/architecture tests, Ruff, VitePlus build, local/production Compose rendering, and real backend/frontend image builds.
- Isolated container verification migrated a fresh PostgreSQL database through `20260824_0004`, created one durable admin, proved repeat bootstrap consumed without identity change, returned API readiness 200, returned Celery ping `pong`, and completed one queued crawl. Frontend liveness, deep-link SPA fallback, and response security headers passed. SEC-05 and SEC-13 closed.

### 2026-08-24 — Slice 8 evidence

- Passlib and its deprecated Python `crypt` import path are absent from the resolved lock. Bounded historical PBKDF2 verification, rejection triggers, and login-time Argon2id migration passed.
- Strict warning execution passed 105 focused password, browser lifecycle, worker-loop, container-contract, and architecture tests with `PytestUnraisableExceptionWarning` and `RuntimeWarning` promoted to errors. Ruff and frozen-lock checks passed.
- Digest-pinned backend/frontend images built. Both inspect as non-root. Backend history contains no build toolchain stage; runtime package probes found no compiler, make, curl, or libpq headers. Chromium 151 launched and closed inside the final backend image.

### 2026-08-24 — Slice 9 evidence

- Backend OSV and frontend High audits report no known vulnerabilities. All workflow Actions are pinned to 40-character commits and actionlint passes.
- Final backend/frontend images generated SPDX JSON SBOMs and both scan gates reported zero fixable High/Critical findings. Pinned base digests own the reproducible OS package set; broad mutable distro upgrades are absent. The backend also removed Xvfb/X server and still launched Chromium 151 as non-root.
- ECR policy malicious fixtures prove `YES`/`PARTIAL` and unclassified High/Critical findings block. No-fix High/Critical blocks unless both explicit review and a reference are supplied. Missing, failed, or basic-only scan output blocks. The safe enhanced-scan control passes.

### 2026-08-24 — Slice 10 production closeout gate

- **NO-GO remains in force.** All fifteen source findings are closed and the
  application-security AWS entry gate is clear, but production closeout cannot run
  before the separate AWS implementation plan.
- `crawlerai-aws-codex-implementation-plan.md` is QUEUED with all slices TODO. No
  `infra/aws/` stack exists. Therefore no deployed CrawlerAI RDS, Redis, EFS, ECS,
  ALB, Cloudflare host, enhanced ECR result, restore drill, or rollback drill exists
  to verify.
- Read-only AWS caller identity succeeded on 2026-08-24. This proves credentialed
  account access only. It is not proof of a CrawlerAI stack, control, owner, or
  permission to make live changes.
- `docs/plans/CRAWLERAI_AWS_OWNER_RUNBOOK.md` is the canonical fail-closed evidence
  register. Every live gate is BLOCKED, five P2 operational risks are unaccepted,
  and all operational roles are UNASSIGNED. No expiry was fabricated for an
  unaccepted risk.
- Slice 10 remains BLOCKED until the AWS plan is implemented, live Cloudflare/AWS
  checks pass, restore and controlled rollback drills succeed, and named primary
  and backup owners sign the GO decision.
