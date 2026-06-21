# Plan: Final Architecture Debt Burn-Down and Crawl Quality Closure

**Created:** 2026-06-21
**Agent:** Codex
**Status:** IN PROGRESS
**Current slice:** Slice 2 — Browser Runtime, Readiness, Interaction, and Traversal Debt
**Touches buckets:** acquisition/browser runtime, extraction and public record contracts, persistence/artifacts/review, crawl orchestration, core config/record quality, intelligence, enrichment, connectors, tests, canonical architecture docs

## Goal

Finish the backend modular-monolith cutover, remove every current architecture debt-ledger exception, and close the generic detail and listing crawl-quality failures found in the latest reports without adding site-specific runtime branches or downstream repair. Done means one traceable owner per runtime decision, deterministic replay produces complete and honest typed records, listing runs return product rows instead of navigation/support links, the architecture ratchets pass with no oversized-module or long-function allowlist, the configured offline suite passes, and the plan remains active as `AWAITING USER 100-SITE GATE` until the user runs the final live gate.

This document supersedes `docs/plans/final-architecture-improvement-plan.md`. It absorbs only that plan's verified results and carries forward its unresolved work. This is the final implementation plan for this debt cycle. Do not create another plan for the same architecture debt; execute these slices to closure. An implementation agent starts from `docs/plans/ACTIVE.md`, this plan, and `AGENTS.md`. The slice guidance below is self-contained; open fallback docs only when code has drifted, an invariant is disputed, or a slice explicitly changes a public contract beyond what is described here.

## Authority and Evidence

Use sources in this order:

1. Current code and tests at branch `debt-burndown-20260620`, audited committed HEAD `553dd794b9ef498c0d9a7e9cfc8034e7f6a6614c`.
2. `AGENTS.md`, `docs/INVARIANTS.md`, `docs/BUSINESS_LOGIC.md`, `docs/CODEBASE_MAP.md`, and `docs/ENGINEERING_STRATEGY.md`.
3. This plan's verified audit and decisions.
4. The attached 93-record detail issue report and the later Arcteryx/Belk/Intimissimi listing reports as current symptom evidence.
5. `docs/feature specs/CrawlerAI_Final_App_Architecture_Simplification_and_Hardening_Plan_REVISED.md` as design rationale only.
6. Local artifact packet: `backend/tests/fixtures/extraction/current_run` plus the user-supplied pasted outputs.

The local artifact packet is accepted as the current handoff evidence for this plan. It is not a complete 93-record replay baseline, and it does not need to be made one before implementation starts. HTML fixtures are intentionally absent from `backend/tests/fixtures/extraction/current_run`; do not add or commit large saved HTML files for this plan. Use the available `*.trace.json`, `*.browser.json`, and `*.extraction.json` files plus focused synthetic regressions for the generic failure class. Never create broad expected-output fixtures from URL reports alone.

## Current Verified Baseline

Measured on 2026-06-21 from committed HEAD `553dd794b9ef498c0d9a7e9cfc8034e7f6a6614c`:

| Scope | Python files | Physical LOC |
|---|---:|---:|
| `backend/app` | 303 | 64,901 |
| `acquisition` | 49 | 16,613 |
| `core` | 82 | 14,777 |
| `crawl` | 38 | 9,596 |
| `extraction` | 24 | 4,743 |
| `intelligence` | 8 | 3,330 |
| `enrichment` | 6 | 2,427 |
| `connectors` | 17 | 2,815 |
| `persistence` | 17 | 2,424 |

Current hard debt:

- 5 production modules exceed 700 physical lines.
- 24 production functions exceed 100 physical lines.
- `backend/tests/unit/test_final_architecture_ownership.py` is the current shrinking debt ledger.
- `backend/tests/unit/test_extraction_architecture.py` already enforces extraction at no more than 24 files, 5,500 LOC, 400 lines per file, and 60 lines per function.
- `backend/pytest.ini` defaults to `-m "unit or component"`; regression verification commands in this plan explicitly override the marker expression.
- Latest focused verification after the parser-ownership slice: Ruff passed and 158 targeted tests passed.
- Last known configured full offline suite before this handoff: 827 passed, 151 deselected. Treat this as context only; Slice 12 must rerun the complete offline suite.

### Committed work already present; preserve and do not redo

- Canonical detail URL fallback and required `CommerceDetailRecord.url`.
- Punctuation-tolerant error-shell title handling.
- Initial persistence no longer writes the four legacy provenance columns; immutable provenance is handed to `record-provenance.json`.
- Browser readiness uses the canonical `HtmlDocument`/Lexbor tree; acquisition has no BeautifulSoup construction.
- Browser readiness, detail extractability, and final extraction reuse a matching parsed document by content hash.
- `acquisition/runtime.py` is below 700 lines and is no longer oversized debt.
- Pass-through modules already deleted: acquisition pacing/Playwright compatibility, pipeline extraction wrapper, run-config snapshot wrapper, discovery type wrapper, and storage factory.
- `backend/tests/regression/test_batch_runtime.py` had no diff at audit time.
- Existing unrelated documentation state must be preserved; do not reset user-owned files to make this plan easier.

## Audited Architecture Debt Ledger

### Oversized modules

| Current owner | Current LOC | Required target | Planned correction |
|---|---:|---:|---|
| `acquisition/browser_detail.py` | 898 | <=650 | Keep detail-expansion orchestration here; move the distinct accessibility-tree implementation to the named `browser_accessibility.py` owner; delete `*_impl` pass-through wrappers. |
| `acquisition/browser_runtime.py` | 1,025 | <=650 | Keep browser fetch orchestration and stable exports; move launch/warmup/popup mechanics to existing `browser_fetch_support.py`; split fetch into bounded phases. |
| `acquisition/fetch/fetch_context.py` | 987 | <=650 | Make `fetch_page()` a thin mode/final-result facade; move attempt mechanics into existing planner/executor, `planned_http.py`, and `browser_attempt_runner.py`; delete aliases and duplicate retry loops. |
| `crawl/batch_runtime.py` | 820 | <=650 | Keep run lifecycle and URL-session ownership; extract no new coordinator layer; consolidate URL failure/session/progress helpers with their existing owners. |
| `enrichment/shopify_catalog.py` | 929 | <=650 | Separate repository I/O/index lookup into the named `shopify_repository.py` owner; retain scoring/matching in `shopify_catalog.py`; require net package LOC reduction. |

The two named new modules are permitted because they establish distinct owners, not because they reduce line counts. No other production module may be created without amending this plan and proving unique ownership plus net deletion.

### Long-function debt

Every entry below must be removed from `LONG_FUNCTION_DEBT`; do not replace it with a new >100-line function.

| Subsystem | Functions | Required decomposition |
|---|---|---|
| Detail interaction | `expand_all_interactive_elements_impl`, `expand_interactive_elements_via_accessibility_impl` | Separate candidate discovery, safety admission, action execution, settle, and diagnostics. Remove wrapper/implementation duplication. |
| Browser page flow | `settle_browser_page_impl` | Named readiness, network-idle, platform-wait, and expansion phases operating on one snapshot state. |
| Browser artifacts | `_capture_listing_visual_elements` | Module-owned page script plus typed response normalization; no hidden extraction decisions. |
| Challenge recovery | `recover_browser_challenge`, `_emit_challenge_activity` | Poll/classify, bounded activity, retry-navigation, and event projection phases. |
| Browser finalization | `BrowserAcquisitionResultBuilder.build` | Classification, event emission, artifact capture, and result assembly methods. |
| Browser runtime | `browser_fetch`, `_maybe_warm_origin_before_navigation` | Launch, navigate/settle/serialize, finalize, and warmup lifecycle phases. |
| Block classification | `classify_blocked_page` | Evidence collection and policy decision; preserve usable-content-over-provider-noise invariant. |
| Listing traversal | `_run_scroll_traversal`, `_run_load_more_traversal`, `_run_paginate_traversal` | Mode-specific action loops with shared progress/stop updates only where behavior is identical. |
| Traversal recovery | `click_with_retry`, `dismiss_overlays_if_needed` | Attempt, settle, and diagnostic phases. |
| LLM connector | `run_prompt_task` | Provider invocation, response validation, cost recording, and failure projection. |
| Public extraction connector | `extract_public_product` | Request admission, normal crawl execution, and response mapping; no second extractor. |
| Runtime config | `_apply_profile_defaults` | Domain-specific default application inside existing config ownership. |
| Confidence | `score_record_confidence` | Field scoring, penalty calculation, and aggregate result. |
| Batch runtime | `_process_urls_in_parallel`, `_process_run_with_span` | Task scheduling/result collection and run setup/finalization. |
| Run progress | `_merge_run_acquisition_metrics` | Timing, method/outcome, and browser metrics reducers. |
| Review | `build_domain_recipe_payload` | Load, coverage, selector, and response assembly using canonical artifacts. |
| Intelligence | `score_candidate` | Typed deterministic feature calculation and final policy decision. |

## Audited Crawl-Quality Findings

### Already guarded; preserve

- A punctuated `Oops, Something Went Wrong.` shell is blocked even when fake product offers exist.
- A missing extracted detail URL falls back to the canonical capture URL.
- Parent availability is aggregated from a complete variant availability matrix and records lineage.
- Missing requested/default contract fields emit `MISSING_CONTRACT_FIELD` findings.
- An uncorroborated cent/magnitude value is not silently divided or repaired.

These passing unit cases do not prove the reported sites are fixed. They are invariant guards only.

### Open generic defects and decided owners

| Failure class | Audited cause | Owner and required correction |
|---|---|---|
| Filename/ID/nav/SEO title pollution | URL collector emits raw leaf including extension/IDs; evidence normalization has no title-quality flags; scalar resolution ranks source/directness but not semantic title admissibility. | `extraction/collectors/url.py`, `pipeline.normalize_evidence`, `resolution.py`, with title tokens/patterns in existing `core/config/extraction_rules/_detail.py`. Reject filename/ID/nav candidates; clean SEO suffix only when a higher-confidence product identity remains. |
| Missing metadata despite captured evidence | JS/network mapping is shallow, inline, and admits arbitrary dictionaries with generic keys; some canonical source-key aliases are absent; missing-field validation sees evidence presence, not necessarily resolved public output. | `core/config/field_mappings.py`, extraction collectors, entity linking, validation. Map all objects deterministically, require product/offer context, and validate selected public values after resolution. |
| Utility/placeholder primary image | Asset decisions are made independently per URL, then materialization writes the same `image_url` field repeatedly, making iteration order a hidden product-level selector. Reject tokens are incomplete. | `entities.py`, `resolution.py`, `materialization.py`, existing `AssetDecision`, and `_images.py`. Perform one product-level asset selection with deterministic role/rank and lineage. |
| No additional images field | `additional_images` is an existing canonical alias, but `CommerceDetailRecord` exposes only `image_url`; collected gallery assets are discarded as public output. | Additive typed contract in `extraction/contracts.py`; materialize ordered deduped gallery URLs; propagate through schemas/API/export/review. |
| Raw spaces or unsafe image URLs | Asset normalization only joins URLs; it does not canonicalize path encoding before identity/dedupe. | Canonical URL normalization before asset entity identity. Preserve query semantics and reject non-HTTP(S)/data/utility assets. |
| Zero/year/100x price errors | Recursive JS/network mapping can treat generic `price` keys as product offers; zero remains admissible; price/currency coupling is enforced only after entity grouping; arbitrary magnitude repair is intentionally absent. | Collector admission and offer grouping in extraction. Reject non-positive prices, require contextual product/offer evidence, preserve price/currency atomicity, and emit contradictions instead of guessing scale. |
| ID-only or URL-only public variants | Variant entity creation accepts stable identity with little commercial/option evidence; materialization emits any nonempty row; parent offer facts are not inherited to variants. | `collectors/js_state.py`, `jsonld.py`, `entities.py`, `validation.py`, `materialization.py`. Require identity plus option/offer evidence for public rows; retain rejected evidence in findings; inherit only explicitly product-wide nonconflicting offer facts with lineage. |
| Missing variants | Deterministic collectors can only publish captured evidence. A reported regional SKU structure is not permission to synthesize variants. | Exhaust structured/network/DOM evidence and request one rendered capability when explicit variant cues exist. If still absent, emit an explicit finding and partial/review verdict. |
| Listing discovery returns navigation/support links | Category discovery scores category-looking and nav anchors, and rendered/static fallback can keep broad same-origin links without proving listing-card/product-link density. Belk examples include customer-service, policies, stores, registry, wish-list, and broad department links mixed with one requested category. Arcteryx examples include nav taxonomy, app, athlete, and unrelated category links when a specific footwear-run listing was requested. | `crawl/sitemap_resolver.py`, `crawl/site_link_discovery.py`, `crawl/sitemap_nav.py`, and `core/config/sitemap.py`. Require product-listing evidence for selected ecommerce listing URLs, demote site-chrome/nav-only buckets, keep requested branch affinity when a seed is already category-specific, and expose rejected-link diagnostics instead of returning utility URLs. |
| Listing records use swatch/control text as title | `extraction/listing.py` picks the first configured title selector inside a broad card (`article`, `li`, generic product class) and accepts `title`/text from color controls. Intimissimi examples show valid product URLs/prices/images paired with `Cor selecionada` from a selected-color control. | `extraction/listing.py`, `core/config/extraction_recipes.py`, `core/config/extraction_rules/_common.py`, and existing text/url identity helpers. Select title evidence from product-link/name scope, reject CTA/swatch/control/aria state labels, require title-to-product-url or image/price/card context agreement, and keep the row partial/rejected when no product title exists. |
| Legacy provenance ownership | Initial writes stopped, but active writers remain in `persistence/publish/metadata.py`, `crawl/crud.py`, and review promotion; schemas and observability still dual-read ORM columns. | Canonical artifacts plus derived read models. Review acceptance is represented by existing review/domain-feedback ownership and logs, not mutable extraction provenance. |

### Listing symptom reports to cover

- Arcteryx requested footwear-run/category context produced broad navigation taxonomy and utility links: `Get the App`, `Athletes & Ambassadors`, `ACCESSORIES`, `PACKS`, `WOMEN`, unrelated category branches, and many `/wid-*` category URLs.
- Belk mens-pants/category context produced customer-service, legal/compliance, vendor resources, stores, registry/wish-list, and unrelated promo/category URLs alongside actual category URLs.
- Intimissimi listing rows had plausible product URLs, images, and prices, but every title was `Cor selecionada`, a color-selection state label rather than a product name.

These are listing failures, not detail extraction failures. Fix discovery/card admission upstream. Do not patch exports, product intelligence, or persistence to hide them.

### Explicit non-fixes

- Do not enforce global SKU/MPN uniqueness. Numeric prefixes can legitimately collide across retailers and product domains. Act only if one record's lineage points to another product's captured evidence.
- Do not infer brand from hostname, URL, retailer, or category when no product-side evidence exists. Missing brand plus a finding is better than fabrication.
- Do not force a price for quote-only, region-gated, unavailable, or blocked pages.
- Do not turn a blocked shell into success. Correct outcome is blocked/error plus preserved diagnostics.
- Do not add browser clicking until structured, network, and static DOM evidence paths are exhausted and explicit stateful controls remain.
- Do not add a broad 93-record expected-output fixture. Use minimal generic regressions and available JSON artifacts.
- Do not add Arcteryx, Belk, or Intimissimi hostname branches. The fix must be generic category/listing URL admission and listing-card evidence ranking.

## Target Runtime Ownership

```text
crawl/batch_runtime.process_run                 run lifecycle and URL scheduling
  -> crawl/pipeline/extraction_loop.process_single_url
       -> acquisition/acquirer.acquire          page acquisition facade
          -> acquisition/planner                finite attempt plan for every mode
          -> acquisition/executor               one typed AttemptResult per attempt
          -> acquisition/fetch/*                transport mechanics only
       -> extraction/engine.extract             evidence -> entities -> decisions -> typed records
       -> crawl/pipeline/persistence             database writes only
       -> persistence/ArtifactRepository         canonical immutable artifacts/manifests
```

Do not introduce speculative `RunCoordinator` or `UrlProcessor` classes. The existing functions are the owners; make their typed inputs/outputs clear and small.

## Global Acceptance Criteria

- [ ] Every HTTP, Patchright, Real Chrome, handoff, warmup, and browser retry is represented by one `AttemptSpec` and one terminal `AttemptResult` in the canonical `AcquisitionResult`.
- [ ] `fetch_page()` and `browser_fetch()` orchestrate existing owners; neither reimplements planner policy, extraction, or persistence.
- [ ] Explicit `surface`, traversal, proxy, diagnostics, and `llm_enabled` controls remain unchanged.
- [ ] No BeautifulSoup construction exists under `app/acquisition`; no duplicate full-document parse is introduced.
- [ ] Detail URL, shell, title, asset, offer, availability, and variant decisions have deterministic lineage or visible findings.
- [ ] Ecommerce listing discovery returns only listing/category URLs with product-listing evidence or strong requested-branch affinity; customer-service, policy, store, registry, app, athlete, and other site-chrome URLs are rejected with diagnostics.
- [ ] Ecommerce listing records require a product URL plus an admissible product title from product-link/name scope. Swatch, selected-color, CTA, aria-state, nav, and utility labels cannot become row titles.
- [ ] `CommerceDetailRecord.additional_images` is an additive ordered tuple/list contract; `image_url` remains backward compatible as the primary image.
- [ ] No ID-only variant row is public. Missing non-inferable SKU/offer fields produce findings, not fabricated values.
- [ ] Persistence, publish, export, review, and observability do not reinterpret extraction facts or URL verdicts.
- [ ] No active runtime write remains to `CrawlRecord.raw_data`, `discovered_data`, `source_trace`, or `raw_html_path`.
- [ ] Legacy readers are removed after canonical artifact coverage is proven; any temporary dual-read owner is explicit and shrinking.
- [ ] `app.services` and deleted compatibility modules remain absent.
- [ ] No hostname/site-name branch is added to generic acquisition, extraction, pipeline, publish, or export code.
- [ ] No non-data production module exceeds 700 lines; the five named owners are at or below 650.
- [ ] No production function exceeds 100 lines; `LONG_FUNCTION_DEBT` is empty.
- [ ] No architecture allowlist is widened.
- [ ] Production LOC budgets and extraction shape gates pass.
- [ ] Ruff and the complete offline unit/component/regression suite pass.
- [ ] No smoke, browser probe, or live acceptance is run by implementation agents.
- [ ] After offline closure, this plan and `ACTIVE.md` say `AWAITING USER 100-SITE GATE`, not `DONE`.

## Quantitative Gates

Replace the arbitrary “25% file deletion” and old 58,109-LOC target with budgets tied to audited owners and retained capabilities.

| Scope | Current LOC | Final maximum |
|---|---:|---:|
| `backend/app` | 64,901 | 62,600 |
| `acquisition` | 16,613 | 15,400 |
| `crawl` | 9,596 | 9,250 |
| `core` | 14,777 | 14,500 |
| `enrichment` | 2,427 | 2,150 |
| `connectors` | 2,815 | 2,700 |
| `intelligence` | 3,330 | 3,250 |
| `extraction` | 4,743 | 5,500 existing hard cap |

Rules:

- Feature slices may temporarily add extraction contract/test code, but each architecture slice must delete more production LOC than it adds.
- Named file moves do not count as debt reduction. Package and total LOC must fall.
- File count has no arbitrary target. Delete wrappers/dead owners; keep cohesive capability owners.
- Add these package budgets to `test_final_architecture_ownership.py` before final closure. Do not add a permanently failing target test at the start of a slice.

## Do Not Touch

- Do not reset, checkout, stash, or discard unrelated working-tree changes.
- Do not restore or further alter the unrelated deleted docs except when the user explicitly requests it.
- Do not change frontend behavior in this plan. The additive API field may be rendered by existing dynamic record views; frontend work requires evidence of a broken contract.
- Do not run live URLs, smoke scripts, `run_*smoke.py`, browser probes, or the 100-site gate.
- Do not introduce LangGraph, a second product scraper, a second verdict owner, or LLM-generated extraction facts.
- Do not move constants/tunables into service code. Extend existing `app/core/config/*` owners.
- Do not create generic `manager`, `utils2`, `helpers2`, compatibility, or line-count-only modules.
- Do not edit `backend/tests/regression/test_batch_runtime.py` outside Slice 8; preserve its existing behavior and add assertions only when the crawl contract changes.

## Slice Execution Protocol

For every slice:

1. Read only the listed owner files, nearby tests, and named canonical docs.
2. Use the listed locator commands only to confirm symbols have not moved before editing.
3. Add the smallest regression that fails for the audited generic cause.
4. Implement upstream; delete replaced logic and obsolete tests in the same slice.
5. Run the slice verify command once after implementation; rerun only failures.
6. Inspect the slice diff and current LOC/function ledger.
7. Mark the slice `DONE` only when every slice acceptance item and verify step passes.
8. Stop after one slice and hand off exact results in this document's Notes.

## Standalone Implementation Guidance

This section exists to reduce repeated broad audits. Treat it as the implementation map unless a slice's local code has changed since this plan was written.

### Environment and verification setup

Use these commands exactly from the repository root unless a slice says otherwise:

```powershell
# If imports or tools are missing, repair the local backend environment first.
.\backend\bootstrap-dev.ps1

# Type check. Important: pass the backend mypy config when running from repo root.
.\backend\.venv\Scripts\python.exe -m mypy --config-file backend\pyproject.toml `
  backend\app `
  backend\harness_support.py `
  backend\run_acquire_smoke.py `
  backend\run_browser_surface_probe.py `
  backend\run_extraction_smoke.py `
  backend\run_test_sites_acceptance.py

# Focused lint for changed backend Python files.
.\backend\.venv\Scripts\python.exe -m ruff check <changed-python-files>
```

Why this matters: running mypy from the repo root without `--config-file backend\pyproject.toml` can ignore backend overrides and report missing third-party stubs such as `defusedxml` or `celery.signals`. That is an environment invocation error, not architecture debt. Do not work around it by adding ignores in production files.

For pytest, run from `C:\Projects\CrawlerAI\backend` when using the slice commands:

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest <slice-tests> -q
```

Do not run smoke/live commands from this plan. The only live gate is Slice 13 and it is user-owned.

### Global locator commands before edits

Run only the locator group for the slice being implemented:

```powershell
# Slice 1 acquisition attempt ownership
rg -n "AcquisitionPlan|AttemptSpec|AttemptResult|AcquisitionResult|fetch_page|run_planned_http_only|run_browser_attempts|browser_attempt|handoff|engine_attempt|proxy" backend\app\acquisition backend\app\connectors\public_api backend\tests -S

# Slice 2 browser/runtime debt
rg -n "browser_fetch|settle_browser_page|expand_all_interactive|accessibility|capture_listing_visual|recover_browser_challenge|classify_blocked_page|_run_scroll_traversal|_run_load_more_traversal|_run_paginate_traversal|click_with_retry|dismiss_overlays" backend\app\acquisition backend\tests -S

# Slice 3 listing discovery and listing rows
rg -n "resolve_category_urls|discover_rendered_category_links|HomepageCandidate|SiteLinkCandidate|category_only|listing_url_is_structural|collect_ecommerce_listing|ECOMMERCE_LISTING|LISTING_TITLE_CTA|selected|swatch|aria-label" backend\app\crawl backend\app\extraction backend\app\core backend\tests -S

# Slice 4 detail identity/title/metadata
rg -n "product.title|product.brand|product.description|detail_title_from_url|title_looks|SOURCE_PRIORITY|normalize_evidence|JsonLdCollector|OpenGraphCollector|MicrodataCollector|JsStateCollector|NetworkCollector|UrlCollector|MISSING_CONTRACT_FIELD" backend\app\extraction backend\app\core backend\tests -S

# Slice 5 assets/additional_images
rg -n "AssetDecision|asset.image_url|image_url|additional_images|PRIMARY_IMAGE|placeholder|logo|swatch|sprite|gallery|media|srcset" backend\app backend\tests -S

# Slice 6 offers/variants
rg -n "variant|variants|selected_variant|offer.price|offer.currency|availability|price|currency|early return|DOM cue|backfill|INCOMPLETE_VARIANT|parent" backend\app\extraction backend\app\core backend\tests -S

# Slice 7 provenance
rg -n "raw_data|discovered_data|source_trace|raw_html_path|record-provenance|RecordArtifacts|field_discovery|requested_field_coverage|review_bucket|ReviewPromotion|DomainFieldFeedback" backend\app backend\tests -S

# Slice 8 crawl runtime
rg -n "process_run|process_single_url|_process_urls_in_parallel|_process_run_with_span|URL session|heartbeat|pause|kill|record limit|PendingRollback|_merge_run_acquisition_metrics" backend\app\crawl backend\tests -S

# Slice 9 config/confidence
rg -n "_apply_profile_defaults|runtime_settings|score_record_confidence|confidence|profile defaults|field_mappings|public_record_policy" backend\app\core backend\tests -S

# Slice 10 review/intelligence/enrichment
rg -n "build_domain_recipe_payload|score_candidate|shopify_catalog|shopify_categories|shopify_attributes|taxonomy|exact conflict|brand registry" backend\app\crawl backend\app\intelligence backend\app\enrichment backend\tests -S

# Slice 11 LLM
rg -n "run_prompt_task|llm_enabled|LLMConfig|cost|provider|circuit|prompt task|missing fields|adjudication" backend\app\connectors backend\app\llm backend\app\core backend\tests -S
```

### Embedded owner map

| Concern | Current owner | What it owns | What it must not own |
|---|---|---|---|
| Batch lifecycle | `crawl/batch_runtime.py` | run setup, URL scheduling, terminal run status, pause/kill/heartbeat | per-URL extraction decisions, DB writes for another URL, browser policy |
| Per-URL workflow | `crawl/pipeline/extraction_loop.py` | acquire -> extract -> normalize -> persist sequencing for one URL | transport loops, field repair, export shaping |
| Acquisition facade | `acquisition/acquirer.py` | translating pipeline request to fetch runtime and canonical acquisition result | crawl DB writes, extraction, review |
| Attempt planning | `acquisition/planner.py`, `acquisition/fetch/browser_policy.py` | explicit attempt list, engine/proxy/handoff/browser retry admission | browser mechanics, result materialization, hidden retries |
| Attempt execution | `acquisition/executor.py`, `fetch/planned_http.py`, `fetch/browser_attempt_runner.py` | one `AttemptSpec` -> one `AttemptResult` | deciding the next attempt after execution |
| Browser mechanics | `browser_runtime.py`, `browser_fetch_support.py`, `browser_page_flow.py`, `browser_result_builder.py` | launch/navigate/settle/serialize/finalize observations | field extraction or record decisions |
| Browser interaction | `browser_detail.py`, `browser_accessibility.py` after Slice 2, `traversal.py`, `traversal_recovery.py` | bounded observation-producing clicks/scroll/load-more/pagination | direct field assignment or site-specific rescue |
| Listing discovery | `crawl/sitemap_resolver.py`, `crawl/site_link_discovery.py`, `crawl/sitemap_nav.py` | choosing category/listing URLs from sitemap/homepage/rendered links | persisted record rows, detail extraction, product intelligence |
| Listing extraction | `extraction/listing.py` | listing-card evidence -> decisions -> `CommerceListingRecord` rows | category discovery, detail fallback, export cleanup |
| Detail extraction | `extraction/engine.py`, collectors, `entities.py`, `resolution.py`, `validation.py`, `materialization.py` | evidence collection, entity linking, deterministic resolution, findings, typed records | acquisition retries, persistence repair, LLM-generated values |
| Public record boundary | extraction contracts, schemas, APIs, export/review serializers | typed public fields and lineage transport | post-hoc semantic repair |
| Provenance/artifacts | `persistence/record_artifacts.py`, `persistence/url_result_artifacts.py`, `crawl/pipeline/persistence.py` | immutable artifacts, manifests, DB writes | extraction fact mutation |
| Review/domain feedback | `crawl/review/*`, `models/review.py`, `DomainFieldFeedback` | review payloads and user-approved feedback | mutating immutable extraction provenance |
| Config | `core/config/*` | thresholds, tokens, selectors, field aliases, runtime tunables | service-local constants |
| LLM | `connectors/llm/*`, `llm/*` | explicit, degradable backfill/adjudication when enabled | primary extraction, deterministic overwrite |

### Generic failure templates to convert into tests

Use these patterns for small synthetic regressions. Do not snapshot whole external pages unless a replay artifact already exists.

#### Listing discovery utility spillover

```html
<nav>
  <a href="/customer-service/">Contact Us</a>
  <a href="/stores/">Find a Store</a>
  <a href="/c/mens/footwear-run/wid-kjyr4dq9">Run</a>
</nav>
<main>
  <section class="product-grid">
    <a class="product-card" href="/products/trail-shoe-1"><span>Trail Shoe 1</span><span>$120</span></a>
    <a class="product-card" href="/products/trail-shoe-2"><span>Trail Shoe 2</span><span>$130</span></a>
    <a class="product-card" href="/products/trail-shoe-3"><span>Trail Shoe 3</span><span>$140</span></a>
  </section>
</main>
```

Expected: product/category URL kept only when listing evidence is present; support/store URLs rejected with diagnostics.

#### Listing title swatch/control pollution

```html
<li class="product-card">
  <a class="product-link" href="/blusa-verde/p"><img src="/p.jpg"></a>
  <button aria-label="Cor selecionada" title="Cor selecionada"></button>
  <a class="product-name" href="/blusa-verde/p">Blusa de Manga Comprida em Lã Merino</a>
  <span class="price">399</span>
</li>
```

Expected: title is product name, never `Cor selecionada`. If product-name evidence is absent, reject/partial the row rather than publishing a control label.

#### Detail title pollution

Use one record with URL leaf `foo-product-123.html`, one bad candidate `123.html` or `Measurements`, and one valid structured/H1 product name. Expected: valid product title wins; if no valid title exists, missing-title finding is visible.

#### Utility image pollution

Use assets for product photo, logo, loader GIF, payment badge, swatch, quote/testimonial, and placeholder. Expected: one deterministic primary product image; additional product images exclude primary and utilities.

#### Variant/offer integrity

Use structured/JS state with one ID-only variant, one complete variant, one parent-wide offer, and one conflicting child offer. Expected: ID-only evidence becomes finding; complete variant publishes; inherited offer facts are explicit and lineage-backed only when nonconflicting.

### Slice-specific implementation notes

#### Slice 1 notes: canonical acquisition attempts

- Current pain: `fetch_context.py` still acts as facade, policy owner, retry executor, result assembler, and diagnostic projector. It should become a thin owner that calls planner/executor and selects the final acquisition result.
- Existing contracts to preserve: `AttemptSpec`, `AttemptResult`, `AcquisitionPlan`, `AcquisitionResult`. Extend them only if every attempt needs the field.
- Do not create a second browser policy object. Use current browser-policy functions and make them return explicit specs/results.
- Main invariant: no retry without a visible planned attempt and no terminal page result without a terminal `AttemptResult`.
- Delete target: aliases, duplicated retry loops, and local dict diagnostics that duplicate typed attempt fields.

#### Slice 2 notes: browser debt

- Keep `browser_runtime.browser_fetch` as public orchestration entry; split private phases.
- `browser_page_flow` should own navigation/readiness/serialization phases. `browser_readiness` owns classification helpers. `browser_result_builder` owns result assembly.
- `browser_detail.py` keeps high-level detail expansion. Move accessibility-tree scanning/action admission into `browser_accessibility.py` because it is a distinct browser observation owner.
- `browser_page_helpers._capture_listing_visual_elements` is observation only. It may emit typed visual/card facts for diagnostics; it must not choose product fields.
- Traversal loops must remain mode-specific. Shared helpers are allowed only for identical stop/progress accounting.

#### Slice 3 notes: listing discovery and rows

- Discovery and extraction are separate. Discovery chooses URLs to crawl; `extraction/listing.py` chooses rows on a listing page.
- Static sitemap/homepage fallback can return category URLs when category signals are strong. Rendered discovery must validate thin/broad candidates with product-listing evidence before returning them.
- Use generic utility tokens in `core/config/sitemap.py` or existing URL identity helpers. Do not hardcode example domains.
- If a seed is already a deep category/listing URL, preserve branch affinity: sibling/child paths may be valid, unrelated top-level nav branches should need stronger listing evidence.
- In `extraction/listing.py`, pick product URL before title. Prefer title from the same anchor or a nearby product-name node; treat swatches/buttons/aria-selected labels as title noise.
- Existing broad selectors (`article`, `li`) are allowed only if row admission proves product URL plus product title. They must not turn nav list items into product rows.
- Tests should assert both accepted rows and rejected diagnostics/reasons where current APIs expose them.

#### Slice 4 notes: detail identity/title/metadata

- Bad titles come from URL fallback, DOM tabs/headings, filenames, IDs, nav text, and SEO boilerplate. Fix candidate admission/ranking before materialization.
- URL-derived titles are low-confidence review evidence only. They should not win over weak but semantically valid product evidence unless configured rules support it.
- JS/network collectors need product/offer context before generic keys become product facts. A random dict with `price` or `title` is not enough.
- Move source-key aliases to `core/config/field_mappings.py`; collectors should not own field vocabulary.
- Validation must inspect selected public output after resolution, not only raw evidence presence.

#### Slice 5 notes: asset and `additional_images`

- `AssetDecision` currently exists but product-level primary selection is not yet enforced. Either use it or replace it with one generic decision shape; do not leave dead parallel contracts.
- Materialization must write `image_url` exactly once from the selected primary decision.
- `additional_images` is additive and backward-compatible. Absence/empty list is valid when no secondary product image exists.
- Normalize asset URL identity before dedupe; preserve meaningful query params but encode unsafe spaces.
- Reject utility assets by role/context, not extension alone. Legitimate SVG product art must remain possible.

#### Slice 6 notes: offers and variants

- Do not synthesize variants. Publish only captured, stable, sellable/product-relevant variant facts.
- ID-only/URL-only variants become findings, not rows.
- Price/currency/availability are atomic offer facts. Keep contradictions visible.
- Parent-wide offer inheritance must be explicit and nonconflicting; no silent deletion of duplicate-looking child fields after resolution.
- Browser capability request for variants is allowed only when explicit variant DOM cues exist and captured deterministic evidence is incomplete.

#### Slice 7 notes: provenance

- Four legacy columns are `raw_data`, `discovered_data`, `source_trace`, and `raw_html_path`.
- Current direction: immutable artifacts and manifests are canonical; derived read models can be built from them.
- Stop writes first, then remove readers/exposure after compatibility coverage exists.
- Review acceptance belongs to review/domain-feedback models/logs. It must not mutate immutable extraction provenance.
- Migration/backfill is allowed only when tested; no silent column removal if old rows still need read fallback.

#### Slice 8 notes: crawl runtime

- Keep one DB session/transaction per URL. Never let a failed URL poison the run orchestration session.
- Local mode concurrency is exactly 1 when Celery dispatch is disabled.
- Split scheduling/result collection and setup/finalization without inventing `RunCoordinator` or `UrlProcessor`.
- Preserve record limits, restart/idempotency, pause/cancel, heartbeat, sitemap/category discovery, and URL-local failures.

#### Slice 9 notes: config and confidence

- `_apply_profile_defaults` is long because it applies multiple domains. Split by existing settings domains; do not create parallel settings sources.
- All runtime strings/tokens/thresholds stay in `core/config/*`.
- Confidence is diagnostic. It cannot mutate records, verdicts, or field values.

#### Slice 10 notes: review/intelligence/enrichment

- Review payloads must read canonical artifacts/provenance and domain feedback; no mutable extraction provenance.
- `score_candidate` must preserve the identity ladder from `docs/INVARIANTS.md` Rule 16.
- Shopify repository I/O/indexing can move to `shopify_repository.py`; taxonomy scoring stays in `shopify_catalog.py`.
- Enrichment cannot clean extraction pollution. If enrichment sees bad title/category/brand, fix extraction upstream.

#### Slice 11 notes: LLM

- `run_prompt_task` should split provider call, response validation, cost log, and visible failure projection.
- LLM remains dual-gated by run setting and active config.
- LLM can adjudicate/fill allowed gaps only; deterministic evidence wins unless a separate conflict-review path exists.

#### Slice 12 notes: final ratchet

- Remove all debt allowlist entries. Do not replace them with new names.
- Add package LOC budgets to `test_final_architecture_ownership.py`.
- Run Ruff once, then the complete offline suite with regression marker included.
- Update docs only for implemented ownership/contract changes. Do not rewrite historical rationale.

## Slices

### Slice 0: Audit, Standalone Plan, and Activation

**Status:** DONE
**Files:** this plan, `docs/plans/ACTIVE.md`, `docs/plans/final-architecture-improvement-plan.md`
**What:** Recomputed code/LOC/function debt, audited current extraction/acquisition/persistence owners, classified the attached failures, retired superseded targets, and made this the sole active plan.
**Acceptance:** Baselines and decisions above match the committed baseline; prior plan is marked superseded; no production code changed.
**Verify:** `git diff --check -- docs/plans/ACTIVE.md docs/plans/final-architecture-debt-burndown-plan.md docs/plans/final-architecture-improvement-plan.md`

### Slice 1: Canonical Acquisition Attempt Ownership

**Status:** DONE — VERIFIED 2026-06-21
**Owners:** `acquisition/contracts.py`, `planner.py`, `executor.py`, `fetch/fetch_context.py`, `fetch/planned_http.py`, `fetch/browser_attempt_runner.py`, `fetch/browser_attempt.py`, `fetch/browser_policy.py`, `fetch/types.py`, `acquirer.py`, `connectors/public_api/extraction_service.py`
**Fallback docs:** `docs/INVARIANTS.md` Rules 5, 6, 9, 13; acquisition section of `docs/CODEBASE_MAP.md`.
**Known audited scope:** `AcquisitionPlan`, `AttemptSpec`, `AttemptResult`, `AcquisitionResult`, `run_planned_http_only`, `_run_browser_attempts`, `run_browser_attempts`, `_run_http_fetch_chain`, handoff helpers, and all `fetch_page` callers.

**Implement:**

- Extend the existing planner to describe all auto/browser/handoff attempts, not only HTTP-only mode.
- Execute every transport through `AttemptExecutor`; browser runner performs mechanics for one planned attempt and returns its page result plus terminal attempt result.
- Make `fetch_page()` select the canonical result and attach one complete plan/result diagnostic payload.
- Delete duplicate engine/proxy loops, alias exports, and policy decisions from `fetch_context.py` after their callers move.
- Keep public extraction on normal acquisition/extraction; split its request admission and response mapping without creating another scraper.

**Slice acceptance:**

- `fetch_context.py` <=650 lines; `extract_public_product` <=100 lines.
- Every started attempt terminates exactly once as success/blocked/empty/error/skipped.
- Global deadline, retry floor, proxy identity, engine-specific storage, user controls, and host memory behavior remain covered.
- No requested-field-only browser trigger returns.
- No acquisition allowlist entry is added.

**Handoff:** Slice 1 complete.

- Files changed: `acquisition/fetch/fetch_context.py`, `acquisition/fetch/planned_http.py`, `acquisition/fetch/browser_attempt_runner.py`, `connectors/public_api/extraction_service.py`, `tests/component/test_crawl_fetch_runtime.py`, `tests/unit/test_final_architecture_ownership.py`, `docs/plans/ACTIVE.md`, and this plan.
- Deletions: no files deleted; duplicate HTTP/proxy loops and handoff/result-policy bodies were removed from `fetch_context.py`.
- LOC/function delta: `fetch_context.py` 987 -> 632 lines; `extract_public_product` 111 -> 40 lines; `planned_http.py` and `browser_attempt_runner.py` now own the moved attempt mechanics and remain below the oversized-module threshold.
- Verification: `189 passed` for the exact Slice 1 command on 2026-06-21.
- Debt removed: `acquisition/fetch/fetch_context.py` removed from `OVERSIZED_MODULE_DEBT`; `connectors/public_api/extraction_service.py::extract_public_product` removed from `LONG_FUNCTION_DEBT`.
- Remaining debt: Slice 2 browser runtime/detail/readiness/traversal long-function and oversized-module entries remain.
- Next slice: Slice 2 — Browser Runtime, Readiness, Interaction, and Traversal Debt.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_acquisition_planner_executor.py `
  tests\component\test_acquirer.py `
  tests\component\test_crawl_fetch_runtime.py `
  tests\component\test_public_api.py `
  tests\unit\test_final_architecture_ownership.py `
  -q
```

### Slice 2: Browser Runtime, Readiness, Interaction, and Traversal Debt

**Status:** TODO
**Owners:** `browser_runtime.py`, `browser_fetch_support.py`, `browser_page_flow.py`, `browser_page_helpers.py`, `browser_detail.py`, new `browser_accessibility.py`, `browser_readiness.py`, `browser_recovery.py`, `browser_result_builder.py`, `runtime.py`, `traversal.py`, `traversal_recovery.py`, `traversal_card_counting.py`
**Fallback docs:** `docs/INVARIANTS.md` Rules 5, 6, 13 and `docs/ENGINEERING_STRATEGY.md` AP-16/AP-17.
**Known audited scope:** all functions in the acquisition portion of the long-function ledger; `HtmlAnalysis`, `HtmlDocument`, parser constructors, expansion entry points, warmup state, popup guards, readiness probes, traversal stop reasons.

**Implement:**

- Make `browser_runtime.browser_fetch` a phase orchestrator; existing support/page-flow/result owners perform mechanics.
- Move launch/warmup/popup lifecycle into public APIs in existing `browser_fetch_support.py`; remove private cross-module reach-ins.
- Keep DOM detail expansion in `browser_detail.py`; move accessibility-tree expansion and its candidates/snapshots to `browser_accessibility.py`; delete `*_impl` wrappers.
- Split readiness settle phases while preserving one parsed tree per unique snapshot and no BeautifulSoup under acquisition.
- Split challenge and traversal loops by action/poll/progress/finalization without combining mode-specific behavior.
- Keep page-side listing visual capture as a module-owned script plus typed normalization; it remains observation, not extraction.

**Slice acceptance:**

- `browser_runtime.py` <=650; `browser_detail.py` <=650; `browser_page_flow.py` <=650.
- Acquisition package <=15,400 LOC.
- Every acquisition long-function entry is removed; no replacement exceeds 100 lines.
- No expansion click can target header/nav/footer/site chrome or navigate away from requested detail identity.
- Readiness, block, listing, and final extraction reuse matching HTML documents; changed snapshots never reuse mismatched trees.
- Usable content still overrides provider noise; bounded challenge/warmup/close behavior remains intact.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\component\test_browser_context.py `
  tests\component\test_crawl_fetch_runtime.py `
  tests\unit\test_block_detection.py `
  tests\unit\test_browser_failure_kind.py `
  tests\unit\test_pipeline_browser_retry_budget.py `
  tests\unit\test_final_architecture_ownership.py `
  -q
```

### Slice 3: Listing Discovery and Listing Card Integrity

**Status:** TODO
**Owners:** `crawl/sitemap_resolver.py`, `crawl/site_link_discovery.py`, `crawl/sitemap_nav.py`, `extraction/listing.py`, `core/config/sitemap.py`, `core/config/extraction_recipes.py`, `core/config/extraction_rules/_common.py`, `core/records/url_identity.py`, listing tests
**Fallback docs:** `docs/INVARIANTS.md` Rules 1, 2, 7, 8, 13; listing/discovery ownership in `docs/CODEBASE_MAP.md`; user-supplied listing reports.
**Known audited scope:** `resolve_category_urls_from_sitemap_result`, rendered site-link validation, homepage/category candidate scoring, category nav tree labels, listing card selectors, listing URL validation, listing title selector order, `LISTING_TITLE_CTA_TITLES`, utility/category/detail URL markers, and all tests covering site-link discovery, sitemap resolver, and ecommerce listing extraction.

**Implement:**

- Treat the supplied Arcteryx, Belk, and Intimissimi outputs as symptoms only; create small generic fixtures that reproduce the failure classes without host branches.
- In static and rendered category discovery, require ecommerce listing evidence before returning broad same-origin links when `category_only`/ecommerce listing discovery is active: product-card density, product-detail-link density, price/image/card signals, or explicit requested-branch affinity.
- Demote or reject utility/site-chrome links: customer service, policy/legal/compliance, contact, FAQ, returns/shipping, stores/store locator, registry/wish list, app, athletes/ambassadors, vendor resources, catalog/ads, on-page `#` anchors, and marketing quizzes when they lack product-listing evidence.
- Preserve valid category/listing URLs even when the link appears inside nav, but only when path/category signal plus listing evidence or requested-branch affinity is present.
- In listing-card extraction, choose the product URL first, then choose title evidence from the same product-link/name scope. Reject selected-color/swatch/control/CTA/aria-state labels such as `Cor selecionada`.
- Require title evidence to agree with product URL/card context enough to avoid product rows with valid URL/price/image but non-product title.
- Keep failure honest: zero accepted product rows remains `listing_detection_failed`; rejected candidates carry diagnostics, not fake rows.

**Regression classes:**

- rendered category discovery rejects support/legal/store/registry/app/athlete links but keeps valid category links with product-listing evidence;
- category-specific seed does not broaden to unrelated top-level nav branches when requested branch affinity exists;
- listing card with product URL/price/image and selected-color label does not publish `Cor selecionada` as title;
- listing card with a valid product link/title still publishes normally;
- utility `#` anchors and same-page store-directory links are rejected.

**Slice acceptance:**

- No host/site branches for Arcteryx, Belk, or Intimissimi.
- Discovery diagnostics count rejected utility/nav candidates by reason.
- Ecommerce listing output cannot contain customer-service/legal/store/registry/app/athlete/site-chrome URLs.
- Ecommerce listing output cannot contain swatch/control/selected-state titles.
- Listing and detail surfaces stay separate; no detail fallback or downstream cleanup is added.
- Existing category discovery behavior for legitimate category URLs remains covered.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\component\test_site_link_discovery.py `
  tests\component\test_sitemap_resolver.py `
  tests\unit\test_extraction_pipeline.py `
  tests\acceptance\test_replay_sites.py `
  -q
```

### Slice 4: Product Identity, Title Quality, and Metadata Admission

**Status:** TODO
**Owners:** `extraction/collectors/url.py`, `dom.py`, `metadata.py`, `js_state.py`, `jsonld.py`, `pipeline.py`, `entities.py`, `resolution.py`, `validation.py`, `core/records/url_identity.py`, `core/config/field_mappings.py`, `core/config/extraction_rules/_detail.py`
**Fallback docs:** `docs/INVARIANTS.md` Rules 3, 6, 7, 13; extraction sections of `docs/BUSINESS_LOGIC.md`.
**Known audited scope:** all `product.title`, `product.brand`, `product.description`, source-key mappings, URL-title fallbacks, shell/title quality rules, and selected-public-value validation.

**Implement:**

- Add evidence flags/admission for filename extensions, code-only leaves, nav/tab/measurement titles, shell titles, and generic headings.
- Score title candidates by semantic product identity, URL-token agreement, source reliability, and pollution; do not clean a bad candidate into a fabricated title.
- Keep URL-derived title as low-confidence review evidence only; strip `.html`/query noise before comparison.
- Move source-key aliases out of collectors into `field_mappings.py`; add generic description, currency, availability, image-array, and brand-object mappings.
- Require JS/network product or offer context before generic keys create entities/offers.
- Validate resolved selected public values, not only raw evidence presence.

**Regression classes:**

- filename/ID title versus valid structured/H1 title;
- `Measurements`/navigation title rejected;
- SEO suffix/price removed only when product title evidence remains;
- arbitrary nested `price` object cannot create a product offer;
- missing brand/price/image remains missing with a finding when no evidence exists.

**Slice acceptance:**

- No host/site branches.
- No filename, internal ID, generic tab, or navigation title can produce success.
- Brand is never inferred from retailer/hostname alone.
- Missing default/requested fields produce one visible field finding after resolution.
- Extraction shape gates remain within 24 files/5,500 LOC/400 lines/60-line functions.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_extraction_pipeline.py `
  tests\unit\test_extraction_architecture.py `
  tests\unit\test_extraction_current_run_replay.py `
  tests\unit\test_public_record_firewall.py `
  -q
```

### Slice 5: Product Asset Selection and Additional Images Contract

**Status:** TODO
**Owners:** `extraction/contracts.py`, `entities.py`, `resolution.py`, `materialization.py`, asset collectors, `core/config/extraction_rules/_images.py`, `core/config/field_mappings.py`, `schemas/crawl.py`, `persistence/export/*`, record APIs/review serializers
**Fallback docs:** `docs/INVARIANTS.md` Rules 3, 8, 13 and public API/output sections of `docs/BUSINESS_LOGIC.md`.
**Known audited scope:** `AssetDecision`, all asset facts/entities, every `image_url`/`additional_images` reader and serializer, primary-image reject tokens, URL normalization and asset dedupe.

**Implement:**

- Use the existing `AssetDecision` contract for one product-level ordered asset decision; delete it if a single generic `Decision` representation fully replaces it, but do not keep both unused.
- Normalize HTTP(S) asset URLs before entity identity; encode path spaces safely and dedupe transform-equivalent URLs without deleting meaningful variant parameters.
- Rank structured/product-scoped/direct assets above DOM-wide assets; reject placeholders, 1x1/pixel/no-image, logo, payment, discount, loader, arrows/icons, testimonial/quote, schedule/email, and unrelated promotional assets using generic role signals.
- Materialize `image_url` once from the primary decision. Materialize ordered, deduped, admissible non-primary product assets as `additional_images` excluding the primary.
- Add backward-compatible `additional_images` to typed record, schemas, API, export, review, and lineage.

**Slice acceptance:**

- Asset iteration order cannot change the primary image.
- Primary and additional assets carry accepted evidence IDs and role/rank rule IDs.
- Utility SVG/GIF and placeholder cases are rejected; a legitimate product SVG is not rejected solely by extension.
- `additional_images` is absent/empty when no secondary evidence exists and never duplicates `image_url`.
- Existing consumers of `image_url` remain compatible.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_extraction_pipeline.py `
  tests\unit\test_extraction_architecture.py `
  tests\component\test_records_api.py `
  tests\component\test_record_export_service.py `
  tests\component\test_review_service.py `
  -q
```

### Slice 6: Offer Integrity, Variant Completeness, and Honest Diagnostics

**Status:** TODO
**Owners:** `extraction/collectors/js_state.py`, `jsonld.py`, `dom.py`, `entities.py`, `resolution.py`, `validation.py`, `materialization.py`, `result_building.py`, existing variant/config owners
**Fallback docs:** `docs/INVARIANTS.md` Rule 3 first, then Rules 6, 7, 13; `docs/ENGINEERING_STRATEGY.md` AP-12/AP-20.
**Known audited scope:** all early returns, recursive object traversal, variant identity/grouping, parent/variant offers, price/currency pairing, selected-variant references, DOM cue gates, and capability requests.

**Implement:**

- Preserve full recursive source traversal and later-object backfill; no first-object or early-return loss.
- Admit price only with product/offer context; reject non-positive price; keep magnitude changes forbidden without independent corroboration.
- Resolve price/currency/availability atomically within one offer entity.
- Publish a variant only when it has stable identity plus at least one option or commercial fact. Preserve ID-only evidence in an `INCOMPLETE_VARIANT_EVIDENCE` finding.
- Inherit product-wide price/currency/availability to variants only when the offer is explicitly parent-wide, no child evidence conflicts, and lineage names the inheritance rule.
- Keep missing SKU/color/size honest when not inferable. No Cartesian variant fabrication.
- Request one rendered capability only when explicit variant DOM cues exist and deterministic captured evidence remains incomplete.

**Slice acceptance:**

- No public variant is ID-only or URL-only.
- Explicit sellable variants retain all available identity, option, offer, availability, URL, and image evidence.
- Parent availability is coherent only for a complete variant matrix; incomplete matrices do not override parent evidence.
- `0.00` cannot be a successful product price; year-like or 100x values are rejected/flagged unless corroborated, never guessed.
- Missing regional variants remain partial/review with findings if capture contains no variant evidence.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_extraction_pipeline.py `
  tests\unit\test_extraction_current_run_replay.py `
  tests\unit\test_pipeline_browser_retry_budget.py `
  tests\unit\test_extraction_architecture.py `
  -q
```

### Slice 7: Canonical Provenance and Legacy Column Retirement

**Status:** TODO
**Owners:** `crawl/pipeline/persistence.py`, `persistence/url_result_artifacts.py`, `record_artifacts.py`, `record_export_service.py`, `publish/metadata.py`, `crawl/crud.py`, `crawl/review/*`, `schemas/crawl.py`, `observability/run_audit.py`, `models/crawl_run.py`, migration only if required
**Fallback docs:** `docs/INVARIANTS.md` Rules 4, 8, 14; persistence/review sections of `docs/CODEBASE_MAP.md` and `docs/BUSINESS_LOGIC.md`.
**Known audited scope:** every read/write of the four legacy columns, `RecordArtifacts` dual-read behavior, review bucket mutation, field discovery/coverage, LLM suggestion acceptance, manifest/provenance readers.

**Implement:**

- Make canonical record provenance/artifacts the source for raw evidence, lineage, acquisition diagnostics, field discovery, review candidates, and requested coverage.
- Derive field-discovery/coverage from extraction lineage plus current `record.data`; stop `publish/metadata.py` writes.
- Derive remaining review candidates from immutable provenance minus existing ReviewPromotion/DomainFieldFeedback decisions; stop review-bucket mutation.
- Record accepted user/LLM edits through existing review/domain-feedback ownership and logs; do not mutate immutable extraction provenance.
- Move all active consumers to `RecordArtifacts`; keep legacy-column fallback read-only only for old rows until a coverage test proves artifact availability.
- Remove ORM/schema/API exposure and physical columns only after the slice's compatibility fixture proves old-row reads or the migration/backfill is explicit. No silent data loss.

**Slice acceptance:**

- Zero active writes to all four legacy columns.
- Architecture owner allowlist for legacy fields is empty or contains only a single documented old-row loader pending the same slice's migration.
- Current records read canonical artifacts; old-row compatibility behavior is tested.
- Persistence remains storage-only and does not repair fields/verdicts.
- Artifact writes remain atomic, hashed, manifest-last, and replayable.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_url_result_persistence.py `
  tests\unit\test_replay_persistence_guard.py `
  tests\unit\test_publish_metrics.py `
  tests\unit\test_crawl_schemas.py `
  tests\component\test_record_export_service.py `
  tests\component\test_review_service.py `
  tests\unit\test_final_architecture_ownership.py `
  -q
```

### Slice 8: Crawl Run Ownership, URL Sessions, and Progress Debt

**Status:** TODO
**Owners:** `crawl/batch_runtime.py`, `crawl/pipeline/extraction_loop.py`, `run_progress.py`, existing failure/runtime helpers, worker adapters
**Fallback docs:** `docs/INVARIANTS.md` Rules 5, 6, 14; crawl flow in `docs/CODEBASE_MAP.md`.
**Known audited scope:** `process_run`, `process_single_url`, URL session creation/rollback, parallel task ownership, progress summaries, pause/kill/heartbeat paths, duplicate state transitions.

**Implement:**

- Keep `process_run` as run lifecycle owner and `process_single_url` as URL workflow owner; do not add coordinator classes.
- Split parallel scheduling from result collection and run setup from finalization.
- Preserve one DB session/transaction per URL in serial and parallel modes; orchestration session never performs URL persistence.
- Consolidate acquisition metric merging by concern and delete duplicate progress shaping.
- Preserve sitemap/category discovery, pause/cancel, heartbeat, restart/idempotency, record limits, and URL-local failures.

**Slice acceptance:**

- `batch_runtime.py` <=650; three crawl long-function entries removed.
- Crawl package <=9,250 LOC.
- A failed URL flush/timeout does not poison the run or later URLs.
- Local mode concurrency remains 1; record limits remain deterministic.
- Restart/duplicate delivery cannot duplicate records or regress terminal run state.
- `test_batch_runtime.py` behavior remains intact; edits are limited to new/changed contract assertions.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\regression\test_batch_runtime.py `
  tests\component\test_crawl_service.py `
  tests\unit\test_final_architecture_ownership.py `
  -q -m "unit or component or regression"
```

### Slice 9: Config and Confidence Ownership

**Status:** TODO
**Owners:** `core/config/runtime_settings.py`, existing domain config modules, `core/records/confidence.py`, config/architecture tests
**Fallback docs:** `docs/ENGINEERING_STRATEGY.md` AP-1/AP-10/AP-11/AP-13/AP-21/AP-22.
**Known audited scope:** all runtime settings imports and profile-default application; duplicate extraction key mappings; confidence inputs/consumers.

**Implement:**

- Split `_apply_profile_defaults` into existing acquisition/extraction/storage/worker/observability/intelligence/enrichment domain views while retaining one application settings object.
- Remove orphaned settings and duplicate exports only after caller search; do not create parallel config sources.
- Split confidence field scoring, penalties, and aggregation; confidence remains diagnostic and cannot mutate extraction values/verdicts.
- Add source-key mappings needed by Slices 3-5 only to canonical config owners.

**Slice acceptance:**

- Both long functions removed; no import-time `globals()` config mutation added.
- Core package <=14,500 LOC.
- Runtime settings remain environment-driven and explicit user controls unchanged.
- Confidence output is deterministic for identical typed input.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\unit\test_config_security.py `
  tests\unit\test_public_record_firewall.py `
  tests\unit\test_publish_metrics.py `
  tests\unit\test_final_architecture_ownership.py `
  -q
```

### Slice 10: Review, Intelligence, and Enrichment Owner Closure

**Status:** TODO
**Owners:** `crawl/review/__init__.py`, existing review support modules, `intelligence/matching.py`, `enrichment/shopify_catalog.py`, new `shopify_repository.py`, `enrichment/deterministic.py`, `service.py`
**Fallback docs:** `docs/INVARIANTS.md` Rules 8, 9, 10, 13; `docs/ENGINEERING_STRATEGY.md` AP-17/AP-18.
**Known audited scope:** long review/intelligence functions, Shopify catalog imports, repository file loads, taxonomy/matching duplicates, LLM boundaries.

**Implement:**

- Split review recipe load/coverage/selector/response phases using existing support owners; no mutable extraction provenance.
- Split intelligence deterministic features from final score policy without changing identity ladder or exact-conflict behavior.
- Move Shopify JSON repository loading/index/lookup into `shopify_repository.py`; keep taxonomy scoring/matching in `shopify_catalog.py`; delete duplicate token/flatten helpers.
- Keep candidate product pages on normal acquisition/extraction. Keep enrichment unable to change extraction facts/verdicts.

**Slice acceptance:**

- `shopify_catalog.py` <=650 and enrichment package <=2,150 LOC; new repository file has no scoring policy.
- Review and score long-function entries removed.
- Intelligence <=3,250 LOC.
- GTIN/style exact conflicts remain deterministic; LLM cannot override them.
- No local shadow taxonomy or product-detail scraper is introduced.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\component\test_review_service.py `
  tests\component\test_crawls_api_domain_recipe.py `
  tests\component\test_product_intelligence.py `
  tests\regression\test_data_enrichment.py `
  tests\unit\test_final_architecture_ownership.py `
  -q -m "unit or component or regression"
```

### Slice 11: LLM Connector Task Closure

**Status:** TODO
**Owners:** `connectors/llm/tasks.py`, existing provider/config/cost owners and tests
**Fallback docs:** `docs/INVARIANTS.md` Rule 10; LLM section of `docs/BUSINESS_LOGIC.md`.
**Known audited scope:** `run_prompt_task`, direct/missing-field/review modes, provider calls, cost logging, circuit breaker, fallback/error paths.

**Implement:**

- Split provider invocation, response validation, cost recording, and visible failure projection.
- Preserve explicit dual gate: run setting and active LLM config.
- LLM remains gap fill/adjudication only; deterministic values and conflicts win.
- Delete duplicate prompt/result shaping and obsolete task wrappers.

**Slice acceptance:**

- `run_prompt_task` <=100; connectors <=2,700 LOC.
- Provider timeout/error is visible and degradable.
- No LLM call occurs when disabled; no deterministic value is silently replaced.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest `
  tests\regression\test_llm_runtime.py `
  tests\regression\test_llm_circuit_breaker.py `
  tests\component\test_llm_config_service.py `
  -q -m "unit or component or regression"
```

### Slice 12: Final Architecture Ratchet, Offline Suite, and Documentation

**Status:** TODO
**Owners:** architecture tests, canonical docs, this plan, `ACTIVE.md`; production files only for defects revealed by verification
**Fallback docs:** canonical docs listed under Authority only when final verification reveals a contract/doc mismatch; do not reread superseded plans/audits.
**Known audited scope:** deleted symbols/modules, all architecture allowlists, cross-module private imports, config placement, package/file/function counts, legacy fields, public contracts.

**Implement:**

- Remove all five oversized and all 24 long-function debt entries. Do not replace them with new allowlist entries.
- Add exact package LOC budgets from this plan to the architecture ratchet.
- Confirm extraction shape gates, no `app.services`, no acquisition `bs4`, no site branches, and no deleted compatibility symbols.
- Update canonical docs only for ownership/contract changes actually implemented, including `additional_images` and any named new owners.
- Run Ruff once and the complete offline unit/component/regression suite once; rerun only failures.
- Record final counts and verification in Notes.

**Slice acceptance:**

- Every global acceptance checkbox is satisfied except the user live gate.
- `OVERSIZED_MODULE_DEBT` and `LONG_FUNCTION_DEBT` are empty.
- Package and total LOC budgets pass.
- Full offline suite passes with regression marker included.
- Plan status becomes `IN PROGRESS — AWAITING USER 100-SITE GATE`; `ACTIVE.md` still points here.

**Verify:**

```powershell
cd C:\Projects\CrawlerAI\backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m ruff check app tests
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
.\.venv\Scripts\python.exe -m pytest tests -q -m "unit or component or regression"
```

### Slice 13: User 100-Site Gate

**Status:** USER-OWNED; DO NOT RUN
**Owner:** user/operator
**Prerequisite:** Slice 12 offline closure.

The user runs the live 100-site gate. Implementation agents only inspect supplied artifacts/results afterward.

**Acceptance:**

- Zero successful shell/error pages.
- Zero missing canonical detail URLs.
- Zero primary images classified as placeholder, utility, logo, payment, loader, navigation, testimonial, or unrelated promo assets.
- `additional_images` is populated only from product-scoped admissible evidence and contains no primary duplicate.
- Zero filename/ID/nav/tab titles among successful detail records.
- Zero non-positive successful prices and zero silent uncorroborated magnitude repairs.
- Zero contradictory parent availability for complete variant matrices.
- Zero unexplained loss of explicit captured variants; incomplete evidence has findings.
- Missing metadata without admissible evidence remains missing with visible findings, never fabricated.
- Where comparable, p50/p95 acquisition latency does not regress more than 10% from the supplied prior gate.

If the gate passes, mark this plan `DONE` and update `ACTIVE.md` to `No active plan.` If it fails, reopen only the owning slice using supplied artifacts; do not start another architecture plan.

## Required Documentation Updates

- [ ] `docs/CODEBASE_MAP.md` — named new owners and moved responsibilities.
- [ ] `docs/INVARIANTS.md` — additive `additional_images`/asset-role contract and any new violation signatures.
- [ ] `docs/BUSINESS_LOGIC.md` — title/asset/variant decision ownership if behavior changed.
- [ ] `docs/ENGINEERING_STRATEGY.md` — only if implementation reveals a new recurring anti-pattern not already covered.
- [ ] `docs/backend-architecture.md` — final acquisition attempt flow, provenance ownership, and public record contract.
- [ ] `AGENTS.md` — only if bootstrap routing or always-on warnings change; keep it terse.
- [ ] Revised feature specification — mark implementation status or supersession; do not rewrite historical rationale.

## Handoff Notes

- Start at Slice 1. Do not reopen the global audit.
- Do not create another architecture plan for these issues. If new evidence appears, attach it to the owning slice's notes and continue this plan.
- Before editing, inspect the current working-tree diff for the slice files and preserve user work.
- Recompute only the slice's file/function counts after edits; recompute the full ledger in Slice 12.
- Do not mark a slice done from code inspection alone. Run its exact verify command.
- Stop after one coherent slice. Record files changed, deletions, test result, LOC delta, remaining debt, and next slice here.
