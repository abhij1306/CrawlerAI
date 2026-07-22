# Backend Architecture

> Last updated: 2026-06-29
>
> Canonical detailed backend reference. This is the merged replacement for the older split architecture docs.
>
> **Rebuild in progress.** The Site & Product Knowledge Graph rebuild (`docs/plans/site-knowledge-graph-master-plan.md`) is reshaping extraction, artifacts, and observability. Slices 1-4 are landed (single-writer artifacts, self-contained `diagnose.json`/`report.json`, deleted observability/audit modules, the `app/core/config/knowledge_graph.py` vocabulary owner, and architecture ratchets). The extraction file inventory in §6.4 below predates the `app/extraction/` package consolidation and is being superseded; treat `docs/INVARIANTS.md` §3, §12, §17 and `tests/unit/test_extraction_architecture.py` as authoritative for current extraction/artifact boundaries.

## 1. Scope

CrawlerAI backend is a crawl execution, extraction, review, and export system with:

- authenticated FastAPI APIs
- Postgres persistence
- Redis-backed runtime state
- Celery execution
- pooled HTTP and browser acquisition
- structured-source and DOM extraction
- selectors, review, and domain-memory feedback loops
- admin-managed LLM configuration and optional task/runtime assistance

## 2. Runtime Stack

- API: FastAPI in `backend/app/main.py`
- Worker: Celery in `backend/app/tasks.py`
- DB: SQLAlchemy async + Alembic
- Cache/runtime state: Redis
- HTTP: `httpx` plus `curl_cffi`
- Browser: Playwright
- Parsing: BeautifulSoup, `glom`, `jmespath`, `lxml`, `extruct`, `w3lib`

## 3. Registered API Surface

Routers registered in `backend/app/main.py`:

- `/api/auth`
- `/api/users`
- `/api/dashboard`
- `/api/crawls`
- `/api/crawls/{run_id}/records`
- `/api/records/{record_id}/provenance`
- `/api/jobs`
- `/api/review`
- `/api/selectors`
- `/api/knowledge`
- `/api/llm`
- `/api/data-enrichment`
- `/api/product-intelligence`
- `/api/v1`
- `/api/health`
- `/api/metrics`

Important route groups:

- `api/crawls.py`: create runs, category discovery, CSV ingestion, logs, websocket updates, pause/resume/kill, commit fields, commit LLM suggestions
- `api/crawl_domain.py`: domain recipe, domain run-profile, field feedback, and cookie-memory routes under `/api/crawls`
- `api/records.py`: records list plus JSON/CSV/discoverist exports and provenance
- `api/review.py`: review payload, artifact HTML, save review mapping
- `api/selectors.py`: selector CRUD, cross-surface listing by domain, suggestion, test, preview HTML
- `api/knowledge.py`: authenticated graph/site/entity/contract reads, operator source selection, admin rebuild, purge, and per-site delete
- `api/llm.py`: provider catalog, config CRUD, connection test, cost log
- `api/data_enrichment.py`: on-demand ecommerce detail enrichment jobs and enriched product row lookup
- `api/product_intelligence.py`: product discovery, candidate crawl jobs, match scoring, and review
- `api/public/*`: API-key authenticated extraction, domain info, capabilities, and envelopes

Routes with no console UI by design (do not delete as "dead"):

- `POST + GET /api/api-keys` (`api/api_keys.py`) — operator API, no console UI by design; the only key-creation surface backing the public `/api/v1` API
- `GET /api/crawls/{run_id}/export/discoverist` (`api/records.py`) — documented external partner contract, no console caller by design

Domain-recipe routes live under `api/crawl_domain.py`:

- `GET /api/crawls/domain-run-profile` — lookup saved run-profile defaults by normalized `(domain, surface)` for single-URL Crawl Studio auto-load
- `GET /api/crawls/{run_id}/domain-recipe` — completed-run payload containing requested-field coverage, grouped winning selector candidates, acquisition evidence, per-field learning state, affordance hints, saved selectors, and the saved domain run profile
- `POST /api/crawls/{run_id}/domain-recipe/promote-selectors` — promote selected winning selector candidates into exact-surface domain memory
- `POST /api/crawls/{run_id}/domain-recipe/save-run-profile` — save the reusable fetch/locality/diagnostics profile for the run's normalized `(domain, surface)`
- `POST /api/crawls/{run_id}/domain-recipe/field-action` — keep/reject field-local learning evidence and deactivate exact-surface saved selectors when a selector-backed field is rejected
- `GET /api/crawls/domain-memory/cookies` — compact domain-scoped cookie-memory summary for the Domain Memory workspace

## 4. Crawl Request and Settings Contract

`CrawlCreate` currently accepts:

- `run_type`: `crawl | batch | csv`
- `url` and/or `urls`
- `settings`
- `requested_fields`
- `additional_fields`

Current live behavior:

- batch and crawl run creation preserve raw user-entered `requested_fields` / `additional_fields` on the run, while runtime-only canonicalization happens later when extraction and confidence scoring need alias matching
- batch run settings persist the resolved `urls` list inside `CrawlRunSettings`, so `crawl/batch_runtime.py` fans out the same URL set that the create request submitted
- category discovery is exposed as `POST /api/crawls/category-discovery`; it returns candidate category/listing URLs only and does not create runs or records

`CrawlRunSettings` normalizes settings for storage/runtime. Important fields include:

- `proxy_list`
- `fetch_profile`
- `locality_profile`
- `diagnostics_profile`
- `advanced_enabled` / `advanced_mode` as UI-mode compatibility fields
- resolved traversal mode derived from explicit `fetch_profile.traversal_mode`; legacy `auto` traversal is normalized to a default explicit mode- `max_records` as a traversal stop target, not a persisted-row hard cap
- `sleep_ms`
- `respect_robots_txt`
- `url_batch_concurrency`
- local in-process dispatch is serial when `CELERY_DISPATCH_ENABLED=false`; Celery-enabled runs may use the configured URL batch concurrency
- every URL is processed in an owned SQLAlchemy session so a URL-local failed transaction cannot poison run orchestration or later URLs
- `url_timeout_seconds`
- `llm_enabled`
- `extraction_contract`
- `llm_config_snapshot`
- `extraction_runtime_snapshot`

Current live behavior:

- nested run-profile settings are the canonical execution-shaping contract: `fetch_profile`, `locality_profile`, and `diagnostics_profile`
- `create_crawl_run()` resolves single-URL settings in this order: generic UI defaults, saved `DomainRunProfile.fetch/locality/diagnostics` defaults, explicit user edits from Crawl Studio, then backend normalization/snapshotting
- acquisition-contract reuse is not snapshotted into the run at create time; `pipeline/core.py` resolves it per URL for crawl/batch/CSV as `explicit settings -> saved DomainRunProfile(domain, surface) -> defaults`
- saved run profiles are limited to execution defaults only and intentionally exclude selector rows, proxies, LLM config/budgets, requested fields, cookies, auth/session state, and user identifiers
- Crawl Studio now exposes `Quick Mode` and `Advanced Mode` as UI presentation modes only; both dispatch the same nested settings contract to the backend

## 5. High-Level Flow

```text
POST /api/crawls
  -> crawl/ingestion_service
  -> crawl/crud.create_crawl_run
  -> crawl/service.dispatch_run
  -> Celery task process_run
  -> crawl/batch_runtime.process_run
  -> pipeline/core._process_single_url for each URL
  -> acquire page + diagnostics + artifacts
  -> extract records
  -> optional selector self-heal; ecommerce detail never generates missing values with LLM
  -> publish verdict + metrics + source trace
  -> persist CrawlRecord rows and run summary
```

## 6. Subsystem Ownership

### 6.1 API and bootstrap

Primary files:

- `app/main.py`
- `app/api/*`
- `app/core/config.py`
- `app/core/database.py`
- `app/core/redis.py`
- `app/core/security.py`
- `app/core/telemetry.py`
- `app/core/metrics.py`

Responsibilities:

- app startup/shutdown
- migrations on startup
- route registration
- auth/dependencies
- correlation IDs
- health and metrics

Security posture notes:

- Outside dev/test (`APP_ENV` other than development/dev/local/test/testing) the
  interactive API docs are disabled (`docs_url`/`redoc_url`/`openapi_url=None`)
  and `/api/metrics` requires `Authorization: Bearer <METRICS_AUTH_TOKEN>`
  (constant-time compare; 404 when the token is unset, 401 otherwise). The
  `/health` + `/api/health` probes stay open because orchestrators scrape them
  unauthenticated.
- Password hashing is argon2id. `passlib` stays in the dependency tree solely
  to verify legacy pbkdf2_sha256 hashes at login; successful legacy logins are
  rehashed to argon2 transparently, so passlib must not be used for new hashes.
- The backend image builds with `uv sync --locked --no-dev --extra prod`: the
  lockfile is the only dependency source, dev extras never ship, and the prod
  extra keeps `psycopg2` install-time compilation isolated to the image build.

### 6.2 Crawl ingestion and orchestration

Primary files:

- `crawl/ingestion_service.py`
- `crawl/service.py`
- `crawl/crud.py`
- `crawl/events.py`
- `crawl/batch_runtime.py`
- `crawl/category_discovery.py`
- `crawl/sitemap_resolver.py`
- `crawl/site_link_discovery.py`
- `crawl/profile/*`
- `pipeline/core.py`
- `pipeline/record_extraction_stage.py`
- `pipeline/retry/stage.py`
- `pipeline/types.py`
- `pipeline/runtime_helpers.py`
- `data_enrichment/service.py`
- `data_enrichment/deterministic.py`
- `data_enrichment/shopify_catalog.py`

Responsibilities:

- create runs from payloads and CSV uploads
- stamp run snapshots
- dispatch and recover runs
- process URLs
- discover category/listing URLs from static sitemaps/homepages and rendered same-origin site links
- load, merge, persist, and learn reusable domain run-profile acquisition settings
- persist records and summary state
- create on-demand enrichment jobs from persisted ecommerce detail records
- normalize deterministic enrichment fields and match Shopify taxonomy/attributes; taxonomy matching uses exact Shopify path/leaf matches first, then deterministic token scoring, with LLM backfill only when explicitly enabled
- emit logs and progress

Current live behavior:

- local startup recovery only reclaims stale active runs: fresh `pending` rows without a local task id are left alone, while stale `running` rows are forced into `failed` and stale local-dispatch `pending` rows are forced into `killed` so interrupted work does not stay orphaned forever
- batch execution now refreshes `last_heartbeat_at` as runs advance so startup recovery can distinguish live external workers from truly stale local work
- per-URL failures now roll back and reload the active DB session, persist URL-level error metrics/diagnostics, and continue the batch; mixed success/error runs finish `completed` with aggregate verdict `partial`, and persisted records remain exportable
- per-URL pipeline calls return `URLProcessingResult`; tuple result compatibility is removed so batch orchestration depends on the typed public result interface
- acceptance harness runs now support curated manifest-driven site sets with bucketed expectations, explicit acceptance surfaces remain authoritative instead of being silently re-inferred from URLs, and curated commerce rows can reuse artifact-backed run ids before falling back to live execution
- acceptance reports now distinguish transport verdicts from output quality through `quality_verdict`, `observed_failure_mode`, and `quality_checks`, so runs that technically succeed but return shell pages, promo pages, chrome-heavy listings, or broken variant semantics no longer look healthy
- reusable domain execution defaults are persisted separately from selector memory in `DomainRunProfile`; fetch/locality/diagnostics defaults still merge into single-URL run creation, while acquisition contracts are re-resolved per URL at runtime for every run type
- category discovery runs static sitemap/homepage discovery first, then rendered DOM site-link discovery for empty, thin, blocked, invalid, or explicitly rendered cases; it returns grouped URL evidence and never extracts product fields or parses markdown as a link source
- `pipeline/extraction_loop.py` stays the per-URL stage orchestrator; record extraction, acquisition-contract memory, retry families, direct-record LLM fallback, browser diagnostics merge, typed result objects, and public failure-state persistence live in dedicated pipeline helper modules
- Data Enrichment is separate from the crawl pipeline: it reads persisted ecommerce detail `CrawlRecord` rows, writes `EnrichedProduct` rows, and only updates source-record enrichment status metadata.
- Product monitoring, product alerts, in-app monitor notifications, and alert MCP wrappers are deleted surfaces. There are no monitor scheduler loops, alert routes, public alert routes, notification models, or monitor-owned run callbacks.
- Public API v1 is a lightweight FastAPI surface under `/api/v1` for Railway-style single-process deployment. API keys are dashboard-owned rows in `ApiKey`; public auth and rate limits are keyed by API key, not client IP. `POST /api/v1/extract` creates a normal single-URL crawl and runs one URL inline with HTTP-only settings, disabled LLM/browser/traversal/screenshots/network capture, and a capped timeout. Batch extraction remains deferred with structured `WORKER_REQUIRED`. `GET /api/v1/domains/{domain}` reads existing `DomainMemory`, `DomainRunProfile`, and recent crawl rows without probing the target. `app/mcp_server/*` is a stateless FastMCP wrapper over `/api/v1` and does not import crawl orchestration internals.
- Alembic is reset for a fresh-start project: `backend/alembic/versions/` intentionally contains one clean baseline migration.

### 6.3 Acquisition and browser runtime

Primary files:

- `acquisition/acquirer.py`
- `acquisition/policy.py`
- `acquisition/runtime.py`
- `acquisition/browser_capture.py`
- `acquisition/browser_runtime.py`
- `acquisition/browser_pool.py`
- `acquisition/browser_page_flow.py`
- `acquisition/browser_result_builder.py`
- `acquisition/browser_page_helpers.py`
- `acquisition/http_client.py` (thin adapter over `runtime.get_shared_http_client`)
- `acquisition/browser_identity.py`
- `acquisition/cookie_store.py`
- `acquisition/pacing.py`
- `acquisition/traversal.py`
- `acquisition/traversal_helpers.py`
- `acquisition/traversal_recovery.py`
- `crawl_fetch_runtime.py`
- `config/runtime_settings.py`
- `config/browser_fingerprint_profiles.py`
- `robots_policy.py`
- `url_safety.py`

Responsibilities:

- safe target validation
- pooled HTTP/browser fetch
- JS-shell and blocked-page escalation
- browser identity generation
- network payload capture
- temporary screenshot staging for browser artifacts
- detail-page expansion
- listing traversal
- cookie policy enforcement
- robots handling when enabled

Current live behavior:

- fetch results carry headers, blocked state, browser diagnostics, transient browser artifacts, and network payload metadata
- callers pass an explicit `AcquisitionPolicy`; `acquirer.py` translates that policy to `crawl_fetch_runtime.fetch_page` knobs so raw fetch-runtime controls stay inside acquisition
- browser runtime is pooled and exposes runtime snapshots
- browser context identity is a minimal, host-OS-coherent UA de-headlessification (no `browserforge`, no fingerprint generator): `build_playwright_context_spec` rewrites the headless `HeadlessChrome` UA token to plain `Chrome` and emits matching `sec-ch-ua` client hints keyed off the host OS, because the engine runs headless bundled Chromium (see `docs/INVARIANTS.md` Rule 6, "Patchright runs headless bundled Chromium")
- browser fetch uses `patchright` as the primary acquisition engine. There is no legacy `playwright-stealth` stack and no silent generic Chromium fallback. Explicit `real_chrome` remains an escalation lane for protected ecommerce detail pages and Product Intelligence native Google discovery when `C:\Program Files\Google\Chrome\Application\chrome.exe` (or `CRAWLER_RUNTIME_BROWSER_REAL_CHROME_EXECUTABLE_PATH`) is available.
- `run_browser_surface_probe.py` is the canonical browser-surface verification harness for acquisition changes. It runs through the same shared browser runtime as crawls and writes timestamped `browser_surface_probe` artifacts with direct JS baseline, Sannysoft/Pixelscan/CreepJS extracted values, consensus drift, connection source metadata, and normalized findings. Report summary/Markdown rendering lives in `browser_surface_probe/report_rendering.py`.
- the browser-surface probe treats `window.chrome.runtime` as healthy when its type is `object`, and its `isTrusted` behavioral smoke now uses real Playwright mouse input against a temporary overlay target instead of JS-dispatched synthetic events, so probe findings reflect actual runtime leaks instead of expected DOM-event semantics
- browser contexts now reload engine-scoped per-run Playwright storage state first and then fall back to engine-scoped domain cookie memory, so `chromium`, `patchright`, and `real_chrome` do not replay each other's cookies/localStorage while still reusing learned state inside the same lane
- domain cookie memory is intentionally filtered acquisition memory, not a verbatim storage-state cache: challenge-only bot-defense state (for example PerimeterX `_px*`, `pxcts`, PX localStorage) is dropped on load/save, and blocked browser runs do not persist domain memory
- blocked browser runs also do not rewrite per-run Playwright storage snapshots, so one challenged detail page does not poison later URLs in the same batch run
- browser-to-HTTP handoff is guarded: only sanitized engine-scoped session state is exported, direct-lane reuse is allowed, proxy-scoped replay is skipped unless proxy affinity is explicit, and drift/challenge re-entry falls back to browser
- shared HTTP acquisition is intentionally shallow: one `curl_cffi` attempt, one `httpx` fallback attempt when curl transport fails, then browser escalation when policy/evidence and remaining budget allow it; there is no hidden multi-attempt HTTP backoff loop inside `fetch_context.py`
- successful acquisition paths can autosave an editable `DomainRunProfile.acquisition_contract`; future runs may reuse a proven browser engine, mark whether curl-cookie handoff is actually eligible, and record whether rendering, traversal, or network payloads were required. Host memory no longer owns the durable success path; it only biases short-lived protection/backoff choices.
- browser diagnostics now persist explicit lane identity (`browser_engine`, `browser_profile`, launch mode, native-context flag, stealth-enabled flag) so metrics and audits can distinguish shaped Chromium from native real Chrome without inferring from free-form logs
- traversal is explicit and separate from browser escalation; only explicit traversal modes are supported
- JSON-expected acquisition now stays in `acquisition/http_client.py`; concrete connectors must consume decoded payloads instead of compensating for transport quirks
- browser network interception is bounded through a small response-queue worker pool with per-endpoint payload budgets instead of untracked background tasks
- platform-specific acquisition URL normalization is not active in the hot path; future connectors may produce artifacts but product-detail URLs still use normal acquisition and extraction
- browser diagnostics now classify `browser_reason` and `browser_outcome`, record phase timings and HTML bytes, and preserve failed browser-attempt evidence even when the final acquisition method stays HTTP
- browser diagnostics now also expose rendered-listing evidence counts (`rendered_listing_fragment_count`, `listing_visual_element_count`) plus stage-aware browser failures (`failure_stage`, `timeout_phase`) so browser-heavy listing regressions can be triaged without replaying the whole run
- rendered-listing-fragment capture and visual-element capture are now bounded by a dedicated runtime timeout and recorded in `phase_timings_ms` (`rendered_listing_fragment_capture`, `listing_visual_capture`) so heavy browser pages cannot stall the whole acquisition tail indefinitely
- browser stages (`navigation`, `settle`, `serialize`, `finalize`) now run in cancellation-aware tasks; if a stage times out or the run is killed mid-flight, the runtime force-closes the page/context before unwinding so local hard-kill does not wait forever on a stuck Playwright DOM call
- acquisition timeout budget is staged: HTTP/curl attempts are capped at `http_timeout_seconds` (10s) per attempt, and browser fallback starts only when at least `browser_retry_min_remaining_seconds` remains for launch/navigation/settling. If the remaining budget is too small, the HTTP observation is returned with `browser_escalation_skipped=insufficient_budget` instead of failing in a predictable browser stage timeout. `browser_only` mode skips the HTTP tier and allocates the full budget to the browser path. The default outer URL-processing ceiling is the processing allowance plus acquisition-attempt allowance plus configured buffer, capped by `max_url_process_timeout_seconds` (default `90 + 90 + 15 = 195s`); an explicit run-level `url_timeout_seconds` remains an exact user control
- shared browser runtimes now recycle once when the driver disconnects during `new_context` / page bootstrap, so a dead browser process does not poison later URLs in the same run
- browser rendering probes extractability at `domcontentloaded`, caps primary `networkidle` navigation to a configured budget slice, uses a short-circuit readiness wait instead of fixed optimistic sleep, reuses settled HTML/analysis for serialization, and limits detail expansion with bounded DOM-first then accessibility-assisted fallback
- browser rendering behavior:
  - checks extractability at `domcontentloaded`
  - caps primary `networkidle` navigation to a configured budget slice
  - uses a short-circuit readiness wait instead of fixed optimistic sleep
  - reuses settled HTML/analysis for serialization
  - limits detail expansion with bounded DOM-first then accessibility-assisted fallback
- detail expansion now skips plain navigation anchors with real `href`s (for example footer/about/careers/returns links) unless they behave like true in-page expanders, which prevents Souled Store-style utility-page navigations during PDP acquisition
- detail expansion also skips header/nav/footer controls outside main content, preventing Lowe's-style pivots from a requested PDP into site chrome or marketing pages
- blocked-page detection is evidence-based: anti-bot vendor markers alone do not block a page, but challenge-specific signals such as CAPTCHA-delivery elements and corroborating blocker text do
- browser outcomes now distinguish challenge pages, low-content terminal shells, and explicit navigation/page-closed failures instead of collapsing them into generic browser HTML
- listing traversal now captures bounded per-step listing snapshots for extraction instead of concatenating full rendered DOMs across page turns, and diagnostics expose traversal fragment count plus traversal HTML bytes
- traversal, browser artifact capture, and listing extraction share listing-card selector/scoring through `extraction/listing.py` and the listing selector banks in `extraction/collectors/*`; traversal is orchestration, not a separate listing-card pipeline
- listing-card counting now falls back to the shared heuristic when configured selectors miss a real grid, and the shared ecommerce selector set accepts case-variant `productCard`-style class names instead of requiring a single casing convention
- traversal-enabled browser fetches now retain both traversal-composed HTML and the full rendered HTML so the pipeline can retry extraction once when traversal fragments produce zero records
- browser block classification now preserves usable listing/detail content when vendor markers and challenge widgets coexist with clear extractable signals, instead of forcing a blocked verdict from anti-bot evidence alone
- traversal stop reasons remain diagnostic when the first rendered listing page is already usable: no-progress traversal keeps the full rendered HTML as the primary payload and only downgrades to `traversal_failed` when listing evidence is still below threshold
- detail-page expansion is field-aware and commerce-safe: default detail acquisition does not click accordions/tabs/carousels just to hunt core fields; requested fields contribute expansion tokens, blocked action labels such as add-to-cart/login are skipped, and ARIA-driven affordances (`aria-expanded`, `aria-controls`, tabs, summaries) are considered only for requested-field expansion inside browser acquisition
- detail-page expansion now short-circuits when the current rendered DOM already exposes the requested section headings, avoiding unrelated follow-up clicks that would otherwise mutate an already-extractable detail page
- thin browser listing results can trigger one bounded recovery re-acquisition that performs ordered listing actions (`clear filters`, `view all`, `next page`) before traversal/extraction, and the pipeline only keeps the retry when it improves record count
- browser acquisition keeps internal rendered-page evidence (rendered HTML, visible text, accessibility snapshots, expansion artifacts, network payloads), but markdown is no longer a first-class runtime/export artifact
- browser screenshots are staged to temp files inside the artifacts area and then persisted by the pipeline, avoiding large in-memory PNG handoffs on the hot path
- a single shared HTTP client pool in `acquisition/runtime.py` is keyed on `(proxy, address-family preference, force_ipv4)`; `acquisition/http_client.py` no longer maintains a second pool and simply delegates to `get_shared_http_client`
- curl_cffi impersonation target is now an actionable setting (`crawler_runtime_settings.curl_impersonate_target`, default `chrome131`) rather than dead config, and httpx clients ship with a matching default Chrome `User-Agent`/`Accept` header set so direct HTTP requests present a coherent identity
- acquisition identity now repairs malformed browser client-hint headers before Playwright contexts are created, and the shared HTTP default headers advertise the same Chrome client-hint family (`sec-ch-ua*`, `Upgrade-Insecure-Requests`) when the configured UA is Chrome-like instead of sending a partial browser header set
- tracked detail URLs are normalized upstream before reuse: extracted and user-entered commerce/job targets now drop low-signal click/search context params (`utm_*`, `click_*`, `content_source`, `pf_from`, `sr_prefetch`, `qs`, and similar short replay flags) while preserving functional params such as `variant`, `q`, and `id`
- hosts with repeated hard blocks can temporarily prefer browser-first acquisition within the pacing TTL, but one successful browser recovery clears that host memory so random PDP challenges do not taint the whole host
- origin warmup has been removed on every engine: both Patchright and real Chrome navigate straight to the target URL, and a blocked product URL is recovered in place by the challenge loop rather than by pre-seeding cookies from the origin root — the critical path no longer carries a speculative warmup navigation
- sanitized engine-scoped `real_chrome` domain state, when it exists, is still applied to the browser context, but it no longer gates a warmup step (there is none)
- real Chrome is not challenge-exempt: if the direct PDP nav lands on a challenge shell, acquisition runs the same bounded challenge wait/activity/retry loop before returning a blocked verdict
- Cloudflare "Just a moment" managed challenges are solved in place: the engine-agnostic recovery loop treats a Cloudflare interactive interstitial as solvable (not a terminal hard block) so it keeps polling until the Turnstile widget renders, then issues a humanized coordinate click on the checkbox (`CLOUDFLARE_TURNSTILE_SELECTORS`) on both Patchright and real Chrome; Akamai/DataDome "Access Denied" still fails fast as terminal
- crawl pages can never open a second browsing context: `suppress_new_context_openers` neutralizes `window.open` and rewrites anchor `target=_blank` to `_self` (init script + live-document evaluate, sentinel-guarded), so detail expansion reveals collapsed content without flashing new tabs; the reactive popup guard remains only as a backstop
- browser contexts accept a per-fetch `proxy` for rotated-proxy traversal; `temporary_browser_page` is a thin wrapper over `SharedBrowserRuntime.page(proxy=...)`
- `browser_identity` is host-OS-coherent: the de-headlessified UA OS token, the `sec-ch-ua-platform` header, and the engine's native `navigator.platform` all agree, keyed off the host OS the browser runs on (Windows dev box vs Linux Docker in prod). There is no synthetic fingerprint generation and no UA-vs-OS regeneration loop; the engine is genuinely Chrome, so only the headless token is normalized.
- browser acquisition no longer injects custom init scripts into Patchright contexts; identity shaping is limited to context options, headers, locale/timezone alignment, and engine-native behavior so we do not reintroduce script-surface blockers. Real Chrome (headful, native context) is exempt from de-headlessification because it already reports a clean UA.
- browser runtime settings are split by concern: `runtime_settings.py` owns tunables/launch args, and `browser_fingerprint_profiles.py` owns static browser identity/profile constants
- blocked-page escalation is now two-pronged: vendor-specific response headers (DataDome, Cloudflare, Akamai, PerimeterX, Sucuri, ...) classified via `classify_block_from_headers` short-circuit into the browser and mark the host vendor-blocked so sibling fetchers skip further HTTP attempts; HTML heuristics continue to catch vendor-silent blocks
- `is_non_retryable_http_status` keeps `401` out of browser escalation (auth walls) while still escalating `403`/`429` challenges, and `classify_blocked_page` emits typed `BlockPageClassification` outcomes (`auth_wall`, `rate_limited`, `challenge_page`, ...) distinct from network failures
- `classify_blocked_page` must keep provider/body evidence even on forced `403` / `429` outcomes; status-only early returns are not enough because recovery, diagnostics, and regression triage need the concrete blocker family
- platform/runtime policy no longer hardcodes vendor-owned domains just to force browser usage; escalation is driven by runtime policy, response/header evidence, and structured blocker signatures
- host pacing is now enforced before both HTTP and browser attempts in `crawl_fetch_runtime.py`, and protection evidence can temporarily widen the per-host interval instead of hammering the same blocked edge
- after browser navigation, blocked challenge pages now get one bounded recovery window: the runtime polls for clearance, checks Akamai-style `_abck` issuance when relevant, and only then performs a single paced reload before surfacing the failure
- real-Chrome behavior realism is timeout bounded by `browser_behavior_realism_timeout_seconds`; the browser stage records timeout diagnostics and continues instead of letting mouse/scroll simulation consume the URL budget
- the legacy `async def fetch_page` trampoline in `acquisition/runtime.py` has been removed; callers import `fetch_page` from `crawl_fetch_runtime` directly

### 6.4 Extraction

Primary files (flat `app/extraction/` package):

- `extraction/engine.py` — common Harvest → Resolve → Publish orchestration
- `extraction/adapters.py` — the four surface adapters behind the common API
- `extraction/surfaces.py` — `Surface` enum, surface specs, and listing schemas
- `extraction/contracts.py` — frozen extraction contracts, evidence, records, and projections
- `extraction/entities.py` — product/variant/offer/asset entities and `EntitySet`
- `extraction/targeting.py` — commerce/subject target selection and scoped graphs
- `extraction/documents.py` — HTML/JSON document parsing and the `DocumentStore`
- `extraction/pipeline.py` — ecommerce detail collection/harvest and price/brand conflict flagging
- `extraction/listing.py` — ecommerce listing collection and resolution
- `extraction/jobs.py` — job collection, wrong-surface checks, and job detail/listing resolution
- `extraction/collectors/*` — DOM, JS-state, JSON-LD, metadata (microdata/OG/network), and URL evidence collectors
- `extraction/resolution/` — product/variant consensus, ranking, price-unit derivation, and asset resolution
- `extraction/validation.py` — missing-evidence, incomplete-offer, and contradiction findings
- `extraction/result_building.py` — decision accounting, evidence dispositions, and field states
- `extraction/publication.py` — resolver-authorized publication projections and serializers
- `extraction/field_states.py`, `extraction/json_walk.py`, `extraction/model_runtime.py`, `extraction/sentinel.py`, `extraction/replay.py` — field-state derivation, JSON traversal primitives, evaluation-gated model fallback, Sentinel challenger comparison, and replay/fixture construction

Responsibilities:

- choose listing vs detail path
- consume connector artifacts when a concrete artifact-only connector exists
- parse JSON-LD, embedded JSON, JS state, microdata, Open Graph, and network payloads
- extract field values from structured sources and DOM
- normalize field values before publish

Important implemented features:

- `structured_sources.py` now integrates extruct-backed microdata and Open Graph extraction, with fallback parsing when dependencies are unavailable
- Nuxt `__NUXT_DATA__` payload revival is live in structured-source harvesting
- `network_payload_mapper.py` now uses declarative specs from `config/network_payload_specs.py`, and browser-side endpoint classification derives its path tokens from that same spec source instead of maintaining a parallel capture-only token table
- network payload detail inference now keeps its signature/list-container config in `config/network_payload_specs.py`, recognizes normalized camel/Pascal-case commerce keys (`ProductName`, `DetailUrl`, `FieldValues`), and rejects product/detail payloads whose explicit URL anchor does not match the current detail page
- generic ghost-route payload fallback now rejects multi-record listing envelopes for detail surfaces, so paginated product-list APIs cannot masquerade as a single detail payload just because one row happens to expose product-like keys
- tracking-parameter stripping is live in field-value normalization via `w3lib`
- tracking URL cleanup has its own owner in `field_url_normalization.py`; generic value coercion stays in `field_value_core.py`
- platform registry config in `config/platforms.json` owns platform metadata, network signatures, JS-state mappings, and listing-readiness selectors/waits
- ecommerce detail title selection now ranks structured sources ahead of raw DOM headings, rejects noisy DOM `<h1>/<title>` values such as promo or generic-results text, and only promotes fallback titles when the replacement source is materially stronger
- ecommerce detail extraction now drops low-signal site-shell records when the surviving title still resolves to site-brand chrome and no real product anchors survive, preventing stale SPA/detail misses from being persisted as false product successes
- ecommerce-detail extraction now threads the originally requested PDP URL through Resolve and the authorized publication projection so same-site utility redirects can either preserve the requested product identity when the product metadata still matches or drop the row entirely when the utility page is carrying mismatched stale product data
- detail harvest/resolve sequencing lives in `extraction/pipeline.py` and `extraction/resolution/`; all detail evidence flows through one sourced-`Evidence` boundary carrying source, collector, and evidence ID, with authoritative -> structured -> JS state -> DOM ordering, DOM skip decisions, and finalization owned by the pipeline and resolver
- detail materializes once before the DOM skip decision and once after DOM collection; parallel candidate-source/evidence arrays and their alignment repair pass are deleted
- incomplete variant offers and parent/variant currency contradictions remain visible as validation findings instead of silent rewrites; public `record.data` stays flat while evidence summaries live in source trace/review
- source capability diagnostics distinguish terminal shells from successful PDP observations; HTTP error bodies, challenge/low-content browser shells, and URL-title-only placeholders mark affected product fields as source-unavailable and prevent title/url-only public success rows
- detail extraction now has a DOM variant fallback for `ecommerce_detail` pages when structured data and JS state leave variant axes empty
- listing candidate quality lives in `extraction/listing.py` with shared evidence ranking in `extraction/resolution/ranking.py`; listing extraction delegates candidate admission, support-signal checks, utility rejection, dedupe, and set ranking to those owners
- extraction config is split by concept: `field_mappings.py` owns schemas/aliases/field-name primitives, `js_state_field_specs.py` owns glom specs, `variant_policy.py` owns variant axes and flat transport fields, `extraction_price_rules.py` owns price selectors/JSON-LD price fields/currency-price thresholds, and `public_record_policy.py` owns public persisted/exported record policy
- variant record normalization is owned by `extraction/resolution/`; `extraction/pipeline.py` harvests variant evidence and delegates final variant axis/value cleanup to the resolver
- DOM variant recovery now recognizes radio/checkbox-based size and color groups, associates labels via `for`/parent label structure, and carries stock-derived availability (`0 Left`, `17 Left`, etc.) into `variants` and `selected_variant`
- JS-state ecommerce-detail mapping now scores candidate product payloads so richer nested PDP nodes beat shallow landing/navigation shells, and generic direct-axis variant keys such as `condition`, `grade`, `storage`, and `memory` are normalized without adapter-specific branches
- DOM listing extraction no longer accepts the first non-empty candidate set; it now ranks structured, DOM, and browser-captured rendered-card candidates by record quality and keeps visual elements as a last-resort fallback only
- job-listing detail-path recognition now treats numeric terminal posting slugs as detail-like URLs, so boards such as Startup.jobs survive candidate-set ranking without reopening city/search hub noise
- listing extraction may retry the original uncleaned DOM when noise-removal cleanup strips card detail-link evidence from the cleaned DOM, which protects header-nested product links on sites such as IndiaMART without weakening global cleanup rules
- listing title filtering now rejects numeric-only titles before persistence, and detail DOM image fallback keeps linked gallery media instead of dropping anchored product thumbnails
- generic ecommerce detail-path recognition now includes vendor-common routes such as `/proddetail/`, and listing anchor selection accepts same-site cross-subdomain detail links instead of requiring an exact hostname match
- DOM image extraction now scores likely product-gallery media higher and filters obvious tracking, logo, and spacer assets before building `additional_images`
- image dedupe now canonicalizes Next.js-style image proxy URLs back to their underlying asset, so transformed `/_next/image?...` duplicates do not survive as fake `additional_images` beside the same hero image
- ecommerce-detail DOM completion now treats missing `additional_images` as a high-value gap, so structured-data early exit does not suppress DOM gallery recovery when only a primary image was found upstream
- DOM section extraction now follows accordion/tab structures through `aria-controls`, native `details/summary`, and common wrapped content containers before falling back to plain heading-sibling scans
- requested-content extractability now only promotes canonical or explicitly requested section labels, preventing arbitrary product headings from being treated as synthetic extractable fields in browser diagnostics and DOM-completion gating
- raw requested field labels are preserved through crawl creation, and ecommerce-detail DOM section matching now checks those exact requested labels before collapsing to broader canonical aliases; composite headings such as `Features & Benefits` therefore extract into `features_benefits` instead of being silently reduced to a generic alias like `benefits`
- surface alias lookup now keeps normalized requested labels addressable as identity mappings as well as exact requested-field keys, so custom dynamic fields continue to flow through candidate collection even when they do not collapse to a built-in alias
- requested custom ecommerce-detail fields now keep DOM completion active when matching section headings are present, so structured-data early exit does not hide fields such as `product_story` after detail expansion
- ecommerce-detail DOM completion skips optional DOM variant probing when the record already has complete unrequested core detail fields, which avoids giant SoupSieve scans on large PDPs such as Amazon while keeping requested-field and true repair paths intact
- ecommerce-detail extraction reuses per-context JS-state harvests and caches variant DOM scope/node probes per Soup object, avoiding repeated full-document scans during DOM fallback, variant repair, and final cleanup
- DOM variant fallback now materializes concrete variant rows, keeps `variant_count` aligned with those rows, and avoids widening an already authoritative `selected_variant` choice with later DOM-only axis noise
- Shopify detail extraction can expand bounded same-family linked PDP salertes through `/products/<handle>.js`, then merge the sibling rows upstream so split color/scent product URLs still emit flat public variants.
- selector-backed fields that survive into `record.data` now persist exact selector provenance under `record.source_trace.field_discovery[field_name].selector_trace`, including selector kind/value, selector source, source run id, sample value, page URL, and `survived_to_final_record`
- ecommerce-detail long-text ranking now prefers explicit DOM sections over thinner structured blurbs when the page exposes a real description/spec-style accordion body, and `product_details` remains a separate field instead of being collapsed into `specifications`
- long-text candidate intake now rejects low-signal placeholders such as single-word review/schema values or accordion index labels before they can win `description` / `specifications`, and selector-backed long-text fields must expose non-interactive prose rather than button/tab indexes
- ecommerce-detail output no longer exposes platform slug fields such as `handle` by default; those values remain requestable explicitly, but the default user-facing detail schema stays limited to higher-signal commerce fields
- DOM section intake now rejects very short non-prose tab/button label clusters before they can override a real product description or specifications body
- ecommerce-detail JS-state product detection now requires real commerce cues instead of accepting arbitrary titled image blocks, and JS-state image harvesting filters payment, logo, bookmark, salert, and video assets before they can outrank structured product media
- latest commerce artifact replay lives in the unit harness as a manifest-backed gate over stored HTML/network artifacts; it checks sparse shell suppression, field-state diagnostics, variant identity, offer evidence, brand coercion, description boundaries, and product-scoped image selection through the real extraction pipeline
- the artifact gate fails on field-state or semantic invariant violations even when a case has no external issue id; issue metadata is reporting context, not the pass/fail authority
- output schema validation now applies to listing surfaces as well as detail surfaces before persistence, so type mismatches on listing records are nullified instead of silently bypassing validation
- final public shaping is owned by `app/extraction/publication.py`: projection entries authorize each atomic field, collection entity, and URL canonicalization trace before serialization
- persistence writes the already-authorized record and performs no extraction repair
- pipeline post-processing keeps selector self-heal for detail pages. Ecommerce detail is guarded from `extract_missing_fields()` and direct-record value generation; non-detail LLM fallback remains explicitly gated

### 6.5 Publish and persistence

Primary files:

- `publish/verdict.py`
- `publish/metrics.py`
- `publish/metadata.py`
- `persistence/url_result_artifacts.py` (the single per-URL artifact writer)
- `persistence/artifacts.py` (`ArtifactRepository` byte store)
- `pipeline/core.py`
- `pipeline/persistence.py`

Responsibilities:

- compute per-URL verdicts
- compute acquisition and URL metrics
- build/persist field-discovery metadata
- write per-URL artifacts through the single writer (see §6.8); keep artifact I/O and `CrawlRecord` persistence out of the orchestration hot path in `pipeline/core.py`
- write `CrawlRecord` rows and update run summaries
- skip already-persisted `(run_id, url_identity_key)` identities on rerun/re-entry so detail/listing retries stay idempotent instead of failing the run on a duplicate-key insert

Current verdict rules:

- records + not blocked -> `success`
- records + blocked -> `partial`
- blocked + no records -> `blocked`
- listing + no records -> `listing_detection_failed`
- detail + no records -> `empty`

### 6.6 Review, selectors, and domain memory

Primary files:

- `review/__init__.py`
- `selectors_runtime.py`
- `selector_auto_learn.py`
- `selector_suggestions.py`
- `selector_self_heal.py`
- `domain_memory_service.py`

Responsibilities:

- build review payloads
- save approved field mappings
- expose review artifact HTML
- store and manage selectors in domain memory
- suggest/test selectors; suggestion assembly lives in `selector_suggestions.py`
- synthesize and validate selectors during self-heal flows

Current storage/runtime model:

- selector/domain memory is stored by normalized `(domain, surface)`
- selectors are persisted inside `DomainMemory`
- reusable run defaults and learned acquisition contracts are persisted separately in `DomainRunProfile`, keyed by the same normalized `(domain, surface)` scope but never mixed into extraction-memory selector recipes
- successful DOM-only extraction can auto-save revalidated final-field selectors as `dom_observed` rules; structured, adapter, network, and JS-state winners are intentionally not promoted to selector memory
- ecommerce-detail setup repair uses the union of explicit user fields and limited defaults (`price`, `title`, `image_url`) for selector self-heal, LLM gap fill, and acquisition field-coverage metadata. Missing default fields no longer trigger low-quality HTTP-to-browser retry by themselves; browser retry is reserved for empty extraction with retryable evidence, blocked/shell evidence, explicit browser mode, traversal/listing recovery, and listing-integrity escalation. Static not-found pages and static homepage/category shells that do not match the requested detail slug are terminal HTTP observations, not browser retries. Optional deep fields are not forced unless requested
- reusable browser cookie/local-storage state is persisted separately in `DomainCookieMemory`, keyed by normalized domain only, because acquisition reuse is host-level rather than surface-level
- completed-run field keep/reject actions are persisted separately in `DomainFieldFeedback`, keyed by normalized `(domain, surface)` and the field/source that was accepted or rejected
- runtime can layer surface-specific and generic rules
- `GET /api/selectors` can now list all selector records for a domain across surfaces when `surface` is omitted, which is what the frontend uses for domain-memory management and crawl-config prefill
- selector self-heal reuses stamped extraction runtime snapshot data
- selector self-heal persists only validated improvements and reuses domain memory on later runs before attempting another synthesis pass
- once reused domain-memory rules satisfy the requested fields for a record, the pipeline does not launch a second generic selector-synthesis round just because confidence remains low
- completed runs now expose a Domain Recipe workflow that combines acquisition evidence, field-local keep/reject actions, selector promotion, and saved run-profile editing in one surface; rejecting a selector-backed field deactivates the exact matching saved selector for that `(domain, surface)` without mutating unrelated memory
- Domain Recipe also exposes confusing evidence summaries and validation findings for review; it never exposes the internal `_evidence_graph`

### 6.7 LLM admin and runtime

Primary files:

- `llm/runtime.py`
- `llm/provider_client.py`
- `llm/config_service.py`
- `llm/cache.py`
- `llm/circuit_breaker.py`
- `llm/tasks.py`
- `llm/types.py`
- `api/llm.py`

Responsibilities:

- manage provider configs
- test provider connectivity
- run task-specific prompts
- cache responses and isolate failures
- expose provider catalog and cost log

Current crawl/runtime usage:

- optional missing-field extraction in the pipeline
- selector suggestion and review cleanup support
- config snapshots prevent mid-run drift

### 6.8 Observability — single-file diagnosis

Primary files:

- `persistence/url_result_artifacts.py`
- `observability/diagnose.py`
- `observability/run_report.py`

Responsibilities and current behavior:

- `publish_url_result_artifacts` is the **sole** per-URL artifact writer. It emits exactly three files under `runs/{run_id}/results/{url_result_id}/`: `page.html` (written once), `record.json` (public record view, matching the records API), and `diagnose.json`.
- `diagnose.json` is self-contained and bounded: per field it inlines the `FieldEvidenceState` status, evidence disposition summary, winning candidate, rejected candidates with reasons (≤120-char value previews), and any publication-policy suppression. It references no other file and invents no reason vocabulary — it reuses resolver, publication, and evidence-disposition reason codes. `ExtractionResult` carries `collector_outcomes`, `stage_outcomes`, and `evidence_dispositions` to feed it.
- `run_report.py` registers as a run-complete callback (via `pipeline/run_complete_callbacks.py`) and folds every `diagnose.json` into a deterministic run-level `report.json` that groups root causes with direct links to each URL's diagnosis. Like all of `app/observability/`, it is observe-only: it must never mutate extraction output, verdicts, selector memory, or domain contracts, and must not grow monitor-style diffing/retention/webhook behavior.
- The legacy second artifact scheme (`runs/{id}/pages/...`), `manifest.json`/`summary.json`/`records.json`/`debug.json`/`browser.json`/`trace.json`/screenshots, the never-written `acquisition.json`/`extraction.json` readers, the dead `source_trace` provenance keys, and the observe-only LLM diagnosis flow are all deleted. Deleted modules include `observability/{artifact_reader,baseline,browser_artifact,run_audit,run_llm_diagnosis,run_trace}.py`, `persistence/artifact_store.py`, `persistence/storage/`, `api/observability.py`, and `config/{audit_rules,observability}.py`. See `docs/INVARIANTS.md` §12.

### 6.9 Extraction Memory

Primary files:

- `core/config/extraction_memory.py` — store vocabulary and release/compiler/manifest versions.
- `models/extraction_memory.py` — templates, recipe layers, compiled recipes, run releases, URL manifests, operator labels, and observations.
- `persistence/extraction_memory.py` — recipe compilation, release freezing, observation/manifest writes, and purge.
- `core/extraction_memory/templates.py` — `normalize_route`, `fingerprint_from_parts`, `fingerprint_template`, `extract_tech_signals`.
- `core/extraction_memory/contract_runtime.py` — frozen-release preference lookup; Resolve owns final eligibility and ranking.
- `api/knowledge.py` — compatibility read/refine API backed only by extraction memory.
- `alembic/versions/20260702_0004_extraction_memory.py` — migrates the prior stores and deletes generic graph tables.

Extraction memory is PostgreSQL-authoritative. Run creation freezes one relational release and each URL result gets a relational execution manifest. Contracts rank eligible evidence only; extraction never imports mutable memory storage. Observation failure is logged without changing crawl verdicts. See `docs/INVARIANTS.md` §17.

## 7. Persistence Model

Primary models:

- `User`
- `CrawlRun`
- `CrawlRecord`
- `CrawlLog`
- `DomainRunProfile`
- `DomainCookieMemory`
- `ExtractionOperatorLabel`
- `ReviewPromotion`
- `DataEnrichmentJob`
- `EnrichedProduct`

`DomainCookieMemory.storage_state` is encrypted at rest (audit 1.6): rows hold
an envelope `{"v": 1, "ct": <fernet ciphertext of the normalized storage
state>}` keyed by `ENCRYPTION_KEY`, written by
`acquisition/cookie_store.py` and migrated by
`alembic/versions/20260722_0004_encrypt_domain_cookie_memory.py`. The memory
stays deliberately shared across users keyed by `(domain[, engine])` — it is
the cross-run learning substrate (`docs/INVARIANTS.md` §9), so scoping it per
user would fragment learning; encryption removes the DB-dump exposure instead.
Readers decrypt envelopes, pass legacy plaintext rows through unchanged, and
skip (log + re-learn) rows that no longer decrypt. Deploy ordering: run the
migration after all workers run the new code; old workers simply skip
encrypted rows and re-learn.
- `ApiKey`
- `LLMConfig`
- `LLMCostLog`
- `DomainMemory`

Notable current schema direction:

- durable queue lease support
- max-records trigger support
- URL identity keys on records
- enrichment status metadata on crawl records, with derived enrichment data stored separately in `enriched_products`
- domain-memory storage
- split crawl-data reset versus domain-memory reset, so destructive cleanup no longer wipes learned selectors/profiles/cookies by default

## 8. Record, Review, and Provenance Contracts

`CrawlRecordResponse` intentionally cleans user-facing output:

- `data`: populated logical fields only
- `raw_data`: full stored extraction payload
- `discovered_data`: trimmed review/provenance metadata
- `source_trace`: acquisition and extraction provenance
- `review_bucket`: unverified attributes exposed for review
- `provenance_available`: indicates manifest/provenance detail exists

`CrawlRecordProvenanceResponse` exposes the fuller provenance/debug view:

- `raw_data`
- `discovered_data`
- `source_trace`
- `manifest_trace`
- `raw_html_path`

The normal records API hides:

- empty/null values
- `_`-prefixed internal fields
- obsolete raw manifest containers in standard display responses

## 9. Product Intelligence Discovery

Product Intelligence lives under `app/intelligence/` and remains upstream of candidate crawl/export paths. SerpAPI discovery is Shopping-first: `engine=google_shopping` results are parsed, Immersive Product store links are expanded, then organic results remain as fallback evidence. Candidate ranking prefers exact identifiers, Shopping product-group evidence, and title overlap before source-type authority, so a strong marketplace match can outrank a weak brand-site adjacent product without adding extra search queries.

Belk brand inference uses data files under `app/data/product_intelligence/`, with `belk_brands.txt` for longest-match brand inference from Belk source titles/URLs and `belk_exclusive_brands.txt` for private-label exclusion. Belk detail extraction preserves UPC-like `sku_upc` values as public `barcode`/Product Intelligence `gtin` evidence while keeping retailer SKU/product ID separate. Confidence scoring is deterministic and evidence-based: title similarity, brand match, valid GTIN/barcode match, retailer SKU match, MPN/style match, Shopping product-group evidence, price band, and source authority are scored separately so the UI can explain why a candidate URL is strong or weak.

## 10. Recent Feature Status From Plans/Audits

Implemented from recent extraction/audit work:

- extruct-backed microdata + Open Graph support
- generic network payload specs
- host-OS-coherent headless UA de-headlessification (replaces browserforge identity)
- URL tracking-param stripping
- Nuxt data revival
- selector self-heal + domain memory
- provenance/review bucket response cleanup

Still worth treating as active engineering concerns:

- generic-path hardcodes that should live in adapters/config
- large utility/service modules that still own too many concerns
- frontend/backend client-surface drift where unused client methods outlive removed routes
- selector tool and Crawl Studio now share selector memory semantics, so future selector changes need tests in both surfaces instead of assuming one page is authoritative

## 11. Known Issues

### Celery concurrent crawl can stall after browser page load

The production URL timeout bounds this failure, but the root cause is not yet proven. The two saved worker logs favor browser lifecycle/resource blockage inside a long-running Celery task over Redis lock contention:

- Across `celery-worker-1.log` and `celery-worker-2.log`, there are six browser storage-state capture timeouts, four context-close timeouts, two browser capture queue-join timeouts, one page-open timeout, and one runtime-close timeout. Nearby errors include Patchright `TargetClosedError`, driver connection loss, and a destroyed pending route task.
- Workers repeatedly miss peer heartbeats while `crawl.process_run` executes. The subsequent Celery clock-drift value closely matches the task wall time, including 446 seconds for the 2026-06-28 run. This is consistent with a `MainProcess`/solo worker being unable to service heartbeats while the crawl owns its execution thread.
- Redis connections succeed. Neither log contains a Redis lock, semaphore, lease-contention, or exhaustion message. Current evidence therefore does not support Redis as the primary blocker.
- The latest 96-URL run log records the run boundary and selected HTTP/network events, but not per-URL browser admission and stage transitions. It cannot identify the reported five URLs or prove whether they waited before page/context admission, during post-load capture, or during context shutdown.

Keep the URL timeout guard. For the next reproduction, log bounded per-URL browser admission wait, runtime/context/page identity, stage entry/exit, runtime snapshot, and cleanup duration. This is needed to distinguish runtime semaphore starvation from a Patchright context/driver close race. Do not add a Redis concurrency workaround without lock-wait evidence.

## 12. Operational References

Useful local commands:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check .
```

Acceptance harness note:

- `harness_support.parse_test_sites_markdown()` consumes literal URLs from `TEST_SITES.md` lines and markdown tables without rewriting them; when a table `Surface` cell says `Listing`, `Detail`, `AJAX listing`, `Infinite scroll`, or `SPA Detail`, that label only steers surface inference (`ecommerce_listing` vs `ecommerce_detail`) while the source URL remains unchanged

Companion docs:

- [../AGENTS.md](../AGENTS.md)
- [ENGINEERING_STRATEGY.md](ENGINEERING_STRATEGY.md)
- [INVARIANTS.md](INVARIANTS.md)
- [frontend-architecture.md](frontend-architecture.md)
