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

### `api/` — route handlers only

| File | Purpose |
|---|---|
| `crawls.py` | Run creation, CSV ingestion, run control, logs, domain recipe/profile/feedback/cookie-memory routes |
| `records.py` | Record listing, exports, provenance |
| `review.py` | Review payloads and approved mapping save |
| `selectors.py` | Selector CRUD, suggest, test, preview |
| `llm.py` | LLM provider catalog, config, connection test, cost log |
| `product_intelligence.py` | Product matching jobs, source products, candidates, match review |
| `data_enrichment.py` | On-demand ecommerce detail enrichment jobs and enriched product rows |
| `auth.py` | Login, register, `/me` |
| `users.py`, `dashboard.py`, `jobs.py`, `health.py`, `metrics.py` | Named route modules |

### `core/` — infrastructure only

| File | Purpose |
|---|---|
| `config.py` | Pydantic settings from `.env` |
| `database.py` | Async SQLAlchemy engine and session factory |
| `redis.py` | Shared Redis connection |
| `security.py` | JWT, password hashing, encryption |
| `dependencies.py` | FastAPI auth dependency helpers |
| `telemetry.py`, `metrics.py` | Observability |

### `models/` — ORM entities

| Model | File | Purpose |
|---|---|---|
| `User` | `user.py` | account, role, token version |
| `CrawlRun` | `crawl_run.py` | run state, surface, settings, summary |
| `CrawlRecord` | `crawl_run.py` | extracted record payload and provenance |
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

`crawl.py`, `user.py`, `llm.py`, `selectors.py`, `data_enrichment.py`, `common.py`

---

## Bucket 2: Crawl Ingestion + Orchestration

| File | Purpose |
|---|---|
| `crawl/ingestion_service.py` | Validate and normalize `CrawlCreate`, stamp run snapshots |
| `crawl/service.py` | `dispatch_run()` entry — delegates to `dispatch/` strategy |
| `crawl/crud.py` | DB create and state transitions |
| `dispatch/` | `RunDispatcher` protocol + `LocalRunDispatcher` + `CeleryRunDispatcher` |
| `crawl/profile/*` | Reusable domain run-profile normalization, merge, persistence, and acquisition-contract learning |
| `crawl/events.py` | WebSocket log emission |
| `product_intelligence/*` | Product web discovery, candidate crawl orchestration, deterministic match scoring |
| `data_enrichment/*` | On-demand enrichment job setup for ecommerce detail records |
| `crawl/batch_runtime.py` | URL loop, progress, pause, kill checks |
| `tasks.py` | Celery task entry |
| `pipeline/extraction_loop.py` | Per-URL orchestration: acquire -> extract -> normalize -> persist |
| `pipeline/url_processing_context.py` | Per-URL acquisition config and run-context resolution |
| `pipeline/persistence.py` | `CrawlRecord` writes, dedupe, summaries |
| `pipeline/runtime_helpers.py` | Typed stage helpers, browser diagnostics merge, failure-state persistence |
| `pipeline/direct_record_fallback.py` | Direct-record and explicit LLM gap-fill fallback |
| `pipeline/extraction_retry_decision.py` | Empty-extraction browser retry decisions |
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
| `acquisition/browser_runtime.py` | Shared Playwright runtime and limits |
| `acquisition/browser_fetch_support.py` | Browser fetch result, diagnostics, and page event assembly helpers |
| `acquisition/browser_capture.py` | Screenshots and network payload capture |
| `acquisition/browser_diagnostics.py` | Browser engine labels, profile diagnostics, and failed-fetch diagnostic contracts |
| `acquisition/browser_identity.py` | Browser fingerprint generation |
| `acquisition/browser_interstitial.py` | Location-interstitial detection and safe dismissal |
| `acquisition/browser_page_flow.py` | Page navigation and readiness probing |
| `acquisition/browser_proxy_config.py` | Browser proxy URL parsing, redaction, and Playwright proxy config |
| `acquisition/browser_readiness.py` | DOM readiness checks, listing/detail probes, outcome classification |
| `acquisition/browser_stage_runner.py` | Bounded browser-stage execution, timeout cancellation, and page/context teardown |
| `acquisition/browser_storage_state.py` | Browser storage-state capture and persist-policy marking |
| `acquisition/traversal.py` | Listing pagination and load-more |
| `acquisition/traversal_card_counting.py` | Card-count and progress-snapshot helpers used by traversal loops |
| `acquisition/pacing.py` | Host-level rate limiting |
| `acquisition/cookie_store.py` | Temp storage state plus domain cookie memory helpers |
| `fetch/fetch_context.py` | `fetch_page()` owner: HTTP/browser decision, escalation, block detection |
| `robots_policy.py` | robots.txt policy |
| `url_safety.py` | SSRF and public-target validation |

Import rule: import `fetch_page` from `app.services.fetch.fetch_context` directly.

Canonical config owner:

| File | Purpose |
|---|---|
| `config/runtime_settings.py` | browser runtime tunables and launch args |
| `config/browser_init_scripts.py` | browser stealth/coherence init-script builders |
| `config/browser_fingerprint_profiles.py` | static browser fingerprint profile data |

---

## Bucket 4: Extraction

| File | Purpose |
|---|---|
| `crawl_engine.py` | Extraction facade and routing |
| `detail_extractor.py` | Detail-page preparation and field candidate arbitration |
| `listing_extractor.py` | Listing-page extraction |
| `structured_sources.py` | JSON-LD, microdata, OG, Nuxt, harvested JS state |
| `extract/field_candidates/*` | Field candidate collection, structured payload traversal, structured variant row assembly, finalization, and scoring |
| `js_state/state_normalizer.py` | JS state to field mapping (canonical owner) |
| `js_state/helpers.py` | Shared JS-state variant selection, availability, stock, price, and compact-row helpers |
| `js_state/variant_options.py` | JS-state variant axis, option-value, and display-label normalization |
| `network_payload_mapper.py` | Network payload to field mapping |
| `shared/field_coerce.py` | Canonical field coercion dispatch and public-record shaping |
| `shared/field_coerce_price.py` | Price, currency, and shared-price comparison coercion |
| `shared/field_coerce_text.py` | Brand, identity, SKU, barcode, gender, and category text coercion |
| `shared/field_coerce_url.py` | URL/image URL coercion and tracking cleanup exports |
| `field_url_normalization.py` | Tracking URL cleanup and query stripping |
| `dom/content_extractability.py` | Visible text/link/image extractability checks used by selector extraction |
| `dom/selector_engine.py` | DOM selector extraction, image URL ranking, and selector result assembly |
| `public_record_firewall.py` | Final public persisted-data schema/value firewall |
| `field_value_*.py` | Per-field normalization helpers |
| `field_policy.py` | Field eligibility by surface |
| `adapters/registry.py` | Adapter resolution |
| `adapters/[platform].py` | Platform-specific extraction |
| `extract/listing_card_fragments.py` | Canonical listing-fragment discovery, scoring, and listing-card heuristics shared by traversal, browser artifact capture, and listing extraction |
| `extract/listing_candidate_ranking.py` | Listing candidate admission, support signals, utility rejection, dedupe, and set ranking |
| `extract/structured_listing_handler.py` | Structured JSON-LD listing record extraction and typed/untyped listing payload gating |
| `extract/article_card_parser.py` | Article/content listing card author, date, and summary parsing |
| `extract/network_listing_mapper.py` | Network listing rows and network-to-listing price/brand/currency backfill |
| `extract/content_listing_handler.py` | Content listing table-row extraction and open-field row tagging |
| `extract/content_surface_extractor.py` | DOM fallback extraction for content, article, and forum detail surfaces |
| `extract/table_extractor.py` | Meaningful table detection, filtering, context resolution, and structured table output |
| `extract/detail_tiers.py` | Detail tier execution order, DOM skip decision, and finalization transitions |
| `extract/detail_dom_extractor.py` | Detail DOM context selection, DOM fallback fields, and DOM variant recovery |
| `extract/detail_dom_variant_options.py` | DOM variant option availability, URL, image, and selected-state helpers |
| `extract/detail_image_dedupe.py` | Primary/additional detail image merge and dedupe helper |
| `extract/detail_numbered_options.py` | DOM-axis hydration for raw numbered option variant rows |
| `extract/detail_raw_signals.py` | Raw detail breadcrumb category and deterministic gender signal helpers |
| `extract/detail_price_extractor.py` | Detail price, currency reconciliation, and visible PDP price backfill |
| `extract/detail_record_finalizer.py` | Detail field cleanup, DOM variant backfill sequencing, variant row repair, and final quality normalization |
| `extract/detail_shell_filter.py` | Site-shell and utility-page detail rejection helpers |
| `extract/detail_state_variant_targets.py` | JS-state target maps for DOM variant URL/id enrichment |
| `extract/detail_text_sanitizer.py` | Detail long-text pollution filters, fulfillment copy cleanup, and low-signal scalar checks |
| `extract/detail_title_scorer.py` | Detail title promotion and shell-title scoring |
| `extract/shared_variant_logic.py` | Canonical variant identity, merge, richness, grouping, and axis helpers |
| `extract/variant_dom_cues.py` | Variant DOM cue and sibling-signal helpers |
| `extract/variant_dom_provenance.py` | DOM variant provenance capture for validator input |
| `extract/variant_group_validator.py` | Evidence-based DOM variant group admission and rejection logging |
| `extract/variant_record_normalization.py` | Variant value normalization delegated by detail record finalization before public variant flattening |
| `extract/variant_structural_pruning.py` | Structural variant row pruning for non-DOM/raw variant records |
| `extract/variant_value_guards.py` | Variant value and URL quality gates shared by DOM validation and normalization |
| `extract/*` | Other extraction helpers |

Canonical config owners:

| File | Purpose |
|---|---|
| `config/field_mappings.py` | canonical schemas, field aliases, and primitive field-name constants |
| `config/js_state_field_specs.py` | JS-state product and variant field mapping specs |
| `config/public_record_policy.py` | Public persisted/exported record exclusions, URL safety, and identity value policy |
| `config/variant_policy.py` | Public variant axes, flat variant transport fields, and variant axis aliases |
| `config/extraction_rules.py` | extraction/runtime selector tokens, structured-source key maps, detail selectors, shell/utility path rules |
| `config/variant_migration_rules.py` | Variant migration selectors, validation thresholds, and residual noise/url gates |
| `config/selectors.py` | DOM selectors |
| `config/platforms.json` | adapter metadata, signatures, JS mappings, readiness selectors |
| `config/network_payload_specs.py` | payload specs and endpoint tokens |
| `config/data_enrichment.py` | data enrichment statuses, limits, and taxonomy file path |

---

## Bucket 5: Publish + Persistence

| File | Purpose |
|---|---|
| `publish/verdict.py` | URL verdicts |
| `publish/metrics.py` | acquisition and URL metrics |
| `publish/metadata.py` | field-discovery metadata |
| `artifact_store.py` | HTML artifact I/O |
| `pipeline/persistence.py` | persistence owner shared with Bucket 2 |

Verdict set:
`success`, `partial`, `blocked`, `listing_detection_failed`, `empty`

---

## Bucket 6: Review + Selectors + Domain Memory

| File | Purpose |
|---|---|
| `review/__init__.py` | Review payloads and approved field mapping persistence |
| `selectors_runtime.py` | Selector CRUD and runtime lookup |
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

## Frontend Root: `frontend/`

| Path | Purpose |
|---|---|
| `app/` | Next.js App Router pages |
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

- Config belongs in `services/config/*`
- Fix extraction upstream, not in publish or persistence
- Do not create `_helpers.py`, `_utils.py`, or compat stubs
- Do not hardcode platforms in generic paths
- Test public behavior, not private internals

See `docs/ENGINEERING_STRATEGY.md` for the full anti-pattern list.
