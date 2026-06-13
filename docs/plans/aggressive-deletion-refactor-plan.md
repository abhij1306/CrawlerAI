# Plan: Aggressive Deletion Refactor

**Created:** 2026-06-12
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Bucket 1 (API + bootstrap), Bucket 2 (crawl orchestration), Bucket 4 (extraction surface policy), Bucket 6 (review/selectors/domain memory), Bucket 7 (LLM prompt/task registry), Frontend routes/API/types, Alembic/schema, docs/tests

## Goal

Reduce product and code complexity so the app can be productionized for Feedonomics as CrawlerAI. Done means the codebase no longer exposes or imports Playground, AI Discoverability audit, Page Audit, Design Crawl, or non-commerce/non-jobs crawl surfaces. Remaining crawl behavior is limited to commerce and jobs, with dead backend models/routes/services/config/tests/frontend views removed instead of hidden.

## Acceptance Criteria

- [ ] Product naming uses `CrawlerAI` in active docs, app shell, browser title, default settings, service names, and public visual assets; no active `CrawlerAI` references remain outside archived docs or explicitly historical specs.
- [ ] Backend route registration has no Playground, AI Discoverability audit, Page Audit, or Design Crawl endpoints.
- [ ] Backend models, schemas, services, config modules, prompt files, reset paths, and tests for deleted features are removed or replaced by explicit no-reference assertions.
- [ ] Frontend routes, nav entries, API client functions/types, pages, components, and tests for deleted features are removed.
- [ ] Crawl surfaces are limited to commerce and jobs at API validation, public API mapping, field policy, domain memory/profile behavior, frontend controls, and tests.
- [ ] Non-commerce/non-jobs extractors/config/tests are deleted only after their imports are gone.
- [ ] Alembic/database handling is explicit: either drop deleted feature tables with a forward migration or reset pre-production migration history in one documented step.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
- [ ] Frontend typecheck/test command exits 0.

## Do Not Touch

- `backend/app/services/product_intelligence/*` - still relevant to commerce production workflows unless separately removed.
- `backend/app/services/data_enrichment/*` - still relevant to commerce Feedonomics enrichment unless separately removed.
- `backend/app/services/monitor*`, `backend/app/services/alert*`, `backend/app/api/monitors.py`, `backend/app/api/alerts.py`, `backend/app/api/public_alerts.py` - alerting/monitoring is outside this deletion request.
- `backend/app/services/acquisition/*`, `backend/app/services/fetch/*`, `backend/app/services/pipeline/*` - keep shared crawl runtime; only remove references to deleted features/surfaces.
- `backend/app/data/enrichment/shopify_*.json` - large taxonomy data remains commerce-owned.
- `docs/archive/**` - historical only; do not churn unless a live import/link points there.

## Slices

### Slice 1: Final Inventory and Kill List
**Status:** TODO
**Files:** `backend/app/main.py`, `backend/app/models/__init__.py`, `backend/app/schemas/*`, `backend/app/services/*`, `frontend/src/router.tsx`, `frontend/lib/api/*`, `frontend/components/layout/app-shell.tsx`, relevant tests
**What:** Build exact reference inventory with `rg` for `playground`, `ucp_audit`, `page_audit`, `design_system`, `design crawl`, `CrawlerAI`, and every internal surface. Decide database path for deleted tables before code deletion.
**Verify:** Save kill list in Notes. No implementation changes in this slice.

### Slice 2: Delete Playground End to End
**Status:** TODO
**Files:** `backend/app/api/playground.py`, `backend/app/services/playground_service.py`, `backend/app/models/playground.py`, `backend/app/schemas/playground.py`, `backend/tests/component/test_playground_service.py`, `frontend/app/playground/*`, `frontend/src/router.tsx`, `frontend/lib/api/*`, nav/sidebar files
**What:** Remove route registration, model exports, user relationship, schemas, service, frontend page, route, API methods/types, nav entry, tests, docs references. Remove queued Agentic Browser Playground plan from active queue or mark obsolete.
**Verify:** `rg -n "playground|PlaygroundSession|/playground" backend/app backend/tests frontend docs --glob '!docs/archive/**'` returns only intentional historical plan notes, then run focused backend import/structure tests.

### Slice 3: Delete AI Discoverability Audit
**Status:** TODO
**Files:** `backend/app/api/ucp_audit.py`, `backend/app/services/ucp_audit/*`, `backend/app/services/config/ucp_audit.py`, `backend/app/services/config/aid_score.py`, `backend/app/models/ucp_audit.py`, `backend/app/schemas/ucp_audit.py`, `backend/app/data/prompts/aid_discoverability_audit.*.txt`, UCP tests, `frontend/app/ucp-audit/*`, nav/API/types
**What:** Remove audit route, service package, config, models, schemas, LLM task registration/payload handling, prompt files, dashboard reset rows, frontend page/nav/API/types/tests.
**Verify:** `rg -n "ucp_audit|UCPAudit|AI Discoverability|aid_discoverability" backend/app backend/tests frontend docs --glob '!docs/archive/**'` has no active code hits.

### Slice 4: Delete Page Audit and Design Crawl
**Status:** TODO
**Files:** `backend/app/api/page_audit.py`, `backend/app/services/page_audit/*`, `backend/app/services/config/page_audit.py`, `backend/app/models/page_audit.py`, `backend/app/schemas/page_audit.py`, page-audit tests, `frontend/components/crawl/page-audit-workspace.tsx`, `frontend/components/crawl/crawl-audit-mode.tsx`, `frontend/components/crawl/design-crawl-submit.ts`, `backend/app/services/design_system.py`, `backend/app/services/config/design_system.py`, `backend/app/data/prompts/design_system_markdown.*.txt`
**What:** Remove page-audit endpoint/service/model/schema/config/tests, remove Crawl Studio audit mode UI, remove design-crawl submit path, remove design-system markdown service/config/prompts/tests, and simplify crawl config screen to crawl-only mode.
**Verify:** `rg -n "page_audit|PageAudit|page-audit|crawl-audit|design_system|design crawl|design-crawl" backend/app backend/tests frontend docs --glob '!docs/archive/**'` has no active code hits.

### Slice 5: Contract Surfaces to Commerce and Jobs
**Status:** TODO
**Files:** `backend/app/services/config/field_mappings.py`, `backend/app/services/field_policy.py`, `backend/app/services/surface_detection.py`, `backend/app/services/surface_hints.py`, `backend/app/services/extract/content_surface_extractor.py`, `backend/app/services/extract/table_extractor.py`, crawl schemas, public API config/service, frontend crawl form/types/tests, surface tests
**What:** Keep only `ecommerce_listing`, `ecommerce_detail`, `job_listing`, and `job_detail` internally. Remove automobile, content, article, forum, and tabular routes through validation, public API aliases, field policy, extraction handlers, frontend options, acceptance manifests, and tests. Delete now-unused extractor modules/config only after imports are gone.
**Verify:** Focused surface tests plus `rg -n "automobile|content_listing|content_detail|article_|forum_|tabular" backend/app backend/tests frontend --glob '!backend/app/data/**'` has no active code hits except unrelated natural-language data.

### Slice 6: Rename CrawlerAI to CrawlerAI
**Status:** TODO
**Files:** `backend/app/core/config.py`, `backend/app/core/celery_app.py`, frontend app shell/title/logo/theme assets, active docs, test expectations
**What:** Replace active brand strings and assets with `CrawlerAI`. Rename logo asset from `crawlerai-logo.svg` to `crawlerai-logo.svg` or replace with existing CrawlerAI asset. Keep lowercase technical prefixes like `crawlerai-*` where already correct.
**Verify:** `rg -n "CrawlerAI|crawlerai|CRAWLERAI" backend/app backend/tests frontend docs --glob '!docs/archive/**'` returns only explicitly historical docs/specs that are either updated or documented as out of scope.

### Slice 7: Database and Migration Cleanup
**Status:** TODO
**Files:** `backend/alembic/versions/*playground*`, `*ucp_audit*`, `*page_audit*`, new migration if needed, model bootstrap tests
**What:** Choose one database path. If no production DB exists, delete pre-production feature migrations and validate a clean migration chain. If existing DBs must upgrade, add a forward migration dropping `playground_sessions`, `ucp_audit_*`, and `page_audit_*` tables, then keep old migrations for history. Update structure tests accordingly.
**Verify:** Alembic upgrade on empty DB succeeds. Model metadata no longer registers deleted tables.

### Slice 8: Docs, Structure Gates, Full Verify
**Status:** TODO
**Files:** `docs/CODEBASE_MAP.md`, `docs/BUSINESS_LOGIC.md`, `docs/INVARIANTS.md`, `docs/backend-architecture.md`, `docs/frontend-architecture.md`, `backend/tests/regression/test_structure.py`, this plan, `docs/plans/ACTIVE.md`
**What:** Remove deleted feature ownership from active docs, update app description to CrawlerAI commerce/jobs scope, add structure gates that fail on deleted feature imports/routes/surfaces, run full backend and frontend verification, then mark plan done.
**Verify:** Backend full tests and frontend typecheck/tests pass.

## Doc Updates Required

- [ ] `docs/CODEBASE_MAP.md` - remove deleted owners and narrow surfaces.
- [ ] `docs/BUSINESS_LOGIC.md` - remove deleted product behaviors and update surviving surface contracts.
- [ ] `docs/INVARIANTS.md` - delete Playground/UCP/Page Audit invariants and update surface invariant.
- [ ] `docs/backend-architecture.md` - remove endpoints/models/services and update API surface list.
- [ ] `docs/frontend-architecture.md` - remove routes/components and update navigation/API map.
- [ ] `docs/ENGINEERING_STRATEGY.md` - update project name and add anti-reintroduction gate only if a new recurring bloat pattern appears.

## Notes

- Initial grep found the delete targets spread across backend API registration, ORM exports, schemas, services, config, prompts, dashboard reset, frontend routes/nav/API/types/components, tests, Alembic migrations, and active docs.
- Existing `docs/plans/ACTIVE.md` had no active plan. Queue includes a blocked LOC plan and an Agentic Browser Playground plan. This plan should supersede the queued Playground work because Playground is now a deletion target.
- Database decision is the main open point: pre-production reset is cleaner; forward drop migration is safer if any existing environment must upgrade.
