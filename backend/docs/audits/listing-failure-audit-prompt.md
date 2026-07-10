# Audit Prompt — CrawlerAI Listing Extraction Failures & Architecture

You are auditing the listing-extraction subsystem of CrawlerAI (a selector-free,
LLM-assisted web extraction pipeline). Below is a concrete, evidence-backed
diagnosis produced from live run artifacts. Your job is to **independently verify
each claim against the code, judge whether the proposed architecture is sound,
and surface anything the diagnosis missed**. Do not take the diagnosis as ground
truth — confirm or refute each point with file/line evidence, then produce a
prioritized remediation plan.

---

## 0. System context (what the design is *supposed* to be)

The extraction cascade for a listing page (many records) is meant to run:

1. **Tier 0 — deterministic structured floor.** JSON-LD / microdata / network-JSON
   that grounds *every* discovered record → publish with zero LLM. Code:
   `app/extraction/listing_tier0.py` (`collect_deterministic_listing` →
   `collect_structured_listing` → `collect_network_listing` → DOM floor).
2. **Tier 1 — per-domain recipe replay.** A previously-learned binding recipe is
   replayed deterministically (no LLM). Code: `app/extraction/listing_generalized.py`
   (`run_listing_generalized`, recipe path).
3. **Tier 2 — generalized exemplar LLM.** One LLM call per newly-seen page: the
   model sees ONE exemplar record's flat-map and returns *which relative DOM path*
   holds each field (title/price/etc.); values are always read from the page
   (grounding gate), never from the model. Bindings compile to a recipe for future
   replay. Code: `app/extraction/listing_generalized.py` (`_acquire`).

**Record boundaries** ("where are the N products on this page?") are found
site-independently by `discover_listing_records` in
`app/extraction/listing_records.py` — via structural repetition of content-rich,
same-site, non-structural-URL anchors. No selectors, no per-platform branches.

**The five stated architecture principles** (must be preserved by any fix):
1. No brittle selector dependency.
2. LLM is a one-time setup cost / reusable intelligence, not a per-page crutch.
3. Simple HTTP crawls still work *without* any LLM.
4. Acquisition escalation is surface-agnostic.
5. New surfaces are added via typed schema only (`app/extraction/surfaces.py`).

---

## 1. Observed failure evidence (from live runs, today)

Artifacts live under `backend/artifacts/runs/<N>/results/<M>/{diagnose,record}.json`.
Four consecutive real runs:

| Run | Site (final_url host) | `record_count` | `boundary_count` | `model_invoked` | model_outcome | Reality |
|-----|----------------------|----------------|------------------|-----------------|---------------|---------|
| 25  | (generic)            | 0              | 0                | false           | `no_match`    | 20 candidate anchors → 1 accepted → 0 boundaries |
| 26  | (generic)            | 0              | 0                | false           | `no_match`    | same shape as 25 |
| 27  | workforcenow.adp.com | 0              | 0                | false           | `disabled`(*) | JS/SPA: 1 anchor total in server HTML |
| 28  | arcteryx.com         | 4              | 4                | false           | `not_considered` | **FALSE POSITIVE**: the 4 "products" are category-nav tiles |

(*) Run 27 shows `llm_enabled: false` in its stored settings — a run submitted
before the default-on flag change; treat its LLM-disabled state as expected for
that run, but its 0-boundary discovery result is still representative.

**Run 28 published records (from `record.json`) — verify this yourself:**
```
"Climb Footwear ..."  → https://arcteryx.com/ca/en/c/mens/footwear-climb/wid-...
"Hike Footwear ..."   → https://arcteryx.com/ca/en/c/mens/footwear-hike/wid-...
"Run Footwear ..."    → https://arcteryx.com/ca/en/c/mens/footwear-run/wid-...
"All Footwear ..."    → https://arcteryx.com/ca/en/c/mens/footwear?intcmp=
```
Every URL is a `/c/<category>/` **category landing page**, not a product. The run
reported `verdict: success`, `data_integrity: clean`, `trust_state: verified`.
A false success is worse than a zero — it silently poisons downstream data.

---

## 2. Diagnosis to verify (two independent root causes)

### Root cause A — category-nav tiles seed fake product records
- **Claim:** `discover_listing_records` → `_product_anchors`
  (`app/extraction/listing_records.py`) rejects a URL only via
  `listing_url_is_structural(url)`, which is
  `detail_url_is_collection_like(url) or detail_url_is_utility(url)`
  (`app/core/records/url_identity.py:612`).
- `detail_url_is_collection_like` checks only whether the **last** path segment is
  in `{collections, collection, category, categories, shop, catalog, products,
  jobs, careers}`.
- Arcteryx category URLs like `/ca/en/c/mens/footwear-run/wid-kjyr4dq9` have the
  category token `c` as a **middle** segment and a non-token last segment
  (`wid-kjyr4dq9`), so `listing_url_is_structural` returns **False**.
- **Verify:** run
  `python -c "from app.core.records.url_identity import listing_url_is_structural as f; print(f('https://arcteryx.com/ca/en/c/mens/footwear-run/wid-kjyr4dq9'))"`
  — the diagnosis says this prints `False` (bug). Confirm.
- Consequence: these nav anchors are content-rich (each has an `<img>`) and repeat
  homogeneously, so `_best_grid_children` accepts them as a product grid. The bad
  boundaries then pollute BOTH the Tier-0 DOM floor AND the Tier-2 LLM exemplar
  (the model would be shown a category tile as the "exemplar record").
- **Note the asymmetry:** the CSS collector `collect_ecommerce_listing`
  (`app/extraction/listing.py`) *does* reject these via
  `_listing_url_has_category_segment` + `LISTING_STRUCTURAL_CATEGORY_PATH_SEGMENTS`
  = `{c, categories, category, collections}` (checks *any* segment). So the two
  code paths disagree on what a category URL is. Confirm this inconsistency and
  decide the single source of truth.

**Questions for you:**
- Is middle-segment category detection the right fix, or does it risk rejecting
  legitimate product URLs that happen to contain `/c/`? Enumerate real-world
  collisions (e.g. a brand whose products live at `/c/<slug>`).
- Should `listing_url_is_structural` be unified with the CSS collector's
  category logic? Where should the canonical definition live?

### Root cause B — the LLM tier is gated *behind* deterministic discovery
- **Claim:** `run_listing_generalized`
  (`app/extraction/listing_generalized.py:147`) does:
  ```python
  boundaries = discover_listing_records(doc, page_url=page_url)
  if not boundaries:
      return ModelFallbackResult(outcome="no_match", artifact=artifact)  # LLM never called
  ```
- So on any page where structural discovery finds nothing (runs 25/26/27), the
  LLM is short-circuited BEFORE invocation. The LLM can only ever run on records
  that the brittle discovery *already found*.
- Combined with Root cause A: when discovery finds the WRONG thing (run 28),
  deterministic extraction "succeeds" and the LLM isn't triggered either.
- **Net effect the operator reported: "the LLM never fired once, ever."** Verify
  that this is structural, not a config problem. The diagnosis asserts config is
  healthy: DB has active `LLMConfig` rows for both `general` and
  `generalized_extraction` (provider `mistral`), runs 26/28 carry
  `llm_enabled: true` and a valid config snapshot, and the runtime artifact
  (`GENERALIZED_EXTRACTION_OPERATOR_RUNTIME_ARTIFACT`) is `approved/enabled` for
  all surfaces. Confirm by reading `_approved_artifact` / `_model_adapter` in
  `app/crawl/pipeline/record_extraction_stage.py` and
  `app/extraction/model_runtime.py`.

**Questions for you:**
- Is decoupling correct: when discovery yields 0 (or only structural/nav)
  boundaries, should the pipeline fall through to a **whole-page** generalized
  model pass (à la `run_model_fallback` for detail) so the LLM can *find* records,
  not just bind fields to pre-found ones? Judge this against principle #2 (LLM as
  reusable intelligence) and #3 (non-LLM crawls still work).
- If the LLM finds records on a 0-boundary page, how should those records be made
  *replayable* (principle #2) given the recipe mechanism currently keys on
  discovery-produced boundaries? Propose the boundary-independent recipe shape.
- What stops a whole-page LLM pass from re-introducing the run-28 category-nav
  false positive? (The model must be told to reject category/landing links.)
  Design the grounding/verification gate.
- Cost/latency: firing the LLM on every 0-record page is a DoS on your own token
  budget for pages that are genuinely empty (404s, walls, non-listings). Where is
  the guard that distinguishes "usable page, discovery missed it" from "nothing
  here"? See `_needs_contract_fallback` (`app/extraction/engine.py:402`) and the
  capture/acquisition outcome flags.

### Root cause C (secondary) — JS/SPA pages (run 27, ADP)
- ADP renders jobs client-side; server HTML has ~1 anchor. Neither discovery nor
  an HTML-only LLM pass can see records that don't exist in the captured HTML.
- **Verify:** is there a rendered/browser artifact for run 27, and did the
  extractor read the rendered DOM or the raw HTTP HTML? Check `_html_source`
  ordering (`rendered_html` should win over `http_html`) and whether browser
  rendering actually executed (`acquisition.method`, `browser_outcome`).
- This is a separate axis (acquisition, not extraction). Judge whether it should
  block the listing-extraction fix or be tracked independently.

---

## 3. Architecture-level questions (the real point of the audit)

1. **Boundary discovery is a single point of failure.** Both Tier 0 and Tier 2
   depend on `discover_listing_records`. If it under-detects (0 boundaries) or
   mis-detects (nav tiles), the whole cascade fails or lies. Is a single
   structural-repetition heuristic the right spine, or should there be an
   independent second opinion (LLM region proposal, visual/rendered segmentation)
   that can disagree with it? Propose the arbitration.
2. **No semantic backstop.** There is no check that a "product" record is
   *actually a product* vs a category/nav/promo. The URL-structure filter is the
   only guard and it is leaky (Root cause A). Where should a semantic gate live,
   and can it be deterministic (URL + DOM signals) before spending an LLM call?
3. **Silent false success.** Run 28 reported `verdict: success` /
   `trust_state: verified` on category tiles. What invariant *should* have caught
   "all N records are collection-like URLs"? Propose a publication-time trust gate
   (e.g., reject a listing whose records are ≥K% structural/collection URLs).
4. **Test/reality gap.** The unit suite
   (`tests/unit/test_extraction_listing_behavior.py`,
   `test_listing_record_discovery.py`) is green, yet live crawls fail. The tests
   assert the *discovery-first* design; they cannot catch failures caused *by*
   that design. Identify the missing test archetypes: (a) category-nav rejection
   with mid-path tokens, (b) 0-boundary page → LLM fires, (c) end-to-end
   "verdict must not be success when all URLs are collection-like". Recommend
   whether behavior tests should be driven from frozen real-site HTML fixtures
   (e.g. the arcteryx capture) rather than synthetic snippets.
5. **Diagnostic honesty.** `diagnose.json` reported `boundary_count: 4` and
   `data_integrity: clean` for garbage. What diagnostic signal would have made
   this failure visible without a human reading the URLs? Propose the metric.

---

## 4. Required output

Produce a report with:
- **A. Verification table** — for each claim in §1–§2, state CONFIRMED / REFUTED /
  PARTIAL with file:line evidence and (where cheap) a one-line repro command.
- **B. Missed issues** — anything in the listing path the diagnosis did not name
  (grounding gate holes, recipe-replay drift handling, network-listing path,
  same-site subdomain logic, locale-prefix URL restoration, etc.).
- **C. Architecture verdict** — is the discovery-first cascade fundamentally sound
  and needs patching, or does the LLM/discovery coupling need to be redesigned?
  Take a position; justify against the five principles.
- **D. Prioritized plan** — ordered fixes with blast radius, principle-alignment,
  and the specific test that would prove each fix (prefer real-HTML fixtures).
  Flag anything that would regress principle #3 (non-LLM crawls must keep working).

**Ground every conclusion in code and the run artifacts. Where the diagnosis is
wrong, say so plainly and show why.**
