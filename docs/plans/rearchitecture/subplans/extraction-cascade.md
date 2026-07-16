# Extraction Spine — Detailed Implementation Plan (Plan draft)

Scope: the surface-agnostic extraction cascade that replaces the selector-bank approach for all 4
surfaces. Backend only. Paths verified against `git ls-tree -r main`. Reference-only branch:
`origin/feature/extraction-v3-phase0-eval` (read via `git show <branch>:<path>`; NONE of these
files exist on `main`).

> Slicing principle (per main-agent guidance): the cascade ships PER SURFACE, gated independently.
> Task order is: shared spine/schema (T1) → **commerce listing** (T2) → **job listing** (T3) →
> **commerce detail** (T4) → **job detail** (T6), with the LEARN-ONCE tier (T5) landing after the
> listing floors exist and before detail hardening. Each surface task is a full vertical slice
> (collector + adapter wiring + tests) that can be enabled/disabled behind config without touching
> the others.

## File structure map

New files (create):
- `backend/app/extraction/listing_records.py` — selector-free record-boundary discovery
  (`discover_listing_records`, `RecordBoundary`, grid/homogeneity scoring). Surface-agnostic.
- `backend/app/extraction/listing_tier0.py` — deterministic structured + DOM floor
  (`collect_structured_listing`, `collect_deterministic_listing`, `ground_boundaries`).
- `backend/app/extraction/network_listing.py` — network-JSON repeated-array floor
  (`collect_network_listing`).
- `backend/app/extraction/cascade.py` — the single tier-ordering seam
  (`run_listing_cascade`, `run_detail_cascade`) that composes floors + recipe replay + learn. This
  is the only module that knows tier order; it is driven by `SurfaceSpec`/`ListingSchema`, never by
  `surface ==`.
- `backend/app/extraction/representation/__init__.py`, `backend/app/extraction/representation/flat_map.py`
  — flat path→text representation + grounding (`build_flat_map`, `build_scoped_flat_map`, `ground`).
- `backend/app/core/extraction_memory/recipe_contracts.py` — frozen `ExtractionRecipe`,
  `RecipeBinding`, `RecipeEntity`, `RecipeExecutionResult`, `DiscoveryResult` (branch shape).
- `backend/app/core/extraction_memory/recipe_executor.py` — mechanical replay (`execute_recipe`);
  no discovery, no storage.
- `backend/app/core/extraction_memory/recipe_transforms.py`, `recipe_artifacts.py` — value
  transforms + JSON-artifact reads used by the executor (branch has these; port verbatim).
- `backend/app/core/extraction_memory/recipe_compiler.py` — LEARN-ONCE compiler: flat-map → ONE
  grounded LLM proposal → `ExtractionRecipe`. **New, main-owned (do NOT port the branch's
  `compile_recipe_candidate` — it reverse-derived from published records).**
- `backend/app/core/config/cascade.py` — cascade thresholds/knobs (tier order enable flags,
  `_MIN_REPEATED_RECORDS`, record-signal sets per surface, LLM-learn enable, recipe scope key).

Changed files:
- `backend/app/extraction/surfaces.py` — extend `SurfaceSpec`; add `ListingSchema` +
  `listing_schema()` + `structured_type_selectors()` (branch shape).
- `backend/app/extraction/documents.py` — add `HtmlNode.child_elements()` and
  `HtmlNode.content_text()` (discovery + richness depend on these; absent on `main`).
- `backend/app/extraction/adapters.py` — repoint `_harvest_listing`, `_harvest_job_listing`,
  `_harvest_job_detail`, `_harvest_detail`/`harvest_compiled_recipe` at the cascade.
- `backend/app/extraction/engine.py` — route recipe/learn tiers through `cascade`, set
  `extractor_tier="llm"` on the learn path; keep verdict/retry/metrics ownership.
- `backend/app/extraction/jobs.py` — read the ecommerce-style HTML artifact set (not only `"html"`),
  apply the shared quality gate, add wrong-surface guard for `job_listing`.
- `backend/app/extraction/targeting.py` — off-host root admission for job listing; URL
  disambiguation for job detail (mirror `_select_product_by_url`).
- `backend/app/extraction/result_building.py` — `retry_request` emits `CapabilityRequest` for all
  four surfaces, not only ecommerce.
- `backend/app/extraction/contracts.py` — relax `CapabilityRequest.max_attempts` cap (currently
  `ge=1, le=1`) to allow a multi-rung ladder; add `network_payloads` to the `required_artifacts`
  vocabulary if not present.
- `backend/app/crawl/pipeline/extraction_loop.py` — fix `UrlVerdict` Literal
  `"listing_failed"` → `"listing_detection_failed"` to match `persistence/publish/verdict.py`.
- `backend/app/core/config/extraction_recipes.py` — keep `ECOMMERCE_LISTING_HTML_ARTIFACT_IDS`;
  add a shared listing-HTML-artifact constant jobs also read.

Config ownership: all strings/thresholds/selectors/field-names live under `core/config/*`
(`cascade.py`, `extraction_recipes.py`, `surfaces.py` spec data, `network_capture.py`,
`evaluation.py` for flat-map token limits). No literals in service code (repo INVARIANT).

## Tasks

### Task 1 — Shared spine: typed schema + representation + document primitives [parallel]
Foundation every surface task depends on. No behavior change to existing surfaces yet.
- Extend `SurfaceSpec` in `extraction/surfaces.py` with `structured_types: frozenset[str]`,
  `listing_optional_text_facts: tuple[str, ...]`, `listing_structured_fact_kinds:
  tuple[tuple[str,str], ...]`, `listing_network_fact_keys: tuple[tuple[str,tuple[str,...]], ...]`
  (defaults empty). Populate all 4 `SURFACE_SPECS` entries with the branch's values
  (commerce: `{"Product","ItemList"}`, price/image kinds; jobs: `{"JobPosting","ItemList"}`,
  organization/location kinds; identity keys `id/jobId/opportunityId/requisitionId` for job listing).
- Add `ListingSchema` dataclass + `listing_schema(value)` (returns `None` for `cardinality=="one"`)
  + `structured_type_selectors(value)`, ported from branch `surfaces.py`. `entity_type_for` splits
  `fact_type` on `.`.
- Add `HtmlNode.child_elements()` (direct element children) and `HtmlNode.content_text()`
  (subtree text) to `extraction/documents.py`, matching the branch signatures the discovery module
  calls. Verify against branch `documents.py`.
- Add `extraction/representation/flat_map.py` + `__init__.py`, ported from branch. Uses
  `core/config/evaluation.py` token/anchor constants (`EXTRACTION_V3_*`); port any missing
  constants into `evaluation.py`.
- Add `core/config/cascade.py` with: tier enable flags, `LISTING_MIN_REPEATED_RECORDS`, per-surface
  record-signal descriptors (commerce: image|price|text-link; jobs: title+detail-link+location/
  company — NO price/image), LLM-learn enable default, recipe scope key.
Tests:
- `backend/tests/unit/test_surface_schema.py` (new): `listing_schema` returns typed lens for both
  listing surfaces and `None` for both detail surfaces; `entity_type_for` mapping; all 4 spec
  entries have consistent `title_fact`/`url_fact` in `required_facts`.
- `backend/tests/unit/test_flat_map.py` (new, port branch tests): path building, scoping,
  grounding exact/normalized, token capping/chunking.
- `backend/tests/unit/test_documents_primitives.py` (new): `child_elements`, `content_text` on a
  fixture tree.
- Run: `cd backend && ruff check app/extraction/surfaces.py app/extraction/representation && pytest tests/unit/test_surface_schema.py tests/unit/test_flat_map.py tests/unit/test_documents_primitives.py -q`.

### Task 2 — Commerce listing cascade slice [after 1]
First shippable surface. Wire the deterministic floors behind the commerce listing adapter and gate
it independently.
- Add `extraction/listing_records.py` (port `discover_listing_records`, `RecordBoundary`,
  `_GridParent`, `_best_grid_children`, `_homogeneity_score`, `_structural_signature`,
  `_product_anchors`, `_link_identity`). Keep it schema-agnostic; move the commerce-specific
  `_is_content_rich` logic behind a `record_signal` callable supplied by the cascade from
  `core/config/cascade.py` (so jobs can pass a different signal in Task 3 without editing this file).
- Add `extraction/listing_tier0.py` (`collect_structured_listing`, `collect_deterministic_listing`,
  `ground_boundaries`, JSON-LD scan) and `extraction/network_listing.py`
  (`collect_network_listing`), ported and driven by `listing_schema(surface)`.
- Add `extraction/cascade.py::run_listing_cascade(request, reader, schema)` returning ordered floor
  evidence: structured → network → DOM. Emits `CollectorOutcome`s. No `surface ==` branch.
- Repoint `adapters._harvest_listing` to call `run_listing_cascade` via `_harvest_from_rows`,
  replacing the direct `collect_ecommerce_listing` call. Keep `collect_ecommerce_listing` as the
  commerce DOM-floor detail-mapper the branch reuses.
- Config flag in `core/config/cascade.py` to enable the cascade for `ecommerce_listing`
  independently (fallback to legacy `collect_ecommerce_listing` when off) — this is the per-surface
  gate.
Tests:
- `backend/tests/unit/test_listing_records.py` (new, port branch): grid repetition, homogeneity
  tie-break, structural-URL rejection, singleton-only-via-structured.
- `backend/tests/unit/test_listing_tier0_structured.py` (port branch test of same name): JSON-LD
  floor grounds boundaries; partial coverage fails whole floor.
- `backend/tests/unit/test_network_listing.py` (new): repeated-array materialization, `>=2` rows,
  same-host URL, id→detail-URL grounding.
- Extend `backend/tests/unit/test_extraction_listing_behavior.py`: commerce listing produces
  records from structured + DOM floors with zero model calls (dyson/arcteryx-style fixtures).
- Run: `cd backend && pytest tests/unit/test_listing_records.py tests/unit/test_listing_tier0_structured.py tests/unit/test_network_listing.py tests/unit/test_extraction_listing_behavior.py -q`.

### Task 3 — Job listing cascade slice + de-commerce discovery invariants [after 2]
Reuse the same cascade for jobs; this is where the commerce assumptions get removed.
- `extraction/jobs.py::collect_job_listing`: read the shared listing HTML-artifact set (the
  `ECOMMERCE_LISTING_HTML_ARTIFACT_IDS` equivalent — rename to a shared
  `LISTING_HTML_ARTIFACT_IDS` in `core/config/extraction_recipes.py`) instead of only `"html"`, so
  JS-rendered job boards are covered.
- Route `adapters._harvest_job_listing` through `run_listing_cascade` with the job `ListingSchema`
  and the **job record-signal** from `core/config/cascade.py` (title + detail-link +
  location/company; NO price/image).
- De-commerce `listing_records`:
  - Foreign-host acceptance: confirm/keep `_consistent_record_host` accepting a single foreign host;
    add an explicit test with Greenhouse/Lever/Bullhorn off-host grids. Remove any hard
    `same_site(page_url, child.url)` requirement from the non-singleton path (it currently only
    appears in the `allow_singleton` branch — verify and keep record-set path host-neutral).
  - Anchor-less JS-onclick cards: in `_product_anchors`/discovery, when a repeated container has no
    `<a href>` but has a stable record-local key (data-*/id token) and repeats `>=
    LISTING_MIN_REPEATED_RECORDS`, admit it. Add the record-local key extraction to
    `listing_records` behind a schema/cascade-supplied resolver.
- `adapters._resolve_job_listing_adapter`: keep; add `_incomplete_record_findings` job required
  `{"job.title","job.url"}` (already present) and ensure the shared quality gate (reject
  nav/footer titles like "Apply"/"Save") runs — wire the existing but unused job hub-rejection
  markers from `core/config/extraction_rules/_listing_structured.py`
  (`JOB_LISTING_HUB_TITLE_*`, `JOB_POSTING_PATH_MARKERS`) into the job floor.
- Add wrong-surface guard for `job_listing` (mirror `jobs.wrong_surface_findings_for_job_detail`).
- Per-surface enable flag for `job_listing` in `core/config/cascade.py`.
Tests:
- Extend `backend/tests/unit/test_listing_records.py`: off-host ATS grid accepted; anchor-less
  onclick grid accepted; nav menu rejected.
- `backend/tests/unit/test_job_listing_cascade.py` (new): JS-rendered board fixture → records via
  DOM floor with zero model calls (ultipro-style); hub titles rejected; foreign-host apply links
  accepted; `job_listing` reads rendered artifact set.
- Extend `test_extraction_surface_behavior.py`: job_listing no longer returns
  `listing_detection_failed` on the rendered fixture.
- Run: `cd backend && pytest tests/unit/test_listing_records.py tests/unit/test_job_listing_cascade.py tests/unit/test_extraction_surface_behavior.py -q`.

### Task 4 — Commerce detail cascade + structured floor unification [after 1]
Bring detail surfaces onto the same structured-floor primitives. Can run in parallel with T2/T3
after T1 (touches detail harvest, not listing), but sequence after T2 if reviewer prefers one
listing surface proven first.
- Add `run_detail_cascade(request, reader, spec)` in `extraction/cascade.py`: structured floor
  (JSON-LD/microdata/OG/script-JSON via existing `collectors/jsonld.py`, `js_state.py`,
  `metadata.py`) → existing `harvest_ecommerce_detail` DOM pipeline. Keep the existing
  `resolve`/`publish`/variant logic untouched.
- `adapters._harvest_detail`: compose via `run_detail_cascade`; preserve
  `harvest_compiled_recipe` fast-path (now a recipe-replay path, see Task 5).
- Per-surface enable flag for `ecommerce_detail`.
Tests:
- Extend `backend/tests/unit/test_extraction_baseline.py` and
  `test_extraction_contract_behavior.py`: commerce detail unchanged outputs on existing fixtures
  (regression parity), plus structured-floor-first ordering asserted via `stage_outcomes`.
- Run: `cd backend && pytest tests/unit/test_extraction_baseline.py tests/unit/test_extraction_contract_behavior.py tests/unit/test_extraction_variant_behavior.py -q`.

### Task 5 — LEARN-ONCE tier: recipe contracts, replay, grounded compiler, persistence [after 2, after 4]
The cold-path learner + hot-path replayer. Depends on flat-map (T1) and at least one listing floor
(T2) plus detail floor (T4) so the fallback ordering is real.
- Port `core/extraction_memory/recipe_contracts.py`, `recipe_executor.py`, `recipe_transforms.py`,
  `recipe_artifacts.py` from branch verbatim (frozen, storage-free, no discovery in executor).
- Write NEW `core/extraction_memory/recipe_compiler.py`:
  - Inputs: `ExtractionRequest` (capture + flat-map only), `SurfaceSpec`/`ListingSchema`,
    LLM client (`connectors/llm/provider_client.call_provider_with_retry`).
  - ONE model call: prompt asks for `{field: path}` bindings + (listings) the repeated record-root
    path, over `build_scoped_flat_map(doc)`. Prompt/task config in `core/config/cascade.py` +
    `connectors/llm/prompt_rendering`.
  - Grounding gate: for each proposed binding, `flat_map.ground(expected_value_at_path)` /
    node-resolution must pass; ungrounded bindings are dropped; if required
    (title/url/record-root) fail, NO recipe is persisted (honest failure).
  - Output: `ExtractionRecipe` (`extraction_recipe.v2`), persisted via
    `persistence/extraction_memory.upsert_recipe` + `compile_recipe_layers` keyed by
    `(domain, surface, route_pattern)` template (`ensure_template`,
    `create_release_snapshot`). MUST NOT read `record_extraction_result`'s published records — it
    only reads the capture/flat-map. Add an assertion/architectural test enforcing this.
- Engine/cascade wiring (`engine.py`, `cascade.py`):
  - Replace the ecommerce-detail-only `_compiled_recipe_template` + `harvest_compiled_recipe` gate
    with a surface-agnostic `execute_recipe` replay path for any surface with a matching compiled
    recipe. On replay success → `extractor_tier="recipe"`. On drift (grounding fails) → fall
    through to floors and, if still empty + `llm_enabled` + new template, invoke the compiler once
    → `extractor_tier="llm"`.
  - Retire `model_runtime.py`'s ecommerce-detail-only ML fallback path from the live cascade (keep
    the grounding helpers `_value_is_grounded`/`_grounded_evidence` — reuse them in the compiler's
    gate). Sentinel/challenger stays optional and read-only.
- Config: recipe scope key, LLM-learn enable, per-surface learn allow-list in
  `core/config/cascade.py`.
Tests:
- Port `backend/tests/unit/test_recipe_contracts.py`, `test_recipe_executor.py` from branch.
- `backend/tests/unit/test_recipe_compiler.py` (new): grounded proposal → recipe persisted;
  ungrounded binding rejected/capped; required-field ungrounded → no recipe; compiler given a
  fixture with published records present in the bundle still ignores them (invariant test).
- `backend/tests/unit/test_extraction_architecture.py` (extend): assert exactly one records
  producer; compiler module has no import path to publication/records output.
- `backend/tests/unit/test_learn_once_replay.py` (new): first crawl (LLM stub) learns; second crawl
  replays deterministically with the LLM stub asserted NOT called; drift fixture forces recompile.
- Run: `cd backend && pytest tests/unit/test_recipe_contracts.py tests/unit/test_recipe_executor.py tests/unit/test_recipe_compiler.py tests/unit/test_learn_once_replay.py tests/unit/test_extraction_architecture.py -q`.

### Task 6 — Job detail slice + surface-agnostic escalation ladder + verdict fixes [after 3, after 5]
Last surface + the cross-cutting correctness fixes the brief flagged.
- `extraction/jobs.py::collect_job_detail` / `adapters._harvest_job_detail`: route through
  `run_detail_cascade` (structured JobPosting floor → DOM). Read the rendered artifact set.
- `targeting.py`: add URL-based disambiguation for `job_detail` (mirror `_select_product_by_url`)
  so multi-`JobPosting` JSON-LD (similar-jobs widgets) no longer trivially triggers
  `AMBIGUOUS_JOB_ROOT`; keep `select_subject_targets` but disambiguate by requested URL first.
- `result_building.retry_request`: emit `CapabilityRequest` for `job_listing`/`job_detail`
  (empty/shell → `rendered_html`; missing structured → `network_payloads`), not only ecommerce.
- `contracts.CapabilityRequest`: relax `max_attempts` upper bound to allow a multi-rung ladder
  (HTTP → browser → browser+network) so escalation does not dead-end after one browser attempt;
  keep a bounded max in `core/config/cascade.py`.
- `crawl/pipeline/extraction_loop.py`: fix `UrlVerdict` Literal `"listing_failed"` →
  `"listing_detection_failed"`.
- `crawl/pipeline/retry/stage.py`: honor the surface-agnostic ladder (loop up to the configured
  rung count instead of the hard `browser_escalation_count >= 1` cap) — bounded, honest exhaustion.
Tests:
- `backend/tests/unit/test_job_detail_cascade.py` (new): JobPosting structured floor; similar-jobs
  widget disambiguated by URL (no false ambiguity); rendered artifact read.
- Extend `test_extraction_surface_behavior.py`: job surfaces get a `RetryRequest` on empty/shell.
- `backend/tests/unit/test_verdict_literal.py` (new): `UrlVerdict` contains
  `"listing_detection_failed"` and downstream string checks match `verdict.VERDICT_LISTING_FAILED`.
- `backend/tests/component/` escalation test: multi-rung ladder reaches browser+network then
  exhausts honestly.
- Run: `cd backend && pytest tests/unit/test_job_detail_cascade.py tests/unit/test_extraction_surface_behavior.py tests/unit/test_verdict_literal.py -q && ruff check app/extraction app/crawl/pipeline`.

## Final integration verification
- `cd backend && ruff check app && pytest tests/unit tests/component -q` (full extraction + pipeline
  suites green).
- Per-surface toggle matrix: each surface enabled independently via `core/config/cascade.py`; with
  all floors on and `llm_enabled=false`, all 4 surfaces extract deterministically on the branch's
  proven fixtures (principle 3). With `llm_enabled=true` on a new template, exactly one LLM call
  learns; the replay run makes zero LLM calls (principle 2).
- Architecture assertions: one records producer; cascade has no `surface ==` branch (grep gate in
  `test_extraction_architecture.py`); compiler cannot import publication output.

## Requirement → task traceability
- Shared cascade routed by typed SurfaceSpec → T1 (schema), T2/T3/T4/T6 (all use it, no if/else).
- Tier 0 structured floor → T2 (listing), T4/T6 (detail).
- Tier 0 network-JSON floor → T2 (listing); available to detail via same schema.
- Selector-free DOM discovery (dyson/arcteryx/ultipro) → T2 + T3.
- LEARN-ONCE (one grounded call, compiled recipe, replay LLM-free, drift→recompile) → T5.
- Hard grounding gate → T5 (compiler) reusing `model_runtime` grounding helpers.
- De-commerce invariants (no same_site, no image/price, anchor-less onclick, off-host ATS) → T3.
- Avoid branch mistakes (no 2nd architecture; compiler never publishes/reverse-derives; one owner)
  → reuse main's Harvest→Resolve→Publish (all tasks); T5 new compiler + invariant tests.
- Config in core/config/* → all tasks (`cascade.py`, `surfaces.py` data, `extraction_recipes.py`).
- Contracts for other streams (SurfaceSpec, ExtractionResult/verdict, recipe persistence,
  capability seam) → T1, T5, T6.

## Blocking question (architecture fork — main agent should confirm with user before T5)
Recipe scope granularity + LLM-learn autonomy. Options:
- **A. Per (domain, surface, route_pattern) template, auto-learn on first crawl when `llm_enabled`**
  (reuses existing `extraction_templates` route normalization; matches branch data model). Learns
  silently, replays forever, recompiles on drift. Lowest operator friction; risk of a bad
  auto-learned recipe replaying until drift.
- **B. Per (domain, surface) only** (coarser; one recipe serves all routes of a surface on a
  domain). Simpler, fewer recipes, but mixed-template domains (e.g. two PLP layouts) may thrash.
- **C. Auto-learn but quarantine**: new recipe is `provisional`, replays but is flagged for operator
  promotion to `active` (uses existing `EXTRACTION_MEMORY_STATUS_PROVISIONAL` +
  `ExtractionOperatorLabel`). Safest, adds a review step.
This is expensive to change later (persistence keys + replay matching), so it needs a user decision.
All other decisions are resolved by existing convention (Harvest→Resolve→Publish, extraction_memory
tables, grounding gate) or by explicit user requirement in the brief.
