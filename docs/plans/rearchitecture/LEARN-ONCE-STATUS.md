# LEARN-ONCE recipe tier — implementation status & handoff

**Branch:** `vorflux/extraction-cascade-rearchitecture`
**Base of this slice:** `a6eb772` (Slice 3 — commerce detail cascade)
**Last pushed checkpoint when this doc was written:** `442c791`
**Author context:** continuation of the selective rearchitecture (Phase 0 → Slice 1 commerce listing → Slice 2 job listing → Slice 3 commerce detail → **LEARN-ONCE** → Slice 4 job detail/escalation → acquisition ladder).

> **SUPERSEDED FOR STATUS (2026-07-16):** The single consolidated handoff is now
> `docs/plans/rearchitecture/SLICE-4-HANDOFF.md`. Trust that file for current
> finding status. This document is retained for its background/goal/design
> narrative; its per-finding status table below has been updated to match, but
> `SLICE-4-HANDOFF.md` is authoritative.

This document exists so any future agent (or human) can resume without re-auditing from scratch. Keep it updated as findings are closed.

---

## Goal of this slice

Add a "learn once, replay forever" extraction tier:

1. On the **first** crawl of a new `(domain, surface, route_pattern)` template, **only when** deterministic floors produced nothing **and** `request.llm_enabled` **and** config gate **and** the surface is in the learn allow-list, make **exactly one** LLM call to compile a **grounded recipe** (field → page-node bindings; the model proposes *paths*, never values).
2. Persist that recipe (reusing `extraction_memory` tables) and attach it to future runs' frozen release snapshot.
3. On **subsequent** crawls, **replay** the recipe deterministically with **zero** model calls (`extractor_tier="recipe"`).
4. On **drift** (recipe no longer grounds), fall through to deterministic floors and, after `CASCADE_RECIPE_STALE_FAILURE_THRESHOLD=3` failures, self-heal (suspend) — mirroring the acquisition-contract pattern. Operator-owned scopes are never auto-suspended.

**Hard invariants (do not violate):**
- Extraction (`app/extraction/`, sync `extract()`) is **storage-free** (INVARIANTS Rule 17 / AP-24). Learning + DB writes happen only in the **async** crawl pipeline (`app/crawl/pipeline/`), never inside sync `extract()`.
- Recipes may only **locate evidence**; they must **not** mint public records or derived identifiers directly. All values flow through the normal adapter **Resolve → Publish** authority (INVARIANTS Rule 3). `publication.py` must remain the **single** typed-record producer.
- Frozen release snapshots are immutable once a run is created (no mutable live state overlaid at load time).
- No `surface ==` / `surface is` branching in cascade bodies.
- No retailer literals. No abandoned/parallel migration.

---

## Commits in this slice (on top of `a6eb772`)

| SHA | What it does |
|-----|--------------|
| `7df332e` | Original LEARN-ONCE build: frozen recipe primitives (contracts/executor/transforms/artifacts) ported from `archive/extraction-v3-phase0-eval`; NEW grounded one-call `recipe_compiler.py`; surface-agnostic replay in `engine.py`; async learn seam `crawl/pipeline/learn_once.py` + `record_extraction_stage.py`; persistence helpers; drift self-heal; tests. **Had 3 critical + 9 high + 3 medium review findings — NOT shippable as-is.** |
| `93b0621` | **CRITICAL 1 + 2 fix**: unify release payload so real runs carry executable recipes (`release.v2`); freeze snapshots (stop overlaying live suspension at load); rework drift self-heal. |
| `fdaa2fe` | Align engine + tests with the unified release payload. |
| `921c33c` | **CRITICAL 1 proof**: `test_learn_once_production_replay.py` — learned recipe replays on a real subsequent run via the actual `create_crawl_run`/release path. |
| `442c791` | **CRITICAL 3 scaffold only**: `recipe_evidence.py` + `RECIPE_FIELD_FACT_TYPES_BY_SURFACE` in `field_mappings.py`. **NOT wired into the engine yet.** |

> When the slice is complete, all of the above will be **squashed into one** clean commit: `feat(extraction): add LEARN-ONCE recipe tier` on `a6eb772`. Until then, WIP commits are pushed so no work is lost.

---

## Review findings (from independent review of `7df332e`) and status

### CRITICAL
1. **Learned recipes never reached real runs** — `create_release_snapshot`/`build_release_payload` emitted `release.v1` and `compile_recipe_layers` dropped `EXECUTABLE` recipes, while `select_active_recipe` requires `release.v2`; learned snapshots had `run_id=None` and were never attached. **STATUS: FIXED** (`93b0621`), proven by real-run replay test (`921c33c`). Confirmed empirically by the testing agent against real Postgres.
2. **Frozen release mutated at load** — `load_release_payload` overlaid current template suspension onto stored snapshots, changing in-flight runs. **STATUS: FIXED** (`93b0621`) — stored payload returned unchanged; suspension applied only when building future snapshots.
3. **Replay bypasses resolver/publication authority.** **STATUS: FIXED + WIRED** (`7266a85`). `engine._replay_active_recipe` now routes through `recipe_execution_evidence(request, recipe, execution)` (engine.py:495) → normal `Evidence` → adapter resolve/publish. `publish_recipe_execution` is deleted (grep confirms zero references in `app/` and `tests/`).

### HIGH
4. **`job_listing` compiler emitted `apply_url` but `JobListingRecord` requires `url`.** **STATUS: FIXED** (`e47f0db`). Identity keyed on `is_listing` in `_identity_field` (listing = `url`).
5. **Learning runs before browser retry; can call compiler twice per URL.** **STATUS: OPEN — deferred to Slice 4** (SLICE-4-HANDOFF.md §4). Fix: learn only after the final attempt; per-URL "learning attempted" latch.
6. **HTTP-only capture consumes a model call but can't produce an executable recipe.** **STATUS: OPEN — deferred to Slice 4.** Fix: don't call the model until the rendered artifact exists.
7. **Listing recipes accept singleton record roots.** **STATUS: OPEN — deferred to Slice 4.** Fix: enforce `CASCADE_LISTING_MIN_REPEATED_RECORDS` at compile and every replay.
8. **URL/image bindings discarded the grounded model path** and broadened to `a[href]`/`img[src]`. **STATUS: FIXED** (`e47f0db`). `_attribute_binding` anchors to the exact grounded path; values stay scalar.
9. **Grounding validates against the full-page flat map, not the scoped/capped map.** **STATUS: OPEN — deferred to Slice 4.**
10. **Template-newness is race-prone; does not guarantee one model call.** **STATUS: OPEN — deferred to Slice 4.** Fix: durable transactional claim/lease keyed by `(domain, surface, route_pattern)`.
11. **Drift inferred from final emptiness, not the replay outcome.** **STATUS: FIXED** (`e47f0db`). Precise gate `_recipe_fields_suppressed`: drift = a grounded field suppressed in the published record; optional-contract-field partiality is not drift.
12. **Drift failures neither consecutive nor concurrency-safe; success never resets.** **STATUS: OPEN — deferred to Slice 4.** Fix: reset counter after success; update under `FOR UPDATE`/atomic.

### MEDIUM (all OPEN — deferred to Slice 4)
13. **Any domain/surface operator label disables auto-suspension** (ignores route/template/field/action). Fix: scope exemption to the exact recipe/template + explicit operator ownership/action.
14. **"One model call" allows provider retries** (`call_provider_with_retry` may issue `max_retries+1` requests). Fix: `max_retries=0` for LEARN-ONCE; add a production-client test.
15. **Detached executable snapshots (`run_id=None`) accumulate without a consumer.** Fix as part of the unified-release fix: stop creating detached snapshots (or add explicit activation + retention).

### Simplify follow-ups (do alongside, do not prioritize over correctness)
- Delete unused `RecipeBindingProposal` / `DiscoveryCompiler` and unused `DiscoveryResult` diagnostic fields if no valid use remains after the above.
- `ExtractionResult.recipe_candidate` is currently dead (only set in tests): either wire it through a real diagnostic path or remove it + candidate-only test assertions.
- Remove the no-op `if ...: pass` in `recipe_compiler._relative_css`; consolidate the repeated segment→CSS conversion and duplicated identity-field / `stable_id` logic.

Also per the plan: **retire the ecommerce-detail-only universal-model fallback from the normal live cascade** (currently structurally present but inert — nothing populates `runtime_snapshot["universal_model"]`), while keeping the optional Sentinel challenger and grounding helpers.

---

## Key files (owners)

- **Pure primitives** (`backend/app/core/extraction_memory/`): `recipe_contracts.py`, `recipe_executor.py` (pure interpreter — no discovery/storage), `recipe_transforms.py`, `recipe_artifacts.py`.
- **Grounded compiler** (main-owned, NEW): `recipe_compiler.py` — one model call over `build_scoped_flat_map`; hard grounding gate; must NOT import `record_extraction_result`, publication, `PublicRecord`, `result.records`, persistence/models.
- **Recipe→evidence bridge (CRITICAL 3, NEW/WIP):** `recipe_evidence.py` + `field_mappings.RECIPE_FIELD_FACT_TYPES_BY_SURFACE`.
- **Replay:** `backend/app/extraction/engine.py` `_replay_active_recipe` / `_recipe_result` (runs before deterministic floors; drift → `None` → floors).
- **Async learn/persist seam:** `backend/app/crawl/pipeline/learn_once.py` + `record_extraction_stage.py`.
- **Persistence:** `backend/app/persistence/extraction_memory.py` (`persist_learned_recipe`, unified release payload builder, drift counter). `select_active_recipe` in `core/extraction_memory/contract_runtime.py`.
- **Config:** `core/config/cascade.py` (flags, threshold, learn allow-list), `core/config/extraction_memory.py` (`EXTRACTION_RELEASE_VERSION`).

## Tests

- Unit: `test_recipe_contracts.py`, `test_recipe_executor.py`, `test_recipe_compiler.py`, `test_learn_once_replay.py`, plus architecture ratchet in `test_extraction_architecture.py`.
- Component (need Postgres): `test_learn_once_persistence.py`, `test_learn_once_production_replay.py`.
- **Test DB:** `TEST_DATABASE_URL=postgresql+asyncpg://postgres:crawlerai_dev_pw@localhost:5432/test_db` (the `crawlerai-db-1` docker container). Run: `cd backend && export PATH="$HOME/.local/bin:$PATH" && TEST_DATABASE_URL=... PYTHONPATH=. .venv/bin/python -m pytest <files> -q`.
- **Known pre-existing failures (NOT this slice):** 3 tests in `test_final_architecture_ownership.py` (LOC/complexity budget ratchets) fail identically on base `a6eb772` — legacy debt, out of scope.

## Reference: the eval corpus ("good output")

`backend/eval/` (loader `corpus.py`, `run.py`, `score.py`) + `backend/app/evaluation/` provide the labeled fixture/label harness for extraction **accuracy**. The labeled corpus (`fixtures/<surface>/*.html` + `labels/<surface>/*.json`) is the ground-truth reference for good extraction output. NOTE: in the current working tree these dirs contain only `.gitkeep`; the populated labels live in the `archive/extraction-v3-phase0-eval` tag (`git ls-tree -r archive/extraction-v3-phase0-eval -- backend/eval/labels`). Use these as the correctness reference when validating that a learned recipe reproduces known-good records.

---

## Process notes for the next agent (lessons learned)

- **Commit + push after every coherent milestone.** Long uncommitted build passes risk timeout/loss. Each critical/high finding should be its own WIP commit, verified with focused tests, before moving on.
- **Fix findings in dependency order**, not all at once: CRITICAL 3 (resolver-authorized replay incl. variants) → grounding/compiler correctness (4,6,7,8,9,14) → pipeline timing/concurrency/drift (5,10,11,12,13,15) → simplify + retire dead fallback.
- **Verify each fix against a real subsequent-run path** (component test with Postgres), not just hand-built snapshots — that gap is exactly why CRITICAL 1 slipped through the original build.
- Do **not** implement Slice 4 / acquisition ladder inside this slice.
