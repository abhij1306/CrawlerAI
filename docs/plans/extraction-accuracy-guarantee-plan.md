# Extraction Accuracy & Normalization — Guarantee-Backed Plan

## Context

This finishes the **Extraction Accuracy Overhaul** (original plan: `docs/plans/extraction-overhaul.md`). Slices A1, A4, A5, B1–B4 shipped and the suite is green (backend 1206 unit/component + ruff clean; frontend 136 green). The two **accuracy levers** — **A2 (resolution as the sole semantic owner)** and **A3 (grounded LLM fallback)** — were deferred last session as "too risky to land blind." The user rejected that deferral and rejected the 90-URL audit corpus as the validation target, asking two questions that reframe the whole effort:

1. **"What is the guarantee that this will work?"**
2. **"How do we know we are not missing data from any site?"**

The answer to both is **not a sample of URLs** — it is **three architectural invariants made executable**, so correctness is a property of the pipeline rather than of a corpus:

- **RECALL** — collection never *silently* drops a recognized shape. A field is "missing" only via a **recorded selection decision**, never a silent collection gap. *(Answers Q2.)*
- **PRECISION / OWNERSHIP** — resolution is the **sole semantic owner**; the firewall rejects anything not traceable to a real collected candidate. *(The A2 lever.)*
- **EXPLAINABILITY** — for **any** URL/field the system answers exactly one of: *published* / *rejected-with-reason* / *no-candidate-collected*. This is the **guarantee mechanism** — it makes both other invariants checkable per field, on every page, with no sample. *(Answers Q1.)*

These are verifiable by **synthetic shape-fixtures + property tests**, not a fixed URL list. The plan sequences: **explainability backbone first** (so every later change is observable), then **A2**, then **recall closure**, then **A3**, then **CodeRabbit issues + docs**.

### Standing constraints (still in force)
- **Greenfield** — do NOT commit; the user runs CodeRabbit at the end.
- **Stay generic** — no site-specific adapters or retailer-domain literals (enforced by `test_extraction_carries_no_retailer_domain_literals`, which scans `app/extraction/` only). Every rule keys on evidence *shape*.
- **LLM (A3) may only choose among collected candidates** / enum classifications — it may NEVER invent a value.
- **LLM trust model = auto-replay, flag for review** — an `llm_proposed` source replays automatically on the next same-template page but is surfaced in the KG for operator review; operator always wins.
- **24-file extraction ceiling** (`test_extraction_architecture.py`): `app/extraction/` is at EXACTLY 24 files, ≤5500 canonical lines, ≤400 lines/file, ≤60 lines/function. **New extraction modules break it.** → place the divergence guard in `app/core/records/` (outside the ceiling); place A3 orchestration in the async stage `app/crawl/pipeline/` (outside the ceiling); only bump the ceiling constant if genuinely forced.
- Backend test cmd (from `backend/`): `PYTHONPATH=. ./.venv/Scripts/python.exe -m pytest tests -m "unit or component" -q`; lint `./.venv/Scripts/python.exe -m ruff check .`. Frontend (from `frontend/`): `npm run check && npm run check:policy && npm run test`.

---

## Phase 0 — Explainability backbone (the guarantee mechanism)

**Goal:** make every public field answer *published / rejected-with-reason / no-candidate*. Build this first so Phases 1–3 are observable as they land.

### 0.1 Decision-derived field states (fix the misattribution)
`app/extraction/result_building.py::field_evidence_states` (lines 36–147) currently computes each field's `FieldEvidenceState` from `record.get(field)` (line ~96), **after** materialization/output-safety have already stripped values. So a field stripped by a downstream guard is mislabeled `not_present_in_captured_sources` ("no candidate") instead of `captured_but_rejected` ("rejected"), and the **actual rejection reason is lost**.

- Recompute `FieldEvidenceState` from the **resolution decision graph** (`ResolutionResult.decisions` + `unresolved_fact_types` + `blocking_finding_ids`), not from the final record dict. The 5-state machine already exists in `contracts.py:314` (`captured_and_resolved` / `captured_but_rejected` / `captured_conflicting` / `source_unavailable` / `not_present_in_captured_sources`) — feed it from decisions so the distinction is authoritative.
- Carry `RejectedEvidence.reason` (and the `_invalid()` flag reason from `resolution.py:652-693` — `INVALID_AVAILABILITY_EVIDENCE_FLAG`, `invalid_currency`, `invalid_decimal`, …) into the `captured_but_rejected` branch. Today `_resolve_scalar` (`resolution.py:546-610`) only emits `stable_tiebreak`/`lower_confidence`/`blocked_by_finding`/`invalid_value` and the specific `_invalid()` reason is dropped — thread it through so diagnose.json shows *why*.

### 0.2 Divergence guard (precision backstop, outside the 24-file ceiling)
New `app/core/records/divergence.py::assert_public_matches_resolution(data, lineage, resolution)`: **every public scalar must equal an accepted Decision value or a lineage-reachable `DerivedFact`**; anything else emits a non-blocking `Finding` (visible in diagnose.json). This is what makes "the public record never diverges from resolution" an *enforced* property rather than a hope.

- Wire it **observationally (non-blocking Findings only)** at the persistence boundary (`app/crawl/pipeline/persistence.py`, where public data is built per record). Prove the full suite stays green with the guard emitting zero Findings on existing fixtures *before* relying on it to catch A2 regressions.

### 0.3 Tests
`tests/unit/test_field_state_provenance.py` (new): stripped-downstream field → `captured_but_rejected` **with reason**, not `not_present`; no-candidate field → `not_present_in_captured_sources`; published field → `captured_and_resolved`. `tests/unit/test_divergence_guard.py` (new): a synthetic public value with no backing decision emits a Finding; a fully-lineage-backed record emits none.

**Exit criterion:** for every field in every existing fixture, diagnose.json answers exactly one of the three states, and the divergence guard emits zero Findings on the green suite.

---

## Phase 1 — A2: Resolution as the sole semantic owner (precision)

**Goal:** all semantic decisions live in `resolution.py`; `materialization.py` becomes serialize-only; the firewall enforces keys/types/enums only. The divergence guard from Phase 0 is the safety net that makes this landable without a URL corpus.

### 1.1 `_rank` value-quality term + tuple reorder (the phantom-DOM bug)
`resolution.py::_rank` (lines 703–764). Today the generic fall-through (line 764) is `(0, directness, reliability, -confidence, evidence_id)` — **directness outranks reliability**, so a `direct` DOM `[data-price]` `(0,0,5)` beats an `embedded` JSON-LD offer `(0,1,0)`. That is the phantom-price / phantom-DOM bug.

- Add a generic `_value_quality(ev)` term (lower = better) computed **from evidence shape only**: enum validity (availability enum, ISO-4217 currency), format plausibility (positive `Decimal` price, GTIN check digit, URL grammar), pollution flags (`code_only_title`, etc.).
- Reorder the generic tuple to **`(value_quality, reliability, directness, -confidence, evidence_id)`** so source reliability beats directness.
- Fold the special-cased title/brand/currency/description tuples (lines 715–763) onto the shared `value_quality` prefix so all fields share one ranking spine.

### 1.2 Move derivation + asset selection INTO resolution
Extend the existing `_derived` path (`resolution.py:613-649`) so these become `DerivedFact`s with `input_evidence_ids` + `rule_id` (today they live **outside** resolution in `materialization.py` and `output_safety.py`, which is exactly why the public record diverges):
- From `materialization.py`: `_cohere_parent_offer` (172-247, uniform/min/max price aggregation), SKU drop on collision (187-189), `_drop_conflicting_variant_prices` (249-281), `_reconcile_near_equal_price` (284-319), `_cohere_parent_availability` (345-376), variant offer-field drop (630-640).
- From `output_safety.py`: asset primary/dedup/conflict selection (`materialize_product_assets` 34-109, `_enforce_atomic_price_currency` 216-235) → move into resolution's `AssetDecision` path.

### 1.3 Materialize = serialize-only; firewall = enforce-only
`materialization.py::materialize` writes values + lineage only (no aggregation/SKU-drop/range/asset-selection). `public_record_firewall.py` keeps keys/types/enums/URL canonicalization only. `output_safety.py` retains only the atomic price+currency *enum-layer* check (moved per A4) — no semantic ownership.

### 1.4 Tests
`tests/unit/test_resolution_ranking.py`: JSON-LD offer beats phantom DOM `[data-price]`; enum-invalid availability loses to enum-valid; brand/title quality ranking preserved. `tests/component/test_materialize_is_serialize_only.py`: materialization performs no aggregation (a record with conflicting variant prices is resolved *before* materialize, not inside it). Plus the Phase-0 divergence guard must stay at zero Findings.

---

## Phase 2 — Recall: close the silent-collection holes (no missed data)

**Goal:** every recognized shape is either collected or recorded as a *decision* to skip — never silently dropped. This is the executable answer to "how do we know we aren't missing data from any site." Folds in the overlapping CodeRabbit findings (2, 3, 6, 7).

### 2.1 Path containment recognizes all separator forms (CodeRabbit #3 — VALID)
`js_state_scope.py::path_is_within_selected_root` (256-266) admits only `/` descendants, but `_path_is_descendant` elsewhere accepts `.`, `[`, and `/`. Roots like `foo.bar` / `foo[0]` lose their legitimate children. Align `path_is_within_selected_root` to the same descendant rules (normalize across `.`/`[`/`/`), preserving fail-closed behavior. → recovers structured candidates currently dropped under selected roots.

### 2.2 Unresolved-root policy (CodeRabbit #2 — judgment, verify first)
`js_state_scope.py::root_admits_path` (269-285) returns `True` for `unresolved` (fail-open, by deliberate A1 design — defers to per-row guards). Decision: **keep the fail-open deferral only if the per-row conflict guards are provably sufficient**; if Phase-0 field states show unresolved-root pages leaking sibling/recommendation evidence, tighten `unresolved` to admit nothing (like `ambiguous`) and rely on recorded rejections instead. Verify against current per-row guards before changing.

### 2.3 DOM `<picture>` candidate collapse (CodeRabbit #6 — VALID, verify)
`collectors/dom.py` (~206-212): the fail-closed `len(candidates)` gate counts raw DOM matches, so a single responsive `<picture>` hero (its `source[srcset]` + `img[src]`) reads as multiple candidates and gets rejected. Collapse candidates by enclosing `<picture>` / resolved asset identity **before** the gate. Keep fail-closed for true multi-image galleries.

### 2.4 JSON-LD standalone-variant scoping (CodeRabbit #7 — VALID, verify)
`collectors/jsonld.py` (~44-48): a standalone variant can bypass root scoping. Emit a variant only when the variant itself **or** its `isVariantOf` target matches the selected root / page URL; otherwise skip when no page product root was identified. Use existing `select_product_roots`, `root_admits_path`, `_is_standalone_variant`.

### 2.5 Field-map collection gaps + replace silent drops
- Close field-map gaps so recognized shapes are collected: `gtin`/`mpn`/`seller`/`category` in JS-state / network / microdata / OpenGraph collectors; container-scoped microdata `itemprop`; availability in OpenGraph; `priceCurrency` camelCase. (These are the A4 "remainder" carried forward.)
- Replace silent `if not value: continue` collection drops with **recorded rejections** (a `FieldEvidenceState` / `RejectedEvidence` with a reason), so Phase-0 diagnose.json proves nothing was dropped silently.

### 2.6 Tests
`tests/unit/test_collector_recall.py` (new): a synthetic page carrying gtin/mpn/seller/category in each source shape yields a collected candidate **or** a recorded rejection for each — never a silent gap. Plus existing `test_collector_root_scoping.py` extended for dot/bracket roots and `<picture>` collapse.

---

## Phase 3 — A3: Grounded LLM fallback resolver (the accuracy lever)

**Goal:** for fields still missing/low-confidence after deterministic resolve, an LLM **chooses among collected candidates** (or classifies an enum/role) — never invents — and its choice persists as an `llm_proposed` contract that **auto-replays** on same-template pages (flagged for operator review).

### 3.1 Async orchestration in the pipeline stage (outside the 24-file ceiling)
Inject at `app/crawl/pipeline/record_extraction_stage.py:136`, immediately **after** `await asyncio.to_thread(extract_records_impl, ...)` — it already has `session`, `run.id`, `domain`, `result.evidence`, `result.decisions`, `result.contract_outcomes`. Call only for fields in `unresolved_fact_types` or whose decision is low-confidence/review (brand role ambiguity, code-only/slug title, no-variant, missing offer). Clean PDPs never call it.

### 3.2 Reuse the LLM connector — do NOT rebuild
- Entrypoint `app/connectors/llm/tasks.py:41::run_prompt_task(session, *, task_type, run_id, domain, variables, …)` — already composes cache + budget + circuit-breaker + cost-log + pydantic validation; returns `LLMTaskResult`.
- Register a new `grounded_fallback_resolver` `task_type` in `payloads.py` (`_PAYLOAD_ADAPTERS` at line 147, `validate_task_payload` at 170), modeled on the existing grounded `_FieldCleanupReviewPayload` (line 66). **Schema is enum-only / evidence_id-only**: the model returns an existing `evidence_id` to accept, OR an enum/role classification over existing candidates, OR `abstain`. Validation rejects anything else → field stays unresolved. The firewall + Phase-0 divergence guard are the backstop.

### 3.3 Output wiring + auto-replay-with-review
- Produce a `Decision` whose accepted evidence is the LLM-chosen candidate, `rule_id="llm_fallback"`, recording model id + rationale; emit an `llm_proposed` `ContractOutcome` (so it appears in diagnose.json and is ingested by the projector, B3).
- **Flip selection priority** for auto-replay: `app/core/knowledge_graph/contract_runtime.py:268::_selection_priority` currently `{"llm_proposed": 0, "generic": 1, "operator": 2}` makes `llm_proposed` **inert** (loses to generic). Change to `{"generic": 0, "llm_proposed": 1, "operator": 2}` so `llm_proposed` beats generic but loses to operator. Update the comment at `app/core/config/knowledge_graph.py:92` ("always inert until an operator promotes it" is no longer true).

### 3.4 Tests (mocked — no live LLM)
Mock via `monkeypatch.setattr("app.connectors.llm.tasks.<symbol>", fake)` (pattern: `tests/regression/test_llm_runtime.py:121`). Assert: LLM never publishes a value absent from candidates; LLM-chosen source becomes an `llm_proposed` contract; a second same-template page resolves via the persisted contract with **no** LLM call; circuit-open / abstain falls back deterministically (never blocks a crawl). Origin-carry pattern: `tests/component/test_projection.py:793`.

---

## Phase 4 — CodeRabbit issues + final docs update

Source: `coderabbit.md` (repo root, 16 findings). Rule for each: **verify against current code; fix only still-valid; skip the rest with a one-line reason.** Several overlap earlier phases and are handled there (note where).

### 4.1 Folded into earlier phases (verify, then fix in place)
- **#1 variant float-width** (`variant_policy.py:454-460`) — **VALID**: `width.isdigit()` rejects `"800.0"`, so a `{variant_id, width:"800.0"}` echo slips through as sellable via the `variant_id` transport field. Normalize/parse width (float-aware) before the min-px check; still reject non-numeric/mixed-field rows. *(Touches the A5 variant gate — do it with Phase 1/2.)*
- **#3 path containment** — done in **2.1**.
- **#2 unresolved fail-open** — addressed in **2.2**.
- **#6 `<picture>` collapse** — done in **2.3**.
- **#7 JSON-LD standalone variant** — done in **2.4**.
- **#4 Croatia `hr→EUR`** (`currency_hints.py:44-63`) — **VALID**: add `"hr": "EUR"` to the eurozone block. *(Do with Phase 2.5 currency work.)*

### 4.2 Standalone fixes (independent quality)
- **#5 doubled-`?` after unquote** (`url_utils.py:188-192`) — **likely already mitigated**: `candidate` is `urlsplit`-derived, not `unquote()`-derived. Verify; if correct, **skip with reason**.
- **#8 / #9 projection tests** (`test_projection.py` 942-951, 798-856) — assert asset claims belong to `prod-1`; exercise real re-projection so a non-generic `selection_origin` is preserved across a second `project_extraction_result()` for the same run/url.
- **#10 diagnose-builder test** (`test_diagnose_builder.py` 247-252) — assert the full `contract_outcomes` shape incl. `selection_origin`, `selected_source`, truncation metadata.
- **#11 frontend KG diagnosis fallback** (`knowledge-graph-tab.tsx` 421-425) — only show "No diagnose artifact persisted" when the request succeeded with no data; surface real `diagnosis.error` (auth/server/network) separately.
- **#12 diagnostics not-found sentinel** (`diagnostics_artifacts.py` 45-49) — catch `ArtifactRepository.read_json()`'s exact not-found sentinel, not broad `OSError`/`ValueError`; let malformed-JSON / permission errors propagate; return `None` only when genuinely absent.
- **#13 / #14 diagnostics API tests** (`test_diagnostics_api.py` 24-31, 210-226) — save/restore only the `get_db`/`get_current_user` overrides in `try/finally` (no blanket `dependency_overrides.clear()`); add an access-control-hidden 404 test (crawl owned by a different user → report.json + diagnose.json both 404).
- **#15 / #16 KG query error handling** (`use-knowledge-graph.ts` 35-53) — stop swallowing `listKnowledgeSites` failures in the `Promise.all`; let the query fail (or handle only a clean "no site" case) so mutations don't proceed with stale version context.

### 4.3 Final docs update
- Rewrite `docs/plans/extraction-overhaul.md` to **mark A2/A3/recall/backbone complete** and **replace the "90-URL audit corpus" verification framing with the three-invariant guarantee** (recall / precision / explainability via property tests), so the doc matches how correctness is actually established.
- Update `docs/INVARIANTS.md` with the three executable invariants and the divergence-guard / decision-derived-field-state mechanisms.
- Update `docs/plans/ACTIVE.md` (currently points at the completed KG rebuild) to reference this plan and its completion.
- Refresh the `active-plan-extraction-overhaul` memory to reflect A2/A3/recall/backbone done.

---

## Verification (how we prove the guarantee — no URL sample)

1. **Backend** — `PYTHONPATH=. ./.venv/Scripts/python.exe -m pytest tests -m "unit or component" -q` stays green at every phase; new property tests above pass; genericness ratchets (`test_extraction_carries_no_retailer_domain_literals`, `test_extraction_rules_have_no_matrix_tuned_constants`) stay green; ruff clean; 24-file ceiling test green (or its constant deliberately bumped with rationale).
2. **EXPLAINABILITY (Q1 guarantee)** — `test_field_state_provenance` + the divergence guard prove that for **every** field in **every** fixture, diagnose.json answers exactly one of *published / rejected-with-reason / no-candidate*, and no public value diverges from resolution. This is the structural guarantee, independent of any site list.
3. **RECALL (Q2 — no missed data)** — `test_collector_recall` proves every recognized shape across every source becomes a collected candidate **or** a recorded rejection — never a silent gap.
4. **PRECISION** — `test_resolution_ranking` proves JSON-LD offers beat phantom DOM prices and enum-valid beats enum-invalid; materialization performs no semantic decisions.
5. **A3** — mocked tests prove the LLM only ever selects among candidates, its choice auto-replays on same-template pages with no second call, and circuit-open/abstain degrades deterministically.
6. **Frontend** — `npm run check && npm run check:policy && npm run test` green after the CodeRabbit frontend fixes.
7. **CodeRabbit** — each of the 16 findings is either fixed or skipped-with-reason in the implementation notes.
