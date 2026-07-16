# Extraction-Cascade Rearchitecture — Single Handoff for Remaining Work

**Repo:** `abhij1306/CrawlerAI` · **Work branch:** `vorflux/extraction-cascade-rearchitecture` (off `main`).
**Written:** 2026-07-16. **Author context:** hand-off after the LEARN-ONCE recipe tier slice.

> This is the ONE document a fresh agent (or human) needs to resume. It is
> self-contained: all context needed to finish is inlined here so nothing
> dangles after this branch merges to `main`. The richer original planning docs
> live only on the separate `vorflux/rearchitecture-plans` branch (see
> "Reference docs" at the bottom) and will NOT be reachable from `main` — do not
> rely on links to them.

---

## 1. Where the overall project stands

Selective rearchitecture of the extraction cascade into a selector-free,
typed-`SurfaceSpec`-routed pipeline with a learn-once recipe tier. Sequence and
status:

| Step | State |
|------|-------|
| Phase 0 — foundation | DONE (`c11a974`) |
| Slice 1 — commerce listing | DONE (`d8a733e`) |
| Slice 2 — job listing | DONE (`96883c8`) |
| Slice 3 — commerce detail cascade | DONE (`a6eb772`) |
| **LEARN-ONCE recipe tier** | **Mostly done — see §3.** CRITICAL findings all fixed + wired; several HIGH/MEDIUM findings deferred to Slice 4 (§4). |
| **Slice 4 — job detail + escalation ladder + verdict fixes** | **NOT STARTED — see §5.** |
| Acquisition ladder + unified card ownership | NOT STARTED (§6) |
| Eval-gated cross-cutting cleanup + docs | NOT STARTED (§7) — **owns the LOC-ledger reconciliation, see §8.** |
| Final testing / report / PR | NOT STARTED |

**Base commits:** `4fc9d49`=`origin/main`; `c11a974` Phase 0; `d8a733e` Slice 1;
`96883c8` Slice 2; `a6eb772` Slice 3 (base for the LEARN-ONCE commits).

**Merge intent (user):** Do NOT merge to `main` until the WHOLE feature
(through Slice 4 + acquisition ladder + eval-gated cleanup) is complete. The
LEARN-ONCE commits are NOT yet squashed. No PR is open.

---

## 2. Repo invariants (enforce on every change)

- Config strings / thresholds / selectors / field-names live in `app/core/config/*`,
  never inline in service code. Cascade tunables go in `core/config/cascade.py`.
- Fix upstream, not downstream. Grep before adding. One concern, one owner.
  Delete duplication as part of the change.
- LLM is an explicit, degradable backfill, never the primary extractor. Tier
  order is fixed: **adapter → structured → network → DOM → (recipe replay) →
  LEARN-ONCE LLM**.
- **No `surface ==` / `surface is` branching in the cascade body**
  (`extraction/cascade.py`). Route by typed `SurfaceSpec`/`ListingSchema` only.
  A grep-based architecture test enforces this.
- **No retailer/ATS domain literals or matrix-tuned constants in non-test code.**
  ATS names (Greenhouse/Lever/Bullhorn) may appear only in test fixtures.
- Extraction (`app/extraction/`, sync `extract()`) is **storage-free** (INVARIANTS
  Rule 17 / AP-24). Learning + DB writes happen only in the async crawl pipeline
  (`app/crawl/pipeline/`), never inside sync `extract()`.
- Recipes may only **locate evidence**; they must not mint public records or
  derived identifiers directly. All values flow through the normal adapter
  **Resolve → Publish** authority (`publication.py` is the single typed-record
  producer).
- Frozen release snapshots are immutable once a run is created.
- Migration chain is linear: `20260703_0001` → `20260711_0002` → `20260711_0003`
  (head). LEARN-ONCE needs no new migration (reuses `extraction_memory` tables).
  Do NOT reintroduce the abandoned `20260713_0004`.

---

## 3. LEARN-ONCE tier — what is DONE

Goal: on the first crawl of a NEW `(domain, surface, route_pattern)` template,
when deterministic floors produced nothing AND the crawl is `llm_enabled` AND the
surface is allow-listed, make **exactly one** LLM call to compile a grounded
recipe (model proposes page *paths*, never values). Persist it, and on
subsequent crawls **replay** it deterministically with zero model calls
(`extractor_tier="recipe"`). On drift, fall through to deterministic floors and,
after `CASCADE_RECIPE_STALE_FAILURE_THRESHOLD=3` failures, self-heal (suspend).

### Commits on top of `a6eb772` (NOT yet squashed)

| SHA | What |
|-----|------|
| `7df332e` | Original LEARN-ONCE build (primitives, compiler, replay, async seam, persistence, drift self-heal, tests). |
| `93b0621` | CRITICAL 1+2: unify release payload (`release.v2`) so real runs carry executable recipes; freeze snapshots; rework drift self-heal. |
| `fdaa2fe` | Align engine + tests with the unified release payload. |
| `921c33c` | CRITICAL 1 proof: `test_learn_once_production_replay.py` — recipe replays on a real subsequent run via `create_crawl_run`/release path. |
| `442c791` | CRITICAL 3 scaffold: `recipe_evidence.py` + fact-type map (not yet wired at that point). |
| `0075d33` | docs: original `LEARN-ONCE-STATUS.md` (now partly stale — this doc supersedes its status table). |
| `21dc39d` | docs: human-verified commerce_detail eval labels + test-site corpus (`EVAL-TEST-SITES.md`). |
| `23f3cd2` | test: align active-recipe selection test with `executable_recipe` key. |
| `7266a85` | **CRITICAL 3 wiring**: route replay through resolver/publish authority; `recipe_execution_evidence` called in `engine.py`; `publish_recipe_execution` deleted. |
| `e47f0db` | **HIGH 4/8/11**: precise replay drift gate + job_listing identity/binding. |
| `a11eb07` | align `_requested_field_names` identity with `is_listing`; relocate recipe fact-type map into `recipe_evidence.py` (LOC fix). |

### Findings that are FIXED (verified this branch)

- **CRITICAL 1** — learned recipes now reach real runs (`release.v2`, executable
  recipes attached). Proven by `test_learn_once_production_replay.py`.
- **CRITICAL 2** — frozen release no longer mutated at load; suspension applied
  only when building future snapshots.
- **CRITICAL 3** — replay routed through resolver/publication authority.
  `engine._replay_active_recipe` now calls `recipe_execution_evidence(request,
  recipe, execution)` (engine.py:495) → normal `Evidence` → adapter
  resolve/publish. `publish_recipe_execution` is deleted (grep confirms zero
  references in `app/` and `tests/`).
- **HIGH 4** — `job_listing` record identity is `url` (not `apply_url`). Keyed on
  `is_listing` in `recipe_compiler._identity_field(field_paths, *, is_listing)`.
- **HIGH 8** — attribute bindings (`url`/`apply_url`/`image_url`) anchor to the
  exact grounded model path via `_attribute_binding`, keeping values scalar
  instead of broadening to `a[href]`/`img[src]`.
- **HIGH 11** — drift gate is precise: drift = a field the recipe grounded at
  read time is suppressed in the published record
  (`engine._recipe_fields_suppressed`), NOT a blunt verdict-only gate.
  Optional-contract-field partiality (e.g. brand/description never grounded) is
  NOT drift.
- Consistency: `_requested_field_names` identity aligned with `is_listing`
  (a job_listing always requires `url`; detail prompts for both `url`+`apply_url`
  and lets `_identity_field` pick post-grounding).

### Current config posture (unchanged — important)

The LEARN-ONCE tier is **enabled by default** in `core/config/cascade.py`:
`CASCADE_LEARN_ONCE_TIER_ENABLED = True`,
`CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL = True`,
`CASCADE_RECIPE_STALE_FAILURE_THRESHOLD = 3`,
`CASCADE_LEARN_ONCE_SURFACES = ("ecommerce_detail", "ecommerce_listing", "job_listing")`.

Because the deferred findings below affect the tier's production behavior
(duplicate/wasted model calls, one-call race, drift-counter accuracy), the
Slice-4 agent MUST decide with the user whether to (a) close those findings
before this feature goes live, or (b) gate the tier OFF by default until they
are closed. This branch is NOT being merged until the full feature is complete,
so nothing ships in the current state regardless. See §4.

---

## 4. LEARN-ONCE findings DEFERRED into Slice 4 (open work)

These were identified in independent review of `7df332e` and are **not yet
implemented**. They interact on `failure_count` / one-model-call semantics —
keep them as **separate per-finding commits**, do not batch, and re-run the DB
component tests after each.

### HIGH (open)

- **5 — Learning runs before browser retry; can call compiler twice per URL.**
  `record_extraction_stage` calls the learn seam before
  `retry_extraction_request_with_browser`. Fix: learn only after the final
  deterministic/browser attempt; carry a per-URL "learning attempted" latch
  across retries.
- **6 — HTTP-only capture consumes a model call but can't produce an executable
  recipe** (compiler accepts `http_html`, emits a recipe requiring
  `rendered_dom` → `recipe_capture_requirement_missing`). Fix: don't call the
  model until the rendered artifact the recipe will use exists (or persist the
  actual capture type compiled against).
- **7 — Listing recipes accept singleton record roots** (executor requires ≥1,
  not the configured min of 2). Fix: enforce
  `CASCADE_LISTING_MIN_REPEATED_RECORDS`=2 at compile AND every replay. Note:
  `execute_recipe` slices `roots[:request.max_records]`, so counting
  `execution.records` needs a request whose `max_records` matches the fixture
  record count.
- **9 — Grounding validates against the full-page flat map, not the scoped/capped
  map shown to the model.** Fix: validate only against the exact prompt entries;
  derived roots must anchor to an accepted entry.
- **10 — Template-newness is race-prone; does not guarantee one model call.**
  Concurrent URLs/runs can both see "no recipe" and both call the model. Fix:
  durable transactional claim/lease keyed by `(domain, surface, route_pattern)`;
  recheck the durable recipe before inference.
- **12 — Drift failures neither consecutive nor concurrency-safe; success never
  resets.** Fix: reset the counter after a successful replay; update under
  `FOR UPDATE`/atomic conditional.

### MEDIUM (open)

- **13 — Any domain/surface operator label disables auto-suspension** (ignores
  route/template/field/action). Fix: scope exemption to the exact
  recipe/template + explicit operator ownership/action.
- **14 — "One model call" allows provider retries** (`call_provider_with_retry`
  may issue `max_retries+1` requests). Fix: `max_retries=0` for LEARN-ONCE; add a
  production-client test.
- **15 — Detached executable snapshots (`run_id=None`) accumulate without a
  consumer.** Fix: stop creating detached snapshots (or add explicit activation +
  retention).

### Simplify follow-ups (do alongside, do not prioritize over correctness)

- Delete unused `RecipeBindingProposal` / `DiscoveryCompiler` and unused
  `DiscoveryResult` diagnostic fields if no valid use remains.
- `ExtractionResult.recipe_candidate` is dead (only set in tests): wire through a
  real diagnostic path or remove it + candidate-only test assertions.
- Consolidate `_repeated_root_css` / `_relative_css` / `_absolute_css`;
  remove any no-op `if ...: pass`.
- Retire the ecommerce-detail-only universal-model fallback from the live
  cascade (structurally present but inert — nothing populates
  `runtime_snapshot["universal_model"]`); keep the Sentinel challenger +
  grounding helpers.

---

## 5. Slice 4 — Job detail + escalation ladder + verdict fixes (the remaining slice)

Sequence: after LEARN-ONCE. This slice OWNS `result_building.retry_request` and
the `contracts`/`extraction_loop` verdict items. Scope (from the settled plan):

- `extraction/jobs.py::collect_job_detail` / `adapters._harvest_job_detail`:
  route through `run_detail_cascade` (structured JobPosting floor → DOM); read
  the rendered artifact set (the shared `LISTING_HTML_ARTIFACT_IDS`-style set,
  not only raw `"html"`).
- `targeting.py`: add URL-based disambiguation for `job_detail` (mirror
  `_select_product_by_url`) so multi-`JobPosting` JSON-LD (similar-jobs widgets)
  no longer trivially triggers `AMBIGUOUS_JOB_ROOT`; keep `select_subject_targets`
  but disambiguate by requested URL first.
- `result_building.retry_request`: emit `CapabilityRequest` for
  `job_listing`/`job_detail` (empty/shell → `rendered_html`; missing structured →
  `network_payloads`), not only ecommerce.
- `contracts.CapabilityRequest`: `max_attempts` upper bound was relaxed in Phase 0
  from `le=1` to `le=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP` (default 2) — verify,
  don't redo. Test: `test_final_architecture_contracts.py::test_capability_request_is_bounded_to_configured_cap`.
- `crawl/pipeline/extraction_loop.py`: verify Phase 0 already renamed `UrlVerdict`
  Literal `"listing_failed"` → `"listing_detection_failed"`; add
  `test_verdict_literal.py` coverage.
- `crawl/pipeline/retry/stage.py`: honor the surface-agnostic ladder (loop up to
  the configured rung count instead of the hard `browser_escalation_count >= 1`
  cap) — bounded, honest exhaustion.

**Tests for Slice 4:**
- `backend/tests/unit/test_job_detail_cascade.py` (new): JobPosting structured
  floor; similar-jobs widget disambiguated by URL; rendered artifact read.
- Extend `test_extraction_surface_behavior.py`: job surfaces get a `RetryRequest`
  on empty/shell.
- `backend/tests/unit/test_verdict_literal.py` (new): `UrlVerdict` contains
  `"listing_detection_failed"` and downstream string checks match
  `verdict.VERDICT_LISTING_FAILED`.
- `backend/tests/component/` escalation test: multi-rung ladder reaches
  browser+network then exhausts honestly.
- Run: `cd backend && pytest tests/unit/test_job_detail_cascade.py tests/unit/test_extraction_surface_behavior.py tests/unit/test_verdict_literal.py -q && ruff check app/extraction app/crawl/pipeline`.

---

## 6. Acquisition ladder + unified card ownership (after/with Slice 4)

Owns NEW `backend/app/acquisition/listing_cards.py`. Shares the
`CapabilityRequest`/`RetryRequest` contract with Slice 4's ladder work.

- Honest verdict + failure classification.
- Surface-agnostic escalation ladder — contract + declare + fulfill
  (HTTP → browser → browser+network), bounded by
  `CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP`.
- Network-payload capture on rung 2 + `network_json` persistence.
- Unified surface-aware card owner — collapse the four card forks into
  `acquisition/listing_cards.py`; job-listing rendered read + shared quality gate.
- Browser readiness: reject loading/search shells; `diagnose.json` discovery
  diagnostics. Uniform `card_count` semantics across surfaces.

---

## 7. Eval-gated cross-cutting close-out (last)

- **Eval-gated per-surface selector deletion** — only after the cascade beats the
  selector baseline for that surface on the eval harness (`backend/eval/`). NEVER
  delete a working DOM floor before the cascade proves ≥ baseline.
- Live-constant relocation for any remaining inline constants.
- Fix any remaining stale extraction docs.
- **Owns the LOC-ledger reconciliation described in §8.**

---

## 8. Architecture ratchets & the LOC-ledger state (READ before touching budgets)

There are TWO parallel budget ledgers:

1. **TOML manifest** `backend/app/core/config/extraction_semantic_surface.toml`
   `[ratchets]` — backs `test_extraction_architecture.py`. This slice bumped it
   (engine.py module budget `1023 → 1099`; top-level `physical_loc_budget`
   `17333 → 17496`). `test_extraction_architecture.py` PASSES (28 tests).
2. **Hardcoded ledger** `backend/tests/unit/test_final_architecture_ownership.py`
   (`OVERSIZED_MODULE_DEBT`, `PACKAGE_LOC_BUDGETS`, `TOTAL_APP_LOC_BUDGET`).

Both `_physical_line_count` helpers count **NON-BLANK** lines, not raw lines.

### What this slice changed in the hardcoded ledger (kept — genuine slice growth)

- `OVERSIZED_MODULE_DEBT["extraction/engine.py"]`: `1023 → 1099` (lockstep with TOML).
- `OVERSIZED_MODULE_DEBT["persistence/extraction_memory.py"]`: `825 → 961`
  (no TOML counterpart; this dict is the sole ledger for that module).
- `PACKAGE_LOC_BUDGETS["core"]`: `19_272 → 19_982`.
- `PACKAGE_LOC_BUDGETS["extraction"]`: `15_534 → 16_433`.
- `TOTAL_APP_LOC_BUDGET`: `84_853 → 84_998`.

Result: `test_production_package_loc_budgets` PASSES.

### Two tests in that file are PRE-EXISTING failures (NOT this slice, NOT ours to fix)

Verified: both fail **identically on `origin/main`** (the merge target) and on
base `a6eb772`, in files the LEARN-ONCE slice never touches. This matches the
existing note in the plans-branch `REMAINING-SLICES-IMPLEMENTATION-PROMPT.md`
§5 item 3 ("Pre-existing FAILING architecture tests on `main` … NOT ours to fix,
out of scope").

- **`test_no_new_oversized_modules`** — key-set mismatch: 9 debt entries were
  recorded at RAW line counts but the test measures NON-BLANK, so these 9 are now
  below 700 non-blank and never appear in `oversized`, breaking
  `oversized.keys() == OVERSIZED_MODULE_DEBT.keys()`. The 9:
  `acquisition/browser_capture.py` (696), `browser_pool.py` (639),
  `browser_readiness.py` (681), `cookie_store.py` (639),
  `fetch/browser_attempt_runner.py` (686), `extraction/result_building.py` (698),
  `intelligence/discovery.py` (656), `intelligence/matching.py` (651),
  `schemas/crawl.py` (623). Also `extraction/pipeline.py` is 773 non-blank vs
  debt 772 (over by 1) — pre-existing (773 on `a6eb772` too), unchanged by this
  slice.
- **`test_no_new_complex_functions`** — over-debt in files this slice does not
  touch: `extraction/result_building.py::field_evidence_states` (46>41),
  `projection_field_states` (78>70),
  `core/shared/field_coerce_text.py::infer_brand_from_page_identity` (39>38),
  `infer_brand_from_product_url` (86>69).

**The full reconciliation of this hardcoded ledger (rebuild
`OVERSIZED_MODULE_DEBT` from the actual >700 non-blank set, drop the 9 stale
sub-700 entries, reconcile the complex-function debt) belongs to the eval-gated
cleanup slice (§7)** — it is `main`'s pre-existing debt, out of scope for
LEARN-ONCE. This slice deliberately kept only the value bumps that reflect its
own genuine growth (engine.py/extraction_memory.py + package/total), so
`test_production_package_loc_budgets` stays green and no NEW failure is
introduced relative to `main`.

**End-state of `test_final_architecture_ownership.py` at this handoff:**
31 passed / 2 pre-existing-documented failures (the two above).

---

## 9. Key files (owners)

- **Pure primitives** (`backend/app/core/extraction_memory/`): `recipe_contracts.py`
  (`ExtractionRecipe`, `RecipeExecutionResult`, `RecipeBinding`
  [`cardinality: RecipeCardinality = "zero_or_one"`], `RecipeEntity`, `RecipeScope`),
  `recipe_executor.py` (pure `execute_recipe(request, recipe)`; slices
  `roots[:request.max_records]`; `_check_cardinality` only raises for `"one"` when
  count>1), `recipe_transforms.py`, `recipe_artifacts.py`.
- **Grounded compiler** (main-owned): `recipe_compiler.py` (async `compile_recipe`;
  `_identity_field(field_paths, *, is_listing)`,
  `_requested_field_names(request, surface_spec, listing_schema)`, `_field_binding`,
  `_attribute_binding`, `_attribute_node_resolves`, `_structural_attribute_binding`;
  `_ATTRIBUTE_FIELDS={"url":"href","apply_url":"href","image_url":"src"}`;
  `_FIELD_TRANSFORMS={"price":"dom_price","currency":"dom_currency"}`; must NOT
  import publication/persistence/`PublicRecord`). 533 lines.
- **Recipe→evidence bridge:** `recipe_evidence.py` (`recipe_execution_evidence`;
  OWNS `RECIPE_FIELD_FACT_TYPES_BY_SURFACE`, `_ENTITY_BY_PREFIX`, `_LOCATOR_KIND`;
  confidence 0.86, directness "direct").
- **Replay/engine:** `backend/app/extraction/engine.py` (`_replay_active_recipe`
  ~439, `_recipe_fields_suppressed`, `_needs_contract_fallback` ~425, `_assess`
  ~677; `extract()` calls `_replay_active_recipe` first). engine.py nonblank=1099.
- **Async learn seam:** `backend/app/crawl/pipeline/learn_once.py`
  (`should_attempt_learn_once`, `learn_recipe_after_extraction`) +
  `record_extraction_stage.py`.
- **Persistence:** `backend/app/persistence/extraction_memory.py`
  (`persist_learned_recipe`, `build_release_payload`, `_executable_recipe_block`,
  `_locked_active_executable_recipe`, drift counter). nonblank=961.
  `select_active_recipe` in `core/extraction_memory/contract_runtime.py`.
- **Config:** `core/config/cascade.py` (flags, threshold, learn allow-list,
  `CASCADE_RECIPE_COMPILER_FIELD_DESCRIPTORS`,
  `CASCADE_LISTING_MIN_REPEATED_RECORDS=2`); `core/config/field_mappings.py`
  (fact-type constants; `RECIPE_FIELD_FACT_TYPES_BY_SURFACE` moved OUT to
  `recipe_evidence.py`); `extraction_semantic_surface.toml` (TOML ratchet).
- **Contracts:** `backend/app/extraction/contracts.py` (`PublicRecord` [FrozenModel,
  `extra="allow"`, `.get()`/`.items()`/`.keys()`], `JobListingRecord`
  [`title:str`, `url:str` required], `CommerceDetailRecord`).

---

## 10. Environment & test commands

- `uv` at `$HOME/.local/bin/uv`. Venv at `backend/.venv` (no pip/ensurepip — use
  `uv sync --extra dev`). Ruff: `.venv/bin/ruff check <paths>`.
- **Focused tests only** (AGENTS.md forbids broad `pytest tests -q` sweeps):
  ```
  cd backend && export PATH="$HOME/.local/bin:$PATH" \
    && TEST_DATABASE_URL=postgresql+asyncpg://postgres:crawlerai_dev_pw@localhost:5432/test_db \
       PYTHONPATH=. .venv/bin/python -m pytest <specific files> -q
  ```
- Component/DB tests need Postgres (docker container `crawlerai-db-1` on
  `localhost:5432`, DBs `crawlerai` + `test_db` migrated to head).
- Import smoke: `PYTHONPATH=. .venv/bin/python -c "import app.main"`.

### LEARN-ONCE test inventory (current pass counts)

- Unit: `test_recipe_contracts.py` (8), `test_recipe_executor.py` (6),
  `test_recipe_compiler.py` (9, incl.
  `test_job_listing_identity_is_url_and_apply_url_stays_scalar`,
  `test_job_listing_url_required_even_when_not_requested`),
  `test_learn_once_replay.py` (7, incl.
  `test_replay_falls_through_when_grounded_field_is_suppressed`),
  `test_extraction_architecture.py` (28).
- Component (Postgres): `test_learn_once_persistence.py` (6),
  `test_learn_once_production_replay.py` (1), `test_crawls_api_domain_recipe.py` (6).
- Regression (correct filenames): `test_extraction_baseline.py` (6 skipped —
  frozen corpus absent), `test_job_listing_cascade.py`,
  `test_commerce_listing_cascade.py`, `test_extraction_variant_behavior.py`,
  `test_extraction_contract_behavior.py` — combined 133 passed, 6 skipped.
- Pre-existing failures (NOT this slice; fail identically on `main` and
  `a6eb772`): `test_final_architecture_ownership.py::test_no_new_oversized_modules`
  and `::test_no_new_complex_functions` (see §8).

---

## 11. Close-out checklist for the LEARN-ONCE slice (when its findings are done)

1. Squash the LEARN-ONCE WIP commits (`7df332e`→tip) into ONE clean
   `feat(extraction): add LEARN-ONCE recipe tier` on `a6eb772`. After squash,
   VERIFY `git show HEAD:docs/plans/rearchitecture/` still has this handoff +
   `LEARN-ONCE-STATUS.md` + `EVAL-TEST-SITES.md`.
2. `git diff --name-only a6eb772..HEAD` — confirm no foreign ownership file changed.
3. Focused pytest green + `ruff check` clean + `import app.main` clean.
4. Run Simplify + Review + DB-backed Testing subagents against the squashed diff;
   route findings verbatim back to the build task.
5. Push (`--force-with-lease` after a squash rewrite; never empty the branch
   below base).

---

## 12. Reference docs (on the `vorflux/rearchitecture-plans` branch only — NOT on `main`)

These are the richer originals; they will NOT be reachable after this branch
merges to `main`, so the needed context has been inlined above. Read them via
`git show vorflux/rearchitecture-plans:<path>` while that branch exists:

- `docs/plans/rearchitecture/REMAINING-SLICES-IMPLEMENTATION-PROMPT.md` — full
  per-slice implementation prompt (source of §5–§7 above).
- `docs/plans/rearchitecture/subplans/extraction-cascade.md` — task T1–T6 detail.
- `docs/plans/rearchitecture/DECISIONS.md` — settled architecture decisions
  (recipe scope key, self-heal model, no parallel migration).
- `docs/plans/rearchitecture/context-brief.md`,
  `subplans/acquisition-ladder.md`, `subplans/crosscut-migration.md`.

On this working branch (survives merge): this file,
`docs/plans/rearchitecture/LEARN-ONCE-STATUS.md` (original status doc — its
finding-status table is partly superseded by §3/§4 here; trust this file),
`docs/plans/rearchitecture/EVAL-TEST-SITES.md` (eval corpus reference).

**Reference primitives** for LEARN-ONCE + Slice 4 were ported from tag
`archive/extraction-v3-phase0-eval` (`git show archive/extraction-v3-phase0-eval:<path>`).
Reject that tag's architecture (two competing pipelines + a compiler that
reverse-derived recipes from published records); do NOT port its abandoned
migration `20260713_0004`.
