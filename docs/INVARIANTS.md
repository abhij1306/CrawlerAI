# Invariants

These are the backend contracts. Violations are bugs, not style issues.
**Each rule below includes what a violation looks like so there is no ambiguity.**

---

## HOW TO USE THIS FILE

Before writing any code, read each rule that touches your subsystem.
If your change would produce an output matching a VIOLATION signature below, stop and redesign.
These rules override any plan doc, any inline comment, and any agent reasoning about "exceptions."

---

## 1. Config and Constants — Zero Tolerance

**Rule:** Every string token, timeout value, threshold, field name, URL pattern, and numeric constant
that controls runtime behavior lives in `app/core/config/`. Nowhere else.

**VIOLATION signatures — if your code matches any of these, it is wrong:**
- A `.py` file outside `app/core/config/` contains a string like `"shopify"`, `"greenhouse"`, `"DataDome"`, a URL pattern, a timeout integer, or a field name as a bare constant
- A new `constants.py`, `config.py`, or `settings.py` file is created inside any bucket folder
- The same threshold or token appears in two different files
- A dict or constant inside a service module silently overrides what `app/core/config.py` controls via env

**Fix:** Move the constant to the appropriate file in `app/core/config/` and import it. If no appropriate file exists, extend the nearest one. Do not create a new config file without confirming no existing config file can absorb it.

---

## 2. No Duplication Before Search

**Rule:** Before creating any function, class, constant, or file, run a grep to confirm it does not already exist.
If it exists, extend it. If a similar version exists, consolidate — do not create a parallel copy.

**VIOLATION signatures:**
- Two functions in different files do the same normalization (e.g., price cleaning in both `detail_extractor.py` and `listing_extractor.py`)
- A field alias defined in both `config/field_mappings.py` and a bucket-local dict
- A new adapter that reimplements logic already in `field_value_core.py`
- A plan doc that proposes the same fix as a closed plan that was never verified

**Fix:** Grep first. Consolidate to the canonical owner. Delete the duplicate.

---

## 3. Extraction Model — Field Quality and Repair

**How ecommerce-detail extraction works:**
All collectors write immutable `Evidence` rows into one ledger. Normalization is representation-only: it may preserve raw values and canonicalize value shape, but it must not add evidence, assign ownership, rank, or infer semantics. Entity assembly groups evidence into product, offer, variant, and asset entities. Target selection chooses the primary product before canonical field resolution. Resolve owns accepted/rejected evidence IDs, conflicts, selected facts, derived facts, variant eligibility, asset selection, and publication policy. Publish serializes only the surface-specific publication projection and compares the serialized record back to that projection.

There is no downstream semantic repair stage. Title cleanup, brand rejection, SKU repair, variant-family filtering, image choice, availability normalization, and cross-product rejection belong upstream in collector admission, entity linking, target selection, resolution, or asset decisions. Persistence writes the authorized public record and performs no extraction repair.

**Source priority is a resolver tiebreaker, not a source discard rule:**
1. Platform adapter
2. JSON-LD / Microdata
3. Network payload intercept
4. JS state
5. DOM selector / heuristics
6. LLM-adjudicated evidence only when the user enabled LLM

Variant and offer facts remain entity-scoped. Parent offer/range/availability values may be derived from resolved variant facts only when the derivation has explicit lineage. A variant ID may be derived from one accepted unique SKU only when the derivation is recorded. No hidden post-resolution mutation is allowed.

Extraction results expose `transport_outcome`, `data_integrity`, per-field evidence states, and terminal evidence dispositions. Field states include legacy states plus v2 states such as `captured_published`, `captured_suppressed`, `captured_conflicting`, `captured_unowned`, `source_unavailable`, and `not_requested`. Transport success never implies clean data integrity. Proven product-data-source failure must be represented as honest source unavailability rather than an extraction defect.

Variant and additional-image coverage is `not_applicable` only when the run explicitly did not request that capability; absent capture evidence remains `unknown`, and captured-but-unpublished rows are `partial`.

Every zero-record extraction result must carry one or more typed failure classifications using the extraction taxonomy (`wrong_surface`, `insufficient_input_bundle`, `discovery`, `record_boundary`, `entity_binding`, `semantic_resolution`, `canonicalization`, `locale_normalization`, `validation`, `unsupported_representation`, `model_service_failure`, `internal_error`). `diagnose.json` must expose those classifications plus the stable diagnostic summary and manifest context when available.

Terminal shell acquisitions, including HTTP error bodies, challenge pages, browser low-content shells, redirect-only shells, and URL/title-only placeholders, are not successful product observations. They must mark affected detail fields as `source_unavailable` and suppress public `ecommerce_detail` records when the only surviving public values are the requested URL and a URL-derived title.

---

**Active known bugs:** DOM-only variant axes can remain unresolved when the captured sources contain no product-scoped variant matrix. Details below. Keep this section for active extraction bugs only. Do not document already-fixed bugs here.

### Known Extraction Gaps

Run 1 artifact sampling on 2026-06-28 established these source/collector boundaries:

- Availability: Nike Air Force 1 (`url_result_id=2393`) and Apple iPhone 16 (`url_result_id=2407`) contain no product-scoped availability value in captured HTML. Nike's `sold out` text is translation copy, not selected-product state; Apple's availability wording is generic purchase-flow copy. Missing availability is expected for these captures.
- Availability: Williams-Sonoma Bambino Plus (`url_result_id=2429`) contains six `Offer` rows with `availability=https://schema.org/InStock` nested under `Product.offers` as an `AggregateOffer.offers` list. The JSON-LD collector previously read only the aggregate row. It now recursively collects nested offers; artifact replay resolves `availability=in_stock`.
- Variants: ColourPop Going Coconuts (`url_result_id=2388`) exposes one Shopify `Default Title` row. Sibling-product swatches are separate products, not variants of the selected product. Omitting public variants is expected.
- Variants: Bombas ankle socks (`url_result_id=2389`) exposes four color controls and three size controls in DOM, but no captured product-scoped variant matrix connecting combinations to SKU, offer, or availability. The extractor reports `EXPECTED_VARIANT_AXIS_MISSING` with zero materialized variants. This remains an upstream collector gap. Do not synthesize the color/size cross-product from DOM axes alone; recover the product-state or network variant matrix with same-product evidence.

**Visible detail prices are extraction-owned. Owner: `detail_extractor.py` + `config/extraction_rules.py`.**

When structured data lacks price but the rendered detail DOM exposes a product display-price block, `extract/detail_price_extractor.py` may fill `price` and `original_price` from configured detail price selectors. This is still upstream extraction. Do not add price repair in `publish/` or `pipeline/`.

**Definitions:**
- **Requested fields**: Fields explicitly listed in run settings via `requested_fields`
- **Default canonical repair fields for ecommerce detail**: `price`, `title`, `image_url` (as defined in config)
- **High-value fields**: The union of requested fields and default canonical fields for the active surface
- **Missing-field diagnostic**: A structured reason why a field could not be extracted (non-public, requires authentication, dynamically loaded only, etc.)

**Canonical field quality is extraction-owned.**
For ecommerce detail, missing high-value fields such as `price`, `title`, and `image_url` are not acceptable just because one source tier had high total confidence. If the run requested deeper fields such as `brand`, `sku`, `variants`, or `availability`, those requested fields join the contract. Extraction must either repair contract fields, mark a diagnostic reason they are not public/extractable, or leave a visible missing-field diagnostic before persistence.

Ecommerce detail candidate admission must reject semantic artifacts before ranking. BreadcrumbList JSON-LD is not a detail category source. DOM breadcrumbs may provide category only after UI/root labels and product-title suffixes are removed. Price repair may correct 100x cent/magnitude drift only when visible DOM, same-product variant evidence, or an explicit host/currency conflict corroborates the smaller value; host name alone must not divide integral prices by 100. Installment/payment-plan prices, promo variant values, hex-only color values, system SKUs, structural IDs, placeholder product types, raw list-string text, related-product variants, and whole-value non-product guide/glossary text must not win as canonical fields.

Public ecommerce detail output has a flat variant contract. Persisted/exported `variants` rows may contain row-level `variant_id`, public transport fields (`sku`, `price`, `currency`, `url`, `image_url`, `availability`, `stock_quantity`), and configured public variant axes from `app/core/config/field_mappings.py` (`PUBLIC_VARIANT_AXIS_FIELDS`); `variant_count` is top-level only. Public output must not expose `selected_variant`, `variant_axes`, `available_sizes`, `option_*`, variant `title`, nested `option_values`, or other variant-only identity helpers. Public row-level `variant_id` values must be unique within one product record; duplicate ids are an upstream identity/linking failure, not a downstream export cleanup task. If legacy rows are still present internally, the public boundary must flatten and strip them before persistence/export.

Complete variant offers are semantic data, not transport duplication. Public-contract shaping must not delete inherited `price`, `currency`, or `availability` after the resolver makes them explicit. Product/variant consensus and offer inheritance belong to `app/extraction/resolution/`; findings belong to `app/extraction/validation.py`.

Locale and market interpretation are policy, not structural extraction. Decimal/thousands parsing, ccTLD/locale currency inference, currency-symbol mapping, and GTIN check-digit validation belong to `app/core/config/locale_format_rules.py`. Availability enum/tokens and token-to-enum normalization belong beside the canonical enum in `app/core/config/extraction_rules/`. Extraction normalizes evidence by delegating to these config-owned policy surfaces; resolution remains the semantic authority for choosing currency evidence and deriving currency fallback facts.

Asset dedupe uses canonical asset identity, not delivery URL equality. Storefront-host and CDN-host Shopify URLs for the same file, and transformed Nike URLs for the same asset ID, are one asset. Keep the strongest delivery URL.

Image candidate parsing must preserve delivery-URL syntax before normalization. In particular, a comma inside a `srcset` URL is part of that URL; only the candidate grammar may separate source-set entries. A malformed relative fragment created by source-set parsing is not admissible image evidence.

Network and embedded JSON admission is same-product evidence only. Ad/feed/analytics/recommendation payload roots, sibling products, and selected-color conflicts must be rejected or diagnosed before entity assembly unless an explicit URL, product id, SKU, or selected-root relationship ties the payload to the requested PDP. File extensions are not required for image evidence when the asset URL, response metadata, or product-scoped lineage proves the URL is an image.

Retailer/site identity and product manufacturer identity are separate facts. When a title suffix is corroborated as host identity and a distinct title/path prefix supplies the product brand, host-derived brand evidence must be rejected during Resolve rather than repaired after publication.

Public-field identity validators are single-owner rules at the public boundary (`field_value_core.py` / `FieldCoercion`):

- **`barcode`**: digits-only, allowed lengths `8`, `12`, `13`, `14`; otherwise absent and may be rerouted to `sku`.
- **`gender`**: must be one of `Men`, `Women`, `Unisex`, `Kids`, `Boys`, `Girls` or absent.
- **`brand`**: must not keep trailing region/site suffixes (`| US`, `- UK`).
- **`product_id`, `title`, `product_type`**: must drop structural/internal tokens (`plp`, `pdp`, `specifications`, media-player tokens).

**Enrichment is not extraction cleanup.**
Data enrichment consumes persisted `record.data` as the upstream extraction contract. It must not add blocklists, URL-token cleanup, UI-title suppression, category/source correction, or field-specific compensations for polluted canonical fields. If enrichment output exposes garbage such as URL tokens in `brand`, UI copy in `title`, impossible `size` values, or breadcrumb/category pollution, fix the acquisition/extraction candidate, coercion, ranking, or finalization path before persistence.

**Shopify taxonomy and attributes are the enrichment source of truth.**
Data enrichment must use `shopify_categories.json` for product category paths and category attribute handles, and `shopify_attributes.json` for Shopify-defined attribute values such as colors, sizes, fabrics, materials, and target gender. Do not build local product-universe dictionaries for categories, colors, materials, sizes, or category synonyms. Small local rules are allowed only for generic parsing mechanics such as token singularization, UI noise stripping, source-field lookup, and availability wording that Shopify does not model.

**Ecommerce detail LLM is adjudication-only.**
Ecommerce detail must not call missing-field value generation. LLM may later choose or reject existing evidence IDs, suggest reusable selectors/source references, or abstain. Verified recipes store selectors, JSON paths, endpoint families, and validation rules by `(domain, surface)`; they never store extracted values. Non-detail LLM workflows remain explicitly gated by run settings and active config.

---

**VIOLATION signatures — do not introduce these:**
- Replacing the per-field `candidates` + `_winning_candidates_for_field` system with a record-level merge or a single `winner` variable
- Adding a new tier or source that writes directly to `record` instead of going through `_add_sourced_candidate`
- Accepting a partial ecommerce detail record with missing requested/default high-value fields and no repair attempt or diagnostic
- Treating `requested_fields=[]` as permission to ignore ecommerce detail quality
- Forcing optional deep ecommerce fields such as `brand`, `sku`, or `variants` when the user did not request them
- Persisting or exporting legacy variant keys such as `selected_variant`, `variant_axes`, `available_sizes`, `option_*`, nested `option_values`, or variant `title`
- Letting non-numeric barcodes, region-suffixed brands, or structural identity tokens survive the public record boundary
- Fixing missing variants by adding hidden browser-side extraction that bypasses normal field provenance
- Calling `backfill_detail_price_from_html` only at the end of the full tier sequence but not after early exit paths
- Fixing missing visible PDP prices in persistence/export instead of `detail_extractor.py`
- Calling ecommerce-detail `extract_missing_fields()` or accepting an LLM-generated field value
- Letting LLM replace a populated adapter / structured / network / JS / DOM value without an explicit conflict-review workflow
- Maintaining parallel candidate source/evidence arrays beside `CandidateSet`
- Mutating public detail fields after `_evidence_graph` is serialized
- Recording a repair only in record-level `_transforms` without a matching graph transform
- Silently rewriting a contradictory currency or dropping the contradicting evidence instead of emitting a finding
- Deleting explicit variant offer fields because they equal the parent offer
- Treating a thin acquisition shell with only URL/title identity as a complete detail record without a high-severity evidence finding
- Adding enrichment-side blocklists or cleanup to hide polluted extracted `title`, `brand`, `category`, `size`, `material`, or other canonical source fields
- Adding local category synonym maps such as "matching sets -> outfit sets" instead of improving Shopify-backed taxonomy matching
- Adding hand-maintained material/color/category lists when Shopify attributes or category metadata already contain the vocabulary

---

## 4. Delete Before Adding

**Rule:** When fixing a bug or adding a feature, the first question is always:
"What existing code can I delete or simplify?" Adding more code to compensate for broken existing code is a violation.

**VIOLATION signatures:**
- A new normalization pass added in `publish/` to fix values that `detail_extractor.py` already should have cleaned
- A new fallback branch added in `pipeline/core.py` to handle a case that should be rejected upstream
- A helper function added that duplicates logic in a file that was "too complex to refactor right now"
- A plan that adds 3 new files without deleting any

**Fix:** Trace the bad value upstream. Fix it at the source. Delete the downstream compensation if it existed.

---

## 5. User Control Ownership

**Rule:** User-selected controls are authoritative. Do not silently rewrite `surface`, traversal intent, `proxy_list`, or `llm_enabled`.

**VIOLATION signatures:**
- Heuristics or adapters silently change the run's `surface` after creation
- Traversal runs without settings authorizing it
- LLM activates without both run settings AND active config enabling it

---

## 6. Acquisition — Observe, Render, Diagnose

**Rule:** Acquisition returns observational facts only: URL, final URL, status, method, headers, blocked state, diagnostics, and artifacts. It does not invent blocker causes, insert retries not in policy, or escalate without evidence.

Browser acquisition may use Patchright or real Chrome to produce better observations: rendered HTML, network payloads, visible text, accessibility text, readiness probes, and screenshots when enabled. It may also produce explicit detail-expansion artifacts (HTML/JSON from clicked size/color variant controls, expanded accordion sections, etc.). These are observation artifacts and are allowed inputs to extraction and LLM repair.
Browser acquisition must not fabricate fields. It must not run hidden page scripts that directly assign `price`, `brand`, `variants`, or other logical fields outside the normal extraction/repair provenance path.

Internal-API replay may reuse a captured JSON endpoint only when it is HTTPS, passes public-target validation, and is on the same host or an allow-listed first-party subdomain. Endpoint memory is scoped to the exact source route, including configured significant query parameters; it must never synthesize an endpoint URL from another product or listing page. A learned endpoint must pass one anonymous replay before persistence. Failed eligible endpoints accrue a bounded per-endpoint failure count and are evicted at the configured threshold. An `api_replay` acquisition has empty HTML by design; its bounded `network_json` artifact is valid extraction evidence and must follow normal provenance.

Internal-API replay is disabled by default until controlled and live route/identity parity is proven. Stored endpoint metadata is a candidate, not an activation signal.

A crawl page must never open a second browsing context. As soon as the page is created, `suppress_new_context_openers` installs an idempotent guard (init script for every navigation plus an immediate `evaluate` for the live document) that neutralizes both new-tab vectors: `window.open` is overridden to return null, and a capture-phase click listener rewrites any anchor `target` to `_self`. Detail expansion deliberately keeps clicking accordions/tabs/"show more"; suppression is what makes those clicks safe so collapsed content is still revealed without a tab flashing open. The reactive popup guard (`install_popup_guard`) stays as the backstop for anything JS contrives that attribute/`window.open` rewriting can't catch — it is the safety net, not the primary defense. Detail admission (`_candidate_is_admitted`) is the third layer: navigational anchors (a real http(s) `href` or `target=_blank`/`_new`) are never clicked even when they also carry `aria-controls`, so only genuine in-page toggles are exercised.



Challenge recovery is part of acquisition, not extraction. Direct browser navigation must run the bounded challenge wait/activity/retry loop. A provider-marked low-content shell may not be accepted as final just because the blocked-page classifier is not yet `blocked=True`; it must be re-polled until it becomes usable content or the configured challenge budget is exhausted.

Browser retry is allowed only when policy and diagnostics justify it, and only when enough URL-local budget remains to complete a meaningful browser attempt. If an HTTP result indicates a block/shell but the remaining budget is below `browser_retry_min_remaining_seconds`, acquisition returns the observed HTTP result with `browser_escalation_skipped=insufficient_budget` instead of starting a doomed browser navigation/settle stage.

Empty extraction may retry browser for retryable HTTP statuses, blocked/shell evidence, listing-integrity recovery, and non-browser HTML with no static detail evidence. Detail runs with explicit requested fields may choose browser up front because those fields often require rendered DOM or expansion. It must not retry browser for static detail "not found" pages (for example `Page Not Found`, `Product not found`, or `Nothing to see here`), static homepage/category shells that do not match the requested detail slug, or low-quality detail records that already exist but are missing default fields. Missing `price`, `title`, `image_url`, or requested fields after a completed acquisition should be handled by deterministic extraction diagnostics and the explicit LLM path when enabled, not by hidden HTTP-to-browser escalation. Every retry must be logged.

Diagnostics controls are user controls. If `diagnostics_profile.capture_screenshot` is `False`, browser acquisition must not capture any screenshots, regardless of outcome.

Browser-driver disconnects are URL-local failures. If a shared browser dies during `new_context`, page bootstrap, or content serialization, the runtime may recycle that browser once, but `_batch_runtime.py` must keep the failure scoped to the current URL and continue the batch.

Every batch URL owns its own database session and transaction, including serial/local execution. A failed flush or `PendingRollbackError` for one URL must never poison the run-orchestration session or stop later URLs. When `CELERY_DISPATCH_ENABLED=false`, batch URL concurrency is `1`; local mode does not silently retain the Celery parallel execution policy.

Browser close operations are bounded but not cancellation-owned by timeout wrappers. If Patchright/Playwright close exceeds its cleanup budget, the close task remains observed until completion; callers must not cancel driver internals and create unhandled `TargetClosedError` futures.

**Patchright runs headless bundled Chromium; headless leaks must be masked.**

- Engine is `patchright` headless bundled Chromium (`--headless=new`), not Patchright's headful `channel="chrome"` mode. Headless leaks a `HeadlessChrome` UA token with no `sec-ch-ua` hints, which PX/Akamai/DataDome block on sight.
- `build_playwright_context_spec` MUST rewrite the UA to plain `Chrome` with coherent `sec-ch-ua` headers. UA OS token, `sec-ch-ua-platform`, and native `navigator.platform` MUST agree, keyed off host OS. Real Chrome (headful, native context) is exempt.
- No `browserforge`, no JS init-script shaping. Patchright's "no fingerprint injection" guidance applies only to headful `channel="chrome"` and never justifies dropping the mask while headless.
- There is no origin warmup. Acquisition navigates directly to the target URL on every engine (Patchright and real Chrome); a blocked product URL is recovered in place by the challenge loop, never by pre-seeding cookies from the origin root. The critical path carries no speculative warmup navigation.
- Challenge recovery re-checks for clear immediately after challenge activity (activity is ~2s; providers often clear during it) to avoid a needless engine escalation on an already-usable page.
- A terminal hard block (title/strong "Access Denied" evidence, no active challenge or challenge-element markers) never clears by waiting; the recovery loop exits early and skips the retry-goto so real-Chrome escalation is not delayed by the full challenge budget. **Cloudflare interactive interstitials are the explicit exception:** a "Just a moment…" / "Checking your browser" shell (Cloudflare provider + interstitial marker, even before the Turnstile iframe paints) is solvable, not terminal. `_is_solvable_interactive_challenge` must classify it as non-terminal so the recovery loop keeps polling long enough for the Turnstile widget to render and be clicked instead of failing fast. Akamai/DataDome "Access Denied" stays terminal.
- Cloudflare Turnstile checkboxes are solved by a real coordinate click, on both engines. The recovery loop is engine-agnostic (`recover_browser_challenge` drops the engine), so when a Turnstile widget is present (`CLOUDFLARE_TURNSTILE_SELECTORS` match) `_maybe_click_turnstile` moves the mouse into the widget and clicks the checkbox hit point, latched so it fires once and re-fires only after a short poll cooldown. The click is best-effort and gated on an actual Turnstile match: non-Cloudflare challenges are never clicked.
- Challenge recovery MUST re-read and re-classify the live DOM on every poll. It may not gate the clear-check on a provider cookie (e.g. Akamai `_abck`): a provider shell (Akamai/DataDome/PerimeterX) clears by swapping in real content, so the re-read HTML is the source of truth. Gating the re-check on a cookie that never appears in-page makes Patchright miss an already-usable page and wastes the whole challenge budget before a needless real-Chrome escalation. A missing provider cookie is at most a hint, never a reason to skip the DOM re-check.

**Usable content beats provider noise. This is a hard contract.**
If browser diagnostics report `browser_outcome == "usable_content"`, provider telemetry such as `provider:*`,
`active_provider:*`, `challenge_provider_hits`, vendor headers, Akamai/DataDome/Cloudflare script markers,
or challenge iframe markers is diagnostic evidence only. It must not by itself set `blocked=True`,
`failure_reason=challenge_shell`, host hard-block memory, or real-Chrome retry.

Only these can override `usable_content`:
- explicit blocked outcome (`challenge_page`, `low_content_shell`)
- challenge-title evidence (`title:*`)
- strong visible blocker text evidence (`strong:*`, for example real CAPTCHA/access-denied copy)
- HTTP-forced hard block status where no usable browser content was recovered

This rule exists because modern commerce pages often load normal PDP content while bot-defense scripts,
cookies, iframes, or Akamai/DataDome/Cloudflare markers remain present. Treating those markers as a block
is a crawler bug, not stricter security detection.

**VIOLATION signatures:**
- Block detection classifies a page as blocked based on a vendor header alone when useful content is present and extractable
- Block detection classifies a page as blocked from generic `captcha` text or `recaptcha` / `hcaptcha` provider markers alone when the page still has real extractable listing/detail content and no stronger challenge evidence such as challenge-title hits, active challenge markers, or challenge elements
- `browser_outcome == "usable_content"` plus only `provider:*`, `active_provider:*`, `challenge_provider_hits`, vendor headers, or challenge iframe markers becomes `challenge_shell`
- A usable detail page retries from Chromium to real Chrome solely because Akamai/DataDome/Cloudflare provider markers are present
- Host protection memory records a hard block from a usable browser page with provider markers but no title/strong blocked evidence
- A retry happens that is not logged and visible in diagnostics
- Browser escalation starts when remaining acquisition budget is below `browser_retry_min_remaining_seconds`, producing predictable `Browser navigation/settle stage exceeded timeout_seconds=...` failures
- Serial URL processing reuses the run-orchestration SQLAlchemy session for extraction/persistence work
- `CELERY_DISPATCH_ENABLED=false` still allows `url_batch_concurrency > 1`
- A static product-not-found or homepage-shell detail page retries browser only to rediscover the same non-product page
- Provider-marked low-content shells skip the bounded recovery loop, or a Cloudflare "Just a moment" interstitial is treated as a terminal hard block and fails fast before the Turnstile widget can render and be clicked
- A crawl page opens a second browsing context (new tab/window) — `window.open` or a `target=_blank` anchor is left un-neutralized so a tab flashes open during navigation or detail expansion
- Browser escalation triggers for a URL that returned 200 with complete requested/default high-value fields
- Browser-side code writes logical extraction fields directly into the record instead of returning observation artifacts
- Browser acquisition captures a screenshot when `capture_screenshot=False`
- Launching Patchright first when a learned contract specifies real Chrome, without explicit user override or when the contract has been marked stale (see Rule 9)

---

## 7. Listing and Detail Stay Separate

**Rule:** Listing extraction never falls back into single-record detail behavior. A
DOM-only listing record needs repeated structural boundaries plus a record-local title
and detail URL; a singleton needs a structured URL-identity join. A listing run with
zero records produces `listing_detection_failed`. It never produces a fake success
with one row of page metadata.

Listing recipes are grounded record-relative source paths scoped by `(domain,
surface, route)`. They store no values and no CSS selectors, and every replay must
ground every required fact on every discovered record before publication.

Network listing rows obey the same boundary gate: one response array needs at
least two title + same-site detail-URL records before it may publish. A direct
detail API replay must expose a record URL for the requested route; a response
for another route is stale input and falls back to normal acquisition.

When a repeated network row has an opaque record ID but no detail URL, it may use
only a page-local URL anchor or a captured URL template with an explicit ID
placeholder. The response ID is substituted into that observed template. Never
invent a URL format from a platform name or a static site rule.

Detail extraction must also reject collection/category URLs that expose product-tile prices. A category URL submitted under `ecommerce_detail` is a bad seed, not a single PDP. Do not turn its first tile or page heading into a detail record.

**VIOLATION signatures:**
- A listing run returns 1 record containing the page title, OG description, or brand name
- A DOM-only singleton/footer/navigation card is published as a listing record
- A listing recipe reuses a stale value or a binding that fails on any record
- A network array, recommendation set, or stale direct API response publishes
  without matching the requested listing/detail identity
- `verdict.py` returns `success` for a listing run that extracted zero product rows
- `crawl_engine.py` routes a listing URL through `detail_extractor.py`
- An `ecommerce_detail` run on `/c/...`, `/category/...`, or `/collections/...` persists a fake detail record from a product tile
- Detail expansion clicks header/nav/footer chrome and navigates a PDP request onto a marketing or utility page

---

## 8. Persistence — User-Facing Payload Only

**Rule:** `record.data` contains only populated logical fields. No empty values, no `_` internals, no raw manifest containers, no internal page-context blobs, no site chrome.

**VIOLATION signatures:**
- Exported CSV contains fields like `_raw`, `_source`, `__nuxt`, or empty string columns
- `record.data` contains breadcrumb text, footer links, or support page anchors
- Detail records contain breadcrumb/support/link spillover or other internal page-context scaffolding

---

## 9. Domain Memory Scoping

**Rule:** Domain memory is always scoped by normalized `(domain, surface)`. A selector for `example.com` on `ecommerce_detail` must never apply to `example.com` on `job_detail` or to `other.com` on any surface.

**VIOLATION signatures:**
- A `DomainMemory` lookup uses only `domain` without `surface`
- Self-heal writes a new selector without verifying the target surface
- Generic fallback selectors override a domain-specific rule for the same surface

**Domain cookie memory addendum:**
- Domain cookie memory is acquisition memory, not a raw browser-state dump.
- Challenge-state cookies/localStorage from bot-defense pages must never be persisted or replayed as reusable domain memory.
- A blocked browser run must not promote its storage state into domain memory or run-scoped browser storage.
- Run-scoped and domain-scoped browser storage must stay engine-scoped; `chromium`, `patchright`, and `real_chrome` state must not bleed across engines.
- Browser-to-HTTP handoff may only reuse sanitized engine-scoped session state on the same proxy identity. If proxy affinity cannot be proven, skip handoff and stay browser-first.
- Host browser-first memory is for repeated hard blocks, not one noisy challenge hit.
- Real Chrome navigates directly to the detail URL; there is no origin warmup on any engine. Reusable engine-scoped `real_chrome` domain state, when it exists, is still applied to the context, but it does not gate a warmup step because none exists.
- Real Chrome is not challenge-exempt. If the direct PDP nav lands on a challenge shell, acquisition must still run the bounded challenge wait/activity/retry loop (defined in `app/core/config/acquisition_policy.py`) before declaring the page blocked.
- Learned acquisition contracts live in editable `DomainRunProfile` memory scoped by normalized `(domain, surface)`. They own durable engine choice and handoff eligibility; explicit run settings always override them.
- Future crawls must reuse the successful acquisition/data-extraction path and learned selectors for the domain/surface without fresh experimentation unless the user explicitly changes settings, enables experimentation, resets learned memory, or the contract becomes stale.
- Only contracts with `handoff_eligible=true` may trigger curl handoff. Browser success alone is not enough; rendered extraction (DOM-tier fields used), traversal (link discovery from rendered page), or network-payload dependence (intercepted XHR/fetch bodies) must disable handoff.
- When safe cookies exist for a handoff-eligible saved engine:
  1. Try curl handoff first.
  2. On drift/block/empty output, fallback to the proven browser engine.
  3. On further failure, revert to the normal auto policy.
- **Handoff timeout is capped at `browser_http_handoff_timeout_seconds` (default 3s), not the full HTTP timeout.**
  Handoff is speculative — it tries to skip the browser entirely using stored cookies. If the WAF hangs or slow-rejects, the full `http_timeout_seconds` (10s) would burn before the browser even starts launching. On WAF-heavy sites this caused 20–26s total acquisition delay (handoff timeout + cold browser launch). The dedicated short timeout ensures handoff either succeeds fast or fails fast, keeping browser-first paths responsive.
- Host protection memory is short-TTL block/backoff memory only. It may bias browser-first safety, but it must not become the durable owner of engine preference or handoff eligibility.
- After the configured acquisition-contract stale threshold (defined in `app/core/config/domain_memory.py` as `CONTRACT_STALE_FAILURE_COUNT`) of consecutive non-blocked zero-data failures, the contract is marked stale. Stale contracts must not keep forcing browser engine or curl handoff choices.

**Why this is here:**
Static cleanup advice to persist/reuse more browser state caused a real regression on 2026-04-23. The crawler started replaying PerimeterX challenge state (`_px*`, `pxcts`, PX localStorage) across runs, which poisoned acquisition on multiple sites. Any future "simplification" of cookie memory must preserve this guard and its regression tests.

---

## 10. LLM — Explicit, Degradable, Validated

**Rule:** LLM runs only when both run settings and active config enable it. It may propose grounded recipe roots, paths, joins, and senses after deterministic discovery abstains; it never generates a publishable field value or `Evidence`. Compiler validation and candidate recipe execution remain mandatory. LLM failures must be visible in diagnostics and must not corrupt deterministic extraction state.

**VIOLATION signatures:**
- LLM fires on a run where `llm_enabled=False`
- An LLM output is published as a field value or converted directly into `Evidence`
- An LLM timeout or API error silently produces an empty record instead of a diagnostic log entry
- A model proposal bypasses capture grounding, recipe compilation, or shared validation

---

## 11. Deleted Monitoring and Alerting Surfaces

**Rule:** Monitors, product alerts, in-app monitor notifications, and alert MCP wrappers are deleted product surfaces. Do not reintroduce monitor schedulers, alert routes, notification tables, or watch/alert MCP tools without a new approved plan.

The run-complete callback remains a generic observability extension point. It must not grow monitor-specific diffing, retention, webhook, or notification behavior.

**VIOLATION signatures:**
- Runtime routes such as `/api/monitors`, `/api/alerts`, `/api/v1/alerts`, `/api/watches`, or `/api/v1/watches` are registered.
- ORM tables such as `monitor_jobs`, `monitor_events`, `monitor_snapshots`, `monitor_webhook_deliveries`, or `in_app_notifications` return.
- Celery or FastAPI startup registers monitor scheduler tasks or loops.
- Frontend routes `/monitors` or `/alerts` return.
- Product Intelligence creates monitors instead of handing selected URLs to normal crawl workflows.

---

## 12. Single-Writer URL-Result Artifacts

**Rule:** Exactly one component writes per-URL artifacts: `publish_url_result_artifacts` in `persistence/url_result_artifacts.py`. It writes exactly three files per URL result under `runs/{run_id}/results/{url_result_id}/`:

- `page.html` — the acquired HTML, written **once**.
- `record.json` — the public record(s); shape matches the records API.
- `diagnose.json` — a **self-contained, bounded** root-cause artifact built by `app/observability/diagnose.py`.

`diagnose.json` is the single-file debugging contract: a missing or wrong `price`, `currency`, `availability`, or dropped variant must be fully explainable from `diagnose.json` alone, without opening `page.html` or source. Per field it inlines status (existing `FieldEvidenceState` names), evidence disposition summaries, the winning candidate, rejected candidates with reasons (≤120-char value previews), and any publication-policy action. It reuses existing resolver/publication/disposition vocabulary — no parallel reason names — and references no other file. The deterministic run-level `report.json` (`app/observability/run_report.py`, a run-complete callback) groups root causes and links to each URL's `diagnose.json`.

**VIOLATION signatures:**
- A second writer or a second directory scheme (`runs/{id}/pages/...`) emits URL artifacts.
- Any file other than the three above is written per URL result — `manifest.json`, `summary.json`, `records.json`, `debug.json`, `browser.json`, `trace.json`, `screenshot.*`, `llm_diagnosis.json`, or a duplicate copy of the HTML.
- `page.html` is written twice.
- `diagnose.json` references another file instead of inlining bounded provenance, or invents reason vocabulary instead of reusing `FieldEvidenceState`, evidence disposition, and publication-policy reasons.
- A reader opens the never-written `acquisition.json` / `extraction.json`, or reads the deleted `source_trace` candidate/conflict/resolver/llm provenance keys.
- `run_report.py` (or any run-complete callback) grows monitor-style diffing, retention, webhook, or notification behavior (see Rule 11).

---

## 13. Codebase Shape

**Rule:** Generic crawler paths stay generic. Pipeline boundaries use typed objects. CPU-bound parsing does not block async hot paths. New architecture must improve reusable coverage across multiple domains or surfaces, not just rescue one site, unless the user explicitly asks for a site-specific path.

**VIOLATION signatures:**
- `if "shopify" in url` or `if "greenhouse" in host` appears in `crawl_fetch_runtime.py`, `crawl_engine.py`, `_batch_runtime.py`, or any non-adapter file
- A new shared layer, pipeline branch, or runtime abstraction is added for a bug proven on only one domain, with no evidence it improves broader extractor coverage
- A generic service module starts owning logic that belongs in an adapter or existing platform-specific mapper just to fix one site's markup
- A function returns a tuple of 4+ items instead of a typed object
- A sync `requests.get()` or sync parsing call inside an `async def` function without `run_in_executor`

---

## 14. Plans Must Be Verified, Not Just Written

**Rule:** A plan slice is not done until its focused verify step passes. Plans that are not verified are not done — they are abandoned, and their changes must be treated as untrusted.

Backend verify steps use the smallest relevant pytest target plus ruff for touched Python. Do not run broad `pytest tests -q` unless the user explicitly asks for a full-suite sweep.

Frontend verify steps use direct VitePlus commands: `vp test <test-path>`,
`vp check --fix`, and `vp build`. Do not use npm wrappers or Jest-only flags.

Smoke scripts and fixture/corpus replay gates are not default verification. Do not add or run them unless the user explicitly asks for corpus, replay, or smoke work.

**VIOLATION signatures:**
- A slice is marked DONE without running the focused verify command
- A plan doc exists with status IN PROGRESS but no corresponding test run in the last session
- A second plan is created to fix the same issue as a previous plan that was never verified

**Fix:** If a plan was abandoned, treat its changes as potentially broken. Do not build on top of unverified work.

---

## 15. Google Search Mimicry Footprint

**Rule:** Google native search discovery must mimic human behavior to avoid immediate blocks. 
- **No random mouse jitter:** Never call `emit_browser_behavior_activity` on Google Search pages; erratic, high-speed mouse trajectories are a strong bot signal.
- **Natural input:** Use `page.locator(...).fill()` and `Enter` rather than direct `goto` or slow character-by-character typing. 
- **Natural syntax:** Queries must not use strict boolean dorking (e.g., exact match quotes around every word) unless explicitly required for specific repair.

**VIOLATION signatures:**
- `emit_browser_behavior_activity(page)` is called inside `_google_native_session`.
- `_quoted` wraps every search token in double quotes.
- `page.goto` is used for search execution instead of interacting with the search box.

---

## 16. Product Intelligence — Discovery Identity Ladder

**Rule:** Deterministic product matching uses a fixed identity ladder, strongest signal first.
Owner: `product_intelligence/matching.py` (`score_candidate`) + `product_intelligence/discovery.py`,
thresholds in `config/product_intelligence.py`. No LLM in the deterministic path (see Rule 10).

Ladder (highest confidence first), with the basis recorded in `score_reasons["match_basis"]`:
1. **GTIN/UPC exact** — strongest, auto-accept.
2. **Manufacturer style/model code exact** — GTIN-class. The universal cross-retailer code
   (e.g. Nike `FV5285`) must be **decomposed** from a composite retailer SKU before comparison.
   Belk SKUs glue a numeric retailer prefix onto the manufacturer core (`3900462FV5285` → `FV5285`),
   and external listings expose it bare or with a colorway suffix (`FV5285-002`). Match on the core.
3. **Brand-DTC own listing** (brand-exact on the brand's own domain).
4. **Brand-exact + strong title similarity.**
5. **Brand-exact + distinctive model token** — model-level match. The distinctive model name
   (brand-stripped, generic-descriptor-stripped, e.g. `promina`) is matched **directionally**
   (source distinctive tokens must be contained in the candidate) so a truncated generic candidate
   cannot self-promote.
6. **Brand-exact + medium title similarity.**
7. **Title-only** — refinement, never auto-accept.

**Brand resolution is evidence-based, not allowlist-gated.** The brand registry / `BRAND_DOMAIN_MAP`
only *canonicalizes* aliases. A candidate whose own text states the source brand matches even when the
brand is absent from the registry. Brand is never fabricated without candidate-side evidence (Rule 6).

**Colorway and size are the SAME model, not a variant mismatch.** The variant-spec guard
(`_variant_spec_mismatch`) only fires on genuine spec conflicts (capacity unit, "N-in-1"). Footwear/apparel
color and size differences must stay matchable. Candidate URLs are canonicalized (volatile size/color/
tracking query params stripped) before dedupe so one listing at N sizes consumes one candidate slot.

**The manufacturer style core and distinctive model token are NOT a site-specific path** (Rule 13): they
apply to every branded ecommerce target. Raw internal retailer identifiers (a composite SKU string,
`product_id`, `style_id`) are still never scored as-is — only the decomposed manufacturer core.

**VIOLATION signatures:**
- Scoring a raw composite retailer SKU string as an identity signal instead of the decomposed core.
- Gating `brand_match` on registry membership so an obviously-branded candidate cannot match.
- Treating a colorway/size difference as a wrong-product variant mismatch.
- A single listing at multiple sizes consuming multiple per-product candidate slots (missing canonical dedupe).
- Re-introducing image/pHash matching for recall (audited NO-GO: rejects same-model colorways).
- Adding an LLM call to the deterministic discovery/matching path.

---

## 17. Extraction Memory — Single PostgreSQL Owner

**Supersession (2026-07-02, D4):** This rule replaces the former Knowledge Graph greenfield/no-backfill/reset-separation contract. The generic entity/relationship/claim graph and the parallel selector, review-promotion, field-feedback, and run-JSON stores were intentionally consolidated.

**Rule:** `app/models/extraction_memory.py` is the only durable owner for structural templates, executable recipe candidates and compiled recipes, locale-policy references, immutable run releases, per-URL manifests, operator labels, and extraction observations. PostgreSQL is authoritative.

- **Frozen releases.** Run creation writes one immutable `ExtractionReleaseSnapshot`; workers load it through `CrawlRun.extraction_release_snapshot_id`. Live recipe changes cannot affect an in-flight run.
- **Per-URL identity.** Every persisted URL result receives an `ExtractionManifest` and exposes its ID through `CrawlUrlResult.extraction_manifest_id`.
- **Executable recipes are release-only.** Runtime selection accepts only `release.v2` executable recipes. Selector/source-pin/profile payloads may remain operator-facing historical data, but no extraction runtime translates or executes them.
- **Labels are unified.** Review promotions and field feedback are typed rows in `ExtractionOperatorLabel`, distinguished by `label_kind`.
- **Extraction stays storage-free.** `app/extraction/` may import pure helpers from `app/core/extraction_memory/`; it must not import `app/models/extraction_memory.py` or `app/persistence/extraction_memory.py`.
- **Resolve remains authority.** Saved contracts rank already-admissible evidence only. They cannot create ownership, resurrect rejected evidence, or publish values directly.
- **Models remain evaluated fallback.** ML/LLM output is evidence only, is lazy off the deterministic success path, and cannot enter release evaluation unless qualified by the evaluation schema. Runtime ML requires approved, passing benchmark metadata in the frozen release snapshot plus an exact adapter/artifact identity match. Missing or unapproved metadata disables it. Predictions must resolve to retained compact-source paths and source values before becoming Evidence.
- **Drift cannot override.** Typed active-recipe failures may suspend a recipe under the lifecycle policy; they cannot replace, mutate, or mix with the current result. Repair is a separately compiled candidate and explicit future-release promotion.
- **Grounded publication.** No learned or LLM-produced value reaches publication without a source locator and resolver acceptance.

**VIOLATION signatures:** parallel selector/review/feedback stores; `extraction_runtime_snapshot` in run settings; generic KG entity/edge/claim tables; extraction importing mutable memory; ungrounded learned values; challenger output directly changing records.
