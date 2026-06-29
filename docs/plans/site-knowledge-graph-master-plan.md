# Plan: CrawlerAI Site and Product Knowledge Graph Rebuild

**Created:** 2026-06-28
**Revised:** 2026-06-29
**Status:** IN PROGRESS
**Feature spec:** `docs/feature specs/site-product-knowledge-graph.md` (authoritative — the *what* and *why*; this plan is the *order*)
**Touches buckets:** extraction, persistence, observability, PostgreSQL models, crawl orchestration, API, Domain Memory UI, architecture docs

## Goal

Fix extraction debugging, harden extraction architecture, and build a durable cross-crawl Knowledge Graph so the one-time setup cost of a site is paid once and reused. The two qualities that matter most are **field coverage** and **output efficiency**; every slice is judged against them.

Priority order, set by the operator:

1. **Debugging works.** A wrong or missing field is root-caused by reading **one** self-contained file, never raw HTML or source code.
2. **Extraction architecture is clean.** No site-specific branches; one artifact writer; observations flow one way into the graph.
3. **Setup cost falls.** A site's extraction contract is learned once (optionally LLM-proposed, always operator-approved) and reused deterministically.

Knowledge Graph owns extraction contracts, page templates, canonical-field source candidates, source decisions, product claims, and cross-crawl relationships. Domain Memory continues to own acquisition contracts, browser preferences, cookies, saved selectors, operator feedback, and host protection.

## The governing principle

> A diagnostic artifact must cost less to read than the code it explains. If reading the artifact is more expensive than reading the source, the agent reads the source and the artifact is dead weight.

This is why diagnosis collapses to a single self-contained file, not a tree of cross-referenced JSON. See feature spec §6.

## Acceptance Criteria

### Debugging and artifacts (highest priority)

- [ ] Exactly one component writes URL-result artifacts. The second directory scheme (`runs/{id}/pages/...`) is deleted.
- [ ] Every URL result contains exactly `page.html`, `record.json`, and `diagnose.json`. No manifest, summary, debug, browser, trace, screenshot, or duplicate HTML files.
- [ ] `page.html` is written once per URL, not twice.
- [ ] `diagnose.json` is self-contained: per field, the winning candidate, the rejected candidates with reasons, and any firewall action are inlined as bounded text. It never references another file.
- [ ] A missing or wrong `price`, `availability`, or variant is fully explainable from `diagnose.json` alone, without opening `page.html` or source code.
- [ ] Every dropped variant includes row, stage, rule, and reason.
- [ ] `diagnose.json` reuses the existing `FieldEvidenceState` names and the firewalls' existing reject reasons — no parallel vocabulary.
- [ ] A run-level `report.json` groups root causes and links directly to each URL's `diagnose.json`.
- [ ] No dangling artifact references remain: the never-written `acquisition.json` / `extraction.json` reads and the dead `source_trace` provenance keys are deleted.
- [ ] Records API and exports remain behaviorally unchanged.

### Architecture

- [ ] Generic extraction contains no site-specific adapters or retailer-domain branches.
- [ ] Extraction emits observations but never writes canonical graph storage.
- [ ] Every run freezes graph version and matching extraction contracts before processing.
- [ ] Site knowledge is scoped by page template plus surface.

### Knowledge Graph

- [ ] PostgreSQL is authoritative. No Neo4j, Apache AGE, or synchronous dual writes.
- [ ] Knowledge Graph is greenfield. No Domain Memory or legacy-artifact migration/backfill.
- [ ] Workspace reset and Domain Memory reset preserve Knowledge Graph; graph purge is explicit and leaves Domain Memory intact.
- [ ] Every canonical field exposes accepted/rejected source candidates, selection rule, and evidence.
- [ ] Operator source selection affects matching future runs without rewriting historical records.
- [ ] Product identity is deterministic; title, vector, and LLM similarity cannot create authoritative SAME_AS edges.
- [ ] Individual variants are not graph entities; only canonical variant-set claims persist.
- [ ] Domain Memory UI exposes a bounded visual Knowledge Graph explorer and source controls.

### LLM

- [ ] No LLM call runs in the extraction hot path.
- [ ] The cold-start contract proposer produces only `selection_origin=llm_proposed` contracts; nothing is auto-activated. The runtime that consumes contracts never calls an LLM.

### Gates

- [ ] Backend tests and smoke suites pass.
- [ ] Frontend tests, policy checks, and build pass.

## Architecture Decisions

### Knowledge Graph and Domain Memory stay separate

- Domain Memory remains acquisition-owned; Knowledge Graph remains extraction-owned. Neither migrates into the other. Resets are independent (feature spec §2).

### PostgreSQL graph model

Add tables: `kg_site_versions`, `kg_entities`, `kg_relationships`, `kg_claims`, `kg_assertion_evidence`, `kg_extraction_contracts`. Node and edge vocabulary, identity order, and the vector posture are specified in feature spec §4. Deterministic product identity: GTIN → manufacturer+MPN → site product ID → site SKU → canonical URL. Vector/title/LLM similarity may seed candidates only.

### Extraction contracts

Scope saved source choices by `(page template, surface, canonical field)`. Retain all candidates, bounded latest values, success/rejection counts, resolver rule, selected source, and selection origin (`generic` / `operator` / `llm_proposed`). Operator selection is preferred precedence, never a forced value; validate the preferred source on each page and fall back deterministically. Freeze graph version and relevant contracts in `extraction_runtime_snapshot` at run creation (feature spec §5).

### Diagnostics (the corrective core)

The debt to remove (feature spec §6.1): two competing directory layouts, `page.html` written twice, two writers/readers, references to files that are never written, dead `source_trace` keys, and the discarding of `ExtractionResult.evidence`.

The replacement (feature spec §6.2): one writer, three files, and a **self-contained** `diagnose.json` that inlines bounded per-field provenance. It distinguishes — using existing vocabulary — `source_unavailable`, collector-not-run, `not_present_in_captured_sources`, `captured_but_rejected`, `captured_conflicting`, removed-by-materialization, and removed-by-public-firewall. Collector outcomes: `ran` / `skipped` / `no_match` / `produced_evidence` / `failed` / `timed_out`. We accept the loss of offline replay for network-sourced fields (feature spec §6.4).

### API

Add bounded read/refine endpoints (`GET /api/knowledge/sites`, `.../graph`, `.../contracts`, `GET /api/knowledge/entities/{id}`, `PUT /api/knowledge/contracts/{id}/selection`, `POST /api/knowledge/sites/{domain}/rebuild`, `DELETE /api/knowledge/sites/{domain}`). Read bounds: default depth 2 / max 4, default 200 nodes / max 500. Authenticated users read and refine; rebuild and purge are admin-only.

## Do Not Touch

- Existing Domain Memory schema and ownership, except reset tests proving graph preservation.
- User-selected surface, traversal, proxy, and LLM controls.
- Generic technology collectors and protocol fingerprints.
- Historical record values after an operator source change.
- Neo4j, Apache AGE, and graph analytics (not in scope for this plan).
- Individual variant rows as persistent graph entities.

## Slices

> Ordering reflects the operator's priority: debugging first, then architecture cleanup, then the graph, then setup-cost reduction. Slices 2 and 3 are independent and may proceed in parallel.

### Slice 1: Save and activate the master plan and feature spec

**Status:** DONE
**Files:** `docs/feature specs/site-product-knowledge-graph.md`, `docs/plans/site-knowledge-graph-master-plan.md`, `docs/plans/ACTIVE.md`

**What:**

- Rewrite the design conversation into an authoritative feature spec and move it to `docs/feature specs/`.
- Rewrite this plan to match the spec and the operator's revised priorities.
- Point ACTIVE.md at this plan.

### Slice 2: Collapse to one artifact writer and a self-contained diagnose.json (PRIMARY)

**Status:** DONE (2026-06-29)
**Files:** URL-result publisher, crawl persistence, observability readers/writers, artifact tests

**What:**

- Make the URL-result publisher the sole writer. Delete the `runs/{id}/pages/...` scheme, `manifest.json`, `summary.json`, `records.json`, `debug.json`, `browser.json`, `trace.json`, screenshots, and the audit duplicates.
- Emit exactly `page.html`, `record.json`, `diagnose.json`. Replace `manifest_uri` with the fixed result-root convention.
- Build `diagnose.json` as a self-contained, bounded index: per requested or notable field — status (`FieldEvidenceState`), winning candidate (collector, locator, value, rule), rejected candidates (collector, locator, ≤120-char value preview, reason), firewall action, and per-variant drop `(row, stage, rule, reason)`. Inline everything; reference nothing.
- Add collector outcomes and stage outcomes to `diagnose.json`.
- Generate deterministic `report.json` grouping root causes with direct links to each URL's `diagnose.json`.
- Delete the dangling reader contracts (`acquisition.json` / `extraction.json`) and the dead `source_trace` provenance keys; repoint records API, exports, audit, replay, and baseline readers to the new layout.
- Delete the superseded observe-only LLM diagnosis flow (`run_llm_diagnosis`) and its `llm_diagnosis.json`.

**Verify:**

- Exactly three files exist per URL for success, partial, blocked, empty, and error; `page.html` written once.
- No `runs/{id}/pages` output is written.
- Missing price, currency, availability, and dropped variants are explainable from `diagnose.json` alone.
- `report.json` lists each root cause with counts and diagnosis links.
- Records API and exports remain behaviorally unchanged.

### Slice 3: Delete site-specific extraction debt

**Status:** TODO
**Files:** extraction/resolver config, structure tests, obsolete artifact/observability code

**What:**

- Audit retailer-domain branches and hardcoded site extraction. The code is already mostly generic; finish the job.
- Keep generic Shopify, JSON-LD, Workday, Greenhouse, and network-protocol collectors, and the parameterized currency-hint and Shopify-shape config tables.
- Add a structure test rejecting retailer domains in generic extraction while allowing protocol, anti-bot, schema.org, test, and Product Intelligence domains.
- Delete compatibility shims, obsolete artifact schemas/readers, duplicate source selection, and dead observability code surfaced by Slice 2.

**Verify:** architecture ratchet passes; no site-specific extraction branch remains; cold-start generic extraction works.

### Slice 4: Ratchet architecture boundaries

**Status:** TODO
**Files:** canonical architecture docs, architecture tests, graph config owner

**What:**

- Add Knowledge Graph subsystem ownership and invariants: Domain Memory separation, no backfill, frozen graph versions, no direct extraction writes, reset preservation, no LLM-authoritative claims, no variant entities, no site-specific extraction adapters.
- Add dependency-direction and reset-separation tests.
- Put graph types, statuses, read bounds, and runtime tunables under `app/core/config`.

**Verify:** focused architecture and invariant tests pass.

### Slice 5: Add PostgreSQL graph foundation

**Status:** TODO
**Files:** graph models/repository/service, Alembic revision, reset service, component tests

**What:**

- Add graph tables, constraints, indexes, repository, and migration (UUID, JSONB, foreign keys, recursive SQL, transactional batch upserts).
- Serialize concurrent per-site projection through site-version row locking.
- Retain bounded evidence after crawl reset using nullable `ON DELETE SET NULL` references.
- Preserve graph tables during application and Domain Memory resets; add explicit graph purge.

**Verify:** migration, constraints, rollback, reset preservation, concurrency, and idempotency tests pass.

### Slice 6: Build deterministic site-template and source projection

**Status:** TODO
**Files:** projection contracts/service, extraction projection seam, template tests

**What:**

- Fingerprint templates from normalized route shape, surface, technology signals, stable DOM structure, and source inventory; exclude volatile content, product values, timestamps, IDs, and counts.
- Convert evidence, decisions, findings, records, and the new diagnostics into graph observations with no DB access inside extraction.
- Project canonical-field sources, winner, rejected alternatives, rules, locators, and validation outcomes.
- Add site, technology, template, route, field, and source relationships.

**Verify:** equivalent PDPs share templates; listing/detail stay separate; unrelated templates cannot share overrides.

### Slice 7: Freeze and execute graph extraction contracts

**Status:** TODO
**Files:** crawl snapshot, URL context, extraction request/resolver, diagnosis tests

**What:**

- Load graph version and bounded contracts into `extraction_runtime_snapshot` at run creation; match acquired pages against frozen route/template candidates; pass selected contracts into extraction.
- Prefer a saved source only when current evidence validates it; keep generic collectors as fallback.
- Record contract outcomes (hit / miss / fallback / stale-source / override-miss) in `diagnose.json`. Never override explicit user controls.

**Verify:** active runs stay stable during concurrent updates; stale sources fall back; choices apply only to later matching templates.

### Slice 8: Project canonical product knowledge

**Status:** TODO
**Files:** projector, identity policy, run-complete finalizer, tests

**What:**

- Project page, product, offer, brand, category, seller, and asset entities from resolved public decisions; preserve accepted and rejected claims with evidence.
- Create `PRODUCT_SAME_AS` only from deterministic identity or explicit approval.
- Store one canonical variant-set claim (axes, count, fingerprint, selected source, lineage); never create variant entities.
- Complete runs in order: project graph, increment material version, generate report, expose projection failure without changing the crawl verdict.

**Verify:** GTIN joins across sites; title-only similarity does not; projection is idempotent; variants remain aggregate-only.

### Slice 9: Add graph API and operator refinement

**Status:** TODO
**Files:** graph router/schemas/service, router registration, API tests

**What:**

- Implement bounded graph, contracts, neighbourhood, source-selection, rebuild, and purge endpoints with optimistic version checks.
- Reject cross-template, cross-surface, and cross-field source choices; append operator decisions to history.
- Return graph-only sites after crawl and Domain Memory resets; rebuild only from retained new-format capsules and atomically swap versions.

**Verify:** auth, bounds, conflicts, invalid-source rejection, reset persistence, and atomic rebuild tests pass.

### Slice 10: Add cold-start LLM contract proposer (setup-cost reduction)

**Status:** TODO
**Files:** cold-start proposer service, reuse of dormant `review_field_candidates` task, contract promotion path, tests

**What:**

- On the first crawl of a new `(domain, surface, template)`, run a single bounded LLM pass that confirms surface/platform, enumerates likely sources per requested field, and proposes selectors with sample matched values verified against the captured page.
- Reuse the existing `connectors/llm` budget/cache/circuit-breaker stack and the dormant `review_field_candidates` task. Emit a `kg_extraction_contract` row marked `selection_origin=llm_proposed`.
- Never auto-activate. Operators promote a proposal via `PUT /api/knowledge/contracts/{id}/selection` (Slice 9). The runtime consuming the contract calls no LLM.

**Verify:** proposer output is deterministic config, never a value; proposals are inert until promoted; promotion affects only matching templates; budget and cache bounds hold.

### Slice 11: Add Domain Memory visual graph explorer

**Status:** TODO
**Files:** frontend API contracts, workspace, explorer components/tests, dependency manifest

**What:**

- Add `@xyflow/react`; include graph-only domains in Domain Memory; add a Knowledge Graph tab preserving existing tabs.
- Provide site/product modes, filters, bounded canvas, inspector, source candidates, evidence, override controls, rebuild state, and graph version. Load bounded neighbourhoods only; no free-form graph editing.

**Verify:** frontend tests cover loading, error, empty, source selection, graph-only domains, and bounded rendering.

### Slice 12: Full validation and canonical documentation

**Status:** TODO
**Files:** canonical docs and final verification repairs

**What:**

- Validate first-run learning, second-run reuse, competing sources, override, fallback, template isolation, reset preservation, graph purge isolation, exact-three artifacts, single-file self-service diagnosis, and cold-start proposal-then-promotion.
- Update stable docs without changelog noise.

**Verify:**

    cd backend
    $env:PYTHONPATH='.'
    python -m pytest tests -m "unit or component or regression" -q
    python run_acquire_smoke.py commerce
    python run_extraction_smoke.py
    python run_test_sites_acceptance.py

    cd ..
    pnpm test
    pnpm run check:policy
    pnpm run build

## Doc Updates Required

- [ ] docs/backend-architecture.md — graph, single-writer artifacts, runtime snapshot, API
- [ ] docs/CODEBASE_MAP.md — Knowledge Graph ownership
- [ ] docs/INVARIANTS.md — graph, reset, single-writer, and extraction boundaries
- [ ] docs/BUSINESS_LOGIC.md — source selection and product identity
- [ ] docs/ENGINEERING_STRATEGY.md — direct graph writes, dual artifact paths, and site-specific extraction anti-patterns
- [ ] docs/agent/SKILLS.md — single-file diagnosis and contract-refinement recipes

## Notes

- 2026-06-28: Plan approved by user. Slice 1 (original) completed.
- 2026-06-29: Operator audit. Priority reset to debugging-first. Plan revised: Slice 2 is now the single-writer + self-contained `diagnose.json` collapse (was Slice 3); site-specific debt deletion pulled forward (Slice 3); cold-start LLM contract proposer added (Slice 10). The design conversation was rewritten into `docs/feature specs/site-product-knowledge-graph.md` and is now the authoritative spec.
- 2026-06-29: Slice 2 completed. One writer (`publish_url_result_artifacts`) emits `page.html` / `record.json` / `diagnose.json` under `runs/{id}/results/{url_result_id}/`. `ExtractionResult` carries `collector_outcomes`, `stage_outcomes`, and `variant_drops`; `diagnose.json` inlines per-field winner/rejected/firewall and the variant-drop ledger. `app/observability/run_report.py` registers as a run-complete callback and folds every diagnose into `report.json`. Dead modules deleted: `observability/{artifact_reader,baseline,browser_artifact,run_audit,run_llm_diagnosis,run_trace}.py`, `persistence/artifact_store.py`, `persistence/storage/`, `api/observability.py`, `config/{audit_rules,observability}.py`, `data/prompts/run_diagnosis.*.txt`, and the frontend Run Trace surfaces. Regression: 1092 passed / 8 expected skips across unit + component + services.
- The feature spec governs intent; this plan governs sequence. When they disagree, the spec wins and this plan is corrected.
