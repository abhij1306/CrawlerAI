# CrawlerAI Extraction-Cascade Rearchitecture — Implementation Prompt for Remaining Slices

> **Status at time of writing (2026-07-15):** Phase 0 Foundation + Slice 1 (commerce
> listing) are landed and pushed. Slice 2 (job listing) is in flight as WIP commits on
> `vorflux/extraction-cascade-rearchitecture`. This doc is the continuation prompt for
> everything after Slice 2: Slice 3 (commerce detail), LEARN-ONCE tier, Slice 4 (job
> detail), the acquisition ladder, and the cross-cutting close-out (eval-gated selector
> deletion, testing, PR). Feed each slice section below to a build subagent as its task
> `description`, one slice at a time, respecting the sequencing.

## 0. Ground truth / where things live

- **Repo:** `/code/abhij1306/CrawlerAI`, remote `https://github.com/abhij1306/CrawlerAI`.
- **Work branch:** `vorflux/extraction-cascade-rearchitecture` (off `main`).
- **Plan docs (tracked):** `docs/plans/rearchitecture/` — `DECISIONS.md`, `context-brief.md`,
  and `subplans/` (`extraction-cascade.md` T1–T6, `acquisition-ladder.md`,
  `crosscut-migration.md`). Read the matching subplan before each slice; the task numbers
  below map to `subplans/extraction-cascade.md`.
- **Reference primitives to port:** the old feature branch was deleted per user request but
  archived as tag **`archive/extraction-v3-phase0-eval`**. Port primitives with
  `git show archive/extraction-v3-phase0-eval:<path>`. **Reject its architecture** (two
  competing pipelines + a compiler that reverse-derived recipes from published records). Do
  **NOT** port migration `20260713_0004_compiled_recipe_compiler_version.py` (abandoned
  compiler).
- **Landed commits:** `c11a974` Phase 0, `d8a733e` Slice 1. Slice 2 lands as squashed
  `feat(extraction): Slice 2 — job listing …` after WIP squash.

## 1. Repo invariants (enforce on every build subagent)

From `AGENTS.md` + `docs/plans/rearchitecture/DECISIONS.md`:

- Config strings / thresholds / selectors / field-names / patterns live in
  `app/core/config/*`, **never** inline in service code. New knobs go in
  `core/config/cascade.py` (owner of cascade tunables) or the relevant `core/config/*`.
- Fix upstream, not downstream. Grep before adding. One concern, one owner. Delete
  duplication as part of the change. Respect explicit user controls.
- LLM is an **explicit, degradable backfill**, never the primary extractor. Extraction tier
  order is fixed: **adapter → structured → network → DOM → (recipe replay) → LEARN-ONCE
  LLM**.
- **No `surface ==` branching in the cascade body** (`extraction/cascade.py`). Route by the
  typed `SurfaceSpec`/`ListingSchema` only. There is a grep-based architecture test that
  fails on `surface ==` in the cascade body — `test_extraction_architecture.py`.
- **No retailer/ATS domain literals or matrix-tuned constants in non-test code.** ATS names
  (Greenhouse/Lever/Bullhorn) may appear only in **test fixtures**. Ratchets:
  `test_extraction_carries_no_retailer_domain_literals`,
  `test_extraction_rules_have_no_matrix_tuned_constants`.

## 2. Ownership boundaries (do NOT edit these unless the slice owns them)

- `extraction/surfaces.py`, `extraction/contracts.py`, `crawl/pipeline/extraction_loop.py`
  = **Foundation only** (already done). Slice 4 is the one exception that may touch
  `contracts.CapabilityRequest.max_attempts` bound and `extraction_loop.py` verdict Literal
  (already done in Phase 0 — verify, don't redo).
- `extraction/result_building.py::retry_request` = **Slice 4** owns.
- `extraction/jobs.py` + `extraction/listing.py` gate unification = **Slice 2** owns.
- Card enumeration lives in NEW `backend/app/acquisition/listing_cards.py` owned by the
  **acquisition-ladder** slice (NOT Slice 2 / not the listing slices).
- After any slice, verify no foreign ownership file changed:
  `git diff --name-only d8a733e..HEAD` (adjust base to the prior slice's tip).

## 3. Architecture ratchet manifest (touch deliberately)

`backend/tests/unit/test_extraction_architecture.py` is backed by TOML manifest
`backend/app/core/config/extraction_semantic_surface.toml` `[ratchets]`:

- `assert len(files) <= N` — file count under `app/extraction/`. **Raise N** when you add a
  module.
- `relative_paths == set(module_physical_loc_budgets)` — **EXACT set match**; every module
  under `app/extraction/` must have an entry, no stragglers.
- Per-module `_physical_line_count(path) <= module_loc_budgets[relative_path]` — raise the
  per-module budget when a module legitimately grows. `_physical_line_count` = count of
  **non-blank** lines.
- `test_extraction_semantic_surface_manifest_is_current` asserts
  `physical_loc_budget >= sum(module_physical_loc_budgets.values())` — bump the top-level
  `physical_loc_budget` whenever you raise any module budget.
- When adding a module: add its `module_physical_loc_budgets` entry, raise file-count `N`,
  raise top-level `physical_loc_budget`. Document budget bumps in the commit message so
  review doesn't read them as loosening for the slice's own growth.

## 4. Environment / run commands

- `uv` at `$HOME/.local/bin/uv` (v0.11.28). Venv at `backend/.venv` (the venv had **no
  pip/ensurepip** — use `uv`, don't try `python -m pip`). pytest 9.0.3, ruff 0.15.10, radon.
- **Tests (FOCUSED files only — AGENTS.md forbids broad `pytest tests -q` sweeps):**
  ```
  cd backend && export PATH="$HOME/.local/bin:$PATH" \
    && PYTHONPATH=. .venv/bin/python -m pytest <specific test files> -q
  ```
- **Lint:** `.venv/bin/ruff check <paths>`.
- **Import smoke:** `PYTHONPATH=. .venv/bin/python -c "import app.main"`.
- **Component/DB tests** need Postgres. A throwaway `postgres:16-alpine` container
  `crawlerai-test-pg` on `localhost:5432` (user/pass `postgres`) with DBs `crawlerai` +
  `test_db` migrated to head `20260711_0003` is available (started by the testing agent). If
  gone, recreate and `alembic upgrade head`.
- **Frontend** uses VitePlus (`vp`). `vp`/`node_modules` are ABSENT — before any
  AI-visibility browser smoke test run `corepack enable` + `pnpm install` in `frontend/`.

## 5. Machine-setup learnings, gotchas & known pre-existing bugs

These were discovered during setup and earlier slices. **Do not treat the pre-existing
failures as regressions from this work.**

1. **`git push` credential flakiness.** Early in the session the credential endpoint
   returned HTTP 404 for this repo and push was not wired; it later started working. If push
   fails again, PR creation must go through `vflux_exec pr create` (handles auth), not raw
   `git push`. Do not `gh auth login`.
2. **venv has no pip/ensurepip.** Always use `uv` for dependency work. `python -m pip`
   inside `backend/.venv` will fail.
3. **Pre-existing FAILING architecture tests on `main` (NOT ours to fix, out of scope):**
   `test_final_architecture_ownership.py::test_no_new_oversized_modules` and
   `::test_no_new_complex_functions` were already red on `main` (verified via a clean
   `git worktree`). Do not attempt to fix them; do not let them block a slice. If a reviewer
   flags them, point to this note.
4. **Pre-existing LOC drift in `collectors/dom.py`.** `dom.py` is **1100** physical
   (non-blank) LOC on `main`, unmodified by this work. Its manifest budget was corrected
   1096→1100 in Phase 0 to reflect reality — this is a correction, not loosening for our
   growth. Leave it at 1100 unless dom.py itself changes.
5. **selectolax returns fresh wrapper objects per access.** In `extraction/documents.py`,
   sibling/identity comparisons must use a stable `mem_id` compare, **not** Python `is`
   (Phase 0 changed `dom_path()` accordingly). Any new DOM-walking code must follow the same
   rule — `is` comparisons on selectolax nodes are a latent bug.
6. **Migration chain is linear** and must stay so:
   `20260703_0001` → `20260711_0002` → `20260711_0003` (head). Any new migration
   (LEARN-ONCE may need none — reuse existing `extraction_memory` tables) must chain off the
   current head, and must NOT reintroduce `20260713_0004`.
7. **Job-hub rejection markers were intentionally LEFT in
   `core/config/extraction_rules/_listing_structured.py` for Slice 2 to wire:**
   `JOB_LISTING_DETAIL_ROOT_MARKERS` (~L128), `JOB_POSTING_PATH_MARKERS` (~L131),
   `JOB_LISTING_HUB_TITLE_PREFIXES` (~L152 = `("remote ",)`), `JOB_LISTING_HUB_TITLE_SUFFIXES`
   (~L153 = `(" jobs"," careers"," openings")`), `JOB_LISTING_HUB_TERMINAL_SUFFIXES`
   (~L158 = `("-jobs","-careers","-openings")`). If Slice 2 wired them, they should now be
   consumed by `jobs.py`; if any remain unused after Slice 2, that's dead config to remove.
8. **`/memory/` was UNREACHABLE this session** for the testing subagent and reflection.
   Later sessions should retry `/memory/knowledge/` and `/memory/testing/` reads — they may
   be reachable again; do not assume the same outage.
9. **`_MIN_REPEATED_RECORDS = 2`, not 3.** An earlier draft used 3; corrected to match the
   reference branch's proven primitive. DOM-only discovery stays repetition-gated at 2; a
   single (singleton) record is admissible **only** via structured corroboration, never
   DOM-only. `CASCADE_LISTING_MIN_REPEATED_RECORDS` in `core/config/cascade.py`.
10. **`required_artifacts` on `CapabilityRequest` is a plain `tuple[str,...]`** with no vocab
    allowlist; `network_payloads` is already used in `result_building.py`. Nothing to extend
    there for Slice 4 — just emit the right artifact IDs.
11. **`CapabilityRequest.max_attempts`** was relaxed in Phase 0 from a hard `le=1` to
    `le=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP` (default 2). Slice 4's multi-rung ladder uses
    this; the contract test is
    `test_final_architecture_contracts.py::test_capability_request_is_bounded_to_configured_cap`.
12. **Incremental commits are mandatory** for long slices. Slice 2's first attempt ran ~1h
    then died on a 300s stream-chunk timeout and lost **all** unpersisted work (clean tree,
    no stash). Every build subagent on a long slice MUST `git commit -am "wip(sN): <what>"`
    after each milestone. The main agent squashes WIP commits after the slice lands green.

## 6. Remaining slices (execute in this order)

### Slice 3 — Commerce detail cascade + structured floor unification (extraction-cascade T4)

Sequence: after Slice 2 lands green. Detail-only, does not touch listing.

- Add `run_detail_cascade(request, reader, spec)` to `extraction/cascade.py`: structured
  floor (JSON-LD / microdata / OG / script-JSON via existing `collectors/jsonld.py`,
  `js_state.py`, `metadata.py`) → existing `harvest_ecommerce_detail` DOM pipeline. Keep
  `resolve`/`publish`/variant logic untouched. **No `surface ==` branch** — route by
  `SurfaceSpec`.
- `adapters._harvest_detail`: compose via `run_detail_cascade`; preserve
  `harvest_compiled_recipe` fast-path (becomes recipe-replay in LEARN-ONCE slice).
- Add per-surface flag `CASCADE_ECOMMERCE_DETAIL_ENABLED` (default True) in
  `core/config/cascade.py`; legacy path when False.
- Tests: extend `test_extraction_baseline.py` + `test_extraction_contract_behavior.py`
  (commerce-detail regression parity on existing fixtures) and assert structured-floor-first
  ordering via `stage_outcomes`. Run those + `test_extraction_variant_behavior.py`.
- Prove flag ON/OFF byte-identical output on existing commerce-detail fixtures before
  declaring done.

### LEARN-ONCE tier (extraction-cascade T5)

Sequence: after Slice 3 (needs a listing floor + a detail floor real). **Do NOT re-plan the
recipe-scope decision** — it is settled in `DECISIONS.md`: scope key =
`(domain, surface, route_pattern)`; auto-learn on first crawl when `llm_enabled` + floors
empty for a NEW template; most-confident recipe replays until an operator changes it (via
existing `ExtractionOperatorLabel`); self-heal + escalate mirroring
`crawl/profile/acquisition_contract.py`; reuse existing `extraction_memory` tables; prefer
storing confidence in the recipe payload / version ordering before adding a column.

- Port verbatim from the archive tag (frozen, storage-free, no discovery in the executor):
  `core/extraction_memory/recipe_contracts.py`, `recipe_executor.py`, `recipe_transforms.py`,
  `recipe_artifacts.py`.
- Write **NEW** `core/extraction_memory/recipe_compiler.py` (main-owned; the branch's
  compiler is rejected):
  - Inputs: `ExtractionRequest` **capture bundle + flat-map ONLY**, `SurfaceSpec`/
    `ListingSchema`, LLM client
    (`connectors/llm/provider_client.call_provider_with_retry`).
  - ONE model call over `build_scoped_flat_map(doc)`: asks for `{field: path}` bindings +
    (listings) the repeated record-root path. Prompt/task config in `core/config/cascade.py`
    + `connectors/llm/prompt_rendering`.
  - **Hard grounding gate:** each proposed binding must resolve to a real node/value on the
    page (reuse `model_runtime._value_is_grounded` / `_grounded_evidence`). Ungrounded
    bindings dropped; if a required binding (title/url/record-root) fails, **NO recipe is
    persisted** (honest empty). The model never emits field values — values are always
    re-read and re-grounded from the page every run.
  - Output: `ExtractionRecipe` (`extraction_recipe.v2`), persisted via
    `persistence/extraction_memory.upsert_recipe` + `compile_recipe_layers`,
    `ensure_template` / `create_release_snapshot`, keyed by `(domain, surface, route_pattern)`.
  - **Invariant: the compiler MUST NOT read `record_extraction_result` published records** —
    only the capture/flat-map. Add an architecture test enforcing no import path from the
    compiler to publication/records output.
- Engine/cascade wiring: replace the ecommerce-detail-only `_compiled_recipe_template` +
  `harvest_compiled_recipe` gate with a surface-agnostic `execute_recipe` replay path for any
  surface with a matching compiled recipe. Replay success → `extractor_tier="recipe"`. Drift
  (grounding fails) → fall through to floors, and if still empty + `llm_enabled` + new
  template, invoke the compiler once → `extractor_tier="llm"`. Retire `model_runtime.py`'s
  ecommerce-detail-only ML fallback from the live cascade (keep the grounding helpers for the
  compiler gate). Sentinel/challenger stays optional and read-only.
- Config in `core/config/cascade.py`: recipe scope key (`CASCADE_RECIPE_SCOPE_KEY`, already
  present), LLM-learn enable (`CASCADE_LEARN_ONCE_TIER_ENABLED`,
  `CASCADE_LEARN_ONCE_AUTOLEARN_ON_FIRST_CRAWL`, already present), per-surface learn
  allow-list, stale-failure threshold (`CASCADE_RECIPE_STALE_FAILURE_THRESHOLD=3`).
- Tests: port `test_recipe_contracts.py`, `test_recipe_executor.py` from the archive tag;
  new `test_recipe_compiler.py` (grounded → persisted; ungrounded → rejected; required-field
  ungrounded → no recipe; **compiler ignores published records present in the bundle** —
  invariant test); extend `test_extraction_architecture.py` (exactly one records producer;
  compiler has no import path to publication output); new `test_learn_once_replay.py` (first
  crawl LLM stub learns; second crawl replays with LLM stub asserted NOT called; drift
  fixture forces recompile).

### Slice 4 — Job detail + surface-agnostic escalation ladder + verdict fixes (extraction-cascade T6)

Sequence: after Slice 2 (job listing) and LEARN-ONCE. This slice owns
`result_building.retry_request` and the `contracts`/`extraction_loop` verdict items.

- `extraction/jobs.py::collect_job_detail` / `adapters._harvest_job_detail`: route through
  `run_detail_cascade` (structured JobPosting floor → DOM); read the rendered artifact set
  (the shared `LISTING_HTML_ARTIFACT_IDS`-style set, not only raw `"html"`).
- `targeting.py`: add URL-based disambiguation for `job_detail` (mirror
  `_select_product_by_url`) so multi-`JobPosting` JSON-LD (similar-jobs widgets) no longer
  trivially triggers `AMBIGUOUS_JOB_ROOT`; disambiguate by requested URL first.
- `result_building.retry_request`: emit `CapabilityRequest` for `job_listing`/`job_detail`
  (empty/shell → `rendered_html`; missing structured → `network_payloads`), not only
  ecommerce.
- Verify Phase 0 already: `CapabilityRequest.max_attempts` bound relaxed and
  `extraction_loop.py` `UrlVerdict` Literal `"listing_failed"` → `"listing_detection_failed"`.
  If present, don't redo; add the `test_verdict_literal.py` coverage.
- `crawl/pipeline/retry/stage.py`: honor the surface-agnostic ladder (loop up to configured
  rung count instead of the hard `browser_escalation_count >= 1` cap) — bounded, honest
  exhaustion.
- Tests: new `test_job_detail_cascade.py` (JobPosting structured floor; similar-jobs widget
  disambiguated by URL; rendered artifact read); extend `test_extraction_surface_behavior.py`
  (job surfaces get a `RetryRequest` on empty/shell); new `test_verdict_literal.py`;
  component escalation test (multi-rung ladder reaches browser+network then exhausts
  honestly).

### Acquisition ladder slice (subplans/acquisition-ladder.md)

Sequence: coordinate with Slice 4's ladder work (shared `CapabilityRequest`/`RetryRequest`
contract). Owns NEW `backend/app/acquisition/listing_cards.py`.

- Honest verdict + failure classification (P0).
- Surface-agnostic escalation ladder — contract + declare + fulfill (HTTP → browser →
  browser+network), bounded by `CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP`.
- Network-payload capture on rung 2 + `network_json` persistence.
- **Unified surface-aware card owner** — collapse the four card forks into
  `acquisition/listing_cards.py`; job-listing rendered read + shared quality gate.
- Browser readiness: reject loading/search shells. `diagnose.json` discovery diagnostics.
- Uniform `card_count` semantics across surfaces.

### Cross-cutting close-out (subplans/crosscut-migration.md)

- **Eval-gated per-surface selector deletion** — only after the cascade beats the selector
  baseline for that surface on the eval harness (`backend/eval/`). NEVER delete a working DOM
  floor before the cascade proves ≥ baseline. This is the last step per surface.
- Live-constant relocation for any remaining inline constants.
- Fix any remaining stale extraction docs (`docs/CODEBASE_MAP.md`,
  `docs/backend-architecture.md` were fixed in Phase 0 — verify still accurate).

## 7. Per-slice close-out checklist (every slice)

1. Squash WIP commits into ONE clean `feat(extraction): Slice N — <surface>` commit.
2. `git diff --name-only <prior-slice-tip>..HEAD` — confirm no foreign ownership file changed.
3. Focused pytest green + `ruff check` clean + `import app.main` clean.
4. Flag ON/OFF regression evidence (byte-identical on existing fixtures for the ON→OFF
   legacy path) where a per-surface flag exists.
5. Update the architecture manifest budgets if modules were added/grown; note bumps in the
   commit message.
6. Run **Simplify** + **Review** subagents against the squashed slice diff
   (`<prior-slice-tip>..HEAD`); route findings verbatim back to the slice's build task via
   `send_message_to_task`; act on all feedback.
7. Push branch (`--force-with-lease` after a squash rewrite; never empty the branch below
   base).
8. Keep the todo list accurate.

## 8. Testing & PR close-out (whole feature)

- A `testing` subagent is set up and holding (Postgres migrated, venv clean). When all
  slices land, send it the **final committed slice list** + the **flag ON/OFF regression
  expectation** and tell it to execute. Frontend needs `corepack enable` + `pnpm install`
  before any AI-visibility browser smoke test.
- Present curated evidence (only artifacts that demonstrate the change); publish ONE Test
  Report via `test-report submit` with the right `--status`.
- Open the PR via `vflux_exec pr create` (NOT raw `git push`/`gh pr create`) once everything
  is green. Write a full PR description with a detailed `## Testing` section.

## 9. Branch/remote hygiene note (state as of this doc)

- Remote now has only `main`, `vorflux/extraction-cascade-rearchitecture`, and
  `vorflux/rearchitecture-plans`. All 7 stale dependabot PRs and the feature-branch PR were
  closed with their branches deleted.
- The deleted feature branch's content is preserved as tag
  `archive/extraction-v3-phase0-eval` (source of recipe primitives for LEARN-ONCE + Slice 4).
- `vorflux/rearchitecture-plans` was branched off an early Slice-2 WIP SHA (`4ddfa17`); it is
  an independent doc branch. If S2 history is squashed it will still point at the old WIP
  SHA — treat it as a standalone docs branch (or re-point it) rather than merging it into the
  work branch, to avoid a confusing divergence.
