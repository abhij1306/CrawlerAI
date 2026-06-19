# CrawlerAI Backend Extraction Rebuild
## Full ZIP Audit and Revised Four-Mode Implementation Plan

**Audit source:** uploaded `backend(1).zip`  
**Scope:** complete backend extraction, acquisition-to-extraction boundary, parsing stack, selectors, adapters/connectors, surface handling, persistence, observability, and extraction tests  
**Architecture status:** authoritative implementation contract  
**Operating assumption:** the previous implementation is preserved elsewhere; this repository can delete obsolete code aggressively.

---

# 1. Executive decision

Rebuild extraction as one small deterministic engine serving exactly four explicit modes:

```text
ecommerce_listing
ecommerce_detail
job_listing
job_detail
```

The selected mode is supplied by the UI/API and is authoritative.

The backend must never:

- infer a mode from a URL;
- infer a mode from HTML schema;
- infer a mode from network JSON;
- switch modes after acquisition;
- use `auto` as a surface;
- treat listing/detail or commerce/jobs as fuzzy runtime classifications.

If a page does not match the selected mode, return a typed `wrong_surface` finding and an honest verdict. Do not silently run another extractor.

The new extraction path is:

```text
Explicit Surface
    + CaptureBundle
    -> one parsed document index
    -> immutable Evidence
    -> typed entity graph
    -> pure Findings
    -> deterministic Decisions
    -> one-time materialization
    -> surface-specific quality verdict
    -> replay and persistence
```

All four modes use this path.

---

# 2. Full ZIP inventory

The uploaded backend contains:

```text
598 Python files
114 test files
104,114 application LOC
75,633 test LOC
```

Extraction-related production scope identified by this audit:

```text
188 production files
47,072 production LOC
```

Extraction-related tests:

```text
55 test files
44,383 test LOC
```

Major current production areas:

| Area | Files | LOC |
|---|---:|---:|
| `app/services/extract` | 79 | 24,618 |
| `app/services/acquisition` | 42 | 14,294 |
| `app/services/adapters` | 27 | 7,223 |
| `app/services/pipeline` | 18 | 5,557 |
| `app/services/js_state` | 12 | 2,806 |
| `app/services/dom` | 6 | 2,767 |
| `app/services/extraction_v2` | 41 | 1,248 |
| `listing_extractor.py` | 1 | 734 |
| `structured_sources.py` | 1 | 643 |
| `network_payload_mapper.py` | 1 | 639 |
| `selectors_runtime.py` | 1 | 602 |
| `extract_records.py` | 1 | 544 |
| `record_extraction_stage.py` | 1 | 539 |
| `extraction_retry_decision.py` | 1 | 484 |
| `extraction_context.py` | 1 | 340 |
| `surface_resolver.py` | 1 | 292 |

The current extraction area contains at least 91 functions of 60 lines or more. Examples include:

```text
collect_structured_candidates                 336 LOC
backfill_detail_price_from_html               266 LOC
extract_records                               240 LOC
looks_like_site_shell_record                  202 LOC
repair_ecommerce_detail_record_quality        175 LOC
extract_listing_records                       170 LOC
iter_variant_choice_groups                    168 LOC
```

The test suite contains very large implementation-coupled files:

```text
test_detail_extractor_structured_sources.py   9,326 LOC
test_crawl_engine.py                          6,867 LOC
test_state_mappers.py                         2,054 LOC
test_selectolax_css_migration.py              2,775 LOC
test_normalizers.py                           1,649 LOC
test_shared_variant_logic.py                  1,125 LOC
```

This is not merely old code around a new engine. It is multiple competing extraction systems with a test suite preserving their internal behavior.

---

# 3. Current four-mode routing audit

The backend currently has three different runtime architectures:

## 3.1 `ecommerce_detail`

Routed early to `extraction_v2`.

```text
pipeline/extract_records.py
    -> extract_ecommerce_detail_v2()
```

This path is small and directionally correct, but incomplete.

## 3.2 `job_detail`

Still routed through the legacy detail system.

```text
pipeline/extract_records.py
    -> extract/detail/assembly/record_assembly.py
    -> CandidateSet
    -> tiers
    -> DOM completion
    -> cleanup/repair
```

## 3.3 `ecommerce_listing`

Still routed through the legacy listing system.

```text
pipeline/extract_records.py
    -> adapters
    -> network listing mapper
    -> listing_extractor.py
    -> candidate-set ranking
    -> integrity gate
```

## 3.4 `job_listing`

Shares the commerce listing implementation and switches behavior using checks such as:

```python
surface.startswith("job_")
"listing" in surface
```

This is not a unified architecture. It is a large conditional application.

---

# 4. Surface inference is unnecessary debt

The frontend already maps user choices deterministically:

```text
commerce + category -> ecommerce_listing
commerce + PDP      -> ecommerce_detail
jobs + category     -> job_listing
jobs + PDP          -> job_detail
```

Despite that, the backend contains:

- `surface_resolver.py` with URL and HTML schema inference;
- `config/surface_detection.py`;
- `config/surface_hints.py`;
- `AUTO_SURFACE`;
- harness `infer_surface()`;
- sitemap candidate surface inference;
- site-link discovery surface inference;
- selector surface inference;
- network-payload body surface inference;
- public-surface-to-internal-surface translation;
- tests preserving all of the above.

## Final surface contract

Create one backend enum:

```python
class Surface(str, Enum):
    ECOMMERCE_LISTING = "ecommerce_listing"
    ECOMMERCE_DETAIL = "ecommerce_detail"
    JOB_LISTING = "job_listing"
    JOB_DETAIL = "job_detail"
```

Use it in:

```text
API request schemas
database/run model boundaries
acquisition plan
capture bundle
extraction request
replay fixtures
selector recipes
public API
smoke harness
sitemap and bulk runs
```

`surface` is mandatory. No default and no `auto`.

## Wrong-mode behavior

When the user selects `job_detail` but the page contains a product:

```text
selected surface remains job_detail
finding = WRONG_SURFACE_CONTENT
verdict = invalid or review
```

The application must not reroute to ecommerce extraction.

## Mandatory deletion

Delete:

```text
app/services/surface_resolver.py
app/services/config/surface_detection.py
app/services/config/surface_hints.py
tests/unit/test_surface_resolver.py
surface inference tests in test_harness_support.py
```

Remove surface inference from:

```text
app/services/crawl/crud.py
app/services/crawl/site_link_discovery.py
app/services/crawl/sitemap_resolver.py
app/services/public_api/extraction_service.py
app/services/selectors_runtime.py
app/services/network_payload_mapper.py
backend/harness/support.py
run_acquire_smoke.py
run_extraction_smoke.py
```

Sitemaps and URL batches inherit the run’s explicit surface.

---

# 5. Parser and dependency audit

The current backend uses three HTML parsing stacks:

```text
BeautifulSoup
Selectolax/Lexbor
lxml
```

The audit found:

```text
BeautifulSoup imports:          64 files
BeautifulSoup constructor use:  47 calls
Selectolax imports:             20 files
Lexbor parser construction:     14 calls
lxml imports:                    2 files
extruct imports:                 1 file
```

`ExtractionContext` can hold all of these representations for one page:

```text
cleaned Selectolax DOM
original Selectolax DOM
cleaned BeautifulSoup DOM
original BeautifulSoup DOM
```

The cleaned DOM is mutated to remove noise, after which fallback code reparses the original DOM because useful content was removed.

This is a self-created failure mode.

## 5.1 Final HTML parser decision: keep Selectolax/Lexbor

Keep `selectolax` as the sole HTML parser in the new extraction engine.

Reasons:

- the application primarily needs CSS selection, attributes, text, ancestors, siblings, and HTML fragments;
- Lexbor is designed as a fast HTML5 parser with CSS selectors;
- listing extraction is parser-heavy, so parsing once with the fastest existing stack is valuable;
- the repository already has working Selectolax abstractions and familiarity;
- CSS is sufficient for deterministic extraction recipes;
- parser-specific usage can be isolated behind one wrapper.

## 5.2 Remove BeautifulSoup from extraction

Do not use BeautifulSoup anywhere in the new extraction package.

Delete the pattern:

```text
parse with Selectolax
convert fragment to string
parse again with BeautifulSoup
mutate tree
fall back to original tree
```

After all extraction, acquisition-readiness, adapter, and selector consumers are migrated, remove `beautifulsoup4` from the project dependencies.

## 5.3 Remove XPath and lxml

The current XPath feature creates another parse tree and requires:

```text
lxml
cssselect
BeautifulSoup
regex timeout handling
XPath policy validation
CSS-to-XPath translation
```

The new recipe system supports:

```text
CSS selector
optional attribute
text extraction
constant metadata
JSON Pointer for JSON artifacts
```

It does not support XPath.

Delete:

```text
app/services/dom/xpath_service.py
lxml dependency
cssselect dependency
XPath request/API fields
XPath selector tests
CSS-to-XPath translation
```

If XPath is ever reintroduced, it must be an isolated optional plugin and may not affect the normal path.

## 5.4 Remove extruct

The application needs targeted extraction of:

```text
JSON-LD
OpenGraph
microdata
```

Implement all three directly over the single Selectolax tree.

Do not retain a large generic metadata framework solely for these cases.

Delete:

```text
extruct dependency
extruct fallback paths in structured_sources.py
w3lib dependency used for extruct base URL handling
```

## 5.5 Remove glom and JMESPath

Current use:

```text
glom:      four JS-state configuration/normalizer files
JMESPath:  two JS-state/network mapper files
```

These expression engines hide behavior in string expressions and create a second mapping language beside Python.

Replace them with:

```text
one recursive JSON object walker
NodeContext
typed object classifiers
JSON Pointer locators
plain Python connector mappings
```

Delete:

```text
glom
jmespath
js_state_field_specs.py
state_normalizer expression specifications
network payload JMESPath specifications
```

Do not replace them with another query language.

## 5.6 Other dependency decisions

| Dependency | Decision | Reason |
|---|---|---|
| `selectolax` | Keep | Sole HTML parser |
| `pydantic` | Keep | Typed immutable contracts |
| `httpx` | Keep | APIs, connectors, internal HTTP |
| `curl-cffi` | Keep | External page HTTP/TLS impersonation |
| `patchright` | Keep | Sole browser runtime |
| `defusedxml` | Keep | Safe sitemap/XML parsing |
| `regex` | Remove from extraction | User regex selectors are removed; built-in patterns use `re` |
| `beautifulsoup4` | Remove | Duplicate parser |
| `lxml` | Remove | XPath removed |
| `cssselect` | Remove | XPath/CSS translation removed |
| `extruct` | Remove | Targeted collectors replace it |
| `w3lib` | Remove | Use `urllib.parse` canonicalization |
| `glom` | Remove | Replace with typed object walking |
| `jmespath` | Remove | Replace with typed object walking |
| `jsonschema` | Remove | Unused; Pydantic owns validation |
| `price-parser` | Remove | Unused; use Decimal-based money parser |
| `dateparser` | Remove | Unused; implement tested ISO/common job-date parsing |
| `aiohttp` | Remove | Used by one adapter; convert it to `httpx` |
| `urllib3` | Remove direct dependency | Unused directly |
| `idna` | Remove direct dependency | Let HTTP stack own it |
| `psutil` | Remove unless a new direct use is proven | No direct import found |

Some non-extraction framework dependencies may be dynamically required by FastAPI, SQLAlchemy, or deployment and are outside this deletion decision.

---

# 6. New unified architecture

Do not maintain a package named `v2` after migration.

Rename/refactor it into:

```text
app/services/extraction/
```

Target layout:

```text
app/services/extraction/
    __init__.py
    contracts.py
    surfaces.py
    engine.py
    capture.py
    documents.py
    json_walk.py
    normalize.py
    replay.py
    quality.py

    collectors/
        structured.py
        state.py
        dom_detail.py
        dom_listing.py
        recipes.py

    graph/
        build.py
        commerce.py
        jobs.py

    resolve/
        common.py
        commerce.py
        jobs.py

    materialize/
        commerce.py
        jobs.py
```

Target:

```text
<= 28 production files
<= 7,500 production LOC
target 5,500–6,500 LOC
maximum file length 400 LOC
maximum function length 60 LOC
```

The current V2 package has 41 files for 1,248 LOC, including many 3–20 line modules. Consolidate related contracts and behavior rather than reproducing this fragmentation.

---

# 7. One explicit surface registry

`surfaces.py` is the only place allowed to describe mode differences.

```python
@dataclass(frozen=True)
class SurfaceSpec:
    surface: Surface
    domain: Literal["commerce", "jobs"]
    cardinality: Literal["one", "many"]
    root_entity: Literal["product", "job"]
    required_facts: frozenset[str]
    allowed_facts: frozenset[str]
    supports_variants: bool
    supports_traversal: bool
```

Required specifications:

## Ecommerce detail

```text
cardinality: one
root entity: product
children: variants, offers, assets
required: product.url, product.title
variants: supported
traversal: no
```

## Ecommerce listing

```text
cardinality: many
root entity: product
children: offer, asset
required per row: product.url, product.title
variants: no
traversal: yes
```

## Job detail

```text
cardinality: one
root entity: job
required: job.title
recommended: company, location, apply_url or description
variants: no
traversal: no
```

## Job listing

```text
cardinality: many
root entity: job
required per row: job.url, job.title
variants: no
traversal: yes
```

No other module may use:

```python
surface.startswith("job_")
"listing" in surface
"detail" in surface
```

Add an AST architecture test enforcing this.

---

# 8. Capture and document model

## 8.1 CaptureBundle

Production extraction accepts only:

```python
extract(request: ExtractionRequest) -> ExtractionResult
```

`ExtractionRequest` contains:

```text
explicit Surface
CaptureBundle
requested fields
max records
```

`CaptureBundle` contains:

```text
requested URL
final URL
actual acquisition outcome
HTTP status/method
request context
HTTP HTML artifact
rendered HTML artifact when present
script-state artifacts
network JSON artifacts
connector JSON artifacts
browser diagnostics
```

No loose arguments such as:

```text
html
network_payloads
artifacts dict
adapter_records
browser_diagnostics
```

## 8.2 DocumentStore

Implement one lazy store per bundle:

```python
class DocumentStore:
    def html(self, artifact_id) -> HtmlDocument
    def json(self, artifact_id) -> JsonDocument
    def text(self, artifact_id) -> str
```

Each HTML artifact is parsed at most once.

## 8.3 HtmlDocument

Only `documents.py` imports Selectolax.

Expose a small wrapper:

```text
css()
css_first()
text()
attribute()
ancestors()
siblings()
html()
stable_locator()
is_hidden()
```

Collectors do not import Selectolax directly.

## 8.4 No cleaned DOM

Never delete nodes from the parsed tree.

Noise is handled through:

```text
scope selection
negative context flags
visibility checks
entity ownership
asset role
validator findings
```

There is no original/cleaned DOM fallback because there is no destructive cleaned DOM.

---

# 9. Unified evidence model

Evidence must support every mode.

```python
class Evidence(FrozenModel):
    evidence_id: str
    surface: Surface
    artifact_id: str
    collector_id: str
    collector_version: str

    subject_id: str
    parent_subject_id: str | None
    group_id: str | None

    entity_kind: Literal[
        "product",
        "variant",
        "offer",
        "asset",
        "job",
    ]
    fact_type: str

    raw_value: JsonValue
    value: JsonValue
    locator: SourceLocator
    directness: Literal["direct", "embedded", "inferred"]
    confidence: float
    flags: tuple[str, ...]
```

`subject_id` is mandatory.

Every fact from one source object or DOM card shares the same subject.

This fixes the current problem where SKU, options, offer, and image from one variant can split into separate entities.

---

# 10. Controlled fact vocabulary

## Commerce

```text
product.url
product.title
product.brand
product.description
product.category
product.sku
product.mpn
product.gtin
product.material
product.color
product.size

variant.id
variant.url
variant.sku
variant.gtin
variant.selected
variant.option.*

offer.price
offer.currency
offer.original_price
offer.availability
offer.stock_quantity
offer.seller

asset.url
asset.role
```

## Jobs

```text
job.url
job.title
job.id
job.company
job.location
job.salary
job.type
job.posted_date
job.apply_url
job.description
job.requirements
job.responsibilities
job.qualifications
job.benefits
job.skills
job.remote
job.department
```

Unknown arbitrary aliases are not promoted into public fields.

Custom user-requested facts use:

```text
custom.<normalized_name>
```

and must come from an explicit recipe.

---

# 11. Collector architecture

All collectors emit evidence only.

## 11.1 Structured collector

One collector handles:

```text
JSON-LD Product
JSON-LD ProductGroup
JSON-LD Offer/AggregateOffer
JSON-LD JobPosting
JSON-LD ItemList/ListItem
OpenGraph
microdata
```

The explicit surface controls which schema types are admissible. It does not infer the surface.

## 11.2 JSON object walker

Replace glom/JMESPath with:

```python
walk_json(value) -> Iterator[JsonNode]
```

`JsonNode` includes:

```text
JSON Pointer
parent key
array index
ancestor keys
ancestor schema types
value
```

Classify each object before emitting facts:

```text
offer
variant
product group
product
job
asset
unknown
```

## 11.3 Script-state collector

Harvest embedded states directly from script tags:

```text
__NEXT_DATA__
Nuxt payload
Redux/Apollo state
known global JSON assignments
application/json script blocks
```

Parsing is artifact collection, not record mapping.

## 11.4 Network collector

Network response bodies are JSON artifacts.

Run the same object walker and classifiers used for script state.

There is no separate network payload mapper and no body-based surface inference.

## 11.5 Detail DOM collector

Uses the explicit surface specification.

Commerce detail:

```text
primary product root
title
commerce identifiers
offer container
gallery assets
variant controls
specification sections
```

Job detail:

```text
primary job root
title
company
location
apply action
description
section headings
```

## 11.6 Listing DOM collector

Uses repeated structural groups.

Algorithm:

1. collect candidate destination links;
2. identify repeated ancestor/card signatures;
3. assign one subject per card;
4. emit title, URL, offer/salary, image/company/location facts;
5. deduplicate by exact identity;
6. never build final dictionaries inside the collector.

Commerce and jobs use separate field vocabularies but the same card grouping engine.

## 11.7 Recipe collector

Support only declarative CSS recipes:

```python
class CssFieldRule:
    surface: Surface
    scope_selector: str | None
    selector: str
    output_fact: str
    source: Literal["text", "attribute"]
    attribute: str | None
```

Delete runtime XPath and regex selector support.

Delete automatic selector saving and self-healing from the crawl hot path.

A user may explicitly save a CSS recipe. Offline recipe suggestion can be added later.

---

# 12. Entity graph for all modes

Use one small generic entity contract:

```python
class EntityNode(FrozenModel):
    entity_id: str
    kind: EntityKind
    parent_entity_id: str | None
    subject_ids: tuple[str, ...]
    fact_evidence: dict[str, tuple[str, ...]]
```

## Commerce detail graph

```text
Product
  -> Variant*
  -> Offer*
  -> Asset*
```

## Commerce listing graph

```text
Product*
  -> Offer?
  -> Asset?
```

## Job detail graph

```text
Job
```

Job fields can remain facts on the job entity. Do not create organization/location subgraphs until a real requirement requires them.

## Job listing graph

```text
Job*
```

This keeps jobs simpler than commerce and avoids unnecessary generic graph complexity.

---

# 13. Entity building rules

## Product identity

Merge only through:

```text
exact product ID
exact canonical URL
exact SKU/GTIN/MPN with compatible URL
explicit structured relationship
```

## Variant identity

Merge only through:

```text
exact variant ID
exact SKU
exact GTIN
exact canonical variant URL
exact option tuple within one product
```

## Job identity

Merge only through:

```text
exact job ID/requisition ID
exact canonical job URL
exact apply URL plus compatible title/company
```

## Listing entities

Do not choose one primary entity. Retain all valid root entities up to `max_records`.

## Detail entities

Select one primary entity by:

```text
requested/final URL
mainEntity
DOM primary root
selected variant parent
identity compatibility
completeness
```

Do not merge recommendations into the primary entity.

---

# 14. Resolution and materialization

## 14.1 Resolution

Resolution happens per entity and fact.

Order:

```text
exact entity ownership
same request context
same subject/group
direct over inferred
no blocking finding
fact-specific reliability
confidence
stable evidence ID
```

Do not use one global source ranking table.

## 14.2 Commerce offers are atomic

Choose one coherent offer group.

Do not resolve price and currency independently.

## 14.3 Primary asset

Choose one primary asset using explicit role and context.

Reject:

```text
logo
icon
review star
badge
swatch
placeholder
tracking pixel
recommendation image
tiny UI asset
```

## 14.4 Materialization

Use four typed Pydantic public models:

```text
CommerceDetailRecord
CommerceListingRecord
JobDetailRecord
JobListingRecord
```

Requested-field filtering happens only after a complete typed record is materialized.

No collector or resolver creates public dictionaries.

---

# 15. Quality verdicts

Common page verdicts:

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

## Ecommerce detail success

Requires:

```text
one primary product
compatible URL/title identity
all published fields have lineage
coherent offer if price is published
valid primary asset if image is published
explicit variant evidence is not lost
no blocking finding
```

## Ecommerce listing success

Requires:

```text
at least one valid product row
every row has URL and title
row identities are distinct
no promo-only/recommendation cluster
```

## Job detail success

Requires:

```text
one primary job
valid title
company, apply URL, location, or meaningful description support
no error shell
```

## Job listing success

Requires:

```text
at least one distinct job row
every row has title and URL
no navigation-only cluster
```

Wrong content does not trigger another surface.

---

# 16. Acquisition architecture

Do not use LangGraph.

Use one bounded deterministic state machine:

```text
HTTP fetch
    -> CaptureBundle
    -> extract with selected surface
    -> RetryRequest?
        -> browser once
        -> new CaptureBundle
        -> extract again
    -> final result
```

## Keep low-level infrastructure

Keep, after interface cleanup:

```text
browser pool
browser page lifecycle
cookie store
rate limiter
host protection memory
proxy configuration
route blocking
storage-state handling
URL safety
```

## Rewrite/consolidate orchestration

Current acquisition has 42 files and 14,294 LOC. Consolidate overlapping orchestration responsibilities:

```text
acquirer
runtime
browser detail
browser page flow
browser result builder
browser recovery
stage runner
traversal recovery
readiness routing
```

Target acquisition orchestration:

```text
acquisition/engine.py
acquisition/http.py
acquisition/browser.py
acquisition/traversal.py
acquisition/contracts.py
acquisition/capture.py
```

Low-level browser pool/security files can remain separate.

## Explicit surface behavior

```text
listing surfaces may traverse when UI requests it
detail surfaces do not traverse
commerce readiness looks for product evidence
job readiness looks for job evidence
```

This is mode-specific validation, not surface detection.

---

# 17. Adapter replacement

Current adapters total 7,223 LOC and frequently return final records.

Replace `Adapter` with `Connector`.

```python
class Connector(Protocol):
    name: str

    async def supports(self, url: str, surface: Surface) -> bool:
        ...

    async def acquire_artifacts(
        self,
        request: ConnectorRequest,
    ) -> tuple[ArtifactRef, ...]:
        ...
```

Connectors may:

```text
call public platform endpoints
capture structured JSON
normalize transport metadata
```

Connectors may not:

```text
return final records
bypass evidence
select field winners
infer the surface
```

Likely valuable connector families:

```text
Shopify
Workday
Greenhouse
iCIMS
Oracle HCM
ADP
Jibe
Bullhorn
Paycom/UKG
Algolia/Firestore jobs
```

Commerce site-specific connectors remain only if replay fixtures prove unique artifact value.

For every existing adapter:

```text
unique fixture benefit -> convert to connector
no unique benefit      -> delete
```

Convert the single `aiohttp` adapter to `httpx`, then remove `aiohttp`.

---

# 18. Field-policy and normalization cleanup

Current code distributes field behavior across:

```text
field_mappings.py
field_mappings.exports.json
extraction_rules exports
field_policy.py
shared/field_coerce*.py
normalizers/__init__.py
public_record_firewall.py
confidence.py
surface-specific cleanup modules
```

Replace this with:

```text
SurfaceSpec allowed facts
FactNormalizer registry
typed public record schemas
surface quality policy
```

Keep tiny reusable primitives only:

```text
clean_text
canonical_url
parse_decimal_money
normalize_currency
normalize_availability
normalize_date
normalize_identifier
```

Do not keep a generic `coerce_field_value(field_name, value, page_url)` dispatcher.

Do not infer brand from hostname or product type from URL inside normalization.

---

# 19. Configuration cleanup

Current extraction configuration includes approximately 12,115 lines across Python and exported JSON, including a 134 KB extraction-rules export.

Delete configuration that encodes code paths and heuristic tables.

Keep configuration only for operational values:

```text
timeouts
artifact size limits
maximum records
maximum variants
maximum network bodies
browser budgets
```

Business logic belongs in small typed surface modules and validators.

Delete:

```text
dynamic locals().update() export loading
wildcard extraction-rule imports
duplicated Python + JSON rule ownership
source-priority tables
repair tables
surface-detection token lists
```

---

# 20. Revised implementation sequence

Execute in this exact order.

## Step 1 — Make surface explicit everywhere

- add `Surface` enum;
- make API schemas require it;
- reject `auto`;
- remove surface resolution and inference;
- update harness/sitemap/public API;
- add `WRONG_SURFACE_CONTENT`.

**Gate:** zero calls to `infer_surface`, `resolve_auto_surface`, or `AUTO_SURFACE`.

---

## Step 2 — Establish one parser/document layer

- create `extraction/documents.py`;
- wrap Selectolax;
- create JSON document/walker;
- parse each artifact once;
- no DOM mutation;
- no BeautifulSoup in new extraction.

**Gate:** only `documents.py` imports Selectolax within extraction.

---

## Step 3 — Rename and consolidate V2 into the unified engine

- rename `extraction_v2` to `extraction`;
- reduce 41 files to the target structure;
- add explicit `SurfaceSpec`;
- generalize Evidence with `surface`, `subject_id`, `parent_subject_id`;
- replace loose input parameters with `ExtractionRequest`.

**Gate:** ecommerce detail still runs only through the unified engine.

---

## Step 4 — Finish ecommerce detail correctly

Implement:

```text
Product/ProductGroup
variant classification
subject-based linking
atomic offers
asset role and primary selection
explicit variant expectation
strict quality
```

Use current output failures as replay fixtures.

**Gate:** no configurable product succeeds with missing explicit variants.

Immediately delete ecommerce-detail legacy modules and tests that no longer serve another mode.

---

## Step 5 — Migrate job detail

Add:

```text
JobPosting structured collector
job script/network classifier
job detail DOM collector
job entity resolver
job detail materializer and quality
```

Cut `job_detail` to the unified engine.

Delete the remaining legacy detail assembly and job-detail tests.

**Gate:** both detail modes use the same engine and no `extract/detail` runtime remains.

---

## Step 6 — Migrate ecommerce listing

Implement listing root/card grouping and commerce listing resolution.

Do not reuse `listing_extractor.py` by wrapping it. Rebuild its outcomes as evidence/entity logic.

Cut over and delete commerce listing candidate ranking/overlay/integrity code that no longer serves jobs.

**Gate:** commerce listing returns typed product entities with lineage.

---

## Step 7 — Migrate job listing

Reuse the shared card grouping engine with the job fact vocabulary.

Cut over and delete:

```text
listing_extractor.py
extract/listing_*.py
structured_listing_handler.py
network_listing_mapper.py
```

**Gate:** all four modes call `extraction.engine.extract()`.

---

## Step 8 — Convert or delete adapters

- convert platform APIs to connectors;
- feed connector JSON through collectors;
- delete direct-record adapter output;
- delete connectors without fixture-proven unique value;
- remove `aiohttp`.

**Gate:** no connector returns a public record.

---

## Step 9 — Replace selector system with CSS recipes

- retain explicit user-saved CSS rules only;
- migrate DB/API to `CssFieldRule`;
- delete XPath, regex selectors, auto-learn, self-heal, and LLM selector generation;
- run recipes as an evidence collector.

**Gate:** no crawl writes or changes selector recipes automatically.

---

## Step 10 — Simplify acquisition orchestration

- implement the bounded HTTP/browser state machine;
- consume `RetryRequest` from extraction;
- remove duplicated retry/readiness orchestration;
- keep low-level browser pool and security.

**Gate:** maximum one browser escalation per URL.

---

## Step 11 — Unify replay, persistence, and trace

Persist for all four modes:

```text
capture.json
evidence.jsonl
entities.json
findings.json
decisions.json
records.json
verdict.json
```

RunTrace reads the new result directly.

**Gate:** no success with zero evidence, zero decisions, or missing lineage.

---

## Step 12 — Replace the extraction test suite

Create:

```text
tests/extraction/unit/
tests/extraction/property/
tests/extraction/replay/
tests/extraction/integration/
```

Delete implementation-coupled legacy tests.

**Gate:** extraction tests <= 15,000 LOC.

---

## Step 13 — Aggressive deletion

Delete all obsolete extraction owners:

```text
app/services/extract/**
app/services/extraction_v2/**
app/services/listing_extractor.py
app/services/extraction_context.py
app/services/network_payload_mapper.py
app/services/structured_sources.py
app/services/js_state/**
app/services/dom/**
app/services/surface_resolver.py
app/services/selectors_runtime.py
app/services/selector_auto_learn.py
app/services/selector_self_heal.py
app/services/selector_suggestions.py
```

Delete old field policy/coercion modules after their remaining non-extraction consumers move to small primitives.

Remove unreachable branches from pipeline files.

---

## Step 14 — Remove dependencies and stale configuration

Remove final unused dependencies and config exports.

Run:

```text
ruff
mypy
vulture
dependency import scan
AST architecture tests
full unit/component suite
replay corpus
live smoke separately
```

---

# 21. New testing strategy

## Unit tests

Test public owners:

```text
document wrapper
JSON walker
collectors
entity linking
normalizers
resolvers
materializers
quality
```

## Property tests

Required:

```text
evidence order independence
duplicate evidence independence
unrelated entity isolation
offer context isolation
listing row order determinism
no invented variants
every public value has lineage
wrong surface never switches engine
```

## Replay tests

Minimum fixture groups:

```text
commerce detail
commerce listing
job detail
job listing
blocked/error
client rendered
network first
wrong surface
cross-sell/recommendation
variant-heavy
```

## Integration tests

```text
explicit surface API
HTTP -> browser retry
connector artifacts
persistence
trace
bulk/sitemap explicit surface propagation
CSS recipe collection
```

Tests must target public contracts and fixture outcomes, not private helper functions.

---

# 22. Stale-test deletion rules

Delete a test when it:

- imports a deleted extraction module;
- asserts `CandidateSet`;
- asserts cleanup/repair ordering;
- asserts source-priority behavior;
- asserts surface inference;
- asserts XPath or regex selector behavior;
- asserts adapter final records;
- tests a private helper already covered by replay/property tests;
- passes while the active engine is broken;
- exceeds 1,000 LOC and can be represented by fixture cases.

Large mixed files must be split; do not retain unrelated legacy sections.

---

# 23. Architecture enforcement tests

CI must fail if:

```text
surface inference is added
an extraction module imports BeautifulSoup
an extraction module imports lxml/extruct/glom/jmespath
XPath appears in the extraction API
a collector returns a public record
a materializer imports a collector
a validator mutates evidence/entities
a cleanup.py or repair.py is added
surface string prefix/substring branching appears outside surfaces.py
a connector returns records
a public value lacks lineage
a success result has zero evidence or decisions
```

---

# 24. Final size and dependency gates

## Production

```text
unified extraction engine: <= 7,500 LOC
target:                    5,500–6,500 LOC
engine files:              <= 28
connector code:            <= 4,000 LOC
extraction pipeline glue:  <= 1,500 LOC
```

Total extraction-related production target:

```text
<= 13,000 LOC
```

Current audited scope:

```text
47,072 LOC
```

Required reduction:

```text
at least 70%
```

## Tests

```text
new extraction tests <= 15,000 LOC
```

Current audited extraction-related tests:

```text
44,383 LOC
```

Required reduction:

```text
at least 65%
```

---

# 25. Immediate first execution slice

The first implementation slice should contain only:

1. `Surface` enum and explicit API validation.
2. Deletion of all surface inference.
3. `DocumentStore` with one Selectolax parse per HTML artifact.
4. `JsonWalker` with JSON Pointer paths.
5. Rename `extraction_v2` to `extraction`.
6. Generalize the engine contract to all four surfaces.
7. Architecture tests preventing BeautifulSoup/query-language imports and surface inference.

Do not add more extraction heuristics in this slice.

---

# 26. Codex execution directive

Use this exact instruction:

> Treat the uploaded backend audit plan as the architecture contract. Rebuild extraction as one deterministic engine for exactly four explicit surfaces: ecommerce_listing, ecommerce_detail, job_listing, and job_detail. Delete all URL/HTML/network surface inference and reject auto surfaces. Keep Selectolax/Lexbor as the sole HTML parser behind one DocumentStore wrapper; remove BeautifulSoup, XPath/lxml/cssselect, extruct, glom, JMESPath, and duplicated DOM representations from extraction. All collectors emit immutable evidence with subject and parent-subject IDs. All four modes build entities, validate, resolve, materialize once, and produce replayable lineage. Convert adapters to artifact connectors or delete them. Replace selector self-healing with explicit CSS-only recipes. Use a bounded HTTP-to-browser state machine, not LangGraph. Cut over one surface at a time and immediately delete its old runtime and tests. Final gates are all four surfaces on one engine, zero legacy extraction imports, at least 70% production LOC reduction, at least 65% extraction-test LOC reduction, no success without evidence/decisions/lineage, and no inferred or switched surface.

---

# 27. Definition of done

The rebuild is complete only when:

- the UI/API supplies one of four exact surfaces;
- the backend never categorizes the surface;
- all four surfaces run through one extraction engine;
- each HTML artifact is parsed once;
- Selectolax is the only extraction HTML parser;
- no XPath, extruct, glom, or JMESPath remains;
- no mutable record exists before materialization;
- listings and details share evidence/entity/resolution contracts;
- commerce variants and offers remain coherent;
- jobs use typed job facts, not commerce aliases;
- connectors produce artifacts, not records;
- selectors are CSS-only explicit recipes;
- all public values have lineage;
- all runs are replayable offline;
- legacy extraction code and stale tests are deleted;
- production and test LOC reduction gates pass.
