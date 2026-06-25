# Plan: Upstream Product Extraction Integrity Audit and Remediation

**Created:** 2026-06-25  
**Agent:** GPT-5.5 Thinking using Serena, Codeweave, and stored crawl artifacts  
**Status:** IN PROGRESS — IMPLEMENTATION NOT STARTED  
**Touches buckets:** acquisition artifacts and diagnostics, structured/JS/network/DOM collectors, evidence contracts, product identity, entity linking, variant/offer/asset resolution, validation and verdicts, materialization/public boundary, artifact replay and quality gates

## Goal

Repair product-output correctness at the earliest subsystem that owns each fact. The pipeline must preserve source object boundaries, establish the primary product before attaching children, and resolve only evidence demonstrably belonging to that product. Materialization, persistence, export, and presentation must not repair wrong titles, brands, variants, offers, identifiers, availability, or images after contamination has occurred.

Done means the same captured artifacts deterministically produce product-scoped, lineage-backed output; genuine source absence or blocked subresources are reported honestly; unrelated page content cannot become product data; and the release gate evaluates replayed output rather than manually declaring issue classes fixed.

## Why This Replaces the Previous Plan

The previous plan mixed architecture debt, completed refactors, output symptoms, and downstream safety patches. It also froze a bug list before completing an artifact-grounded root-cause audit. This plan starts from current code and latest artifacts. Downstream sanitization is a final safety boundary only, never the owner of semantic correctness.

The current unverified working-tree changes in these files are not an accepted implementation baseline:

- `backend/app/core/records/output_safety.py`
- `backend/app/extraction/materialization.py`
- `backend/tests/unit/test_output_safety.py`
- `.gitignore`

Moving title, brand, variant-family, availability, SKU, and image repair into `output_safety.py` is contrary to the target architecture. During implementation, each rule must move to its upstream owner and redundant output repair must be deleted.

## Evidence Reviewed

- Latest multi-domain crawl output supplied by the user.
- User-supplied initial audit.
- Current extraction, entity, resolution, materialization, validation, and acquisition code.
- Stored records, summaries, diagnostics, and captured HTML for representative failures.

### Confirmed artifact findings

1. **END Clothing cap: upstream product-boundary failure.** The browser acquired about 1.7 MB of usable HTML. The cap record included SKUs and size inventories from unrelated products. Lineage shows these became variant entities and inherited the cap's parent offer. The primary defect is structured-object scoping, identity, entity linking, and inheritance.
2. **Target duvet: missing fields are not all proven extraction defects.** Usable visible HTML supplied title and images, while several product-data requests failed. Price, currency, availability, and richer data may therefore be absent from the captured evidence. The correct result is a source-limited diagnostic unless another captured source contains the values.
3. **Downstream repair masks provenance.** The END raw record contained brand and raw availability while the public record differed. Post-resolution cleanup cannot repair wrong entity ownership and can obscure the failed upstream decision.
4. **The current quality gate can be self-fulfilling.** A fixture labels issue classes as fixed, and a clean result can follow those declarations. A gate must replay artifacts and inspect generated records and findings.

## Confirmed Bugs vs. Issues Requiring Proof

Confirmed defects include cross-product children and assets, aggregate size blobs represented as variants, raw availability values, identifier conflation, weak scalar candidates, unsafe offer inheritance, false-clean verdicts, and semantic repair after materialization.

The following are not automatically bugs: high variant counts, decimal-string prices, mixed currencies across storefronts, long product-specific descriptions, missing optional fields, no variants for a single-SKU product, legitimate parent/child price differences, or absent availability where no stock signal exists. Each requires artifact proof before implementation work is opened.

## Non-Negotiable Architecture Rules

1. Acquisition records what was captured, what failed, and which product-data sources were unavailable.
2. The primary product is selected before any variant, offer, option, or asset is attached.
3. JSON-LD nodes, JS objects, network roots, DOM product containers, and recommendation sections retain separate identities.
4. Parent-child relations require explicit references or strong multi-signal product identity agreement. Being on the same page is not a relationship.
5. Field arbitration remains per field, but every candidate stays scoped to its source product/entity.
6. Missing commerce facts remain missing with a reason when evidence is absent. No values are invented.
7. Public-boundary code may enforce allowed keys, types, enums, and empty-value stripping only.
8. Fixes must be generic across domains. No product values, URL exceptions, or hostname rescue branches.
9. Quality status is calculated from generated replay output, not a manually assigned resolution label.

## Root-Cause Inventory

### U-01 — Page usability hides field-source incompleteness

A page can contain useful product HTML while product-data sources needed for offers or variants fail. Acquisition must expose source capability by field family: HTML/structured data present, product payload observed, payload unavailable, malformed payload, and interaction-required data not captured. Page usability and field-source completeness are separate outcomes.

**Owners:** acquisition capture, result builder, acquisition contracts, diagnostic serialization.

### U-02 — Structured collectors lack selected-root scope

JSON-LD traversal currently sees every product-like object. Build a source graph per script, select candidate page-product roots using canonical URL, `mainEntity`, `@id`, SKU/product ID, H1/title agreement, and container context, and quarantine recommendation or unrelated Product nodes.

**Owners:** `extraction/collectors/jsonld.py`, structured traversal helpers, evidence normalization.

### U-03 — JS/network mapping is insufficiently root-aware

Recursive object mapping must preserve response URL, frame URL, root path, object ID, parent object ID, schema fingerprint, and candidate product identities. Generic keys are mapped only when the object agrees with the selected product or has an explicit relation.

**Owners:** `collectors/js_state.py`, `collectors/metadata.py::NetworkCollector`, network-capture config, field mappings.

### U-04 — Evidence scope is too weak

Standardize immutable source-root ID, object/container ID, role, relation type/target, identity candidates, confidence basis, and raw versus canonical value. Normalization may clean a value but must not erase its scope.

**Owners:** `extraction/contracts.py`, evidence helpers, pipeline normalization, all collectors.

### U-05 — Product entity grouping merges on insufficient identity

Use a conflict-aware identity graph. Strong identities are canonical product URL, GTIN, manufacturer model/MPN, product ID, and correctly namespaced SKU. Title is supporting evidence only. URL-only evidence may enrich one selected product but must not merge arbitrary roots.

**Owners:** `extraction/entities.py`, product identity and model-code helpers.

### U-06 — Variant ownership is resolved too late

A public variant entity is created only when its source has an explicit parent relation or strong agreement with the selected product's URL, product ID, model code, SKU family, title, and axes. Related products remain separate roots. Output filtering is not the primary defense.

**Owners:** variant collectors, `entities.py`, `resolution.py`.

### U-07 — Option inventories and purchasable variants are conflated

Model option group, option value, selected option state, purchasable variant/SKU, and variant offer separately. Do not turn a list of sizes into one variant or split it into fake variants. Do not create a Cartesian product.

**Owners:** variant collectors, option catalogs, `variant_axis.py`, `variant_option_value.py`, entities and validation.

### U-08 — Offer ownership and inheritance are weak

Price, currency, availability, seller, sale/original status, and locale form one typed offer unit. Every offer has a proven product or variant owner. Parent inheritance is allowed only into proven children, with no conflicting child offer and explicit lineage.

**Owners:** offer collectors, `entities.py`, `resolution.py`, `validation.py`.

### U-09 — Availability is canonicalized too late

Retain raw source text for provenance, but canonicalize the evidence value before entity resolution. Parent availability aggregation occurs only after child ownership and matrix completeness are proven.

**Owners:** source-specific coercion and shared field coercion before resolution.

### U-10 — Identifier namespaces are conflated

Distinguish `product_id`, `product_sku`, manufacturer model, `variant_id`, `variant_sku`, GTIN/barcode, and source structural IDs. Generic `id` values remain non-public until their namespace is proven by source schema and context.

**Owners:** field mappings, collectors, entity hints, public contracts.

### U-11 — Asset selection lacks product ownership

Attach assets to source product/variant objects or a product DOM gallery. Rank only within the selected family using role, dimensions, delivery transform, alt text, style/SKU/color agreement, and container relation. Recommendation and unrelated colorway assets remain rejected evidence.

**Owners:** asset collectors, `entities.py`, asset resolution, image config.

### U-12 — Scalar admission and text fidelity are weak

Colors, condition words, navigation fragments, endpoint names, option labels, and search/shipping copy must be rejected at admission. Complete descriptions must be preserved; hard character slicing cannot masquerade as complete source text. Ranking chooses only among admissible same-product candidates.

**Owners:** DOM/metadata/structured collectors, shared field coercion, title scorer, text sanitizer, resolution.

### U-13 — Missing-field logic does not distinguish absence classes

Each requested/default field must end in one evidence state: `captured_and_resolved`, `captured_but_rejected`, `captured_conflicting`, `not_present_in_captured_sources`, `source_unavailable`, `interaction_required_not_captured`, `not_applicable`, or `not_requested`. Only proven extraction misses drive extractor fixes.

**Owners:** acquisition diagnostics, validation, result building, verdict logic.

### U-14 — Materialization and output safety own semantic repair

After upstream fixes, remove title recovery, brand deletion, variant-family filtering, SKU repair, availability choice, and image conflict selection from output safety. Materialization serializes decisions and lineage; the public firewall enforces shape only.

**Owners:** upstream collector/entity/resolver modules and the public firewall.

### U-15 — Public values can diverge from the evidence graph

All deterministic transformations must be represented before graph serialization as decisions, derived facts, or field transforms with evidence IDs. No hidden semantic mutation after graph finalization.

**Owners:** pipeline, resolution transforms, materialization.

### U-16 — Quality gates trust declarations instead of output

A fixture may describe expected invariants and affected artifacts, but issue resolution is computed from replay output. The gate must fail on cross-entity lineage, invalid enums, identifier conflicts, unresolved field states, and public/evidence divergence even when field presence counts look acceptable.

**Owners:** artifact replay harness and catalog quality audit tests.

## Target Pipeline

```text
Acquisition
  -> captured HTML / structured scripts / network payloads / interaction artifacts
  -> source-capability diagnostics
Collectors
  -> typed evidence preserving source root, object identity, role and relations
Root selection
  -> one selected PDP product or explicit unresolved/ambiguous target
Entity graph
  -> product with only proven variants, options, offers and assets
Resolution
  -> per-field decisions scoped to the selected entity
Validation
  -> integrity findings + field evidence states + honest verdict
Materialization
  -> serialization only
Public firewall
  -> schema/type/enum/key enforcement only
```

## Acceptance Criteria

- [ ] Every public child row has lineage to an accepted parent-relation decision.
- [ ] Unrelated Product, Offer, Variant, and Asset objects cannot attach to the selected product.
- [ ] A public variant never represents multiple independent sizes in one scalar.
- [ ] Parent offer inheritance is impossible before product and child ownership are proven.
- [ ] Raw source availability URLs cannot reach resolved/public values.
- [ ] Product IDs, SKUs, variant IDs, variant SKUs, model codes, and structural IDs remain distinct.
- [ ] Primary and additional images come only from the selected product/variant family.
- [ ] Complete descriptions are preserved; incomplete values cannot outrank complete evidence.
- [ ] Field absence is classified as extraction miss, source absence, source failure, interaction gap, conflict, or not applicable.
- [ ] Output safety, persistence, export, and UI contain no semantic product repair.
- [ ] Public records cannot diverge from the evidence graph through post-resolution mutation.
- [ ] Quality gates replay artifacts; manually asserted fixed labels cannot make them pass.
- [ ] No site-specific values, hostname branches, product exceptions, or fabricated data are introduced.

## Do Not Touch

- Do not patch persisted/exported JSON to hide upstream defects.
- Do not add product/domain-specific output filters.
- Do not use generated commerce facts to fill missing deterministic evidence.
- Do not infer brand from hostname/retailer or availability from a generic button.
- Do not split aggregate option text into fake variants.
- Do not force a price where the source is quote-only, region-gated, unavailable, or not captured.
- Do not run a live crawl until the final offline artifact gate passes.
- Do not reset or overwrite unrelated user working-tree changes.

## Implementation Slices

### Slice 1 — Freeze Artifact-Grounded Failure Cases
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** existing artifact replay fixtures and test harness only; no production correction yet.  
**What:** Create a compact case index pointing to stored HTML, diagnostics, summaries, and records for every major failure class. For each suspicious missing field, record whether evidence is present, rejected, conflicting, unavailable, interaction-dependent, or genuinely absent. Remove manually asserted resolution as a source of truth.  
**Verify:** Offline audit reports all cases and evidence states without network access.

### Slice 2 — Source Capability Diagnostics
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** acquisition contracts, browser capture/result builder, diagnostics config, replay serialization.  
**What:** Represent field-critical product-data source failures separately from page usability. Preserve product payload failures, malformed payloads, and missing interaction artifacts as first-class observations.  
**Verify:** A Target-like page remains usable for title/images while offer fields are classified `source_unavailable`, not generic missing or fabricated.

### Slice 3 — Evidence Scope and Relation Contracts
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** extraction contracts, evidence helper, pipeline normalization, collectors.  
**What:** Standardize source root/object/container IDs, role, relation type/target, identity candidates, and raw versus canonical value. Ensure no normalizer discards scope.  
**Verify:** Two product objects in one script remain independently identifiable throughout the evidence ledger.

### Slice 4 — Primary Product Root Selection
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** JSON-LD/metadata/DOM root discovery, product identity helpers, target selection.  
**What:** Select the requested PDP product before linking children. Use canonical/final URL and strong identity agreement; quarantine recommendations and unrelated roots.  
**Verify:** A page with a main product plus related Product nodes selects only the requested product and records rejected roots with reasons.

### Slice 5 — Conflict-Aware Product Entity Linking
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** `entities.py`, identity/model-code helpers, focused entity tests.  
**What:** Replace weak merge behavior with strong identity unions plus explicit conflicts. Title-only and URL-fallback evidence may enrich but not merge contradictory products.  
**Verify:** Same title with different product URLs or SKUs remains separate; canonical URL plus matching SKU merges correctly.

### Slice 6 — Collector Root Scoping
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** `collectors/jsonld.py`, `collectors/js_state.py`, `collectors/metadata.py`, network-capture config and mappings.  
**What:** Map only selected-root objects or explicitly related children. Correct payload schema classification and reject generic nested dictionaries lacking same-product context.  
**Verify:** Related structured products never enter the selected product graph; valid explicit variant structures remain supported.

### Slice 7 — Variant, Option, and Family Model
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** variant collectors, option catalogs, variant axes/value helpers, entities, validation.  
**What:** Separate option inventory from purchasable variants; require a proven parent relation plus sellable identity or commercial evidence for public rows. Remove size-blob and related-product repair from the public boundary.  
**Verify:** Aggregate size text becomes option evidence or a finding, not one variant; real size SKUs remain individual variants; no Cartesian synthesis.

### Slice 8 — Offer Ownership and Parent Semantics
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** offer collectors, entities, resolution, validation, price coercion.  
**What:** Resolve price, currency, availability, seller, and sale status as one owned offer. Define selected/default/range/minimum semantics and constrain inheritance.  
**Verify:** Parent/child price differences are deterministic and lineage-backed; unrelated offer leakage and iteration-order selection are impossible.

### Slice 9 — Availability and Identifier Semantics
**Status:** DONE — VERIFIED 2026-06-25  
**Files:** field mappings/coercion, source collectors, contracts, entity hints.  
**What:** Canonicalize availability before decisions while retaining raw provenance. Enforce distinct product/variant/model/barcode/structural ID namespaces.  
**Verify:** No raw availability URL reaches public output; a source variant ID cannot appear as SKU without explicit semantics.

### Slice 10 — Product-Scoped Asset Graph
**Status:** TODO  
**Files:** asset collectors, entities, asset resolution, image config.  
**What:** Require product/variant ownership for gallery assets; use role, dimensions, transform identity, alt/style/SKU/color agreement, and container relation. Remove output-stage image conflict filtering.  
**Verify:** Other-product and unrelated-colorway images are rejected before asset decisions; thumbnails cannot beat adequate product images.

### Slice 11 — Scalar Admission, Fidelity, and Ranking
**Status:** TODO  
**Files:** DOM, metadata, and structured collectors; shared text coercion; title scorer; text sanitizer; resolution.  
**What:** Reject color, condition, navigation, control, endpoint, search, and shipping candidates at admission. Preserve complete descriptions and rank only same-product admissible evidence.  
**Verify:** Values such as `Black`, `Refurbished`, `& More`, `product.do`, selected-option labels, and incomplete snippets cannot become canonical product fields.

### Slice 12 — Honest Completeness, Findings, and Verdicts
**Status:** TODO  
**Files:** validation, result building, engine verdict, harness quality reporting.  
**What:** Generate field evidence states and separate transport success from data integrity. Block clean success for unresolved identity, offer, asset, or variant integrity while allowing honest partial output for genuine absence.  
**Verify:** A page with unavailable offer sources is partial with precise reasons; a complete page with valid evidence rejected by extraction is classified as an extraction defect.

### Slice 13 — Remove Downstream Semantic Repair
**Status:** TODO  
**Files:** `output_safety.py`, materialization, public firewall, related tests.  
**What:** After upstream slices pass, delete title, brand, variant, SKU, image, and availability decision logic from output safety. Keep only allowed-key, type, enum, and empty-value enforcement. Reconcile or remove the current unverified dirty changes rather than layering over them.  
**Verify:** Materialized public values correspond exactly to decisions, derived facts, and accepted evidence; no post-graph semantic mutation remains.

### Slice 14 — Artifact-Replay Quality Gate
**Status:** TODO  
**Files:** replay harness, catalog quality audit, compact case manifest.  
**What:** Re-run stored artifacts through the real pipeline and calculate issue status from generated output and findings. Detect cross-entity lineage, enum leaks, identifier conflicts, field-state failures, and public/evidence divergence.  
**Verify:** The gate fails on current product-boundary and source-availability defects without relying on a manually assigned fixed status, and passes only when replay output satisfies the invariants.

### Slice 15 — Documentation, Offline Validation, and User-Owned Live Gate
**Status:** TODO  
**Files:** canonical architecture, business-logic, invariant docs, and this plan.  
**What:** Document final ownership, run focused then full offline validation, inspect the final diff for downstream or site-specific patches, and provide one final multi-site acceptance command for the user to run.  
**Verify:** All offline suites and architecture gates pass; the user-run live gate has zero unresolved integrity blockers, with genuine source absence represented honestly.

## Execution Order and Stop Rules

- Work one slice at a time in the stated order.
- Every production change begins with a failing artifact replay or minimal generic regression.
- Do not implement a downstream workaround while an upstream owner remains unfixed.
- When a suspected issue is not reproducible from captured evidence, classify it as unproven and do not add code.
- Validate the smallest relevant scope after each slice and record the exact evidence and result in this plan.
- Do not run a live crawl before Slice 15.
- Stop after each implementation slice for review; this documentation task does not begin implementation.

## Notes

- The attached initial audit correctly identified visible availability and variant symptoms, but output sanitization is too late to be the primary remedy. Artifact lineage shows wrong children can already exist as resolved entities before export.
- Field-presence percentages are triage signals only. They do not distinguish genuine source absence, unavailable product-data sources, incomplete interaction capture, conflicting evidence, or extraction failure.
- Existing output safety may remain temporarily as a guard while upstream work is incomplete, but it must not become permanent semantic ownership.
