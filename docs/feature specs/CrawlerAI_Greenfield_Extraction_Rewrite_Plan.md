# CrawlerAI Greenfield Extraction Rewrite
## Forced Simplification Architecture and Executable Implementation Plan

**Status:** Authoritative implementation contract  
**Goal:** Replace the current brittle extraction logic with a small deterministic pipeline that is easy to replay, test, reason about, and delete/extend safely.  
**Primary constraint:** No patching of the current extraction decision flow. Build the new pipeline as an isolated implementation, cut over, then delete the old path.

---

# 1. Final decision

Build a new extraction pipeline from scratch around five concepts only:

1. **CaptureBundle** — immutable acquired page artifacts.
2. **Evidence** — immutable facts extracted from artifacts.
3. **EntitySet** — product, variant, offer, and asset entities built from evidence.
4. **ResolutionResult** — deterministic accepted/rejected evidence decisions.
5. **MaterializedRecord** — the public output generated once.

The entire hot path is:

```text
CaptureBundle
    -> collect Evidence
    -> normalize Evidence
    -> build EntitySet
    -> validate
    -> resolve
    -> materialize once
    -> quality verdict
```

There is no:

```text
flat record -> cleanup -> repair -> backfill -> normalize -> repair again
```

There is no mutable partially-correct record.

There is no generic source-priority winner.

There is no LLM in the default extraction path.

---

# 2. Why the current style of extraction becomes unmaintainable

The system becomes brittle when the same code path performs all of these responsibilities:

```text
parsing
field selection
entity matching
fallback generation
normalization
repair
validation
publishing
```

The result is predictable:

- one fix changes another field;
- parent and variant values contaminate each other;
- currency and price come from different contexts;
- mutation order becomes business logic;
- tests prove individual patches, not system correctness;
- every new source creates another priority or cleanup rule;
- debugging requires reconstructing the final mutation sequence.

The greenfield system avoids this by enforcing:

```text
observe first
decide once
materialize once
```

---

# 3. Non-negotiable invariants

Codex must implement these exactly.

## 3.1 Immutable inputs

Artifacts and evidence are immutable Pydantic models or frozen dataclasses.

## 3.2 No public record before resolution

No collector, normalizer, linker, or validator may receive or modify a public record dictionary.

## 3.3 Evidence is append-only

Collectors may emit evidence. They may not remove or overwrite evidence emitted by another collector.

## 3.4 Entity ownership before value comparison

Two values are compared only after they are assigned to the same product, variant, offer, or asset entity.

## 3.5 Offers are atomic

The following stay in one offer group:

```text
price
currency
availability
original_price
seller
request context
```

Price from one offer group may never be combined with currency from another.

## 3.6 Validators never repair

Validators return findings only.

## 3.7 Resolver never mutates inputs

The resolver returns decisions.

## 3.8 Materialization happens exactly once

After materialization, only serialization and public-schema filtering are allowed.

## 3.9 Every public value has lineage

Every value must link to accepted evidence IDs or a derived-fact ID.

## 3.10 Order independence

Reordering evidence must not change the output.

## 3.11 Duplicate independence

Adding duplicate equivalent evidence must not change the output.

## 3.12 No invented variants

No Cartesian product is created unless an artifact explicitly supplies the supported combinations.

## 3.13 No silent inheritance

Parent-to-variant or variant-to-parent inheritance is permitted only through named derivation rules with explicit preconditions and lineage.

## 3.14 No source table as business logic

Source reliability is a late tie-breaker, not the primary decision rule.

---

# 4. Scope

The first production version supports only:

```text
ecommerce_detail
```

Do not generalize the core around listings, jobs, content, or arbitrary schemas during this rewrite.

The design should be extensible, but implementation must optimize for product detail correctness.

---

# 5. Target repository layout

Create this isolated package:

```text
backend/app/services/extraction_v2/
    __init__.py
    contracts.py
    ids.py
    pipeline.py
    quality.py
    replay.py

    collectors/
        __init__.py
        registry.py
        jsonld.py
        microdata.py
        opengraph.py
        js_state.py
        network.py
        dom.py
        url.py

    entities/
        __init__.py
        contracts.py
        product_linker.py
        variant_linker.py
        offer_linker.py
        asset_linker.py
        builder.py

    validation/
        __init__.py
        contracts.py
        identity.py
        variants.py
        offers.py
        output.py
        runner.py

    resolution/
        __init__.py
        contracts.py
        scalar.py
        identity.py
        variants.py
        offers.py
        assets.py
        engine.py

    materialization/
        __init__.py
        record.py
        lineage.py
```

Do not create more packages until this implementation is complete.

---

# 6. Hard code-size limits

These are acceptance criteria, not suggestions.

## 6.1 Production LOC budget

Excluding tests and generated schemas:

```text
core contracts + pipeline + quality + replay: <= 1,200 LOC
collectors total:                           <= 2,200 LOC
entity building total:                      <= 1,200 LOC
validation total:                           <=   800 LOC
resolution total:                           <= 1,200 LOC
materialization total:                      <=   500 LOC
--------------------------------------------------------
maximum extraction_v2 production LOC:       <= 7,100 LOC
target:                                     <= 5,500 LOC
```

## 6.2 File limits

```text
maximum file length:      400 LOC
maximum function length:   60 LOC
maximum function args:      8
maximum nesting depth:      4
```

## 6.3 Structural limits

- No file named `cleanup.py`.
- No file named `repair.py`.
- No function name beginning with `repair_`.
- No function may mutate a `dict[str, Any]` representing a product record.
- No global source-priority list with more than 10 entries.
- No site-specific Python branch in core resolution code.
- Domain-specific extraction recipes must be data, not branching code.
- No module may import from the old detail extraction package.

Add automated structure tests for all limits.

---

# 7. Core contracts

Implement in `contracts.py` and focused contracts modules.

## 7.1 CaptureBundle

```python
class CaptureBundle(BaseModel):
    schema_version: Literal["capture.v1"]
    bundle_id: str
    run_id: int
    requested_url: str
    final_url: str
    request_context: RequestContext
    artifacts: tuple[ArtifactRef, ...]
    acquisition_outcome: str
```

## 7.2 RequestContext

```python
class RequestContext(BaseModel):
    context_id: str
    locale: str | None = None
    language: str | None = None
    country: str | None = None
    currency_hint: str | None = None
    timezone: str | None = None
    browser_profile_id: str | None = None
    session_fingerprint: str | None = None
```

## 7.3 ArtifactRef

```python
class ArtifactRef(BaseModel):
    artifact_id: str
    artifact_type: Literal[
        "http_html",
        "rendered_html",
        "jsonld",
        "microdata",
        "opengraph",
        "js_state",
        "network_json",
        "screenshot",
    ]
    content_sha256: str
    storage_uri: str
    media_type: str
    metadata: dict[str, JsonValue] = {}
```

## 7.4 Evidence

```python
class Evidence(BaseModel):
    evidence_id: str
    bundle_id: str
    artifact_id: str
    collector_id: str
    collector_version: str

    fact_type: str
    raw_value: JsonValue
    value: JsonValue

    locator: SourceLocator
    entity_hint: EntityHint | None = None
    group_id: str | None = None

    directness: Literal["direct", "embedded", "inferred"]
    confidence: float
    flags: tuple[str, ...] = ()
    metadata: dict[str, JsonValue] = {}
```

## 7.5 SourceLocator

```python
class SourceLocator(BaseModel):
    kind: Literal[
        "json_pointer",
        "css_selector",
        "xpath",
        "script_path",
        "network_json_pointer",
        "url_component",
        "adapter_path",
    ]
    value: str
    preview: str | None = None
```

## 7.6 EntityHint

```python
class EntityHint(BaseModel):
    entity_type: Literal["product", "variant", "offer", "asset"]
    product_id: str | None = None
    variant_id: str | None = None
    sku: str | None = None
    url: str | None = None
    option_values: dict[str, str] = {}
    selected: bool | None = None
```

## 7.7 Entities

```python
class ProductEntity(BaseModel):
    entity_id: str
    identity_evidence_ids: tuple[str, ...]
    attribute_evidence: dict[str, tuple[str, ...]]
    variant_ids: tuple[str, ...]
    offer_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
```

```python
class VariantEntity(BaseModel):
    entity_id: str
    product_entity_id: str
    identity_key: str
    identity_evidence_ids: tuple[str, ...]
    option_values: dict[str, str]
    attribute_evidence: dict[str, tuple[str, ...]]
    offer_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    selected: bool
```

```python
class OfferEntity(BaseModel):
    entity_id: str
    product_entity_id: str
    variant_entity_id: str | None
    group_id: str
    request_context_id: str
    fact_evidence: dict[str, tuple[str, ...]]
```

```python
class AssetEntity(BaseModel):
    entity_id: str
    product_entity_id: str
    variant_entity_id: str | None
    url_evidence_ids: tuple[str, ...]
```

## 7.8 Finding

```python
class Finding(BaseModel):
    finding_id: str
    rule_id: str
    severity: Literal["info", "low", "medium", "high", "critical"]
    entity_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    message: str
    blocking: bool
    metadata: dict[str, JsonValue] = {}
```

## 7.9 Decision

```python
class Decision(BaseModel):
    decision_id: str
    entity_id: str
    fact_type: str
    accepted_evidence_ids: tuple[str, ...]
    rejected: tuple[RejectedEvidence, ...]
    finding_ids: tuple[str, ...]
    rule_id: str
    status: Literal["resolved", "unresolved", "conflicted"]
```

## 7.10 ResolutionResult

```python
class ResolutionResult(BaseModel):
    primary_product_entity_id: str | None
    decisions: tuple[Decision, ...]
    derived_facts: tuple[DerivedFact, ...]
    unresolved_fact_types: tuple[str, ...]
    blocking_finding_ids: tuple[str, ...]
```

---

# 8. Fact vocabulary

Use a controlled vocabulary.

## Product facts

```text
product.url
product.title
product.brand
product.description
product.category
product.product_type
product.sku
product.mpn
product.gtin
product.materials
product.color
product.size
```

## Variant facts

```text
variant.id
variant.sku
variant.gtin
variant.url
variant.selected
variant.option.size
variant.option.color
variant.option.width
variant.option.length
variant.option.material
variant.option.style
variant.option.capacity
variant.option.quantity
```

## Offer facts

```text
offer.price
offer.currency
offer.original_price
offer.availability
offer.stock_quantity
offer.seller
```

## Asset facts

```text
asset.image_url
asset.role
asset.variant_association
```

Do not create arbitrary field names at runtime.

---

# 9. Collector design

Every collector implements:

```python
class Collector(Protocol):
    collector_id: str
    collector_version: str

    def collect(
        self,
        bundle: CaptureBundle,
        artifacts: ArtifactReader,
    ) -> tuple[Evidence, ...]:
        ...
```

## 9.1 Collector rules

Collectors may:

- parse one artifact family;
- normalize local syntax;
- emit evidence with exact locators;
- assign entity hints;
- assign group IDs for facts from the same object.

Collectors may not:

- select winners;
- read another collector’s evidence;
- write a public record;
- perform parent/variant inheritance;
- repair another source;
- infer a missing commercial value.

## 9.2 Group IDs

Facts extracted from the same structured object must share a `group_id`.

Example JSON-LD offer:

```json
{
  "price": "129.00",
  "priceCurrency": "AUD",
  "availability": "InStock"
}
```

Emits:

```text
offer.price        group_id=offer:<artifact>:<pointer>
offer.currency     group_id=offer:<artifact>:<pointer>
offer.availability group_id=offer:<artifact>:<pointer>
```

This prevents cross-source offer mixing.

## 9.3 Site-specific behavior

Site-specific logic must be represented as a declarative recipe:

```yaml
domain: example.com
version: 3
selectors:
  product_root: "main[data-product-id]"
  title: "h1"
  price: "[data-current-price]"
  currency_attribute: "data-currency"
  variant_rows: "[data-variant-id]"
```

Recipes emit normal evidence.

No site hostname checks are allowed inside resolver code.

---

# 10. Normalization

Normalization is a pure function:

```python
def normalize_evidence(evidence: Evidence) -> Evidence:
    ...
```

Allowed:

- whitespace cleanup;
- URL canonicalization;
- currency uppercase;
- decimal parsing;
- availability enum mapping;
- option label normalization;
- GTIN digit normalization.

Forbidden:

- replacing one value with another;
- guessing currency;
- correcting magnitude from another price;
- assigning a product fact from variant consensus;
- deleting evidence because a better source exists.

Invalid evidence remains present with a flag:

```text
invalid_decimal
invalid_currency
invalid_gtin
placeholder_text
tracking_url
low_signal
```

The validator/resolver decides whether flagged evidence is admissible.

---

# 11. Primary product selection

The product linker creates product clusters.

## 11.1 Positive identity signals

Apply in this order:

1. exact canonical product ID;
2. exact GTIN/MPN/SKU compatible with requested URL;
3. exact canonical URL;
4. exact requested/final URL path identity;
5. structured `mainEntity`;
6. selected-variant relationship;
7. primary DOM region;
8. title/model-code similarity.

## 11.2 Negative identity signals

```text
recommendation section
recently viewed
related product
cross-sell
upsell
carousel item
analytics-only product object
different canonical product URL
different product ID
```

## 11.3 Selection rule

Return one of:

```text
resolved primary product
ambiguous primary product
no product
```

Never merge ambiguous product clusters.

---

# 12. Variant model

## 12.1 Variant identity

Merge only through this exact precedence:

1. exact variant ID;
2. exact SKU;
3. exact GTIN;
4. exact canonical variant URL;
5. exact option tuple within the same product and source group.

Do not merge by:

```text
price
image only
title only
one option only
array position
```

## 12.2 Option axes

Classify option axes from explicit labels and attributes first.

Supported axes:

```text
size
color
width
length
material
style
capacity
quantity
unknown
```

Unknown remains unknown. Do not force unknown numeric values into size.

## 12.3 Cartesian products

Never generate a Cartesian product.

Only create variant rows explicitly present in:

```text
JSON-LD hasVariant
JS state variant list
network variant list
DOM variant row/object
verified combination map
```

Option lists without supported combinations are stored as product option metadata, not variants.

---

# 13. Offer model

## 13.1 Atomic offer rule

An offer is one group in one request context attached to one product or variant.

The resolver may accept:

```text
price + currency + availability
```

only when those facts are in the same offer entity or explicitly linked compatible groups.

## 13.2 Product price

Use:

1. direct product offer;
2. direct selected-variant offer;
3. otherwise unresolved.

Do not:

- take minimum variant price;
- copy product price to all variants;
- infer exact price from a range;
- overwrite structured currency from URL locale.

## 13.3 Variant price

Publish a variant price only when direct evidence exists for that variant offer.

No blanket inheritance.

## 13.4 Availability

Product availability may be derived from variants only when:

```text
variant set is explicitly complete
and every sellable variant has availability
```

Otherwise keep product availability unresolved unless directly observed.

## 13.5 Original price

Accept only if:

```text
same offer group
same currency
original_price >= current_price
```

Otherwise reject with a finding.

---

# 14. Validation

Validators are pure:

```python
def validate(
    evidence: tuple[Evidence, ...],
    entities: EntitySet,
) -> tuple[Finding, ...]:
    ...
```

Required rules:

## Identity

```text
PRIMARY_PRODUCT_AMBIGUOUS
REQUESTED_PRODUCT_MISMATCH
CROSS_SELL_CONTAMINATION
DUPLICATE_PRODUCT_ID
```

## Variants

```text
DUPLICATE_VARIANT_IDENTITY
CONTRADICTORY_OPTION_TUPLE
UNSUPPORTED_VARIANT_COMBINATION
QUANTITY_MISCLASSIFIED_AS_SIZE
SELECTED_VARIANT_NOT_FOUND
```

## Offers

```text
PRICE_WITHOUT_CURRENCY
CURRENCY_WITHOUT_PRICE
OFFER_CONTEXT_MISMATCH
PARENT_VARIANT_CURRENCY_CONFLICT
INVALID_ORIGINAL_PRICE
NEGATIVE_STOCK
INCOMPLETE_SELLABLE_VARIANT_OFFER
```

## Output

```text
MISSING_PRODUCT_IDENTITY
INSUFFICIENT_PRODUCT_KNOWLEDGE
PUBLIC_VALUE_WITHOUT_LINEAGE
BLOCKING_FINDING_ON_PUBLIC_VALUE
```

Validators do not fix anything.

---

# 15. Resolver

The resolver applies lexicographic rules, not a weighted mystery score.

For each entity and fact:

```text
1. admissible evidence only
2. exact entity ownership
3. same request context
4. same coherent group
5. direct evidence over inferred
6. no blocking finding
7. complete composite fact group
8. source reliability for this fact type
9. confidence
10. stable evidence ID tie-break
```

## 15.1 Scalar fields

For title, brand, description, category, identifiers:

```python
resolve_scalar(entity_id, fact_type, evidence, findings) -> Decision
```

## 15.2 Offers

Resolve the offer as a whole:

```python
resolve_offer(offer_entity, evidence, findings) -> OfferDecision
```

Do not resolve price and currency independently.

## 15.3 Assets

- canonicalize image URL;
- remove exact duplicates;
- prefer product/selected-variant association;
- preserve deterministic order;
- no color inference from image filename.

## 15.4 Rejection reasons

Every rejected evidence item gets one exact reason:

```text
wrong_entity
wrong_context
wrong_group
invalid_value
blocked_by_finding
less_direct
less_complete
lower_fact_reliability
lower_confidence
stable_tiebreak
duplicate
```

No generic `lower_source_priority` catch-all.

---

# 16. Derived facts

Derived facts are explicit outputs of named rules.

Allowed initial rules:

```text
NORMALIZE_MONEY_PRECISION
PRODUCT_AVAILABILITY_FROM_COMPLETE_VARIANT_SET
PRODUCT_IMAGE_FROM_SELECTED_VARIANT
PRODUCT_COLOR_FROM_SELECTED_VARIANT
```

Each rule must:

- declare preconditions;
- list input evidence IDs;
- produce one derived fact;
- abstain when preconditions are not satisfied.

Do not add any other derivation rule in the first implementation.

---

# 17. Materialization

Materialization is pure:

```python
def materialize(
    entities: EntitySet,
    resolution: ResolutionResult,
) -> MaterializedRecord:
    ...
```

It may:

- select the resolved primary product;
- project resolved facts;
- output resolved variants;
- output resolved offers;
- attach lineage;
- remove internal fields from public output;
- serialize decimals/enums.

It may not:

- parse HTML;
- examine JS state;
- call selectors;
- infer missing values;
- alter decisions;
- add fallback values;
- repair data.

---

# 18. Quality verdict

Implement:

```text
success
partial
review
empty
blocked
invalid
error
```

## success

All required:

- primary product resolved;
- URL and title resolved;
- minimum product knowledge satisfied;
- no critical/blocking findings;
- no unresolved required fact;
- all public values have lineage;
- offer is coherent if price is published.

## partial

- product identity resolved;
- useful record exists;
- optional fields missing;
- no blocking contradiction affects published fields.

## review

- ambiguous primary product;
- unresolved high-value conflict;
- selected variant conflict;
- ambiguous commercial context.

## invalid

- a materialized value violates an invariant;
- value lacks lineage;
- price/currency coherence broken;
- blocking finding affects a published value.

## empty

No product entity satisfies minimum identity.

## blocked

Acquisition captured a challenge/interstitial without usable product evidence.

## error

Unhandled runtime failure.

---

# 19. Persistence and replay

Persist for every URL:

```text
capture.json
evidence.jsonl
entities.json
findings.json
decisions.json
derived.json
record.json
verdict.json
```

Replay command:

```bash
python -m app.services.extraction_v2.replay \
  --bundle-id <bundle_id>
```

Required properties:

- no network access;
- deterministic output;
- output fingerprint;
- decision diff against another resolver version.

---

# 20. LangGraph decision

Do not use LangGraph in the first implementation.

Reason:

The hard problem is deterministic data modeling, not workflow orchestration.

LangGraph may be added later only for:

```text
human review
LLM evidence adjudication
offline recipe proposal and approval
```

It must never wrap every extractor or become the hot path.

The first release must ship without LangGraph.

---

# 21. LLM decision

No LLM in the default path.

After the deterministic resolver is stable, an optional adjudicator may:

```text
select one evidence ID
reject all
abstain
classify an unknown option axis
```

It may not generate field values.

The resolver remains final authority.

---

# 22. Exact implementation sequence

Each step is one mergeable PR. Codex may not reorder steps.

## PR 1 — Contracts and IDs

Create:

```text
contracts.py
ids.py
entities/contracts.py
validation/contracts.py
resolution/contracts.py
```

Implement deterministic IDs.

Tests:

- identical inputs produce identical IDs;
- evidence order does not affect entity IDs;
- schemas reject extra fields.

No production wiring.

## PR 2 — CaptureBundle and replay loader

Implement artifact reader and replay loader.

Tests:

- bundle round trip;
- missing artifact failure is explicit;
- replay performs no network call.

No extraction logic.

## PR 3 — JSON-LD, OpenGraph, microdata collectors

Implement structured collectors only.

Tests:

- exact JSON pointers;
- offer group IDs;
- product/variant hints;
- malformed structured data produces no crash.

No DOM.

## PR 4 — JS-state and network collectors

Implement generic recursive object walking with strict fact mapping.

Tests:

- variant arrays;
- product arrays with cross-sell separation;
- offer grouping;
- request-context linkage.

No source arbitration.

## PR 5 — DOM and URL collectors

Implement minimal semantic DOM extraction:

```text
h1/title
canonical URL
visible price container
currency marker
availability
explicit variant rows/controls
images
```

Do not port the old cleanup heuristics.

Tests use saved HTML fixtures.

## PR 6 — Normalization

Implement pure evidence normalization and flags.

Property tests:

- idempotence;
- raw value preserved;
- no cross-evidence dependency.

## PR 7 — Product linker

Implement product clustering and primary product selection.

Tests:

- requested product plus recommendations;
- duplicate product objects;
- canonical URL mismatch;
- ambiguous primary product.

## PR 8 — Variant and asset linkers

Implement exact variant merge rules and asset association.

Tests:

- duplicate SKU merge;
- conflicting SKU split/finding;
- quantity control not size;
- no Cartesian expansion;
- selected variant linking.

## PR 9 — Offer linker

Implement atomic offer grouping and entity attachment.

Tests:

- price/currency remain grouped;
- variant and product offers stay separate;
- request contexts stay separate;
- marketplace sellers stay separate.

## PR 10 — Validators

Implement all named validator rules.

Tests assert exact finding IDs and linked evidence IDs.

## PR 11 — Resolver

Implement scalar, identity, offer, variant, and asset resolution.

Property tests:

- order independence;
- duplicate independence;
- cross-sell evidence does not change primary output;
- wrong-context evidence cannot win;
- stable tie-break.

## PR 12 — Derived facts

Implement only the four allowed derivation rules.

Tests prove preconditions and abstention.

## PR 13 — Materializer and verdict

Implement single-pass record projection and quality verdict.

Tests:

- every public value has lineage;
- no unresolved price/currency publication;
- high conflict cannot be success;
- no mutation of inputs.

## PR 14 — Shadow pipeline integration

Add one integration entry:

```python
extract_detail_v2(bundle) -> ExtractionV2Result
```

Run old and new pipelines in parallel.

Persist V2 artifacts and diff.

Do not let V2 alter public output yet.

## PR 15 — Fixture gate

Create replay corpus from all known failing URLs and representative successful URLs.

Required:

```text
minimum 50 detail fixtures
minimum 10 multi-variant fixtures
minimum 10 localized currency fixtures
minimum 10 cross-sell-heavy fixtures
minimum 5 blocked/empty fixtures
```

All V2 acceptance tests must pass.

## PR 16 — Cutover

Switch ecommerce detail output to V2.

Fallback to old pipeline is forbidden.

If V2 returns `review`, `invalid`, `empty`, or `error`, persist that result honestly.

Do not silently call old extraction.

## PR 17 — Delete old pipeline

Delete the old ecommerce detail decision, repair, cleanup, normalization, and arbitration path.

Remove imports, tests, configs, and docs tied only to it.

Acceptance gate:

```text
net production LOC reduction after deletion >= 40%
```

relative to the deleted ecommerce detail extraction surface.

## PR 18 — Structure and anti-regression gates

Add tests that fail when:

- old package is imported;
- `repair_` functions are added;
- cleanup modules are introduced;
- materializer imports collectors;
- resolver mutates input;
- collectors import resolver/materializer;
- source priority is used before entity/context checks;
- production LOC exceeds budget.

---

# 23. Mandatory test matrix

## Unit

- every collector;
- every linker;
- every validator;
- every resolver policy;
- every derivation;
- materializer;
- verdict.

## Property-based

- evidence order independence;
- duplicate evidence independence;
- deterministic replay;
- unrelated evidence isolation;
- no cross-context offer merge;
- no unsupported variant generation;
- every public field has lineage.

## Golden replay

- expected primary entity;
- expected findings;
- expected decisions;
- expected verdict;
- expected public record.

## Mutation tests

At minimum, use targeted mutation testing for:

```text
offer grouping
variant identity
primary product selection
quality verdict
```

---

# 24. Metrics

Emit:

```text
evidence_count
product_entity_count
variant_entity_count
offer_entity_count
finding_count_by_severity
resolved_decision_count
unresolved_decision_count
public_lineage_coverage
primary_product_resolution_rate
offer_coherence_rate
replay_determinism_failures
success_with_blocking_findings
success_with_missing_lineage
```

These must remain zero:

```text
replay_determinism_failures
success_with_blocking_findings
success_with_missing_lineage
```

---

# 25. Explicitly forbidden implementation shortcuts

Codex must not:

- add more conditions to the old cleanup flow;
- port old repair functions into V2;
- call old materialization from V2;
- add a generic “best candidate” source-priority function;
- generate variant combinations from option lists;
- copy product price/currency to every variant;
- infer brand from hostname in the resolver;
- use title parsing to invent identifiers;
- silently replace conflicting currency;
- return success because one record exists;
- add LangGraph before cutover;
- add LLM-generated values;
- preserve old behavior merely because an old test expects it.

Old tests that encode brittle behavior must be deleted or rewritten against the new invariants.

---

# 26. Codex execution directive

Use the following as the implementation instruction:

> Build `extraction_v2` exactly as specified. Do not patch, refactor, or reuse the old ecommerce detail decision pipeline. Do not make architecture decisions. Do not reorder PRs. Do not introduce fallback to the old pipeline after cutover. Implement immutable evidence, explicit product/variant/offer entities, pure validators, deterministic resolution, explicit derived facts, one-time materialization, replay artifacts, and quality verdicts. Enforce the LOC and structural limits with tests. After V2 cutover, delete the old ecommerce detail extraction flow and demonstrate at least 40% net production LOC reduction across the replaced surface.

---

# 27. Definition of done

The rewrite is complete only when:

- V2 is the only ecommerce detail extraction path;
- old fallback is deleted;
- every public value has lineage;
- offers cannot mix contexts or entities;
- variants are never invented;
- replay is deterministic;
- high conflicts cannot produce success;
- no semantic cleanup runs after materialization;
- extraction_v2 stays within the LOC budget;
- deleted surface achieves at least 40% net LOC reduction;
- all saved failure fixtures pass;
- a new production defect can be reproduced and debugged from artifacts without revisiting the website.

That is the complete architecture. No further architecture review is required before implementation.
