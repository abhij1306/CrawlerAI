# CrawlerAI Adaptive Extraction, Normalization, and Learning Architecture

**Status:** Revised architecture after critique audit  
**Scope:** Page classification, extraction, entity binding, normalization, validation, template learning, drift detection, repair, and operator workflows  
**Primary objective:** Extract and normalize commerce and job data accurately across known and unseen page templates while becoming cheaper, more deterministic, and easier to operate as the system learns.

---

## 1. Scope Boundary

CrawlerAI receives a prepared **Extraction Input Bundle** from an upstream subsystem.

The upstream subsystem is responsible for producing the available page artifacts. This architecture does not prescribe how those artifacts are produced, transported, refreshed, or recovered.

The extraction system begins only after an input bundle exists.

An input bundle may contain any available combination of:

- page URL and stable request identity;
- HTML or DOM snapshot;
- structured metadata;
- embedded application state;
- structured response payloads;
- screenshot or visual-region references;
- interaction-state identifier;
- timestamp;
- language, market, currency, tax, unit, and timezone context;
- upstream completeness and provenance indicators.

CrawlerAI may report that the supplied bundle is insufficient for a required field, but it must not alter or control the upstream subsystem.

---

## 2. Executive Decision

CrawlerAI should not be built as either:

- a continuously growing collection of manually maintained selectors and site-specific conditionals; or
- a general-purpose LLM that reads every page and directly emits final records.

The recommended product is a **hybrid extraction learning system**:

1. Resolve the page type, structural template, market, and applicable execution manifest.
2. Use a compiled template recipe when a trusted recipe exists.
3. Validate the recipe using field semantics, entity integrity, and anti-contamination rules.
4. Continuously challenge a risk-adjusted sample of recipe executions with the universal extractor.
5. Use structured-source adapters and generic deterministic collectors when no recipe is available.
6. Build a compact DOM-and-layout representation only when the universal ML path is required.
7. Use grounded LLM or vision assistance for cold-start, ambiguity, custom fields, and repair—not as the default bulk parser.
8. Convert successful adaptive extraction and operator corrections into reusable recipe layers and training examples.
9. Normalize, validate, and publish through explicit field policies rather than embedding business meaning inside selectors.

CrawlerAI should therefore learn in two directions:

- **generalize outward** through a reusable cross-domain extractor;
- **specialize downward** through scoped, compiled extraction recipes.

The expected steady state is that common known templates run through a small deterministic fast path, while unfamiliar or changed templates progressively receive more capable processing.

---

## 3. Critique Audit and Decisions

### 3.1 Accepted changes

The following critique recommendations are valid and are incorporated:

- Sentinel testing for known-template recipes;
- an explicit onboarding bootstrap state machine;
- locale- and market-aware normalization and validation;
- hierarchical recipe inheritance with strict scope isolation;
- lazy creation of the compact page representation;
- one atomic scoped execution manifest for each active domain-template-market combination;
- an explicit ML inference deployment strategy;
- defined behavior for records waiting for human review.

### 3.2 Accepted with modification

#### Sentinel challenger output is not ground truth

The universal extractor is an independent challenger, not an unquestioned authority. A disagreement between the recipe and challenger is a drift signal that must be adjudicated using:

- source grounding;
- field semantics;
- visible-value agreement where available;
- historical consistency;
- entity ownership;
- operator labels;
- template-specific invariants.

The challenger must never silently replace a validated recipe value merely because its model score is higher.

#### Component versions remain internally traceable

The runtime and operator experience use one **Scoped Execution Manifest** as the atomic release unit. Internal model, policy, recipe, and validator hashes remain recorded for reproducibility, but operators do not manage seven independent micro-releases.

#### Review timing is a policy, not a hard-coded architectural constant

The architecture defines what happens while a record is awaiting review and what happens when its review deadline expires. The exact queue target is configurable by client, contract, field criticality, and operating model.

### 3.3 Outside this document

All page-artifact production and upstream execution choices are intentionally outside this architecture.

---

## 4. Product Objective

A non-specialist operator should be able to provide:

- one or more seed examples;
- the expected page type;
- a versioned field contract;
- optional custom fields;
- sample expectations where known.

CrawlerAI should then:

1. identify structural templates and market variants;
2. extract standard and custom fields;
3. construct the correct product, offer, variant, job, employer, and location records;
4. normalize values to a canonical schema;
5. show a business-readable preview;
6. allow visual correction without requiring selector authoring;
7. compile accepted corrections into a scoped recipe;
8. test the recipe on representative examples;
9. activate it through a gated manifest;
10. continuously detect silent semantic drift;
11. escalate only genuinely ambiguous or unsupported cases.

Operators should not need to understand XPath, graph algorithms, model serving, source-lineage groups, or selector syntax.

---

## 5. Architectural Principles

### 5.1 Adaptive discovery, controlled publication

Discovery may use:

- deterministic parsers;
- generic heuristics;
- cross-domain ML models;
- LLM reasoning;
- visual grounding;
- operator labels.

Publication requires:

- source-grounded evidence;
- an immutable execution manifest;
- deterministic canonicalization for standard primitives;
- explicit field-semantic policies;
- deterministic critical validations;
- an explicit trust decision.

Probabilistic extraction is acceptable. Ungrounded publication is not.

### 5.2 Expensive reasoning must produce reusable assets

A higher-cost model invocation is justified when it creates one or more reusable outputs:

- a confirmed page classification;
- a structural-template label;
- a record-boundary label;
- field-bearing-node labels;
- an entity relationship correction;
- a custom-field mapping;
- a recipe proposal;
- a regression example;
- a training example for the universal extractor.

Repeatedly paying a large model to rediscover the same stable structure is architectural waste.

### 5.3 Recipe success is not proof of semantic correctness

A recipe can match every selector and still produce the wrong record or semantic role.

Examples include:

- a recommendation price selected as the primary product price;
- a parent price assigned to all variants;
- an original price selected as current price;
- a thumbnail from a carousel assigned to the wrong variant;
- a localized tax-exclusive amount published where tax-inclusive price is required.

Therefore, successful recipe execution must still pass semantic, entity, locale, and Sentinel checks.

### 5.4 Source priority is field- and template-specific

There is no universal source order.

For one template:

- structured metadata may be reliable for canonical URL;
- embedded state may be reliable for variants;
- visible page content may be reliable for the displayed sale price;
- a product payload may contain internal images that must be filtered.

Source selection is expressed through field policy and recipe evidence, not one global precedence chain.

### 5.5 Normalization is not extraction

The following are separate operations:

1. locate `1.299,00 €`;
2. determine that it is the current price for the selected variant;
3. parse it into decimal `1299.00`;
4. resolve currency as `EUR`;
5. determine whether tax is included;
6. map it to the target output field.

Each operation must be independently testable.

### 5.6 Complex entity assembly is conditional

Most detail pages contain one primary entity. Most list pages contain repeated flat records.

Complex assembly runs only when signals indicate:

- variants or option axes;
- multiple offers;
- parent-child products;
- conflicting identifiers;
- source objects requiring joins;
- locale-specific offer structures.

The default path must not build a universal graph for every page.

### 5.7 Template structure and market semantics are separate dimensions

A structural template may be shared across markets while:

- currency;
- tax display;
- decimal separators;
- availability labels;
- date formats;
- units;
- legal text;
- price composition

vary by locale.

The system must not duplicate structural recipes merely because text or currency changes. It must also not assume that one normalization policy applies to all markets sharing the same layout.

### 5.8 Progressive disclosure for operators

The default UI communicates:

- what was found;
- what is missing;
- whether values match expected page meaning;
- what changed;
- what the system proposes;
- whether activation is safe.

Technical evidence is available in an advanced view.

### 5.9 A persistent knowledge graph is optional

The extraction product needs:

- an ephemeral page-level relationship model;
- durable canonical record identifiers;
- typed relational links.

PostgreSQL, JSONB, and object storage are sufficient for the core architecture. A separate graph system should be introduced only if later cross-page or cross-domain entity-fusion use cases justify it.

---

## 6. System Architecture

CrawlerAI consists of three planes, one evidence layer, and one continuous learning loop.

```text
┌──────────────────────────────────────────────────────────────────────┐
│ Product Plane                                                        │
│ Bootstrap wizard · visual correction · review · activation · drift   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ labels, approvals, policy
┌───────────────────────────────▼──────────────────────────────────────┐
│ Control and Learning Plane                                           │
│ Template discovery · recipe synthesis · replay · Sentinel analysis   │
│ model training · evaluation · manifest compilation · promotion       │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ immutable Scoped Execution Manifest
┌───────────────────────────────▼──────────────────────────────────────┐
│ Runtime Extraction Plane                                             │
│ classify → route → extract → bind → normalize → validate → project   │
└───────────────────────────────┬──────────────────────────────────────┘
                                │
┌───────────────────────────────▼──────────────────────────────────────┐
│ Evidence and Evaluation Layer                                        │
│ grounded evidence · accepted labels · sampled artifacts · metrics    │
└──────────────────────────────────────────────────────────────────────┘
```

### 6.1 Product Plane

Responsible for:

- guided onboarding;
- business-readable previews;
- visual correction;
- template and market approval;
- review queues;
- activation gates;
- Sentinel drift alerts;
- rollback and retirement.

### 6.2 Control and Learning Plane

Responsible for:

- structural-template clustering;
- recipe proposal generation;
- deterministic recipe compilation;
- representative sample selection;
- replay and current-sample evaluation;
- Sentinel disagreement analysis;
- cross-domain model training;
- field-policy evolution;
- manifest creation;
- canary and promotion decisions.

### 6.3 Runtime Extraction Plane

Responsible for:

- page and surface classification;
- structural-template matching;
- recipe execution;
- generic structured-source extraction;
- universal ML fallback;
- bounded entity assembly;
- canonicalization;
- semantic resolution;
- validation;
- trust assignment;
- output projection;
- evidence and metric emission.

The runtime cannot edit, promote, or activate a recipe.

### 6.4 Evidence and Evaluation Layer

Stores only what is needed for:

- field auditability;
- review;
- drift detection;
- regression testing;
- model learning;
- reproducibility.

It does not retain every raw artifact and rejected candidate indefinitely.

---

## 7. Core Input Contracts

### 7.1 ExtractionInputBundle

Contains:

- `bundle_id`;
- `url`;
- `observed_at`;
- one or more content artifacts;
- artifact provenance and completeness indicators;
- structured metadata objects;
- structured payload references;
- visual references when available;
- `execution_context`;
- upstream warnings.

The extraction runtime treats the bundle as immutable.

### 7.2 ExecutionContext

Contains the semantic environment required for extraction and normalization:

- language;
- country or market;
- expected currency or currencies;
- timezone;
- tax-display mode when known;
- unit system;
- host and subdomain;
- channel or storefront identifier;
- personalization cohort when supplied;
- interaction-state identifier when supplied.

Unknown context values are permitted, but inferred values must be recorded as inferred rather than supplied.

### 7.3 FieldContract

Defines:

- canonical field;
- value type;
- semantic role;
- entity scope;
- cardinality;
- requiredness;
- criticality;
- output name;
- row granularity;
- validators;
- allowed partial-publication behavior;
- review policy.

---

## 8. Runtime Extraction Cascade

The runtime must execute the least expensive path capable of satisfying the field contract safely.

### Stage 0: Resolve Scoped Execution Manifest

Resolve an immutable manifest using:

- domain;
- structural template;
- page surface;
- market or locale scope;
- contract;
- optional constrained exception.

The manifest is the only runtime release identifier exposed operationally.

### Stage 1: Classify Page and Structural Template

Determine:

- product detail;
- product list;
- category or navigation list;
- job detail;
- job list;
- unsupported or irrelevant surface;
- structural-template identity;
- market-layout variant where relevant.

Template matching uses stable structural features and available source-shape signals. Localized text and price values should not dominate the fingerprint.

### Stage 2: Known-Template Recipe Fast Path

When a trusted compiled recipe applies:

1. execute its field collectors and local joins;
2. create only the minimal evidence needed for selected fields and critical conflicts;
3. canonicalize standard primitives;
4. apply locale and field-semantic policies;
5. validate entity integrity and recommendation exclusion;
6. apply Sentinel sampling policy;
7. publish only if the trust gate passes.

The fast path must not build the universal page representation unless:

- the recipe fails;
- a critical warning is raised;
- the page is selected for Sentinel challenge;
- the manifest explicitly requires a universal-model field.

### Stage 3: Generic Structured and Deterministic Path

When no trusted recipe exists, or when the recipe falls through, run bounded generic collectors over the artifacts already present in the input bundle.

Collectors may include:

- Schema.org objects;
- Open Graph and metadata;
- embedded state adapters;
- known platform-shape adapters;
- repeated-block detection;
- generic URL, identifier, image, label-value, and price heuristics.

These collectors emit evidence candidates, not unquestioned final values.

A syntactically valid structured object must still pass:

- page-type agreement;
- identity ownership;
- recommendation exclusion;
- current-versus-original-price semantics;
- market and currency coherence;
- entity-binding validation.

### Stage 4: Universal ML Fallback

Build the compact page representation only after the earlier paths fail to satisfy the contract or when the page is selected as a Sentinel challenger.

The representation contains only visible or semantically relevant nodes and bounded structured objects.

A node may contain:

- stable node ID;
- normalized tag or object type;
- bounded text;
- selected attributes;
- URL or image reference;
- parent and sibling relationships;
- repeated-block membership;
- bounding box when available;
- visibility state;
- style and emphasis buckets;
- nearby labels;
- source lineage;
- market-sensitive token features.

The universal extractor predicts:

- page content type;
- primary entity region;
- repeated record boundaries;
- field-bearing nodes or paths;
- recommendation and boilerplate regions;
- basic product-offer-variant or job-employer-location relationships.

The initial implementation should favor compact CPU-efficient models over large generative models for high-volume standard fields.

### Stage 5: Grounded LLM or Vision Assistance

Use a grounded model when:

- a new template remains ambiguous;
- a low-frequency custom field is requested;
- standard candidates have unresolved semantic roles;
- an operator correction must be converted into a recipe proposal;
- a difficult visual relationship cannot be represented adequately by generic features.

The model receives only:

- the target schema;
- the compact relevant representation;
- bounded structured objects;
- referenced screenshot regions when available;
- existing evidence candidates;
- operator labels when present.

The output must include:

- proposed value;
- evidence node or path references;
- entity reference;
- semantic role;
- uncertainty reason;
- optional recipe-diff proposal.

Ungrounded values are rejected.

### Stage 6: Bounded Entity Assembly

Select one of three modes.

#### Flat detail mode

One primary product or job, plus optional offers, images, employer, or location.

#### Repeated-list mode

Repeated records with local field binding inside each detected record boundary.

#### Variant mode

Parent product, option axes, variants, offers, and variant-owned assets.

Variant mode uses at most two deterministic binding passes:

1. resolve identity, option, and source-object anchors;
2. bind remaining fields and validate ownership and relationships.

If the page remains ambiguous, return `needs_review`; do not run an open-ended graph convergence loop.

### Stage 7: Canonicalization and Semantic Resolution

Convert raw evidence into typed comparable values while retaining raw input.

Resolve:

- money and currency;
- URL;
- identifier;
- date and time;
- availability;
- quantity;
- boolean;
- option names and values;
- units and dimensions.

Field meaning is determined through explicit field policies rather than a single global ranking score.

### Stage 8: Validation and Trust Decision

Apply:

- contract validation;
- field-semantic validation;
- entity-integrity validation;
- recommendation and cross-sell contamination checks;
- cross-source consistency;
- market, currency, tax, unit, and date coherence;
- historical and distribution guards;
- record-count and variant-count guards;
- Sentinel concordance policy when sampled.

Produce one trust state:

- `verified`;
- `verified_with_warning`;
- `needs_review`;
- `unsafe`;
- `unsupported`.

### Stage 9: Projection and Output

Project canonical entities into the requested row granularity only after the trust decision.

The system must not invent fields to satisfy schema completeness.

---

## 9. Sentinel Testing and Anti-Drift Gating

### 9.1 Purpose

Sentinel testing protects the cheap recipe path from silent semantic drift caused by:

- A/B experiments;
- personalized components;
- promotional injections;
- market-specific changes;
- recommendation modules;
- structurally similar but semantically different templates;
- selectors continuing to match after content ownership changes.

### 9.2 Two levels of protection

#### Level A: Invariant validation on every recipe execution

Every fast-path result must pass local checks such as:

- primary entity identity exists;
- selected price belongs to the primary entity or variant;
- current price and original price roles are coherent;
- recommendation regions are excluded;
- record and variant counts are plausible;
- required fields are grounded;
- currency matches execution context or has an explicit exception;
- critical field source has not changed unexpectedly;
- duplicate identities are absent.

#### Level B: Challenger extraction on sampled traffic

A risk-adjusted percentage of recipe executions is also processed by the universal extractor.

The default sampling range may be 1–5%, but the rate is a policy, not a fixed constant.

Increase sampling when:

- the structural fingerprint changes;
- a critical field changes source or node region;
- the recipe was recently activated;
- the template has a history of drift;
- a new market or locale is introduced;
- local validation warnings increase;
- a platform-layer recipe changes.

Reduce sampling only after sustained concordance.

Low-volume templates should use a fixed representative Sentinel set in addition to random sampling.

### 9.3 Comparison contract

Compare recipe and challenger at the semantic level, not only string equality:

- primary entity identity;
- record boundaries;
- current and original price roles;
- normalized values;
- currency and tax context;
- variant identity and count;
- availability;
- image ownership;
- canonical URL;
- recommendation exclusion;
- grounding location;
- null and fallback behavior.

### 9.4 Disagreement handling

Classify disagreements:

- **benign:** formatting or equivalent normalized values;
- **warning:** source changed but value and ownership remain consistent;
- **material:** different value or entity association for a non-critical field;
- **critical:** different primary identity, price role, availability, variant binding, or required field.

The challenger is not automatically correct.

For a sampled page:

- benign disagreement does not block publication;
- warning disagreement is recorded and contributes to rolling drift metrics;
- material disagreement may route that record to full resolution or review depending on policy;
- critical disagreement blocks automatic `verified` status and triggers adjudication.

### 9.5 Rolling drift state

Maintain by template, market, and manifest:

- recipe-challenger concordance;
- critical disagreement rate;
- source-change rate;
- entity-identity disagreement;
- price-role disagreement;
- variant-count disagreement;
- validation-warning trend.

Template drift states:

- `stable`;
- `watch`;
- `suspected_drift`;
- `confirmed_drift`;
- `recipe_suspended`.

A recipe may be automatically suspended when policy-defined critical thresholds are exceeded.

### 9.6 Sentinel limitations

Sentinel testing is not a substitute for ground truth because both the recipe and universal model can be wrong.

The adjudication hierarchy is:

1. explicit operator label or approved evaluation truth;
2. deterministic semantic and ownership constraints;
3. agreement with trusted template history and current representative samples;
4. independent evidence sources;
5. recipe-versus-challenger comparison.

---

## 10. Hierarchical Recipe Architecture

### 10.1 Recipe layers

Use an immutable recipe hierarchy:

```text
Platform Base Layer
        ↓
Domain Overlay
        ↓
Structural Template Overlay
        ↓
Market / Locale Overlay
        ↓
Constrained URL Exception
```

Each layer may add or override only explicitly permitted elements.

### 10.2 Layer responsibilities

#### Platform Base Layer

Contains reusable semantics for a recognizable platform family:

- known object shapes;
- standard identity relationships;
- common variant structures;
- generic exclusions;
- safe candidate collectors.

It must not assume authority over every merchant implementation.

#### Domain Overlay

Contains merchant-wide adjustments:

- custom application-state shape;
- domain-specific entity identifiers;
- recurring content exclusions;
- stable source preferences.

#### Structural Template Overlay

Contains layout-specific behavior:

- primary record boundary;
- field locators;
- local joins;
- recommendation exclusions;
- variant mapping;
- template-specific validations.

#### Market / Locale Overlay

Contains semantic differences that do not require duplicating structure:

- expected currencies;
- localized availability mappings;
- date and number formats;
- tax-display rules;
- unit conventions;
- market-specific labels;
- regional price policies.

#### Constrained URL Exception

Used only for narrow, explicitly bounded cases that cannot be represented safely at a broader scope.

### 10.3 Isolation rules

- A lower layer cannot mutate a higher layer.
- A local correction creates a new overlay version; it never edits the shared base.
- Platform-layer changes require affected-domain discovery and broad regression testing.
- Domain and template changes are tested only across their actual blast radius.
- Override precedence is explicit and field-specific.
- Ambiguous merge conflicts fail manifest compilation.

### 10.4 Runtime compilation

The control plane resolves the active layers into one **Compiled Recipe** before activation.

The runtime does not repeatedly traverse and merge the hierarchy for every page.

The compiled recipe records:

- flattened extraction steps;
- field-source policy;
- joins;
- exclusions;
- market policy references;
- validators;
- recipe-layer provenance;
- compatibility hash.

This preserves inheritance without adding runtime complexity.

---

## 11. Structural Template and Locale Resolution

### 11.1 Structural fingerprint

A fingerprint should emphasize stable shape signals such as:

- normalized route family;
- visible DOM hierarchy;
- repeated-block geometry;
- stable attributes and component signatures;
- source-object shape;
- variant-shape indicators;
- placement relationships between key regions.

Avoid over-weighting:

- translated text;
- product-specific values;
- currency symbols;
- temporary campaign labels;
- personalized recommendation contents.

### 11.2 Collision protection

A broad platform match is not sufficient to select a merchant recipe.

Template resolution uses:

1. platform-family evidence;
2. domain scope;
3. structural-template fingerprint;
4. page surface;
5. market and locale context;
6. optional cohort or state key.

If two templates collide, the runtime uses a provisional classification and avoids automatic recipe publication until a safe match is resolved.

### 11.3 Market handling

The same structural template may resolve to different market overlays.

Examples:

- a UK storefront expects GBP and tax-inclusive pricing;
- a German storefront uses EUR, decimal commas, and localized availability;
- a US storefront may show tax-exclusive price and imperial units;
- a cross-border storefront may display both local and base currency.

Locale handling belongs to the field-policy and overlay system, not ad hoc selector logic.

### 11.4 Unknown context

When market context is missing:

- infer only from grounded evidence;
- record the inference and supporting evidence;
- reject ambiguous currency symbols when country cannot be established;
- use `needs_review` for critical unresolved tax or currency semantics.

---

## 12. Page Representation and Resource Efficiency

### 12.1 Lazy construction

Do not build the full compact page representation for:

- successful non-sampled recipe executions;
- simple structured-source results that pass all trust gates;
- pages rejected as irrelevant by a lightweight classifier.

Build it only for:

- universal ML fallback;
- Sentinel challenge pages;
- grounded LLM or visual assistance;
- operator correction;
- sampled evaluation cases.

### 12.2 Bounded representation

Apply limits for:

- number of nodes;
- text length per node;
- selected attributes;
- structured object size;
- screenshot regions;
- repeated blocks;
- candidate count per field.

Prioritize:

- visible content;
- primary and repeated entity regions;
- semantically labelled areas;
- price, identifier, image, option, title, and availability candidates.

Exclude or heavily down-rank:

- analytics;
- hidden templates;
- unrelated navigation;
- large script bodies after relevant objects are isolated;
- duplicate representations;
- obvious advertising and recommendation regions.

### 12.3 Representation caching

Cache by:

- input artifact hash;
- representation-schema version;
- market-sensitive context hash.

A representation may be reused by:

- the universal model;
- Sentinel comparison;
- recipe synthesis;
- operator review;
- regression evaluation.

---

## 13. ML Inference Strategy

### 13.1 Initial deployment choice

Use a **shared, versioned inference pool in the same cluster or region as extraction workers** for the universal extractor.

Reasons:

- the model is loaded once per serving instance rather than once per extraction worker;
- requests can be micro-batched;
- model rollout and rollback are isolated;
- memory usage scales with inference capacity rather than worker count;
- the service can autoscale independently;
- model telemetry is centralized.

### 13.2 Latency control

To limit service overhead:

- send only the compact representation;
- use a binary schema such as Protobuf or MessagePack;
- keep the service network-local;
- cache inference by representation hash and model version;
- use micro-batching with a strict latency ceiling;
- avoid universal inference on successful unsampled fast-path pages.

### 13.3 Local inference option

Permit local in-process or sidecar inference only when benchmarking shows that:

- the model is sufficiently small;
- worker concurrency does not create unacceptable memory duplication;
- local latency materially improves end-to-end cost or throughput.

This is a deployment optimization behind a stable model interface, not a change to extraction semantics.

### 13.4 Grounded LLM serving

LLM and vision reasoning should use a separately governed service because it has different:

- cost;
- latency;
- privacy;
- schema enforcement;
- retry;
- audit;
- model-version requirements.

It must not sit on the normal known-template path.

---

## 14. Scoped Execution Manifest

### 14.1 Purpose

The Scoped Execution Manifest is the atomic release unit for runtime extraction.

It resolves the complexity of separately versioned internals into one operational object.

### 14.2 Scope key

A manifest is resolved using an explicit scope such as:

```text
domain + page surface + structural template + market/locale + field contract
```

A manifest may safely cover multiple markets only when the included locale policies explicitly support them.

### 14.3 Manifest contents

The manifest contains immutable references to:

- page classifier package;
- compiled recipe, when available;
- universal extractor version;
- field-policy pack;
- locale-policy pack;
- canonicalizers;
- validators;
- output contract and mapping;
- Sentinel policy;
- trust and review policy;
- compatibility hash.

It contains only extraction, normalization, validation, and publication policy references.

### 14.4 Internal traceability

Each component retains its own internal version and hash for engineering traceability.

Operationally:

- a run records one manifest ID;
- a change creates a new manifest version;
- activation promotes the manifest atomically;
- rollback restores the previous manifest atomically.

### 14.5 Promotion states

- `draft`;
- `replay_passed`;
- `representative_sample_passed`;
- `canary`;
- `active`;
- `suspended`;
- `retired`.

### 14.6 Blast-radius rules

- Template-overlay change: test affected template and markets.
- Domain-overlay change: test all affected templates in the domain.
- Platform-base change: test all inheriting domains and templates.
- Field-policy change: test all manifests using that policy.
- Universal-model change: evaluate known, unseen, temporal, and regional datasets plus sampled challenger traffic.

---

## 15. Onboarding Bootstrap State Machine

### 15.1 State model

```text
SEED_RECEIVED
      ↓
BASELINE_EXTRACTED
      ↓
OPERATOR_REVIEW
   ↙          ↘
APPROVED     CORRECTION_CAPTURED
   │                ↓
   │          PROPOSAL_GENERATED
   │                ↓
   │          PROPOSAL_COMPILED
   │                ↓
   └──────────→ REPLAY_TESTED
                     ↓
             REPRESENTATIVE_TESTED
                     ↓
               MANIFEST_DRAFTED
                     ↓
                   CANARY
                 ↙       ↘
              ACTIVE    REVIEW_REQUIRED
```

### 15.2 Step 1: Seed and contract

The operator provides:

- seed URL or input bundle;
- page type expectation;
- required and optional fields;
- target row granularity;
- market context where known;
- optional expected values.

### 15.3 Step 2: Baseline extraction

The system runs:

- page and template classification;
- generic deterministic collectors;
- universal extraction where required;
- semantic resolution;
- normalization;
- validation.

It presents sample records and confidence reasons in business language.

### 15.4 Step 3: Visual operator review

The operator can:

- confirm a correct field;
- click the correct value;
- mark an incorrect value;
- identify the primary product or job region;
- mark a recommendation or unrelated block;
- confirm a list-record boundary;
- link a field to the correct variant;
- identify current versus original price;
- choose between proposed interpretations;
- state that a field is absent.

Every correction becomes a grounded label tied to a node, path, region, or explicit absence assertion.

### 15.5 Step 4: Proposal synthesis

The control plane uses:

- operator labels;
- the compact representation;
- structured evidence;
- generic extractor output;
- field policies;
- similar accepted recipes

to propose one or more of:

- recipe field locator;
- record-boundary rule;
- exclusion region;
- structured path;
- source preference;
- semantic-role rule;
- entity join;
- locale-policy override;
- template split.

A grounded LLM may propose the change, but it cannot activate it.

### 15.6 Step 5: Deterministic compilation

A recipe compiler validates:

- syntax;
- allowed operations;
- scope;
- field ownership;
- inheritance conflicts;
- bounded execution;
- output typing;
- evidence requirements.

Executable runtime behavior is produced by this compiler, not by directly running model-generated code.

### 15.7 Step 6: Replay and representative testing

Test against:

- original seed examples;
- representative pages from the same template;
- edge cases;
- pages with and without variants;
- sale and non-sale states;
- in-stock and out-of-stock states;
- each supported market;
- historical accepted samples where available.

### 15.8 Step 7: Activation gates

Activation requires:

- zero critical semantic failures;
- acceptable field precision and recall;
- correct record and variant ownership;
- no unexplained critical source change;
- locale and currency coherence;
- stable representative-sample results;
- an approved Sentinel policy;
- operator approval when policy requires it.

### 15.9 Bootstrap failure

When no stable deterministic recipe can represent the template:

- retain the universal extractor as the active path for that template;
- optionally train a template-specific lightweight model;
- classify unresolved cases for review;
- do not force a brittle recipe merely to obtain fast-path status.

---

## 16. Extraction Engines

### 16.1 Generic structured-source adapters

Purpose:

- generate high-quality candidates cheaply;
- extract stable identifiers and relationships;
- apply known source semantics.

Adapters emit evidence, not final records.

Initial coverage may include:

- Schema.org Product, Offer, JobPosting, and ItemList;
- Open Graph;
- common embedded state shapes;
- selected high-volume platform object models;
- common job-platform structures.

### 16.2 Compiled recipe engine

A compiled recipe may contain:

- record boundaries;
- field locators or paths;
- source preferences by field;
- local joins;
- recommendation exclusions;
- variant mappings;
- locale-policy references;
- semantic checks;
- field-level fallbacks.

Recipes are bounded data programs, not unrestricted scripts.

### 16.3 Universal cross-domain extractor

Initial prediction targets:

- primary product or job region;
- product-card or job-card boundaries;
- title;
- current price;
- original price;
- currency;
- availability;
- brand or employer;
- primary image;
- canonical URL;
- SKU, variant ID, or job ID;
- description;
- option names and values;
- recommendation and boilerplate exclusion.

A field may have multiple candidates. The semantic resolver selects the final value.

### 16.4 Grounded schema extractor

Used for:

- custom attributes;
- rare semantic labels;
- difficult conflicts;
- repair synthesis;
- visual relationship interpretation.

Its output remains provisional until policy and validation pass.

### 16.5 Generic deterministic heuristics

Useful for:

- repeated-block discovery;
- nearby label-value pairs;
- price-token recognition;
- image ownership and size filtering;
- URL and identifier extraction;
- duplicate suppression;
- schema parsing;
- boilerplate rejection.

Domain-specific exceptions belong in recipe overlays, not hidden application conditionals.

---

## 17. Field Policy and Normalization Architecture

### 17.1 Four field states

Each field progresses through:

1. **Raw evidence** — exact source value;
2. **Typed candidate** — parsed comparable primitive;
3. **Resolved canonical value** — selected semantic value for the correct entity;
4. **Output value** — transformed for the contract.

### 17.2 FieldPolicy

Each standard field policy defines:

- admissible evidence types;
- parser;
- semantic roles;
- entity scope;
- source-ownership requirements;
- candidate comparison;
- hard validations;
- historical and distribution guards;
- locale behavior;
- output defaults;
- review behavior.

### 17.3 LocalePolicy

A locale policy defines:

- decimal and grouping separators;
- currency resolution;
- ambiguous symbol handling;
- tax display and price composition;
- localized availability mapping;
- date parsing;
- unit conversions;
- localized boolean and enum mapping;
- timezone application;
- Unicode normalization.

### 17.4 Example: current price

A current-price policy may require:

- ownership by the primary product or selected variant;
- exclusion from crossed-out, comparison, installment, subscription, or recommendation regions unless explicitly allowed;
- currency coherence with market context;
- non-negative amount;
- original price greater than or equal to current price when both exist;
- visible or independent-source agreement for critical changes;
- Sentinel critical comparison when sampled.

### 17.5 Custom fields

A custom field declares one of:

- string;
- string list;
- number;
- money;
- date;
- boolean;
- enum;
- key-value map;
- structured object.

Grounded model extraction is allowed, but the output still passes declared typing, evidence, and validation policy.

---

## 18. Evidence Model

### 18.1 Published-field evidence

Store:

- field name;
- raw value;
- typed value;
- canonical value;
- source type;
- node, path, or region reference;
- entity ID;
- extractor and version;
- recipe-layer provenance where relevant;
- resolution policy;
- locale policy;
- validation outcome;
- manifest ID.

### 18.2 Rejected evidence

Persist rejected candidates when:

- the field is critical;
- candidates conflict;
- trust is below `verified`;
- a Sentinel disagreement occurs;
- operator review is triggered;
- the page is selected for evaluation or training.

### 18.3 Artifact retention

Persist larger artifacts only for:

- failures;
- review cases;
- Sentinel disagreements;
- canary samples;
- drift samples;
- training labels;
- bounded quality samples.

Successful ordinary fast-path executions retain compact evidence summaries.

---

## 19. Review Queue and Publication Policy

### 19.1 Review is a first-class result

`needs_review` is not a hidden success and not an unclassified failure.

A review item contains:

- affected record and fields;
- business-readable reason;
- evidence alternatives;
- visual references when available;
- manifest and template identity;
- proposed correction;
- publication impact;
- deadline policy.

### 19.2 Publication behavior

Configure by field contract and client policy.

#### Critical required field unresolved

Choose one explicit policy:

- block current publication;
- publish the last known verified record with a staleness marker;
- publish the current record without the unresolved field only when the contract explicitly permits it.

#### Non-critical field unresolved

The record may be published with:

- field omitted;
- warning state;
- review ticket;
- retained evidence.

### 19.3 Deadline expiry

When the configured review deadline expires:

- never auto-promote an unsafe value;
- apply the configured block, last-known-good, or permitted-partial policy;
- mark the item `review_timeout`;
- retain the unresolved reason and evidence;
- escalate according to operating policy.

### 19.4 Queue priority

Prioritize by:

- field criticality;
- record volume affected;
- template blast radius;
- client priority;
- age;
- Sentinel criticality;
- availability of a safe last-known-good result.

---

## 20. Repair and Learning Lifecycle

### Step 1: Detect

Triggers include:

- zero records;
- required-field loss;
- trust decline;
- structural-fingerprint change;
- source-region change;
- Sentinel disagreement;
- record-count or variant-count shift;
- distribution anomaly;
- locale-validation increase;
- operator correction.

### Step 2: Classify

Use:

- wrong surface;
- insufficient input bundle;
- template mismatch;
- recipe drift;
- source discovery;
- record boundary;
- field localization;
- entity binding;
- semantic resolution;
- canonicalization;
- locale normalization;
- validation;
- unsupported representation;
- model-service failure;
- internal error.

### Step 3: Build representative set

Include:

- failing examples;
- ordinary examples;
- edge cases;
- market variants;
- product states;
- variant structures;
- historical accepted samples;
- Sentinel disagreements.

### Step 4: Generate grounded proposals

Possible proposals:

- new locator or path;
- corrected boundary;
- exclusion region;
- source-preference change;
- semantic-role rule;
- entity-join change;
- locale-policy change;
- template split;
- recipe-layer scope change.

### Step 5: Compile

Validate proposals through the deterministic recipe compiler.

### Step 6: Replay and representative tests

Compare:

- record identity;
- field precision and recall;
- normalized exact match;
- price-role accuracy;
- variant binding;
- recommendation contamination;
- market correctness;
- latency and cost;
- review burden.

### Step 7: Create candidate manifest

Create an atomic scoped manifest containing the compatible recipe and policy set.

### Step 8: Canary and Sentinel challenge

Run the candidate on bounded traffic with elevated challenger sampling.

### Step 9: Promote, retain for review, or reject

Promotion requires all applicable gates.

### Step 10: Learn

Accepted corrections become:

- template-recipe evidence;
- regression cases;
- operator-label examples;
- universal-model training data;
- field-policy test cases.

---

## 21. Product Plane

### 21.1 Onboarding wizard

Shows:

- detected page types;
- structural templates;
- market variants;
- sample records;
- field coverage;
- variant interpretation;
- warnings;
- review requirements.

### 21.2 Business-readable validation

Examples:

- “Current price matches the primary product region on 19 of 20 samples.”
- “One page appears to use a different template.”
- “Three variants do not have unique identifiers.”
- “The displayed amount may be an original price rather than the current price.”
- “Seven product cards were excluded as recommendations.”
- “The German storefront uses a different availability vocabulary.”
- “The recipe and universal extractor disagree on two sale prices.”

### 21.3 Visual correction workspace

Allow operators to:

- select correct values;
- mark wrong values;
- mark absent fields;
- identify primary regions;
- identify recommendation blocks;
- confirm list boundaries;
- confirm variant ownership;
- distinguish semantic roles;
- approve a proposed repair.

### 21.4 Sentinel dashboard

Show by template and market:

- sample rate;
- concordance trend;
- critical disagreements;
- source-region changes;
- suspended recipes;
- latest adjudications;
- recommended action.

### 21.5 Advanced evidence view

Specialists may inspect:

- source objects;
- node IDs;
- paths and locators;
- model scores;
- rejected candidates;
- inheritance provenance;
- validation traces;
- manifest composition.

### 21.6 Activation view

Activation requires visible results for:

- replay;
- representative samples;
- regional samples;
- critical semantic fields;
- record and variant changes;
- Sentinel policy;
- remaining review cases.

---

## 22. Core Data Model

### 22.1 ExtractionInputBundle

Prepared immutable page artifacts and execution context.

### 22.2 ExecutionContext

Language, market, currency, tax, units, timezone, channel, and supplied state.

### 22.3 FieldContract

Canonical fields, types, scopes, criticality, validators, projection, and review behavior.

### 22.4 StructuralTemplate

Contains:

- template ID;
- domain and surface;
- stable fingerprint;
- representative samples;
- supported markets;
- status;
- collision history.

### 22.5 RecipeLayer

Contains:

- layer type;
- scope;
- field rules;
- joins;
- exclusions;
- policy references;
- parent layer;
- version;
- state.

### 22.6 CompiledRecipe

Flattened bounded runtime program produced from compatible layers.

### 22.7 ScopedExecutionManifest

Atomic runtime release for a scope.

### 22.8 FieldEvidence

Contains:

- field;
- raw and typed value;
- node, path, or region;
- source type;
- entity hint;
- extractor identity;
- ranking signals;
- semantic role;
- locale interpretation;
- validation state.

### 22.9 CanonicalEntity

Supports:

- product;
- offer;
- variant;
- asset;
- job;
- employer;
- location.

Relationships use typed references rather than a general-purpose graph engine.

### 22.10 SentinelObservation

Contains:

- manifest and template;
- recipe result;
- challenger result;
- semantic comparison;
- disagreement class;
- adjudication;
- drift contribution.

### 22.11 BootstrapSession

Contains:

- seed inputs;
- operator labels;
- proposals;
- compiled recipe;
- test results;
- state transitions;
- approvals.

### 22.12 EvaluationCase

Contains:

- input-bundle reference;
- grounded expected records;
- field and entity labels;
- market and template tags;
- expected trust outcome;
- required metrics.

---

## 23. Failure Taxonomy

### Wrong surface

The supplied page is not the requested type.

### Insufficient input bundle

The provided artifacts do not contain enough grounded evidence for a required result.

### Template mismatch

No trusted structural-template match can be established.

### Recipe drift

A recipe executes but fails semantic, Sentinel, or structural trust gates.

### Discovery

Relevant content exists in the bundle but was not identified.

### Record boundary

Primary or repeated entity boundaries are incorrect.

### Entity binding

Values cannot be assigned reliably to the correct record or variant.

### Semantic resolution

Candidates exist but their business roles are ambiguous or wrong.

### Canonicalization

A raw value cannot be parsed into the standard primitive.

### Locale normalization

Market, currency, tax, date, availability, or unit semantics cannot be resolved safely.

### Validation

A result violates contract, semantic, historical, distribution, or ownership checks.

### Unsupported representation

The available representation cannot express a critical field with supported extractors.

### Model service failure

A required model could not provide a result independently of page meaning.

### Internal error

CrawlerAI failed due to its own implementation.

Zero records must always include one or more classifications.

---

## 24. Evaluation Framework

### 24.1 Dataset partitions

Maintain distinct sets for:

- known templates;
- unseen domains;
- unseen templates in known domains;
- temporally changed templates;
- A/B variants;
- personalized or promotional variants;
- market and locale variants;
- platform-template collisions;
- listing and detail pages;
- simple and multi-variant products;
- job pages;
- Sentinel disagreement cases.

### 24.2 Ground truth

Ground truth must include:

- record boundaries;
- field node, path, or region references;
- entity association;
- canonical value;
- semantic role;
- locale interpretation;
- absence labels where applicable.

Text-only expected values are insufficient because identical text may appear in unrelated regions.

### 24.3 Metrics

Measure:

- page-type classification accuracy;
- template-match accuracy;
- record-boundary precision and recall;
- field precision, recall, and F1;
- normalized exact match;
- current-versus-original-price accuracy;
- variant-binding accuracy;
- primary-image ownership accuracy;
- locale and currency accuracy;
- recommendation-contamination rate;
- ungrounded-value rate;
- recipe fast-path pass rate;
- recipe-challenger concordance;
- critical Sentinel disagreement rate;
- false-safe recipe rate;
- drift-detection latency;
- p50 and p95 extraction latency;
- universal-model invocation rate;
- grounded-LLM invocation rate;
- cost per 1,000 pages;
- operator minutes per new template;
- review queue volume;
- recovery time after drift.

### 24.4 Temporal and current evaluation

Stored artifacts support deterministic replay, but resilience must also be evaluated on current representative inputs and intentionally evolving controlled fixtures.

### 24.5 Champion and challenger

Use champion/challenger evaluation for:

- universal-model changes;
- platform-base recipe changes;
- field-policy changes;
- critical template repairs.

Do not promote based only on aggregate accuracy. Critical semantic regressions are blocking even when average metrics improve.

---

## 25. What Not to Build Initially

Do not make the following foundational:

- a persistent enterprise knowledge graph;
- a graph database for page-level variants;
- unlimited source enumeration for every page;
- an open-ended entity convergence loop;
- LLM extraction on every page;
- full page-representation construction on every page;
- permanent storage of every artifact and rejected candidate;
- operator-authored selectors as the default onboarding method;
- one shared mutable recipe for every merchant on a platform;
- local fixes applied directly to a platform base layer;
- opaque confidence as the sole activation criterion;
- seven independently promoted runtime components for every domain;
- automatic challenger override of a recipe without adjudication.

---

## 26. Recommended Implementation Sequence

### Phase 1: Contracts and deterministic core

Build:

- Extraction Input Bundle contract;
- Execution Context;
- Field Contract and Field Policy registry;
- locale-policy registry;
- evidence contract;
- stable failure taxonomy;
- semantic validators;
- Scoped Execution Manifest;
- business-readable diagnostics.

**Outcome:** A clean extraction boundary with deterministic normalization and validation.

### Phase 2: Recipe hierarchy and compiler

Build:

- structural-template model;
- recipe layers;
- merge and conflict rules;
- deterministic recipe compiler;
- compiled fast-path engine;
- scoped manifest promotion and rollback;
- template and market replay sets.

**Outcome:** Safe low-cost execution without shared-rule pollution.

### Phase 3: Bootstrap product workflow

Build:

- onboarding state machine;
- sample preview;
- visual field correction;
- region and record-boundary labels;
- variant relationship correction;
- proposal review;
- activation gates.

**Outcome:** Non-specialists can create and correct extraction behavior without writing selectors.

### Phase 4: Compact representation and universal extractor

Build:

- lazy compact representation;
- labeling pipeline;
- shared model inference pool;
- models for page type, boundaries, field nodes, exclusions, and basic relationships;
- unseen-domain and market evaluation sets.

**Outcome:** General extraction for new templates without a hand-written rule per site.

### Phase 5: Sentinel anti-drift system

Build:

- risk-adjusted challenge sampling;
- semantic recipe-versus-challenger comparison;
- rolling concordance metrics;
- drift states;
- recipe suspension policy;
- Sentinel dashboard;
- adjudication workflow.

**Outcome:** Known recipes remain cheap without becoming silently wrong.

### Phase 6: Grounded LLM and visual assistance

Build:

- grounded schema extractor;
- evidence-reference enforcement;
- recipe-diff synthesis;
- custom-field workflow;
- ambiguity explanations;
- review and cost controls.

**Outcome:** Reduced engineering effort for the long tail and faster repair.

### Phase 7: Advanced learning only when justified

Possible later capabilities:

- template-specific compact models;
- active-learning prioritization;
- cross-page entity fusion;
- cross-domain product matching;
- automated label proposal;
- broader relationship analytics.

---

## 27. Acceptance Criteria

### Scope

- Runtime extraction begins from an immutable prepared input bundle.
- The architecture begins from an immutable prepared input bundle and specifies extraction behavior only.

### Runtime

- Every page follows a recorded extraction decision path.
- Successful unsampled recipes do not build the compact universal representation.
- Every recipe execution passes semantic invariants.
- Risk-adjusted Sentinel challenge is active for known recipes.
- Challenger output cannot silently override a recipe.
- Variant processing is bounded and deterministic.
- Grounded models cannot publish values without evidence references.
- Zero records always have a classified reason.

### Recipe safety

- Platform, domain, template, market, and constrained overrides are isolated.
- Local fixes cannot modify shared base behavior.
- Recipe layers compile into one bounded runtime recipe.
- Platform changes receive broad regression coverage.
- A recipe can be automatically suspended after confirmed critical drift.

### Locale

- Structural templates can be shared across locales without sharing incorrect semantic policies.
- Currency, number, tax, date, unit, and availability policies are explicit.
- Ambiguous critical locale semantics cannot receive `verified` status.

### Product

- A non-specialist can onboard and correct a standard template without writing selectors.
- The bootstrap state machine is visible and recoverable.
- Operator corrections produce grounded labels.
- Proposed behavior is compiled and tested before activation.
- Sentinel disagreements are visible in business terms.

### Versioning

- Each run records one atomic Scoped Execution Manifest ID.
- Internal component hashes remain available for engineering audit.
- Activation and rollback are atomic at manifest level.

### Review

- `needs_review` has explicit publication behavior.
- Review timeout cannot silently promote an unsafe value.
- A safe last-known-good policy is supported where configured.

### Efficiency

- Universal representation build rate is measured.
- Universal-model invocation rate is measured and bounded.
- Grounded-LLM invocation rate is measured and bounded.
- Cost per 1,000 pages is a release metric.
- Model memory is not duplicated across every extraction worker by default.

---

## 28. Final Architectural Position

CrawlerAI should be a **learning compiler for web extraction**, not a selector warehouse and not an LLM wrapper.

Its operating model is:

> classify the supplied page artifacts, resolve the structural template and market, execute the cheapest trusted extraction policy, validate semantic ownership, challenge a controlled sample with a generalized model, and convert accepted adaptive results into safe compiled recipes.

The architecture assigns each technology the role it performs best:

- generic parsers provide cheap evidence;
- recipes provide deterministic high-volume execution;
- cross-domain ML generalizes to unseen layouts;
- grounded LLM and vision models handle sparse ambiguity and synthesize repairs;
- field and locale policies establish business meaning;
- Sentinel testing detects silent recipe drift;
- operators resolve uncertainty through visual labels;
- manifests provide atomic release and rollback;
- evidence makes every published value auditable.

Traditional deterministic rules are not obsolete when they are compiled outputs of a learning and validation system. They become obsolete only when humans must continuously author and maintain them as the system’s primary intelligence.

---

## 29. Research and Product Evidence

The architectural direction is consistent with current commercial extraction products and recent research:

1. **Zyte automatic extraction and custom attributes:** typed standard extractors combined with schema-defined LLM custom attributes over reduced relevant content. See [Zyte automatic extraction](https://docs.zyte.com/zyte-api/usage/extract/index.html) and [custom attributes](https://docs.zyte.com/zyte-api/usage/extract/custom-attributes.html).
2. **Diffbot Extract and Custom APIs:** automatic page-type extraction combined with visual or rule-based corrections and custom fields. See [Extract API introduction](https://docs.diffbot.com/reference/extract-introduction) and [Custom API](https://docs.diffbot.com/docs/introduction-to-custom-api).
3. **Farag et al., Cross-Domain Web Information Extraction at Pinterest, KDD 2025:** compact structural, visual, and textual page representations with lightweight models and distillation into cheaper domain-specific execution. DOI: `10.1145/3711896.3737207`.
4. **LiveWeb-IE, 2026:** evaluation against evolving live pages demonstrates why static replay alone is insufficient for drift robustness. arXiv: `2603.13773`.
5. **FreeDOM, WebFormer, and MarkupLM:** structural and markup-aware representations improve transfer and web-field understanding compared with treating raw HTML as plain text.

These sources support the hybrid position: generalized learned extraction for cold-start, deterministic compiled execution for learned templates, grounded correction, and continuous temporal evaluation.
