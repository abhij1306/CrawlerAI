# CrawlerAI Revised Backend Implementation Plan

**Date:** 30 June 2026  
**Basis:** latest 96-result crawl, previous 96-result crawl, original 90-page/144-issue HTML audit, current backend static audit after Plan 1  
**Primary surface:** ecommerce detail  
**Status:** proposed  

## 1. Decision

Plan 1's ownership architecture should remain. Do **not** create another extraction path.

The inspected backend already enforces the essential ratchets:

- `Harvest → Resolve → Publish` is the production stage sequence;
- `EvidenceDisposition` accounting is exact and fail-closed;
- `SelectedFact` is tied to accepted evidence and a decision;
- public records are serialized from `PublicationProjection` only;
- publication divergence is blocking and emits no canonical records.

The next work should therefore repair diagnostic truth and deterministic recall **inside the existing architecture**. Adaptive contracts and LLM assistance come only after those layers are trustworthy.

## 2. Revised baseline

The latest 96-run is mixed:

- success verdicts: **40 → 43**;
- records with price/currency: **75 → 72**;
- records with images: **88 → 85**;
- variant-bearing records: **46 → 44**;
- evidence p95: **1,253 → 515**;
- diagnose p95: **16.6 KB → 213.9 KB**.

Against the original 144 issue instances:

- **113** remain reproducible;
- **20** are resolved;
- **1** is resolved with a new regression;
- **10** are currently capture failures.

The implementation must preserve the 20 genuine improvements while recovering lost field/variant recall.

## 3. Non-negotiable invariants

1. Resolve remains the only semantic authority.
2. Publish remains projection-only and representation-only.
3. Acquisition, contracts, humans and LLMs may create artifacts/evidence or relation hypotheses; they never write canonical values.
4. No site/domain literals in production extraction rules.
5. No Cartesian-product variants.
6. No blocked/shell capture is converted into `not_present`.
7. No browser escalation for an optional field that was not requested and is not enabled by an approved template policy.
8. Every evidence row retains one terminal disposition.
9. Every public value has selected/derived lineage and canonicalization lineage where representation changed.
10. All corpus outputs remain ignored local artifacts.

---

## Slice 0 — Lock the two-run baseline and residual ledger

**Goal:** establish a reproducible target before changing code.

### Work

Create an ignored local acceptance harness that:

- replays all 96 latest captures and all 96 previous captures;
- maps captures by canonical URL/path identity, not result ID;
- imports the original 144 issue rows;
- writes one residual-ledger row per issue with:
  - `resolved`;
  - `resolved_with_regression`;
  - `still_reproducible`;
  - `capture_failure`;
  - `ground_truth_review_required`;
- stores the 22 original clean-control URLs as a named partition;
- records commit, dirty-tree fingerprint, runtime config and corpus hashes;
- compares public records, field states, evidence counts, findings and diagnostic size.

### Files

- Add a generic harness under `backend/harness/` or the established acceptance location.
- Store run-specific URL maps, expected values, reports and captures only under ignored `backend/artifacts/`.

### Acceptance

- 96/96 latest and 96/96 previous captures replay; zero skips.
- All 144 issue rows receive exactly one residual disposition.
- No corpus-specific URL or expected value appears in tracked code.
- Existing Plan 1 accounting/divergence tests remain green.

**Size:** S

---

## Slice 1 — Make diagnostic truth complete before fixing extraction

**Goal:** make every missing or suppressed canonical field explainable at the actual failing stage.

### 1.1 Add typed assessment contracts

In `backend/app/extraction/contracts.py`, add:

```python
class CaptureCompletenessSignal(FrozenModel):
    shadow_roots_detected: int = 0
    shadow_roots_flattened: int = 0
    closed_shadow_roots_detected: int = 0
    hidden_panel_dom_present: bool = False
    serialization_method_version: str

class CaptureAssessment(FrozenModel):
    status: Literal[
        "usable", "blocked", "captcha", "status_error", "empty",
        "partial_shell", "wrong_content_type", "redirect_mismatch",
    ]
    reasons: tuple[str, ...] = ()
    retry_capabilities: tuple[str, ...] = ()
    completeness: CaptureCompletenessSignal | None = None

class ResultAssessment(FrozenModel):
    outcome: Literal[
        "accept", "retry_with_rendered_capture", "request_interaction",
        "request_contract", "request_human_review", "reject_wrong_surface",
        "reject_ambiguous_target", "reject_source_unavailable",
    ]
    reasons: tuple[str, ...] = ()
    unresolved_fields: tuple[str, ...] = ()
```

Keep the existing `CaptureBundle` compatible; initially populate these from `acquisition_diagnostics` and migrate to a typed field once readers are updated.

### 1.2 Fix the field-state universe

Replace the current universe in `result_building.projection_field_states()`.

The field set must be:

```text
surface canonical fields
∪ contract-required fields
∪ explicitly requested fields
∪ fields represented by projection/evidence
```

Do not infer field existence from projection entries alone.

Add explicit states:

- `capture_incomplete`;
- `collector_missed`;
- `captured_unowned`;
- `captured_rejected`;
- `captured_conflicting`;
- `join_failed`;
- `captured_published`;
- `captured_suppressed`;
- `interaction_required`;
- `source_unavailable`;
- `not_present_in_captured_sources`;
- `output_divergent`;
- `not_requested`.

Keep aliases only for schema migration; emit one canonical state vocabulary in `diagnose.v2`.

### 1.3 Repair run-level aggregation

Update `backend/app/observability/run_report.py::_root_causes` to aggregate:

- field states and their reason codes;
- blocking/high-value findings;
- collector budget losses by fact family;
- join failures;
- variant drops;
- capture assessment;
- output divergence.

Do not count hundreds of entity-level duplicates as hundreds of root causes. Store count plus bounded examples.

### 1.4 Reduce diagnostic noise without hiding evidence

`validation._validate_offers()` currently emits findings for every partial candidate offer. Scope publication-level findings to:

- selected product;
- selected/default offer;
- eligible variant offers;
- candidates that could beat or conflict with the selected offer.

Move unselected-candidate incompleteness into one grouped diagnostic with counts and examples.

### Acceptance

- Every standard ecommerce-detail field receives a state on all 96 captures.
- The run report accounts for all 113 still-reproducible issue rows or links them to a review disposition.
- `PRICE_WITHOUT_CURRENCY` findings fall from 737 individual rows to bounded target-scoped groups without losing candidate counts.
- Diagnose p95 is no greater than 125% of the new, post-fix baseline and every diagnose remains under 1 MiB.
- StockX, Chewy, Arc'teryx and other unusable captures cannot emit `not_present_in_captured_sources` for affected fields.

**Size:** M

---

## Slice 2 — Complete and harden capture serialization

**Goal:** distinguish CSS-hidden, open-shadow, closed-shadow and interaction-fetched content before enrichment.

### 2.1 Harden the existing shadow flattener

Do not add a second implementation. Update `backend/app/acquisition/dom_runtime.py`:

- make flattening idempotent using a versioned host marker;
- enforce `shadow_dom_flatten_max_hosts` in the browser script;
- preserve provenance with attributes such as:
  - `data-crawlerai-shadow-host`;
  - `data-crawlerai-shadow-root="open"`;
  - serialization version;
- return structured counts rather than an ignored integer;
- detect likely closed roots where CDP/browser metadata permits, without claiming they were flattened;
- persist the resulting `CaptureCompletenessSignal`;
- settle mutations before final serialization;
- fail diagnostically, not silently, when flattening fails.

### 2.2 Use one serialization path

Audit every `get_page_html(..., flatten_shadow=False)` call in traversal/card-counting helpers.

- Intermediate card counting may use non-flattened HTML if explicitly documented.
- Any artifact later consumed by Harvest or used to assert field absence must use the canonical shadow-aware serializer.
- Record serialization method/version on the artifact.

### 2.3 Recover product-scoped hidden content

The current DOM collector discards `node.is_hidden()` candidates.

Change this to:

- admit hidden candidates only when they are inside a product-scoped tab, accordion, carousel or disclosure region;
- annotate visibility and component role in evidence flags/provenance;
- lower ranking versus visible evidence, but do not discard it;
- continue rejecting hidden navigation, recommendations, templates and unrelated modals.

This is a recognizer change in Harvest, not a public-value shortcut.

### Tests

Add direct tests for:

- repeated serialization does not duplicate shadow content;
- max-host limit is honored;
- open-root counts/provenance are persisted;
- flattener failure is reported;
- light-DOM controls do not regress;
- hidden product tab content is collected;
- hidden recommendation content is rejected.

### Acceptance

- Re-capture the inconclusive/variant-ambiguous partition and 22 clean controls.
- Every audited URL is classified A/B/C/D or explicitly unresolved with an adjudication note.
- Zero clean-control field-state regression.
- No Category A/B page is routed to interaction solely because serialization/visibility lost the content.

**Size:** M

---

## Slice 3 — Close deterministic scalar, text and asset defects

**Goal:** fix representation and role errors before adding adaptive behavior.

### 3.1 Canonical scalar text

Introduce field-specific representation canonicalizers before ranking/publication:

- HTML-unescape titles, brands, option values and plain-text descriptions;
- convert description markup to stable text while retaining raw evidence;
- normalize whitespace after entity/markup decoding;
- record a `CanonicalizationTrace` whenever the published representation differs.

Do not mutate raw Evidence.

### 3.2 Asset identity and delivery

In `url_utils.py`, `entities.py`, `resolution.py` and `publication.py`:

- HTML-unescape URLs before parsing;
- calculate both source identity and canonical delivery identity in Resolve;
- deduplicate assets on structured identity **and** canonical delivery identity;
- keep transformation parameters required for delivery while excluding them from identity;
- if the highest-ranked asset fails delivery canonicalization, promote the next eligible asset;
- never wait until Publish to discover that two selected assets serialize to the same URL.

Regression targets:

- the 10 latest duplicate-image URLs;
- Phase Eight and KitchenAid `&amp;` queries;
- Glossier primary-image fallback;
- all prior cross-product contamination controls.

### 3.3 Brand role resolution

Model candidate roles explicitly:

- manufacturer/private label;
- retailer;
- marketplace;
- seller;
- collection;
- unknown.

Hostname/domain evidence is weak corroboration only. It may normalize a selected brand but may not create manufacturer truth.

Regression targets:

- Target → Levtex Home (when supported by source evidence);
- Peloton/OnePeloton;
- Amazon marketplace vs product brand;
- Amsterdam Vintage Watches vs Rolex;
- Back Market vs Apple;
- Calvin Klein spacing/casing;
- J.Crew trailing punctuation.

### 3.4 Offer atomicity

Resolve current price and currency as one offer-level atomic group. A currency from another candidate offer may not complete a selected price unless relation compatibility is explicit.

### Acceptance

- Duplicate public asset identities: zero across both 96-run partitions.
- HTML entities/raw markup in public title/brand/description/image URL: zero.
- Malformed/rejected primary images fall back to the next valid product-owned asset.
- Brand-role regression suite passes with no hostname-as-manufacturer publication.
- All published price/currency pairs share compatible offer lineage.

**Size:** M–L

---

## Slice 4 — Make variant evidence budgeting and joins deterministic

**Goal:** close the dominant remaining structural defects without site adapters.

### 4.1 Priority-aware JS/network budgets

Replace positional truncation in `JsStateCollector.harvest()`.

Within each admitted source object, allocate evidence in this order:

1. product/variant stable identity and parent relation;
2. requested field or atomic group;
3. option axes/values;
4. offer price + currency + availability;
5. SKU/MPN/GTIN namespaces;
6. variant assets;
7. descriptions and remaining images.

Budget outcomes must report dropped fact families and source paths, not only counts.

### 4.2 Explicit join diagnostics

When child evidence exists but cannot be attached to the same Variant/Offer entity, emit `join_failed` with:

- child evidence IDs;
- candidate parent IDs;
- missing/conflicting relation keys;
- source object/path;
- whether a budget removed a required key.

### 4.3 Preserve valid partial children

A stable variant with one missing optional field remains a child entity. Suppress the missing field, not the entire row. Require only the minimum identity/axis policy for public eligibility.

### 4.4 Default configuration policy

- one explicit child identical to the parent and without a differentiating option is diagnostic-only and may contribute derived parent commerce facts;
- multiple optionless children remain conflicted unless stable identity or an axis distinguishes them;
- never synthesize combinations from independent option lists.

### Regression targets

- DTLR 14 variants missing price/currency and SKU namespace mapping;
- Farfetch 4/4 missing offer;
- Puma India and Puma US missing variant SKU;
- Nike 24/24 missing variant availability;
- H&M offer/availability joins;
- Revolver Club partial child joins;
- the 9 originally confirmed no-variant pages;
- the 32 unproven no-variant pages must remain unforced.

### Acceptance

- All originally confirmed variant discovery/join issues are fixed or explicitly suppressed with a defensible reason.
- Evidence budgets never discard identity or a requested atomic offer group while retaining lower-priority imagery/description from the same source object.
- No Cartesian products.
- Every child field has lineage or an explicit field state.
- Variant-bearing clean controls regress by zero.

**Size:** L

---

## Slice 5 — Replace generic retries with field-scoped ResultAssessment

**Goal:** implement baseline-first enrichment without speculative page-wide escalation.

### 5.1 Central result checker

After Resolve and before publication commitment, evaluate:

- capture usability/completeness;
- requested-field state;
- selected-target identity;
- conflicts and joins;
- known template capability;
- drift;
- budgets.

Produce one typed `ResultAssessment`.

### 5.2 Field enrichment request

Add:

```python
class FieldEnrichmentRequest(FrozenModel):
    run_id: str
    surface: Surface
    template_signature: str | None
    selected_entity_id: str
    field_path: str
    current_state: FieldEvidenceState
    relevant_evidence_ids: tuple[str, ...] = ()
    allowed_capabilities: tuple[str, ...] = ()
    latency_budget_ms: int
    interaction_budget: int
    reason: str
```

One request covers one field or a tightly coupled atomic group such as price+currency.

### 5.3 Planner order

1. re-evaluate captured recognized evidence;
2. use an active validated contract path/relation;
3. fetch a known product-scoped endpoint;
4. render with the same canonical shadow-aware serializer;
5. wait for one known product-scoped element/response;
6. bounded field-specific interaction;
7. request contract/human assistance;
8. fail explicitly.

### 5.4 Delete broad retry behavior

Refactor `result_building.retry_request()`:

- no rendered retry merely because `requested_fields` is empty;
- no whole-page optional-field search;
- preserve acquisition retry for unusable captures and required baseline policy only;
- record negative capability outcomes to prevent repeated identical escalation.

### Acceptance

- A baseline run with all requested fields resolved performs zero enrichment.
- An unrequested optional-field gap performs zero browser render, interaction or LLM call.
- A missing requested field produces at most the configured field-scoped capability sequence.
- Every new artifact re-enters Harvest → Resolve → Publish.
- Interaction failure is an explicit state, never fabricated data.

**Size:** L

---

## Slice 6 — Add replay-validated template contracts, then bounded interaction

**Goal:** adapt unfamiliar templates declaratively after deterministic closure.

### Order

1. structural template signature;
2. versioned contract registry;
3. human-authored ContractDraft;
4. offline replay validator;
5. human approval and atomic activation/rollback;
6. drift/quarantine;
7. bounded interaction hints;
8. LLM ContractDraft proposals last.

### Contract capabilities

A contract may declare:

- source objects/paths;
- product-region and role hints;
- stable child relations;
- variant collection/option axes;
- asset grouping hints;
- `requires_shadow_flattening`;
- `requires_select_then_fetch` for named fields;
- expected structural signals for drift.

It may not create final values, ownership, publication authorization or persistence records.

### Replay gates

Every draft must pass:

- failing capture and all same-template captures;
- both 96-run partitions;
- 22 clean controls;
- contamination controls;
- variant-bearing controls;
- synthetic structural mutations;
- lineage, disposition, divergence, diagnostic-size and performance limits.

### LLM gate

Only after at least five unseen templates are corrected by human-created contracts with no Python rule changes should an LLM be allowed to propose the same strict ContractDraft schema. Initial activation remains human-approved.

### Acceptance

- At least one Category A/B template resolves with zero interaction after capture hardening.
- At least one Category D template resolves through a bounded select/fetch capability.
- Five unseen templates are corrected through contract data only.
- Contract activation causes zero clean-control regression.
- High-drift contracts quarantine automatically.
- Disabling a contract restores the generic path with no hidden state.

**Size:** L

---

## Slice 7 — Rollout and final deletion

### Rollout sequence

1. diagnostics only;
2. deterministic fixes in shadow comparison;
3. deterministic fixes active;
4. contract shadow mode;
5. human-approved contracts active;
6. bounded interaction active;
7. LLM proposals enabled, approval required.

### Delete or retire

After each gate, delete obsolete:

- broad retry branches replaced by ResultAssessment;
- selector self-heal/direct-record paths that bypass Evidence;
- duplicate serialization paths;
- legacy state names after schema migration;
- any export/persistence repair that changes semantic extraction values.

### Final acceptance

#### Corpus

- 96/96 latest and 96/96 previous replay, zero skips.
- Original confirmed defects fixed or explicitly suppressed for public policy.
- Capture failures classified as source unavailable, not extractor misses.
- Inconclusive cases remain honest; no synthetic values.
- 22 clean controls regress by zero.

#### Output

- cross-product assets/offers/variants: zero;
- duplicate public asset identities: zero;
- malformed public URLs: zero;
- raw HTML/entity leakage in canonical text: zero;
- published values without lineage: zero;
- evidence without a terminal disposition: zero;
- publication divergence: zero;
- divergent runs produce zero canonical records.

#### Performance

Re-baseline after Slice 1, then require:

- evidence p95 no more than 125% of the accepted post-fix baseline;
- Resolve p95 no more than 120%;
- diagnose p95 no more than 125%;
- every diagnose artifact under 1 MiB;
- browser interaction and LLM calls bounded and observable.

## 4. Recommended first implementation pull request

The first PR should contain **only Slice 1**:

1. typed capture/result assessment skeletons;
2. complete canonical field-state universe;
3. canonical failure-stage vocabulary;
4. run-report aggregation of findings/reasons;
5. grouped target-scoped offer diagnostics;
6. tests proving missing unrequested canonical fields remain visible.

This PR changes no extraction ranking. It makes every subsequent accuracy change measurable and prevents the latest run's diagnostic blind spot from masking regressions.
