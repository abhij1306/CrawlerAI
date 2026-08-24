# Plan: CrawlerAI Extraction Accuracy and Coverage

**Created:** 2026-08-23
**Agent:** Codex
**Status:** PAUSED
**Touches buckets:** ecommerce extraction contracts, field registry/config, eval corpus and runner, variant/title/offer/identifier/metadata extraction, publication parity, architecture tests, documentation

## Goal

Improve ecommerce-detail extraction accuracy and coverage for CrawlerAI without weakening evidence lineage, selected-variant precision, or truthfulness on source-limited pages. Done means the frozen CrawlerAI-only eval, targeted extraction tests, and final documentation show better product, variant, offer, identifier, title, and metadata behavior while keeping unresolved cases honestly unresolved and preserving existing correct boundary cases.

## Acceptance Criteria

- [ ] Config-owned commerce registry publishes `product_id`, rating/review fields, `materials`, `specifications`, and `product_details` through explicit public-contract wiring.
- [ ] `CommerceDetailRecord` exposes explicit product ID, rating/review, and metadata fields; `price_min` and `price_max` are published separately; `variant_count == len(variants)` after final serialization.
- [ ] A versioned 63-case CrawlerAI-only replay corpus exists under `backend/eval/` with one canonical expectation per URL and manual replay support in the existing runner.
- [ ] Variant, title, price/currency/availability, identifier, and metadata remediation improve coverage only where frozen source evidence supports it and preserve truthful unresolved diagnostics otherwise.
- [ ] Final eval and focused suites prove stable exact assertions, forbidden-value assertions, lineage guarantees, no top-level variant-ID leakage, and p95 extraction time no more than 20% above baseline unless explicitly approved.
- [ ] Focused backend pytest verification, required manual corpus replay commands, Ruff, and final documentation verification exit 0.

## Do Not Touch

Files and modules out of scope — with reason:

- `frontend/**` — no frontend changes requested.
- Listing, jobs, automobiles, export-repair, persistence-repair, enrichment-cleanup flows — explicitly excluded by assumptions.
- Endpoint and database migration owners — plan forbids endpoint and schema migration.
- LLM value-generation paths — LLM stays disabled for ecommerce-detail value generation.
- New parallel eval runners, scheduled jobs, or PR gates — plan requires reuse of the existing local corpus runner and manual-only full replay.

## Slices

### Slice 1: Save and queue this plan
**Status:** DONE
**Files:** `docs/plans/crawlerai-extraction-accuracy-plan.md`, `docs/plans/ACTIVE.md`
**What:** Create this queued plan file, append it to `ACTIVE.md`, preserve the current CodeQL closeout plan as active, run `git diff --check`, confirm both references, then stop. Remaining slices execute in a new session.
**Verify:** `git diff --check`; inspect `docs/plans/ACTIVE.md` and this plan file.

### Slice 2: Reactivate plan and freeze the CrawlerAI eval
**Status:** TODO
**Files:** `docs/plans/ACTIVE.md`, this plan, `backend/eval/**`, existing local extraction corpus runner, focused eval tests
**What:** After the current security plan completes, mark this paused plan `IN PROGRESS` and current in `ACTIVE.md`. Build a versioned 63-case CrawlerAI-only eval under `backend/eval/`. Export replay inputs from the canonical artifact store with HTML plus required embedded state/network JSON, compressed captures, and no derived `record.json` or diagnosis output. Consolidate conflicting old labels so one canonical expectation exists per URL. Extend `run_local_extraction_corpus.py`; do not add a parallel runner. Support stable exact fields and variant tuples, forbidden values, sibling products and UI controls, dynamic price/availability semantic rules, capture-limited or honestly unresolved cases, and extraction mean/p50/p95 timing. Keep full 63-case replay manual only. Record pre-change accuracy, coverage, and three-run warm timing baseline.
**Verify:** Focused eval-runner tests and the explicit manual corpus command for the full 63-case replay.

### Slice 3: Unify field ownership and publication parity
**Status:** TODO
**Files:** existing field-mapping owner, commerce config owners, publication owners, contract tests, architecture tests
**What:** Add one typed commerce-field registry to the existing field-mapping owner. Derive collector aliases, fact-to-public-field publication maps, scope, and value kind from it. Delete duplicated mappings made redundant by the registry. Add architecture tests proving canonical fields cannot exist without fact/publication wiring. Fix publication so variant count is computed from rows actually serialized, not projected entity IDs.
**Verify:** Contract, field-policy, publication, and architecture tests; Ruff.

### Slice 4: Recover source-backed variants
**Status:** TODO
**Files:** variant/entity binding owners, JS-state/network collectors, publication/validation owners, focused tests, optional eval partition
**What:** Repair product/variant/offer binding for product-scoped state and network matrices. Preserve stable IDs, SKU, barcode, option tuple, URL, price, and availability lineage. Reject sibling handles/styles, unrelated product URLs, recommendation payloads, duplicate mobile/desktop controls, and generic parent rows when real variants exist. Permit product-root DOM recovery for a single explicit option axis only when each option is a purchasable form/control with option-level evidence. For two or more axes, require an explicit source matrix or combination relationship and never calculate a blind Cartesian product. Keep incomplete cases unresolved with `EXPECTED_VARIANT_AXIS_MISSING` or source-unavailable diagnostics. Cover stable targets such as Puma 38, Gymshark 7, iFixit 2, Phase Eight 8, MAC 80, and H&M 15 only where the frozen capture contains sufficient source evidence. Test Back Market and Skechers by dimensions and identity rules when counts are dynamic. Preserve every existing correct boundary case from the eval. If required first-party payloads were not captured, improve only the existing generic acquisition artifact capture path; acquisition remains observational and cannot assign logical fields.
**Verify:** Variant, JS-state, collector-root, validation, and publication tests plus the optional variant eval partition.

### Slice 5: Fix product-title authority
**Status:** TODO
**Files:** title candidate/evidence owners, cleanup config owners, focused tests, optional eval partition
**What:** Attach a semantic title role to candidates: product object/API title, PDP H1, JSON-LD product name, or page/SEO title. Rank product identity and pollution flags before generic source priority. Prefer a valid product-object title, then product H1, then same-product JSON-LD, with page/SEO titles last. Add config-owned generic cleanup for action prefixes and detached color, size, platform, locale, and site suffixes. Keep cleanup inside evidence admission/resolution with lineage and no post-publication mutation. Lock the Apple, Birkenstock, Net-a-Porter, Nintendo, Peloton, Sony, and H&M cases.
**Verify:** Title, targeting, integrity, and publication tests plus the title eval partition.

### Slice 6: Fix price, currency, and availability semantics
**Status:** TODO
**Files:** offer extraction owners, selected/default variant resolution owners, locale/currency owners, focused tests, optional eval partition
**What:** Map current/sale price to `offer.price`, compare/list price to `offer.original_price`, and aggregate low/high price to bounds. Select explicitly selected/default variant price before any aggregate price. Strengthen selected-variant evidence from URL parameters and source `selected/default` markers. Keep price and currency atomically paired by subject/source lineage. Roll up availability only from a complete, same-product variant set; one unavailable variant cannot make the product globally unavailable. Add semantic fixtures for sale-over-original, selected-over-minimum, locale currency, Add-to-Cart, and incomplete inventory. Lock Converse and Fellow price behavior. Treat live availability values as dynamic parser checks.
**Verify:** Offer-price, price-unit, locale, availability, and integrity tests plus the offer eval partition.

### Slice 7: Separate product identifiers from variant identifiers
**Status:** TODO
**Files:** identifier/brand collectors, entity-binding owners, contract tests, optional eval partition
**What:** Emit `product.id` only from explicit product-level identifiers in structured state, first-party APIs, or supported structured data. Never manufacture `product_id` from URL text without an explicit platform contract. Remove bare generic `id` from product-SKU admission. Reject a top-level SKU that equals a variant ID or variant-only SKU without direct product-level evidence. Recognize product-root labels such as Style, Style Code, Item Number, Article, Part Number, and explicit SKU. Keep variant identifiers inside their variant entities. Lock DTLR `HQ7978-103` and Phase Eight `10015500806`. Improve brand selection using product/vendor/manufacturer evidence while rejecting retailer/site identity.
**Verify:** Identifier, brand, collector, entity-binding, and public-contract tests plus the identifier eval partition.

### Slice 8: Add safe metadata breadth
**Status:** TODO
**Files:** metadata collectors, JSON-LD owners, DOM-section owners, validation/publication owners, optional eval partition
**What:** Collect and publish source-backed rating, review count, materials, specifications, and product details. Use JSON-LD/first-party state/network first, then product-root DOM sections. Normalize ratings to 0–5 only when the source scale is explicit or standard; otherwise suppress with a diagnostic. Require nonnegative integer review counts. Reject review widgets, navigation copy, recommendations, unrelated tables, and unrestricted metadata blobs. Keep these fields optional. They cannot affect product identity, offer validity, or variant eligibility. Require every eval case whose frozen capture contains an admissible source value to publish that value with lineage.
**Verify:** Field-policy, JSON-LD, metadata, DOM-section, validation, and publication tests plus the breadth eval partition.

### Slice 9: Run final accuracy and performance gates
**Status:** TODO
**Files:** focused extraction suites touched by prior slices, eval outputs, plan notes
**What:** Run all focused extraction suites touched by the plan and Ruff. As a required manual gate after explicit user authorization, run the 63-case eval three warm times on the same machine used for baseline. Require all stable exact and forbidden-value assertions pass, all previous correct boundary cases remain correct, no platform variant ID leaks into top-level SKU, every public value has selected or derived lineage, breadth coverage improves wherever admissible source evidence exists, capture-limited cases remain truthful rather than fabricated, and p95 extraction time is no more than 20% above baseline. Live end-to-end timing is informational because network conditions vary. If p95 exceeds 20%, profile and optimize before completion unless the user explicitly approves an exception.
**Verify:** Focused pytest files, Ruff, and three warm full-corpus manual replay runs on the baseline machine.

### Slice 10: Create final evidence report and close
**Status:** TODO
**Files:** `docs/audits/crawlerai-extraction-remediation-report.md`, `docs/backend-architecture.md`, `docs/CODEBASE_MAP.md`, `docs/INVARIANTS.md`, this plan, `docs/plans/ACTIVE.md`
**What:** Create the final remediation report. Record root causes, changed owners, stable/dynamic/unresolved case results, field coverage before/after, and timing before/after. Update architecture/codebase/invariants docs only for real contract or ownership changes. Mark all acceptance criteria and slices complete. Mark the plan `DONE` and update `ACTIVE.md` to the next queued plan or no active plan. Run `git diff --check` as final documentation verification.
**Verify:** Report/doc diffs reviewed, `git diff --check`, plan checklist complete, and `ACTIVE.md` updated to the next state.

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — only if extraction ownership or durable contracts change.
- [ ] `docs/CODEBASE_MAP.md` — only if new files or ownership boundaries change.
- [ ] `docs/INVARIANTS.md` — only if shared extraction/publication contracts change.
- [ ] `docs/audits/crawlerai-extraction-remediation-report.md` — final evidence report required by Slice 10.

## Notes

- Evaluation data contains only captures, ground truth, expected behavior, and CrawlerAI before/after results.
- Work stays CrawlerAI-only.
- Current baseline before this plan: 145 focused extraction tests pass.
- This plan became active on 2026-08-23 after the prior queued work was completed.
- This plan was paused on 2026-08-24 for the explicit security-plan assignment.
- No endpoint or database migration is allowed.
- `materials`, `specifications`, and `product_details` stay product-scoped text fields for this plan.
- `price_min` and `price_max` must be published separately and must never substitute for selected/default `price`.
- Source-insufficient pages remain diagnosed and unresolved; accuracy wins over fabricated coverage.
- Full corpus replay runs only by explicit user request.
- No frontend, listing, job, persistence-repair, export-repair, or enrichment-cleanup changes belong to this plan.
- Slice 1 verification (2026-08-23): `git diff --check` passed; at that time the CodeQL closeout plan remained current and this plan was queued in `ACTIVE.md`.
