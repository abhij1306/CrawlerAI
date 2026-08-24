# CrawlerAI Codebase Map

Use this doc for ownership and file location. Do not filesystem-wander first.
If a file is not listed, assume it is a helper under a listed owner.

---

## Backend Root: `backend/app/`

### Support files outside `backend/app/`

| File | Purpose |
|---|---|
| `bootstrap_admin.py` | Explicit create-only initial-admin command; never part of API startup |
| `ecr_scan_gate.py` | Fail-closed ECR enhanced-scan release policy and sanitized evidence report |
| `harness_support.py`, `harness/support.py` | Stable acceptance entry points plus live-run/review orchestration and result-quality evaluation |
| `harness/site_sets.py`, `harness/challenge_classifier.py`, `harness/quality_evaluator.py`, `harness/artifact_quality_cases.py` | Site input parsing, failure classification, catalog gates, and artifact replay auditing |
| `test_site_sets/commerce_browser_heavy.json` | Commerce acceptance manifest and quality expectations |
| `browser_surface_probe/core.py` | Browser-surface probe orchestration and artifact bundle assembly |
| `browser_surface_probe/signal_extractor.py`, `target_diagnostics.py`, `report_rendering.py`, `value_coercion.py` | Page-signal collection, target transport/browser diagnosis, report/findings rendering, and shared probe value normalization |
| `.github/workflows/supply-chain.yml` | Final-image build, SPDX SBOM, and fixable High/Critical scan gate |
| `.github/workflows/ecr-enhanced-scan-gate.yml` | OIDC-based reusable ECR enhanced-scan production policy gate |

### `api/` — route handlers only

| File | Purpose |
|---|---|
| `crawls.py` | Run creation, CSV ingestion, run listing/detail/control, commit fields, logs, and Crawl Studio category discovery |
| `crawl_domain.py` | Crawl domain recipe/profile/feedback/cookie-memory routes |
| `records.py` | Record listing, exports, provenance |
| `review.py` | Review payloads and approved mapping save |
| `selectors.py` | Selector CRUD, suggest, test, preview |
| `knowledge.py` | Compatibility routes for extraction-memory template/recipe reads and operator source selection |
| `llm.py` | LLM provider catalog, config, connection test, cost log |
| `product_intelligence.py` | Product matching jobs, source products, candidates, match review |
| `data_enrichment.py` | On-demand ecommerce detail enrichment jobs and enriched product rows |
| `api_keys.py` | Dashboard API-key create/list/revoke endpoints; returns plaintext only on create |
| `public/*` | Public API v1 envelope, rate-limit helpers, HTTP-only extraction, domain info, capabilities, and deferred batch routes |
| `auth.py` | Login, register, `/me` |
| `users.py`, `dashboard.py`, `jobs.py`, `health.py`, `metrics.py` | Named route modules |

(`crawls.py` above is the single run-API owner — the former duplicate row for the category discovery endpoint is folded into it.)

### `core/` — infrastructure only

| File | Purpose |
|---|---|
| `config/` | Pydantic settings, policy modules, declarative recipes, and runtime tunables |
| `config/database_settings.py` | Complete-URL precedence, encoded database-component composition, and production DSN checks |
| `database.py` | Async SQLAlchemy engine and session factory |
| `redis.py` | Shared Redis connection |
| `security.py` | JWT, Argon2id hashing, bounded legacy PBKDF2 verification, encryption |
| `dependencies.py` | FastAPI auth dependency helpers and cookie-session CSRF enforcement |
| `public_auth.py` | Public API-key hashing/authentication and `/api/v1` user resolution |
| `rate_limit.py` | Redis-first sliding windows and trusted-CIDR forwarding-chain resolution |
| `request_body_limit.py` | Pure ASGI receive-byte enforcement before JSON/multipart parsing and spooling |
| `proxy_secrets.py` | Proxy URL userinfo sealing, execution-time resolution, and canonical text redaction |
| `telemetry.py`, `metrics.py` | Observability, including final log/traceback secret redaction |

### `models/` — ORM entities

| Model | File | Purpose |
|---|---|---|
| `User` | `user.py` | account, role, token version |
| `ApiKey` | `api_key.py` | public API bearer-key ownership and validation |
| `BootstrapRecord` | `bootstrap.py` | durable consumption marker for create-only one-shot bootstrap commands |
| `CrawlRun` | `crawl_run.py` | run state, surface, settings, summary |
| `CrawlUrlResult` | `crawl_run.py` | canonical per-URL acquisition/extraction verdict, manifest pointer, and record count |
| `CrawlRecord` | `crawl_run.py` | extracted record payload and URL-result-linked provenance |
| `CrawlLog` | `crawl_run.py` | run logs |
| `DomainRunProfile` | `domain_memory.py` | reusable execution defaults scoped by `(domain, surface)` |
| `DomainCookieMemory` | `domain_memory.py` | encrypted browser state scoped by `(user_id, domain[, engine])` |
| `HostProtectionMemory` | `domain_memory.py` | per-host block/success tracking |
| `ExtractionTemplate`, `ExtractionRecipe`, `CompiledExtractionRecipe`, `ExtractionReleaseSnapshot`, `ExtractionManifest`, `ExtractionOperatorLabel`, `ExtractionObservation` | `extraction_memory.py` | single extraction-memory hierarchy |
| `ProductIntelligenceJob`, `ProductIntelligenceSourceProduct`, `ProductIntelligenceCandidate`, `ProductIntelligenceMatch` | `product_intelligence.py` | web product matching and price comparison jobs |
| `DataEnrichmentJob`, `EnrichedProduct` | `data_enrichment.py` | on-demand ecommerce detail enrichment jobs and derived enriched product rows |
| `LLMConfig`, `LLMCostLog` | `llm.py` | LLM config and cost tracking |

### `schemas/` — request and response DTOs


Public API schemas live in `api_key.py` and `public_api.py`.

---

## Bucket 2: Crawl Ingestion + Orchestration

| File | Purpose |
|---|---|
| `crawl/ingestion_service.py` | Validate and normalize `CrawlCreate`, stamp run snapshots |
| `crawl/service.py` | `dispatch_run()` entry — delegates to `dispatch/` strategy |
| `crawl/crud.py` | DB create and state transitions |
| `workers/` | Celery entry adapters |
| `crawl/profile/*` | Reusable domain run-profile normalization, merge, persistence, and acquisition-contract learning |
| `crawl/events.py` | WebSocket log emission |
| `intelligence/*` | Product web discovery, candidate URL admission/dedupe, brand registry loading, candidate crawl orchestration, deterministic match scoring |
| `intelligence/candidate_polling.py` | Batched candidate crawl-status polling, ready-candidate scoring, timeout transitions, and summary refresh |
| `data/product_intelligence/*` | Product Intelligence brand registry data, including Belk brand and exclusive/private-label lists |
| `enrichment/service.py` | On-demand enrichment job orchestration and persistence for ecommerce detail records |
| `crawl/category_discovery.py` | Shared Crawl Studio category discovery response assembly for one or more seed URLs |
| `connectors/public_api/extraction_service.py` | Public HTTP-only single-product extraction wrapper over normal crawl creation and per-URL pipeline processing |
| `connectors/public_api/domain_info_service.py` | Read-only public domain readiness view over domain memory, run profiles, and recent crawl rows |
| `enrichment/deterministic.py` | Deterministic enrichment normalization, taxonomy matching, and product attribute diagnostics |
| `enrichment/llm_diagnostics.py` | Data enrichment LLM payload application, rejection, and skip-reason diagnostics |
| `enrichment/shopify_catalog.py` | Shopify taxonomy scoring, matching, and exact-conflict policy |
| `enrichment/shopify_repository.py` | Shopify taxonomy/attribute JSON loading, normalization, and lookup indexes |
| `crawl/batch_runtime.py` | URL orchestration, per-URL session ownership, concurrency, progress, pause, kill checks |
| `crawl/sitemap_resolver.py`, `crawl/site_link_discovery.py` | Static sitemap/homepage category discovery plus rendered same-origin site-link fallback |
| `tasks.py` | Celery task entry |
| `pipeline/extraction_loop.py` | Per-URL stage orchestration: acquire -> extract -> normalize -> persist |
| `pipeline/record_extraction_stage.py` | Adapter population, selector-rule loading, extraction invocation, acquisition-contract memory |
| `pipeline/retry/stage.py` | Browser retry families, detail rejection guard, listing-integrity escalation |
| `pipeline/url_processing_context.py` | Per-URL acquisition config and run-context resolution |
| `pipeline/persistence.py` | `CrawlRecord` writes, dedupe, summaries |
| `pipeline/runtime_helpers.py` | Typed stage helpers, browser diagnostics merge, failure-state persistence |
| `pipeline/run_complete_callbacks.py` | Single run-complete callback registration point for post-run observability hooks |
| `pipeline/types.py` | Pipeline typed objects |

Flow:
`POST /api/crawls -> crawl/ingestion_service -> crawl/crud -> crawl/service -> tasks/crawl/batch_runtime -> pipeline/extraction_loop`

---

## Bucket 3: Acquisition + Browser Runtime

| File | Purpose |
|---|---|
| `acquisition/acquirer.py` | Main acquisition entry and fetch-runtime translation |
| `acquisition/policy.py` | Public acquisition plan/policy interfaces |
| `acquisition/runtime.py` | Shared HTTP client pool |
| `acquisition/http_client.py` | Thin shared-client wrapper |
| `acquisition/browser_runtime.py` | Browser fetch orchestration and runtime-policy wiring |
| `acquisition/browser_pool.py` | Shared Playwright pool, context lifecycle, browser binary/proxy launch |
| `acquisition/browser_background_tasks.py` | Observed popup, eviction, and bounded browser-close task lifecycle |
| `acquisition/browser_fetch_support.py` | Browser fetch result, diagnostics, and page event assembly helpers |
| `acquisition/browser_capture.py` | Screenshots and network payload capture |
| `acquisition/browser_content_signals.py` | Static HTML extractability, detail/listing content, and shell signals |
| `acquisition/browser_detail_candidates.py` | Detail-expansion candidate snapshot and admission policy |
| `acquisition/browser_diagnostics.py` | Browser engine labels, profile diagnostics, and failed-fetch diagnostic contracts |
| `acquisition/browser_identity.py` | Browser fingerprint generation |
| `acquisition/browser_interstitial.py` | Location-interstitial detection and safe dismissal |
| `acquisition/browser_page_flow.py` | Page navigation, readiness probing, serialization policy |
| `acquisition/browser_result_builder.py` | Browser acquisition diagnostics, artifacts, screenshots, final result shaping |
| `acquisition/browser_page_helpers.py` | Browser page HTML selection, detail extractability probes, listing visual capture |
| `acquisition/browser_proxy_config.py` | Browser proxy URL parsing, redaction, and Playwright proxy config |
| `acquisition/browser_readiness.py` | DOM readiness checks, listing/detail probes, outcome classification |
| `acquisition/browser_stage_runner.py` | Bounded browser-stage execution, timeout cancellation, and page/context teardown |
| `acquisition/browser_storage_state.py` | Browser storage-state capture and persist-policy marking |
| `acquisition/traversal.py` | Listing traversal mode orchestration |
| `acquisition/traversal_types.py` | Traversal result state container shared by traversal helpers/recovery |
| `acquisition/traversal_helpers.py` | Traversal fragments, timing waits, pagination-control detection |
| `acquisition/traversal_recovery.py` | Listing recovery actions, overlay dismissal, resilient clicks |
| `acquisition/traversal_card_counting.py` | Card-count and progress-snapshot helpers used by traversal loops |
| `acquisition/pacing.py` | Host-level rate limiting |
| `acquisition/cookie_store.py` | Tenant-owned domain cookie persistence and run-state policy |
| `acquisition/run_cookie_storage.py` | Encrypted tenant/run/engine-bound run cookie files, permissions, cache, and deletion |
| `acquisition/cookie_http_export.py` | Domain/path filtering and dedupe for browser-to-HTTP cookie handoff |
| `fetch/fetch_context.py` | `fetch_page()` owner: HTTP/browser decision, escalation, block detection |
| `fetch/browser_policy.py` | Proxy shaping, browser escalation policy, engine attempt selection, and diagnostics merge helpers |
| `fetch/types.py` | Typed fetch request and runtime context containers |
| `robots_policy.py` | robots.txt policy |
| `url_safety.py` | SSRF and public-target validation |

Import rule: import `fetch_page` from `app.acquisition.fetch.fetch_context` directly.

Canonical config owner:

| File | Purpose |
|---|---|
| `core/config/runtime_settings.py` | browser runtime tunables and launch args |
| `core/config/browser_fingerprint_profiles.py` | static browser identity/profile constants |

---

## Bucket 4: Extraction

| File | Purpose |
|---|---|
| `evaluation/baseline.py` | deterministic offline baseline reduction and stable artifact generation |
| `evaluation/schema.py` | grounded-label truth plus evaluation partition, surface, scenario, and metric contracts |
| `extraction/model_runtime.py` | Lazy evaluation-gated universal-model fallback, shared bounded runtime representation, source-grounding enforcement, and Evidence conversion |
| `extraction/sentinel.py` | Known-template challenger comparison, drift-state classification, and business-readable Sentinel diagnostics |
| `evaluation/compact_representation.py` | Offline truth-label decoration over the shared runtime `compact_page.v2` representation |
| `evaluation/partitions.py` | fail-closed release coverage gates by partition, extraction surface, and critical scenario |
| `evaluation/model_harness.py` | offline evidence-only candidate adapter with model/deployment/artifact identity; cannot emit public records |
| `evaluation/benchmark.py`, `evaluation/benchmarks/*` | `universal_model_benchmark.v2`: exact candidate/case checks, per-partition metrics, fail-closed decision, and committed Phase-4 NO-GO artifact |
| `extraction/engine.py` | Common extraction orchestration across surfaces: the Harvest → Resolve → Publish flow, timing, and review-finding wiring |
| `extraction/adapters.py` | The four surface adapters (ecommerce listing/detail, job listing/detail) behind the common Harvest → Resolve → Publish API, with contract-preference and divergence wiring |
| `extraction/surfaces.py` | `Surface` enum, `SurfaceSpec`/`ListingSchema` definitions, and surface parsing/lookup helpers |
| `extraction/contracts.py` | Frozen pydantic extraction contracts: request/capture bundles, `Evidence`, `Decision`, records, and publication projections |
| `extraction/entities.py` | Product/variant/offer/asset entity models and `EntitySet` construction from evidence, including primary product-root selection |
| `extraction/targeting.py` | Commerce/subject target selection and scoped entity-graph derivation for a requested URL |
| `extraction/documents.py` | Selectolax-backed HTML/JSON document parsing: `HtmlNode`, `HtmlDocument`, `HtmlAnalysis`, `JsonDocument`, and the `DocumentStore` |
| `extraction/pipeline.py` | Ecommerce detail collection/harvest orchestration, ordered normalization, and ambiguous-DOM-price/brand-conflict flagging |
| `extraction/listing.py` | Ecommerce listing evidence collection, listing-card evidence, product-link resolution, and listing resolution |
| `extraction/jobs.py` | Job collection, wrong-surface checks, JSON-LD/DOM job evidence, and deterministic job detail/listing resolution |
| `extraction/collectors/dom.py` | DOM evidence collector: product-root/brand node detection and CSS-recipe evidence |
| `extraction/collectors/js_state.py` | JS-state evidence collector, structured harvest results, budget outcomes, and evidence prioritization |
| `extraction/collectors/jsonld.py` | JSON-LD evidence collector: product/offer/variant payload detection and standalone-variant handling |
| `extraction/collectors/metadata.py` | Microdata, Open Graph, and network payload evidence collectors |
| `extraction/collectors/url.py` | URL evidence collector: query-selected variant and detail-URL signals |
| `extraction/collectors/_helpers.py` | Shared collector helpers: evidence construction, HTML doc access, subject identity, and brand-role validation |
| `extraction/resolution/` | Resolver package: product/variant consensus, derived facts, inherited offers, variant rollups, evidence ranking (`ranking.py`), price-unit derivation (`price_units.py`), and product-asset resolution (`assets.py`) |
| `extraction/validation.py` | Missing-evidence, incomplete-offer, shell-title, description, child-join, and variant/currency/availability-contradiction findings |
| `extraction/result_building.py` | Decision/selected-fact accounting, evidence dispositions, per-field and projection field states, and data-integrity status |
| `extraction/publication.py` | Resolver-authorized publication projections, atomic-field/collection authorization, and deterministic serializers |
| `extraction/field_states.py` | Field evidence-state naming and derivation from evidence dispositions |
| `extraction/json_walk.py` | JSON pointer/traversal primitives (`JsonNode`, `walk_json`) shared by structured collectors and resolution |
| `extraction/replay.py` | Ordered fixture/bundle artifact replay from stored acquisition/memory inputs and the `MemoryArtifactReader` used by replay harnesses |
| `app/core/config/locale_format_rules.py` | Locale/market normalization policy: money separators, generic URL currency inference, currency symbols, and GTIN check digits |
| `app/core/config/extraction_rules/` | Availability enum/token policy and generic extraction rule tables; `_detail_sections.py` owns description/long-text and DOM detail-section policy |

Canonical config owners:

| File | Purpose |
|---|---|
| `core/config/field_mappings.py` | canonical schemas, field aliases, field scope/value classification, and primitive field-name constants |
| `core/config/js_state_field_specs.py` | JS-state product and variant field mapping specs |
| `core/config/public_record_policy.py` | Public persisted/exported record exclusions, URL safety, and identity value policy |
| `core/config/variant_policy.py` | Ecommerce fact families, public variant axes, flat variant transport fields, and variant axis aliases |
| `core/config/extraction_rules/` | extraction/runtime selector tokens split by common, image, detail, variant, listing/structured, and job concerns |
| `core/config/extraction_price_rules.py` | Detail price selectors, JSON-LD price fields, currency decimal places, and price repair thresholds |
| `core/config/evaluation.py` | evaluation vocabulary, compact-representation bounds, partition gates, and benchmark metric names |
| `core/config/selectors.py` | DOM selectors |
| `core/config/platforms.json` | platform metadata, signatures, JS mappings, readiness selectors |
| `core/config/network_payload_specs.py` | payload specs and endpoint tokens |
| `core/config/data_enrichment.py` | data enrichment statuses, limits, and taxonomy file path |
| `core/config/public_api.py` | public API key prefixes, envelopes, error codes, rate limits, extraction caps, MCP env names, and static capabilities |
| `core/config/extraction_memory.py` | extraction-memory statuses, recipe/label kinds, and manifest/compiler versions |

### `mcp_server/` — local MCP wrapper

| File | Purpose |
|---|---|
| `client.py`, `tools.py`, `server.py`, `config.py` | Stateless FastMCP stdio/default or literal-loopback SSE server; rejects public binds and calls public REST API only |

---

## Bucket 5: Publish + Persistence

| File | Purpose |
|---|---|
| `publish/verdict.py` | URL verdicts |
| `publish/metrics.py` | acquisition and URL metrics |
| `publish/metadata.py` | field-discovery metadata |
| `persistence/url_result_artifacts.py` | **Single** per-URL artifact writer: `page.html` + `record.json` + `diagnose.json` under `runs/{run_id}/results/{url_result_id}/` |
| `persistence/artifacts.py` | `ArtifactRepository` byte store backing the writer |
| `observability/diagnose.py` | Builds the self-contained, bounded per-URL `diagnose.json` |
| `observability/run_report.py` | Run-complete callback folding diagnoses into deterministic `report.json` |
| `pipeline/persistence.py` | persistence owner shared with Bucket 2 |

Observability is observe-only (never mutates extraction/verdicts/memory). The legacy `artifact_store.py`, `persistence/storage/`, `api/observability.py`, and the `observability/{artifact_reader,baseline,browser_artifact,run_audit,run_llm_diagnosis,run_trace}.py` modules are deleted. See `docs/INVARIANTS.md` §12.

Verdict set:
`success`, `partial`, `blocked`, `listing_detection_failed`, `empty`

---

## Bucket 6: Review + Selectors + Domain Memory

| File | Purpose |
|---|---|
| `crawl/review/__init__.py` | Review and promotion service: review payloads and approved field mapping persistence |
| `crawl/review/domain_recipe_support.py` | Domain-recipe helpers: selector signatures, acquisition info, selector-candidate collection, feedback serialization |
| `core/records/selectors_runtime.py` | Selector CRUD and runtime lookup over extraction-memory recipes; suggest/test/preview |
| `crawl/domain_memory_service.py` | Domain-scoped selector recipe memory: load/save/list `SelectorMemory` and compose runtime selector rules |
| `api/selectors.py` | Selector HTTP routes (CRUD, suggest, test, preview) |
| `schemas/selectors.py` | Selector request/response DTOs |
| `core/config/selectors.py` | Deterministic DOM candidate patterns (anchor/card selectors) |
| `core/config/selector_runtime.py` | Selector runtime tunables |
| `models/domain_memory.py` | `DomainRunProfile` / `DomainCookieMemory` ORM rows (see the `models/` table) |

All selector recipes are scoped by normalized `(domain, surface)`.
The legacy flat modules (`review/__init__.py`, `selector_auto_learn.py`,
`selector_suggestions.py`, `selector_self_heal.py`, top-level
`selectors_runtime.py`/`domain_memory_service.py`) are deleted — the owners
above replaced them.

---

## Bucket 7: LLM Admin + Runtime

| File | Purpose |
|---|---|
| `llm/runtime.py` | Pipeline LLM entry |
| `llm/tasks.py` | Prompt task orchestration and typed task wrappers |
| `llm/prompt_rendering.py` | Prompt variable rendering, HTML pruning, structured evidence shaping, and prompt truncation |
| `llm/payloads.py` | Provider JSON parsing and task-specific payload validation |
| `llm/cost_logging.py` | LLM cost log persistence |
| `llm/provider_client.py` | Provider HTTP clients |
| `llm/config_service.py` | Config CRUD and key encryption |
| `llm/cache.py` | Redis-backed response dedupe |
| `llm/circuit_breaker.py` | Error classification and cost protection |
| `llm/budget.py` | Per-run LLM call budget guard |
| `llm/types.py` | LLM-internal types |

---

## Bucket 8: Extraction Memory (PostgreSQL-authoritative)

| File | Purpose |
|---|---|
| `core/config/extraction_memory.py` | Stable store vocabulary and versions |
| `models/extraction_memory.py` | Purpose-built template, recipe, compiled recipe, release, manifest, label, and observation tables |
| `persistence/extraction_memory.py` | Template/recipe writes, learn-once claims and drift locking, per-URL manifest orchestration, and purge |
| `persistence/extraction_memory_releases.py` | Recipe-layer compilation, immutable release creation/activation, selector projection, and bounded release-payload caching |
| `persistence/extraction_memory_sources.py` | Published-evidence source preference shaping and observed contract merging |
| `persistence/extraction_memory_observations.py` | Sentinel observation validation, recording, and confirmed-drift suspension |
| `persistence/extraction_memory_knowledge.py` | Knowledge-site and contract query projections plus operator source-selection persistence |
| `core/extraction_memory/templates.py` | Pure route normalization and structural fingerprinting |
| `core/extraction_memory/contract_runtime.py` | Pure frozen-release preference lookup; Resolve owns eligibility and ranking |
| `api/knowledge.py` | Compatibility route surface backed only by extraction memory |
| `alembic/versions/20260703_0001_greenfield_schema.py` | Clean-start schema baseline, including extraction memory |
| `alembic/versions/20260824_0002_tenant_cookie_memory.py` | Deletes unowned legacy cookie/profile memory and adds mandatory cookie user ownership |
| `alembic/versions/20260824_0003_bootstrap_records.py` | Adds durable one-shot bootstrap consumption records |
| `alembic/versions/20260824_0004_purge_legacy_proxy_secrets.py` | Purges legacy plaintext proxy settings; credentials are intentionally unrecoverable |

Extraction memory is the single owner for learned structural state. Run releases and URL manifests are relational rows, not payloads embedded in run settings. See `docs/INVARIANTS.md` §17.

---

## Backend test support owners

| File | Purpose |
|---|---|
| `tests/component/crawl_fetch_runtime_test_support.py` | Shared fetch-context builders and the per-test fetch-runtime reset fixture for acquisition-policy tests |
| `tests/component/browser_context_test_support.py` | Browser readiness, proxy, context, runtime-capacity, and cookie-memory test vocabulary |
| `tests/component/crawl_service_test_support.py` | Crawl creation, acquisition-contract, profile, lifecycle, and proxy-validation test vocabulary |
| `tests/component/sitemap_resolver_test_support.py` | Sitemap fake clients, target validation, and XML response setup |
| `tests/regression/batch_runtime_test_support.py` | Batch concurrency, processing, policy, sitemap, and failure-recovery test vocabulary |
| `tests/unit/extraction_pipeline_test_support.py` | Canonical extraction fixture/request/evidence vocabulary shared by behavior suites |
| `tests/unit/extraction_contract_test_support.py`, `extraction_runtime_test_support.py` | Narrow contract/cascade and runtime/sentinel additions over the canonical extraction vocabulary |
| `tests/unit/evaluation_phase4_test_support.py`, `crawl_run_95_test_support.py` | Phase-4 evaluation builders and run-95 regression fixture vocabulary |
| `tests/component/learn_once_persistence_test_support.py`, `contract_runtime_test_support.py` | Extraction-memory persistence, release, matching, and claim test vocabulary |
| `tests/component/product_intelligence_test_support.py`, `public_api_test_support.py` | Product-intelligence discovery/scoring and public-API auth/resource test vocabulary |
| `tests/regression/harness_runtime_test_support.py`, `data_enrichment_test_support.py` | Acceptance-harness and enrichment job/deterministic/LLM test vocabulary |

These modules contain setup vocabulary only. Assertions stay in behavior-named `test_*.py` owners.

---

## Duplicate basenames — canonical owners

Several backend modules share a basename. Resolve ambiguity with this table instead of renaming files.

| Basename | Canonical owners |
|---|---|
| `contracts.py` ×4 | `acquisition/contracts.py` (browser fetch attempt specs) · `crawl/contracts.py` (run-facing DTOs: `UrlResult`, `RunSummary`) · `extraction/contracts.py` (extraction execution context/bundle contracts) · `persistence/contracts.py` (artifact store reference) |
| `extraction_memory.py` owners | `core/config/extraction_memory.py` (store vocabulary/versions) · `models/extraction_memory.py` (ORM tables) · `persistence/extraction_memory*.py` (writes/locks, releases, observations, source preference, and knowledge projections) |
| `service.py` ×3 | `crawl/service.py` (run lifecycle control: dispatch/pause/resume/kill/cancel) · `enrichment/service.py` (data-enrichment job lifecycle) · `intelligence/service.py` (product-intelligence job lifecycle) |
| `types.py` ×3 | `acquisition/fetch/types.py` (fetch runtime context and attempt state) · `connectors/llm/types.py` (LLM connector task results) · `crawl/pipeline/types.py` (URL-processing result and record-writer protocol) |

---

## Frontend Root: `frontend/`

| Path | Purpose |
|---|---|
| `app/` | Frontend feature route components retained from the former Next layout |
| `src/main.tsx`, `src/router.tsx` | Vite bootstrap and React Router route table |
| `src/routing/` | App-owned Link, navigation, dynamic import, and image helpers |
| `app/product-intelligence/product-intelligence-components.tsx` | Product Intelligence local UI pieces |
| `components/layout/` | shell, auth, nav, theme, scoped shell CSS modules |
| `components/ui/button.tsx`, `badge.tsx`, `input.tsx`, `card.tsx`, `metric.tsx`, `table.tsx`, `alert.tsx`, `dialog.tsx` | typed UI primitive owners |
| `components/ui/primitives.tsx` | compatibility barrel plus dropdown, toggle, tooltip, skeleton, field helpers |
| `components/ui/patterns.tsx` | shared operator-page UI patterns |
| `components/ui/table.module.css` | compact and commerce table styling |
| `components/crawl/crawl-config-screen.tsx` | Crawl Studio form and dispatch |
| `components/crawl/use-crawl-field-actions.ts` | Generate/test/save selector rows; saved generated selectors also create Knowledge Graph contracts |
| `components/crawl/crawl-run-screen.tsx` | Run workspace and Domain Recipe workflow |
| `components/crawl/crawl-run-screen.test-support.tsx` | Run-workspace test mocks, builders, rendering, and per-suite lifecycle setup |
| `components/crawl/form-fields.tsx` | Crawl form field controls and manual selector editor |
| `components/crawl/log-terminal.tsx` | Crawl run log terminal grouping and rendering |
| `components/crawl/records-table.tsx` | Crawl records table rendering |
| `components/crawl/record-thumbnail.tsx` | Crawl record image thumbnail rendering and broken-image cache |
| `components/crawl/crawl.module.css` | Crawl Studio feature styling |
| `components/crawl/use-run-polling.ts` | run polling |
| `lib/crawl/fields.ts` | Crawl field-name parsing and validation helpers |
| `lib/crawl/format.ts` | Crawl display formatting helpers |
| `lib/crawl/quality.ts` | Crawl data-quality scoring helpers |
| `lib/crawl/record-utils.ts` | Crawl record cleanup and value access helpers |
| `lib/crawl/scroll.ts` | Crawl viewport scroll helper |
| `src/api/client.ts` | auth-aware fetch wrapper |
| `lib/api/*.ts` | typed domain endpoint owners; `api-access.ts` owns API-key management and capability verification |
| `Dockerfile`, `nginx.conf`, `security-headers.conf` | Locked frontend build and non-root static SPA runtime with liveness and security headers |
| `lib/api/types.ts` | frontend API types |
| `app/api-access/` | authenticated API-key management, one-time secret reveal, REST verification, and MCP setup |
| `components/selectors/domain-memory/knowledge-graph-tab.tsx` | Domain Memory Knowledge Graph tab: bounded graph, relationships, contracts, source controls |
| `scripts/check-token-escapes.mjs` | frontend guard against new raw CSS-var Tailwind token escapes |

---

## Quick Guardrails

- Config belongs in `core/config/*`
- Fix extraction upstream, not in publish or persistence
- Do not create `_helpers.py`, `_utils.py`, or compat stubs
- Do not hardcode platforms in generic paths
- Test public behavior, not private internals

See `docs/ENGINEERING_STRATEGY.md` for the full anti-pattern list.

Deployment manifests: root `docker-compose.yml` is local development;
`docker-compose.production.yml` overlays fail-closed production inputs and
disables local database/Redis services. Backend process commands target the
project virtual environment explicitly.

Production operations evidence: `docs/plans/CRAWLERAI_AWS_OWNER_RUNBOOK.md` owns
the AWS/Cloudflare closeout checklist, restore and rollback drills, named owners,
residual-risk expiry, and final GO/NO-GO record. It stores references, never secrets.
