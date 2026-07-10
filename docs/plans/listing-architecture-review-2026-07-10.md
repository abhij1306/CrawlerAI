# Listing Architecture — Consolidated Review & Plan (2026-07-10)

**Status:** IN PROGRESS
**Active slice:** L2 — Surface-agnostic acquisition-escalation ladder

**Scope:** why listing crawls still fail, what of the target architecture actually
exists in the working tree, and the exact slices that close the gap. Anchored to
the five principles (the crux of listing+detail architecture):

1. No brittle dependency on selector-based architecture.
2. LLM is a one-time setup cost; future crawls reuse the intelligence.
3. Simple HTTP crawls work without LLMs.
4. The extraction/acquisition escalation loop is surface-agnostic.
5. A new surface = adding a typed schema, not a new pipeline.

---

## Part 1 — What actually exists (the plan doc is stale; the code is further along)

The core architecture **already exists and is correctly shaped**. Verified in the
working tree:

| Piece | Where | State |
|---|---|---|
| One shared cascade for all 4 surfaces | `app/extraction/engine.py:92` (`extract()`); listing routes by `listing_schema()` predicate, not surface branches (`engine.py:160`) | LANDED |
| Typed surface schema | `app/extraction/surfaces.py` — `SurfaceSpec` + derived `ListingSchema`; jobs & commerce listing share every module | LANDED (P5 ✓) |
| Tier 0 structured floor (JSON-LD, all-or-nothing URL-identity join) | `listing_tier0.py:collect_structured_listing` | LANDED |
| Tier 0 network-JSON floor (schema-driven repeated-array) | `network_listing.py` | LANDED |
| Tier 0 DOM floor (selector-free boundary discovery + record-local title) | `listing_records.py` + `listing_tier0.py:_dom_floor_evidence` | LANDED |
| Tier 2 exemplar LLM (flat-map ONE record; model picks paths, never values; deterministic apply + re-ground) | `listing_generalized.py` | LANDED |
| Tier 1 recipe persistence (`record_bindings.v1`) | `persistence/extraction_memory.py:943` (`_persist_record_binding_candidate`) → compiled into `compiled_recipe.record_bindings` (`:112`) → replayed via `recipe_store_from_snapshot` (`engine.py:165`) | **LANDED — plan doc Slice 4.4 "persistence is a follow-up" is stale** |
| No CSS-collector fallback for listing | `adapters.py:_harvest_structured_listing` — Tier 0 only; plan doc 4.3's "falls back to CSS collector" is stale | LANDED |
| Listing escalation seam (one rung) | `result_building.py:552` — `empty` + `!browser_attempted` → `rendered_html` retry | LANDED (partial) |

Principles 1, 3, 5 are substantially delivered. Live proof from the artifact runs:
dyson (14 records), arcteryx (6), ultipro (4) — all `listing_dom_floor`, zero LLM.

**So why do listing crawls still fail?** Not because the architecture is missing —
because of five specific gaps at its edges, all verified against real failures.

---

## Part 2 — Verified failure modes (runs 3, 5, 8 — the failing listings)

All three failures share one signature: acquisition reports OK
(`method=browser`, `status=200`, `browser_outcome=usable_content`) but the harvest
is **empty** (zero collectors produced evidence), the model is `disabled`, verdict
`empty`, failure code `insufficient_input_bundle` (misleading — the bundle existed).

Replaying `discover_listing_records` on the captured `page.html`:

| Run | Site | HTML | Anchors found | Boundaries | Root cause |
|---|---|---|---|---|---|
| 3 | paycomonline.net (jobs) | 36 KB React shell | 0 product/job anchors | 0 | Job rows are anchor-less (JS onclick nav); real data is in XHR JSON that was never captured |
| 5 | workforcenow.adp.com (jobs) | 22 KB shell | 0 | 0 | Same — SPA, data only in network payloads |
| 8 | vc5partners.com/jobs | 122 KB | 5 (all nav) | 0 | Job list rendered client-side from Bullhorn REST (`href="…bullhornstaffing.com/…'+job.id+'"` — a raw JS template in the HTML); detail URLs are **cross-host**, which `same_site` rejects anyway |

### The five gaps

**G1 — Single point of failure: anchor-based boundary discovery gates every tier.**
Both the DOM floor **and the generalized LLM tier** require
`discover_listing_records()` boundaries — `listing_generalized.py:182-184` returns
`no_match` *before any model call* when discovery finds nothing. When discovery = 0
the LLM cannot help even when enabled. The escalation loop terminates at a
heuristic instead of at intelligence. (Detail has no such gate: its model fallback
flat-maps the whole page.)

**G2 — Discovery invariants are commerce-shaped.**
- `same_site` requirement: job boards routinely link off-host to an ATS
  (Bullhorn/Greenhouse/Lever). Run 8 fails on this alone.
- href-anchor requirement: Paycom/ADP cards are buttons/divs with JS navigation.
- `_is_content_rich` (`listing_records.py:60`): image OR price-signal OR
  exactly-one-link+≥3-words. Job cards have no image, no price, and often 2+ links
  (title + apply). Commerce bias in a module that claims to be surface-agnostic.

**G3 — The escalation ladder has one rung and it's usually already spent.**
`retry_request` for listings fires only when `!browser_attempted`. All three
failures had `method=browser` already → retry is `None` → dead end. There is no
escalation to network-payload capture, scroll/traversal, or longer render waits —
and no LLM at the end of the ladder. This is the biggest miss against principle 4.

**G4 — Failure classification lies.**
Capture-OK + zero-boundaries is reported as `insufficient_input_bundle`. INVARIANTS
§7 already promises `listing_detection_failed`; it is never emitted. Every agent
that debugged these runs was pointed at the wrong layer.

**G5 — "LLM as one-time cost" is unproven end-to-end and has no enablement story.**
The whole chain exists (acquire → `recipe_candidate` → persist → compile →
snapshot replay) but: (a) nothing defines when listing LLM is enabled in
production — detail got Slice 3.3's per-(domain,surface) gate, listing has none;
(b) replay depends on a **frozen release snapshot being rebuilt** after the
candidate lands — no test proves run-2-replays-with-zero-calls through a real
release; (c) the failing job runs captured **no network artifacts at all**, so the
network floor could never fire.

Also: the plan's "Out of scope (acquisition, not extraction) — note them, don't
chase them" wall parks the SPA-shell runs. Those are **the majority of real listing
failures**. The wall is right that extraction must not do acquisition's job; it is
wrong to leave the loop with no owner. The bridge is G3's ladder: extraction
*declares* capability needs; acquisition fulfills them.

---

## Part 3 — The plan

Ordered so each slice is independently verifiable against the existing captured
runs. No new surfaces, no per-site code anywhere.

### Slice L1 — Honest failure taxonomy + discovery diagnostics
**Small; unblocks all debugging.**
**Status:** DONE (2026-07-10)
- When capture is OK, surface has a `listing_schema`, and discovery yields zero
  boundaries → classify `listing_detection_failed` (per INVARIANTS §7), not
  `insufficient_input_bundle`.
- Emit discovery diagnostics into `diagnose.json`: candidate anchor count,
  rejected-anchor reasons (structural-url / cross-host / hidden), grid candidates
  considered, content-rich rejections.
**Verify:** runs 3/5/8 re-diagnose as `listing_detection_failed` with reasons;
run 10/13 (detail) unchanged.

### Slice L2 — Surface-agnostic acquisition-escalation ladder
**Extraction declares; acquisition fulfills. One ladder for all listing surfaces.**
**Status:** IN PROGRESS (2026-07-10)
- Extend `retry_request` for `listing_schema` surfaces beyond the single rung:
  1. `!browser_attempted` → `rendered_html` (exists today)
  2. `browser_attempted` + zero evidence + no `network_json` artifacts →
     `("rendered_html", "network_payloads")` with traversal/scroll requested
  3. ladder exhausted → honest `listing_detection_failed` (never a fake success)
- Ensure listing browser profiles actually persist captured XHR/GraphQL responses
  as `network_json` artifacts (Slice 5.1's `network_exchanges.json` machinery) so
  `network_listing_floor` can fire.
**Verify:** paycom/adp re-runs reach `network_listing_floor` from their XHR JSON
(their job data is in API responses) with **zero LLM**; the ladder code contains no
surface branches — commerce and jobs take the identical path.

### Slice L3 — De-commerce the discovery invariants
**Status:** IN PROGRESS (2026-07-10)
- `_is_content_rich` → schema-driven record signals: keep image/price for
  commerce; for jobs accept text-structured cards (≥N words / date / location
  pattern). Alternatively: drop per-child richness when grid homogeneity is high —
  repetition is already the discriminator.
- Identity: accept **cross-host** detail URLs when the repeated grid consistently
  targets one foreign host (generic rule — "the grid's own host", not an ATS
  allowlist). For anchor-less cards, allow identity from repeated structure +
  record-local stable key when no href exists.
**Verify:** replay harness on captured pages — vc5partners boundaries > 0;
dyson/arcteryx/ultipro record counts unchanged (no regression).

### Slice L4 — LLM boundary acquisition (kill the single point of failure)
- When discovery yields zero boundaries **and** LLM is enabled: flat-map the page
  (bounded, same budget machinery as detail), one model call returns the repeated
  record-root path pattern; derive boundaries; continue into the existing exemplar
  binding flow unchanged.
- Compile the boundary root-path into the recipe alongside bindings
  (`record_bindings.v2: {root_path, bindings}`) so replay stays zero-LLM.
- Grounding unchanged: the model chooses paths; the page supplies values; every
  record re-grounds every run; drift → re-acquire.
**Verify:** a fixture page with anchor-less cards publishes N records with exactly
one model call; second run replays with zero calls; disabled runs return honest
`listing_detection_failed`.

### Slice L5 — Prove "one-time cost" end-to-end + define enablement
- Integration test through the real persistence path: enabled run acquires
  (`model_invoked=True`) → `record_bindings` recipe persists → release snapshot
  rebuilds → second run replays (`invoked=False`, identical records, tier=recipe).
- Define listing production enablement mirroring detail's Slice 3.3: per
  `(domain, surface)` operator-recorded gate; document the recipe lifecycle
  (candidate → shadow → active → degraded → retired) for listing.
**Verify:** the two-run test is green in CI; dashboard metrics show listing tier
split and blended $/page.

### Slice L6 — Doc/status hygiene (prevents the next agent failing the same way)
- Plan doc: 4.2 status (landed as `listing_records.py`), 4.3 "falls back to CSS
  collector" (no longer true), 4.4 "persistence is a follow-up / NOTHING COMMITTED"
  (persistence is wired).
- INVARIANTS: lines 125 ("recipes store selectors") and 469 ("Selectors are
  recipes") contradict §7's "no CSS selectors" — rewrite to the V3 recipe
  definition.
- backend-architecture.md: remove/mark the pre-V3 selector-CRUD and Invoro-era
  listing stack sections; align the persistence claim with what L5 proves.

---

## Principle scorecard (today → after plan)

| Principle | Today | After |
|---|---|---|
| 1. No selector brittleness | ✓ (selector-free floors; discovery heuristics are the residual brittleness) | ✓✓ (L3/L4 remove shape assumptions) |
| 2. LLM one-time cost | mechanism ✓, loop unproven, no enablement | ✓ proven E2E (L5) |
| 3. HTTP-simple works w/o LLM | ✓ (verified live) | ✓ + network floor for API-driven sites (L2) |
| 4. Surface-agnostic escalation | ✗ one rung, dead-ends after browser | ✓ ladder w/ honest exhaustion (L2), LLM last rung (L4) |
| 5. New surface = typed schema | ✓ (`surfaces.py`) | ✓ (L3 removes the last commerce bias from shared code) |
