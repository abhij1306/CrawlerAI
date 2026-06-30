# Extraction Ownership and Accuracy Plan

**Created:** 2026-06-30
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Extraction, Publish + Persistence, Observability, Frontend diagnostics

## Goal

Replace distributed semantic ownership with a three-stage pipeline:

```text
CaptureBundle
  → Harvest
      Evidence[]
      explicit source relations
      collector/budget outcomes
  → Resolve
      target + ownership
      EvidenceDisposition[]
      SelectedFact[]
      DerivedFact[]
      Findings[]
      surface-specific PublicationProjection
  → Publish
      deterministic serialization
      field-specific canonicalization
      schema validation
      projection comparison
        match      → canonical records
        divergence → invalid + diagnostics only
```

Migrate ecommerce detail first. Use the local-only 90-site captures as partitioned debugging datasets. Never add captures, corpus manifests, hashes, baselines, or derived corpus outputs to Git. Delete the legacy path only after every local dataset passes. Then migrate ecommerce listing, job detail, and job listing. LLM remains deferred. Unrelated CodeRabbit work stays outside this plan.

## Acceptance Criteria

- [ ] Every harvested Evidence has exactly one terminal EvidenceDisposition.
- [ ] Publication divergence is zero across every local corpus dataset.
- [ ] Published values without lineage are zero.
- [ ] Cross-product assets, offers, and variants are zero.
- [ ] Captured valid prices, currencies, and explicit variants are never lost after Resolve.
- [ ] Clean baseline cases regress by zero.
- [ ] Local dataset replay skips are zero for the dataset being used as a cutover gate.
- [ ] p95 evidence count is at most 125% of baseline.
- [ ] p95 Resolve duration is at most 120% of baseline.
- [ ] p95 diagnose size is at most 125% of baseline and every diagnose artifact is at most 1 MiB.
- [ ] All backend tests, ruff, extraction smoke, acquisition smoke, and acceptance commands pass.

## Interfaces and Contracts

### Common interfaces

Four surface adapters implement:

- `harvest(request) -> HarvestResult`
- `resolve(request, harvest) -> ResolutionEnvelope`
- `publish(resolution) -> PublicationResult`

After migration, SurfaceRuntime exposes only these calls. Commerce and job domain models remain surface-specific.

### HarvestResult

HarvestResult contains immutable Evidence, explicit source-object/source-relation metadata, collector outcomes, syntactic-filter counts, and budget outcomes.

Harvest performs syntactic admission only. It may reject analytics, navigation, translation, feature-flag, UI-config, unrelated schema, and budget-overflow objects. It must not reject a commerce candidate because semantic ownership is unknown.

Config-owned limits:

- `MAX_SOURCE_OBJECTS_PER_ARTIFACT = 20_000`
- `MAX_EVIDENCE_PER_SOURCE_OBJECT = 64`
- `MAX_UNOWNED_PRODUCT_ROOTS = 256`
- `MAX_DIAGNOSTIC_EXAMPLES_PER_REASON = 10`
- Existing embedded-state node/depth/list limits remain.
- Maximum persisted diagnose size is 1 MiB.

Budget hits emit bounded collector outcomes with counts and reasons. No silent truncation.

### ResolutionEnvelope

```python
class ResolutionEnvelope:
    surface: Surface
    target: TargetSelection
    decisions: tuple[Decision, ...]
    selected_facts: tuple[SelectedFact, ...]
    derived_facts: tuple[DerivedFact, ...]
    evidence_dispositions: tuple[EvidenceDisposition, ...]
    findings: tuple[Finding, ...]
    field_states: tuple[FieldEvidenceState, ...]
    publication: PublicationProjection
```

PublicationProjection is a discriminated union of CommerceDetailProjection, CommerceListingProjection, JobDetailProjection, and JobListingProjection.

SelectedFact is resolved direct truth and must equal the canonical value of accepted evidence. Multi-value aggregation, inference, inheritance, and reconciliation produce DerivedFact instead.

DerivedFact references input selected/derived fact IDs and leaf evidence IDs.

### Evidence conservation

Every harvested Evidence has one terminal status: accepted, rejected_invalid, rejected_lower_rank, conflicted, unowned, outside_selected_target, duplicate, or diagnostic_only. Each disposition contains evidence ID, optional entity ID, reason code, and selected/derived/decision reference where applicable.

Raw source objects rejected before Evidence creation are summarized in collector outcomes.

### Resolved truth and publication policy

Resolved truth stays resolved when publication suppresses it. Atomic publication entries carry entity and parent identity, public field path, authorized value, publish/suppress/review disposition, reason, one SelectedFact or DerivedFact reference, and optional canonicalization trace.

Atomic paths include record fields, variant fields, and asset URL/role/position. Entity-level entries authorize variant eligibility, asset inclusion, primary role, optional asset sequence, and record eligibility.

### URL canonicalization

URL canonicalization is field-specific and versioned. Projection entries retain raw URL, canonical URL, canonicalizer ID, and canonicalizer version.

- Product URLs remove only configured tracking parameters.
- Variant URLs retain product/variant identity parameters.
- Image URLs retain required delivery parameters.
- Asset identity is separate from delivery URL.

### Comparison semantics

- Scalars compare after registered field canonicalization.
- Variants compare by stable entity-ID set, not list position.
- Variant fields compare by entity ID and atomic path.
- Primary asset identity/role must match.
- Additional assets compare as identity sets unless Resolve explicitly authorizes sequence order.

### Contract safety

Contracts apply after target selection, ownership, and admissibility, but before final ranking. They may select only eligible evidence for the selected entity. They cannot create ownership, move evidence, resurrect rejected evidence, or select unowned evidence.

## Slices

### Slice 1: Baseline, Contracts, and Diagnostic Comparator
**Status:** CODE LANDED; LOCAL CORPUS BASELINE PENDING

- Record commit, dirty-tree fingerprint, test/config versions, and corpus hashes in ignored local output only.
- Restore the focused suite to green.
- Map the 90 local capture bundles without copying them into tracked paths. Stop cutover work if required local bundles are unavailable.
- Partition local captures into clean controls, ownership/identity, offer price/currency, availability, variants, assets, brand/title, and redirect/source-limited datasets. A URL may belong to multiple issue datasets.
- Store baseline records, decisions, findings, field classifications, evidence counts, timings, and diagnose sizes under ignored `backend/artifacts/` only.
- Use `backend/run_local_extraction_corpus.py --manifest <ignored manifest> --dataset <partition>` for partitioned local replay. The script fails on skipped captures, publication divergence, or incomplete evidence accounting and writes only under ignored artifacts by default.
- Add ResolutionEnvelope, SelectedFact, EvidenceDisposition, surface-specific projections, and versioned canonicalization traces.
- Add a diagnostic-only ecommerce-detail projection comparator.
- Add temporary shadow output: legacy record, authorized projection, serialized candidate, and semantic diff. Expose only legacy output.
- Add Resolve and Publish duration metrics.
- Confirm no database migration is required.

**Verify:** Existing suite and contract tests pass. Each selected local dataset replays with zero skipped cases. No corpus-derived file appears in `git status`.

### Slice 2: Bounded Harvest and Ecommerce Ownership
**Status:** CODE LANDED; LOCAL CORPUS OWNERSHIP GATE PENDING

- Harvest bounded, structurally relevant commerce candidates.
- Preserve source identity and explicit relations; stop page-product ownership stamping.
- Aggregate unowned findings by root with bounded examples.
- Resolve roots using URL, product ID, SKU/MPN/GTIN, explicit relations, and unique title identity.
- Keep unresolved/ambiguous candidates unowned.
- Replace one DOM root with identity, commerce, asset, and supplementary product-region resolution.
- Attach regions only through explicit relation, exact identity, non-conflicting component identity, or corroborated proximity.
- Populate one EvidenceDisposition per Evidence.

**Verify:** Cache, recommendation, sibling, responsive duplicate, sticky, portal, and ambiguous-root tests pass; evidence accounting is 100%.

### Slice 3: Representation-Only Canonicalization
**Status:** CODE LANDED; LOCAL REGRESSION GATE PENDING

- Preserve raw values; canonicalization cannot add evidence, change fact type, assign ownership, rank, or infer.
- Move brand/SKU/currency/availability inference, conflict classification, ambiguous price logic, unit correction, and offer inheritance into Resolve.
- Emit SelectedFact, DerivedFact, or explicit rejection for every operation.
- Add architecture tests for evidence identity/shape preservation.

**Verify:** Canonicalization property, provenance, and detail regression tests pass.

### Slice 4: Final Ecommerce-Detail Resolve and Blocking Comparator
**Status:** CODE LANDED; LOCAL CORPUS DIVERGENCE GATE PENDING

- Resolve all target, ownership, ranking, atomic offer, parent aggregation, variant, asset, and publication decisions.
- Preserve resolved truth when public policy suppresses a field.
- Remove semantic behavior from materialization, output safety, and the firewall.
- Publish only CommerceDetailProjection; do not pass Evidence or EntitySet.
- Make the candidate comparator blocking for every scalar, variant, asset, suppression, review, and lineage mismatch.
- Emit critical PUBLIC_RESOLUTION_DIVERGENCE and zero candidate records on mismatch.

**Verify:** Scalar, suppression, variant, asset, range, identity, ordering, and deliberate divergence tests pass.

### Slice 5: Partitioned Local-Corpus Acceptance and Ecommerce Cutover
**Status:** LOCAL-ONLY GATE PENDING

- Classify every requested field as not_captured, captured_published, captured_suppressed, captured_conflicting, captured_unowned, not_present_in_source, source_unavailable, or not_requested.
- Enforce accuracy and performance acceptance criteria.
- Cut over only when all gates pass.
- Delete legacy ecommerce publication and shadow code; add absence tests.
- Keep divergent output diagnostic-only with zero canonical records.

**Verify:** Every local dataset and all release targets pass. `git status` contains no corpus-derived files.

### Slice 6: Migrate Remaining Surfaces
**Status:** CODE LANDED; SURFACE-SPECIFIC ACCEPTANCE PENDING

- Migrate ecommerce listing, job detail, then job listing.
- Keep partial cards as evidence and reject with reasons in Resolve.
- Resolve competing JobPosting roots fail-closed.
- Add per-entity field states and blocking comparator per surface.
- Reduce SurfaceRuntime to Harvest, Resolve, Publish.
- Delete duplicate ranking/materialization and transitional wrappers.

**Verify:** Each adapter passes focused tests; shared unit/component suite passes after all four migrate.

### Slice 7: Recall Closure
**Status:** PARTIAL; LOCAL DATASET DEBUGGING PENDING

- Complete generic GTIN, MPN, seller, category, availability, and camelCase currency mappings.
- Collapse responsive pictures by region and asset identity.
- Preserve dot, bracket, and slash source paths.
- Add generated source-map property tests and disposition assertions.
- Keep corpus/site literals out of production rules.

**Verify:** Recall properties, genericness ratchets, and replay fixtures pass.

### Slice 8: Consumers, Ratchets, Deletion, and Docs
**Status:** CODE LANDED; FULL VERIFICATION PENDING

- Update extraction.v2, diagnose.v2, divergent integrity, disposition summaries, per-entity states, reporting, frontend types, exports, and metrics.
- Reconfirm no database schema migration is required.
- Add a machine-readable semantic-surface manifest.
- Ratchet one derivation owner, one variant owner, one asset owner, zero post-resolution mutation, zero evidence loss, contract ownership safety, projection-only Publish, and repair-free persistence.
- Report baseline/final LOC as secondary evidence; do not enforce density-driven hard reduction.
- Delete obsolete owners and update canonical docs.

**Verify:** Full backend, frontend, smoke, acceptance, architecture, and documentation checks pass.

## Final Verification

```powershell
cd backend
$env:PYTHONPATH='.'
.\.venv\Scripts\python.exe run_local_extraction_corpus.py --manifest <ignored-local-manifest> --dataset <partition>
.\.venv\Scripts\python.exe -m pytest tests -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe run_acquire_smoke.py commerce
.\.venv\Scripts\python.exe run_extraction_smoke.py
.\.venv\Scripts\python.exe run_test_sites_acceptance.py
```

Run frontend type, policy, and test commands after diagnostic contract changes.

## Assumptions

- Exactly four surfaces exist: ecommerce listing/detail and job listing/detail.
- Tables are artifacts, not a surface.
- Guarantees cover captured artifacts and recognized shapes, not unknown markup.
- Old local artifacts remain immutable and ignored. New runs use v2 contracts.
- Divergent records never enter canonical persistence or clean exports.
- LLM remains deferred and llm_proposed remains inert.
- No retailer-specific or corpus-tuned production rules.
- Preserve current user changes. Replace weak divergence wiring only when the stronger mechanism lands.
- No production cutover while any required local dataset is missing, skipped, divergent, or outside acceptance limits.
- Corpus captures, URL manifests, hashes, baselines, and derived dataset outputs must never be committed or pushed.
