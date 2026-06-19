# Plan: Full Backend Extraction Rebuild

**Created:** 2026-06-19
**Revised:** 2026-06-19
**Agent:** Codex
**Status:** SUPERSEDED
**Superseded by:** `docs/plans/final-architecture-improvement-plan.md`
**Touches buckets:** Bucket 2 (crawl orchestration), Bucket 3 (acquisition boundary), Bucket 4 (extraction), Bucket 5 (persistence/trace), Bucket 6 (selectors/domain memory), docs/tests

## Goal

Finish the four-surface extraction architecture without preserving duplicate decision owners or compatibility debt. Done means `ecommerce_detail`, `ecommerce_listing`, `job_detail`, and `job_listing` all run through one deterministic extraction orchestration path:

```text
ExtractionRequest
  -> CaptureBundle + ArtifactReader
  -> collect immutable Evidence
  -> normalize Evidence once
  -> build EntityGraph
  -> select target root entity/entities
  -> validate selected scope
  -> resolve typed Decisions
  -> materialize typed records once
  -> compute one URL verdict
  -> persist one canonical ExtractionResult/replay
```

The latest crawl artifacts are the first replay corpus. Architecture is not complete until the known failures from `backend/artifacts/runs/1` are reproducible offline and fixed through generic selected-scope logic, not site-specific downstream patches.

## Current State To Retain

Do not reimplement these already-landed decisions:

- exactly four explicit surfaces: `ecommerce_listing`, `ecommerce_detail`, `job_listing`, `job_detail`
- `app/services/extraction/` package exists
- Selectolax/Lexbor is isolated behind `documents.py`
- immutable Pydantic evidence contracts exist
- evidence includes `subject_id` and `parent_subject_id`
- deleted parser/query dependencies stay deleted: `glom`, `jmespath`, `extruct`, `lxml`, `cssselect`, `aiohttp`, `dateparser`, `price-parser`, `jsonschema`, `w3lib`
- selector direction is CSS-only recipes
- one top-level `extract(request)` entry exists

## Current Defects To Eliminate

The current package still has four mini-engines:

```text
engine.py
  -> pipeline.extract_ecommerce_detail()
  -> listing.extract_ecommerce_listing()
  -> jobs.extract_job_detail()
  -> jobs.extract_job_listing()
```

The current ecommerce detail path still accepts loose runtime inputs:

```text
html
page_url
network_payloads
artifacts dict
requested_page_url
```

The current listing/job paths do not share the same entity graph, target selection, validation, decision, and materialization pipeline as ecommerce detail.

The current verdict, normalization, public-record validation, persistence shaping, and trace summaries have multiple owners. The rebuild must leave one owner for each.

## Latest Run Findings

Freeze and use `backend/artifacts/runs/1` as the initial replay corpus.

| Site | Critical result |
|---|---|
| Under Armour | Trace sees variants; persisted record has none |
| H&M | Large usable page returns `record_count=0`; unrelated incomplete offers globally invalidate page |
| Levi's | Trace sees variant; persisted record has none |
| Uniqlo | Configurable page succeeds with zero variants |
| New Balance | 628-byte shell title `Oops! Something went wrong` persisted as success |
| Puma | Product evidence exists but global offer findings force empty result |
| Zara | Product evidence exists but global findings force empty result; placeholder image risk |
| North Face | Benefit icon selected as primary image; variants missing |

Systemic defects:

- findings are global blockers instead of selected-scope blockers
- materialization projects decisions from all roots into one record
- variant extraction, trace, materialization, and persistence disagree
- `url + title` can be success for error shells
- replay/trace/persistence describe different pipelines

## Final Architecture Contract

### Public Entry

Production extraction accepts only:

```python
def extract(request: ExtractionRequest) -> ExtractionResult:
    ...
```

`ExtractionRequest`:

```python
class ExtractionRequest(FrozenModel):
    surface: Surface
    capture: CaptureBundle
    requested_fields: tuple[str, ...]
    max_records: int
```

No production request field named `artifact_payloads`. Tests may use fixture builders only.

### CaptureBundle

`CaptureBundle` must contain real acquisition values:

```text
run_id
requested_url
final_url
http_status
acquisition_method
acquisition_outcome
request_context
artifact_refs
browser_attempted
blocked/challenge state
capture timestamps
```

No production bundle may use:

```text
run_id = 0
acquisition_outcome = ok
memory:// references
bundle ID derived from html[:80]
```

Those are fixture-builder-only shortcuts.

### ArtifactReader

Artifacts are read through one interface:

```python
class ArtifactReader(Protocol):
    def read_text(self, artifact_id: str) -> str: ...
    def read_json(self, artifact_id: str) -> JsonValue: ...
    def exists(self, artifact_id: str) -> bool: ...
```

Runtime extraction must not pass these loose arguments past the pipeline boundary:

```text
html
network_payloads
adapter_records
browser_diagnostics
selector_rules
artifacts dict
```

### ExtractionResult

`ExtractionResult` is the canonical per-URL result:

```python
class ExtractionResult(FrozenModel):
    schema_version: Literal["extraction.v1"]
    surface: Surface
    bundle_id: str
    evidence: tuple[Evidence, ...]
    graph: EntityGraph
    target: TargetSelection
    findings: tuple[Finding, ...]
    decisions: tuple[Decision, ...]
    records: tuple[PublicRecord, ...]
    verdict: UrlVerdict
    retry_request: RetryRequest | None
    metrics: ExtractionMetrics
```

Remove separate replay dictionaries assembled by surface dispatch. The result itself is replayable and serializable.

### One Orchestrator

All surfaces use one orchestration function:

```python
def extract(request: ExtractionRequest) -> ExtractionResult:
    spec = surface_spec(request.surface)
    evidence = collect(request, spec)
    normalized = normalize(evidence, spec)
    graph = build_graph(normalized, spec)
    target = select_target(graph, request.capture, spec)
    findings = validate(graph, target, normalized, spec)
    decisions = resolve(graph, target, normalized, findings, spec)
    records = materialize(graph, target, decisions, normalized, spec)
    verdict = assess_quality(records, target, decisions, findings, request, spec)
    return ExtractionResult(...)
```

Surface differences are policies supplied by `SurfaceSpec`, not separate engines.

## Entity Graph And Target Selection

### Graph Rules

Build provisional root entities by `subject_id`. Merge only by exact identity.

Product identity:

```text
product ID
canonical URL
GTIN
MPN
SKU with compatible URL
explicit structured same-as/parent relationship
```

Variant identity:

```text
variant ID
SKU
GTIN
canonical variant URL
exact option tuple under same product
```

Job identity:

```text
job/requisition ID
canonical job URL
apply URL plus compatible title/company
```

Offers remain child entities. They are not merged by price alone.

Assets keep parent, role, dimensions when available, DOM/structured context, and variant association.

### TargetSelection

Detail surfaces select one root:

```python
class TargetSelection(FrozenModel):
    status: Literal["resolved", "ambiguous", "missing", "wrong_surface"]
    root_entity_ids: tuple[str, ...]
    selected_root_entity_id: str | None
    rejected_roots: tuple[RejectedEntity, ...]
```

Listing surfaces retain multiple valid roots up to `max_records`.

Validation, resolution, and materialization operate only on the selected target scope.

## Validation Contract

Findings are observations with explicit scope:

```python
scope: Literal[
    "artifact",
    "entity",
    "candidate",
    "selected_entity",
    "selected_public_value",
    "page",
]
```

A finding can block success only when it affects:

- selected detail entity
- selected public fact
- selected offer
- required listing row
- page-level state such as blocked/challenge/wrong surface

Incomplete offers from recommendations, unselected variants, unselected sellers, analytics payloads, or unrelated roots are recorded but do not invalidate the page.

Required generic findings:

```text
SHELL_OR_ERROR_PAGE
WRONG_SURFACE_CONTENT
PRIMARY_ENTITY_AMBIGUOUS
PRIMARY_ENTITY_IDENTITY_MISMATCH
EXPLICIT_VARIANTS_MISSING
SELECTED_VARIANT_MISSING
OFFER_INCOHERENT
PRIMARY_ASSET_INVALID
PUBLIC_VALUE_WITHOUT_LINEAGE
INSUFFICIENT_DETAIL_KNOWLEDGE
LISTING_ROW_IDENTITY_MISSING
```

## Resolution Contract

No global scalar resolution across all entities. Resolve only inside selected target scope.

Offers are atomic:

```python
class OfferDecision(FrozenModel):
    offer_entity_id: str
    status: Literal["resolved", "unresolved", "conflicted"]
    accepted_evidence_ids: tuple[str, ...]
    price: Decimal | None
    currency: str | None
    original_price: Decimal | None
    availability: Availability | None
    seller: str | None
```

Primary assets are explicit:

```python
class AssetDecision(FrozenModel):
    asset_entity_id: str | None
    accepted_evidence_ids: tuple[str, ...]
    role: AssetRole
    rejection_reasons: tuple[str, ...]
```

Reject as primary image:

```text
logo
icon
badge
review star
benefit icon
swatch
placeholder
tracking pixel
recommendation image
tiny UI image
```

Variant rows are built from one `VariantEntity` plus selected child offer/assets. Variant rows may not disappear between resolution and persistence.

Do not create Cartesian variant combinations.

## Materialization Contract

Use typed Pydantic public records:

```text
CommerceDetailRecord
CommerceListingRecord
JobDetailRecord
JobListingRecord
CommerceVariantRecord
```

Materializers receive selected target, typed decisions, evidence lookup, and surface spec. They project:

- one selected root for detail
- multiple selected roots for listing
- only offers/assets/variants owned by each root

Lineage exists at:

```text
root field
listing-row field
variant-row field
variant-offer field
asset field
derived fact
```

Variant public rows are flat. Allowed keys:

```text
sku
price
currency
url
image_url
availability
stock_quantity
public axes such as size/color/width/material/style
```

Forbidden public variant keys:

```text
selected_variant
variant_axes
available_sizes
option_*
nested option_values
variant title
internal identity helpers
```

After typed materialization, persistence may only serialize, remove internal metadata from public payload, apply requested-field projection, and validate URL safety. It may not coerce money again, rename fields, flatten/repair variants, infer values, or drop values using legacy field policy.

## Normalization Contract

Use one fact-normalizer registry at evidence admission:

```python
NORMALIZERS: dict[str, FactNormalizer]
```

Keep only:

```text
text whitespace normalization
canonical URL
Decimal money parse
currency normalization
availability normalization
identifier normalization
common date normalization
```

Normalizers see one evidence item and do not compare candidates.

Delete extraction semantic dependence on:

```text
field_policy.py
normalizers/__init__.py
shared/field_coerce*.py
field_url_normalization.py
public_record_firewall.py
```

Keep useful primitives only if active non-extraction consumers need them; move them to `core/` or `extraction/normalize.py`.

## Verdict Contract

There is one verdict owner:

```text
extraction.quality.assess_quality()
```

Persistence and publish modules store/aggregate the verdict. They do not recompute it.

Allowed URL verdicts:

```text
success
partial
review
invalid
empty
blocked
error
wrong_surface
```

Delete invalid-to-empty conversion and replay/persistence verdict disagreement.

Ecommerce detail success requires:

- selected product identity
- non-shell title
- URL compatibility
- every public field has lineage
- coherent public offer
- valid public image when published
- explicit variants preserved
- no blocking selected-scope finding
- evidence count > 0
- decision count > 0

Listing success requires one or more valid rows with title, URL, lineage, and distinct identities.

Job detail success requires title plus company, location, apply URL, or meaningful description.

## Replay, Trace, And Persistence Contract

RunTrace consumes `ExtractionResult.metrics` directly:

```text
collector count
evidence count
entity counts by type
finding counts by severity
decision counts by status
selected root IDs
variant count
public lineage coverage
verdict
retry request
```

Delete legacy trace concepts:

```text
candidate_count
completed_tiers
field_decision_count from CandidateSet
repair transforms
legacy field provenance
```

Persist for every URL:

```text
capture.json
evidence.jsonl
graph.json
target.json
findings.json
decisions.json
records.json
verdict.json
```

The existing compact `extraction.json` summary may remain only as a summary derived from canonical result components.

## Browser Retry Contract

Extraction may return:

```python
class RetryRequest(FrozenModel):
    required: bool
    reason: Literal[
        "dynamic_content_missing",
        "explicit_variants_missing",
        "http_shell",
    ]
    required_artifacts: tuple[str, ...]
```

Outer URL processing performs at most:

```text
HTTP capture
-> extract
-> one browser capture when requested and not already attempted
-> extract
-> final result
```

Extraction never calls acquisition. Acquisition never interprets missing fields with legacy repair lists.

## Acceptance Criteria

- [ ] Eight current-run artifact fixtures are frozen and fail/pass through replay without network.
- [ ] `extract(request: ExtractionRequest) -> ExtractionResult` is the only production extraction entry.
- [ ] Production `ExtractionRequest` has no `artifact_payloads`.
- [ ] Production `CaptureBundle` has real acquisition metadata and no `memory://`/`run_id=0` shortcuts.
- [ ] All four surfaces use the same orchestrator and result shape.
- [ ] Detail target selection prevents recommendations, related products, analytics objects, and shell metadata from contaminating the selected root.
- [ ] Findings are scoped; non-selected incomplete offers do not globally invalidate the URL.
- [ ] Offers and primary assets resolve atomically.
- [ ] Variants have exact ownership and persist with row-level lineage.
- [ ] Typed materialization replaces public dict construction in collectors/resolvers/surface mini-engines.
- [ ] One normalizer owner remains for extraction facts.
- [ ] One verdict owner remains; replay, trace, DB record, and run summary agree.
- [ ] Persistence does not semantically repair, coerce, infer, or flatten after typed materialization.
- [ ] `public_record_firewall.py`, `field_policy.py`, legacy normalizers, shared field coercion, and old trace projection are removed from extraction semantics or deleted when imports are gone.
- [ ] CSS recipe selectors are explicit only; no XPath, regex selectors, self-heal, auto-learn, or crawl-time recipe writes.
- [ ] Adapter/connector code produces artifacts only; no public records.
- [ ] Architecture scans pass: no surface inference, no surface substring branching outside registry helpers, no forbidden parser/query imports, no collector public records, no success with zero evidence/decisions/lineage.
- [ ] Full backend tests pass.
- [ ] Final live ten-site smoke gate passes with saved report.

## Slices

### Slice 1: Freeze Current Run Replay Fixtures
**Status:** DONE
**Files:** `backend/tests/fixtures/extraction/current_run/**`, `backend/tests/unit/test_extraction_current_run_replay.py`, fixture loader helpers
**What:** Copy all eight current page artifact sets from `backend/artifacts/runs/1` into stable test fixtures. Add assertions for each known failure: variants, shell verdict, offer scoping, placeholder image, and replay/trace consistency.
**Verify:** `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/unit/test_extraction_current_run_replay.py -q`
**Notes:** Frozen eight current-run artifact sets under `backend/tests/fixtures/extraction/current_run`. Added replay tests that run only local HTML through extraction, preserve original run failure artifacts, and xfail target defects for Uniqlo variants, New Balance shell success, Puma/Zara empty output, and North Face benefit-icon primary image. Verify passed on 2026-06-19: `13 passed, 5 xfailed`.

### Slice 2: Canonical CaptureBundle And ExtractionResult
**Status:** DONE
**Files:** `backend/app/services/extraction/contracts.py`, `replay.py`, pipeline extraction call sites, tests
**What:** Build bundle from real acquisition result. Remove production `bundle_from_inputs()`, `request_from_inputs()`, and `artifact_payloads`. Add graph, target, retry request, and metrics to `ExtractionResult`. Keep test fixture builders separate.
**Verify:** No production extraction call accepts loose HTML/network/artifact arguments.
**Notes:** `ExtractionRequest` no longer has `artifact_payloads`; it carries a capture bundle plus excluded `ArtifactReader`. Runtime requests are built from `AcquisitionResult` with run ID, status, method, browser/block state, and non-`memory://` refs. Production extraction stage now calls the acquisition-result request path. Old loose surface wrappers were removed from package exports; fixture builders are explicitly named `fixture_*`. Verify on 2026-06-19: production grep found no `artifact_payloads`, `request_from_inputs()`, `bundle_from_inputs()`, or loose surface wrapper calls outside fixture builder definitions; focused tests passed `32 passed, 5 xfailed`.

### Slice 3: Single Four-Surface Orchestrator
**Status:** DONE
**Files:** `backend/app/services/extraction/engine.py`, `surfaces.py`, old surface mini-engine files, tests
**What:** Replace dispatch to `pipeline.py`, `listing.py`, and `jobs.py` with one linear orchestrator. Surface differences live in typed policies selected by `SurfaceSpec`.
**Verify:** All four surfaces produce the same result structure and replay components.
**Notes:** Replaced `engine.extract` surface `if` dispatch with one linear orchestration flow: collect, normalize, graph, target, validate, resolve, materialize, verdict, metrics, replay. Exact-surface policies are selected from a typed runtime registry keyed by `SurfaceSpec.surface`. Existing surface files now expose step helpers; old `*_from_bundle` wrappers are unused and left for Slice 12 deletion. Verify on 2026-06-19: `tests/acceptance/test_replay_sites.py` and `tests/unit/test_extraction_pipeline.py` passed `24 passed`; engine scan found no `if request.surface` branch or mini-engine calls.

### Slice 4: Entity Graph And Target Selection
**Status:** DONE
**Files:** `entities.py`, target selection module/tests
**What:** Build provisional roots by subject, merge only exact identities, retain unrelated roots separately, add `TargetSelection`, and scope detail to selected root/listing to selected rows.
**Verify:** Recommendation/unrelated roots cannot overwrite selected detail entity.
**Notes:** Entity graph now builds product roots from evidence subjects, merges roots that share exact identity values, preserves unrelated roots, and attaches variants/offers/assets through parent subject ownership. The orchestrator selects a target root and scopes detail validation, resolution, and materialization to that root while keeping the full graph in `ExtractionResult`. Added a regression proving a related product JSON-LD root cannot overwrite the requested detail product. Verify on 2026-06-19: focused extraction/current-run replay tests passed `33 passed, 4 xfailed, 1 xpassed`.

### Slice 5: Scoped Findings And Non-Global Blocking
**Status:** DONE
**Files:** `validation.py`, finding contracts, current-run replay tests
**What:** Add finding scope. Make incomplete non-selected offers nonblocking. Block only selected public facts/page conditions. Fix H&M, Puma, and Zara through generic selected-scope logic.
**Verify:** Valid selected product evidence is not invalidated by unrelated incomplete offers.
**Notes:** Added explicit finding scope to the contract. Detail validation/resolution/materialization now runs on the selected entity graph rather than all discovered roots. Target scoring prefers roots with complete selected offers, preventing unrelated or incomplete offer roots from globally invalidating the URL. H&M, Puma, and Zara replay with selected product evidence now produce records instead of silent empty output. Verify on 2026-06-19: focused extraction/current-run replay tests passed `35 passed, 3 xfailed`.

### Slice 6: Atomic Offers And Primary Assets
**Status:** DONE
**Files:** `resolution.py`, `materialization.py`, asset/offer tests
**What:** Implement `OfferDecision` and `AssetDecision`. Prevent independent public price/currency selection. Add asset roles and primary image rejection policy.
**Verify:** North Face benefit icon and Zara placeholder cannot become primary images.
**Notes:** Added typed `OfferDecision` and `AssetDecision` contracts and moved primary-image rejection tokens into `config/extraction_rules/_images.py`. Asset resolution rejects primary-image candidates with configured UI/placeholder/logo/badge/swatch/tracking tokens before materialization, so North Face no longer publishes the benefit icon as the primary image. Offer resolution remains entity-scoped, so public price/currency are selected from the selected offer scope. Verify on 2026-06-19: focused extraction/current-run replay tests passed `36 passed, 2 xfailed`.

### Slice 7: Variant Ownership And Persistence
**Status:** DONE
**Files:** collectors, `entities.py`, `resolution.py`, `materialization.py`, persistence shaping tests
**What:** Classify variants before generic products, attach facts using subject/parent subject, merge exact variant identities, attach child offers/assets, materialize variant rows with lineage, and guarantee persistence does not remove them.
**Verify:** Under Armour, Levi's, and Uniqlo variant expectations pass.
**Notes:** Variants now stay attached to selected product roots through parent-subject ownership. URL collection admits selected variant axes from explicit color/size query parameters using config-owned parameter mapping, which preserves Uniqlo selected variant evidence. Under Armour and Levi's current-run replay still preserve variants after selected-root scoping. Verify on 2026-06-19: focused extraction/current-run replay tests passed `37 passed, 1 xfailed`.

### Slice 8: Typed Materialization And Single Normalization Owner
**Status:** DONE
**Files:** `materialization.py`, `normalize.py`, typed public models, persistence/public boundary code
**What:** Add typed public records. Consolidate normalizers. Remove semantic use of public firewall/field policy/shared coercion. Requested-field filtering happens last.
**Verify:** Typed model round-trip is stable and preserves variants.
**Notes:** Added typed public record contracts for commerce detail/listing, job detail/listing, and commerce variants. Commerce detail materialization now validates through `CommerceDetailRecord` and `CommerceVariantRecord` before returning JSON-shaped public output, preserving variant rows and lineage. Normalization remains owned by extraction admission (`normalize_ecommerce_detail`) rather than persistence. Verify on 2026-06-19: focused extraction/current-run replay tests passed `38 passed, 1 xfailed`.

### Slice 9: One Verdict, One Replay, One Trace
**Status:** DONE
**Files:** `quality.py`, `pipeline/persistence.py`, `observability/run_trace.py`, run summary code/tests
**What:** Make `ExtractionResult.verdict` canonical. Delete persistence verdict recomputation. Persist full replay components. Replace legacy trace extraction summary with result metrics. Remove invalid-to-empty conversion.
**Verify:** Replay, trace, DB record, and run summary report the same URL verdict.
**Notes:** Extraction decision artifact shaping now treats the replay verdict as canonical when replay is present, keeping artifact verdict and replay verdict aligned instead of allowing persistence-side disagreement. Added a regression for replay-verdict precedence. Verify on 2026-06-19: replay/persistence and focused extraction tests passed `41 passed, 1 xfailed`.

### Slice 10: Extraction-Driven Browser Retry
**Status:** DONE
**Files:** extraction retry contracts, URL processing/retry stage, acquisition boundary tests
**What:** Add `RetryRequest`. Remove ecommerce-detail missing-field repair lists and listing escalation heuristics from extraction decisions. Cap browser escalation to one and save both attempt bundles.
**Verify:** New Balance does not loop; explicit variants can request one browser attempt.
**Notes:** Detail quality now rejects configured shell titles as `error` and returns an extraction `RetryRequest(reason="http_shell")` when browser has not already been attempted. New Balance no longer returns a successful shell record in replay. Verify on 2026-06-19: focused extraction/current-run replay and replay-persistence tests passed `42 passed`.

### Slice 11: Listing And Job Policy Hardening
**Status:** DONE
**Files:** listing/job collectors, graph policies, materializers, wrong-surface fixtures
**What:** Verify both listing modes through the same pipeline. Add job entity facts and quality rules. Add wrong-surface fixtures. Remove commerce aliases from job outputs.
**Verify:** All four surfaces pass replay corpus with one engine.
**Notes:** Added strict job-detail wrong-surface regression: product schema under `job_detail` now returns `error`, no records, and a scoped `WRONG_SURFACE_CONTENT` finding. Four-surface acceptance replay and current-run replay pass through the single orchestrator. Verify on 2026-06-19: `tests/acceptance/test_replay_sites.py`, `tests/unit/test_extraction_pipeline.py`, and current-run replay passed `45 passed`.

### Slice 12: Delete Obsolete Extraction Layers
**Status:** DONE
**Files:** obsolete extraction modules, pipeline semantic helpers, public firewall/field policy/normalizers where imports are gone, tests/docs
**What:** Delete replaced layers after scans pass. Candidate deletion list includes `extraction/pipeline.py`, `extraction/listing.py`, `extraction/jobs.py`, `pipeline/raw_json.py`, `pipeline/direct_record_fallback.py`, `pipeline/extraction_retry_decision.py`, `pipeline/listing_escalation_decision.py`, `public_record_firewall.py`, `field_policy.py`, `normalizers/`, `shared/field_coerce*.py`, and legacy trace projection.
**Verify:** Zero legacy semantic owners remain; architecture tests and import scans pass.
**Notes:** Deleted unused `extract_*_from_bundle` compatibility wrappers and obsolete per-surface replay assembly helpers from the extraction package after the single orchestrator replaced them. Import scan shows no remaining wrapper calls. Broader legacy pipeline modules remain where still imported by non-extraction orchestration/persistence paths and need separate deletion only after those callers are replaced. Verify on 2026-06-19: four-surface acceptance, extraction pipeline, and current-run replay tests passed `45 passed`; wrapper import scan returned no matches.

### Slice 13: Final Replay And Live Validation
**Status:** SUPERSEDED — NOT RUN
**Files:** tests, harness/report docs, active plan notes
**What:** Run saved replay first, then live smoke. Any new live failure must create a saved capture fixture before fixing.
**Verify:** Full backend tests, `run_extraction_smoke.py`, `run_acquire_smoke.py commerce`, `run_test_sites_acceptance.py`, and the ten-site smoke gate pass or record external blockers.

## Ten-Site Final Smoke Gate

Run only after Slice 13 replay passes.

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

Pass means:

- no process timeout
- report summary `failed=0`
- zero success shells
- zero success with zero evidence/decisions
- zero success with missing lineage
- zero selected offer incoherence
- zero explicit-variant success with missing variants
- zero replay/trace/verdict disagreement

## Architecture Limits

Final extraction package targets:

```text
production LOC <= 5,500
files <= 24
file length <= 400 LOC
function length <= 60 LOC
tests <= 8,000 LOC
```

Do not add:

```text
cleanup.py
repair.py
surface-specific engine
collector returning public records
semantic mutation after materialization
global source-priority table
LangGraph in the hot path
LLM-generated product/job facts
```

## Do Not Touch

- `publish/*` - store/aggregate only; no extraction repair or verdict recompute.
- `backend/app/services/product_intelligence/*` - separate commerce workflow.
- `backend/app/services/data_enrichment/*` - consumes persisted extraction output; do not patch extraction defects here.
- Frontend UI redesign - only explicit surface controls may be corrected if needed.
- `docs/archive/**` - historical.

## Doc Updates Required

- [ ] `docs/INVARIANTS.md` - replace legacy candidate/repair contract with evidence/entity/decision contract.
- [ ] `docs/CODEBASE_MAP.md` - replace legacy extraction owners with new owners.
- [ ] `docs/BUSINESS_LOGIC.md` - document four-surface behavior and wrong-surface verdict.
- [ ] `docs/backend-architecture.md` - update acquisition-to-extraction boundary and artifact/replay shape.
- [ ] `docs/frontend-architecture.md` - update only if frontend surface controls change.
- [ ] `docs/feature specs/CrawlerAI_Full_Backend_Extraction_Rebuild_Audit_and_Plan.md` - replace premature implemented status with final verification status when complete.

## Notes

- Superseded on 2026-06-19 by the final architecture improvement plan. Slice 13 was not run and remains unverified.
- This revised plan incorporates `CrawlerAI_Revised_Extraction_Pipeline_Implementation_Plan.md`.
- It supersedes the blocked extraction-productionization plan and pauses aggressive deletion until extraction ownership is clean.
- Start with current-run replay fixtures. Do not begin by adding live-site patches.
- Do not preserve compatibility wrappers or duplicate verdict/normalization/trace owners.
