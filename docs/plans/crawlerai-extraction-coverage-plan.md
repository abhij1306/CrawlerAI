# Plan: CrawlerAI Source-Backed Extraction Coverage

**Created:** 2026-08-25
**Agent:** Codex
**Status:** QUEUED
**Branch:** `codex/crawlerai-extraction-coverage`
**Base:** updated `main` after the data-accuracy PR merges
**Touches buckets:** commerce public contracts, field mappings, deterministic collectors, variants, product identifiers, attributes, ratings/reviews, publication, diagnostics, focused tests

## Goal

Recover deterministic, source-backed fields that the recent 82-case run missed. This PR owns the remaining 118 observed defects: variants/options, product identifiers, secondary attributes, and ratings/reviews. It extends existing owners in place and preserves every accuracy, product-boundary, selected-state, lineage, and performance guarantee from the preceding data-accuracy PR.

## Preconditions and Owned Baseline

- The data-accuracy PR is merged and its full reference replay is the baseline.
- Canonical inputs are `backend/app/evaluation/reference/crawlerai_eval_compact.json`, `backend/app/evaluation/reference/crawlerai_defects_compact.json`, and matching ignored captures.

Owned defect partitions:

| Area | Defects | Cases | Case IDs |
| --- | ---: | ---: | --- |
| `variants_and_options` | 3 | 3 | 22, 26, 34 |
| `product_identifiers` | 17 | 17 | 1, 2, 4, 5, 12, 21, 22, 28, 55, 56, 61, 66, 67, 71, 75, 79, 81 |
| `attributes` | 79 | 50 | reference defect file is authoritative |
| `reviews` | 19 | 10 | 16, 25, 32, 42, 51, 70, 74, 78, 79, 81 |

## Public Projection Contract

- Add explicit product-level fields only where the reference data requires them: `product_id`, `style_id`, `asin`, `color`, `gender`, `size`, `condition`, `materials`, `rating`, and `review_count`.
- Keep `sku` as the product-level merchant SKU. Variant SKUs/IDs stay in variants.
- Map reference `material` to public `materials`.
- Treat `size_options` and `model_options` as variant assertions, not top-level public fields.
- Treat `product_family` as an evaluation semantic, not a new public boolean.
- Treat `selected_fit` as selected-state evidence and publish it only through a configured public variant axis.
- Keep special serialization for variants/assets/price bounds. Do not add a second commerce-field registry or compatibility map.

## Acceptance Criteria

- [ ] Existing field-mapping config is the single source for direct public field-to-fact wiring. `CommerceDetailRecord`, field states, diagnosis, publication, persistence/export views, and tests agree on the new explicit fields.
- [ ] A scoped consistency test proves every new direct public field has canonical-surface, fact, normalization, and publication wiring; special serializers remain explicit.
- [ ] All 17 product-identifier defects pass from product-level evidence. DTLR publishes `HQ7978-103`, not Shopify variant ID `45993954607338`. ASIN, style ID, product ID, and SKU remain semantically distinct.
- [ ] All three variant/option defects pass: Puma case 22 exposes captured sizes, Fashion Nova case 26 preserves eight coming-soon size variants, and Apple case 34 publishes two model rows with correct USD prices.
- [ ] `variant_count == len(variants)` and every row is a same-product sellable configuration. No blind Cartesian products, sibling PDPs, UI/navigation controls, duplicate desktop/mobile controls, or generic parent rows.
- [ ] All 79 attribute defects pass where the capture contains admissible evidence. Color, material, gender, size, condition, and selected options remain product/variant scoped and normalized through existing config owners.
- [ ] All 19 review defects pass where supported. Ratings require a known/standard 0–5 scale; review counts are nonnegative integers. Ambiguous scales/widgets are suppressed with diagnostics.
- [ ] Missing capture evidence remains `capture_limited`; the PR does not add browser interaction, site-specific fetching, or fabricated values to chase counts.
- [ ] Every public value has selected or derived lineage and a field state. New breadth cannot affect product identity, offer validity, or variant eligibility unless that field is the owning semantic input.
- [ ] All 47 PR 1 defects and all previously passing reference fields remain passing.
- [ ] Three warm full-replay runs keep extraction p95 within 20% of the PR 2 baseline unless the owner approves a measured exception.
- [ ] `.\scripts\check.ps1` and `.\scripts\test.ps1` pass once after implementation is complete.

## Do Not Touch

- `frontend/**`, endpoints, database schema, listing, jobs, automobiles, downstream value repair, enrichment cleanup, or LLM value generation. Existing persistence/export projections may change only to carry the owned extraction fields without recomputing them.
- Acquisition/browser/traversal and option clicking. Report absent source artifacts; do not expand capture scope inside this PR.
- Site-specific branches in generic extraction, a generic metadata blob collector, parallel eval runners, scheduled replay, or CI corpus gates.
- PR 1 targeting, selected-state, title/brand, and commercial rules except to fix a directly reproduced regression without weakening their tests.

## Slices

### Slice 1: Complete Public Field Wiring

**Status:** TODO
**Files:** `backend/app/core/config/field_mappings.py`, `backend/app/extraction/contracts.py`, `backend/app/extraction/publication.py`, field-state/diagnosis/public-view owners, focused tests
**What:** Add the explicit fields in the Public Projection Contract to existing mappings and typed records. Consolidate only real duplicate direct maps. Define types: rating numeric 0–5, review count nonnegative integer, other new product attributes bounded strings. Keep price bounds/assets/variants on existing paths.
**Verify:** Focused field-policy, contract, normalization, publication, field-state, diagnosis, persistence/export view, and architecture tests.

### Slice 2: Recover Product Identifiers

**Status:** TODO
**Files:** existing JSON-LD, JS-state/network, product-root DOM-label, admission, entity-binding, resolution, focused tests
**What:** Emit product identifiers only from same-product structured state, supported structured data, first-party payloads, or explicit product-root labels. Keep internal entity IDs and variant identifiers separate. Do not infer an identifier from arbitrary URL text unless a generic platform contract proves the URL segment's meaning.
**Verify:** Focused identifier/collector/binding/publication tests plus all 17 identifier cases.

### Slice 3: Recover Variants and Options

**Status:** TODO
**Files:** existing JS-state/network/DOM variant collectors, entity assembly, resolution, validation, publication, focused tests
**What:** First reproduce each miss and check documented historical failure modes at current HEAD. Preserve structured matrices and selected-state relationships. Allow one-axis DOM controls only when each is purchasable with option-level evidence. Require an explicit source matrix/relationship for multiple axes. Preserve stable IDs, SKU, barcode, option tuple, price, currency, availability, URL, and lineage.
**Verify:** Focused state/network/DOM, entity, variant resolution, validation, publication tests plus cases 22, 26, and 34 and all existing correct variant cases.

### Slice 4: Recover Product Attributes

**Status:** TODO
**Files:** existing structured collectors, requested product-root DOM sections, normalization/config, resolution, publication, focused tests
**What:** Recover color, gender, size, condition, and materials from product/selected-variant evidence. Reject navigation, size guides, reviews, recommendations, unrelated tables, and unrestricted blobs. Reuse current product-root section scoping; do not add a generic metadata layer.
**Verify:** Focused collector, normalization, scope, field-state, publication tests plus the 50-case attribute partition.

### Slice 5: Recover Ratings and Reviews

**Status:** TODO
**Files:** existing JSON-LD/state/network collectors, rating/review normalization and validation, publication, focused tests
**What:** Prefer same-product AggregateRating/first-party state. Accept 0–5 ratings only when scale is explicit or standard. Reject rating widgets tied to recommendations/other products and invalid review counts.
**Verify:** Focused rating/review collector, normalization, validation, diagnosis, publication tests plus the 10-case review partition.

### Slice 6: Close PR 2 and Program

**Status:** TODO
**Files:** `docs/audits/crawlerai-extraction-coverage-report.md`, this plan, `docs/backend-architecture.md`, `docs/BUSINESS_LOGIC.md` if public semantics changed, `docs/plans/ACTIVE.md`
**What:** Record all 118 owned defects before/after, capture-limited cases, preserved PR 1 behavior, field coverage, and timing. Run repository gates once. Mark this plan done and advance `ACTIVE.md` only after merge.
**Verify:** Full 82-case manual replay requested by the implementation assignment; `.\scripts\check.ps1`; `.\scripts\test.ps1`; `git diff --check`; checklist complete.

## Doc Updates Required

- [ ] `docs/audits/crawlerai-extraction-coverage-report.md` — before/after evidence.
- [ ] `docs/backend-architecture.md` — new explicit commerce-detail fields and existing owners.
- [ ] `docs/BUSINESS_LOGIC.md` — public output semantics for new fields.
- [ ] `docs/CODEBASE_MAP.md` — only if ownership/files move; not expected.
- [ ] `docs/INVARIANTS.md` — only for a newly discovered durable contract/anti-pattern; not expected.

## Notes

- This plan replaces the extraction-coverage half of the former combined 63-case plan.
- Reference coverage is a correctness target only for independently supported fields. It is not a mandate to maximize populated values.
- Accuracy wins over fabricated coverage. Missing is acceptable when source evidence is absent or ambiguous.
