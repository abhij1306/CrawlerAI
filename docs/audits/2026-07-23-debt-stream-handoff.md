# Audit-Debt Stream Handoff — 2026-07-23

Continuation of `docs/audits/2026-07-22-fix-stream-handoff.md`. Remaining MEDIUM/LOW/INFO debt from
`docs/audits/2026-07-21-full-stack-audit.md` is **fully implemented** on two branches per the approved plan
(37 commit-sized chunks, all landed). PRs are being opened; adversarial test verification was in flight at
handoff time.

## Branches (both pushed)

### `vorflux/audit-debt-backend` — 28 commits on main (`751c4ca`)
- **Stream A (security/scalability, 12 commits):** CSV formula-injection escaping (`core/shared/csv_safety.py`,
  all 4 export write sites + headers); WS log-stream Origin check; `UserRegister` min_length=12 +
  `UserUpdate.role` Literal; `/docs`+`/api/metrics` gated outside dev (bearer `METRICS_AUTH_TOKEN`);
  Dockerfile `uv sync --locked --no-dev --extra prod`; domain cookie-state Fernet encryption at rest +
  Alembic data migration `20260722_0004` (idempotent, legacy passthrough, wrong-key→None); proxy endpoint
  validation at run creation (`CRAWLER_PROXY_ENDPOINT_VALIDATION_ENABLED`); `POST /api/auth/logout`
  (token_version bump + cookie clear); `redis_execute()` (bypasses `redis_state_enabled` gate) + Redis Lua
  sliding-window rate limiting (middleware/auth/public API) + Redis per-host pacing; WS poll backoff
  (`log_stream_max_poll_ms` 5000); fallback log caps without Redis + `session.refresh` removal; worker-pool
  URL scheduling in `batch_runtime.py`; public API-key principal cache (60s TTL, 300s touch throttle);
  slim `source_trace.browser_diagnostics` (allowlist: `browser_reason`, `detail_expansion`);
  `delete_run` artifact-tree cleanup + daily `maintenance.sweep_run_artifacts` beat task
  (`run_artifacts_retention_days` 30); `find_contract_location` single JSONB-containment query; shared
  robots httpx client.
- **Stream B (dead-code/maintainability, 14 commits):** CODEBASE_MAP Bucket 6 + INVARIANTS §3/§9 rewrites;
  evaluation module deletions (`baseline.py`, `llm_repair.py`); dead constants/routes/smoke-script deletions
  (404 pins in `test_deadcode_routes.py`); helper hoists (`workers/base.py`, lazy `_browser_pool()` accessors,
  `text_coerce.clean_str`, `url_utils.looks_like_locale_segment`, `traversal_helpers.RECOVERABLE_ERRORS`);
  `ai_visibility/_provider_http.py`; `schemas/job_lifecycle.py` shared bases (Sequence-typed);
  CASCADE flag removal + legacy branch deletion; 48 silent-except diagnostics; 3 behavioral test files
  (matching ladder, enrichment transitions, dispatchers); `PublicRecord`/`URLMetrics` TypedDicts;
  conftest `real_dns`/`real_redis` opt-out markers; 5 function decompositions (incl. `resolve`).
- **Simplify pass** `f1434d8` + **mypy fix** `a19609d` (10 branch-introduced errors → 0; CI gate clean).
- Verified: mypy 0 errors (381 files), ruff clean, ledger pair 60/60 (TOTAL 87,900), ~900 focused tests green,
  two review rounds → READY FOR PR.

### `vorflux/audit-debt-frontend` — 14 commits on main (`751c4ca`)
C1 CSV escape + image referrerPolicy + 5xx generic messages · C2 sidebar logout button · C3 build-time CSP
meta + `public/theme-init.js` · C4 dead sweep (msw, 8 CSS rules, config rot, de-exports) · C5 prefill/helper/
ActionButton dedupes · C6 dead review-surface removal + `run_health` type · C7 API facade deleted → direct
domain imports (24 files) · C8 admin/llm React Query rewrite (650→256 LOC) · C9 tab view-models + log-stream
buffering/windowing/shared clock · C10 default 400-LOC budgets · C11 `components/domain-memory/` move +
`@lib`/`@ui` aliases · C12 telemetry base-URL + records-table heights/rAF scroll · simplify `334474e` ·
review fixes `0fe990b` (log-window zebra parity + jump-to-hidden-group).
Verified: 240/240 tests, vp check/build/check:policy green, review verdict READY FOR PR.

## Remaining work (in order)

1. **Finish adversarial test verification** — testing agent `test-audit-debt` was mid-run at handoff.
   Test plan: `/code/.plans/v1-test-plan.md` (approved). Key probes: CSV exports incl. headers; deleted
   routes 404 vs kept siblings; login→logout→401 E2E; metrics gating under prod env; WS origin; cookie
   encryption + migration idempotency; Redis cross-process rate limits; log caps; principal cache;
   artifact sweeper; production-build CSP; UI evidence via agent-browser. Env: backend on :8001 (8000 is
   squatted by `docker-web-1`), Postgres `crawlerai-db` on **5433** (`export
   TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/test_db"` — 5432 is Searchify's
   DB), Redis `crawlerai-redis` on 6379, repo-root `.env` has JWT/ENCRYPTION keys, frontend worktree at
   `/code/abhij1306/CrawlerAI-fe` (no `.env` — pass `VITE_API_BASE_URL`). Full setup notes:
   `/memory/testing/crawlerai/setup.md`. Then publish ONE Test Report via `vflux_exec test-report submit`.
2. **PRs** — create via `vflux_exec pr create` (backend first): bodies must include the audit-item → commit
   mapping and the full Testing section (see `/code/.skills/system/pr-description.md`). Update Testing with
   the agent's final results.
3. **Merge order: backend PR first, then frontend** (logout button needs `POST /api/auth/logout`; frontend
   handles the 404 gracefully until then).
4. **Update `docs/audits/2026-07-21-full-stack-audit.md`** — mark medium/low items resolved after merge.

## Accepted decisions (plan-approved)

- 1.6: encrypt + document shared trust model (NO user_id scoping — INVARIANTS §9). 2.9: adaptive backoff
  (no pub/sub). 2.13: JSON export provenance slims `browser_diagnostics` (release note). 1.10: validation
  only (no cred encryption). 4.12: no renames (CODEBASE_MAP owner notes instead). 7.3: no openapi codegen.
- Compat notes: effective rate limits now global (login 20/min→10/min at 2 workers); pause/kill lets
  in-flight URLs finish (was cancel); 5xx API errors render generic message + request id.

## Ops actions (user/deploy — not code)

1. **5.4:** rotate JWT_SECRET_KEY, ENCRYPTION_KEY, POSTGRES_PASSWORD, DEFAULT_ADMIN_PASSWORD for the preview
   environment (were live at audit time).
2. **5.5 complement:** static SPA host headers `frame-ancestors 'none'`, `nosniff`, `Referrer-Policy`.
3. **Chunk C deploy ordering:** run Alembic migration AFTER all workers run new code.

## Environment gotchas (new this session)

- Postgres: dedicated `crawlerai-db` container on **5433** (postgres/postgres, db `test_db`); the 5432
  container belongs to Searchify — conftest's default `TEST_DATABASE_URL` points there and auth-fails.
- `uv` installed via `python3 -m pip install uv` → `~/.local/bin`; venv: `uv sync --locked --extra dev`.
- pnpm: after removing `msw`, `pnpm-workspace.yaml` needs `allowBuilds: msw: false` (optional peer of
  `@vitest/mocker`) or every install hard-fails `ERR_PNPM_IGNORED_BUILDS`. Already committed on the
  frontend branch; do not delete that entry.
- Parallel tracks used `git worktree add /code/abhij1306/CrawlerAI-fe vorflux/audit-debt-frontend`
  (+ `pnpm install` inside; the worktree has no `.env`/`.venv`).
