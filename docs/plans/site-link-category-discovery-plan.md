# Plan: Site-Link Category Discovery for Crawl Studio

**Created:** 2026-06-04
**Agent:** Codex
**Status:** DONE
**Touches buckets:** Crawl Ingestion + Orchestration, Acquisition + Browser Runtime, API, Frontend, Documentation

## Goal

Replace the current sitemap/homepage-only category discovery with a Crawl Studio-owned category discovery API that can crawl rendered site links, follow bounded nested category-like links, and return validated category/listing URLs. Playground must consume that API instead of owning discovery logic, so Crawl Studio and Playground share one discovery contract. Existing sitemap behavior stays as the fast first tier; browser/rendered link discovery is a fallback or explicit mode, not a new extraction pipeline.

## Acceptance Criteria

- [x] Crawl Studio exposes a category discovery API that accepts one or more seed URLs, limit, depth/budget options, and returns grouped category URLs, sources, nav tree, errors, and diagnostics.
- [x] Discovery order is deterministic: sitemap/static homepage first, rendered homepage/site-link crawl second when static discovery is empty, thin, blocked, invalid, or explicitly requested.
- [x] Browser site-link discovery uses normal acquisition/browser runtime and does not parse markdown as the source of links.
- [x] Nested discovery follows only same-origin, public, canonicalized links within configured depth/page/link budgets.
- [x] Returned category URLs are scored and filtered so utility links such as login, client-service, stores, privacy, search, media, and editorial/experience pages do not outrank real category/listing URLs.
- [x] Optional listing validation keeps category candidates only when rendered/static evidence shows listing-grid/product-card signals.
- [x] Sitemap-mode batch runs in Crawl Studio use the same improved resolver, so direct Crawl Studio runs benefit without Playground-specific code.
- [x] Playground discovery calls the shared Crawl Studio category discovery contract and stores the API response shape in existing `step_data["sitemap"]` compatibility fields.
- [x] Existing detail/listing classification behavior remains unchanged for direct detail/listing URLs.
- [x] `python -m pytest tests -q` exits 0.

## Do Not Touch

- `backend/app/services/pipeline/persistence.py` — discovery must not compensate downstream or change persisted record semantics.
- `backend/app/services/extract/detail_extractor.py` — this plan discovers category/listing URLs only; it does not change PDP extraction.
- `backend/app/services/extract/listing_extractor.py` — listing extraction may be used for validation signals only through public behavior, not rewritten.
- `backend/app/services/playground_service.py` downstream extract/enrich/compare/monitor/audit flows — only discovery handoff changes.
- Public API v1 routes under `backend/app/api/public/*` — this is authenticated console/Crawl Studio behavior, not public extraction.

## Slices

### Slice 1: Shared Discovery Contract and Static Resolver Facade
**Status:** DONE
**Files:** `backend/app/schemas/crawl.py`, `backend/app/services/crawl/sitemap_resolver.py`, `backend/app/services/config/sitemap.py`, `backend/tests/component/test_sitemap_resolver.py`
**What:** Define typed request/response objects for category discovery while preserving the current `SitemapResolutionResult` compatibility path. Add config-owned budgets for max depth, rendered page budget, candidate validation budget, and thin-result thresholds. Make static sitemap/homepage discovery return richer diagnostics: attempted URLs, blocked HTTP statuses, invalid XML, timeout, static candidate counts, and reject reasons where available.
**Verify:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/component/test_sitemap_resolver.py -q` (25 passed, 2026-06-04)

### Slice 2: Rendered Site-Link Frontier Discovery
**Status:** DONE
**Files:** `backend/app/services/crawl/site_link_discovery.py`, `backend/app/services/crawl/sitemap_resolver.py`, `backend/app/services/config/sitemap.py`, `backend/tests/component/test_site_link_discovery.py`
**What:** Add a Crawl-owned rendered discovery helper that uses normal acquisition/browser runtime to fetch seed pages, harvest visible rendered DOM anchors, canonicalize/dedupe same-origin URLs, score category/listing candidates, and walk a bounded breadth-first frontier. Keep it observational: URL, final URL, status, diagnostics, link context, score, reject reason. Do not extract product fields and do not use markdown as input.
**Verify:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/component/test_site_link_discovery.py -q` (5 passed, 2026-06-04)

### Slice 3: Candidate Validation and Batch Runtime Reuse
**Status:** DONE
**Files:** `backend/app/services/crawl/site_link_discovery.py`, `backend/app/services/crawl/batch_runtime.py`, `backend/app/services/crawl/sitemap_resolver.py`, `backend/tests/regression/test_batch_runtime.py`, `backend/tests/component/test_site_link_discovery.py`
**What:** Wire the improved resolver into existing sitemap-mode batch runs. Add optional candidate validation that probes likely category URLs and keeps those with listing/card/grid evidence. Preserve explicit user controls: do not rewrite `surface`, traversal intent, proxy settings, or LLM settings. Ensure static sitemap success remains fast and rendered fallback only runs on empty/thin/error cases or explicit strategy.
**Verify:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/regression/test_batch_runtime.py tests/component/test_site_link_discovery.py -q` (targeted commands passed, 2026-06-04)

### Slice 4: Crawl Studio Category Discovery API
**Status:** DONE
**Files:** `backend/app/api/crawls.py`, `backend/app/schemas/crawl.py`, `backend/tests/component/test_crawl_api.py`
**What:** Add an authenticated Crawl Studio endpoint, for example `POST /api/crawls/category-discovery`, that calls the shared resolver for one or more seeds and returns the grouped discovery response. Keep the endpoint launch-only/read-only: no crawl run or records are created by discovery itself. Include source labels such as `sitemap`, `homepage`, `rendered_homepage`, `rendered_nested`, and `mixed`.
**Verify:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/component/test_crawls_category_discovery_api.py -q` (1 passed, 2026-06-04)

### Slice 5: Playground Uses Crawl Studio API Contract
**Status:** DONE
**Files:** `backend/app/services/playground_service.py`, `backend/app/api/playground.py`, `frontend/lib/api/client.ts`, `frontend/app/playground/page.tsx`, `backend/tests/component/test_playground_service.py`, `frontend/app/playground/playground-nav-tree.test.tsx`
**What:** Remove Playground's direct resolver ownership. Playground discovery should call the same Crawl Studio category discovery service/API contract and store the result under existing `step_data["sitemap"]` fields (`urls`, `groups`, `trees`, `sources`, `errors`, `total_found`, `limit`) so current UI behavior survives. Update labels from “sitemap” toward “category discovery” where user-facing copy would otherwise be misleading.
**Verify:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/component/test_playground_service.py -q` (20 passed, 2026-06-04); `cd frontend; npm test -- playground` (3 passed, 2026-06-04)

### Slice 6: Live Probe and Documentation
**Status:** DONE
**Files:** `docs/CODEBASE_MAP.md`, `docs/BUSINESS_LOGIC.md`, `docs/backend-architecture.md`, `backend/run_acquire_smoke.py` or a focused temporary-free smoke command if existing smoke supports discovery
**What:** Document the shared category discovery decision point and ownership. Run the luxury-site set from `TEST_SITES.md` with a small budget and record observed reasons: static block, rendered success, validation rejection, or timeout. Remove any temporary probes before marking done.
**Verify:** `cd backend; .\.venv\Scripts\python.exe -m pytest tests/component/test_sitemap_resolver.py tests/component/test_site_link_discovery.py tests/component/test_crawls_category_discovery_api.py tests/component/test_playground_service.py tests/regression/test_batch_runtime.py -q` (54 passed, 2026-06-04); `cd backend; .\.venv\Scripts\python.exe -m pytest tests -q` (1326 passed, 2026-06-04); `cd frontend; npm run lint` (passed, 2026-06-04); `cd frontend; npm test` (133 passed, 2026-06-04); live discovery smoke ran against Coach, Kate Spade, Tory Burch, Burberry, Prada, Fendi, Balenciaga, and Armani.

## Doc Updates Required

- [x] `docs/backend-architecture.md` — add shared Crawl Studio category discovery flow and budgets.
- [x] `docs/CODEBASE_MAP.md` — add any new `crawl/site_link_discovery.py` owner entry and Crawl API endpoint note.
- [x] `docs/BUSINESS_LOGIC.md` — update sitemap/category discovery decision: static first, rendered fallback, Playground consumes Crawl Studio contract.
- [x] `docs/INVARIANTS.md` — not required; acquisition/user-control contracts preserved.
- [x] `docs/ENGINEERING_STRATEGY.md` — not required; no new anti-pattern.

## Notes

- Current failure evidence on 2026-06-04: Coach and Kate Spade return HTTP 403 for static sitemap/homepage; Burberry sitemap is invalid XML and static homepage has no category candidates; Prada and Fendi hit read timeouts; Armani can find homepage links after about 45s but Playground's per-input timeout is 20s.
- Existing traversal (`scroll`, `load_more`, `paginate`) expands a known listing page. It does not own domain-level nested category discovery. This plan adds a bounded discovery frontier before normal listing extraction.
- Markdown is not a link source for this plan. Rendered DOM anchors are the source; markdown may be returned later as display evidence only if needed.
- The previous active plan was queued, not in progress. It was moved into `ACTIVE.md` queue while this explicitly assigned plan is active.
- Live smoke after implementation, small budget: Tory Burch and Balenciaga returned 5 category URLs via homepage discovery; Armani returned `homepage+rendered_site_links` and utility links were reduced to a single gift-category candidate after generic legal/cookie/digital-card filtering; Coach, Kate Spade, Burberry, Prada, and Fendi still timed out under the bounded smoke budget and now report timeout/error diagnostics through the shared response.
