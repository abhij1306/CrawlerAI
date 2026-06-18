# CrawlerAI / Invoro Extraction Architecture — Final Audit Report for Codex

**Prepared for:** Codex implementation planning  
**Current code source audited:** `app.zip` uploaded in this conversation  
**Proposal audited:** Claude's `Invoro — Evidence Graph Implementation Plan v3 (Final)`  
**Primary objective:** Reduce recurring ecommerce extraction defects by replacing record-first resolution with evidence-backed, entity-aware extraction.

---

## 1. Executive Summary

The Claude plan is directionally correct: the current extraction architecture needs to move toward an evidence graph, entity-scoped resolution, stricter variant/offer validation, request-context-aware currency handling, and validator-driven output. However, the plan is **not fully accurate against the latest `app.zip`**. Several important assumptions are wrong or incomplete.

The biggest corrections are:

1. **LLM detail fallback is still active in the latest code.**
   - `apply_direct_record_llm_fallback()` is guarded for detail surfaces.
   - But `pipeline/extraction_loop.py` explicitly calls `apply_llm_fallback()` for detail records.
   - `apply_llm_fallback()` can fill missing detail fields from HTML when deterministic values are absent.
   - Claude's statement that LLM field filling does not run on ecommerce detail is therefore incorrect.

2. **Image deduplication is not raw-URL-only anymore.**
   - The current code already has canonical URL image dedupe in `dom/image_extraction.py` via `canonical_image_url()` and `dedupe_image_urls()`.
   - A new `AssetEntity` model may still be useful for provenance and owner scope, but it should not be treated as the primary duplicate-image fix.

3. **The proposed thread-local evidence builder is too weak for the current async pipeline.**
   - It would miss some candidate paths.
   - It is risky in an async service.
   - Evidence must be attached index-by-index to candidate insertion, not inferred later by raw value matching.

4. **The proposed raw-value-based entity resolver is unsafe.**
   - Values like `Black`, `USD`, `129.00`, `InStock`, or `Brown` can appear in multiple scopes.
   - Scope cannot be recovered from value text alone.
   - Candidate/evidence IDs must be preserved from collection through resolution.

5. **Existing mutators must be audited before layering validators.**
   - Current price, currency, variant, and money repair code mutates records in ways that can hide contradictions.
   - Those mutators should become explicit transforms backed by evidence and validation findings.

**Recommended decision:** Do not rebuild the whole backend from scratch. Keep acquisition, adapters, JS-state extraction, network capture, persistence, public record firewall, export schema, and LLM infrastructure. Rebuild the **extraction decision core** around typed evidence, entity linking, validators, and a resolver.

---

## 2. Current Codebase Findings from `app.zip`

### 2.1 Current architecture is record-first, not evidence-first

The central detail assembly path is still built around collecting candidates and then materializing a flat record:

- `app/services/extract/detail/assembly/record_assembly.py`
- `app/services/extract/detail/assembly/tiers.py`
- `app/services/extract/detail/assembly/candidate_collection.py`
- `app/services/extract/detail/assembly/final_cleanup.py`

The key path in `candidate_collection.py` is:

```text
_add_sourced_candidate()
  -> add_candidate()
  -> candidate_sources[field]
  -> field_sources[field]

_materialize_record()
  -> _ordered_candidates_for_field()
  -> grouped_candidates[0]
  -> finalize_candidate_value()
  -> final_cleanup / price repair / currency repair / public finalization
```

This creates a flat record before all candidate provenance, entity scope, and field contradictions are fully resolved.

### 2.2 Source priority is still the primary scalar resolver

`candidate_collection.py` defines `SOURCE_PRIORITY` and uses `_ordered_candidates_for_field()` / `_field_source_rank()` to order candidates.

For scalar fields, `_materialize_record()` effectively chooses:

```python
selected_source = grouped_candidates[0][0]
winning_values = grouped_candidates[0][1]
finalized = finalize_candidate_value(field_name, winning_values)
```

And in `field_candidates/finalization.py`, scalar fallback is essentially:

```python
return values[0]
```

This means a value can win because it came from a high-ranked source, even if it belongs to the wrong entity scope. This is consistent with failures such as:

- root color mismatch against variants/title
- root currency differing from variant currency
- cross-sell product text contaminating variant color
- wrong root price propagated to variants

### 2.3 Variant logic is mature but still row-based

Important existing files:

- `app/services/extract/variant_identity_merge.py`
- `app/services/extract/variant_group_validator.py`
- `app/services/extract/variant_normalization/backfill.py`
- `app/services/extract/variant_normalization/contract.py`
- `app/services/extract/detail/variants/dom_extraction.py`
- `app/services/extract/detail/variants/dom_availability.py`

The latest code has meaningful variant identity and richness logic. `variant_identity_merge.py` already handles:

- identity keys
- semantic identity
- option values
- richness-based row merge
- dedupe behavior

However, the model still collapses to merged variant rows. There is no internal graph of:

```text
ProductEntity
  -> VariantEntity
       -> OfferEntity
            -> price
            -> currency
            -> availability
            -> sku/url
```

This is the architectural cause of recurring size-only or offer-incomplete variant bugs.

### 2.4 DOM skip logic can still skip when variants have offer gaps

`dom_completion.py` already has `_variant_signal_strength()` and `_should_collect_dom_variants()`, which is good.

But `record_has_rich_existing_variants()` in `dom_section_targets.py` treats a variant as rich if it has an axis and **any** transport field among:

```text
sku, price, currency, url, image_url, availability, stock_quantity
```

This can incorrectly treat axis + availability-only variants as rich enough and skip deeper DOM collection, even when price/currency/offer data is missing.

The skip decision should require **offer completeness**, not just any transport field.

### 2.5 LLM fallback is still active for detail surfaces

This is the most important correction to Claude's plan.

Observed current behavior:

- `pipeline/direct_record_fallback.py::apply_direct_record_llm_fallback()` has a detail guard and returns early for detail surfaces.
- `pipeline/direct_record_fallback.py::apply_llm_fallback()` does **not** have the same guard.
- `pipeline/extraction_loop.py` explicitly calls `apply_llm_fallback()` when `"detail" in context.surface` and records exist.

Therefore, detail extraction can still call `extract_missing_fields()` for missing fields.

If the product direction is “LLM must not fill ecommerce detail fields,” this must be fixed in two places:

1. Guard the call site in `pipeline/extraction_loop.py`.
2. Add a defensive guard inside `apply_llm_fallback()` itself.

### 2.6 Image dedupe is stronger than Claude's plan assumes

Current image code already includes canonical dedupe:

- `app/services/extract/dom/image_extraction.py`
  - `canonical_image_url()`
  - `dedupe_image_urls()`
  - Shopify-aware image keys
  - width/height-aware image scoring
- `app/services/extract/detail/images/materialize.py`
- `app/services/extract/detail/images/dedupe.py`

Therefore, do **not** treat image dedupe as raw URL string equality only.

The remaining image architecture gap is not dedupe itself. It is lack of internal asset scope:

```text
product gallery image
variant image
description image
cross-sell image
logo/tracking image
```

An `AssetEntity` can still help, but it should be scoped as an evidence/provenance enhancement, not the top priority duplicate fix.

### 2.7 Price and currency code exists but mutates too much

Important files:

- `app/services/extract/detail/price/core.py`
- `app/services/extract/detail/price/money_repair.py`
- `app/services/extract/variant_normalization/backfill.py`
- `app/services/extract/detail/assembly/final_cleanup.py`

Current behavior includes:

- reconciling currency with URL hints
- propagating parent price/currency into variants
- dropping variant rows when currencies mismatch
- adjusting root price based on variant price range
- money repair copying parent price into variants

These may be individually useful, but architecturally dangerous when they run before evidence-backed validation. They can turn contradictions into apparently clean output.

Codex should audit all silent mutators and convert them into explicit transforms with validation findings.

### 2.8 Network capture lacks enough request context for currency/locale truth

`acquisition/browser_capture.py` captures network payloads with fields like:

```text
url
method
status
content_type
endpoint_type
endpoint_family
body
```

It does not sufficiently capture:

```text
response_id
request_url
final_url
request headers subset
response headers subset
redirect chain
body hash
browser locale
cookie/country context
captured_at
resource type/frame
```

This is a key limitation for currency and locale issues. Currency cannot be resolved reliably using URL/TLD alone.

### 2.9 Source trace exists but is not evidence-grade

`export/schema.py` currently has:

```python
class FieldProvenance(BaseModel):
    status: str
    value: Any
    sources: list[str]
    selector_trace: dict | None
```

This is not enough for debugging recurring extractor issues. It should eventually expose:

```text
winning_evidence_ids
candidate_count
rejected_candidate_count
conflict_count
validation_finding_ids
resolver_rule
llm_used
```

### 2.10 Test coverage is a major gap

The uploaded zip appears to contain no test suite for the extraction core. No meaningful `test_*.py` files were found.

Before or alongside implementation, Codex should create a regression harness for the 30 reported failures and focused synthetic fixtures for resolver behavior.

---

## 3. Audit of Claude's Plan

### 3.1 What Claude's plan gets right

Claude's plan is correct on the following principles:

1. **Evidence-first architecture is the right direction.**
   - The system should collect typed evidence before materializing the public record.

2. **Source priority should become a tiebreaker, not the main resolver.**
   - Entity scope and validation must come before source rank.

3. **Variant rows need offer completeness gates.**
   - Sellable variants should not be emitted as complete if they lack price/currency/availability evidence.

4. **Currency contradictions should not be silently resolved.**
   - Root currency vs variant currency mismatch should create a high-severity finding.

5. **Public schema should stay flat.**
   - Internal evidence graph and entity models should not leak into public product output.

6. **Validators should become first-class.**
   - Current final cleanup has too many silent repairs.

7. **Source trace should become field-level and evidence-backed.**
   - Current `_field_sources` and `_selector_traces` are insufficient.

### 3.2 What Claude's plan gets wrong or under-specifies

#### Correction 1 — LLM detail fallback claim is false

Claude's plan states that LLM field filling is not active on detail surfaces because `apply_direct_record_llm_fallback()` is guarded.

That is incomplete. The current extraction loop still calls `apply_llm_fallback()` for detail records, and that function can call `extract_missing_fields()`.

**Required correction:** Make LLM detail field filling a Phase 0 item.

#### Correction 2 — Thread-local evidence builder should not be used

Claude proposes a thread-local active builder.

This is risky because the backend is async and because candidate insertion is not guaranteed to pass through one function.

**Required correction:** Store the builder on `DetailTierState`, or use `contextvars.ContextVar` only if state threading is impossible. Prefer explicit state over hidden context.

#### Correction 3 — `_add_sourced_candidate()` is not the only candidate path

Some code paths call `add_candidate()` directly, including structured payload candidate collection. Shadow evidence emitted only inside `_add_sourced_candidate()` will miss candidates.

**Required correction:** Create a central candidate emission API that all tier collectors use, or maintain a candidate-to-evidence index map wherever `add_candidate()` is called.

#### Correction 4 — Raw-value scope resolver is unsafe

Claude proposes mapping `raw_value -> entity_scope`.

This will break whenever the same value appears in multiple contexts. Examples:

```text
Black: title, variant color, cross-sell product, breadcrumb
USD: root offer, stale network payload, unrelated recommended product
129.00: parent price, variant price, related product price
InStock: root availability, variant availability
```

**Required correction:** Preserve evidence IDs through candidate insertion and resolution. Never infer scope from the raw value string.

#### Correction 5 — Asset identity phase is over-prioritized

Current image dedupe already uses canonical image URLs. Duplicate image bugs may still exist, but the current code is not as naive as Claude assumes.

**Required correction:** Keep existing image dedupe. Add asset entities only for owner scope, provenance, and optional perceptual/hash identity later.

#### Correction 6 — Offer completeness validator is too naive

Claude's proposed validator checks mostly for missing price. A production validator must distinguish:

```text
complete sellable offer
inherited parent offer with evidence
explicitly unavailable variant
non-commercial option metadata
incomplete sellable variant
ambiguous/review-only variant
```

**Required correction:** Implement variant/offer status classification, not just a price-missing if-statement.

#### Correction 7 — Validators and mutators are mixed

Claude's sample variant validator both creates findings and clamps negative stock.

This violates the plan's own invariant that validators must not silently mutate values.

**Required correction:** Split:

```text
validators -> findings only
normalizers/transforms -> explicit transformations with findings and provenance
resolver -> decides what reaches public output
```

#### Correction 8 — Currency validator must not rely mainly on TLD

TLD hints are weak. The current code already does URL-based currency hints, but that is insufficient.

**Required correction:** Extend browser/network capture and attach request context to price/currency evidence.

#### Correction 9 — Removing intermediate materialization is low priority

Claude correctly identifies two intermediate materializations in `tiers.py`. They are likely CPU waste, but they may affect `completed_tiers` trace behavior.

**Required correction:** Treat this as cleanup after evidence trace is stable, not an early correctness fix.

#### Correction 10 — Existing dangerous repair paths are not addressed enough

Claude's plan underestimates how much existing cleanup/repair code currently mutates price, currency, and variants.

Codex must audit these files before implementing final validators:

```text
app/services/extract/detail/assembly/final_cleanup.py
app/services/extract/detail/price/core.py
app/services/extract/detail/price/money_repair.py
app/services/extract/variant_normalization/backfill.py
app/services/extract/variant_normalization/contract.py
```

---

## 4. Final Recommended Architecture

### 4.1 Target design

The pipeline should become:

```text
URL
  -> acquisition/browser/network/js-state/dom observations
  -> typed evidence nodes
  -> entity linker
  -> validators
  -> resolver
  -> materializer
  -> public flat product record + field trace + review findings
```

Not:

```text
candidates
  -> values[0]
  -> flat record
  -> final cleanup repairs
```

### 4.2 Internal entities

Introduce internal-only models:

```text
FieldEvidence
ValidationFinding
ProductEntity
VariantEntity
OfferEntity
AssetEntity
CandidateRef
RequestContext
ResolutionDecision
```

These should not appear in the public product `data` payload.

### 4.3 Evidence must preserve source and scope

Each evidence node should include at least:

```text
evidence_id
field_name
raw_value
normalized_value
source_type
source_label
source_strength
extraction_tier
entity_ref
entity_scope
candidate_index
json_path / css_path / xpath where available
response_id where available
request_context_id where available
confidence
```

### 4.4 Candidate-to-evidence mapping is mandatory

Do not infer evidence by matching raw value after the fact.

Maintain an index-aligned mapping:

```python
candidates[field][i] -> candidate value
candidate_sources[field][i] -> source label
candidate_evidence[field][i] -> evidence_id
```

Or replace values with an internal envelope:

```python
CandidateEnvelope(
    value=...,
    source=...,
    evidence_id=...,
    entity_ref=...,
)
```

For lower regression risk, use the index-aligned mapping first and keep the existing candidate dict shape.

### 4.5 Resolver rules

For entity-sensitive scalar fields:

```text
price
currency
availability
sku
gtin
mpn
brand
color
size
style
material
image_url
```

Resolution order should be:

1. Entity scope match.
2. Participation in a complete entity set.
3. Validator pass.
4. Source strength.
5. Existing source priority as final tiebreaker.

### 4.6 Variants and offers

Variants should not be considered complete simply because they have axes.

Classify each variant as:

```text
complete_sellable
inherited_parent_offer
explicitly_unavailable
non_commercial_option
incomplete_sellable
ambiguous_review
```

Only `complete_sellable`, carefully validated `inherited_parent_offer`, and `explicitly_unavailable` variants should be emitted without high-severity review findings.

### 4.7 LLM role

Immediate rule:

```text
No LLM field filling on ecommerce_detail.
```

Future safe role:

```text
LLM may classify or adjudicate evidence only.
It must choose from evidence IDs or abstain.
It must not invent field values.
```

Allowed future LLM task shape:

```json
{
  "decision": "choose|reject|abstain",
  "winning_evidence_ids": ["ev_abc"],
  "rejected_evidence_ids": ["ev_def"],
  "reason_code": "cross_sell_not_variant_color",
  "confidence": 0.82
}
```

Disallowed shape:

```json
{
  "price": "129.99",
  "currency": "USD"
}
```

unless those exact values already exist as evidence.

---

## 5. Final Implementation Plan for Codex

Codex should not blindly apply this report. It should first run its own code audit, then produce a patch plan. The phases below are the recommended implementation sequence.

---

### Phase 0 — Verification and Safety Gates

**Goal:** Confirm current code structure and prevent implementation based on stale assumptions.

Codex should run:

```bash
python -m py_compile $(find app -name '*.py')
rg "apply_llm_fallback|apply_direct_record_llm_fallback|extract_missing_fields|review_field_candidates" app
rg "_materialize_record|_ordered_candidates_for_field|finalize_candidate_value|values\[0\]" app/services/extract
rg "dedupe_image_urls|canonical_image_url|dedupe_primary_and_additional_images" app/services/extract
rg "reconcile_detail_currency|_backfill_variant_prices|_enforce_variant_currency|repair_detail_variant" app/services/extract
find . -name 'test_*.py' -o -name '*_test.py'
```

Deliverables:

- `docs/extraction_architecture_current_audit.md`
- `docs/extraction_invariants.md`
- list of all record-mutating price/currency/variant functions
- explicit confirmation of detail LLM fallback call path

Acceptance criteria:

- Codex confirms whether `apply_llm_fallback()` is still called for detail surfaces.
- Codex confirms whether existing image canonical dedupe is active.
- Codex confirms all candidate insertion paths.

---

### Phase 1 — Disable LLM Field Filling on Ecommerce Detail

**Goal:** Prevent unsupported LLM-filled fields from entering detail records.

Modify:

```text
app/services/pipeline/extraction_loop.py
app/services/pipeline/direct_record_fallback.py
```

Required behavior:

- `apply_direct_record_llm_fallback()` remains disabled for detail.
- `apply_llm_fallback()` also returns early for detail surfaces.
- The call site in `extraction_loop.py` should not call `apply_llm_fallback()` for detail surfaces.
- Non-detail LLM fallback may remain, but must not overwrite deterministic fields.

Acceptance tests:

- A detail run with missing fields must not call `extract_missing_fields()`.
- Non-detail fallback still works for zero-candidate missing fields.

---

### Phase 2 — Add Evidence Graph in Shadow Mode

**Goal:** Add evidence without changing output behavior.

Create:

```text
app/services/extract/evidence_graph/models.py
app/services/extract/evidence_graph/builder.py
app/services/extract/evidence_graph/source_ref.py
app/services/extract/evidence_graph/__init__.py
```

Minimum models:

```text
FieldEvidence
ValidationFinding
CandidateRef
ResolutionDecision
```

Implementation guidance:

- Prefer storing builder on `DetailTierState` or passing it explicitly.
- Avoid thread-local. If unavoidable, use `contextvars.ContextVar`, not `threading.local`.
- Add `candidate_evidence` index-aligned with `candidates` and `candidate_sources`.
- Emit evidence from **all** candidate insertion paths, not only `_add_sourced_candidate()`.
- Include source type, extraction tier, and source label at minimum.

Modify:

```text
app/services/extract/detail/assembly/candidate_collection.py
app/services/extract/detail/assembly/tiers.py
app/services/extract/detail/assembly/record_assembly.py
```

Output:

```text
record["_evidence_graph"]
record["_validation_findings"]
record["_candidate_evidence"]
```

These are internal only.

Acceptance tests:

- Every candidate field added through normal detail assembly has at least one evidence node.
- Structured payload candidates are represented.
- DOM candidates are represented.
- Network/adapter/JS-state candidates are represented where available.
- Public product data does not include `_evidence_graph`.

---

### Phase 3 — Add Regression Harness Before Major Resolver Changes

**Goal:** Prevent another cycle of fixes causing new regressions.

Create tests under an appropriate test directory, for example:

```text
tests/extraction/test_detail_evidence_graph.py
tests/extraction/test_detail_llm_guard.py
tests/extraction/test_variant_offer_completeness.py
tests/extraction/test_currency_context.py
tests/extraction/test_image_dedupe.py
tests/extraction/test_entity_scope_resolution.py
```

Minimum synthetic fixtures:

1. Adapter root color `Brown`, JS-state/title/variants `Jet Black`.
2. Variants with only size and no price/currency.
3. Root `USD`, variant `CAD`.
4. US URL with body currency `INR`.
5. Cross-sell product names appearing near variant/color text.
6. Duplicate images differing by CDN params and width params.
7. Negative stock value.
8. Variant size/volume contradiction.
9. Parent price copied to variant without variant evidence.
10. Detail record with missing fields must not call LLM fallback.

Acceptance criteria:

- Tests fail against current behavior where appropriate.
- Future phases must make the relevant tests pass.

---

### Phase 4 — Variant/Offer Entity Linker and DOM Offer Gate

**Goal:** Stop size-only and offer-incomplete variants from being emitted as complete.

Create:

```text
app/services/extract/evidence_graph/entity_linker.py
app/services/extract/validators/variant_offer.py
```

Modify:

```text
app/services/extract/detail/assembly/dom_completion.py
app/services/extract/dom_section_targets.py
app/services/extract/detail/assembly/final_cleanup.py
app/services/extract/variant_identity_merge.py
```

Required behavior:

- Build internal `VariantEntity` and `OfferEntity` from current variant rows plus evidence references.
- Classify variant offer status.
- Update DOM skip logic so “rich existing variants” requires offer completeness, not merely any transport field.
- If sellable variant has axis values but lacks offer evidence, force DOM completion where DOM is available.
- If still incomplete after DOM, attach high-severity validation finding and review bucket entry.

Important:

- Do not delete current `merge_variant_rows()`.
- Reuse it as one input to entity linking.
- Do not blindly inherit parent price into every variant unless evidence supports a single shared offer.

Acceptance tests:

- Size-only variants trigger DOM completion or review finding.
- Explicitly out-of-stock variants are not treated as missing sellable offers.
- Parent price inheritance is marked as inherited, not original variant evidence.

---

### Phase 5 — Request Context for Price/Currency Evidence

**Goal:** Make currency and price decisions context-aware.

Create:

```text
app/services/extract/locale/request_context.py
app/services/extract/validators/price_currency.py
```

Modify:

```text
app/services/acquisition/browser_capture.py
app/services/network_payload_mapper.py
app/services/extract/detail/price/core.py
app/services/extract/detail/assembly/final_cleanup.py
```

Extend network payload capture with:

```text
response_id
request_url
final_url
status
content_type
response_headers_subset
request_headers_subset where safe
body_hash
captured_at
resource_type / frame_url if available
```

Attach `response_id` and `request_context_id` to price/currency evidence.

Required behavior:

- Root currency vs variant currency mismatch creates `CURRENCY_CONTRADICTION` finding.
- URL/TLD hint is only a hint, never final truth.
- No silent overwrite of variant/root currency when evidence contradicts.
- Currency repair functions must either emit transform evidence or be moved behind the resolver.

Acceptance tests:

- Root USD + variants CAD goes to review or preserves explicit contradiction, not silent correction.
- Bombas-style INR on US site creates a context mismatch finding.
- Strong API currency evidence can beat weak DOM currency evidence.

---

### Phase 6 — Entity-Scoped Resolver

**Goal:** Replace source-priority-first scalar resolution for entity-sensitive fields.

Create:

```text
app/services/extract/evidence_graph/resolver.py
app/services/extract/evidence_graph/resolution_rules.py
```

Modify:

```text
app/services/extract/detail/assembly/candidate_collection.py
app/services/extract/field_candidates/finalization.py
```

Do **not** implement raw-value-to-scope lookup. Use candidate evidence IDs.

Resolution inputs:

```text
field_name
candidate values
candidate sources
candidate evidence IDs
evidence graph
entity graph
validation findings
```

Resolution output:

```text
ResolutionDecision
  field_name
  selected_value
  selected_evidence_ids
  rejected_evidence_ids
  resolver_rule
  confidence
  findings
```

Fields requiring entity-aware resolution:

```text
price
currency
availability
sku
gtin
mpn
brand
color
size
style
material
image_url
selected_variant
variants
```

Acceptance tests:

- Wrong high-priority adapter color loses to correctly scoped title/variant evidence.
- Cross-sell color/name evidence is rejected for variant/root color.
- Source priority is used only after scope/completeness/validation are tied.

---

### Phase 7 — Convert Silent Repairs into Explicit Transforms

**Goal:** Stop cleanup from hiding contradictions.

Audit and refactor:

```text
app/services/extract/detail/assembly/final_cleanup.py
app/services/extract/detail/price/core.py
app/services/extract/detail/price/money_repair.py
app/services/extract/variant_normalization/backfill.py
app/services/extract/variant_normalization/contract.py
```

Required behavior:

- Validators create findings only.
- Normalizers/transforms may mutate only when they also record:
  - transform rule
  - before/after value
  - evidence IDs
  - severity if data was questionable
- High-severity validator findings must suppress the affected value or route to review.

Examples:

- Negative stock can be normalized to `0`, but must create `NEGATIVE_STOCK_VALUE` finding.
- Parent price copied into variants must create `INHERITED_PARENT_OFFER_PRICE` transform evidence.
- Currency mismatch must not be silently fixed by URL hint.

Acceptance tests:

- A high-severity currency contradiction is visible in trace/review.
- Parent price propagation is traceable.
- Negative stock mutation is traceable.

---

### Phase 8 — Asset Scope Model, Not Duplicate Dedupe Rewrite

**Goal:** Use assets to prevent image contamination and improve traceability.

Create only if needed after Phase 2 evidence graph:

```text
app/services/extract/assets/asset_identity.py
app/services/extract/validators/assets.py
```

Do not replace:

```text
canonical_image_url()
dedupe_image_urls()
dedupe_primary_and_additional_images()
```

Instead, wrap/extend them to attach:

```text
asset_key
owner_scope: product | variant | description | cross_sell | unknown
source evidence IDs
quality score
duplicate_of
```

Acceptance tests:

- Existing CDN-param image dedupe still works.
- Cross-sell images are not emitted as product gallery images.
- Variant images can be linked to variant entities where evidence supports it.

---

### Phase 9 — Field-Level Provenance and Review Bucket Upgrade

**Goal:** Make every output field explainable.

Modify:

```text
app/services/export/schema.py
app/services/pipeline/persistence.py
app/services/review/* if required
```

Extend `FieldProvenance` with backward-compatible optional fields:

```text
winning_evidence_ids
candidate_count
rejected_candidate_count
conflict_count
validation_finding_ids
resolver_rule
llm_used
```

Review bucket entries should include, at minimum:

```text
rule_id
severity
field_name
entity_ref
evidence_ids
message
suggested_action
```

If the existing `UnverifiedAttribute` schema is too flat, either extend it or encode these fields in a compatible `value` object.

Acceptance tests:

- Source trace includes evidence IDs for selected fields.
- High-severity findings are visible in persisted trace/review output.
- Public product data remains flat and does not leak `_evidence_graph`.

---

### Phase 10 — Cleanup: Intermediate Materialization and Dead Artifacts

**Goal:** Clean up after correctness work is stable.

Modify:

```text
app/services/extract/detail/assembly/tiers.py
```

Remove intermediate `_materialize()` calls only after verifying trace behavior.

Also remove stale `__pycache__` or generated artifacts from source zips/repo if present. These are not runtime source issues, but they can confuse audits.

Acceptance tests:

- Completed tier trace remains meaningful.
- Final output unchanged except trace/performance.

---

## 6. Updated Invariants for Codex

Codex should create or update `docs/extraction_invariants.md` with these rules.

### Rule 1 — Evidence First, Record Last

The extraction pipeline must produce typed evidence before resolving public fields. The public record is materialized after validation and resolution.

### Rule 2 — No Public Value Without Evidence

Every public field emitted by the evidence-backed path must have at least one evidence ID or explicit transform ID. No unsupported inferred value should be emitted.

### Rule 3 — Source Priority Is a Tiebreaker

`SOURCE_PRIORITY` remains useful, but only after entity scope, completeness, and validators have been evaluated.

### Rule 4 — Candidate Index Alignment Must Be Preserved

Candidate values, candidate sources, and candidate evidence IDs must remain index-aligned. Do not infer evidence by raw value matching.

### Rule 5 — LLM Must Not Fill Ecommerce Detail Fields

LLM field filling must not run on ecommerce detail surfaces. Future LLM use must be adjudication over evidence IDs, not generation of unsupported values.

### Rule 6 — Sellable Variants Need Offer Evidence

A sellable variant must link to offer evidence. If not, it should trigger DOM completion, review, or suppression depending on final status.

### Rule 7 — Currency Contradictions Are Never Silent

Root/variant/API/DOM currency mismatches must produce validation findings. URL/TLD hints are hints only.

### Rule 8 — Validators Do Not Mutate

Validators produce findings. Normalizers/transforms may mutate only with explicit trace, before/after values, and evidence.

### Rule 9 — Existing Image Canonical Dedupe Must Be Preserved

Do not replace current image dedupe blindly. Extend it with asset scope and provenance.

### Rule 10 — Public Output Remains Flat

Internal entities and evidence graphs are not part of public product data. Public trace may expose summaries and IDs where safe.

### Rule 11 — Acquisition Produces Observations, Not Truth

Browser/network/acquisition code should capture observations and context. It should not decide final price, currency, variant, or product facts.

### Rule 12 — Review Findings Are First-Class

High-severity findings must either suppress affected values or send the record/entity to review with visible reasons.

---

## 7. Recommended File Map

### Keep Mostly As-Is

```text
app/services/acquisition/*                  # extend capture metadata only
app/services/js_state/*                     # evidence producer, not resolver
app/services/adapters/*                     # evidence producer, not resolver
app/services/public_record_firewall.py
app/services/pipeline/persistence.py        # extend trace/review persistence later
app/services/llm/budget.py
app/services/llm/cache.py
app/services/llm/circuit_breaker.py
app/services/extract/variant_identity_merge.py  # reuse for entity linker
app/services/extract/detail/images/dedupe.py
app/services/extract/dom/image_extraction.py
```

### Refactor Carefully

```text
app/services/pipeline/extraction_loop.py
app/services/pipeline/direct_record_fallback.py
app/services/extract/detail/assembly/candidate_collection.py
app/services/extract/detail/assembly/tiers.py
app/services/extract/detail/assembly/dom_completion.py
app/services/extract/detail/assembly/final_cleanup.py
app/services/extract/field_candidates/finalization.py
app/services/extract/variant_normalization/backfill.py
app/services/extract/variant_normalization/contract.py
app/services/extract/detail/price/core.py
app/services/extract/detail/price/money_repair.py
app/services/extract/detail/images/materialize.py
app/services/network_payload_mapper.py
app/services/export/schema.py
```

### Create New

```text
app/services/extract/evidence_graph/__init__.py
app/services/extract/evidence_graph/models.py
app/services/extract/evidence_graph/builder.py
app/services/extract/evidence_graph/source_ref.py
app/services/extract/evidence_graph/entity_linker.py
app/services/extract/evidence_graph/resolver.py
app/services/extract/evidence_graph/resolution_rules.py
app/services/extract/validators/__init__.py
app/services/extract/validators/variant_offer.py
app/services/extract/validators/price_currency.py
app/services/extract/validators/field_consistency.py
app/services/extract/validators/text_quality.py
app/services/extract/validators/assets.py
app/services/extract/locale/__init__.py
app/services/extract/locale/request_context.py
app/services/extract/assets/__init__.py
app/services/extract/assets/asset_identity.py
```

---

## 8. Minimum Acceptance Criteria for the Whole Refactor

Codex should not consider the work complete until these are true:

1. Ecommerce detail LLM missing-field filling is disabled.
2. Evidence nodes are emitted for all major candidate sources.
3. Candidate values have index-aligned evidence IDs.
4. Variants are classified against offer completeness.
5. DOM skip does not skip sellable variants with missing offers.
6. Root/variant currency contradictions produce findings instead of silent repair.
7. Existing image dedupe still passes duplicate URL/CDN-param cases.
8. Source trace exposes evidence IDs and validation finding IDs.
9. Existing public product schema remains backward-compatible.
10. Regression tests exist for all 30 defect classes or representative synthetic equivalents.
11. High-severity findings route to review or suppress unsafe values.
12. No internal `_evidence_graph` leaks into public `data` output.

---

## 9. Final Recommendation

The current codebase has enough strong components that a full rewrite would be wasteful. The right approach is a controlled internal refactor:

```text
Keep acquisition, adapters, JS-state extraction, network capture, persistence, public firewall, export contract, and LLM infrastructure.

Replace the extraction decision core with:
  evidence graph
  candidate-evidence mapping
  entity linker
  validator stack
  entity-scoped resolver
  traceable transforms
  flat materializer
```

The product goal should be:

> Turn CrawlerAI from a scraper with cleanup logic into an evidence-backed ecommerce data compiler.

This is the architectural shift required to stop recurring site-by-site extraction defects.
