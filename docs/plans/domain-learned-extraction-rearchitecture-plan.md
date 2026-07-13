# Plan: Domain-Learned Extraction Re-architecture — One Runtime, Executable Recipes, Net Code Reduction

**Created:** 2026-07-11  
**Status:** SUPERSEDED AFTER AUDIT — valid target work moved to `extraction-architecture-freeze-recovery-plan.md`; unverified implementation remains in the working diff
**Authoritative for:** extraction architecture, extraction memory, recipe learning, generalized/model-assisted extraction, selector migration, and extraction cutover  
**Supersedes:**

- `docs/plans/crawlerai-extraction-v3-confidence-tiered-plan.md`
- the extraction-architecture and retention instructions in `docs/plans/extraction-v3-live-recovery-plan.md`

The Run 39+ and Run 41 artifact evidence in the recovery plan remains valid input. Its instruction to continue repairing the generic detail graph/resolver as the permanent architecture does not.

---

## 1. Executive Decision

CrawlerAI will use one extraction architecture:

> Learn an executable recipe for each `(domain, surface, template family)`, execute that recipe on future captures, and use generic/model-assisted analysis only to compile or repair recipes.

There will not be four competing production extractors called deterministic, recipe, generalized, and legacy. There will be one publication path:

```text
CaptureBundle
    -> select active recipe or discover a candidate recipe
    -> execute recipe
    -> validate identity, ownership, cardinality, and required fields
    -> publish ExtractionResult
```

The generic evidence graph and optional model may help discover a recipe on a cold start or after explicit drift. They may not publish a record through a separate path. Even a first-page cold start must compile an ephemeral candidate recipe and replay that recipe against the same capture before anything is published.

This plan deliberately rejects the current V3 premise that a missing recipe is merely a runtime model-cost problem. The model is a bounded compiler/adjudicator, not the permanent extraction floor.

---

## 2. Why This Plan Exists

The branch has added substantial code without resolving the failures that motivated it.

### 2.1 Current worktree delta against `main`

Measured on 2026-07-11:

| Scope | Files | Added | Deleted | Net |
|---|---:|---:|---:|---:|
| Entire worktree | 182 | 24,616 | 1,277 | +23,339 |
| Backend production | 90 | 9,556 | 847 | +8,709 |
| Frontend production | 14 | 1,860 | 55 | +1,805 |
| Evaluation | 20 | 2,884 | 0 | +2,884 |
| Tests | 38 | 5,841 | 326 | +5,515 |
| Docs/plans | 14 | 4,075 | 47 | +4,028 |

The whole-branch number includes unrelated AI-visibility work. This plan therefore uses a narrower extraction-owned production baseline.

### 2.2 Extraction-owned production baseline

Nonblank Python LOC:

| Scope | `main` | Current | Delta |
|---|---:|---:|---:|
| `backend/app/extraction/` | 14,272 | 16,320 | +2,048 |
| Extraction-memory owners | 1,348 | 1,725 | +377 |
| Extraction pipeline/replay owners | 1,147 | 1,565 | +418 |
| **Total extraction-owned production** | **16,767** | **19,610** | **+2,843** |

The extraction branch also added approximately:

- +2,884 evaluation LOC
- +2,603 focused extraction-test LOC
- +353 extraction/domain-memory frontend LOC

The plan does not accept those additions as evidence of improvement. Retention is earned only by observable extraction behaviour and by replacing an existing owner rather than creating a parallel one.

### 2.3 Runtime findings from the code audit

The current implementation does not execute domain recipes in the same sense that acquisition executes a learned domain contract.

1. Ecommerce-detail selector recipes are explicitly disabled in both the crawl stage and recipe compiler.
2. The engine runs the generic harvest before deciding whether remembered source pins apply.
3. A result is labelled `extractor_tier="recipe"` when a preferred evidence source wins inside generic resolution; no executable recipe controlled the work.
4. The current compiled recipe cannot express product root, selected child, entity joins, relative field paths, endpoint roots, exclusions, cardinality, or validation.
5. Template fingerprints depend on collector/evidence outcomes, forcing generic harvest before template matching.
6. Any `partial` result can trigger generalized fallback even when identity and core fields are correct.
7. `success`, `partial`, and `review` outputs may teach source preferences from the same generic resolver that may have selected the wrong child.
8. Production can carry legacy/no-template and V3/template payloads behind per-domain cutover state, creating a durable dual system.
9. `DomainMemory` selectors, extraction-memory source pins, extraction profiles, listing record bindings, generic collectors, and model fallback are overlapping mechanisms rather than one compiled recipe contract.
10. The focused architecture/runtime/contract suite passes because tests encode this abstraction; the invariants are certifying the wrong system.

### 2.4 Observable failures remain

The Run 41 artifact audit still shows wrong-child mixtures, wrong-product output, shell products, record loss, price-unit corruption, category absence, incomplete variants, and weak evidence winning. Fresh listing runs still demonstrated false success or honest-zero failures despite the added listing/model machinery.

This plan treats those as structural evidence that candidate ranking and fallback expansion are not the final architecture.

---

## 3. Non-Negotiable Architecture

### 3.1 One producer of public records

Only the recipe executor may produce the record that reaches validation/publication.

```text
Known template:
    active recipe -> recipe executor -> shared validation -> publish

Cold start:
    discovery -> candidate recipe -> recipe executor -> shared validation -> publish

Drift:
    active recipe fails explicitly
        -> discovery/repair -> candidate recipe
        -> recipe executor -> shared validation -> publish
```

The discovery system may inspect evidence, use structural heuristics, or call an enabled model. Its product is a recipe candidate, not a parallel record.

### 3.2 One recipe contract for every surface

Commerce detail, commerce listing, job detail, and job listing use the same recipe schema and executor. Surface adapters may discover different boundaries and fields, but they do not own separate extraction architectures.

### 3.3 Generic code remains generic; learned data is domain-specific

No production code may contain retailer-specific branches. Domain knowledge lives in a bounded declarative recipe stored by exact scope.

A recipe may contain learned selectors and paths. The prohibited primitive is not “a selector”; it is an unverified global selector bank or a site-specific Python branch. A learned relative selector, JSON pointer, or endpoint binding that is identity-scoped, replay-validated, and drift-checked is valid recipe data.

### 3.4 Model output cannot be a field value

For ecommerce detail and eventually all surfaces, the model may:

- identify a record root already present in the capture
- identify a source path or relative binding
- propose an entity join
- classify price/value semantics
- reject an unsafe or ambiguous binding
- abstain

It may not inject a product title, price, SKU, category, URL, variant, or other field directly into the evidence ledger for publication. Every published value must be read by the recipe executor from a captured artifact.

### 3.5 No long-lived legacy/V3 dual runtime

This branch is already isolated. Implementation must replace the old path in-place rather than introducing another production feature flag. A temporary test-only or branch-local comparison is allowed, but the merge-ready state has one runtime and one recipe schema.

### 3.6 No compatibility layer for invalid recipe formats

Existing source-pin-only and commerce-detail-disabled selector recipes are not silently translated forever. The new schema receives a new version. Incompatible old recipes are invalidated and relearned. A one-time data migration may preserve operator intent such as `required` and `value_sense`, but there is no runtime adapter that keeps both semantics alive.

---

## 4. Canonical Runtime Flow

### 4.1 Recipe selection happens before generic harvest

Recipe lookup uses cheap, stable pre-extraction inputs:

- normalized domain
- explicit surface
- normalized route pattern
- platform family when already known from acquisition
- optional capture/template signature derived from stable raw artifact markers, not extracted field evidence
- optional locale/market only when it changes page semantics

The current fingerprint based on collectors, evidence, and outcomes cannot be the runtime selector because it requires the generic work that the recipe is supposed to avoid.

### 4.2 Active recipe execution

The executor:

1. verifies capture requirements are present
2. establishes the record root
3. proves requested product/listing/job identity
4. establishes child entities such as offers, variants, assets, or listing rows
5. applies explicit joins and containment relationships
6. reads fields through declared bindings
7. applies centralized transforms and semantic senses
8. enforces cardinality and exclusions
9. emits binding-level provenance and failures
10. runs shared surface validation
11. publishes only when the recipe contract permits it

An active-recipe success does not run unrelated collectors or the model.

### 4.3 Cold-start discovery

When no active recipe matches:

1. existing structured/network/JS/DOM readers inspect the capture
2. record-first discovery establishes candidate boundaries and identity
3. optional model assistance proposes grounded paths/joins only
4. the compiler emits an ephemeral recipe candidate
5. the normal recipe executor replays it against the same capture
6. shared validation decides whether the page result may publish
7. the candidate is persisted in `candidate` state, not immediately trusted for unrelated pages

There is no `generic result -> publish` bypass.

### 4.4 Drift recovery

An active recipe fails only through typed reasons such as:

- `recipe_capture_requirement_missing`
- `recipe_template_mismatch`
- `recipe_root_not_found`
- `recipe_identity_mismatch`
- `recipe_binding_not_found`
- `recipe_join_failed`
- `recipe_cardinality_changed`
- `recipe_value_validation_failed`
- `recipe_required_field_missing`

A generic `partial` verdict is not a recipe-failure trigger.

On typed failure, discovery may compile a repair candidate for that page. Publication still goes through executing the candidate recipe. The active recipe is suspended only after bounded confirmation; it is never silently mixed with generic evidence.

---

## 5. Executable Recipe Contract

The schema should stay small and declarative. Use one version such as `extraction_recipe.v2`.

```json
{
  "schema_version": "extraction_recipe.v2",
  "scope": {
    "domain": "shop.example",
    "surface": "ecommerce_detail",
    "route_pattern": "/products/{id}",
    "template_signature": "optional-stable-signature"
  },
  "capture_requirements": {
    "rendered_dom": true,
    "network_json": false,
    "interaction_artifacts": []
  },
  "record": {
    "root": {
      "source": "dom",
      "path": "main[data-page='product']",
      "cardinality": "one"
    },
    "identity": [
      {
        "source": "dom_attribute",
        "scope": "record.root",
        "path": "[data-product-id]",
        "attribute": "data-product-id",
        "compare_to": "request.product_identity"
      }
    ]
  },
  "entities": {
    "selected_variant": {
      "root": {
        "source": "dom",
        "scope": "record.root",
        "path": "[aria-pressed='true'][data-sku]"
      },
      "identity_field": "sku"
    },
    "offer": {
      "root": {
        "source": "network_json",
        "artifact": "product_api",
        "path": "/variants/*"
      },
      "join": {
        "left": "selected_variant.sku",
        "right": "offer.sku"
      }
    }
  },
  "fields": {
    "title": [
      {
        "source": "dom_text",
        "scope": "record.root",
        "path": "h1",
        "cardinality": "one",
        "transform": "normalized_text"
      }
    ],
    "price": [
      {
        "source": "json_pointer",
        "scope": "entity.offer",
        "path": "/price/current",
        "sense": "current_public_price",
        "unit": "major"
      }
    ]
  },
  "exclusions": [
    "[data-component='recommendations']",
    "[data-component='recently-viewed']"
  ],
  "validation": {
    "required": ["record.identity", "title", "price"],
    "fail_closed": [
      "multiple_record_roots",
      "sibling_identity_conflict",
      "offer_join_failure"
    ]
  }
}
```

### 5.1 Supported binding primitives

Keep the initial primitive set bounded:

- DOM text relative to a root
- DOM attribute relative to a root
- JSON pointer against a named captured artifact
- network JSON pointer against an admitted same-product artifact
- repeated child root
- equality join between established entity identities
- structural containment
- explicit validated single-record assertion
- centralized transform reference
- semantic sense/unit reference
- cardinality and requiredness
- exclusion region

Do not add arbitrary Python expressions, JavaScript, XPath functions, templated code execution, or per-domain plugin classes.

### 5.2 Recipe output

Recipe execution returns a typed internal result containing:

- established record/entity identities
- extracted values
- binding provenance
- binding outcomes
- validation outcomes
- exact recipe failure state
- capture requirements used
- recipe/template/release identifiers

The existing `ExtractionResult` public seam remains, but `extractor_tier` must describe the real path:

- `recipe`: a persisted active recipe executed
- `candidate_recipe`: a newly compiled candidate executed for this page
- `blocked`: acquisition was blocked

Do not label generic source preference as recipe execution. Retire `ml`/`llm` as record-producing tiers; model involvement belongs in diagnostics such as `recipe_discovery.model_invoked`.

---

## 6. Recipe Learning and Promotion

### 6.1 Candidate creation

A candidate is learnable only when:

- record identity is proven
- required fields pass validation
- all published fields were read from captured artifacts
- ownership and joins are explicit
- no critical ambiguity or wrong-product finding remains
- the candidate replays successfully through the recipe executor

A `partial` result may create a candidate only when its missing capability is explicitly outside the candidate contract. It may not teach a field whose ownership is unresolved.

### 6.2 Multi-sample promotion

Default automatic promotion requires:

- at least two distinct product/job/listing URLs in the same scope
- successful replay on both
- identity correctness on both
- 100% required-binding success
- no contradictory binding semantics

An operator may explicitly promote after one verified sample. That action must be stored as operator provenance, not disguised as automatic confidence.

### 6.3 States

Use only states that affect execution:

- `candidate`
- `active`
- `suspended`
- `retired`

Do not add parallel “trusted,” “degraded,” “shadow,” “review,” and “repair queue” states unless an executable transition and reader exist. Observations can record details without becoming lifecycle states.

### 6.4 Drift

- one typed failure: per-page repair discovery; active recipe remains active
- configured consecutive failures on distinct pages: suspend
- successful repair candidate on required samples: activate new immutable version
- rollback: repoint release to prior immutable version

Do not merge old and new recipe bindings at runtime.

---

## 7. Canonical Ownership

| Concern | Canonical owner after re-architecture | Rule |
|---|---|---|
| Public extraction entry | `backend/app/extraction/engine.py` | Orchestration only; recipe select/discover/execute/validate |
| Recipe schema, matching, compile, execute | rename/consolidate `backend/app/core/extraction_memory/contract_runtime.py` into one recipe-runtime owner | Pure functions; no DB access; no generic publication |
| Recipe storage/releases/manifests | `backend/app/persistence/extraction_memory.py` | Storage only; no compiler and no extraction semantics |
| Capture/document readers | existing collectors/document store | Discovery inputs and executor primitives; no public record production |
| Model assistance | `backend/app/extraction/model_runtime.py` plus one provider boundary | Recipe proposals only; never field evidence for publication |
| Surface validation/publication | existing extraction validation/publication owners | Shared by active and candidate recipes |
| Acquisition path learning | existing `DomainRunProfile.acquisition_contract` | Remains separate and authoritative for HTTP/browser/capture behaviour |
| Extraction recipe UI/API | one extraction-recipe surface | Edits the same recipe contract; no selector store plus profile plus source-pin UI |
| Evaluation | one artifact replay/scoring harness | Behavioural outcomes only; no release decisions from stale labels |

There must be no second owner for any row in this table.

---

## 8. File-Family Disposition

### 8.1 Keep

Keep these contracts unless a focused test proves they are responsible for a failure:

- `CaptureBundle`, `ArtifactReader`, `DocumentStore`, and the acquisition-to-extraction request seam
- typed public records and `ExtractionResult`
- evidence/provenance structures needed by discovery and audit
- shared normalization policy
- shared validation and publication firewall
- `ExtractionTemplate`, `ExtractionRecipe`, immutable release snapshot, manifest, and observation concepts
- acquisition contracts and browser/internal-API safety gates
- Run 39+ and Run 41 artifact evidence

### 8.2 Rewrite or consolidate

| Current owner | Required change |
|---|---|
| `extraction/engine.py` | Recipe-first orchestration; remove harvest-first tier cascade |
| `core/extraction_memory/contract_runtime.py` | Become the sole pure recipe matcher/compiler/executor; source preferences are replaced by bindings |
| `persistence/extraction_memory.py` | Move compile/runtime semantics out; retain storage, immutable versions, activation, observations |
| `extraction/model_runtime.py` | Return grounded recipe proposals and abstentions, never publishable Evidence |
| `extraction/collectors/*` | Readers/discovery only; executor calls only recipe-declared primitives |
| `extraction/targeting.py`, `entities.py`, `resolution/` | Discovery helpers and shared validators; not an alternative active-recipe runtime |
| `listing_records.py`, `listing_tier0.py`, `network_listing.py` | Surface-specific discovery adapters feeding the same recipe compiler |
| extraction-profile backend/frontend | Edit the canonical recipe contract or be deleted |
| template fingerprinting | Match from pre-harvest scope/signature; do not fingerprint collector outcomes |

### 8.3 Delete

Delete these behaviours and their tests/readers as part of the replacing slice, not later:

- source-pin preference being labelled recipe execution
- `_generic_harvest` as the mandatory first step for an active recipe
- `_compiled_source_pin_template` and `_source_pin_recipe_applied` semantics
- ecommerce-detail selector stripping that makes stored recipes non-executable
- `css_recipe_evidence` as additive evidence inside generic harvest
- separate selector-rule loading in `record_extraction_stage.py`
- model-generated Evidence injection into the public extraction attempt
- fallback solely because the verdict is `partial`
- listing-only `record_bindings` as a separate recipe language
- legacy release payload versus V3 release payload duality
- per-domain V3 cutover labels after the single runtime is accepted
- compatibility readers for old source-pin-only recipes
- automatic learning from `partial`/`review` without identity and binding proof
- unused repair-cost dashboard metrics and repair-queue state without an executing repair workflow
- stale frozen evaluation reports and implementation-coupled tests that do not protect accepted behaviour
- duplicate DomainMemory selector/profile/source-pin UI and API surfaces after all four surfaces migrate

### 8.4 Conditional retention

`extraction/representation/*` remains only if the recipe compiler uses it to propose grounded bindings. If it exists only to feed a generalized field-value generator, delete it.

Internal-API replay remains acquisition-side only if live two-run exact-identity parity succeeds. Extraction recipes may reference an admitted captured artifact but may not themselves perform unsafe endpoint replay.

---

## 9. Anti-Bloat Laws

These are merge gates, not aspirations.

### 9.1 Production LOC ceiling

Final extraction-owned production LOC must be at or below the `main` baseline:

```text
backend/app/extraction/
+ backend/app/core/extraction_memory/
+ backend/app/persistence/extraction_memory*.py
+ backend/app/models/extraction_memory.py
+ extraction stage/domain-memory/replay integration owners
<= 16,767 nonblank Python LOC
```

Current measured scope is 19,610. The implementation must remove at least 2,843 net production LOC before closure.

### 9.2 Slice-level net rule

- Phase 0 adds no production code.
- Any new production module must replace/delete equal or greater production LOC in the same slice.
- After the recipe contract skeleton lands, every later slice must be production-net-negative or production-net-zero.
- Tests, docs, and evaluation code do not offset production growth.

### 9.3 File limits

Targets after consolidation:

- `extraction/engine.py`: <= 500 nonblank lines
- `persistence/extraction_memory.py`: <= 700 nonblank lines
- canonical recipe runtime/compiler: <= 700 nonblank lines total
- no new production module > 500 nonblank lines
- no new function with cyclomatic complexity > 20

Do not raise architecture budgets to pass.

### 9.4 Store/model limits

- no new database table unless an existing extraction-memory table is deleted in the same migration
- no new persistent state without a runtime reader and explicit transition
- no new API/frontend panel unless it replaces an existing selector/profile/recipe panel
- no new fallback tier
- no new pipeline or package named V4, next, legacy, hybrid, or experimental

### 9.5 Evaluation limits

Shrink `backend/eval/` from the current 2,884 added LOC to a bounded accepted-artifact harness. Target <= 1,200 nonblank LOC unless additional retained lines are justified by current accepted labels and a release decision.

Generated reports are artifacts, not source-controlled architecture.

### 9.6 Test quality

Tests must assert behaviour:

- which work executed
- exact record identity
- binding provenance
- second-run reuse
- drift state
- no model/generic collector on active-recipe success

Delete tests that only assert private helper names, old tiers, source-pin ranking, or disabled selectors.

---

## 10. Strict Implementation Phases

No phase may begin until the prior phase meets its exit gate.

## Phase 0 — Freeze architecture and establish deletion ledger

**Production changes:** none.

### Work

1. Mark this plan as the only active extraction plan.
2. Update `INVARIANTS.md`, `BUSINESS_LOGIC.md`, backend architecture, and codebase map so they describe the target architecture rather than the current tier cascade.
3. Add a checked-in deletion ledger listing every changed extraction-owned production file, current LOC, final owner, and keep/rewrite/delete decision.
4. Capture the exact extraction-owned baseline command and results.
5. Add architecture tests that fail on the current design:
   - active recipe must be selected before generic harvest
   - active recipe success invokes no generic collectors and no model
   - only recipe execution may produce a publishable record
   - model output type cannot be `Evidence`/record fields
   - ecommerce-detail recipes may contain executable DOM/JSON bindings
   - `partial` alone is not a recipe failure
6. Add accepted two-run fixtures for at least one detail and one listing template.

### Exit gate

- architecture tests fail for the intended reasons before production edits
- every retained current file has one future owner
- every deleted behaviour has a named removing phase
- no new production code

---

### Phase 0 execution record — 2026-07-11

**Status:** IMPLEMENTED; verification pending user-run commands. No production source was changed in this phase.

#### Extraction-owned changed-file deletion ledger

| Current file | Current nonblank LOC | Final owner/disposition | Removing phase |
|---|---:|---|---:|
| `app/acquisition/internal_api_replay.py` | 614 | Keep acquisition-only, conditional on live exact-identity two-run proof; never an extraction executor | 8/9 if unproven |
| `app/core/extraction_memory/contract_runtime.py` | 211 | Rewrite into the sole pure recipe matcher/compiler/executor | 1-2 |
| `app/crawl/pipeline/record_extraction_stage.py` | 469 | Keep thin integration; delete selector loading and direct model/extraction-shaping branches | 3-5 |
| `app/extraction/adapters.py` | 443 | Consolidate into surface discovery adapters; no record publication | 4/7 |
| `app/extraction/collectors/dom.py` | 1,291 | Rewrite as bounded DOM reader/discovery primitives used only when recipe-declared or compiling | 2/4/8 |
| `app/extraction/contracts.py` | 888 | Keep and add recipe-v2 execution contracts; delete tier/source-pin compatibility shapes | 1/8 |
| `app/extraction/documents.py` | 270 | Keep canonical captured-document access | keep |
| `app/extraction/engine.py` | 1,099 | Rewrite recipe-first and reduce to <=500 nonblank LOC | 3 |
| `app/extraction/entities.py` | 915 | Keep only shared entity/identity discovery and validation helpers | 4/6/8 |
| `app/extraction/jobs.py` | 358 | Consolidate job-specific discovery into shared recipe compiler; delete bespoke runtime | 7/8 |
| `app/extraction/listing.py` | 429 | Consolidate facade or delete after all listing paths use the shared executor | 7/8 |
| `app/extraction/listing_records.py` | 327 | Rewrite as repeated-root discovery/compiler input | 4/7 |
| `app/extraction/listing_tier0.py` | 450 | Delete tier semantics; retain only unique deterministic binding discovery | 4/7/8 |
| `app/extraction/model_runtime.py` | 542 | Rewrite to `RecipeProposal`; delete Evidence conversion and record-producing fallback | 4 |
| `app/extraction/network_listing.py` | 221 | Rewrite as captured-network row binding discovery; no separate publisher | 4/7 |
| `app/extraction/pipeline.py` | 728 | Consolidate into discovery/validation helpers; delete alternate attempt pipeline | 2-4/8 |
| `app/extraction/representation/__init__.py` | 13 | Conditional: keep only if compiler consumes it | 4/8 |
| `app/extraction/representation/flat_map.py` | 114 | Conditional grounded binding proposal representation; otherwise delete | 4/8 |
| `app/extraction/representation/grounding.py` | 65 | Keep only for recipe-proposal/path grounding | 4/8 |
| `app/extraction/representation/scope.py` | 85 | Conditional compiler scoping helper | 4/8 |
| `app/extraction/resolution/__init__.py` | 1,999 | Split/consolidate shared identity/semantic validation; delete generic winner runtime duplicated by recipes | 4/6/8 |
| `app/extraction/result_building.py` | 700 | Keep one result/diagnostic builder; delete tier-specific branches | 3/8 |
| `app/extraction/surfaces.py` | 216 | Keep surface contracts; remove tier-specific behaviour | 1/7 |
| `app/extraction/targeting.py` | 349 | Keep target/identity discovery and validation only | 4/6 |
| `app/persistence/extraction_memory.py` | 1,154 | Rewrite storage-only and reduce to <=700 nonblank LOC; move compiler/runtime out | 1/5/8 |

#### Phase 0 architecture ratchets added

- active recipe selection must occur before discovery harvest
- engine may not retain parallel generic/model record-producing tiers
- model runtime must return recipe proposals rather than `Evidence`
- ecommerce-detail recipes may contain executable DOM/JSON bindings
- `partial` alone may not trigger recipe failure
- two distinct-page fixtures exist for ecommerce detail and ecommerce listing

The tests are intentionally expected to fail against the current implementation until Phases 1-4 remove the old architecture. They were not executed during this slice.

## Phase 1 — Define the single recipe contract and invalidate old formats

### Primary owners

- `core/extraction_memory/recipe_contracts.py`
- `core/extraction_memory/contract_runtime.py`
- extraction-memory models/config
- persistence only for schema/version storage
- `extraction/contracts.py` re-exports the bounded public types needed by `ExtractionResult`

### Work

1. Define `extraction_recipe.v2` with the bounded primitives in Section 5.
2. Define typed `RecipeCandidate`, `RecipeExecutionResult`, `BindingOutcome`, and recipe failure enums.
3. Move `compile_recipe_layers` out of persistence into the canonical pure recipe owner.
4. Remove source-pin-only compiler output and listing-only record-binding schema.
5. Add one-time invalidation/migration for old recipe formats. Preserve only explicit operator semantics that map cleanly.
6. Do not add a compatibility runtime.

### Required deletion in the same phase

- old source-pin compiler structures
- duplicate selector/record-binding recipe schemas
- implementation tests for those schemas

### Exit gate

- one recipe schema for all surfaces
- persistence contains no extraction compiler logic
- phase production diff <= 0 net LOC


### Phase 1 execution record — 2026-07-11

**Status:** IMPLEMENTED; verification pending user-run commands. No pytest or other test command was run by the assistant.

#### Landed

- Added one strict `extraction_recipe.v2` schema for all four surfaces in `core/extraction_memory/recipe_contracts.py`.
- Added typed scope, capture requirements, DOM/attribute/JSON/network bindings, entities, joins, cardinality, value senses/units, exclusions, validation, provenance, candidates, binding outcomes, lifecycle state, and typed recipe failures.
- Moved compilation and template matching into the pure `core/extraction_memory/contract_runtime.py` owner.
- Compiler rejects legacy selector, source-pin/contract, and listing-record-binding kinds instead of translating them.
- Recipe layers must match the template domain, exact surface, route pattern, and optional template signature.
- Persistence now stores/compiles executable-v2 layers only; old formats are retired within the exact domain/surface release scope.
- Release payload is `release.v2`, exact-surface, and contains only compiled executable recipes. Legacy/V3 dual release payload construction was removed.
- Generic winning-source auto-learning and listing-only `record_bindings.v1` persistence were removed.
- The crawl extraction seam no longer loads, composes, transports, or replays saved selector rules.
- Generic resolution no longer accepts remembered source preferences.
- Legacy selector/source-pin/contract write and read APIs return HTTP 410 rather than creating a hidden compatibility recipe.
- The memory read model exposes executable-v2 binding counts and explicit migration state.
- Replaced the former implementation-coupled contract test file with focused v2 schema/compiler/release contracts.

#### De-bloat result

- Touched backend production files versus Phase 0/HEAD: **-459 nonblank LOC** including the new 130-line recipe contract module.
- Exact extraction-owned Phase 0 scope: **-296 nonblank LOC**, reducing the measured 19,610 baseline to approximately **19,314**.
- Modified tracked test files: **-957 nonblank LOC**; the old 1,359-line source-pin/selector contract suite was replaced by a 414-nonblank-line v2 suite.
- `extraction/contracts.py` is 908 nonblank lines after moving the recipe schema out, below its prior 950-line debt ceiling.
- No new database table or column was added.

#### Expected Phase 0 ratchet state after this phase

- `test_detail_recipe_bindings_are_executable_not_surface_disabled`: expected to pass.
- two-run fixture/schema test: expected to pass.
- recipe-first engine routing, removal of parallel record-producing tiers, model proposal-only output, and `partial` fallback tests remain intentionally red; they belong to Phases 3 and 4.

#### Non-test validation performed

- AST parsing passed for all changed Python files.
- Focused imports passed for recipe contracts/runtime, extraction contracts, persistence, knowledge API, crawl extraction stage, replay, and adapters.
- No active compiler/persistence/stage/replay reference remains for `selector_rules`, `source_pins`, `record_bindings.v1`, `contract_preferences`, or `resolved_contract_outcomes`.
- `git diff --check` passed.

---

## Phase 2 — Implement the canonical recipe executor

### Primary owners

- canonical recipe runtime
- existing document/artifact readers
- shared validation/publication

### Work

1. Execute DOM-relative, attribute, JSON-pointer, network-artifact, repeated-root, join, containment, transform, cardinality, and exclusion primitives.
2. Establish identity before field attachment.
3. Emit exact binding provenance and typed failures.
4. Reuse existing normalizers and surface validators; do not clone them.
5. Add detail, listing, job-detail, and job-listing executor fixtures.

### Required deletion in the same phase

- `css_recipe_evidence` additive collector path
- any direct recipe value assembly outside the executor
- duplicate listing record-binding executor logic

### Exit gate

- executor alone can reproduce accepted fixture outputs
- no generic resolver is called inside executor
- production diff for Phases 1+2 combined <= 0

### Phase 2 execution record — 2026-07-11

**Status:** IMPLEMENTED; verification pending user-run commands. No pytest or other test command was run by the assistant.

#### Landed

- Added `app/core/extraction_memory/recipe_executor.py` as the sole mechanical interpreter for active and candidate `extraction_recipe.v2` recipes.
- The executor supports declared DOM roots/text/attributes, JSON Pointer, captured network JSON, dotted script-state paths, URL components, artifact text, repeated record roots, entity scopes, identity joins, DOM containment/exclusions, transforms, price units, cardinality, exact binding provenance, and typed recipe failures.
- Record identity is established and optionally checked against request/runtime identity before entities and fields are attached.
- The same executor constructs the existing ecommerce-detail, ecommerce-listing, job-detail, and job-listing public record models. It imports no collectors, targeting, entity graph, resolver, or model runtime.
- Added two-page replay fixtures for all four surfaces plus focused executor contracts for fallback bindings, selected-variant-to-network-offer joins, script state, artifact text, minor-unit prices, exclusions, provenance, and typed cardinality failure.
- Added optional identity-to-public-field mapping to the bounded `RecipeBinding` contract.

#### Deleted rather than preserved beside the executor

- Removed the additive `css_recipe_evidence` collector and its value-assembly helper.
- Removed `css_field_rules` replay artifacts and the `css_recipe` artifact type.
- Removed CSS-recipe collector filtering from the engine and all CSS-recipe ranking/price/confidence aliases.
- Removed the listing-only `record_bindings` recipe-kind constant; old formats remain rejected by the v2 compiler rather than executed through compatibility code.

#### De-bloat result

- Combined Phase 1+2 extraction-owned production is **10+ nonblank LOC below HEAD** after adding the schema, compiler, and executor.
- All touched backend production is **130+ nonblank LOC below HEAD**.
- `recipe_executor.py` remains below the oversized-module threshold and is owned with the recipe schema/compiler under `core/extraction_memory`.
- No new oversized-module or cyclomatic-complexity debt was added; executor/compiler/schema functions remain at complexity 20 or lower.
- No database table or column was added.

#### Non-test validation performed

- AST parsing passed for every changed Python file.
- Imports passed for recipe schema, compiler/matcher, and executor.
- All four two-page fixtures validate against `ExtractionRecipeV2`.
- Static ownership debt exactly matches the existing oversized-module and complex-function ledgers with no exceeded allowance.
- No production/test reference remains for `css_recipe_evidence`, `css_field_rules`, `record_bindings.v1`, or `EXTRACTION_RECIPE_KIND_RECORD_BINDINGS`.
- Focused Ruff checks and `git diff --check` pass after the final cleanup.

#### Verification-correction record — 2026-07-11

- Fixed DOM exclusion semantics by retaining the originating `HtmlNode` on text/attribute binding values, so descendants of excluded subtrees cannot leak into public records.
- Consolidated the recipe schema, compiler/matcher, and executor under `app/core/extraction_memory`; package budgets now pass without raising any allowance (`core` 18,920/19,272 and `extraction` 16,162/16,359 at this checkpoint).
- Split executor record/source handling so no new function exceeds cyclomatic complexity 20.
- Corrected recipe-contract test imports to the canonical schema owner instead of re-exporting `ExtractionRecipeV2` from `extraction/contracts.py`.
- Removed stale tests that transported `selector_rules` or treated source-pin/selector payloads as executable recipes. Legacy payloads are now asserted to remain deterministic and to emit no recipe Sentinel state.
- Label scoring now scores verified labels independently of release acceptance; accepted-evidence eligibility remains a separate fail-closed gate. Synthetic gate corpora use accepted run ID 39.
- The accepted commerce evaluation corpus now points to Run 41 and resolves audit-label IDs to captured result directories by exact URL or unique same-product host/path identity. It no longer compares audit result `1` with an unrelated `runs/1/results/1` record merely because the numeric IDs match.
- Removed the always-empty legacy selector-rule return value and metric from the crawl extraction-stage contract; extraction and retry callers now receive only `ExtractionResult`.
- No pytest or other test command was run by the assistant during these corrections; direct fixture/evaluation probes, Ruff, AST/import checks, ownership checks, and `git diff --check` passed.

#### Expected architecture-ratchet state after this phase

- Fixture/schema and executable-detail-recipe checks should pass.
- Recipe-first engine routing, removal of parallel record-producing tiers, and `partial` fallback checks remain intentionally red for Phase 3.
- Model proposal-only output remains intentionally red for Phase 4.

---

## Phase 3 — Make engine recipe-first

### Primary owner

- `extraction/engine.py`

### Work

1. Match active recipe before any generic harvest.
2. Execute active recipe and publish through shared validation.
3. On no match or typed failure, call one discovery entry point.
4. Discovery returns a candidate recipe; engine executes that candidate through the same executor.
5. Remove tier-specific record-producing attempts.
6. Replace tier diagnostics with actual execution diagnostics.

### Required deletion in the same phase

- `_generic_harvest` active-recipe path
- source-pin recipe detection/application helpers
- generic result followed by recipe label
- `partial -> model fallback` rule
- legacy/V3 dual engine routing inside extraction

### Exit gate

Known-template integration test proves:

- recipe lookup precedes harvest
- only declared source readers execute
- generic collector invocation count is zero
- model invocation count is zero
- output matches expected record and provenance

### Phase 3 execution record — 2026-07-11

**Status:** IMPLEMENTED; verification pending user-run commands. No pytest or other test command was run by the assistant.

#### Landed

- `engine.py` now selects an exact active `extraction_recipe.v2` before any discovery work and immediately executes it through the canonical recipe executor.
- Active-recipe success returns without invoking generic collectors, deterministic discovery, Sentinel challengers, or model runtime.
- No-match and typed active-recipe failure enter one bounded deterministic discovery entry point. Discovery may return only a `RecipeCandidate`; the engine executes that candidate through the same recipe executor before publication.
- Removed the engine's generic-harvest attempt, source-pin recipe detection/application, generic-result recipe labeling, model evidence merge/re-resolve route, and `partial -> model fallback` behavior.
- Runtime diagnostics now distinguish persisted `recipe` execution from ephemeral `candidate_recipe` replay. Historical `ml`/`llm` values remain accepted by the read model only for old stored observations; the engine no longer emits them.
- Route matching normalizes placeholder names, so equivalent families such as `{id}` and `{slug}` match without weakening domain/surface/route isolation.
- Job identity values remain strings rather than being coerced as counters, preserving leading zeros and alphanumeric requisition identifiers.
- Added four-surface known-template integration coverage that forces discovery to fail if called, checks exact expected fields, confirms zero collector/model invocations, and verifies resolved binding source paths.
- Cold-start probes for all four surfaces confirm that publication occurs only after deterministic candidate compilation and replay. Model-assisted proposal compilation remains Phase 4.

#### Deletion and debt result

- `engine.py`: 656 nonblank lines and removed from the oversized-module debt ledger.
- `core`: 19,107 / 19,272 nonblank-line budget.
- `extraction`: 16,292 / 16,359 nonblank-line budget.
- `result_building.py` remains at its existing 700-line ceiling; no allowance was raised.
- No new oversized module or cyclomatic-complexity debt was introduced.
- Serena onboarding metadata was removed from the repository and is not part of the patch.

#### Non-test validation completed

- Ruff passed on all Phase 3 owners and affected tests.
- `mypy app` passed with zero issues across 364 source files.
- Direct four-surface active-recipe exit-gate probe passed.
- Direct four-surface cold-start compile/replay routing probe passed.
- Static engine forbidden-path ratchets passed.
- Ownership/LOC/complexity checks and `git diff --check` passed.

#### Expected architecture-ratchet state after this phase

- Recipe-first routing, removal of parallel record-producing tiers, executable detail bindings, fixture coverage, and absence of `partial` fallback should pass.
- The sole expected red architecture ratchet is model proposal-only output, assigned to Phase 4.

---

## Phase 4 — Convert discovery and model runtime into a recipe compiler

### Primary owners

- existing collectors/targeting/entity logic as discovery helpers
- `model_runtime.py`
- canonical recipe compiler

### Work

1. Discovery establishes record boundaries, identity, joins, and candidate field paths.
2. Deterministic readers propose bindings first.
3. Optional model receives captured grounded representation and proposes only paths/joins/senses.
4. Compiler emits a candidate recipe.
5. Executor replay is mandatory before publication or persistence.
6. Remove all model evidence/value injection.
7. Keep provider/accounting diagnostics, but tie them to recipe discovery.

### Required deletion in the same phase

- `ModelFallbackResult.evidence` record-production semantics
- generalized evidence merge/re-resolve path
- model tier names in public extraction routing
- duplicated flat-map/grounding code not consumed by the compiler

### Exit gate

Forced cold-start test proves:

- discovery/model proposes a recipe
- model cannot publish a value directly
- candidate executor reads every published value from capture
- ungrounded proposed paths are rejected
- first page can publish only after candidate replay succeeds

---

## Phase 5 — Implement promotion, immutable releases, and drift without parallel state

### Primary owners

- extraction-memory persistence
- existing observations/releases/manifests

### Work

1. Persist candidate, active, suspended, retired states only.
2. Promote automatically after successful execution on distinct samples or explicit operator approval.
3. Freeze exact recipe version into run release snapshot.
4. Record typed execution outcomes and drift observations.
5. Suspend after confirmed distinct-page failures.
6. Activate repair as a new immutable version; never mutate an active snapshot.
7. Collapse extraction profile source pins into recipe data.

### Required deletion in the same phase

- generic winning-source auto-learning
- repair queue state with no executing consumer
- cutover labels used to choose legacy versus V3 runtime
- legacy release payload
- duplicate extraction-profile storage semantics

### Exit gate

Three-run test:

1. cold start compiles candidate and publishes through candidate execution
2. second distinct product validates/promotes or uses active recipe according to policy
3. later known product uses active recipe with no discovery/model

Drift test proves one failed binding causes explicit repair discovery, not silent generic mixing.

---

## Phase 6 — Migrate ecommerce detail and close Run 41 structural failures

### Work

1. Express exact selected-child identity and offer/variant joins as recipe bindings.
2. Express price unit/sense in recipe bindings and shared normalization.
3. Express shell/record-root requirements in validation.
4. Express category, SKU, image, and variant ownership relative to the established record.
5. Re-run all accepted Run 41 cases through active or candidate recipes.
6. Delete detail-specific generic patches made redundant by explicit bindings.

### Acceptance cases

- selected-child/family contamination: 139, 150, 186, 209
- terminal shell/pseudo-product: 142, 154, 178, 196, 198
- record/entity loss: 124, 146, 194
- price semantics: 115, 117, 144, 167
- weak evidence/candidate ranking family from the Run 41 ledger
- category positive and negative cases
- variant completeness and ownership cases

### Exit gate

- no cross-child field lineage
- no shell record
- correct price units/senses
- all published values trace to recipe bindings
- known-domain second run performs no generic harvest/model
- cumulative extraction-owned production LOC below current by at least 2,000 lines

---

## Phase 7 — Migrate listing and job surfaces to the same runtime

### Work

1. Treat repeated listing/job row discovery as recipe compilation.
2. Compile repeated-root and per-row relative bindings.
3. Execute the same recipe executor for all rows.
4. Require repeated row boundaries unless structured/network evidence proves a singleton.
5. Preserve listing readiness/acquisition failures as acquisition diagnostics.
6. Migrate any remaining DomainMemory selectors into canonical recipes or invalidate them.
7. Delete legacy selector runtime/store/API once all four surfaces use recipe v2.

### Acceptance cases

- Run 39 Arcteryx: repeated products or honest failure; no utility singleton
- Run 40 Dyson: repeated products or honest failure; no accessory/navigation row
- Runs 42–45: grounded repeated jobs or honest acquisition/readiness/record-boundary failure
- second-run known listing/job executes learned repeated-root recipe without generalized discovery

### Exit gate

- one executor for all four surfaces
- no surface-specific alternative publication path
- DomainMemory selector extraction store and duplicate UI/API deleted

---

## Phase 8 — Delete unearned branch systems and shrink evaluation/UI

### Work

1. Use the deletion ledger to remove every family marked delete.
2. Delete stale reports and labels outside the accepted evidence window from release decisions.
3. Shrink eval to accepted artifact replay, output comparison, second-run work comparison, and drift tests.
4. Replace multiple selector/profile/source-pin panels with one recipe view/editor, or remove the UI if backend workflow is not proven.
5. Remove unused dashboard metrics, config, schemas, and compatibility types together with readers.
6. Correct architecture docs and codebase map to retained real owners only.

### Exit gate

- `backend/eval/` <= 1,200 nonblank LOC unless every excess line has an accepted reader
- no orphan database fields, API routes, frontend types, or metrics
- no implementation-coupled tests for deleted systems
- final extraction-owned production LOC <= 16,767

---

## Phase 9 — Fresh live proof and closure

No ad hoc production patches during this phase. A failure reopens the earliest owning phase.

For each live case record:

- run/result ID
- domain/surface/route/template key
- acquisition contract/path
- recipe state/version
- active versus candidate execution
- declared source readers
- generic discovery/model invocation count
- exact binding failures
- output and provenance
- elapsed time and record count

### Required live sequences

1. At least three ecommerce-detail domains:
   - first unseen product cold start
   - second distinct product validation/promotion
   - third product active-recipe replay
2. At least two ecommerce-listing domains with two pages each.
3. At least one job-listing domain with two pages.
4. One deliberate drift fixture or controlled changed template.
5. One domain requiring browser acquisition to show acquisition and extraction memories compose without duplication.

### Close requirements

- active-recipe success performs no generic harvest and no model call
- active recipe reduces work relative to cold start
- output parity or improvement is proven
- drift never publishes stale mixed values
- all accepted Run 41 P0 cases pass
- listing false-success cases pass
- final production LOC and file budgets pass
- only this plan remains active

---

## 11. Verification Commands and Required Measurements

Implementation may refine exact test module names, but it must preserve these measurements.

### Per-slice diff gate

```bash
git diff --shortstat main
git diff --numstat main -- \
  backend/app/extraction \
  backend/app/core/extraction_memory \
  backend/app/persistence/extraction_memory.py \
  backend/app/persistence/extraction_memory_sources.py \
  backend/app/models/extraction_memory.py \
  backend/app/crawl/pipeline/record_extraction_stage.py \
  backend/app/crawl/domain_memory_service.py
```

### Required runtime assertions

- recipe lookup timestamp precedes any discovery collector
- collector IDs executed on active recipe equal recipe-declared readers only
- model invocation count is zero on active-recipe success
- active-recipe execution result identifies exact recipe version
- every published field maps to one successful binding outcome
- no output record can exist without `RecipeExecutionResult`
- first-page publication identifies candidate recipe replay
- drift includes exact failed binding and no stale value

### Focused architecture verification

Retain or create focused suites for:

- recipe schema/compiler/executor
- recipe-first engine routing
- cold-start candidate replay
- promotion and immutable release
- drift/suspension/repair
- Run 41 detail cases
- listing repeated-root recipes
- model proposal grounding
- final architecture ownership and LOC

Do not rely on a broad green suite as proof of the architectural contracts.

---

## 12. Explicit Non-Goals

- no retailer-specific Python adapters in the generic runtime
- no automatic cross-product synthesis when variant relationships are absent
- no LLM-generated missing product values
- no parallel V4 package
- no rewrite of acquisition path learning, cookie memory, browser security, or SSRF controls
- no persistence/publication repair of extraction errors
- no new enrichment behaviour
- no indefinite shadow execution of both old and new systems
- no preservation of code merely because tests exist for it

---

## 13. Completion Checklist

- [ ] This is the only active extraction plan.
- [ ] `INVARIANTS.md` and architecture docs describe recipe-first execution.
- [ ] One recipe schema serves all four surfaces.
- [ ] One recipe executor is the only public-record producer.
- [ ] Cold-start discovery compiles and replays a candidate recipe before publication.
- [ ] Model output is restricted to grounded binding proposals/adjudication.
- [ ] Active-recipe success skips generic discovery and model calls.
- [ ] Recipe matching happens before generic harvest.
- [ ] Old source-pin, selector, record-binding, and cutover semantics are deleted.
- [ ] Extraction profile is folded into canonical recipe data or deleted.
- [ ] Run 41 P0 detail cases pass with binding provenance.
- [ ] Runs 39/40 and job-listing cases pass or fail honestly.
- [ ] Two-run and three-run live reuse is proven.
- [ ] Drift recovery is proven without stale mixed output.
- [ ] Extraction-owned production LOC is <= 16,767.
- [ ] Evaluation is reduced to accepted behavioural gates.
- [ ] No unearned persistence, UI, metric, config, or test system remains.

---

## 14. Audit Notes

- The current focused architecture/runtime/contract suite passing is not acceptance; it proves the current invariants are internally consistent.
- Acquisition is the reference architecture because learned domain state changes future work and skips the failed path.
- Selectors are not inherently forbidden. Global heuristic selector banks and unverified one-page selectors are forbidden; verified domain/template-relative bindings are valid recipe primitives.
- The first implementation task is documentation/tests/deletion-ledger work, not another runtime feature.
- Any implementation proposal that adds a new extractor beside the current engine violates this plan.
