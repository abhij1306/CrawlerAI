# Plan: Full Backend Extraction Rebuild

**Created:** 2026-06-19
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Bucket 2 (crawl orchestration), Bucket 3 (acquisition boundary), Bucket 4 (extraction), Bucket 5 (persistence artifacts), Bucket 6 (selectors/domain memory), docs/tests

## Goal

Implement the root architecture contract in `CrawlerAI_Full_Backend_Extraction_Rebuild_Audit_and_Plan.md`: one deterministic extraction engine for exactly four explicit surfaces (`ecommerce_listing`, `ecommerce_detail`, `job_listing`, `job_detail`). Done means all four surfaces use the same CaptureBundle -> DocumentStore -> Evidence -> Entity Graph -> Findings -> Decisions -> typed materialization path, with replayable lineage, strict quality verdicts, CSS-only recipes, adapter artifacts instead of adapter records, no surface inference, and no success for shell or variant-broken ecommerce detail pages.

## Standalone Architecture Contract

This plan is self-contained. Implementers do not need the older step docs to know the target shape.

Production extraction has one public entry:

```text
extract(request: ExtractionRequest) -> ExtractionResult
```

The production path is:

```text
Explicit Surface
  -> CaptureBundle
  -> DocumentStore
  -> Collectors emit Evidence only
  -> Entity graph
  -> Findings
  -> Decisions
  -> Typed surface record materialization
  -> Requested-field filtering
  -> Quality verdict
  -> Replay + persistence artifacts
```

Allowed surfaces:

```text
ecommerce_detail
ecommerce_listing
job_detail
job_listing
```

Rejected always:

```text
auto
URL-based surface inference
HTML/schema surface inference
network-body surface inference
surface switching after acquisition
listing/detail or commerce/jobs substring branching outside the surface registry
```

Target extraction package ownership:

```text
app/services/extraction/
  contracts.py        # immutable request/result/evidence/entity/decision models
  surfaces.py         # only owner of surface differences
  engine.py           # only extraction orchestrator
  documents.py        # only Selectolax/Lexbor import
  json_walk.py        # JSON Pointer walker
  collectors/         # structured/state/network/dom/recipe evidence only
  entities.py         # product/variant/offer/asset/job graph building
  validation.py       # findings only, no mutation
  resolution.py       # decisions only
  materialization.py  # typed public records only
  quality.py          # surface verdicts
  replay.py           # replay artifact assembly
```

Runtime extraction must not accept or pass these loose arguments past the pipeline boundary:

```text
html
network_payloads
adapter_records
browser_diagnostics
selector_rules
artifacts dict
```

Those become `ArtifactRef` entries and payloads inside `CaptureBundle`.

## Required Public Contracts

### Ecommerce Detail

Must produce one product record or an honest non-success verdict. Success requires:

- title and URL compatible with requested/final URL
- no shell/error title such as `Oops! Something went wrong`
- default high-value fields (`title`, `price`, `image_url`) present or missing-field diagnostics recorded
- coherent offer group when price/currency is published
- primary image not placeholder/logo/icon/swatch/tracking pixel
- explicit variants preserved when structured/state/network/DOM variant evidence exists
- all public values have lineage

Variant public rows are flat. Allowed keys:

```text
sku, price, currency, url, image_url, availability, stock_quantity,
public axes such as size/color/width/material/style
```

Forbidden public variant keys:

```text
selected_variant, variant_axes, available_sizes, option_*, nested option_values,
variant title, internal identity helpers
```

### Ecommerce Listing

Must retain valid product rows up to `max_records`. Every row requires title and URL. Listing zero rows is `empty` or listing failure, never a fake detail success.

### Job Detail

Must produce one job record with job facts only. Success requires title plus support from company, location, apply URL, or meaningful description. Product pages under `job_detail` return `wrong_surface` or invalid/review with a typed finding.

### Job Listing

Must retain valid job rows up to `max_records`. Every row requires title and URL. No navigation-only cluster may succeed.

## Known Live Failures Owned By This Plan

- H&M PDP: previously `record_count=0`; must extract product fields and variants or produce precise diagnostics.
- Puma PDP: previously `record_count=0` from blocking offer findings despite available product data; must resolve coherent offer groups.
- Zara PDP: previously `record_count=0` and placeholder image risk; must reject placeholder assets and keep valid fields.
- New Balance PDP: previously persisted shell title `Oops! Something went wrong` as success; must become non-success with shell diagnostic.
- Latest persisted ecommerce records had `variants=0`; configurable apparel/shoe PDPs must preserve variants when evidence exists.

## Deletion Safety Contract

Do not delete random files. Delete only when one of these is true:

- architecture tests prove no active imports/callers remain
- the file is an obsolete extraction owner named in this plan
- replacement behavior has replay/unit coverage
- a grep scan is recorded in plan notes

Deletion is allowed after Slice 11 only for files that fail the new architecture ownership model. This is the safe point to remove stale tests, config exports, adapters that still return records, old selector self-heal/auto-learn paths, and any remaining legacy extraction owners.

## Acceptance Criteria

- [ ] Backend accepts only `ecommerce_listing`, `ecommerce_detail`, `job_listing`, and `job_detail`; `auto` and inferred/switched surfaces are rejected.
- [ ] `extract(request: ExtractionRequest) -> ExtractionResult` is the only production extraction entry; runtime code does not pass loose `html`, `network_payloads`, `adapter_records`, selector dicts, or artifact dicts into surface-specific extractors.
- [ ] `CaptureBundle` owns requested/final URL, acquisition outcome, request context, and all artifact refs; `DocumentStore` parses each HTML artifact once.
- [ ] All collectors emit immutable `Evidence` only; no collector or resolver creates public dictionaries.
- [ ] All four surfaces build typed entities, findings, decisions, and typed public records before requested-field filtering.
- [ ] Ecommerce detail quality rejects shell/error pages, missing high-value fields without diagnostics, incoherent offers, placeholder primary assets, and missing explicit variants when variant evidence exists.
- [ ] Latest crawl failures are covered by replay tests: missing variants, three zero-result PDPs, and New Balance shell false success.
- [ ] Job detail and job listing use job facts only and do not reuse commerce aliases.
- [ ] Selectolax/Lexbor remains isolated to `app/services/extraction/documents.py`; no BeautifulSoup/lxml/extruct/glom/jmespath in extraction.
- [ ] Adapter code produces artifact refs/payloads only; no adapter returns public records.
- [ ] Selectors are explicit CSS recipes only; no XPath, regex selectors, auto-learn, self-heal, or crawl-time recipe writes.
- [ ] Replay/persistence writes capture, evidence, entities, findings, decisions, records, and verdict for every URL.
- [ ] Architecture tests fail on surface inference, surface prefix/substring branching outside allowed registry helpers, collector public records, missing lineage, success with zero evidence/decisions, and forbidden parser/query dependencies.
- [ ] Deletion readiness scan passes: no active imports of old extraction owners, no adapter public records, no selector self-heal/auto-learn hot-path imports, no generated config export loader, no forbidden parser/query imports.
- [ ] Ten-site smoke gate passes at the end of the plan with explicit surfaces and saved report.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe run_acquire_smoke.py commerce`, `run_extraction_smoke.py`, and `run_test_sites_acceptance.py` complete or have documented external blockers.

## Ten-Site Final Smoke Gate

Run this after Slice 12, not before architecture is in place.

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe run_test_sites_acceptance.py --mode full_pipeline `
  --url "https://www2.hm.com/en_us/productpage.1344928003.html" --surface ecommerce_detail `
  --url "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html" --surface ecommerce_detail `
  --url "https://www.uniqlo.com/us/en/products/E455957-000/00?colorDisplayCode=57&sizeDisplayCode=004" --surface ecommerce_detail `
  --url "https://www.levi.com/US/en_US/clothing/men/shorts/carrier-cargo-lightweight-9-mens-shorts/p/001KG0053" --surface ecommerce_detail `
  --url "https://us.puma.com/us/en/pd/suede-classic-sneakers/395205" --surface ecommerce_detail `
  --url "https://www.newbalance.com/pd/1080v15-breathe/M1080V15_RU-FTW-821915.html/?ICID=pgp_mt_pdp_1080_breathe_nb5294_m" --surface ecommerce_detail `
  --url "https://web-scraping.dev/products" --surface ecommerce_listing `
  --url "https://web-scraping.dev/product/1" --surface ecommerce_detail `
  --url "https://boards.greenhouse.io/embed/job_board?for=airbnb" --surface job_listing `
  --url "https://boards.greenhouse.io/airbnb/jobs/6290875" --surface job_detail
```

Smoke pass means:

- no process timeout
- report summary `failed=0`
- every successful record has evidence, decisions, lineage, and verdict
- ecommerce detail configurable pages have variants or a specific diagnostic explaining absence
- New Balance shell does not persist as success
- H&M/Puma/Zara do not silently produce zero records without findings
- job pages use job facts and never commerce aliases

## Do Not Touch

- `publish/*` - do not hide extraction defects downstream.
- `backend/app/services/product_intelligence/*` - separate commerce workflow.
- `backend/app/services/data_enrichment/*` - consumes persisted extraction output; do not patch extraction defects here.
- Frontend UI redesign - surface controls may be corrected only if needed for the four-surface contract.
- `docs/archive/**` - historical.

## Slices

### Slice 1: Activate Contract And Guardrails
**Status:** TODO
**Files:** `docs/plans/ACTIVE.md`, this plan, `backend/tests/unit/test_extraction_architecture.py`, `backend/tests/unit/test_extraction_pipeline.py`
**What:** Add failing architecture tests for the original contract gaps found in review: no loose extractor inputs, no surface substring branching outside approved helpers, no collector/materializer public dict shortcuts, no success without evidence/decisions/lineage, no ecommerce detail success with shell title or missing high-value fields, no variant evidence loss, and no placeholder primary asset success.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_architecture.py tests/unit/test_extraction_pipeline.py -q`

### Slice 2: Normalize CaptureBundle Boundary
**Status:** TODO
**Files:** `backend/app/services/extraction/contracts.py`, `backend/app/services/extraction/replay.py`, `backend/app/services/pipeline/extract_records.py`, `backend/app/services/pipeline/record_extraction_stage.py`
**What:** Replace loose extraction invocation with a single `ExtractionRequest` built from acquisition artifacts. Move HTML, network JSON, adapter JSON, browser diagnostics, CSS recipes, and requested fields into typed capture/request structures. Keep transitional helpers test-only if needed, but production extraction must not re-expand into loose arguments.
**Verify:** Focused extraction pipeline tests plus import scan for deleted loose-argument paths.

### Slice 3: One Engine Skeleton For Four Surfaces
**Status:** TODO
**Files:** `backend/app/services/extraction/engine.py`, `pipeline.py`, `listing.py`, `jobs.py`, `surfaces.py`, `contracts.py`
**What:** Route all surfaces through one shared orchestration: collect evidence, build entities, validate, resolve, materialize, quality verdict, replay. Surface-specific modules may provide vocabularies, collectors, graph policies, and materializers, but not separate mini-engines.
**Verify:** Acceptance replay tests for all four surfaces pass and assert same replay shape.

### Slice 4: Typed Entity Graph And Public Models
**Status:** TODO
**Files:** `backend/app/services/extraction/entities.py`, `resolution.py`, `materialization.py`, new focused tests if needed
**What:** Introduce typed entity graph nodes for product, variant, offer, asset, and job. Introduce typed public records for commerce detail/listing and job detail/listing. Move job and listing dict construction behind shared decision materialization. Requested-field filtering stays after full materialization.
**Verify:** Unit tests prove every public field has lineage and collectors/resolvers do not return public records.

### Slice 5: Ecommerce Detail Quality Gate
**Status:** TODO
**Files:** `backend/app/services/extraction/validation.py`, `quality.py`, commerce collectors/resolution/materialization tests
**What:** Enforce product shell rejection, high-value field diagnostics, atomic offer coherence, primary asset validity, wrong-surface product/listing detection, and explicit variant expectation. This is architecture-level validation, not site-specific repair.
**Verify:** Replay/unit tests for New Balance shell, H&M/Puma/Zara invalid empty pages, and generic variant-heavy PDPs.

### Slice 6: Variant Evidence And Linking
**Status:** TODO
**Files:** `backend/app/services/extraction/collectors/jsonld.py`, `collectors/js_state.py`, `collectors/network.py`, `collectors/dom.py`, `entities.py`, `resolution.py`, `materialization.py`
**What:** Implement robust ProductGroup/hasVariant, script-state/network variant object classification, DOM variant-control evidence, parent subject IDs, exact variant identity merge, option-tuple identity, offer inheritance, asset association, and flat public variant rows.
**Verify:** Variant replay tests assert non-empty variants, clean rows, inherited offer fields where valid, and no UI-noise variant rows.

### Slice 7: Listing Shared Card Graph
**Status:** TODO
**Files:** `backend/app/services/extraction/listing.py`, `jobs.py`, shared collectors/entities/materialization
**What:** Replace listing-specific dict assembly with repeated structural group evidence and shared listing entities. Ecommerce and jobs keep separate vocabularies but use the same card grouping/resolution shape.
**Verify:** Ecommerce listing and job listing replay tests pass; listing runs with zero rows return listing failure/empty, never fake detail success.

### Slice 8: Connector Artifact Boundary
**Status:** TODO
**Files:** `backend/app/services/adapters/base.py`, `registry.py`, pipeline adapter call sites, tests
**What:** Rename or enforce adapters as artifact connectors. Existing platform value is retained only as JSON artifacts that flow through collectors. No connector returns final public records.
**Verify:** Adapter architecture tests plus adapter artifact replay test.

### Slice 9: CSS Recipe Selector System
**Status:** TODO
**Files:** `backend/app/api/selectors.py`, `schemas/selectors.py`, `selectors_runtime.py`, `domain_memory_service.py`, extraction recipe collector/tests
**What:** Keep explicit saved CSS recipes only. Remove XPath, regex selectors, self-heal, auto-learn, and automatic recipe writes from hot paths.
**Verify:** Selector API/runtime focused tests and grep for XPath/regex/self-heal/auto-learn active code.

### Slice 10: Replay And Persistence Artifacts
**Status:** TODO
**Files:** `backend/app/services/pipeline/persistence.py`, `backend/app/services/observability/*`, `backend/harness/support.py`
**What:** Persist/read new replay shape: `capture.json`, `evidence.jsonl`, `entities.json`, `findings.json`, `decisions.json`, `records.json`, `verdict.json`, plus compact extraction decision summary. RunTrace reads from `ExtractionResult`, not ad hoc legacy summaries.
**Verify:** Replay persistence guard tests and artifact inspection for latest crawl fixture.

### Slice 11: Architecture Scans And Dead-Code Cleanup
**Status:** TODO
**Files:** architecture tests, dependency/config cleanup, docs
**What:** Delete any remaining legacy extraction owners or tests not serving the new public contract. Enforce parser/dependency/import gates, surface-branching gates, adapter-record gates, selector hot-path gates, and stale config export gates. Record grep scans in Notes before deletion.
**Verify:** Architecture tests, dependency import scan, `rg` scans from original plan.

### Slice 12: Live Crawl Repair After Architecture
**Status:** TODO
**Files:** extraction collectors/resolution/validation only
**What:** Re-run the latest crawl set and fix remaining live misses upstream in architecture owners. Target known failures: variants missing, H&M/Puma/Zara zero output, New Balance shell false success.
**Verify:** Smallest relevant replay tests, then `run_extraction_smoke.py`, `run_acquire_smoke.py commerce`, `run_test_sites_acceptance.py`, and the Ten-Site Final Smoke Gate in this plan.

### Slice 13: Deletion Readiness Handoff
**Status:** TODO
**Files:** `docs/plans/ACTIVE.md`, this plan, `docs/CODEBASE_MAP.md`, active docs/tests
**What:** Mark exact files safe to delete or already deleted, based on Slice 11 scans and passing tests. Produce a short kill-list note in this plan. Do not leave broad "random files" language; deletion must be evidence-backed.
**Verify:** Full backend tests pass, ten-site smoke report saved, and kill-list scans show no active imports.

## Doc Updates Required

- [ ] `docs/INVARIANTS.md` - update extraction contract to the rebuilt evidence/entity/decision model once code lands.
- [ ] `docs/CODEBASE_MAP.md` - replace legacy extraction owners with new package ownership.
- [ ] `docs/BUSINESS_LOGIC.md` - document four-surface behavior and wrong-surface verdict.
- [ ] `docs/backend-architecture.md` - update acquisition-to-extraction boundary and artifact/replay shape.
- [ ] `docs/frontend-architecture.md` - update only if frontend surface controls change.
- [ ] `docs/feature specs/CrawlerAI_Full_Backend_Extraction_Rebuild_Audit_and_Plan.md` - replace premature implemented status with actual final verification status when complete.

## Notes

- This plan supersedes the current blocked extraction-productionization plan and pauses the aggressive deletion refactor until the extraction foundation is correct.
- Review on 2026-06-19 found the current implementation deletes large legacy areas but misses the original architecture contract: loose extractor inputs remain, separate mini-engines remain, quality accepts shell title/url success, and latest crawl variants are absent.
- Latest run evidence from `backend/artifacts/runs/1` shows three `record_count=0` ecommerce detail pages (H&M, Puma, Zara) plus one New Balance shell persisted as success with only title/url.
- Fix live crawl misses only after Slices 1-11 establish the intended architecture.
- User wants this plan to be standalone and comprehensive enough to support later deletion. Deletion is gated by Slice 13, not ad hoc file removal.
