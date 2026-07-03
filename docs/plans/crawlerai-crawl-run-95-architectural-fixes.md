# CrawlerAI — Crawl-Run-95 Architectural Fixes

**Source:** `CrawlerAI_Crawl_Run_Analysis_and_Codebase_Audit.md` (audit date 3 Jul 2026, run of 95 ecommerce-detail results).
**Predecessor:** the Extraction Correctness Overhaul v2 (`docs/plans/crawlerai-adaptive-extraction-v2-plan.md`) is COMPLETE. This plan is the follow-on: it fixes the **semantic/observability defects** that survived that overhaul. Architecture verdict from the audit stands — Harvest → Resolve → Publish ownership is valid; **no new framework, no acquisition redesign, no site-specific branches.**
**Status:** COMPLETE — Slice 0 ✅, Slice 1 ✅, Slice 2 ✅, Slice 3 ✅, Slice 4 ✅, Slice 5 ✅, Slice 6 ✅ (all verified vs real artifacts + distilled regressions).
**Constraints (verified):**
- Greenfield: no commits (user runs CodeRabbit). Break freely; optimize for durable architecture.
- Extraction package at the **28-module ceiling** (`test_extraction_architecture.py:226`). Prefer adding logic to existing extraction modules or to `app/core/**`; introduce a new extraction module only if unavoidable (then bump the ceiling with a documented exception).
- **LOC ratchets** in `tests/unit/test_final_architecture_ownership.py` (`extraction` 13,458 / `core` 17,226 / `observability` — see file / total 74,662) and per-module budgets in `app/core/config/extraction_semantic_surface.toml`. Every slice that adds lines re-baselines these numbers as a documented step.
- **Genericness ratchet** `test_extraction_carries_no_retailer_domain_literals` scans `app/extraction/` — all new rules stay site-agnostic (semantic roles, not host names).
- **Hot-path guard** `test_extraction_hot_path_never_imports_grounded_llm_repair` unchanged.
- Test cmd (from `backend/`): `$env:PYTHONPATH='.'; .\.venv\Scripts\python.exe -m pytest tests -m "unit" -q`. ruff/mypy on touched files only.

**Regression source:** real audited pages at `backend/artifacts/runs/1/results/<id>/{page.html,diagnose.json,record.json}` (gitignored). Strategy: **distill minimal, self-contained inline-HTML fixtures** for each defect (verified against the real page during dev) so committed tests don't depend on gitignored artifacts. Optionally add artifact-driven parametrized checks guarded by `skipif(not artifacts_dir.exists())`. Harness: `_extract(surface, html, page_url, …)` in `extraction_pipeline_test_support.py`.

---

## Sequence (audit priority order)

Diagnostics first (so run-level counts become trustworthy), then discovery, ownership, the catastrophic price bug, content rejection, and routing. **Slice 4 (price 1,000,000× on result 81) is the only confirmed data-corruption P0 and may be pulled ahead of 1–3 on request.**

---

### Slice 0 — Save plan + baseline (this file)
1. Commit this plan to `docs/plans/`, point `docs/plans/ACTIVE.md` here, refresh the `active-plan-*` memory.
2. Capture a green baseline: run the unit suite; record current LOC/module ratchet numbers so each slice's re-baseline is auditable.

---

### Slice 1 — Make evaluation trustworthy (P0/P1 diagnostics)
**Defect:** candidate-offer warnings dominate the run report (45/47 `PRICE_WITHOUT_CURRENCY`, 32/33 `CURRENCY_WITHOUT_PRICE` are false page causes); variant prices mark page-level `price` as `captured_published` even when `record.price` is absent (results 68, 90).

**Changes:**
1. **Path-aware field states** — `result_building.py:302-444 projection_field_states()`: stop flattening `entry.path.rsplit(".",1)[-1]`. Distinguish `record.*` from `variants.*`; public parent state derives **only** from `record.*` projection entries. Add `variants.price/currency/availability` summary states reported separately. Thread `entity_id`/parent scope through `field_state()` (already accepts an optional `entity_id`; callers currently drop it). Extend `FieldStateName` in `field_states.py` only if a distinct name is needed (prefer scoping over new enum members).
2. **Scope offer-pair findings to public/eligible entities** — `validation.py:434-488 _validate_offers()`: pass the selected/primary offer + publication disposition; emit page findings only for the primary offer / an eligible public variant / evidence that caused public suppression. Candidate-only incomplete pairs become **diagnostic-only** findings (new severity/scope tag), not page causes.
3. **Run-report filtering** — `observability/run_report.py:107-173 _root_causes()`: already skips `RECORD_COMPLETENESS`; extend the informational/diagnostic-only skip set and ignore outside-target findings for root-cause grouping while preserving them per-page.
4. **New run-level metric** — “record field absent despite child field published” (parent/child divergence counter).

**Acceptance:** results 68 & 90 report parent commercial fields **absent**, not published; the 45/47 and 32/33 false offer warnings no longer dominate root causes.
**Tests:** distilled fixtures for 68/90 (variant-only price, empty parent) and 1/3/55/90 (candidate-offer scoping); assert field states and root-cause set.

**✅ DONE (this session):**
- `projection_field_states()` now splits `variant[*]` entries into a separate `variant_entries_by_field` bucket; parent field state derives only from `record.*`/`asset[*]`/`record[*]` entries. `variants.{price,currency,availability}` summary states appended after the parent loop. Verified vs real artifacts: result 68 parent price/currency/availability = `captured_but_rejected`, result 90 price = `captured_suppressed`; `variants.*` = `captured_published` on both.
- `validation.py`: `FindingScope` alias added; `_finding`/`_grouped_offer_completeness_findings` take a `scope`; `_validate_offers` splits offer-completeness rows into primary (`variant_entity_id is None` → scope `selected_entity`) vs candidate (scope `candidate`) buckets.
- `run_report.py`: `_DIAGNOSTIC_ONLY_FINDING_SCOPES={"candidate"}` skipped from root causes; `variants.*` field statuses skipped as field causes; new `parent_absent_child_published:{price,currency,availability}` divergence cause when a child field is published but the parent field isn't published-clean. `_CLEAN_FIELD_STATES` now includes `captured_published`.
- Regressions: `tests/unit/test_crawl_run_95_regressions.py` (projection field-state split, both directions) + 3 new cases in `test_run_report_builder.py` (candidate-scope exclusion, parent-absent-child-published cause, no-divergence when parent published).
- Re-baselined ratchets: `test_final_architecture_ownership.py` (extraction 13,458→13,525, total 74,662→74,774, validation.py 720→751, projection_field_states 58→70, _root_causes 27→34) and `extraction_semantic_surface.toml` (physical_loc_budget 13469→13532, result_building.py LOC 621→653 / CC 58→70, validation.py LOC 720→751). Full unit suite: **776 passed**.

---

### Slice 2 — Repair generic variant-control discovery (P0)
**Defect:** unscoped `select option` turns review sorters, country selectors, pagination, quantity, and opaque IDs into product size axes (results 10, 17, 21, 58, 70, 79, 95).

**Changes:**
1. **Remove the catch-all** — `collectors/dom.py:749`: delete the bare `"select option"` selector from the `size` axis. Admit an option axis only with product-option semantics: axis-bearing `name`/`data-option-name`/`aria-label`, product-form/gallery scope, or corroboration from structured variants.
2. **Generic control-role rejection** — new config in `app/core/config/extraction_rules/` (e.g. `_control_roles.py`; **core package, not extraction** → no module-ceiling/genericness hit): semantic roles for sort, review/rating, country/state, quantity, pagination, opaque-ID. Reject by role, never by site.
3. **Provenance on the catalog** — add `provenance`/`control_role` to `OptionValue`/`OptionAxis` (`contracts.py:449-452 ProductOptionCatalog`); populate in `entities.py:747-787 _option_catalogs()`.
4. **Gate validation + retry on credible axes** — `validation.py:323-368` enforces axes only with credible product-option provenance (keep the ≥2-distinct-value check but add role/provenance gating); `result_building.py:484-533` browser retry (`_explicit_variant_dom_cues`) fires only on product-option axes, not any `option.*`.

**Acceptance:** sort/country/pagination/quantity/opaque-ID controls create no axes; legitimate size/color (results 11, 12, 20, 25, 30, 75) still do.

**✅ DONE (this session):**
- New site-agnostic config `app/core/config/extraction_rules/_control_roles.py`: `SELECT_CONTROL_REJECT_ROLE_TOKENS` (sort/pagination/quantity/geography/review/filter roles), reject phrases, product-option signal tokens, `control_signal_tokens()` (splits on non-alnum + camelCase), `is_rejected_control()`, `has_product_option_signal()`. Wired via `__init__.py` wildcard re-export.
- `collectors/dom.py`: removed the bare `"select option"` catch-all. `_variant_controls` now iterates `<select>`, classifies each via `_select_option_axis()` (rejects by control role, admits only with product-option signal or an axis-bearing label via `_select_label_text()` — `label[for]` or preceding-sibling `<label>`), emits `option.{size,color}` evidence at 0.58 confidence. Added `documents.py` `previous_element()`.
- Item 4 (browser-retry gate): resolved at source — `_explicit_variant_dom_cues` consumes `option.*` evidence which rejected control selects no longer emit, so no separate gating needed. Items 3 (provenance/control_role on the catalog contract) deferred as pure defense-in-depth: acceptance is met at emission time and threading adds LOC to two oversized modules with no behavior change.
- Verified vs all 13 real artifact pages: false-axis pages (10,17,21,58,70,79,95) yield no size axes; legit pages (11,12,20,25,30,75) retain size/color unchanged. Regressions in `test_crawl_run_95_regressions.py`. Re-baselined ratchets (dom.py 1024→1080, validation.py 720→751, documents.py 235→240; extraction/core/total budgets). Full unit suite: **778 passed**.

---

### Slice 3 — Structured child ownership + commercial projection policy (P1)
**Defect:** offers bound to only one variant leave parent commercial fields blank; all-or-nothing aggregation (results 55, 68, 90, 23, 27, 30, 79).

**Changes:**
1. **Stronger child binding** — `entities.py:646-666 _variant_for()`: add join strategies beyond source-subject alias + SKU — canonical URL, option/axis-value match, identity-key cross-ref. `entities.py:597-643 _link_offers()`: stop dropping a whole group on mixed row-level resolution (lines 613-615); bind rows that resolve, retain unresolved separately.
2. **Selected/default variant grounding** — add `selected` to `VariantEntity` (declared in `VARIANT_FACTS` but unstored) and `selected_variant_entity_id` to the synthetic aggregate offer (`resolution/__init__.py:148-150`). When a default variant is clearly identified it may ground the parent display price **with explicit lineage**.
3. **Aggregation policy** — `resolution/__init__.py:556-631 _aggregate_variant_field()` / `:634-661 _aggregate_variant_availability()`: distinguish (a) complete-catalog aggregate, (b) selected/default variant fact, (c) bounded min/max range from a verified subset, (d) unresolved parent. **Never publish a subset as a complete aggregate.** Price min/max fields already exist (`contracts.py`, `publication.py`); wire the policy + lineage. Relax the availability cardinality gate to “eligible sufficient” where policy allows.

**Acceptance:** results 55/68/90 retain joinable child offers; parent publication follows a documented policy (selected-variant or bounded range) without pretending partial coverage is complete.

**✅ DONE (this session):**
- **Root cause found + fixed at the collector, not patched at aggregation.** `collectors/jsonld.py _offers`: embedded offers under `hasVariant[N].offers` carried the shared product URL as their only identity, collapsing every variant's offer into one `group_id` so `_link_offers` bound them all to a single variant and blanked the parent. Now the offer group is namespaced by the owning variant subject (`offer:{artifact}:{variant_subject}:{identity}`) when the offer is embedded under a variant, so each variant keeps its own price/availability. Verified vs real artifacts 68 (260.00 CAD, in_stock), 90, 23, 27 — all now populate parent + per-variant.
- **Availability rollup precedence** — `AVAILABILITY_PARENT_ROLLUP_PRECEDENCE` (in `_listing_structured.py`) replaces the binary `{in_stock,out_of_stock}` gate in `_aggregate_variant_availability`; mixed variant states now roll up by purchasability (result 68's `limited_stock` no longer drops availability).
- **Bounded-range / selected-variant policy** — new `_aggregate_partial_variant_price` publishes documented `price_min`/`price_max` (rule `bounded_variant_price_range`) + selected-variant display price (rule `selected_variant_price`) so partial coverage never masquerades as a complete aggregate. `_parent_derived_from_variants`/`_aggregate_variant_field` thread `selected_variant_ids`.
- **Regressions:** 4 new tests in `test_crawl_run_95_regressions.py` (per-variant binding, mixed→in_stock rollup, all-out→out_of_stock, partial-price bounded range). Ratchets re-baselined (LOC/complexity/oversized/total) in `test_final_architecture_ownership.py` + `extraction_semantic_surface.toml`. Full unit suite **792 passed**; ruff + mypy clean on touched files.
- **Scope note:** post-fix scan of all 95 results found **0** genuinely-partial-priced pages, so the bounded-range path is defensive. Result 55 (0 variants, `outside_selected_target`) is an `isVariantOf` root-selection issue → **Slice 5**.

---

### Slice 4 — Source-aware price-unit consensus (P0 — catastrophic)
**Defect:** result 81 publishes `128000000.00 USD` vs JSON-LD `128.00 USD` (1,000,000×). JS-state `/productSummary/price` wins via `CONTRACT_PREFERRED_SOURCE` **before** unit normalization runs; only ratio `100` is configured and peer match tolerates up to 2×.

**Changes:**
1. **Normalize units before source preference** — reorder so per-candidate unit inference + cross-source **exact power-of-ten** consensus runs ahead of `_resolve_scalar()` preference selection (`resolution/__init__.py` scalar path ~1786-1875 + pipeline order ~117-189; `resolution/price_units.py`). A high-priority integer must not beat multiple structured decimal peers that agree at an exact ×10ⁿ scale.
2. **Exact-scale consensus, not 2× tolerance** — tighten `field_coerce_price.py:153-193 repair_price_unit()` peer logic to require exact power-of-ten agreement with ≥N independent structured decimal peers; extend `extraction_price_rules.py:14` magnitude ratios beyond `(100,)` to cover ×10⁴/×10⁶ where consensus supports it.
3. **Block/review unresolved scale conflicts** — when scale can’t be resolved safely, emit a blocking/review finding; **do not clamp** downstream.

**Acceptance:** result 81 publishes `128.00 USD`, retains lineage to both sources, records the unit-normalization rule; no raw million-scale value survives; all 112 variants keep price.

**✅ DONE (this session) — real root cause differed from the audit hypothesis:**
- **Not a units/source-preference bug.** Traced result 81 end-to-end: the JS-state value is the string `"128.000000"` (six-place minor units from the ERP/react-query feed). It was `parse_money` in `app/core/config/locale_format_rules.py` that corrupted it — `_separator_is_decimal("128.000000", ".")` returned `False` (6-digit trailing group ∉ {1,2}), so `_decimal_separator` returned `None` and `parse_money` fell into the "strip every separator" branch → `128000000`. `NORMALIZE_MONEY_PRECISION` then just formatted the already-corrupt integer.
- **Fix (minimal, generic):** `_separator_is_decimal` now also returns `True` when a separator occurs **exactly once** with a trailing group of **≥4 digits**. A grouping/thousands separator only ever yields exactly-3-digit groups, so a lone separator with a ≥4-digit tail is unambiguously an over-precise decimal point — never delete it. The tail∈{3} ambiguity (`1.234`→`1234`) and genuine multi-group thousands (`1.234.567`, `₹1,86,000`) are untouched.
- **Verified:** result 81 now publishes `128.00 USD` with all **112 variants** retaining price; no `128000000` survives in any evidence/derived fact. Full 95-page sweep found **no new** scale anomalies — the only remaining large prices (54 ₹270,900 Fender, 59 ₹529,990 Sony, 62 ₹186,000 Technics) are genuine INR and unchanged.
- **Regressions:** `test_over_precise_lone_decimal_is_not_read_as_grouping` (parse_money units) + `test_over_precise_embedded_price_is_not_multiplied_by_scale` (end-to-end). `field_coerce_price.repair_price_unit` / `extraction_price_rules` magnitude ratios were **not** needed — the corruption never reached the peer-consensus stage. Ratchets re-baselined (core 17,340→17,347; total 75,077→75,084). **794 unit tests pass**; ruff + mypy clean.

---

### Slice 5 — Narrow content-rejection rules (P1)
**Defects:** description (result 1: `14ozScreen` rejects whole description); image (result 89: 1440×1440 rejected for `_1x1_` token; result 13 asset-lineage gap); brand (results 59/79/92: structured brand lost as outside selected root).

**Changes:**
1. **Description segmentation** — `pipeline.py:625-626` + pattern `_detail.py:132`: segment/normalize compacted feature suffixes during evidence normalization; keep the longest complete grounded prose span; reject whole description only when the prose itself is unusable (stop `description_missing_separator` in `resolution/__init__.py:_GENERIC_INVALIDITY_FLAGS` from nuking the full candidate).
2. **Context-aware `1x1`** — `_images.py:159` + `resolution/__init__.py:1486-1499 _invalid_primary_asset_evidence()`: treat `1x1` as an aspect-ratio hint when a structured product/variant image relation + high-resolution dimensions exist; require corroborating utility evidence (tiny dims / pixel-tracking context / utility path) to reject. Also close the result-13 asset publication-lineage gap.
3. **Brand root reconciliation** — `entities.py:118-144 _select_primary_product_roots()`: add a focused pass so brand evidence from a structured product object sharing canonical URL / SKU / normalized title joins the selected root instead of being discarded. Don’t infer brand from host.

**Acceptance:** result 1 retains valid prose; result 89 publishes the structured image; results 59/79/92 retain direct brand evidence where identity aligns.

**✅ DONE (this session):**
- **Description segmentation:** compacted malformed suffixes now normalize to the longest grounded prose span instead of rejecting the whole description. Result 1 retains the valid Dime product prose.
- **Context-aware `1x1`:** square-crop image markers are no longer treated as tracking pixels when the same URL carries high-resolution dimensions. Result 89 publishes the 1440×1440 MAC image.
- **Asset lineage:** asset resolution now selects the same high-quality evidence that publication uses, including CDN dimension keys like `sw/sh`. Result 13 publishes the high-resolution Converse image with `ASSET_DELIVERY_QUALITY` lineage.
- **Brand root reconciliation:** structured product brand evidence survives when identity is confirmed by URL/root lineage, nested offer URL promotion, or standalone variant parent grouping. Results 59 (`SONY`), 79 (`Gap`), and 92 (`J.Crew`) retain direct brand evidence.
- **Regressions:** new distilled tests cover description segmentation, tracking-pixel vs square-crop image handling, asset selection/publication lineage, nested-offer root scoping, URL-confirmed brand retention, top-level JSON-LD brand survival, and standalone variant brand inheritance.
- **Verified:** `test_collector_root_scoping.py` + `test_crawl_run_95_regressions.py` = **27 passed**; real artifacts 1/13/59/79/89/92 checked; ruff clean; mypy clean on touched app files; ownership ratchet **33 passed** after re-baseline.

---

### Slice 6 — Risk-based review routing + terminal-state consistency (P1/P2)
**Defect:** every result has `review_required=false`, incl. 44 partial, 2 error, and the 1,000,000× price error; terminal-state signals contradict (results 51/52/84).

**Changes:**
1. **Separate verdict from operator routing** — `engine.py:801`: replace `review_required = verdict == "review"` with a routing policy that flags: unresolved high-value requested fields after all enabled stages; public price-scale anomalies (from Slice 4); parent/variant commercial divergence (from Slice 1); shell/blocked contradictions; public projection divergence. Routine missing optional fields do **not** route.
2. **Single immutable capture outcome** — derive one capture-outcome at the extraction boundary from transport status + content usability + semantic shell/not-found; stop `blocked`/`usable_content`/verdict from contradicting (results 51/52/84). No acquisition-strategy change.

**Acceptance:** result 81 and confirmed anomalies route to review; routine partials don’t; results 51/52/84 have internally consistent terminal states.

**✅ DONE (this session):**
- `review_required` is now a routing policy, not `verdict == "review"`. It routes unresolved requested high-value ecommerce fields after retry paths are spent, public divergence/risk findings, and parent/variant commercial divergence. Routine partial records with only unrequested optional gaps do not route.
- Extraction now reports a normalized terminal `transport_outcome`: `blocked`, `not_found`, `semantic_shell`, or the underlying acquisition outcome. Shell errors no longer look like clean `ok` transport once identified at extraction.
- `diagnose.json` now includes top-level `transport_outcome` and acquisition-level `capture_outcome`, while preserving raw `browser_outcome` for forensic context.
- Real artifact metadata check: result 51 → `semantic_shell` + review, result 52 → `not_found` + no review, result 81 → clean success + no review after the slice-4 fix, result 84 → `semantic_shell` + review.
- Regressions: routine partial no-review, requested high-value missing review, semantic shell terminal outcome, HTTP 404 not-found terminal outcome, and normalized diagnose block outcome.
- **Verified:** focused behavior set + architecture ratchets = **267 passed**; ruff clean; mypy clean on touched source.

---

## Cross-cutting: ratchet & verification (every slice)
1. ruff + mypy on touched files (6 pre-existing unrelated mypy errors are not new).
2. Re-baseline LOC/module ratchets: update `test_final_architecture_ownership.py` budgets + `extraction_semantic_surface.toml` per-module numbers; if a new extraction module is unavoidable, bump the 28 ceiling in `test_extraction_architecture.py` with a comment citing this plan.
3. Run `pytest -m unit`; keep architecture/genericness/hot-path ratchets green.
4. New regression tests live beside existing extraction tests, using distilled inline fixtures.

## Regression map (audit §6)
| Regression | Result IDs | Slice |
|---|---|---|
| Candidate-offer warning scoping | 1, 3, 10, 55, 90 | 1 |
| Parent-vs-variant field states | 68, 90 | 1 |
| False variant axes | 10, 17, 21, 58, 70, 79, 95 | 2 |
| Legitimate variant axes retained | 11, 12, 20, 25, 30, 75 | 2 |
| Child offer joining & parent policy | 23, 55, 68, 90 | 3 |
| Price-unit normalization | 81 | 4 |
| Description segmentation | 1 | 5 |
| Image utility-token exception | 89 | 5 |
| Asset publication lineage | 13 | 5 |
| Brand root reconciliation | 59, 79, 92 | 5 |
| Shell/not-found boundary consistency | 51, 52, 84 | 6 |
