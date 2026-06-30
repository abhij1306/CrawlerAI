# Ground-Truth Recall and Adaptive Contract Cutover Plan

**Created:** 2026-06-30  
**Agent:** Codex  
**Status:** TODO — start only after the predecessor Extraction Ownership and Accuracy Plan is complete  
**Predecessor:** Harvest → Resolve → Publish ownership and publication cutover  
**Primary surface for adaptive cutover:** ecommerce detail  
**Touches:** acquisition classification, extraction, resolution, diagnostics, contract registry, frontend review workflow, metrics  
**Does not replace:** the completed Harvest → Resolve → Publish architecture

## 1. Purpose

Complete the remaining extraction-quality work demonstrated by the audited 90-page corpus, then add a controlled adaptation layer that lets CrawlerAI learn unfamiliar site templates through replay-validated declarative contracts proposed by a human or an LLM.

The successor architecture is baseline-first and demand-driven:

```text
Normal run
  CaptureBundle
    → CaptureAssessment
    → Baseline Harvest
    → Resolve
    → Publish
    → ResultAssessment
          ├─ all requested fields satisfied → accept immediately
          └─ requested field unresolved
                 → FieldEnrichmentRequest
                 → cheapest known targeted capability
                 → new observational artifacts/evidence
                 → targeted re-Harvest/re-Resolve
                 → normal Publish and divergence gates

Successful requested-field enrichment
  → use once
  → or user promotes extraction strategy
  → replay-validated SiteTemplateContract
  → future runs call the known capability directly
  → optional later promotion into the default canonical path

Unknown or drifting template
  → AdaptationRequest
  → Human or LLM ContractDraft
  → Offline replay validation
  → Approved SiteTemplateContract
```

The normal run must not scan controls or click page elements merely because optional fields are absent. Browser rendering and interaction are escalation capabilities invoked only for an explicitly requested unresolved field, a required canonical field under an approved template policy, or a validated acquisition retry.

Contracts, humans, and LLMs must never write canonical records directly. They may help identify source objects, paths, regions, representation mappings, and interactions. Resolve remains the only semantic authority and Publish remains projection-only.

## 2. Ground-truth baseline

The HTML audit mapped all 90 URLs to `page.html`, `record.json`, and `diagnose.json`.

The supplied issue matrix contained 144 issue instances across 68 flagged URLs:

- 83 high-confidence engine/modeling defects across 45 URLs.
- 10 issue instances across 2 URLs caused by acquisition failure: StockX HTTP 403 and an Amazon CAPTCHA.
- 51 issue instances were inconclusive because the saved HTML did not prove the expected value or variant structure.

Confirmed defect families:

| Root cause | Instances |
|---|---:|
| Extractor omission or resolution | 37 |
| Variant field join/materialization | 13 |
| Variant discovery/materialization | 9 |
| Image identity deduplication | 8 |
| Default-variant modeling or option loss | 4 |
| Brand-role selection | 3 |
| Brand normalization | 3 |
| Product-boundary contamination | 2 |
| Identifier namespace mapping | 1 |
| Title ranking/normalization | 1 |
| Image URL sanitation | 1 |
| Title candidate conflict | 1 |

Important variant truth:

- 9 `no_variants` cases contain strong variant evidence and are confirmed failures.
- 32 `no_variants` cases contain no reliable variant evidence in saved HTML and are not confirmed failures.
- 2 cases contain only limited/single-option evidence and remain review cases.
- 4 optionless rows are default-configuration or option-axis modeling defects.
- 13 variant field defects contain source evidence but lose SKU, offer, currency, or availability during joining/materialization.

The 22 unflagged URLs are clean-control cases and must remain regression-free.

## 3. Predecessor completion gate

Do not begin this plan until Codex verifies all predecessor-plan requirements in the local checkout.

Required preconditions:

- All four surfaces expose only `harvest`, `resolve`, and `publish`.
- Every Evidence has exactly one terminal EvidenceDisposition.
- SelectedFact and DerivedFact lineage is complete.
- Semantic ownership, ranking, derivation, variant eligibility, asset selection, and publication disposition occur only in Resolve.
- Publish consumes only a surface-specific PublicationProjection.
- Exact publication comparison is blocking.
- Divergence produces zero canonical records and diagnostic-only output.
- Persistence does not repair, coerce, reroute, filter, or infer extraction values.
- Legacy semantic materializers, output-safety repairs, and public-firewall mutations are deleted.
- `extraction.v2` and `diagnose.v2` are active for new runs.
- The full backend suite, ruff, acquisition smoke, extraction smoke, and test-site acceptance commands pass.
- The local 90-site replay has zero skipped cases.
- No captures, URL manifests, corpus hashes, baselines, or derived corpus reports are tracked by Git.

If any precondition fails, finish the predecessor plan. Do not create a second transitional pipeline.

## 4. Core contracts added by this plan

### CaptureAssessment

```python
class CaptureAssessment:
    status: Literal[
        "usable",
        "blocked",
        "captcha",
        "status_error",
        "empty",
        "partial_shell",
        "wrong_content_type",
        "redirect_mismatch",
    ]
    reasons: tuple[str, ...]
    retry_capabilities: tuple[str, ...]
```

A non-usable capture cannot be converted into field-level `not_present` conclusions.

### ResultAssessment

```python
class ResultAssessment:
    outcome: Literal[
        "accept",
        "retry_with_rendered_capture",
        "request_interaction",
        "request_contract",
        "request_human_review",
        "reject_wrong_surface",
        "reject_ambiguous_target",
        "reject_source_unavailable",
    ]
    reasons: tuple[str, ...]
    unresolved_fields: tuple[str, ...]
```

### AdaptationRequest

Contains template signature, failure classification, unresolved fields, selected target, relevant evidence IDs, unresolved source objects, findings, available acquisition capabilities, and bounded diagnostic excerpts.

### SiteTemplateContract

A versioned declarative contract may contain:

- source-object and source-path locators;
- product-region hints;
- field representation mappings;
- role hints for brand, retailer, seller, offer, variant, and asset objects;
- explicit structural relation paths;
- variant collection and option-axis mappings;
- asset-gallery and responsive-image grouping hints;
- bounded interaction hints;
- expected structural signals for drift detection.

A contract may not:

- create final field values;
- select the target without identity validation;
- make unowned evidence owned;
- resurrect rejected evidence;
- override conflicts;
- authorize publication;
- suppress blocking findings;
- write persistence records;
- activate itself.

Contract-produced relation hints remain hypotheses until Resolve validates them against selected-target identity, explicit containment, stable IDs, or other admissible evidence.

### InteractionRequest

Contains bounded observational actions such as expanding a product section, selecting an option, capturing a changed DOM, or capturing matching network responses. Interaction produces new acquisition artifacts only; it never returns logical fields directly.


## 4A. Baseline-first requested-field enrichment and promotion

### Operating model

CrawlerAI already accepts requested fields. This feature becomes the control plane for expensive extraction.

Every run has two distinct paths:

1. **Baseline canonical extraction**
   - Run the cheap, general collectors over already acquired HTTP HTML, metadata, JSON-LD, microdata, embedded state, and existing network artifacts.
   - Resolve and publish all facts found through the normal pipeline.
   - Do not render, enumerate controls, inspect every accordion, or click elements solely to search for optional missing data.

2. **Requested-field enrichment**
   - Compare the published result and field states with the user’s requested fields.
   - Create enrichment work only for requested fields that remain unresolved, suppressed for remediable reasons, or marked interaction-required.
   - Select the cheapest validated capability for that field and template.
   - Feed newly acquired artifacts back through Harvest → Resolve → Publish.
   - Never patch the public record directly.

A requested field may be a standard canonical field such as price or availability. “Requested” controls when expensive enrichment is attempted; it does not create a separate unvalidated output channel.

### FieldEnrichmentRequest

```python
class FieldEnrichmentRequest:
    run_id: str
    surface: Surface
    template_signature: str | None
    selected_entity_id: str
    field_path: str
    current_state: FieldEvidenceState
    relevant_evidence_ids: tuple[str, ...]
    allowed_capabilities: tuple[str, ...]
    latency_budget_ms: int
    interaction_budget: int
    reason: str
```

The request must identify one field or one tightly coupled atomic group, such as price plus currency. It cannot request a generic “explore page” operation.

### EnrichmentPlanner

The planner chooses the lowest-cost admissible strategy in this order:

```text
1. Re-evaluate already captured recognized sources
2. Use a validated source path or relation from an active template contract
3. Fetch a known product-scoped HTTP/JSON endpoint
4. Capture a rendered DOM without interaction
5. Wait for a known product-scoped element or response
6. Perform a bounded, field-specific interaction
7. Request human/LLM contract assistance
8. Fail explicitly
```

The planner uses a `TemplateCapabilityProfile` containing field, acquisition mode, source locator, observed cost, success rate, contract version, and drift status.

It must not:

- scan every clickable element;
- use random or exploratory clicks;
- enumerate options when no requested field requires them;
- repeat a failed capability without changed evidence or policy;
- invoke an LLM when deterministic requested-field enrichment succeeds;
- turn an optional-field miss into whole-page browser escalation.

### Sigma-Aldrich example

```text
Baseline:
  HTTP HTML/structured sources
    → product identity, title, description, identifiers, images

Requested fields:
  price, availability

Gap assessment:
  price and availability unresolved

Known or newly discovered enrichment:
  product-scoped rendered state or JSON request
    → new price/availability evidence
    → normal Resolve and Publish

User promotion:
  approve the successful source locator/acquisition capability
    → template contract version created
    → replay validation
    → future Sigma-Aldrich runs call that capability directly
```

The user may promote the strategy in one of three modes:

- `conditional_on_request`: run only when the field is requested and missing;
- `default_for_template`: run on every matching template because the field is canonical and the cost is acceptable;
- `candidate_generic_rule`: evaluate across independent templates before adding a generic collector rule.

Promotion stores the extraction strategy, source relation, and acquisition capability—not the observed field value.

### Learning loop

```text
baseline miss for requested field
  → targeted enrichment succeeds
  → evidence resolves and publishes
  → user reviews lineage and result
  → promote successful strategy
  → replay validation
  → active versioned contract
  → future run skips discovery and directly uses known capability
  → drift monitoring can quarantine it
```

One-off results remain run-scoped unless promoted. A promoted contract can be rolled back. Repeated validated contract patterns may later become generic rules under Slice 10.

### No-speculative-interaction invariant

An interaction is admissible only when all are true:

- a specific requested or approved default field is unresolved;
- current evidence explains why the field cannot yet resolve;
- the proposed action is linked to that field;
- the action is product-scoped;
- the interaction and latency budgets permit it;
- the result will be captured as an artifact and re-enter the canonical pipeline.

“Click around and inspect what changes” is not a valid production acquisition strategy.


## 5. Implementation slices

### Slice 0 — Post-predecessor audit and residual ledger

**Goal:** determine what remains after the first plan rather than reimplementing fixes it already delivered.

- Record the local commit, dirty-tree fingerprint, test/config versions, and audit package version in ignored local output.
- Replay all 90 captures through the completed v2 pipeline.
- Compare the new outputs with the HTML audit findings.
- Produce an ignored residual ledger with one row per audited issue:
  - fixed;
  - still reproducible;
  - source unavailable;
  - not proven by captured source;
  - expected suppression;
  - ground-truth review required.
- Keep the 22 clean controls as a named partition.
- Mark already-fixed issues complete without adding new rules.
- Stop the successor plan if any failure is caused by incomplete predecessor ownership, lineage, publication, or legacy deletion.

**Verify**

- 90/90 captures replay; zero skips.
- Every audit issue has one residual disposition.
- No corpus-derived file appears in `git status`.
- Full predecessor verification remains green.

### Slice 1 — Capture-quality gate and centralized result checker

**Goal:** prevent acquisition failures and partial documents from becoming misleading extraction failures.

- Run `CaptureAssessment` before Harvest.
- Detect status failures, CAPTCHA/block pages, minimal shells, wrong content type, redirect mismatch, and unusable documents.
- Map unusable captures to `source_unavailable`, not `not_present_in_captured_sources`.
- Add one `ExtractionResultChecker` after Resolve and before Publish commitment.
- The checker evaluates requested-field completeness, ownership, unresolved conflicts, source cues, template drift, lineage, publication suppression, and interaction requirements.
- Replace scattered field-level retry decisions with ResultAssessment outcomes.
- Keep acquisition retry execution outside Resolve.

**Audit target**

- StockX and Amazon cases classify as acquisition failures.
- Their 10 issue instances do not count as extractor recall defects.
- No canonical records are emitted from blocked/CAPTCHA captures unless a later usable capture succeeds.

### Slice 2 — Diagnostic truth and failure-stage classification

**Goal:** identify the actual failing stage rather than collapsing every omission into “missing.”

Add field/entity states for:

- `source_unavailable`;
- `not_present_in_captured_sources`;
- `collector_missed`;
- `captured_unowned`;
- `captured_rejected`;
- `captured_conflicting`;
- `join_failed`;
- `captured_published`;
- `captured_suppressed`;
- `interaction_required`;
- `output_divergent`;
- `not_requested`.

- Compare generic audit-probe evidence with Harvest evidence in local acceptance tooling.
- When the probe finds recognized JSON-LD, metadata, microdata, or embedded-state evidence absent from Harvest, classify `collector_missed`.
- When Harvest contains evidence that Resolve rejects, retain the exact rejection reason.
- When child evidence exists but cannot be joined to a variant/entity, classify `join_failed`.
- Diagnose output sanitation separately from selection and resolution.
- Keep diagnostic examples bounded and under the existing size ceiling.

**Audit target**

- The 36 HTML-present missing-field omissions are assigned to collector, resolution, join, suppression, or sanitation stages.
- No HTML-present candidate is reported as source-not-present.
- Every recognized candidate retains one terminal EvidenceDisposition.

### Slice 3 — Confirmed scalar recall closure

**Goal:** close remaining high-confidence price, currency, availability, image, brand, and title omissions without site-specific code.

- Complete generic mappings for JSON-LD, Open Graph/product metadata, microdata, and embedded product-state keys encountered by recognized source shapes.
- Preserve dot, bracket, and slash source paths.
- Add offer-completeness to DOM-completion and interaction decisions:
  - selected product exists;
  - commerce cues exist;
  - no eligible current offer resolves;
  - therefore request additional capture/interaction rather than silently accepting a missing offer.
- Keep price and currency atomic at the offer level.
- Distinguish current, original, sale, member, installment, unit, shipping, and range prices.
- Resolve currency from the same offer first, then compatible product/variant context; locale/domain remains weak corroboration only.
- Use an explicit availability evidence ladder. Absence of evidence never becomes out of stock.
- Derive parent availability only from a complete eligible variant set.
- Add field-specific source quality so product-scoped structured evidence outranks host/title inference and generic page values.
- Do not add retailer/domain literals to production rules.

**Audit target**

- All remaining confirmed HTML-present scalar omissions are either published correctly or suppressed with an explicit, valid reason.
- No installment, original, unrelated, or recommendation price publishes as current price.
- Explicit captured availability is not silently lost.

### Slice 4 — Variant graph and default-configuration closure

**Goal:** resolve the dominant confirmed structural defects at variant grain.

Build or complete a typed variant graph inside Resolve:

```text
Product
  ├─ Variant
  │    ├─ OptionValue
  │    ├─ Offer
  │    └─ Asset
  └─ Parent Offer/Asset
```

- Join variant ID, option axes, SKU, offer, currency, availability, and images using stable source-object IDs and explicit relations.
- Never join independent field lists by position.
- Never synthesize a Cartesian product from option axes.
- Require selected-product ownership before variant eligibility.
- Preserve stable child entities even when one optional field is missing; suppress the field, not the whole valid row.
- Define default-configuration behavior:
  - one explicit child identical to the parent with no differentiating axis is retained diagnostically and suppressed as a redundant public variant;
  - its eligible commercial facts may derive parent facts with lineage;
  - multiple optionless children remain conflicted/review unless stable identity or a differentiating axis exists.
- Mark DOM controls with no captured child data as `interaction_required`.
- Emit one rejection reason per ineligible child.

**Audit target**

- The 9 confirmed `no_variants` cases publish the expected variant entities.
- The 13 confirmed variant-field join defects retain available SKU/offer/currency/availability evidence.
- The 4 optionless cases follow the default-configuration policy.
- The 32 unproven `no_variants` cases are not forced to emit variants.
- The 2 limited/single-option cases remain explicit review cases until stronger ground truth exists.

### Slice 5 — Asset, URL, identifier, brand, and title closure

**Goal:** close confirmed sanitation and role-selection defects within established semantic boundaries.

#### Assets

- Maintain separate asset identity and delivery URL.
- Collapse responsive/preset variants by structured media ID, source-container identity, original-path identity, and field-specific URL rules.
- Preserve delivery parameters required for the actual asset.
- Perform product/variant ownership before asset ranking.
- Reject recommendation, carousel, navigation, and unrelated browser/network-state assets.

#### URL sanitation

- Use registered field-specific URL canonicalizers.
- Repair duplicate query separators and malformed transform concatenation only as representation canonicalization.
- Preserve identity-bearing product/variant parameters.

#### Identifiers

- Model identifier namespace explicitly: merchant SKU, platform variant ID, style code, MPN, GTIN, barcode.
- Do not publish a platform variant ID as SKU when a merchant/style SKU is available.
- Do not reroute identifiers during Publish or persistence.

#### Brand and title

- Model organization roles: manufacturer brand, retailer, marketplace, seller, private label, collection, unknown.
- Publish manufacturer/private-label brand only when role evidence is admissible.
- Do not use hostname as brand truth.
- Apply versioned casing/spacing normalization after role resolution.
- Rank clean product names over model-only or review-author candidates when identity remains consistent.

**Audit target**

- All 8 duplicate-image cases collapse by asset identity.
- The malformed Glossier image query is canonicalized.
- Both cross-product contamination cases publish zero unrelated assets/offers/variants.
- DTLR identifier namespace is correct.
- All confirmed brand-role, brand-normalization, and title cases resolve correctly.

### Slice 6 — Site-template signature and contract runtime

**Goal:** add reusable site adaptation without building a second extractor or platform-adapter system.

Create a structural template signature using stable features:

- domain and surface;
- normalized URL pattern;
- JSON-LD types and nesting;
- embedded-state root names;
- recurring source-path shapes;
- DOM landmark/component structure;
- purchase-form and option-control topology;
- relevant network endpoint shapes.

Do not hash complete product content.

Add a versioned contract registry and resolver:

- lookup by domain, surface, URL pattern, and structural similarity;
- execute contract locators through normal collectors;
- emit normal Evidence and bounded contract diagnostics;
- validate every relation hint in Resolve;
- record contract ID/version in lineage;
- use normal publication and divergence gates.

Add static safety tests proving contracts cannot import or call final-record constructors, persistence writers, publication authorization, or semantic override APIs.

**Verify**

- A contract can improve candidate discovery without changing public values directly.
- Disabling a contract restores the generic path with no hidden state.
- Contract-assisted and generic evidence remain distinguishable in diagnostics.
- No site-specific Python adapter is introduced.

### Slice 7 — Replay validator and human-assisted adaptation

**Goal:** prove the adaptation model with humans before allowing LLM proposals.

Add a ContractDraft and offline replay service.

A human reviewer may select:

- source object/path;
- field type;
- structural region;
- organization/offer/asset role hint;
- variant collection/identity path;
- option axis;
- bounded interaction requirement.

The reviewer should not normally type a one-off final value.

Replay every draft against:

- the failing capture;
- all available captures matching the same template;
- clean controls;
- product-boundary contamination cases;
- variant-bearing cases;
- synthetic structural mutations.

Activation gates:

- requested-field improvement;
- zero clean-control regression;
- zero new contamination;
- zero publication divergence;
- complete lineage and evidence dispositions;
- performance and diagnose-size budgets remain within existing limits.

Contract lifecycle:

```text
proposed
→ replay_validated
→ human_approved
→ active
→ drift_detected
→ quarantined
→ repaired or deprecated
```

Activation and rollback must be atomic and versioned.

**Adaptive acceptance test**

Demonstrate at least five previously unseen templates that can be corrected by contract data only, with no production Python rule change. Where possible, validate each contract against at least three pages from its template.

### Slice 8 — Requested-field enrichment and bounded interaction

**Goal:** enrich only explicitly requested unresolved fields and eliminate random or page-wide exploratory clicking.

- Add `FieldEnrichmentRequest`, `EnrichmentPlanner`, and `TemplateCapabilityProfile`.
- Use the user’s existing requested-fields configuration to decide whether enrichment is needed.
- Complete the normal baseline run before planning expensive enrichment.
- Skip enrichment when all requested fields are already resolved.
- Select the cheapest known product-scoped capability.
- Permit rendered capture without interaction before allowing clicks.
- Allow Resolve or ResultAssessment to request only bounded actions tied to a field:
  - expand a known product section;
  - open a known size/color selector;
  - select a bounded option required to resolve a requested field;
  - capture the changed DOM;
  - capture a known or observed product-scoped network response.
- Newly acquired artifacts re-enter Harvest and Resolve; no action writes fields directly.
- Add negative capability memory so known failures are not retried on every run.
- Add user promotion controls:
  - use once;
  - conditional on request;
  - default for template;
  - candidate generic rule.
- Promotion creates a ContractDraft and must pass normal replay, ownership, lineage, divergence, and clean-control gates.
- Destructive, transactional, random, and unbounded actions are prohibited.
- Repeated-state and loop detection are mandatory.

**Verify**

- A baseline run with no missing requested fields performs zero enrichment actions.
- An optional unrequested field performs zero browser escalation.
- A missing requested field triggers at most the configured bounded capability sequence.
- Hidden price/availability or variant evidence can be acquired and re-enters normal lineage.
- A promoted strategy is used directly on the next matching run without rediscovery.
- Interaction failure becomes an explicit field state, not fabricated data.
- Variant enumeration cannot exceed configured budgets.

### Slice 9 — LLM ContractDraft proposals

**Goal:** use the LLM as a site-architecture interpreter, not as a canonical record generator.

Only begin after Slice 7 proves human-created contracts.

Provide bounded context:

- template structural summary;
- source-path inventory;
- selected-target diagnostics;
- evidence graph excerpts;
- unresolved fields;
- competing roots;
- relevant DOM/source excerpts;
- available interaction observations.

The LLM returns only:

- ContractDraft;
- explanation;
- confidence;
- unresolved questions;
- optional InteractionRequest proposal.

Safety:

- page content is untrusted data and cannot supply model instructions;
- strict structured output schema;
- no direct record/value persistence;
- no ownership override;
- no publication authorization;
- no automatic activation initially;
- model, prompt, provider, and contract schema versions are logged;
- redact secrets and unrelated page content;
- enforce token, cost, and call budgets;
- invoke only after deterministic ResultAssessment requests adaptation.

Human approval remains mandatory for target/root hints, ownership-sensitive relations, variants, brand roles, and interaction sequences. Later auto-approval may be considered only for equivalent path/alias changes that pass all replay gates.

### Slice 10 — Drift detection, shadow comparison, and generic promotion

**Goal:** prevent learned contracts from becoming silent brittle adapters.

For each active template contract, monitor:

- locator success;
- selected-target stability;
- accepted/rejected/unowned evidence ratios;
- requested-field completeness;
- generic-versus-contract disagreement;
- contamination findings;
- template structural distance;
- interaction requirements;
- runtime and evidence volume.

Outcomes:

- low drift: use normally;
- moderate drift: run generic discovery in shadow and flag review;
- high drift: quarantine contract and use generic fail-closed behavior;
- new template: create AdaptationRequest.

Sample dual execution:

```text
generic Harvest/Resolve
versus
contract-assisted Harvest/Resolve
```

Use comparison for diagnostics and reliability, not two publication paths.

Promote a repeated pattern into generic code only when:

- several independent validated contracts express the same structural rule;
- broad local replay passes;
- clean controls do not regress;
- precision and ownership invariants remain intact;
- redundant contracts can be retired.

### Slice 11 — Consumers, rollout, deletion, and documentation

- Extend `diagnose.v2` with CaptureAssessment, ResultAssessment, AdaptationRequest, contract ID/version, replay result, drift state, interaction outcome, and per-stage failure states.
- Add frontend diagnostics for evidence/source paths, entity ownership, rejection reasons, proposed contract rules, replay diffs, approval, quarantine, and rollback.
- Keep corpus-specific URLs and expected values out of production UI/config.
- Add metrics for:
  - capture usability;
  - collector miss;
  - captured rejection;
  - join failure;
  - interaction requirement;
  - contract request/success;
  - replay rejection reason;
  - drift/quarantine;
  - generic-versus-contract disagreement;
  - LLM proposal acceptance.
- Roll out ecommerce detail first:
  1. diagnostics only;
  2. contract shadow mode;
  3. human-approved contracts active;
  4. bounded interaction active;
  5. LLM proposals enabled but approval-required.
- Extend contract capabilities to ecommerce listing, job detail, and job listing only after ecommerce-detail gates pass.
- Delete obsolete selector self-heal, site-memory, or direct-record LLM paths that bypass this lifecycle.
- Update architecture, invariants, ownership, diagnostics, security, and operator documentation.

## 6. Acceptance criteria

### Corpus execution

- 90/90 captures replay with zero skips.
- All 83 confirmed engine/modeling issue instances are fixed or explicitly suppressed for a documented public-policy reason.
- The 10 capture-failure issue instances classify as source unavailable and do not distort extraction recall.
- The 51 inconclusive instances are not converted into synthetic values or false failures.
- The 22 clean controls regress by zero.

### Variants

- All 9 confirmed missing-variant cases are resolved.
- All 13 confirmed variant join/materialization defects preserve available child evidence.
- All 4 optionless/default cases follow the explicit default-configuration policy.
- Unproven variant expectations do not create variants.
- No Cartesian-product variants.
- Every child field has lineage or an explicit field state.

### Scalars and roles

- Every recognized captured current offer is published, conflicted, or suppressed with reason.
- Explicit captured availability is not silently lost.
- Parent availability is derived only from sufficiently complete eligible child evidence.
- Retailer, marketplace, seller, and hostname values do not publish as manufacturer brand without admissible role evidence.
- Identifier namespaces remain distinct.

### Assets and safety

- Cross-product assets, offers, and variants: zero.
- Duplicate public asset identities: zero.
- Malformed public URLs caused by canonicalization: zero.
- Published values without lineage: zero.
- Evidence without terminal disposition: zero.
- Publication divergence: zero.
- Divergent runs produce zero canonical records.
- Contracts and LLMs cannot create ownership or final values.

### Baseline and enrichment efficiency

- Baseline extraction performs no speculative interaction.
- Optional unrequested field gaps do not trigger browser rendering, interaction, or LLM calls.
- Enrichment starts only for an explicit requested field or a field enabled by an approved `default_for_template` policy.
- Every enrichment operation is attributable to one field or atomic field group.
- Already resolved requested fields perform zero additional work.
- The planner always attempts cheaper validated capabilities before browser interaction.
- Failed capabilities are remembered and are not retried without drift, policy, or evidence change.
- Successful user promotion eliminates rediscovery on subsequent matching runs.
- One-off enrichment values never become template rules without promotion and replay validation.

### Adaptive capability

- At least five unseen templates are corrected through replay-validated contract data without production Python changes.
- Contract activation introduces zero clean-control regression.
- High-drift contracts quarantine automatically.
- LLM output never enters canonical persistence directly.
- Every active contract can be rolled back to a previous version.

### Performance

Retain predecessor limits unless the new local baseline is stricter:

- p95 evidence count no more than 125% of baseline.
- p95 Resolve duration no more than 120% of baseline.
- p95 diagnose size no more than 125% of baseline.
- Every diagnose artifact no more than 1 MiB.
- Interaction and LLM budgets are bounded and observable.

## 7. Local-only artifacts

Store under ignored `backend/artifacts/` or the project’s established ignored artifact directory:

- predecessor completion audit;
- 90-site residual ledger;
- ground-truth acceptance report;
- contract replay reports;
- template signatures;
- contract drift reports;
- LLM proposal evaluations;
- performance baselines;
- corpus hashes and URL mappings.

Never commit captures, audit outputs, URL manifests, corpus hashes, or site-specific expected values.

Generic schemas, safety tests, audit harnesses, and synthetic fixtures may be committed when they contain no site/corpus literals.

## 8. Final verification

Run the project’s canonical frontend commands plus:

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Add a local, ignored acceptance command that replays the 90-site bundle against the audit package and fails on confirmed-defect, clean-control, lineage, divergence, or skip regressions.

The plan is complete only when all slices, corpus gates, adaptive-contract demonstrations, architecture ratchets, frontend diagnostics, and documentation checks pass.

## 9. Explicit non-goals

- No universal guarantee for arbitrary future markup.
- No retailer-specific Python adapters or domain literals.
- No direct page-to-record LLM extraction in the canonical pipeline.
- No hot-path LLM call on successful deterministic extraction.
- No automatic LLM contract activation in the initial cutover.
- No random, exploratory, or page-wide clicking to search for missing fields.
- No browser escalation for optional fields that the user did not request.
- No promotion of observed values; only validated extraction strategies may be promoted.
- No semantic repair in Publish or persistence.
- No synthetic variants from option-axis Cartesian products.
- No forced “fix” for the 32 unproven no-variant cases.
- No second legacy/new extraction pipeline.
