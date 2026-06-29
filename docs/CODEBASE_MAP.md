# CrawlerAI Codebase Map

Use this doc for ownership and file location. Do not filesystem-wander first.
If a file is not listed, assume it is a helper under a listed owner.

---

## Backend Root: `backend/app/`

### Support files outside `backend/app/`

| File | Purpose |
|---|---|
| `run_test_sites_acceptance.py` | Acceptance runner for curated test-site batches |
| `harness_support.py` | Acceptance helpers, `TEST_SITES.md` parsing, explicit-surface handling, audit shaping |
| `test_site_sets/commerce_browser_heavy.json` | Commerce acceptance manifest and quality expectations |
| `browser_surface_probe/core.py`, `browser_surface_probe/report_rendering.py` | Browser-surface diagnostic harness and report rendering |

### `api/` — route handlers only

| File | Purpose |
|---|---|
| `crawls.py` | Run creation, CSV ingestion, run listing/detail/control, commit fields, and logs |
| `crawl_domain.py` | Crawl domain recipe/profile/feedback/cookie-memory routes |
| `records.py` | Record listing, exports, provenance |
| `review.py` | Review payloads and approved mapping save |
| `selectors.py` | Selector CRUD, suggest, test, preview |
| `llm.py` | LLM provider catalog, config, connection test, cost log |
| `product_intelligence.py` | Product matching jobs, source products, candidates, match review |
| `data_enrichment.py` | On-demand ecommerce detail enrichment jobs and enriched product rows |
| `api_keys.py` | Dashboard API-key create/list/revoke endpoints; returns plaintext only on create |
| `public/*` | Public API v1 envelope, rate-limit helpers, HTTP-only extraction, domain info, capabilities, and deferred batch routes |
| `crawls.py` | Run creation plus Crawl Studio category discovery API |
| `auth.py` | Login, register, `/me` |
| `users.py`, `dashboard.py`, `jobs.py`, `health.py`, `metrics.py` | Named route modules |

### `core/` — infrastructure only

| File | Purpose |
|---|---|
| `config/` | Pydantic settings, policy modules, declarative recipes, and runtime tunables |
| `database.py` | Async SQLAlchemy engine and session factory |
| `redis.py` | Shared Redis connection |
| `security.py` | JWT, password hashing, encryption |
| `dependencies.py` | FastAPI auth dependency helpers |
| `public_auth.py` | Public API-key hashing/authentication and `/api/v1` user resolution |
| `telemetry.py`, `metrics.py` | Observability |

### `models/` — ORM entities

| Model | File | Purpose |
|---|---|---|
| `User` | `user.py` | account, role, token version |
| `ApiKey` | `api_key.py` | public API bearer-key ownership and validation |
| `CrawlRun` | `crawl_run.py` | run state, surface, settings, summary |
| `CrawlUrlResult` | `crawl_run.py` | canonical per-URL acquisition/extraction verdict, manifest pointer, and record count |
| `CrawlRecord` | `crawl_run.py` | extracted record payload and URL-result-linked provenance |
| `CrawlLog` | `crawl_run.py` | run logs |
| `DomainMemory` | `domain_memory.py` | selector memory scoped by `(domain, surface)` |
| `DomainRunProfile` | `domain_memory.py` | reusable execution defaults scoped by `(domain, surface)` |
| `DomainCookieMemory` | `domain_memory.py` | reusable browser state scoped by domain |
| `DomainFieldFeedback` | `domain_memory.py` | per-field keep/reject learning history |
| `HostProtectionMemory` | `domain_memory.py` | per-host block/success tracking |
| `ReviewPromotion` | `review.py` | approved review schema snapshot |
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
| `../data/product_intelligence/*` | Product Intelligence brand registry data, including Belk brand and exclusive/private-label lists |
| `enrichment/service.py` | On-demand enrichment job orchestration and persistence for ecommerce detail records |
| `crawl/category_discovery.py` | Shared Crawl Studio category discovery response assembly for one or more seed URLs |
| `connectors/public_api/extraction_service.py` | Public HTTP-only single-product extraction wrapper over normal crawl creation and per-URL pipeline processing |
| `connectors/public_api/domain_info_service.py` | Read-only public domain readiness view over domain memory, run profiles, and recent crawl rows |
| `enrichment/deterministic.py` | Deterministic enrichment normalization, taxonomy matching, and product attribute diagnostics |
| `enrichment/llm_diagnostics.py` | Data enrichment LLM rejection and skip-reason diagnostics |
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
| `acquisition/cookie_store.py` | Temp storage state plus domain cookie memory helpers |
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
| `crawl_engine.py` | Extraction facade and routing |
| `detail_extractor.py` | Detail-page preparation and field candidate arbitration |
| `listing_extractor.py` | Listing-page extraction |
| `structured_sources.py` | JSON-LD, microdata, OG, Nuxt, harvested JS state |
| `extract/field_candidates/*` | Field candidate collection, structured payload traversal, structured variant row assembly, finalization, and scoring |
| `extract/contracts.py` | Typed extraction contracts and the detail `CandidateSet` evidence ledger |
| `extract/detail/resolution.py` | Single owner for product/variant consensus, inherited offers, and traceable semantic transforms |
| `extract/detail/validation.py` | Single owner for missing evidence, incomplete offers, and currency-contradiction findings |
| `extract/detail/images/dedupe.py`, `dom/image_extraction.py` | Product asset collection and canonical asset-identity dedupe |
| `js_state/state_normalizer/` | JS state facade plus focused ecommerce payload, variant, identity, and product mapping modules |
| `js_state/job_mapper.py` | Configured job-detail JS-state mapping and reusable state-path traversal |
| `js_state/helpers.py` | Shared JS-state variant selection, availability, stock, price, and compact-row helpers |
| `js_state/variant_options.py` | JS-state variant axis, option-value, and display-label normalization |
| `network_payload_mapper.py` | Network payload to field mapping |
| `shared/field_coerce.py` | Canonical field coercion dispatch and public-record shaping |
| `shared/field_coerce_price.py` | Price, currency, and shared-price comparison coercion |
| `shared/field_coerce_text.py` | Brand, identity, SKU, barcode, gender, and category text coercion |
| `shared/field_coerce_url.py` | URL/image URL coercion and tracking cleanup exports |
| `field_url_normalization.py` | Tracking URL cleanup and query stripping |
| `dom/content_extractability.py` | Visible text/link/image extractability checks used by selector extraction |
| `dom/query.py` | Safe BeautifulSoup selector/find/text/traversal primitives shared by DOM extraction modules |
| `dom/selector_engine.py` | DOM selector extraction, image URL ranking, and selector result assembly |
| `dom/xpath_service.py` | XPath syntax validation, conversion, absolute XPath building, and selector value extraction |
| `dom/image_extraction.py` | DOM image URL scoring, dedupe, low-resolution upgrade, and page image extraction |
| `dom/section_extraction.py` | DOM label/value pairs, semantic heading sections, materials sections, and feature rows |
| `public_record_firewall.py` | Final public persisted-data schema/value firewall |
| `field_value_*.py` | Per-field normalization helpers |
| `field_policy.py` | Field eligibility by surface |
| `extract/listing_card_fragments.py` | Canonical listing-fragment discovery, scoring, and listing-card heuristics shared by traversal, browser artifact capture, and listing extraction |
| `extract/listing_candidate_ranking.py` | Listing candidate admission, support signals, utility rejection, dedupe, and set ranking |
| `extract/structured_listing_handler.py` | Structured JSON-LD listing record extraction and typed/untyped listing payload gating |
| `extract/network_listing_mapper.py` | Network listing rows and network-to-listing price/brand/currency backfill |
| `extract/record_overlay.py` | Primary-wins record overlay helper shared by JS-state, network, structured, and listing merges |
| `extract/table_extractor.py` | Meaningful table detection, filtering, context resolution, and structured table output |
| `extract/detail/assembly/tiers.py` | Detail tier execution order, DOM skip decision, and finalization transitions |
| `extract/detail/assembly/candidate_collection.py` | Detail candidate admission, evidence-backed arbitration, and field evidence summaries |
| `extract/detail/assembly/dom_section_targets.py` | Detail DOM context selection and section target field discovery |
| `extract/detail/assembly/dom_fallbacks.py` | DOM fallback field assembly for detail records |
| `extract/detail/variants/dom_coercion.py` | DOM variant axis and option-value coercion helpers |
| `extract/detail/variants/dom_extraction.py` | DOM variant row extraction, expansion, and backfill |
| `extract/detail/identity/structured_pruning.py` | Structured detail payload relevance and variant-leaf pruning |
| `extract/detail/assembly/dom_completion.py` | DOM completion gates and DOM variant collection decisions |
| `extract/detail/images/materialize.py` | Detail image candidate materialization before final cleanup |
| `extract/detail/assembly/record_assembly.py` | Detail record build/extract orchestration and detail rejection/failure reasons |
| `extract/detail/variants/dom_options.py` | DOM variant option availability, URL, image, and selected-state helpers |
| `extract/detail/images/dedupe.py` | Primary/additional detail image merge and dedupe helper |
| `extract/detail/variants/numbered_options.py` | DOM-axis hydration for raw numbered option variant rows |
| `extract/detail/assembly/raw_signals.py` | Raw detail breadcrumb category and deterministic gender signal helpers |
| `extract/detail/identity/core.py` | Detail/listing URL identity, redirect identity, and requested-detail matching |
| `extract/detail/identity/jsonld_identity.py` | JSON-LD identity helpers and duplicate product heading pruning |
| `extract/detail/identity/model_codes.py` | Detail model-number/code compatibility and token extraction |
| `extract/detail/price/core.py` | Detail price, currency reconciliation, visible PDP price backfill, and magnitude repair |
| `extract/detail/assembly/final_cleanup.py` | Ecommerce detail final cleanup orchestrator |
| `extract/detail/assembly/record_sanitization.py` | Detail placeholder, identity scalar, category, materials, and title cleanup |
| `extract/detail/price/money_repair.py` | Detail price precision, discount, original-price, and variant price repair |
| `extract/detail/variants/pruning.py` | Detail variant row sanitization and parent-record variant scalar pruning |
| `extract/detail/images/cleanup.py` | Final detail image cleanup, family matching, and parent image backfill |
| `extract/detail/identity/shell_filter.py` | Site-shell and utility-page detail rejection helpers |
| `extract/detail/variants/state_targets.py` | JS-state target maps for DOM variant URL/id enrichment |
| `extract/detail/text/sanitizer.py` | Detail long-text pollution filters, fulfillment copy cleanup, and low-signal scalar checks |
| `extract/detail/text/materials.py` | Materials-specific parsing and cleanup |
| `extract/detail/assembly/title_scorer.py` | Detail title promotion and shell-title scoring |
| `extract/variant_axis.py` | Variant axis key/display normalization and semantic axis-label gates |
| `extract/variant_option_value.py` | Variant option-value noise, UI-noise, color, and quantity-run gates |
| `extract/variant_choice_traversal.py` | Variant DOM choice traversal, group-name inference, and per-Soup cue-result caching |
| `extract/variant_identity_merge.py` | Variant axis splitting, identity, row richness, row merge, and size alias collapse |
| `extract/variant_dom_cues.py` | Variant DOM cue, scoped node-selection, sibling-signal helpers, and per-Soup selector caches |
| `extract/variant_dom_provenance.py` | DOM variant provenance capture for validator input |
| `extract/variant_group_validator.py` | Evidence-based DOM variant group admission and rejection logging |
| `extract/variant_normalization/*` | Stage-keyed variant record normalization, cleanup, backfill, and public flattening contract |
| `extract/variant_structural_pruning.py` | Structural variant row pruning for non-DOM/raw variant records |
| `extract/variant_value_guards.py` | Variant value and URL quality gates shared by DOM validation and normalization |
| `extract/*` | Other extraction helpers |

Canonical config owners:

| File | Purpose |
|---|---|
| `core/config/field_mappings.py` | canonical schemas, field aliases, and primitive field-name constants |
| `core/config/js_state_field_specs.py` | JS-state product and variant field mapping specs |
| `core/config/public_record_policy.py` | Public persisted/exported record exclusions, URL safety, and identity value policy |
| `core/config/variant_policy.py` | Public variant axes, flat variant transport fields, and variant axis aliases |
| `core/config/extraction_rules/` | extraction/runtime selector tokens split by common, image, detail, variant, listing/structured, and job concerns |
| `core/config/extraction_price_rules.py` | Detail price selectors, JSON-LD price fields, currency decimal places, and price repair thresholds |
| `core/config/selectors.py` | DOM selectors |
| `core/config/platforms.json` | platform metadata, signatures, JS mappings, readiness selectors |
| `core/config/network_payload_specs.py` | payload specs and endpoint tokens |
| `core/config/data_enrichment.py` | data enrichment statuses, limits, and taxonomy file path |
| `core/config/public_api.py` | public API key prefixes, envelopes, error codes, rate limits, extraction caps, MCP env names, and static capabilities |
| `core/config/knowledge_graph.py` | data-only Knowledge Graph vocabulary owner: node/edge types, statuses, selection origins, contract outcomes, identity ladder, read bounds, projection tunables |

### `mcp_server/` — hosted MCP wrapper

| File | Purpose |
|---|---|
| `client.py`, `tools.py`, `server.py`, `config.py` | Stateless FastMCP HTTP/SSE server for `extract_product`, `check_domain`, and `list_capabilities`; calls public REST API only |

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
| `review/__init__.py` | Review payloads and approved field mapping persistence |
| `selectors_runtime.py` | Selector CRUD and runtime lookup |
| `selector_auto_learn.py` | Strict DOM-observed selector auto-save into domain memory |
| `selector_suggestions.py` | Selector suggestion assembly from domain memory, deterministic DOM patterns, listing cards, and LLM candidates |
| `selector_self_heal.py` | Selector synthesis and validation |
| `domain_memory_service.py` | Domain memory load/save |

All selector memory is scoped by normalized `(domain, surface)`.

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

## Bucket 8: Knowledge Graph (extraction-owned, PostgreSQL-authoritative)

| File | Purpose |
|---|---|
| `core/config/knowledge_graph.py` | Data-only vocabulary/bounds owner: node/edge types, statuses, selection origins, contract outcomes, identity ladder, read bounds, projection tunables |
| `models/knowledge_graph.py` | 6 ORM models: `KGSiteVersion`, `KGEntity`, `KGRelationship`, `KGClaim`, `KGAssertionEvidence`, `KGExtractionContract` |
| `persistence/knowledge_graph.py` | Repository: `lock_site_version`, `upsert_entities/relationships/claims/contracts`, `add_evidence`, `fetch_neighborhood`, `count_graph_rows`, `purge_graph`, `load_runtime_snapshot` |
| `persistence/projection.py` | Run-complete projector: `project_extraction_result` — fingerprints templates, upserts structural entities/relationships, projects Evidence into product/offer/brand/category claims and extraction contracts |
| `core/knowledge_graph/templates.py` | Template helpers: `normalize_route`, `fingerprint_from_parts`, `fingerprint_template`, `extract_tech_signals` |
| `core/knowledge_graph/contract_runtime.py` | Frozen contract execution (pure, storage-free): `match_template`, `apply_contracts` — re-points decisions to preferred sources, emits `ContractOutcome` per field |
| `alembic/versions/20260629_0002_knowledge_graph.py` | Migration creating all 6 KG tables |

The Knowledge Graph owns site templates, canonical-field source candidates, source decisions, extraction contracts, product claims, and cross-crawl relationships. It is separate from acquisition-owned Domain Memory (Bucket 6) and resets independently. At run creation `load_runtime_snapshot` freezes the current graph state into `CrawlRun.extraction_runtime_snapshot`; the extraction engine matches page fingerprints against this frozen snapshot and applies saved source preferences via `apply_contracts`. Extraction emits observations only and must never import graph storage (ratcheted in `tests/unit/test_extraction_architecture.py`). The `/api/knowledge/*` read/refine endpoints and cold-start LLM proposer arrive in later slices. See `docs/INVARIANTS.md` §17.

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
| `components/crawl/crawl-run-screen.tsx` | Run workspace and Domain Recipe workflow |
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
| `lib/api/client.ts` | auth-aware fetch wrapper |
| `lib/api/index.ts` | only frontend backend-access layer |
| `lib/api/types.ts` | frontend API types |
| `scripts/check-token-escapes.mjs` | frontend guard against new raw CSS-var Tailwind token escapes |

---

## Quick Guardrails

- Config belongs in `core/config/*`
- Fix extraction upstream, not in publish or persistence
- Do not create `_helpers.py`, `_utils.py`, or compat stubs
- Do not hardcode platforms in generic paths
- Test public behavior, not private internals

See `docs/ENGINEERING_STRATEGY.md` for the full anti-pattern list.
