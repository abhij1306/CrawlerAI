# Plan: Shopify Linked Variant Family Extraction

**Created:** 2026-05-18
**Agent:** Codex
**Status:** IN PROGRESS
**Touches buckets:** Bucket 4 Extraction, config, tests

## Goal

Make Shopify detail extraction treat visible same-product linked PDPs as variant-family members, not unrelated products. Done means Shopify PDPs with variants split across separate URLs emit flat public variant rows with `color`/`size`/`scent`, SKU, URL, image, availability, and stock when public evidence exists. Gymshark remains correct. Fashion Nova includes the Blush linked color. Fenty body mist emits scent variants instead of wrong color/no variants. Allbirds linked color/gender pages no longer collapse to selected-size-only rows.

## Acceptance Criteria

- [ ] Gymshark artifact `backend/artifacts/runs/2/pages/876ac4c7516038f9.html` still extracts 14 variants with `Black` and `White`, size, SKU, URL, image, availability, and stock.
- [ ] Fashion Nova artifact `backend/artifacts/runs/3/pages/1ef8d8636bcfced4.html` extracts both `Black` and `Blush` family variants from the swatch-linked Shopify PDPs, not only the selected black sizes.
- [ ] Fenty artifact `backend/artifacts/runs/4/pages/9da4a0e6ee49da8e.html` extracts the body-mist scent family links (`Green Raspberry`, `Hey, Bouquet`, `Tropic Trip`, `Vanilla Flowers`) as public variants, with selected scent not coerced to wrong `color`.
- [ ] Allbirds artifact `backend/artifacts/runs/1/pages/00d4b6e0eea56f28.html` includes same-family linked PDP variants when exposed.
- [ ] Variant output remains flat public contract only: no `selected_variant`, `variant_axes`, nested option containers, or private helper fields persisted/exported.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests/services/test_state_mappers.py tests/services/test_detail_extractor_structured_sources.py -q` exits 0.
- [ ] `cd backend; $env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -q` exits 0 before closing plan.

## Do Not Touch

- `backend/app/services/pipeline/persistence.py` — downstream compensation forbidden.
- `backend/app/services/publish/*` — variant quality is extraction-owned.
- Frontend files — output contract only; UI not part of bug.
- LLM services — Shopify variant extraction must stay deterministic.
- Browser click traversal — no Playwright variant clicking unless deterministic HTML/JS/API evidence fails after this plan.

## Slices

### Slice 1: Artifact Regression Harness
**Status:** DONE
**Files:** `backend/tests/services/test_detail_extractor_structured_sources.py`, `backend/tests/services/test_state_mappers.py`
**What:** Add focused artifact/fixture regressions for the four observed crawls. Keep Gymshark as passing reference. Add expected failures for Fashion Nova linked Blush, Fenty scent variants, and Allbirds linked rows. Prefer small distilled fixtures when full artifact tests are too slow; keep one smoke assertion against saved artifact HTML for each site.
**Verify:** Targeted tests fail only on the known Shopify variant gaps.

### Slice 2: Same-Family Linked PDP Discovery
**Status:** DONE
**Files:** `backend/app/services/extract/detail/variants/dom_extraction.py`, `backend/app/services/extract/variant_choice_traversal.py`, `backend/app/services/config/extraction_rules.py`, `backend/app/services/config/variant_migration_rules.py`
**What:** Strengthen DOM variant group discovery for linked Shopify/Hydrogen swatches. Admit anchor-hidden swatches like Fashion Nova, image/button swatches like Fenty, and Allbirds linked color/gender cues only when they sit inside validated product option groups. Reject nav/recommendation links.
**Verify:** DOM extraction returns validated linked variant rows with URL plus axis value for Fashion Nova and Fenty fixtures.

### Slice 3: Shopify Family Expansion From Linked Handles
**Status:** DONE
**Files:** `backend/app/services/adapters/shopify.py`, `backend/app/services/config/adapter_runtime_settings.py`, `backend/app/services/extract/variant_identity_merge.py`
**What:** Add bounded Shopify linked-handle expansion for detail pages. From validated sibling PDP URLs, fetch each `/products/<handle>.js`, normalize rows through existing Shopify variant normalization, merge with current record variants, and dedupe by variant id/SKU/semantic axes. Add env-backed caps/timeouts in existing adapter config. No generic pipeline branch.
**Verify:** Distilled Shopify fixtures produce cross-handle matrices: Fashion Nova `Black` + `Blush`, Allbirds multiple colors/sizes.

### Slice 4: Axis Label Repair
**Status:** DONE
**Files:** `backend/app/services/extract/variant_axis.py`, `backend/app/services/extract/detail/variants/dom_coercion.py`, `backend/app/services/js_state/state_normalizer.py`, `backend/app/services/config/variant_policy.py`
**What:** Prefer explicit UI/source axis labels over generic `shade -> color` fallback. Use `scent` when the group/source labels say scent/fragrance/body mist.
**Verify:** Fenty body mist variants use `scent`.

### Slice 5: Candidate Merge And Public Firewall
**Status:** DONE
**Files:** `backend/app/services/extract/field_candidates/finalization.py`, `backend/app/services/extract/variant_normalization/*`, `backend/app/services/public_record_firewall.py`
**What:** Ensure structured, JS-state, DOM, and Shopify-adapter variant candidates merge without losing richer rows. Preserve Gymshark stock/availability. Strip internal fields after merge.
**Verify:** All four artifact regressions pass; public rows contain only allowed flat keys.

### Slice 6: Broad Verification And Docs
**Status:** BLOCKED
**Files:** `docs/INVARIANTS.md`, `docs/backend-architecture.md`, maybe `docs/CODEBASE_MAP.md`
**What:** Update docs only if owner/contract changes. Record Shopify linked-PDP variant extraction as upstream extraction behavior. Run targeted and broad backend verification.
**Verify:** Targeted tests, `pytest tests -q`, and `run_extraction_smoke.py` pass.

**Blocker:** `pytest tests -q` still has unrelated failures outside the Shopify plan (`test_health_api`, `test_structure` private-import drift, and UCP markdown escaping). Shopify-required suites pass.

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — document Shopify linked-PDP variant family flow if implemented.
- [ ] `docs/INVARIANTS.md` — update only if public variant contract changes; expected no contract change.
- [ ] `docs/CODEBASE_MAP.md` — update only if a new file is added; expected no new file.
- [ ] `docs/ENGINEERING_STRATEGY.md` — update only if a new anti-pattern is discovered; expected no change.

## Notes

- Active plan before this was UCP Compliance Audit, status COMPLETE.
- Artifact review:
  - Allbirds run 1: full extractor returns selected-size variants only. HTML contains linked PDPs for same-family color/gender options.
  - Gymshark run 2: full extractor returns 14 variants across `Black` and `White`, with stock/availability. This is the reference behavior to preserve.
  - Fashion Nova run 3: full extractor returns 6 black size rows only. HTML contains validated-looking swatch evidence for `/products/ballpark-tassel-suede-sneakers-blush` with `aria-label="Blush"` and title `View alternate product color Blush`.
  - Fenty run 4: full extractor returns no variants. HTML contains JSON-LD offers and linked body-mist PDPs for `allover-body-mist-green-raspberry`, `hey-bouquet`, `tropic-trip`, and `vanilla-flowers`; selected product has `shade`, `shade_handle`, `shadeCount`, and `micro_collection_handle`.
- Existing code already has Gymshark JS-state sibling merge tests. Extend that path; do not create a parallel Shopify variant system.
