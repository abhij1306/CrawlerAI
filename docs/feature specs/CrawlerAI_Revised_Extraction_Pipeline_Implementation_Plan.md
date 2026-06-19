# CrawlerAI Revised Extraction Pipeline Implementation Plan

**Audit source:** uploaded `backend(2).zip` and `backend/artifacts/runs/1`  
**Plan reviewed:** agent-created `docs/plans/full-backend-extraction-rebuild-plan.md`  
**Status:** replacement plan  
**Objective:** finish the new four-surface extraction architecture, remove duplicate decision owners, and make the latest run replayable and trustworthy.

---

## 1. Decision on the agent plan

The agent plan has the correct target direction, but it should not be executed as written.

It is stale in three ways:

1. It marks foundational work as TODO even though the code already has:
   - an explicit four-value `Surface` enum;
   - the new `app/services/extraction/` package;
   - a Selectolax-backed document wrapper;
   - removal of surface inference and several old dependencies;
   - all four surfaces routed through `extraction.engine.extract()`.

2. It postpones the latest-run failures until the final slice. The current eight page artifacts must become the first replay corpus because they reveal architectural defects that affect every later step.

3. It does not explicitly eliminate the multiple competing owners of:
   - verdict;
   - normalization;
   - persistence shaping;
   - extraction trace;
   - public-record validation.

The revised plan starts from the code that exists now and addresses the actual failures in the current run before further feature expansion.

---

# 2. Current implementation status

## Already completed and retained

Keep these implemented decisions:

- exactly four explicit surfaces:
  - `ecommerce_listing`
  - `ecommerce_detail`
  - `job_listing`
  - `job_detail`
- no URL/HTML/network surface categorization;
- `app/services/extraction/` as the new package;
- Selectolax isolated through `documents.py`;
- immutable Pydantic evidence contracts;
- evidence with `subject_id` and `parent_subject_id`;
- removal of glom, JMESPath, extruct, lxml, cssselect, aiohttp, dateparser, price-parser, jsonschema, and w3lib;
- CSS-only recipe direction;
- one top-level `extract(request)` entry point.

These should not be reimplemented.

## Incomplete or incorrect

The current package still has four mini-engines:

```text
engine.py
  -> pipeline.extract_ecommerce_detail()
  -> listing.extract_ecommerce_listing()
  -> jobs.extract_job_detail()
  -> jobs.extract_job_listing()
```

The ecommerce detail path still accepts loose arguments and rebuilds a memory bundle:

```text
html
page_url
network_payloads
artifacts dict
requested_page_url
```

The listing and job paths do not yet use the same evidence/entity/decision pipeline as ecommerce detail.

The new architecture therefore exists in name, but not yet as one implementation.

---

# 3. Findings from the latest run

The current run contains eight ecommerce-detail pages.

| Site | Replay evidence | Replay decisions | Replay findings | Replay verdict | Persisted verdict | Critical result |
|---|---:|---:|---:|---|---|---|
| Under Armour | 812 | 460 | 0 | success | success | Trace sees 69 variants; persisted record has none |
| H&M | 971 | 201 | 13 | invalid | empty | Large usable page blocked by irrelevant incomplete offers |
| Levi’s | 29 | 18 | 0 | success | success | Trace sees one variant; persisted record has none |
| Uniqlo | 1,121 | 304 | 0 | success | success | Configurable page succeeds with zero variants |
| New Balance | 3 | 2 | 0 | success | success | 628-byte shell titled “Oops! Something went wrong” |
| Puma | 374 | 114 | 13 | invalid | empty | Product evidence exists but page is globally blocked |
| Zara | 1,435 | 105 | 19 | invalid | empty | Product evidence exists but page is globally blocked |
| North Face | 40 | 33 | 0 | success | success | Benefit icon selected as primary image; no variants |

This run proves five systemic defects:

1. **Findings are globally blocking.**  
   Every incomplete offer across recommendations, stale state, or unrelated objects can invalidate the page.

2. **Materialization is not scoped to a selected entity.**  
   Decisions from all products, offers, and assets are projected into one root record.

3. **Variant extraction and persistence disagree.**  
   Trace data can show variants while the persisted public record loses them.

4. **Quality is too weak.**  
   URL + title can become success even for a 628-byte error shell.

5. **Persistence and observability describe a different pipeline.**  
   Replay reports hundreds of evidence items and decisions while RunTrace reports zero candidates and zero field decisions.

---

# 4. Final extraction architecture

The production flow must be exactly:

```text
ExtractionRequest
    |
    v
CaptureBundle + ArtifactReader
    |
    v
collect Evidence
    |
    v
normalize Evidence once
    |
    v
build EntityGraph
    |
    v
select target root entity/entities
    |
    v
validate target scope and candidate facts
    |
    v
resolve typed Decisions
    |
    v
materialize typed records once
    |
    v
compute one quality verdict
    |
    v
persist one canonical ExtractionResult
```

There is one orchestration function for all surfaces:

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

Surface differences are data/policies supplied through `SurfaceSpec`, not separate engines.

---

# 5. Required contract changes

## 5.1 ExtractionRequest

Production extraction accepts only:

```python
class ExtractionRequest(FrozenModel):
    surface: Surface
    capture: CaptureBundle
    requested_fields: tuple[str, ...]
    max_records: int
```

Delete `artifact_payloads` from the request.

Artifacts are read through:

```python
class ArtifactReader(Protocol):
    def read_text(self, artifact_id: str) -> str
    def read_json(self, artifact_id: str) -> JsonValue
    def exists(self, artifact_id: str) -> bool
```

## 5.2 CaptureBundle

Must contain real acquisition values:

```text
run_id
requested URL
final URL
HTTP status
acquisition method
acquisition outcome
request context
artifact references
browser attempted
blocked/challenge state
capture timestamps
```

No production bundle may use:

```text
run_id = 0
acquisition_outcome = "ok"
memory:// references
bundle ID based on html[:80]
```

Those may exist only in a test fixture builder.

## 5.3 ExtractionResult

Make it the canonical per-URL result:

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

Remove separate replay dictionaries assembled in `engine.py`.

The result itself is replayable and serializable.

---

# 6. Entity and target selection redesign

## 6.1 Current defect

`build_entities()` currently merges all `product.*` evidence into one `ProductEntity`.

This allows:

```text
main product
recommendations
related products
analytics product objects
review widgets
page-shell metadata
```

to contaminate one product.

## 6.2 Required graph

Create provisional entities by source `subject_id`.

Merge provisional entities only by exact identity:

### Product

```text
product ID
canonical URL
GTIN
MPN
SKU with compatible URL
explicit structured same-as/parent relationship
```

### Variant

```text
variant ID
SKU
GTIN
canonical variant URL
exact option tuple under the same product
```

### Job

```text
job/requisition ID
canonical job URL
apply URL plus compatible title/company
```

### Offer

Offers remain child entities and are not merged by price alone.

### Asset

Assets keep:

```text
parent subject/entity
role
dimensions if available
DOM/structured context
variant association
```

## 6.3 TargetSelection

Detail surfaces select one root:

```python
class TargetSelection(FrozenModel):
    status: Literal["resolved", "ambiguous", "missing", "wrong_surface"]
    root_entity_ids: tuple[str, ...]
    selected_root_entity_id: str | None
    rejected_roots: tuple[RejectedEntity, ...]
```

Listing surfaces retain multiple valid root entities up to `max_records`.

Validation and materialization operate only on the selected target scope.

---

# 7. Validation redesign

## 7.1 Findings are observations, not global page blockers

A finding must include:

```text
entity IDs
evidence IDs
fact types
scope
severity
blocking policy
```

Required scope:

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

## 7.2 Blocking rule

A finding can block success only when it affects:

- the selected detail entity;
- a selected public fact;
- a selected offer;
- a required listing row;
- the page itself, such as blocked/challenge/wrong surface.

An incomplete offer belonging to:

```text
recommendation
unselected variant
unselected seller
analytics payload
unrelated product
```

does not invalidate the page.

## 7.3 Fix for H&M, Puma, and Zara

Change offer validation from:

```text
validate every offer
mark PRICE_WITHOUT_CURRENCY blocking globally
```

to:

```text
record incompleteness on every offer
select candidate offer groups
block only if the chosen/public offer is incoherent
```

The resolver may reject an incomplete offer while accepting another coherent offer.

## 7.4 Required quality findings

Implement generic rules:

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

---

# 8. Resolution redesign

## 8.1 No global scalar resolution across all entities

Resolve facts only inside the selected entity scope.

## 8.2 Atomic offer decisions

Replace independent `offer.price` and `offer.currency` decisions with:

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

One offer group wins as a unit.

## 8.3 Primary asset decision

Add:

```python
class AssetDecision(FrozenModel):
    asset_entity_id: str | None
    accepted_evidence_ids: tuple[str, ...]
    role: AssetRole
    rejection_reasons: tuple[str, ...]
```

Reject from primary selection:

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

This directly fixes North Face and similar outputs.

## 8.4 Variant decisions

A public variant row is built from one `VariantEntity` and its selected child offer/assets.

Variant rows may not disappear between resolution and persistence.

Required variant facts:

```text
SKU or variant ID or exact option tuple
option axes
selected state
variant URL when available
coherent variant offer when available
variant image when available
```

Do not create Cartesian combinations.

---

# 9. Materialization redesign

## 9.1 Typed records

Use Pydantic models:

```text
CommerceDetailRecord
CommerceListingRecord
JobDetailRecord
JobListingRecord
CommerceVariantRecord
```

## 9.2 Materialize selected scope only

The current materializer loops over every decision and repeatedly writes root fields. Delete this design.

Materializers receive:

```text
selected target
typed decisions
evidence lookup
surface specification
```

They project:

```text
one selected root for detail
multiple selected roots for listing
only offers/assets/variants owned by each root
```

## 9.3 Lineage

Lineage must exist at:

```text
root field
listing-row field
variant-row field
variant-offer field
asset field
derived fact
```

## 9.4 No semantic firewall after materialization

Delete semantic use of `public_record_firewall`.

After typed materialization, persistence may only:

```text
serialize
remove internal metadata from public payload
apply requested-field projection
validate URL safety
```

It may not:

```text
coerce money again
rename fields
route barcode to SKU
flatten/repair variants
infer values
drop values using legacy field policy
```

---

# 10. Normalization redesign

Use one fact-normalizer registry at evidence admission:

```python
NORMALIZERS: dict[str, FactNormalizer]
```

Keep only:

```text
normalize text whitespace
canonicalize URL
parse Decimal money
normalize currency
normalize availability
normalize identifiers
normalize common dates
```

A normalizer sees one evidence item and does not compare candidates.

Delete extraction dependence on:

```text
field_policy.py
normalizers/__init__.py
shared/field_coerce*.py
field_url_normalization.py
public_record_firewall.py
```

Move any still-useful primitives into:

```text
extraction/normalize.py
core/urls.py
core/text.py
```

---

# 11. Verdict redesign

There must be one verdict owner:

```text
extraction.quality.assess_quality()
```

Persistence and publish modules store/aggregate it; they do not recompute it.

Required URL verdicts:

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

Delete the current behavior where:

```text
replay verdict = invalid
persisted verdict = empty
```

Run aggregation uses stored URL verdicts.

## Ecommerce detail success

Requires:

```text
selected product identity
non-shell title
URL compatibility
every public field has lineage
coherent public offer
valid public image when published
explicit variants preserved
no blocking selected-scope finding
evidence_count > 0
decision_count > 0
```

New Balance must become `blocked`, `invalid`, or `review`, never success.

## Listing success

Requires one or more valid rows with title, URL, lineage, and distinct identities.

## Job detail success

Requires title plus at least one supporting job fact:

```text
company
location
apply URL
meaningful description
```

---

# 12. Observability and replay redesign

## 12.1 Current defect

Replay contains hundreds of evidence items and decisions while RunTrace reports:

```text
candidate_count = 0
field_decision_count = 0
```

This means observability is still attached to the deleted architecture.

## 12.2 Canonical result summary

RunTrace must consume `ExtractionResult.metrics` directly:

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

Delete legacy concepts:

```text
candidate_count
completed_tiers
field_decision_count from CandidateSet
repair transforms
legacy field provenance
```

## 12.3 Persist full replay

For every URL, persist:

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

The existing `extraction.json` summary is not enough.

---

# 13. Browser retry contract

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

The outer URL processor performs at most:

```text
HTTP capture
-> extract
-> one browser capture when requested and not already attempted
-> extract
-> final result
```

Extraction never calls acquisition.

Acquisition never interprets missing fields using legacy repair lists.

---

# 14. Current-run replay gates

Before implementing new site fixes, copy the eight current page artifact sets into a stable replay corpus.

Required assertions:

## Under Armour

- verdict not invalid;
- variants must be present because evidence already supports 69 rows;
- persisted variants equal resolved variants;
- every variant field has lineage.

## H&M

- unrelated incomplete offers do not globally invalidate the page;
- selected product and coherent offer resolve when available;
- variants resolve or `EXPLICIT_VARIANTS_MISSING` is emitted;
- no silent empty result.

## Levi’s

- the resolved variant is persisted;
- root and variant offers remain distinct.

## Uniqlo

- configurable product cannot succeed with zero variants;
- selected color/size context is preserved.

## New Balance

- shell title is detected;
- 628-byte error shell is not success;
- browser “usable_content” does not override extraction shell validation.

## Puma

- incomplete unrelated offers are rejected locally;
- selected product is not globally invalidated;
- no silent empty result.

## Zara

- placeholder assets are rejected;
- primary product facts survive unrelated findings;
- no silent empty result.

## North Face

- benefit icon is rejected as primary image;
- product gallery image wins;
- explicit variants are not lost.

---

# 15. Revised implementation sequence

Execute in this order.

## PR 1 — Freeze the latest run as replay fixtures

- copy all eight page artifact sets into `tests/fixtures/extraction/current_run/`;
- add expected verdict/identity/variant/image assertions;
- make current failures reproducible without network;
- remove the agent plan’s assumption that live smoke is the first useful validation.

**Gate:** all eight fixtures load through the production artifact reader.

---

## PR 2 — Canonical CaptureBundle and ExtractionResult

- build bundle directly from `AcquisitionResult`;
- remove production `bundle_from_inputs()` and `request_from_inputs()`;
- remove `artifact_payloads`;
- add real acquisition metadata;
- add graph, target, retry request, and metrics to result;
- retain a separate fixture builder for tests only.

**Gate:** no production extraction call accepts loose HTML/network/artifact arguments.

---

## PR 3 — One four-surface orchestration function

- replace dispatch to `pipeline.py`, `listing.py`, and `jobs.py`;
- create collector, graph, validation, resolver, materializer policies selected by `SurfaceSpec`;
- keep one linear orchestration function;
- move surface differences into typed policies.

**Gate:** all four surfaces produce the same result structure and replay files.

---

## PR 4 — Product/job clustering and target selection

- build provisional roots by subject;
- merge only by exact identities;
- retain recommendation/unrelated roots separately;
- add `TargetSelection`;
- scope detail to selected root and listing to selected rows.

**Gate:** recommendations cannot overwrite the selected detail entity.

---

## PR 5 — Finding scope and non-global blocking

- add finding scope;
- make incomplete non-selected offers nonblocking;
- block only selected public facts/page conditions;
- fix H&M, Puma, and Zara using generic selected-scope logic.

**Gate:** pages with valid selected product evidence are not invalidated by unrelated incomplete offers.

---

## PR 6 — Atomic offers and primary assets

- implement `OfferDecision`;
- implement `AssetDecision`;
- prohibit independent public price/currency selection;
- add asset roles and primary image rejection policy.

**Gate:** North Face benefit icon and Zara placeholder cannot become primary images.

---

## PR 7 — Variant ownership and persistence

- classify variants before generic products;
- attach facts using subject/parent subject;
- merge exact variant identities;
- attach child offers/assets;
- materialize variant rows with exact lineage;
- guarantee persistence does not remove them.

**Gate:** Under Armour, Levi’s, and Uniqlo variant expectations pass.

---

## PR 8 — Typed materialization and single normalization owner

- introduce typed public records;
- consolidate normalizers;
- remove semantic public firewall;
- requested-field filtering happens last;
- persistence serializes without repairs.

**Gate:** typed model round-trip is byte-stable and preserves variants.

---

## PR 9 — One verdict, one replay, one trace

- `ExtractionResult.verdict` is canonical;
- delete persistence verdict recomputation;
- persist full replay components;
- replace legacy RunTrace extraction summary with result metrics;
- remove invalid-to-empty conversion.

**Gate:** replay, trace, DB record, and run summary report the same URL verdict.

---

## PR 10 — Extraction-driven browser retry

- introduce `RetryRequest`;
- remove ecommerce-detail missing-field repair lists and listing escalation heuristics;
- cap browser escalation to one;
- save both attempt bundles when retry occurs.

**Gate:** New Balance does not loop; explicit variants can request one browser attempt.

---

## PR 11 — Migrate and harden listing/job policies

- verify both listing modes through the same pipeline;
- add job entity facts and job quality rules;
- add wrong-surface fixtures;
- remove remaining commerce aliases from job outputs.

**Gate:** all four surfaces pass replay corpus with one engine.

---

## PR 12 — Delete obsolete extraction layers

After import scans pass, delete or replace:

```text
extraction/pipeline.py
extraction/listing.py
extraction/jobs.py
pipeline/raw_json.py
pipeline/direct_record_fallback.py
pipeline/extraction_retry_decision.py
pipeline/listing_escalation_decision.py
public_record_firewall.py
field_policy.py
normalizers/
shared/field_coerce*.py
legacy extraction trace projection
```

Keep only primitives with active non-extraction consumers and relocate them to `core/`.

**Gate:** zero legacy semantic owners remain.

---

## PR 13 — Final live validation

Run saved replay first, then live smoke.

Live failures create new saved capture fixtures before fixes.

**Gate:**

```text
zero success shells
zero success with zero evidence/decisions
zero success with missing lineage
zero selected offer incoherence
zero explicit-variant success with missing variants
zero replay/trace/verdict disagreement
```

---

# 16. Architecture limits

Final extraction package:

```text
production LOC: <= 5,500
files:          <= 24
file length:    <= 400 LOC
function length <= 60 LOC
```

Tests:

```text
<= 8,000 LOC
```

No:

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

---

# 17. Codex execution directive

> Replace the agent-created active plan with this revised plan. Begin with the eight current-run artifact fixtures, not new live patches. Complete a single four-surface orchestration path, real CaptureBundle boundary, multi-entity clustering, selected-scope validation, atomic offer resolution, primary asset selection, exact variant ownership, typed materialization, one normalization owner, one verdict owner, full replay persistence, and ExtractionResult-driven trace. Do not preserve compatibility wrappers or duplicate verdict/normalization/trace owners. Delete obsolete layers immediately after their replacement passes replay tests. Do not add LangGraph or site-specific repairs.
