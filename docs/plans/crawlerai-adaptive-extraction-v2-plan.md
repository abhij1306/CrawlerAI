# Plan: Extraction Correctness Overhaul — Clean Foundation → Compiled Recipes → Learned Fallback

**Created:** 2026-07-02 (rewritten after review rejection of the ML-first draft)
**Agent:** Claude (Opus 4.8)
**Status:** IN PROGRESS — Phase 0 complete; Phases 1–7 expanded into decision-complete slices; next step is Phase 1 implementation
**Authoritative:** This is the single authoritative extraction roadmap going forward. The two previously-queued extraction plans are **retired and not referenced** (their scope is mostly landed and superseded here).
**Feature specs:** `docs/feature specs/CrawlerAI_Adaptive_Extraction_Architecture_v2.md` (target architecture — the *what/why*). Product/ops/governance concerns are **explicitly deferred** to `docs/feature specs/CrawlerAI_Deferred_Product_Operations_Architecture.md` and are **out of scope** here.

---

## Framing

CrawlerAI's **acquisition** architecture is its strength: it works across ~90% of sites, and proxy covers the rest. Its **weakest part is extraction and normalization** — which fails outright or emits confidently-wrong data. Fix extraction correctness and the rest of the roadmap (the deferred product/operations plane) becomes straightforward. This plan is therefore scoped narrowly to **making the extraction engine correct, clean, and small**, exposing stable contracts/evidence so the deferred product plane can be built on top later.

Two motivating failures anchor the acceptance criteria:
1. A crawl returned **0 records** because a card selector was `test-data-id` while the page used `test-dataid`. One character of drift → total loss.
2. **New sites miss variants even when the HTML was captured correctly** — the deterministic binder fails on evidence that is present.

The target is a **self-healing, self-evolving, human-led** system: a cheap compiled fast path for learned templates, an evaluation-gated learned fallback for the unseen, a challenger that detects silent drift, a human correction loop that turns operator labels into recipes + training data, and grounded LLM assistance for the long tail. Deterministic rules are not abandoned — they become **compiled outputs of a learning system**, not hand-maintained intelligence.

**Two rules govern the whole plan:**
- **Quick wins first.** Sequence by cost-to-value: consolidation, deletion, and contracts before any new ML/serving infrastructure.
- **Debt deletion in every phase.** Every phase must remove code and tests, not just add them. A phase that only adds is mis-scoped. "Debt" means real codebase debt (overlapping stores, dead LLM paths, post-extraction repair, mega-modules) **and** test debt — not tests alone.

---

## What the target architecture gets right (retained as hard constraints)

These are non-negotiable and survive from the spec / prior review:
- ML/LLM predictions become **Evidence**; they never write public records. **Resolve** (`app/extraction/resolution.py`) stays the sole semantic authority; **Publish** (`app/extraction/publication.py`) stays projection-only.
- The compact page representation is **lazy** — never built on the success path.
- Sentinel output is a **challenger, not ground truth**.
- Recipes are **compiled and bounded**, never unrestricted generated code executed at runtime.
- **Locale/market semantics are separated** from structural extraction.
- LLM output must be **grounded** in evidence; no LLM in the hot path; LLM may *propose* rules but never *activate* them.
- **Acquisition is out of scope** (Bucket 3). Extraction begins from an immutable input bundle.
- Ratchets stay green: no retailer-domain literals in extraction; extraction does not import KG storage; persistence performs no extraction repair; `resolution.py` owns semantic derivation / variant eligibility / asset selection; `publication.py` owns projection (per `tests/unit/test_extraction_architecture.py`).

---

## Resolved decisions (operator, 2026-07-02)

**D1 — Knowledge Graph disposition → REPLACE WHOLESALE.** Delete the 6-table generic graph package (`KGSiteVersion, KGEntity, KGRelationship, KGClaim, KGAssertionEvidence, KGExtractionContract`) and rebuild extraction memory as purpose-built relational tables. Largest migration, cleanest end state. No generic entity/relationship/claim graph survives unless it has a concrete extraction consumer.

**D2 — Authoritative store → NEW CONSOLIDATED RECIPE/MANIFEST STORE.** One owner: structural template → recipe layer → compiled recipe → locale-policy ref → manifest → operator label → evaluation/observation. `DomainMemory.selectors` (domain_memory.py:27), `KGExtractionContract` (knowledge_graph.py:208), `ReviewPromotion` (review.py), `DomainFieldFeedback` (domain_memory.py:63), and per-run recipe payloads + `extraction_runtime_snapshot` migrate into it or are deleted. This *is* the D1 relational replacement — D1 and D2 are the same target from two angles.

**D3 — Manifest scope → RUN SNAPSHOT + PER-URL MANIFEST ID.** One immutable run-level release snapshot plus one resolved execution manifest per URL-result/template context. Represents mixed templates/locales/provisional pages within a run.

**D4 — Invariant supersession → APPROVED (follows from D1/D2).** The KG *greenfield / no backfill / no Domain Memory migration* invariant is explicitly superseded with a dated `docs/INVARIANTS.md` edit. The `DomainMemory`-owns-selectors ownership inconsistency is resolved during consolidation, not preserved.

**Sequence — APPROVED.** Start Phase 0 (clean-foundation first); no ML/Sentinel infrastructure until their gates pass.

---

## Master roadmap (concise — full target, gated)

Detailed slices are written for every phase below. They remain gated: do not start a later phase until the previous phase exit gate passes and the plan notes record the debt deletion / verification result.

| Phase | Objective | Exit gate |
|---|---|---|
| **0 — Clean foundation & baseline** | Resolve D1–D4. Delete dead LLM paths + post-extraction repair. Consolidate the five stores to one. Split the mega test suite; replace the misleading `ast.unparse` LOC ratchet with physical-LOC + complexity gates. Freeze deterministic accuracy/latency/cost baselines. Define versioned evaluation + grounded-label schema. | Baselines frozen and reproducible; one authoritative store; dead code + repair paths deleted; test suite split; net **negative** LOC. |
| **1 — Deterministic contracts** | Formalize input boundary, execution context, Field/Locale policy, failure taxonomy, trust states, manifest scope+identity (D3), business-readable diagnostics. | Contracts typed and tested; every zero-record outcome carries a classified reason. |
| **2 — Real compiled recipe fast path** | Structural fingerprints; minimal recipe hierarchy; deterministic compiler; a **genuine short-circuit** known-template path (today none exists — recipe evidence is merely appended); replay + atomic rollback; template isolation; locale overlays. | A learned template executes via compiled recipe without running all generic collectors; local fix cannot mutate a higher layer; ambiguous merge fails compilation. |
| **3 — Operator correction & labels** | Consolidate existing review/learning/selector screens into **one** operator flow (delete the others). Visual grounded correction; replay; representative validation; activation gates. Corrections emit **grounded labels** (node/path/region/absence). | A non-specialist corrects a template without writing selectors; a correction produces a trustworthy training label and generalizes to siblings. |
| **4 — Universal extractor research & evaluation** | Compact representation; **offline** model prototypes; known/unseen/temporal evaluation vs the frozen deterministic baseline; compare model families; decide local vs shared inference **from benchmarks**. | Model **proven** to beat deterministic generic extraction on unseen templates without raising ungrounded-value rate; no production serving infra built yet. |
| **5 — Runtime ML fallback** | Wire the proven model as the lazy Stage-4 fallback in `engine.py`, emitting Evidence. Build serving infra **only if** Phase-4 benchmarks require it. | Success path never invokes the model; the `test-data-id`/`test-dataid` mutation now yields records; accuracy/latency/grounding/cost gates pass. |
| **6 — Sentinel / anti-drift** | Start with a **generic deterministic challenger** (compiled recipe vs full generic extraction). Add the ML challenger only after Phase 5. Semantic comparison, drift states, cautious auto-suspension. | Challenger cannot silently override a recipe; confirmed critical drift auto-suspends to fallback. |
| **7 — Grounded LLM repair** | Delete/consolidate the legacy LLM extraction tasks first. Grounded rule-proposal + evidence adjudication; **no direct standard-field generation**; custom fields only under declared typing + grounding. | LLM cannot publish ungrounded values or activate a rule; legacy direct-extraction tasks removed. |

**Deferred beyond this plan:** advanced learning (template-specific models, cross-page fusion, active learning), pgvector (stays candidate-only), and the entire product/operations/governance plane → `CrawlerAI_Deferred_Product_Operations_Architecture.md`.

---

## PHASE 0 — Clean Foundation & Baseline (detailed, executable)

> Rationale: these are the highest value-to-cost moves and they are almost entirely **deletion + measurement**. Nothing here builds new runtime infrastructure. Phases 1+ are unsafe to start until the foundation is clean and a baseline exists to measure against.

### Slice 0.1 — Freeze the deterministic baseline
**Status:** DONE — artifact generated (`app/evaluation/baselines/run_1.json`); `pytest tests/unit/test_extraction_baseline.py` + `test_final_architecture_ownership.py` green (total-app LOC budget still holds after Slice 0.3 deletions offset the new package); ruff/mypy clean on touched files.
**Delete target:** none (measurement only) — but records the debt every later slice must reduce.
**Files:** `app/evaluation/__init__.py` (new), `app/evaluation/baseline.py` (new), `app/evaluation/baselines/run_1.json` (new, committed artifact), `tests/unit/test_extraction_baseline.py` (new)
**Path note:** relocated from the plan's original `app/extraction/evaluation/` to a NEW top-level `app/evaluation/` package. Reason: evaluation observes extraction and does not belong in its semantic runtime surface. Slice 0.5 now guards that package at 24 files / 11,873 physical nonblank lines plus per-module complexity; the former 5,500 normalized-AST figure was deleted as misleading. `app/observability/baseline.py` is also explicitly forbidden by `test_observability_is_owned_by_top_level_package`. `app/evaluation/` imports no extraction runtime and carries no site literals.
**What:** Reduce the existing frozen offline run (`backend/artifacts/runs/1/` — output-only: `record.json` + `diagnose.json` per URL + run-level `report.json`; no raw HTML, so this is a characterization snapshot, not an HTML replay) to a small, stable, versioned summary: verdict/data-integrity distribution, completeness (mean/min/p50/p95), resolve/publish/total latency p50/p95, per-field status counts + contract-field publish rate + reason-code frequency, variant integrity (counts + dropped), findings by rule/severity + blocking count, acquisition method/status distribution, and top root causes. Cost signals recorded as explicitly absent (deterministic extraction has no hot-path LLM cost). Serialized sorted-keys for byte-stability. Committed under `app/evaluation/baselines/` (NOT under ignored `backend/artifacts/`). This is the number every later phase must beat and must not silently regress.
**Verify:** `python -m app.evaluation.baseline` (writes `app/evaluation/baselines/run_1.json`); `pytest tests/unit/test_extraction_baseline.py`; `ruff`/`mypy` on touched files.

### Slice 0.2 — Define evaluation + grounded-label schema (before any model work)
**Status:** DONE — versioned `EvaluationCase` / `GroundedLabel` contracts cover node/path/region grounding, repeated-record boundaries, primary/recommendation regions, typed entity relationships, semantic roles, locale interpretation, and explicit absence. Release truth accepts only human-verified labels or explicitly qualified deterministic pseudo-labels. 12 focused tests green; ruff/mypy clean.
**Delete target:** none yet (schema seeds later deletions).
**Files:** `app/evaluation/schema.py` (new: `EvaluationCase`, `GroundedLabel`), `tests/unit/test_evaluation_schema.py` (new) — relocated to the top-level `app/evaluation/` package for the same ratchet reason as Slice 0.1.
**What:** Versioned schema that separates **human-verified truth**, **deterministic pseudo-labels**, **weak labels**, and **unverified model output** — with node/path/region references, repeated-record boundaries, primary/recommendation-region marks, explicit absence, and semantic roles. Only human truth + qualified pseudo-labels may participate in release evaluation. This directly answers the review's point that existing `KGAssertionEvidence` (locator string + value preview + confidence) is **not** sufficient ML ground truth.
**Verify:** `pytest tests/unit/test_evaluation_schema.py`; schema rejects unqualified model output from the release set.

### Slice 0.3 — Delete dead LLM extraction tasks
**Status:** DONE — 6 prompt files deleted; `pytest tests/regression/test_llm_runtime.py tests/component/test_llm_config_service.py` green; ruff clean. Net LOC negative.
**Delete target:** the three dead wrappers `extract_records_directly` / `extract_missing_fields` / `review_field_candidates` and everything that existed only to serve them.
**Applied edits (verified statically via read/grep — no remaining references):**
- `connectors/llm/tasks.py` — deleted the 3 wrapper functions + orphaned imports (`json`, `safe_truncate_for_prompt`, `truncate_html`, `truncate_json_literal`). `run_prompt_task` (live: enrichment + product-intelligence) preserved.
- `connectors/llm/runtime.py` — dropped the 3 names from imports/`__all__`; re-exports `run_prompt_task` only.
- `connectors/llm/payloads.py` — removed the 3 dead adapters (`direct_record_extraction`, `missing_field_extraction`, `field_cleanup_review`) and their now-orphaned types (`_FieldCleanupReviewPayload`, `_EvidenceDecision`, `_EvidenceRecipeSuggestion`, `_FieldKey`, `_NonEmptyText`, `_PresentValue`, `_require_present_value/_non_empty_text/_payload_key`) and the unused `NotRequired` import. `SUPPORTED_TASK_TYPES` now derives from the 5 surviving tasks.
- `core/config/field_mappings.py` — `PROMPT_REGISTRY` emptied to `{}` (name kept: `config_service.get_prompt_task` + a collision test reference it); merge logic tolerates empty.
- `frontend/app/admin/llm/page-view.tsx` — removed dead `missing_field_extraction` / `field_cleanup_review` from the admin `TASK_TYPES` dropdown.
- Tests re-pointed to surviving/neutral task types: `tests/regression/test_llm_runtime.py` generic-machinery tests → `generic_runtime_probe` / `generic_runtime_probe_array` (unregistered → validation passthrough, preserving exact-echo payload asserts + budget/timeout/cache coverage); array test renamed `…_returns_array_response_payload`. `tests/component/test_llm_config_service.py` → `data_enrichment_semantic` (task row) + `page_classification` (fallback).
**Pending (Bash-gated):** delete the 6 orphaned prompt files `app/data/prompts/{direct_record_extraction,missing_field_extraction,field_cleanup_review}.{system,user}.txt`; run `ruff check` on the 4 edited modules + import smoke + `pytest tests/regression/test_llm_runtime.py tests/component/test_llm_config_service.py`.
**Verify:** grep proves zero remaining references to the 3 task types in `app/` + `tests/` (done); no test enumerates the prompts dir or asserts the dead tasks (checked); net LOC negative.

### Slice 0.4 — Remove post-extraction repair paths
**Status:** DONE — `test_extraction_architecture.py` + `test_harness_support.py` green; app-wide ruff and touched-file mypy clean.
**Delete target:** any persistence-layer or downstream field mutation that "fixes" extraction after Resolve.
**Finding:** the sweep confirmed **no live downstream mutation exists** — Resolve/Publish are already the only authorities and the prior repair mutators (`public_record_firewall`, `sanitize_materialized_record`, `materialize_product_assets`, `drop_unusable_variants`, …) are already gone. What remained was **dead repair scaffolding** referencing that removed era, with no producer anywhere in `app/`:
- `crawl/pipeline/persistence.py` — deleted the `"field_repair": …raw_record.get("_field_repair")` line in `_discovered_data_for_record`; `_field_repair` was read but never written.
- `persistence/export/schema.py` — deleted the `field_repair` and `self_heal` fields from `ExtractionTrace` (projection only ever received `source_trace["extraction"]`, which `_source_trace_for_record` never produces; both fields were producer-less).
- `harness/support.py` — removed the inert (`require_repair_diagnostics` defaulted `False`) repair-diagnostics quality gate: the `repair_diagnostics_ok` check, the `require_repair_diagnostics` expectation, `_quality_repair_diagnostics_ok`, the `repair_diagnostic_missing` failure-mode branch + its entry in the `bad_output` set. It checked a signal nothing can emit.
- `tests/regression/test_harness_support.py` — deleted the 2 tests that exercised that gate.
**Ratchet tightened:** added `tests/unit/test_extraction_architecture.py::test_no_post_resolution_repair_scaffolding_remains` — an `app/`-wide source scan asserting the `field_repair`/`self_heal` tokens cannot return (scoped so `resolution.py`'s in-authority `repair_price_unit`/`_price_unit_repairs` do not match). Existing `test_persistence_performs_no_extraction_repair` walks only AST Name/Attribute/import nodes, so it never caught the string-literal `_field_repair` read; the new sweep closes that gap. Phase 7 (grounded LLM repair) reintroduces repair diagnostics only when a real producer lands.
**Verify:** grep proves zero remaining `field_repair`/`self_heal`/`repair_diagnostic` references in `backend/` (done); `pytest tests/unit/test_extraction_architecture.py tests/regression/test_harness_support.py -q`; `ruff` on the 4 edited modules. Net LOC negative.

### Slice 0.5 — Replace the misleading LOC ratchet
**Status:** DONE — extraction gate now measures 11,873 physical nonblank lines plus per-module Radon complexity. The second misleading app-wide `ast.unparse` ratchet was also replaced; current app budget is 71,204 physical lines, down 905 across completed Phase 0.
**Delete target:** the `ast.unparse`-based canonical-LOC budget.
**Files:** `tests/unit/test_extraction_architecture.py` (lines 39, 191-195), `app/core/config/extraction_semantic_surface.toml` (ratchets block)
**What:** `_canonical_line_count = len(ast.unparse(node).splitlines())` with `<= 5500` measures *normalized* output, not the ~physical size of the package — it reads as "small" while the package is far larger. Replace with a **physical-LOC + cyclomatic-complexity** gate per module, seeded at current real values so it ratchets **down** as Phase 0 deletes code. Keep the other honest ratchets (no retailer literals, no KG-storage import, repair-forbidden, owner assignments).
**Verify:** `pytest tests/unit/test_extraction_architecture.py`; the gate reflects physical reality and only decreases.

### Slice 0.6 — Split the oversized test suites
**Status:** DONE — `test_extraction_pipeline.py` split into nine behavior-owned suites plus shared test support. Exact 298-test collection preserved and green. Largest extraction behavior suite is 1,384 lines. Acquisition/browser and Product Intelligence suites were excluded by scope and the acquisition Do Not Touch rule.
**Delete target:** obsolete compatibility tests, private-function tests, duplicated policy cases, redundant "stays-deleted" checks.
**Files:** `tests/unit/test_extraction_pipeline.py` (reported ~8,159 lines / ~298 tests — measure exactly first), plus other >2k-line suites surfaced by measurement
**What:** Split by owner (move acquisition-concern tests to acquisition suites); replace private-function imports with **contract/behavior** tests; parametrize repeated policy cases; delete obsolete compatibility tests; consolidate the scattered "deleted file must stay deleted" checks (e.g. `test_final_architecture_ownership.py:248,252`) into one registry. New tests assert public outcomes, not internal selector state.
**Verify:** focused `pytest` on each new split file; total test LOC down materially; behavior coverage preserved (verdict/record assertions unchanged).

### Slice 0.7 — Replace KG + consolidate the five stores into one relational owner (executes D1+D2+D4)
**Status:** DONE — generic KG model/repository/projector deleted. Selector memory, contract choices, review promotions, field feedback, release snapshots, URL manifests, and observations now use `models/extraction_memory.py`; migration `20260702_0004` carries existing learned state and drops the prior tables. Focused store/runtime/review/crawl/API/dashboard tests green.
**Delete target:** the entire generic KG package (`app/models/knowledge_graph.py` 6 tables + `persistence/knowledge_graph.py` + `core/knowledge_graph/*` that have no extraction consumer), `DomainMemory.selectors`, `ReviewPromotion`, `DomainFieldFeedback`, and per-run recipe payloads once migrated.
**Files:** new `app/models/extraction_memory.py` (consolidated relational store), `app/models/domain_memory.py`, `app/models/knowledge_graph.py` (delete), `app/models/review.py`, `app/models/crawl_run.py`, corresponding persistence + Alembic migration, `docs/INVARIANTS.md` (supersede per D4)
**What:** Stand up the new consolidated recipe/manifest store (template → recipe layer → compiled recipe → locale ref → manifest → operator label → observation). Migrate learned knowledge in; delete the generic KG package and the other four stores (or reduce to projections). Resolve the `DomainMemory`-selectors ownership inconsistency. Because D1 is a wholesale replacement this is a real schema migration — settle it last in Phase 0 so the baseline (0.1) and honest LOC gate (0.5) already exist to prove no regression and measure the reduction.
**Verify:** migration test proves no behavior change for currently-passing templates; deleted stores/package have zero remaining readers; net schema + LOC reduction.

**Phase 0 exit gate:** D1–D4 resolved; baselines frozen and reproducible; one authoritative store; dead LLM + repair paths gone; test suite split and honest LOC gate in place; **cumulative LOC change is negative**.

---

## PHASE 1 — Deterministic contracts (detailed, executable)

> Rationale: the runtime must describe what it received, what it tried, why it trusted or rejected the output, and why zero records happened. This phase adds contracts and diagnostics only; it does not add ML, Sentinel, or LLM behavior.

### Slice 1.1 — Freeze the extraction input boundary
**Status:** TODO
**Delete target:** ad-hoc request/context dictionaries passed between extraction call sites once typed contracts replace them.
**Files:** `app/extraction/contracts.py`, `app/extraction/engine.py`, `app/extraction/replay.py`, `app/crawl/pipeline/record_extraction_stage.py`, `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, focused tests under `tests/unit/` and `tests/component/`
**What:** Introduce typed `ExtractionInputBundle` and `ExecutionContext` surfaces that treat upstream page artifacts as immutable. Carry bundle identity, URL, observed time, available artifact types, provenance/completeness flags, supplied vs inferred locale context, and run/release snapshot identity into extraction. Runtime may report insufficiency; it must not mutate acquisition state or silently rewrite user controls.
**Verify:** focused tests prove extraction receives a typed immutable bundle, records supplied vs inferred context, preserves `surface` / traversal / proxy / `llm_enabled`, and produces the same deterministic output as the Phase-0 baseline for covered fixtures.

### Slice 1.2 — Move field, locale, and contract policy behind typed registries
**Status:** TODO
**Delete target:** duplicated field names, locale constants, thresholds, and semantic-role strings in extraction service code.
**Files:** `app/core/config/field_mappings.py`, `app/core/config/public_record_policy.py`, `app/core/config/variant_policy.py`, `app/core/config/extraction_price_rules.py`, `app/core/config/extraction_semantic_surface.toml`, `app/extraction/contracts.py`, `app/extraction/resolution.py`, `app/extraction/validation.py`, tests for policy loading and resolution behavior
**What:** Define typed `FieldContract` / field-policy / locale-policy objects that describe canonical field, type, entity scope, cardinality, requiredness, criticality, validators, publish behavior, semantic role, and market interpretation. Keep config in `app/core/config/*`; extraction consumes resolved policy objects only.
**Verify:** focused tests prove no new config literals live in extraction service code; semantic resolution still owns variant eligibility / asset selection / price role; locale ambiguity cannot receive `verified` trust for critical fields.

### Slice 1.3 — Make failure taxonomy mandatory
**Status:** TODO
**Delete target:** unclassified zero-record failures, generic `"failed"` / `"unknown"` result reasons where a specific taxonomy reason is available.
**Files:** `app/extraction/contracts.py`, `app/extraction/engine.py`, `app/extraction/result_building.py`, `app/extraction/validation.py`, `app/observability/diagnose.py`, `tests/unit/test_extraction_architecture.py`, focused zero-record tests
**What:** Implement the architecture taxonomy as typed reason codes: wrong surface, insufficient input bundle, template mismatch, recipe drift, discovery, record boundary, entity binding, semantic resolution, canonicalization, locale normalization, validation, unsupported representation, model service failure, internal error. Require every zero-record outcome to include one or more codes plus a business-readable diagnostic.
**Verify:** focused tests force representative zero-record paths and assert classified reasons; architecture ratchet forbids unclassified zero-record publication.

### Slice 1.4 — Attach manifest identity and business-readable diagnostics to every result
**Status:** TODO
**Delete target:** run/result fields that duplicate or partially shadow manifest identity; opaque extraction debug blobs with no stable schema.
**Files:** `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, `app/extraction/contracts.py`, `app/extraction/engine.py`, `app/observability/diagnose.py`, `app/persistence/export/schema.py`, API serializers that expose diagnose/export fields, focused component tests
**What:** Ensure every extraction result records one run-level release snapshot and one per-URL resolved execution manifest ID. Emit a stable diagnostic summary: decision path, extractor tier, trust state, missing critical fields, failure taxonomy, evidence count, and review/publication impact. Do not build new product-plane workflow here.
**Verify:** focused tests prove manifest IDs are persisted/exported and diagnostics are stable enough for UI/API consumers without exposing internal selector state as the contract.

### Slice 1.5 — Ratchet contract ownership
**Status:** TODO
**Delete target:** compatibility shims kept only to support the pre-contract call shape.
**Files:** `tests/unit/test_extraction_architecture.py`, `tests/unit/test_final_architecture_ownership.py`, touched contract tests
**What:** Add ownership tests that enforce: acquisition is not imported by extraction contracts; persistence performs no extraction repair; publication remains projection-only; config remains in `app/core/config`; zero-record reasons are mandatory; ML/LLM output types are evidence-only.
**Verify:** architecture tests pass; ruff/mypy clean on touched files; Phase 1 net LOC is negative or the Notes section records the justified exception.

**Phase 1 exit gate:** Typed input/context/field/locale/manifest/failure contracts are green; every zero-record result carries a classified reason; diagnostics are business-readable; no ML, Sentinel, or LLM runtime path was added.

---

## PHASE 2 — Real compiled recipe fast path (detailed, executable)

> Rationale: learned templates must become a cheap deterministic fast path, not extra evidence appended after generic collectors already ran. This phase builds the compiler/runtime boundary and template isolation before any universal fallback or Sentinel.

### Slice 2.1 — Add structural template fingerprinting and match states
**Status:** TODO
**Delete target:** selector-only template identity and any duplicated template-shape logic left outside extraction memory.
**Files:** `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, `app/extraction/contracts.py`, `app/extraction/engine.py`, `app/core/config/extraction_semantic_surface.toml`, focused template-match tests
**What:** Represent structural templates with stable fingerprints, surface, market applicability, collision history, provisional/trusted/suspended states, and representative sample references. Fingerprints must weight structure/source shape over localized text or values.
**Verify:** focused tests prove localized text/value changes do not split a structural template, while record-boundary/source-shape changes can force provisional/template-mismatch state.

### Slice 2.2 — Define bounded recipe layers and compiler conflicts
**Status:** TODO
**Delete target:** mutable shared selector payloads and any uncompiled recipe fragments still consumed directly by runtime.
**Files:** `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, `app/core/config/extraction_memory.py`, new/existing recipe compiler module under `app/extraction/`, focused compiler tests
**What:** Model recipe layers by scope: platform base, domain, template, market/locale overlay, and constrained exception. Compile layers into one bounded runtime recipe with explicit field collectors, joins, exclusions, policy refs, provenance, version, and conflict rules. Ambiguous merges fail compilation.
**Verify:** compiler tests prove local fixes cannot mutate parent/base layers; ambiguous override fails closed; compiled recipe records provenance for each rule.

### Slice 2.3 — Implement the genuine known-template short-circuit
**Status:** TODO
**Delete target:** code paths where known-template recipe evidence is merely appended after all generic collectors run.
**Files:** `app/extraction/engine.py`, `app/extraction/adapters.py`, recipe runtime module under `app/extraction/`, `app/extraction/result_building.py`, focused fast-path tests
**What:** When a trusted compiled recipe applies, execute only recipe collectors, minimal evidence capture, canonicalization/resolution, validation, and publication projection. Generic structured/DOM collectors run only on recipe miss/fallthrough, critical warning, explicit manifest requirement, or later Sentinel sampling.
**Verify:** instrumentation-backed tests prove known-template success does not call all generic collectors and preserves published output/trust semantics.

### Slice 2.4 — Add replay, promotion, rollback, and template isolation
**Status:** TODO
**Delete target:** partial promotion paths that update recipe-like state without an atomic manifest.
**Files:** `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, Alembic migration if needed, `app/evaluation/`, focused persistence/replay tests
**What:** Promote compiled recipes only through immutable scoped manifests. Store replay results and rollback targets per template/market/contract. Activation must be atomic at manifest level and reversible without editing recipe history.
**Verify:** focused tests prove candidate manifest creation, activation, rollback, and replay isolation; failed replay leaves active manifest unchanged.

### Slice 2.5 — Add interim anti-brittleness for attribute spelling drift
**Status:** TODO
**Delete target:** exact-attribute-only repeated-block/card detection that caused the `test-data-id` vs `test-dataid` total-loss failure.
**Files:** generic collector/repeated-block modules identified by grep, `app/core/config/extraction_semantic_surface.toml`, focused synthetic mutation tests
**What:** Before the learned fallback exists, add deterministic attribute-name normalization/canonicalization, repeated-block candidate scoring, and DOM/source-shape matching that is not tied to one exact attribute spelling. Keep this as evidence generation, not publication authority.
**Verify:** synthetic mutation where only `test-data-id` changes to `test-dataid` yields candidate records through deterministic fallback or recipe fallthrough; final Phase-5 criterion remains owned by the learned fallback.

**Phase 2 exit gate:** A trusted learned template executes through compiled recipe fast path without all generic collectors; local fixes cannot mutate higher layers; ambiguous merges fail closed; manifest rollback is atomic; interim attribute-spelling mutation no longer causes total deterministic loss.

---

## PHASE 3 — Operator correction & grounded labels (detailed, executable)

> Rationale: operators should correct business meaning, not write selectors. This phase consolidates existing review/learning/selector paths into one label-producing correction path. Product/ops/governance beyond this extraction correction loop remains deferred.

### Slice 3.1 — Inventory and consolidate existing correction surfaces
**Status:** TODO
**Delete target:** duplicate selector-learning, review-promotion, and domain-memory correction screens/APIs that bypass grounded labels or the consolidated extraction-memory store.
**Files:** `app/api/*` routes identified by grep for selector/review/domain-memory learning, `app/crawl/review/*`, `app/core/records/selectors_runtime.py`, relevant frontend selector/domain-memory/review routes, focused API/frontend tests
**What:** Identify every operator correction entry point and choose one authoritative correction API that writes grounded labels. Keep read-only compatibility only where required for existing pages during the slice; schedule deletion in the same phase.
**Verify:** grep inventory recorded in Notes; focused tests prove the chosen API path writes extraction-memory labels and legacy mutation paths no longer promote selectors directly.

### Slice 3.2 — Implement grounded correction payloads
**Status:** TODO
**Delete target:** correction payloads that contain only field/value text with no node/path/region/absence grounding.
**Files:** `app/evaluation/schema.py`, `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, chosen correction API, frontend correction types/components, focused schema/API tests
**What:** Support labels for correct value, wrong value, explicit absence, primary region, recommendation/exclusion region, repeated-record boundary, semantic role, locale interpretation, and variant/job relationship. Labels must reference node/path/region or explicit absence and carry operator/review provenance.
**Verify:** focused tests reject text-only labels for release truth; API tests prove all accepted corrections create grounded labels.

### Slice 3.3 — Replay corrections against representative siblings
**Status:** TODO
**Delete target:** one-page correction paths that activate without representative replay.
**Files:** `app/evaluation/`, `app/persistence/extraction_memory.py`, recipe compiler/runtime modules, chosen correction API, focused replay tests
**What:** Convert accepted labels into candidate recipe proposals, compile them, replay against representative siblings/current samples, and report precision/recall/trust deltas before activation. Generalization must be proven by sibling coverage, not one corrected page.
**Verify:** focused tests prove a correction can generalize to siblings and a one-page-only unsafe correction remains inactive.

### Slice 3.4 — Add activation gates for human-led corrections
**Status:** TODO
**Delete target:** direct correction-to-active-template writes.
**Files:** `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, correction API, manifest activation code from Phase 2, focused activation tests
**What:** Require compile success, representative replay pass, conflict-free layer merge, policy validation, and explicit activation decision before a correction affects production extraction. Store rejected proposals as learning/evaluation data, not runtime behavior.
**Verify:** focused tests prove failed gates do not change active manifest; accepted correction activates through manifest only.

### Slice 3.5 — Delete duplicate correction UI/API paths
**Status:** TODO
**Delete target:** legacy selector/domain-memory/review-promotion UI/API paths superseded by the grounded correction path.
**Files:** frontend selector/domain-memory/review routes from Slice 3.1 inventory, backend APIs from Slice 3.1 inventory, tests updated or deleted with the removed paths
**What:** Remove the duplicate screens/routes/API handlers after the single correction flow is green. Keep the deferred product/ops plan as the owner for broader queues/dashboards/governance; this slice only removes extraction-correction duplication.
**Verify:** focused backend API tests, `vp test <changed frontend test paths>`, `vp check --fix`, `vp build`; grep proves deleted mutation endpoints/components have no live references.

**Phase 3 exit gate:** A non-specialist can correct template extraction without authoring selectors; corrections produce grounded labels; replay gates activation; duplicate correction paths are deleted or explicitly out of extraction scope.

---

## PHASE 4 — Universal extractor research & evaluation (offline only)

> Rationale: do not build model serving until evidence proves a universal extractor beats the frozen deterministic baseline on the right partitions without increasing ungrounded output.

### Slice 4.1 — Build compact page representation offline
**Status:** TODO
**Delete target:** any research prototype that consumes full raw HTML when a bounded representation is sufficient.
**Files:** `app/evaluation/`, possible representation module under `app/extraction/` only if needed by later runtime, `app/core/config/*` for bounds, focused representation tests
**What:** Create a bounded representation containing relevant nodes, selected attributes, source lineage, repeated-block membership, labels, optional region references, and market-sensitive features. Keep it lazy/offline in this phase.
**Verify:** tests prove representation is bounded, excludes irrelevant bulk, carries node/path/region references, and is not built on normal extraction success paths.

### Slice 4.2 — Partition evaluation data for known/unseen/temporal cases
**Status:** TODO
**Delete target:** aggregate-only model evaluation that hides unseen-template or critical-semantic regressions.
**Files:** `app/evaluation/schema.py`, `app/evaluation/`, baseline artifacts/config, focused evaluation tests
**What:** Define dataset partitions for known templates, unseen domains, unseen templates in known domains, temporal changes, A/B variants, locale variants, listings/details, multi-variant products, jobs, and Sentinel-disagreement seeds. Only grounded human labels and qualified pseudo-labels can enter release evaluation.
**Verify:** tests prove weak/model-only labels are excluded and partition metrics fail closed when required partitions are missing.

### Slice 4.3 — Add offline universal-model adapter harness
**Status:** TODO
**Delete target:** one-off notebooks/scripts that cannot reproduce model evaluation.
**Files:** `app/evaluation/`, optional `scripts/` evaluation entrypoint, model config under `app/core/config/*`, focused adapter tests
**What:** Implement an offline adapter interface for candidate models that predicts page type, record boundaries, field-bearing nodes/paths, exclusion regions, and basic relationships. Outputs are evidence predictions only. No production serving infrastructure.
**Verify:** focused tests run a deterministic fake adapter through the harness and prove outputs cannot become public records directly.

### Slice 4.4 — Benchmark against the Phase-0 deterministic baseline
**Status:** TODO
**Delete target:** model-selection decisions based on anecdotes or overall accuracy only.
**Files:** `app/evaluation/`, `app/evaluation/baselines/run_1.json`, benchmark report artifact under `app/evaluation/` or `docs/` as appropriate, focused metric tests
**What:** Compare candidate models on field precision/recall/F1, normalized exact match, record-boundary accuracy, variant binding, recommendation contamination, ungrounded-value rate, latency, memory, and cost per 1,000 pages. Compare local/shared inference from measured data only.
**Verify:** benchmark command produces stable report; release gate fails if unseen-template gains are absent or ungrounded-value rate rises.

### Slice 4.5 — Record go/no-go and serving decision
**Status:** TODO
**Delete target:** production model wiring before benchmark approval.
**Files:** this plan Notes, benchmark artifact, `docs/CODEBASE_MAP.md` only if new evaluation modules landed
**What:** Record the selected model family/deployment mode or explicitly reject runtime ML for now. If rejected, Phase 5 is blocked or reduced to deterministic fallback improvements.
**Verify:** plan Notes contain benchmark summary, go/no-go, and serving decision; no production runtime code invokes the candidate model.

**Phase 4 exit gate:** Offline model is proven to beat deterministic generic extraction on unseen templates without increasing ungrounded-value rate, or Phase 5 is blocked/re-scoped; no production serving infra exists before the gate.

---

## PHASE 5 — Runtime ML fallback (evaluation-gated)

> Rationale: the model is a lazy fallback that emits evidence. It is not the primary extractor and cannot publish values.

### Slice 5.1 — Add model artifact and runtime contract
**Status:** TODO
**Delete target:** hard-coded model paths, thresholds, endpoints, and runtime flags outside config.
**Files:** `app/core/config/*`, `app/extraction/contracts.py`, `app/evaluation/` model metadata, focused config/contract tests
**What:** Define model artifact identity, version, thresholds, deployment mode, memory/cost bounds, timeout behavior, and evidence-only output contract. Runtime must record model identity in evidence and diagnostics.
**Verify:** tests prove missing/unapproved artifact disables fallback cleanly; config is not embedded in extraction service code.

### Slice 5.2 — Wire lazy Stage-4 fallback into extraction engine
**Status:** TODO
**Delete target:** fallback paths that re-run expensive representation/model work after deterministic success.
**Files:** `app/extraction/engine.py`, representation module, model adapter module, `app/extraction/result_building.py`, focused fallback tests
**What:** Invoke the universal model only when compiled recipe and generic deterministic paths fail to satisfy the field contract, or when explicitly selected by later Sentinel sampling. Convert predictions to grounded evidence candidates; resolve/publication remains deterministic.
**Verify:** focused tests prove success path never invokes model/representation; failure path emits evidence and diagnostics; model predictions cannot bypass `resolution.py`.

### Slice 5.3 — Add serving only if Phase-4 decision requires it
**Status:** TODO
**Delete target:** unused local/shared serving scaffolding not selected by benchmark.
**Files:** serving adapter files only as selected in Phase 4, `app/core/config/*`, focused service-failure tests
**What:** Implement the minimal selected inference path: local process, shared service, or no serving. Include timeout, degraded-mode, and model-service-failure taxonomy. Do not duplicate model memory across workers unless the benchmark requires local inference.
**Verify:** focused tests cover timeout/degraded behavior and `model_service_failure` classification without publishing unsafe values.

### Slice 5.4 — Prove the attribute-spelling mutation recovers records
**Status:** TODO
**Delete target:** brittle fixture assumptions that hide the original `test-data-id` / `test-dataid` failure.
**Files:** focused synthetic mutation tests, `app/evaluation/`, relevant extractor/model adapter tests
**What:** Add the explicit mutation acceptance test: same page evidence, only attribute spelling drifted. The learned fallback must produce grounded record-boundary/field evidence and final records through deterministic resolve/trust gates.
**Verify:** synthetic mutation test yields records; evidence references the mutated source; no ungrounded fields are published.

### Slice 5.5 — Add invocation, latency, grounding, and cost gates
**Status:** TODO
**Delete target:** model fallback that can silently become the default hot path.
**Files:** `app/observability/diagnose.py`, `app/evaluation/`, architecture tests, focused metric tests
**What:** Track universal representation build rate, model invocation rate, p50/p95 latency, model-service failure rate, ungrounded-value rejection rate, and cost per 1,000 pages. Add ratchets that keep fallback lazy.
**Verify:** focused tests prove invocation metrics are emitted and success-path invocation remains zero for known-template/generic-success fixtures.

**Phase 5 exit gate:** Success path never invokes the model; runtime ML fallback is evidence-only; the attribute-spelling mutation yields records; accuracy/latency/grounding/cost gates pass.

---

## PHASE 6 — Sentinel / anti-drift (detailed, executable)

> Rationale: Sentinel is a challenger, not ground truth. Start with deterministic challenger behavior because Phase 2 provides a real recipe fast path; add ML challenger only after Phase 5 is safe.

### Slice 6.1 — Add deterministic challenger sampling
**Status:** TODO
**Delete target:** recipe trust assumptions with no independent comparison path.
**Files:** `app/extraction/engine.py`, `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, `app/core/config/*`, focused Sentinel tests
**What:** For sampled known-template executions, compare compiled recipe output against the full generic deterministic path. Store observations with manifest/template IDs, recipe result, challenger result, and evidence references.
**Verify:** tests prove sampled recipe success invokes challenger after publication decision capture without letting challenger override the recipe.

### Slice 6.2 — Implement semantic comparison and drift states
**Status:** TODO
**Delete target:** raw value-diff drift alerts that ignore semantic role/entity ownership.
**Files:** Sentinel comparison module, `app/models/extraction_memory.py`, `app/observability/diagnose.py`, focused comparison tests
**What:** Compare record count, identity, field value, normalized value, semantic role, entity ownership, locale interpretation, variant binding, and recommendation contamination. Classify observations as concordant, benign difference, needs review, suspected drift, or critical drift.
**Verify:** tests prove recommendation-price vs primary-price disagreement is critical even if value parses; harmless formatting-only differences are not critical.

### Slice 6.3 — Add cautious suspension and fallback routing
**Status:** TODO
**Delete target:** silent recipe continuation after confirmed critical drift.
**Files:** `app/persistence/extraction_memory.py`, `app/extraction/engine.py`, `app/core/config/*`, focused suspension tests
**What:** After configured confirmed critical drift, suspend the affected scoped manifest/template and route future traffic to generic/fallback extraction. Suspension must be reversible and auditable. Sentinel still cannot replace individual values silently.
**Verify:** tests prove confirmed critical drift suspends to fallback; unconfirmed challenger disagreement creates review/observation only; rollback restores prior manifest state when approved.

### Slice 6.4 — Add ML challenger after Phase 5
**Status:** TODO
**Delete target:** duplicate challenger code paths for deterministic and ML challengers.
**Files:** model fallback adapter from Phase 5, Sentinel comparison module, config, focused challenger tests
**What:** Reuse the evidence-only ML fallback as an optional challenger on sampled known-template traffic. Feed the same semantic comparator and observation store.
**Verify:** tests prove deterministic and ML challengers share comparison/suspension policy; ML challenger output cannot override recipe values.

### Slice 6.5 — Emit drift diagnostics for deferred product plane
**Status:** TODO
**Delete target:** product-facing drift blobs that require reading internal extractor traces.
**Files:** `app/observability/diagnose.py`, API/export serializers as needed, focused diagnostic tests
**What:** Emit business-readable drift diagnostics: affected template/market, sample rate, concordance trend, critical disagreement class, publication impact, suspension state, and next action. Do not build the full product dashboard in this plan.
**Verify:** focused API/diagnostic tests prove stable fields for future product/ops UI.

**Phase 6 exit gate:** Challenger cannot silently override recipes; confirmed critical drift auto-suspends scoped recipe to fallback; observations and diagnostics are persisted and business-readable.

---

## PHASE 7 — Grounded LLM repair (detailed, executable)

> Rationale: LLM returns only grounded proposals and evidence adjudication. It must not reintroduce the direct extraction tasks deleted in Phase 0.

### Slice 7.1 — Sweep and delete/consolidate remaining legacy LLM extraction surfaces
**Status:** TODO
**Delete target:** any remaining direct standard-field LLM extraction, prompt, task, API, or frontend surface that can emit final records or bypass evidence/resolution.
**Files:** `app/connectors/llm/*`, `app/core/config/field_mappings.py`, frontend admin/task surfaces, focused LLM/config tests
**What:** Re-run the Phase-0 grep sweep before adding grounded repair. Preserve live non-extraction LLM tasks such as enrichment/product-intelligence where they are outside this plan. Delete or consolidate any standard-field extraction remnants.
**Verify:** grep proves no direct standard-field LLM extraction tasks/prompts remain; focused LLM runtime/config tests pass.

### Slice 7.2 — Add grounded rule-proposal contract
**Status:** TODO
**Delete target:** free-form LLM selector/rule output with no evidence references.
**Files:** `app/connectors/llm/*`, `app/extraction/contracts.py`, recipe compiler module, `app/core/config/*`, focused contract tests
**What:** Define LLM input as target schema + compact representation + bounded structured objects + existing evidence + operator labels. Output may propose locator/path, boundary, exclusion, source-preference, semantic-role, entity-join, locale-policy, or recipe-layer diff. Every proposal must reference node/path/region/evidence and uncertainty reason.
**Verify:** tests reject ungrounded proposals and prove proposals cannot activate without compiler/replay gates.

### Slice 7.3 — Add evidence adjudication, not direct field publication
**Status:** TODO
**Delete target:** LLM-produced standard field values that skip deterministic resolve/trust.
**Files:** grounded LLM adapter, `app/extraction/result_building.py`, `app/extraction/resolution.py`, focused adjudication tests
**What:** Use LLM only to adjudicate ambiguous evidence candidates or propose repair diffs. Standard fields still publish only through grounded evidence, deterministic canonicalization, semantic resolution, validation, and trust gates.
**Verify:** tests prove an LLM answer with a plausible value but no accepted evidence is rejected; accepted adjudication still passes `resolution.py`.

### Slice 7.4 — Support typed custom fields under grounding rules
**Status:** TODO
**Delete target:** custom-field extraction as untyped arbitrary strings.
**Files:** field/custom contract config, grounded LLM adapter, evaluation schema, focused custom-field tests
**What:** Allow custom fields only when they declare type (`string`, `list`, `number`, `money`, `date`, `boolean`, `enum`, `key-value`, `structured object`), cardinality, grounding requirement, validation, and publish policy. Model output remains evidence until validated.
**Verify:** tests prove undeclared custom fields are rejected; typed grounded custom fields can be retained/published according to policy.

### Slice 7.5 — Gate LLM repair through compile, replay, and activation
**Status:** TODO
**Delete target:** LLM repair paths that mutate active recipes directly.
**Files:** recipe compiler/runtime modules, `app/persistence/extraction_memory.py`, grounded LLM adapter, evaluation/replay modules, focused repair lifecycle tests
**What:** Route LLM proposals through the same deterministic compiler, replay, representative validation, activation, and rollback gates as operator corrections. Retain rejected proposals as evidence/training data only.
**Verify:** focused tests prove LLM cannot publish ungrounded values or activate a rule; failed compile/replay leaves active manifest unchanged.

**Phase 7 exit gate:** LLM cannot publish ungrounded standard values, cannot activate rules, and cannot run in the hot path; legacy direct-extraction tasks remain deleted; grounded repair proposals pass the same compile/replay/activation gates as human corrections.

---

## Debt-deletion ledger (enforced every phase)

Maintained in Notes and asserted at each phase gate:
- Every slice names a **Delete target** (or is explicitly measurement-only).
- Every phase must end with **net-negative LOC** across app + tests, or justify the exception in writing.
- Track running totals: physical LOC removed (app), test LOC removed, stores retired, dead functions removed, screens/APIs/tables retired.

**Phase 0 running totals (updated per slice):**
| Slice | App code deleted | Test code deleted | Notable removals |
|---|---|---|---|
| 0.3 | 3 dead LLM wrappers + payload adapters/types + emptied `PROMPT_REGISTRY` | re-pointed runtime/config tests (net −) | 6 prompt files; `direct_record_extraction`/`missing_field_extraction`/`field_cleanup_review` |
| 0.1 | +`app/evaluation/` harness (measurement-only; offset by 0.3) | +baseline test | frozen baseline artifact `app/evaluation/baselines/run_1.json` |
| 0.4 | dead `field_repair`/`self_heal` conduits (persistence + export projection) + harness repair-diagnostic gate | 2 harness repair-diagnostic tests | producer-less repair scaffolding; +1 ratchet sweep test |
| 0.2 | +versioned evaluation/grounded-label schema | +12 schema contract tests | release truth rejects weak, model-only, and unqualified pseudo-labels |
| 0.5 | no app deletion | canonical AST LOC helpers removed from two gates | physical LOC + Radon complexity now honest |
| 0.6 | none | mega-suite split; 298 tests preserved | nine owner-focused suites, max 1,384 lines |
| 0.7 | generic KG models/repository/projector/config; duplicate selector/review/feedback models | generic graph/projection suites replaced by focused extraction-memory coverage | 6 generic KG tables + 3 parallel stores retired; app physical LOC −1,223 from Slice 0.5 baseline |

---

## Acceptance Criteria (engine scope; testable)

**Anti-brittleness**
- [ ] A template differing only by attribute spelling (`test-data-id` vs `test-dataid`) still yields records (proven by synthetic mutation) — met in Phase 5 via the learned fallback, with an interim Phase-2 mitigation (attribute-name canonicalization + repeated-block detection + candidate scoring not tied to one exact attribute).
- [ ] Present-but-unbound variant evidence is recovered **only** through a grounded path, and the plan distinguishes: **binding failure** (matrix exists, linking failed → recover), **source insufficiency** (only option axes, no combination proof → do not fabricate), **operator-authored mapping** (human-confirmed), **unsupported** (no grounded relationship → no variant). "Model predicted a relationship" is **not** sufficient evidence to publish a variant.
- [x] `test_extraction_carries_no_retailer_domain_literals` stays green.

**Foundation / debt**
- [x] One authoritative extraction-memory store; the other four dispositioned.
- [x] Dead LLM extraction tasks and post-extraction repair removed.
- [x] LOC gate measures physical lines; extraction app + test LOC net-decrease through Phase 0.
- [x] Frozen deterministic baseline exists and is the regression reference.
- [x] Release evaluation truth is versioned, grounded, and excludes weak/model-only labels.

**Correctness / governance (later phases)**
- [ ] Every zero-record outcome carries a classified reason (Phase 1).
- [ ] A learned template short-circuits generic collectors via a compiled recipe (Phase 2).
- [ ] No universal model reaches production before it beats the deterministic baseline on unseen templates without raising ungrounded-value rate (Phase 4→5).
- [ ] No Sentinel before a genuine recipe fast path exists (Phase 6).
- [ ] Grounded models cannot publish ungrounded values or activate rules (Phase 7).

**Per-slice gates:** focused backend `pytest` target + `ruff`/`mypy` on touched files (INVARIANTS §14). Frontend slices: `vp test <path>`, `vp check --fix`, `vp build`. No broad `pytest tests -q`, smoke, or corpus gate unless explicitly requested.

---

## Do Not Touch
- `app/acquisition/*` and browser runtime (Bucket 3) — acquisition is the strength; extraction starts from the input bundle.
- User-selected controls: `surface`, traversal, `proxy_list`, `llm_enabled`.
- The deferred product/operations/governance plane — belongs to `CrawlerAI_Deferred_Product_Operations_Architecture.md`, not this plan.
- Neo4j / Apache AGE / graph analytics; pgvector as an active dependency (deferred/candidate-only).
- Product Intelligence deterministic identity ladder (cross-domain matching is deferred).

---

## Doc Updates Required
- [x] `docs/INVARIANTS.md` — supersede the KG greenfield/no-backfill invariant (D4); record single-authoritative-store, ML-as-evaluated-fallback-only, challenger-cannot-override, grounded-publication.
- [x] `docs/CODEBASE_MAP.md` — `app/evaluation/`; store consolidation; corrected owners.
- [x] `docs/ENGINEERING_STRATEGY.md` — "overlapping recipe stores", "mega test suite", and "misleading canonical-LOC ratchet" anti-patterns.
- [x] `docs/plans/ACTIVE.md` — this plan is authoritative; prior extraction plans retired (not referenced).

---

## Notes
- 2026-07-02: Rewritten after the ML-first draft was rejected. Corrections adopted: sequence is quick-wins/clean-foundation first (not ML-first); ML is offline-research until an evaluation gate passes, then a lazy runtime fallback; Sentinel follows a real recipe fast path; evaluation + grounded-label schema precede any model; the five overlapping stores are consolidated before any new store; the `ast.unparse` LOC ratchet is replaced with physical LOC; debt deletion is a per-phase requirement, not a slogan.
- All file references verified against the live tree (extraction package, `connectors/llm/*`, `models/*`, `core/records|shared/*`, `tests/unit/test_extraction_architecture.py`). The prior draft's paths (`structured_sources.py`, `app/llm/*`, `app/extraction/dom/*`, `shared/field_coerce` under extraction) were fabricated and are corrected here.
- The two previously-queued extraction plans are **retired and intentionally not referenced** per operator direction.
- Product/ops/governance concerns are deferred to `CrawlerAI_Deferred_Product_Operations_Architecture.md` and explicitly out of scope.
- D1–D4 approved and executed in Slice 0.7. Slice 0.2 completed afterward; Phase 0 exit gate is met with app physical LOC net −905 from the Slice 0.5 physical baseline.
- 2026-07-02: Expanded Phases 1–7 in this plan itself into decision-complete slices with file targets, delete targets, and verify gates. No Phase 1 implementation started in this edit.
