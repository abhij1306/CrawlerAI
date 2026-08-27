# CrawlerAI Invariants

Hard runtime and engineering contracts. Violations are bugs. Read only sections touched by the task.
Code and focused tests are authoritative when stale plans or audits disagree.

## 1. Ownership, config, and repository shape

- One concern has one owner. Extend or split that owner; do not create parallel managers, registries, helpers, stores, pipelines, or compatibility facades.
- Grep before creating a function, class, constant, file, config source, or normalization path. Consolidate duplicates and delete superseded code.
- Runtime strings, tokens, field names, selectors, URL patterns, thresholds, timeouts, and tunables live under `backend/app/core/config/`. Do not add bucket-local `constants.py`, `config.py`, or settings dictionaries.
- One rule has one config source. Explicit typed mappings beat import-time `globals()` mutation.
- Generic paths stay generic. Retailer/platform rules belong in declarative platform config or a genuine connector. A new abstraction must improve multiple domains or surfaces unless the user explicitly requests a site-specific path.
- Cross-subsystem calls use public typed contracts. Do not import another module's underscore-prefixed internals. Allowlists are shrinking debt ledgers.
- Delete completed migration shims and re-export stubs. Do not add `_misc`, `_helpers2`, `_v2`, `registry2`, or context-free root assets.
- Split files by responsibility, not to hide complexity or evade LOC gates. Facades orchestrate; owners implement.

Forbidden patterns consolidated from the former Engineering Strategy:

- inline or duplicate config; cross-bucket field aliases; env-bypassing tuning dictionaries
- hardcoded retailer/platform branches in generic acquisition, crawl, extraction, or publication code
- speculative caching, plugin hooks, policy engines, or cross-cutting layers outside task scope
- duplicate normalization, public-field cleanup, selector state, learned state, or artifact layouts
- private-function test coupling; blanket lint disables; normalized-AST LOC accounting; mega test modules
- binary mystery files at repository root; shell-owned DSN construction; build toolchains in runtime images

## 2. User controls and run contracts

- User-selected `surface`, traversal intent, proxy settings, diagnostics controls, and `llm_enabled` are authoritative. Heuristics may advise but never silently rewrite them.
- Run creation freezes active runtime, profile, extraction-release, and LLM settings needed for reproducibility. Live changes affect future runs only.
- Each batch URL owns its own database session and transaction. One failed URL cannot poison later URLs or the run-orchestration session.
- With `CELERY_DISPATCH_ENABLED=false`, URL concurrency is `1`.
- A run or URL result never reports clean success merely because transport returned HTTP 2xx.

## 3. Extraction and publication

Canonical ecommerce-detail flow:

`Harvest -> representation-only normalization -> entity graph -> target selection -> Resolve -> Publish -> verdict`

- Collectors emit immutable `Evidence`. Normalization may reshape values but cannot invent evidence, assign ownership, rank, or resolve semantics.
- Entity assembly owns product/offer/variant/asset relationships. Target selection chooses the requested product before resolution.
- Resolve owns accepted/rejected evidence IDs, conflicts, selected and derived facts, variant eligibility, offer inheritance, assets, and publication authorization.
- Publish serializes only the authorized surface projection and checks the record against it. Persistence and exports never repair extraction.
- Source order is a resolver tiebreaker, not permission to discard lower-tier evidence: adapter, structured data, network, JS state, DOM, then explicitly enabled grounded model evidence.
- `transport_outcome`, `data_integrity`, field evidence states, and evidence dispositions remain separate.
- Zero-record outcomes carry typed failure classifications and a stable diagnostic summary in `diagnose.json`.
- Terminal shells, error bodies, challenge pages, redirect-only pages, and URL/title-only placeholders are not product observations. Mark source unavailability and suppress fake detail records.

Field and identity rules:

- Requested fields plus configured canonical defaults define the contract. Missing fields require deterministic recovery or a visible reason.
- Candidate admission rejects breadcrumb categories, installment prices, promo values, system IDs/SKUs, structural tokens, placeholder types, related-product variants, sibling products, and non-product guide/glossary text before ranking.
- Network/embedded JSON is untrusted until URL, product ID, SKU, or selected-root evidence links it to the requested product.
- Product-root URL conflict checks inspect the root's own URL, never an arbitrary nested child, breadcrumb, recommendation, or asset URL.
- A URL-less schema Product may use its sole same-resource Offer URL as target-ownership evidence. Several or cross-resource offer URLs do not authorize the binding.
- Locale, price parsing, currency inference, availability vocabulary, and GTIN validation use their config owners. GTIN checksum failure is diagnostic and lowers rank; it does not suppress an explicitly declared GTIN whose digit length is valid. Integral price strings mean whole currency units unless a transform explicitly enables cents. Negative decimal values are rejected.
- Retailer identity and manufacturer identity are separate. Reject host-derived brand evidence during Resolve when product evidence identifies another brand.
- Public `barcode` is digits-only and length 8/12/13/14. `gender` is one of Men/Women/Unisex/Kids/Boys/Girls. Brand loses region/site suffixes. Product identity fields reject structural tokens.
- Asset dedupe uses canonical asset identity, not delivery URL equality. Preserve URL grammar such as commas inside `srcset` candidates.

Variant rules:

- Variant and offer facts stay entity-scoped. Parent facts may be derived only from resolved variants with explicit lineage.
- A selected JSON-LD `hasVariant` child admits its declared ProductGroup parent. Incomplete option-group and parent/default diagnostic shells are not sellable rows and do not make the explicit leaf matrix incomplete.
- Public variants are flat rows with `variant_id`, transport fields, configured public axes, and top-level `variant_count`.
- Never publish `selected_variant`, `variant_axes`, `available_sizes`, `option_*`, nested `option_values`, or variant `title`.
- Variant IDs are unique. Do not delete explicit inherited offer fields because they equal parent values.
- DOM axes without a same-product variant matrix do not authorize a synthesized cross-product. This remains the active Bombas-style extraction gap.

Never:

- repair titles, brands, SKUs, prices, availability, assets, variants, or identity in `publish/`, persistence, enrichment, exports, or UI
- mutate fields after the evidence graph or record a repair only in record-level transforms
- maintain parallel candidate arrays beside the Evidence ledger
- synthesize parent facts from `selected_variant`
- hide currency conflicts, resurrect rejected evidence, or treat HTTP success as clean integrity
- validate artifact regressions only from old `records.json`; replay stored HTML/network inputs through the real pipeline

## 4. Listing/detail separation

- Listing extraction never falls back to one detail-like metadata row. Zero listing rows produce `listing_detection_failed`.
- Detail extraction rejects category/collection pages and must not promote the first tile or page heading into a product.
- Detail expansion clicks only proven in-page/main-content controls. Never click header, nav, footer, marketing, assistant, or real navigation links.
- A crawl page must not open another tab/window. Neutralize `window.open` and new-tab targets; keep the popup guard as backstop.

## 5. Acquisition and browser runtime

Acquisition returns observations: requested/final URL, status, method, headers, blocked state, diagnostics, rendered HTML, visible/accessibility text, network payloads, expansion artifacts, and optional screenshots. It never writes logical product fields.

- Fast-finalize only successful 2xx responses with verified usable/extractable content. Error bodies continue through error/block classification.
- Retry/escalate only from policy and evidence, with enough URL-local budget. Record every retry. When budget is insufficient, return the observed result with an explicit skipped diagnostic.
- Do not retry static not-found pages, mismatched homepage/category shells, or existing low-quality detail rows merely missing defaults.
- Respect `capture_screenshot=False` on every outcome.
- Browser-driver disconnect is URL-local. Recycle a failed shared browser at most once. Browser close tasks remain observed if cleanup exceeds budget; do not cancel driver internals.

Patchright and challenge contracts:

- Patchright uses bundled headless Chromium. Rewrite headless UA/client hints coherently with the host OS. Do not add browserforge or JS fingerprint shaping.
- Navigate directly to the target. No origin warmup.
- Challenge recovery is bounded, re-reads and reclassifies live DOM every poll, and checks immediately after activity. A provider cookie is never required to observe that content cleared.
- Terminal Access Denied evidence fails fast. Cloudflare interactive interstitials remain solvable until their bounded budget expires. Turnstile clicks are best-effort, coordinate-based, widget-gated, and engine-neutral.
- `browser_outcome=usable_content` wins over provider headers, scripts, cookies, iframes, or telemetry. Only explicit blocked outcome, challenge title, strong visible blocker text, or forced hard-block status without usable content may override it.
- Provider noise alone never writes hard-block memory or triggers real-Chrome escalation.

## 6. Memory, cookies, SSRF, and bounded input

- Selector and learned structural memory is scoped by normalized `(domain, surface)`.
- Acquisition profiles/cookies/host protection are separate from extraction memory. Durable engine choice and handoff eligibility belong to editable `DomainRunProfile`; short-TTL host memory only biases block/backoff safety.
- Explicit run settings override learned contracts. Stale contracts stop forcing engine/handoff choices.
- Domain and run browser state is engine-scoped. Challenge-state cookies/localStorage and blocked-run state are never persisted or replayed.
- Browser-to-HTTP handoff requires sanitized state, matching proxy identity, and `handoff_eligible=true`. Try short-timeout curl first, then proven browser, then normal auto policy. Rendered/traversal/network-dependent paths are not handoff eligible.
- A shared HTTP client carries no cross-run cookie state. Redirect-chain cookies stay per fetch and are re-matched by domain, path, and Secure on every hop.
- URL validation and connection establishment are one SSRF boundary. HTTPX, curl, browser navigation/subresources, and every redirect connect only to the approved public IP while retaining original Host and TLS SNI. Mixed/private DNS fails closed.
- Untrusted request and response bodies are bounded before full materialization. Oversize bodies are errors, never successful content.
- Per-run browser cookie files are encrypted and bound to `(user_id, run_id, browser_engine)`, owner-only, deleted with the run, and cleaned when expired/orphaned. Plaintext or binding mismatch fails closed.
- Proxy rows store no URL userinfo. Credentials resolve only at acquisition time. One redactor owns API, logs, diagnostics, telemetry, and exceptions. Celery receives run IDs, not secrets.

## 7. Extraction memory

`backend/app/models/extraction_memory.py` is the only durable structural-memory owner. PostgreSQL is authoritative.

- One immutable `ExtractionReleaseSnapshot` freezes each run. Each persisted URL result links one `ExtractionManifest`.
- Selectors are domain-default recipes. Review promotions and feedback are typed `ExtractionOperatorLabel` rows.
- `backend/app/extraction/` is storage-free. It may use pure core helpers but cannot import extraction-memory ORM or persistence modules.
- Saved recipes rank admissible evidence only. They cannot create ownership, revive rejected evidence, or publish values.
- Model output is grounded Evidence, lazy off deterministic success, and enabled only by approved benchmark metadata plus exact adapter/artifact identity. Predictions resolve to retained source paths and values.
- Challengers diagnose or suspend a recipe through policy; they never mutate a published record.
- No learned/model value publishes without a source locator and resolver acceptance.

Never add parallel selector, review, feedback, knowledge-graph, runtime-snapshot, recipe, manifest, or learned-value stores.

## 8. Persistence and diagnostics

- `record.data` contains populated logical fields only: no empty values, private/internal keys, raw manifests, page context, or site chrome.
- `publish_url_result_artifacts` in `backend/app/persistence/url_result_artifacts.py` is the only per-URL artifact writer.
- Each URL result owns exactly `page.html`, `record.json`, and self-contained bounded `diagnose.json` under `runs/{run_id}/results/{url_result_id}/`.
- `diagnose.json` explains field status, accepted/rejected evidence, bounded previews, publication actions, failure classifications, and manifest context without opening another file or inventing another vocabulary.
- Run-level `report.json` groups diagnoses only. It does not add monitoring, retention, webhook, or notification behavior.

No parallel artifact roots, duplicate HTML, extra per-URL manifests/summaries/debug files, stale readers, or second reason vocabulary.

## 9. LLM, enrichment, and product intelligence

LLM:

- LLM runs only when both run settings and active config enable it. Failure is visible and does not corrupt deterministic state.
- Ecommerce-detail LLM is adjudication-only: select/reject grounded evidence, suggest reusable locators, or abstain. It never generates missing field values or replaces accepted deterministic facts.
- Non-detail LLM workflows remain explicitly gated.

Enrichment:

- Enrichment consumes persisted crawl records and writes derived rows. It does not clean polluted extraction output.
- Shopify category paths/attribute handles come from `shopify_categories.json`; Shopify-defined values come from `shopify_attributes.json`.
- Do not create local product-universe dictionaries for category synonyms, materials, colors, sizes, fabrics, or gender. Local rules may only implement generic parsing mechanics or vocabulary Shopify does not model.

Product Intelligence identity ladder, strongest first:

1. exact GTIN/UPC
2. exact decomposed manufacturer style/model core
3. brand-DTC own listing
4. exact brand plus strong title
5. exact brand plus distinctive model token
6. exact brand plus medium title
7. title-only refinement, never auto-accept

- Brand evidence is not gated by registry membership. Never fabricate brand without candidate evidence.
- Color/size differences are the same model, not automatic mismatch. Canonicalize volatile variant/tracking params before candidate dedupe.
- Do not score raw composite retailer IDs, use image/pHash matching for recall, or call LLM in deterministic matching.
- Google native search uses normal form fill plus Enter, no direct search-result `goto`, blanket quoted dorking, or random mouse behavior.

## 10. Authentication and public boundaries

- API startup never creates, promotes, reactivates, or resets users. Initial admin bootstrap is explicit, create-only, serialized by a durable consumed marker, and fails for an existing identity.
- Unsafe cookie-authenticated requests require exact allowed Origin/Referer and signed double-submit CSRF. Explicit bearer requests remain independent of cookies.
- Forwarded client identity is accepted only from configured trusted peers and resolved right-to-left to the first untrusted hop.
- Public API global/IP Redis-first limits run before API-key DB lookup; per-key limits run after authentication.
- MCP is stdio by default. Optional SSE binds only a literal loopback IP. MCP calls `/api/v1` with its principal key and never bypasses REST authentication/rate limits.

## 11. Production and release

- Central config accepts a complete database URL or composes and URL-encodes all components. Compose, workflows, and shell scripts never build DSNs.
- Non-development startup rejects placeholder/local PostgreSQL, non-TLS Redis, and non-HTTPS frontend origins.
- Migration and create-only bootstrap are separate one-off processes. API, worker, and beat never run them implicitly.
- Images invoke project virtual-environment binaries explicitly. Runtime stages are non-root, digest-pinned, locked, and contain no compilers, headers, curl, or dependency resolver.
- First-release Celery uses one solo worker per container and scales by container count.
- API liveness is `/health/live`; readiness is `/health/ready`; worker readiness uses Celery ping. Frontend is a non-root static SPA server with security headers.
- Every external Action is commit-pinned. Dependency audits are lock-based. Final images publish SPDX SBOMs.
- Release scans gate immutable digests and fail closed. Fixable/unclassified High/Critical findings block. No-fix exceptions require explicit review plus a non-secret risk reference.
- AWS uses OIDC. Docker credentials use runner-temporary config, the ECR helper, and disabled helper caching. Evidence contains no secrets.

## 12. Maintainability, tests, plans, and docs

- Static validation is owned by `scripts/check.ps1`; affected test selection is owned by `scripts/test.ps1` and `scripts/validation.json`. Do not bypass them, weaken gates, raise limits, or edit mappings to avoid relevant tests.
- Backend callable complexity fails above 15. Frontend complexity uses the existing VitePlus/ESLint threshold. LOC uses physical source lines with narrow legacy baselines that may not grow.
- Applied Alembic migrations are immutable history. Validation scope, exclusions, and legacy baselines live only in `scripts/validation.json`; do not add undocumented exceptions or grow a baseline.
- Split large test modules by public behavior. Shared fixture vocabulary may live in non-test support modules; preserve collected behavior.
- Test contracts and observable behavior, not private call order or existence of private constants.
- A plan slice is complete only after its mapped affected tests and canonical local gate pass. Full suites are CI-only.
- Do not use `--no-verify`, skip/xfail/delete failures for green, trivialize assertions, over-mock behavior away, swallow errors, or turn failures into warnings.
- Audit and plan docs are historical once complete/abandoned. Stable rules belong here; current ownership belongs in `CODEBASE_MAP.md`; product semantics belong in `BUSINESS_LOGIC.md`; implementation detail belongs in architecture docs.

## 13. Deleted product surfaces

Monitors, product alerts, in-app monitor notifications, and watch/alert MCP tools are deleted. Do not restore their routes, tables, frontend pages, schedulers, notifications, or Product Intelligence coupling without explicit new product scope.

The generic run-complete callback remains observability-only. It must not acquire monitor-specific diffing, retention, webhook, or notification logic.
