# Plan: Extraction V3 — Confidence-Tiered Hybrid Extraction (rebuild behind stable contracts)

**Created:** 2026-07-05
**Agent:** Claude (Fable 5) — research + authoring
**Status:** IN PROGRESS
**Touches buckets:** `app/extraction/*`, `app/core/records/*`, `app/core/extraction_memory/*`, `app/persistence/extraction_memory*`, `app/models/extraction_memory.py`, extraction-side of `app/crawl/pipeline/*`, new eval harness under `backend/eval/`, frontend Extraction Profile panel. **Explicitly NOT** acquisition (`app/acquisition/*`), fetch runtime, or run orchestration.

---

## Goal

Replace the *implementations* behind CrawlerAI's extraction tiers so that data quality no longer depends on brittle, per-site selectors surviving unchanged. Extraction becomes a **confidence-tiered cascade** — deterministic structured sources → compiled recipe (cache hit) → grounded LLM generalized extractor (cache miss / fallback) → optional vision — over a single **flat path→text representation**, with a **hard grounding gate** so no LLM value is trusted unless it resolves back to a real node in the captured page. A page is never left unextracted or silently degraded because a recipe is missing or has drifted; a bad/missing recipe becomes a *cost* problem, not a *correctness* problem.

Done looks like: on the **commerce-detail** cell (the only cell the current corpus can prove — see Corpus Reality), the new engine beats the current engine on a newly-built eval set, with the generalized tier alone (no recipe) achieving high field-level accuracy on cold-start pages, and a human-in-the-loop **Extraction Profile** (the extraction analog of the existing acquisition profile) letting an operator pin sources/bindings for hard sites. Jobs and listing surfaces follow the identical architecture but ship **only after** a corpus for each is built (they have zero ground-truth pages today). All of this ships behind the **existing** `ExtractionResult` / `CapabilityRequest` / `DiagnosticSummary` contracts — the acquisition→extraction and extraction→persistence seams do not change.

### Replace the selector architecture — keep the outer contract, delete the brittle core

Investigation of the current tree settled the "rebuild vs migrate vs new repo" question (chosen on the "fewest tokens, least debt" criterion), **and identified exactly which code is the brittle core that must be deleted, not wrapped.** The failure mode the user has fought for months is selector-based field binding; a plan that leaves it alive as a fallback keeps the disease. It does not survive here.

What we **keep** (the outer shell — it is correct and already anticipates V3):
- The extraction surface is **consolidated** in one package: `app/extraction/*` (~15.5k LOC). There is no parallel/legacy `app/extract/*` system; the engine entry is `app.extraction.extract` (`engine.py`).
- The **contracts already encode the V3 target**: `DiagnosticSummary.extractor_tier: "blocked" | "deterministic" | "recipe" | "ml" | "llm"`, `SentinelDriftState`, `SentinelObservation` (challenger comparison), `ContractOutcome`, `CapabilityRequest` (re-acquisition), rich `FailureTaxonomy`. The acquisition→extraction seam (`request_from_acquisition_result`) and extraction→persistence seam stay byte-compatible.

What we **delete** (the brittle selector core — verified in the tree):
- **`collectors/dom.py` (1,196 LOC) is a hardcoded per-field CSS selector bank** — `DETAIL_BRAND_DOM_SELECTORS`, `DETAIL_DOM_PRODUCT_ROOT_SELECTORS`, `DETAIL_DOM_DESCRIPTION_SELECTORS`, `DETAIL_DOM_OFFER_SELECTORS`, and `collect_requested_fields()` iterating CSS selectors. This *is* the "generic heuristics fail on new sites" engine. It is gutted to a flat-map builder + generic record-container discovery (a few hundred lines); the per-field selector banks are removed.
- **A "recipe" today literally is `selector_rules`** (`engine.py:414`, `compiled_recipe.get("selector_rules")`). This binding is deleted and `recipe` is redefined (below) to hold **zero authored selectors**.
- **The persisted-selector subsystem** — `core/records/selectors_runtime.py` (256), `crawl/domain_memory_service.py` (281, selector-rule composition), `models/domain_memory.py` (80), `api/selectors.py` (224), `schemas/selectors.py` (70), `core/config/selectors.py` (234) — the store/replay/self-heal of CSS selectors per `(domain, surface)`. Removed once the eval gate proves the generalized tier holds without it. (`BUSINESS_LOGIC.md`'s `selector_self_heal.py`/`selector_auto_learn.py`/`field_value_dom.py` names are stale — those files no longer exist; the live selector surface is the six files above.)

Why deletion is safe and not a leap: **selectors are the wrong primitive for "works on new/changing sites."** NEXT-EVAL puts DOM-only LLM extraction over a flat path→text map at **0.957 F1** vs the heuristic-selector baseline at **0.083** — the DOM-only site selectors handle *worst* is the site the generalized tier handles *best*. The only thing selectors buy is zero marginal cost, which is affordable at ≤20k pages/day. Deletion is **eval-gated**: it happens only after the generalized tier is measured to beat baseline on the 94-site corpus (Phase 0), so the floor is never removed before its replacement is proven.

---

## Evidence base (research summary, with citations)

This plan's design choices are grounded in verified 2025–2026 evidence, not the prior draft's unverified citations. Key findings that **survived verification**, and the ones that **changed**:

**1. Representation is the single largest accuracy lever — verified and stronger than claimed.**
NEXT-EVAL (Kim, Kim, Jeong 2025, arXiv:2505.17125), 164 real pages / 12,278 records, Gemini-2.5-pro, zero-shot. Exact Table 2 results:

| Method / input | Precision | Recall | F1 | Hallucination rate |
|---|---|---|---|---|
| MDR (heuristic baseline) | 0.075 | 0.159 | **0.083** | 0.000 |
| LLM + Slimmed HTML | 0.122 | 0.097 | **0.101** | **0.915** |
| LLM + Hierarchical JSON | 0.493 | 0.380 | 0.405 | 0.598 |
| LLM + **Flat JSON (XPath→text)** | 0.994 | 0.939 | **0.957** | **0.031** |

The Flat-JSON representation is a key→value map where each key is an **absolute XPath** and each value is that node's text (class/id/style stripped, only text-bearing nodes). It turns extraction from a *generation* problem into a *selection* problem, which is also what makes grounding cheap. Caveat learned in verification: the flat map is *token-heavy* — avg **116,698 tokens** for these listing-heavy pages (up to 913 records each). For a single scoped **product detail region** it is small (~2–8k), but for large **listing** pages it must be scoped/paginated (see §Representation). Source: https://arxiv.org/html/2505.17125

**2. "LLM at runtime is reliable *only when grounded*" — verified.**
McGill "Generative AI for Data Scraping" (Cohen & Hage-Youssef 2025, SSRN 5353923): ~3,000 pages across Amazon, Cars.com, Upwork; LLM methods show "resilience to layout changes." But naive URL-browsing extraction "varied anywhere from 0% to 100% correct" on *the same URL, model and prompt* — "unsuitable for real-world workloads." Conclusion: constrain the model to grounded, materialized page content; never let it browse or free-generate. Sources: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5353923 , https://dev.to/astro-official/effectiveness-of-traditional-and-llm-based-methods-for-web-scraping-dh6

**3. "Compile once, run LLM-free" is a real, mainstream pattern — with a documented failure mode we must design around.**
crawl4ai's `JsonCssExtractionStrategy.generate_schema()` calls an LLM once on sample HTML, then extracts LLM-free forever. **Documented gotcha:** single-sample schema generation produces fragile selectors like `tr:nth-child(6)` that break across pages; the fix is **multi-sample** compilation. This is direct evidence for compiling recipes from *several* captures, not one. Source: https://docs.crawl4ai.com/extraction/no-llm-strategies/

**4. Wrapper-induction degrades on the *live* web — recipes must be treated as a decaying cache, not a solution.**
AutoScraper (EMNLP 2024, arXiv:2404.12753) hit 88.7 F1 on SWDE, but LiveWeb-IE (2026, arXiv:2603.13773) shows wrapper methods drop materially on *current* pages vs the 2010s SWDE snapshots. This validates the core thesis: a compiled recipe is a cache of a generalized extraction, and needs a live fallback + drift detection, never a one-shot.

**5. Industry convergence (architecture references only — no vendor dependency).**
Kadoa: AI agents *generate deterministic code*, auto-regenerate on breakage, and validate with **"reverse search"** — verifying each output value was present in the raw input before trusting it (this is exactly our grounding gate). Source: https://www.kadoa.com/blog/autogenerate-self-healing-web-scrapers . Diffbot (vision page-classification + corpus-trained extraction) and Zyte (cross-site ML + LLM "custom attributes, no selectors") corroborate the "generalized extractor as the floor" model.

**6. Model landscape (for the cost model; validate against real bundles before finalizing).**
Llama 4 Maverick median pricing ~$0.35/M input, $0.85/M output, 1M-token context (https://artificialanalysis.ai/models/llama-4-maverick) — consistent with the user's finding that Llama-family beat frontier models for their extraction task. Purpose-built cheap tier option: **NuExtract 3** (NuMind), a 4B **Apache-2.0** extraction VLM, 131K context, template-driven, self-hostable, reported to beat a 9B Qwen on NuMind's extraction benchmark (https://huggingface.co/numind/NuExtract3). This is a strong candidate for a self-hosted cheap/vision tier.

---

## Reconciliation with the V2 architecture doc (which doc wins, per topic)

The prior `CrawlerAI Extraction V2 — Final Architecture` doc and this plan disagree on the spine. **Where they conflict, this plan wins** — but V2's record-discipline is adopted wholesale. Agents must read this table before treating anything in the V2 doc as authoritative.

| Topic | V2 doc says | This plan (V3) | Why |
|---|---|---|---|
| Runtime LLM (V2 Law #20) | "Healthy runtime uses **no** LLM" | **Rejected.** Grounded LLM is a first-class, budgeted runtime tier | Law #20 is the exact assumption that has failed for months — a compiled recipe is a bet on structure holding. Verified evidence (NEXT-EVAL 0.957 vs 0.083) says the LLM-over-flat-map *is* the reliable floor. |
| Selectors / recipe as durable config | "The recipe is the single durable extraction configuration"; DOM adapter kept | **Rejected.** Selector banks + persisted-selector store **deleted**; recipe redefined as source-pin + schema, zero authored selectors | The user's stated core problem; see "Replace the selector architecture". |
| Record-first extraction (V2 §7–§14) | establish records → verify identity → attach sources (4 mechanisms) → bind fields; no global candidate pool; completeness ⟂ confidence | **Adopted wholesale** as the control flow *inside* the tiers | Orthogonal to selectors-vs-LLM; directly fixes the audit's cross-product-image contamination (5 pages) and mis-attributed-variant defects. This is V2's best contribution. |
| Per-field source selection (V2 §14) | no universal cascade; recipe picks source order per field | **Adopted.** The tier *cascade* is mechanism; per-field source order is orthogonal and preserved | Both compose: a field's value may come from structured, recipe-pinned, or grounded-LLM source, chosen per field. |
| CaptureBundle / network / API / GraphQL-APQ / interactions (V2 §5, §15–19) | rich bundle with `network_exchanges`, request templates, APQ, interaction snapshots | **Deferred to Phase 5** (new, corpus-gated) | Audit proved the saved corpus is **HTML-only** (`network_payloads_captured: false`). This machinery is unexercisable until a network-capturing corpus exists. Phase 1 uses DOM + embedded `<script>` JSON, which *is* in the captures. |
| Evidence model (V2 §31) | "no universal immutable evidence ledger"; compact field traces | **Keep the existing lightweight per-field provenance** (`FieldEvidenceState`, source path) — needed for the grounding gate and HITL review; do not adopt V2's heavier recipe schema, do not build a new ledger | Grounding + operator review both need per-field source provenance; the current contract already carries it. |
| New `app/extraction_v2/` package | greenfield parallel package importing none of the old code | **Rebuild in place** behind the stable `ExtractionResult` contract; new tier code imports **none** of the old selector/field-binding code, but reuses the good contracts | Fewer tokens/less duplication than a parallel package; the isolation V2 wanted is achieved by the deletion slices + "no old-collector imports" rule, not by forking the contract. |
| Drift + human-gated repair (V2 §24–25) | conservative aggregation, no auto production mutation | **Adopted** (V3 Slice 2.3) — plus automatic *per-page* fallback (not recipe replacement) | Repair of the recipe stays human-gated; only the per-page correctness fallback is automatic. |
| Four surfaces, setup budget, Crawl Studio (V2 §1, §28, §32) | commerce/jobs × listing/detail; ~$5/template; no-code recipe editor | **Adopted**, but corpus-gated: only commerce-detail is proven now (Phase 4 for the rest); Crawl Studio editor becomes the Extraction Profile (Slice 3.2) | Matches measured corpus scope. |

### Record-first extraction (adopted from V2 §7–§14 — the control flow inside every tier)

The tiers describe *where a value comes from*; record-first describes *the order of operations*, and it is mandatory regardless of tier:

1. **Establish records first** — product / variants / offers / (job / listing-items) via ordered establisher chains. A record boundary may come from a structured source (Tier 0) *or* from the grounded LLM proposing boundaries on the region-scoped flat map (Tier 2 — exactly what NEXT-EVAL's flat-map extraction does well). Never a global candidate pool.
2. **Verify identity before attaching anything** — product id / sku / canonical-URL must match the requested page; listings use normalized-URL overlap with recommendation/sponsored/nav regions excluded. This is the gate that kills the audit's cross-product image contamination. A record that fails identity is never published (V2 Law #14).
3. **Attach sources only via the four explicit mechanisms** — same-record source, key join (e.g. variant SKU ↔ DOM `data-sku`), structural containment, or validated single-record assertion. No fuzzy global resolver. The **grounding gate lives here**: an attached LLM value must ground to the established record's own source region, not anywhere on the page.
4. **Bind fields per-field-source-order** — the value comes from the highest-priority *available* source for that specific field (structured, recipe-pinned, or grounded LLM), after the record is established.
5. **Report completeness ⟂ confidence** — variant-matrix completeness (expected option-count from controls vs extracted) is a separate axis from per-field confidence. A grounded, high-confidence 5-variant result is still `partial` when 12 are expected. No sampled subset is published as a complete feed (V2 Law #13).

This makes the grounded LLM *safer than a naive whole-page call*: identity verification + record-scoped flat map + grounding jointly prevent it from inventing or mis-attributing cross-product data.

## Corpus reality (measured 2026-07-05 — this governs scope; see `chatgpt_audit/`)

A full-corpus audit (`chatgpt_audit/audit_report.md`, `summary.json`) measured all 94 captures. The numbers below are **authoritative** for this plan; agents must not re-estimate them.

- **Surface/domain skew — critical.** 91/94 are **commerce-detail**; **0 listing**, **0 jobs**, 3 other/unclassifiable (dirs 6, 79, 83). → The eval gate and selector-deletion gate can only be set for **commerce-detail**. Jobs and listing have **no ground truth** and are explicitly deferred (Slice 4.x) until a corpus exists. `jsonld_jobposting` presence is **0%** — jobs is entirely unproven.
- **Capture shape — confirmed.** Each dir = `page.html` + `diagnose.json` + `record.json`. `network_payloads_captured: false` — **embedded state exists only inside `page.html` `<script>` tags.** Platform parsers read script content, never a separate network payload. `record.json` is the *current engine output* (defective), **not** ground truth — eval labels must be human-verified.
- **Structured-source floor — strong for flat fields.** any_source **92.6%** (7 pages have none). Deterministic-only field recovery: title **93%**, primary_image **90%**, price **87%**, availability **84%**, sku **82%**, brand **80%** — but **sale_price 12%**, gtin **20%**, **variant_count 21%**. → title/price/image/brand/sku/availability are a real deterministic floor; **sale_price, gtin, and variants are LLM-tier responsibilities** on most sites.
- **Variants — the LLM tier is mandatory.** Of the ~36 multi-variant pages: **embedded_json 7, dom_only 17, partial 12** (single_sku 55). Deterministic goldmines cleanly cover **~7** variant pages; **~29 need DOM/LLM variant extraction.** (Audit's variant detector is imprecise — one "embedded" hit, `{"name":"off","value":false}`, is a feature-flag false positive — so treat 7 as an optimistic ceiling.) Variant matrix extraction is the **hardest sub-problem** and gets its own slice + metric.
- **Platforms:** unknown 37, shopify 21, nextjs_custom 20, sfcc 11, magento 4, woo 1. → Build platform parsers for **Shopify (`compare_at_price` gives sale price + full variant JSON), Next.js `__NEXT_DATA__`, SFCC/Redux** first; they cover ~52 pages. The 37 "unknown" lean on JSON-LD + the LLM tier.
- **Representation tokens (scoped flat map) — scoping is the linchpin and not yet robust.** Median scoped detail region ≈ **6–12k tokens** (cheap). But 2/10 samples show scoping failure: dir47 → **167 tokens** (found nothing) and dir94 → **162k tokens** (scoped nothing; raw HTML 1.2M). → Region-scoping **must** have a validated fallback and a hard token cap (see Slices 0.3/1.1); pathological pages route to chunking/vision.
- **Baseline to beat (current engine, 94 records):** 5 empty records, **13 missing price on commerce-detail**, **11 empty variants where the page has variants**, 5 likely image-contamination. ~14–20% defect rate. These exact counts are the numbers V3 must beat.

## Acceptance Criteria

All criteria below are scoped to **commerce-detail** (the only cell with a corpus). Jobs/listing criteria are identical but deferred to Slice 4.x.

- [ ] **Eval harness exists and is the gate.** `backend/eval/` builds a **human-verified** labeled eval set for the **91 commerce-detail** captures (exclude dirs 6, 79, 83), scores per-field precision/recall/F1 + variant-matrix accuracy + a hallucination proxy, runs deterministically offline. `python -m eval.run --baseline` reproduces the current engine's defect counts (**expect: 5 empty, 13 missing-price, 11 empty-variants**).
- [ ] **Flat path→text adapter** exists, shared by compiler and runtime generalized extractor, unit-tested to the NEXT-EVAL shape (absolute-path → text, class/id/style stripped). Includes **region-scoping with a validated fallback**: if the scoped region yields < 300 tokens or is missing core anchors, widen to full flat map; if full flat map > 60k tokens, chunk or route to vision. (Directly targets the dir47/dir94 scoping failures.)
- [ ] **Grounding gate** enforced: any `extraction_method="generalized"` value that does not resolve back to a real path/source is capped at `uncertain` (or `invalid` if required), never `verified`/`supported`. Measured grounding-failure rate < 5% on the eval set.
- [ ] **Cascade router** wires deterministic → recipe (cache hit) → generalized LLM (cache miss / identity-or-coverage failure, per-page) → optional vision, emitting the correct existing `extractor_tier`. Cold-start (no recipe) routes to generalized from first contact.
- [ ] **Generalized tier beats baseline on commerce-detail** with **zero recipes and zero selectors present** (cold-start correctness): price recovered on ≥ 90/91 (vs baseline's 78), 0 empty records (vs 5), and it must recover **sale_price** (baseline structured floor is only 12%). Recipe-tier then matches generalized at a fraction of the cost.
- [ ] **Variant matrices** meet a dedicated metric (Slice 1.5): per-variant price/availability/SKU on the ~36 variant pages, **beating the baseline's 11 empty-variant failures** — sourced from embedded state where present (~7) and from the **generalized tier for the ~29 DOM-only/partial pages**. Deterministic goldmines are a bonus, not the variant solution.
- [ ] **Extraction Profile (HITL)** lets an operator pin sources / field bindings / senses / required-flags per (domain, surface), persisted in extraction memory, consumed by the router, reflected in re-run output.
- [ ] `ExtractionResult`, `CapabilityRequest`, and the acquisition/persistence seams are **byte-compatible** with today; existing acceptance/replay tests still pass.
- [ ] Focused backend pytest for the new engine exits 0; blended $/page and grounding-failure rate emitted as metrics.

## Do Not Touch

- `app/acquisition/*`, `app/crawl/crawl_fetch_runtime.py`, browser/HTTP runtime — acquisition is settled and out of scope. The engine consumes whatever `request_from_acquisition_result` already produces.
- `app/extraction/replay.py`'s `request_from_acquisition_result` **input signature** — the acquisition→extraction seam. New adapters live *downstream* of it.
- The `ExtractionResult` / `PublicRecord` / `CapabilityRequest` public shapes — extend via already-present optional fields only (`extractor_tier`, `data_integrity`, `field_states`); do not rename or remove.
- `app/crawl/pipeline/persistence.py` record identity/dedupe and the public-record firewall — extraction feeds it unchanged.
- Data-enrichment (`app/data_enrichment/*`) and Public API v1 semantics.

## Explicitly In Scope For Deletion (not protected)

These are the brittle selector core and are **removed** (eval-gated, Slice 2.3). Do not preserve or "wrap" them:
- `app/extraction/collectors/dom.py` — per-field selector banks gutted to a flat-map builder + record-container discovery.
- `app/extraction/engine.py` — the `selector_rules` recipe path (`:414`).
- `app/core/records/selectors_runtime.py`, `app/crawl/domain_memory_service.py` (selector composition), `app/models/domain_memory.py`, `app/api/selectors.py`, `app/schemas/selectors.py`, `app/core/config/selectors.py`.
- Selector-promotion paths in `app/crawl/review/__init__.py` — replaced by the Extraction Profile (pins a *source*, not a selector).

**Deletion is surface-scoped and eval-gated.** Because only commerce-detail has a corpus, the `dom.py` selector banks and the persisted-selector store are removed **for commerce-detail first**, after the commerce-detail eval gate passes (Slice 2.3). The *code paths* stay physically present but disabled/guarded for jobs+listing until their corpora exist and their eval gates pass (Slice 4.x); only then is the shared selector infrastructure deleted outright. This prevents V3 from silently breaking the jobs/listing surfaces the old engine still serves.

---

## Architecture (target)

### The four tiers (map onto existing `extractor_tier` enum)

```
                      ┌─────────────────────────── Extraction Router ───────────────────────────┐
 CaptureBundle  ──►   │  Tier 0  deterministic   structured sources: JSON-LD / embedded JS state │
 (from acquisition)   │                          / platform endpoints (Shopify, SFCC, BC, Woo)   │  ──► ExtractionResult
                      │  Tier 1  recipe          compiled path bindings (cache hit)              │      (unchanged contract)
                      │  Tier 2  generalized     grounded LLM over flat path→text map            │
                      │  Tier 2b vision          screenshot + VLM (last resort, auto-gated)      │
                      └───────────────────────────────────────────────────────────────────────┘
```

- **Tier 0 deterministic** — no LLM, no per-site rules. Parse the universal structured sources every serious platform emits: JSON-LD `Product`/`JobPosting`/`ItemList`, microdata, OpenGraph, and **platform embedded state** (see Variant strategy). This is the free floor. It already partially exists (`collectors/jsonld.py`, `collectors/js_state.py`, `structured_sources` logic) and is *extended*, not rewritten.
- **Tier 1 recipe (redefined — zero authored selectors)** — a recipe is a **source-pin + field-schema plan**, not a `selector_rules` list. It records *which materialized source holds the record* (e.g. "Shopify `product.json`") and the field schema/senses to apply — the deterministic tier then runs against that pinned source with no per-field CSS. The only optional path-caching is **grounding-gated**: a compiler-derived path hint (from multiple captures) that is **re-verified against the live flat map every run and auto-falls-back to the generalized tier on any mismatch** — categorically unlike today's replay-a-CSS-selector-and-hope. For DOM-only sites with no stable structured source, the "recipe" is simply "call the generalized tier with this schema" — a cost note, not a selector. Consumed via the existing `contract_runtime` / extraction-memory release mechanism.
- **Tier 2 generalized** — the grounded LLM extractor. Input is the **flat path→text map** scoped to the record region. Output is constrained by JSON schema and **must pass the grounding gate**. This is `model_runtime.py` rebuilt around the flat map and promoted from "emergency fallback" to first-class tier.
- **Tier 2b vision** — screenshot + VLM, auto-selected only when the flat-map path fails grounding/coverage (canvas prices, obfuscation, image-only). Gated on cost/latency.

### Representation: flat path→text map (the core change)

A new adapter `app/extraction/representation/flat_map.py` converts a materialized source (DOM, or a JSON tree for embedded state) into an ordered map: `absolute_path → text/attribute`. Rules from NEXT-EVAL: strip class/id/style; keep only text-bearing nodes; absolute paths for unambiguous localization. **Two modes** because of the token caveat:
- **Detail:** scope to the main record region (reuse the structural-containment the engine already computes) → ~2–8k tokens → whole-region single call.
- **Listing:** the flat map of a 900-record page is ~100k+ tokens. Do **record-boundary discovery first** (Tier 0 / cheap heuristic finds repeated containers), then flat-map **one exemplar record** to compile a per-record binding, and apply it across the list — LLM sees one record, not 900. This directly uses NEXT-EVAL's finding while dodging its cost.

The same adapter feeds **both** the compiler (setup) and the runtime generalized tier — they are the same code path at two frequencies (setup caches the answer; runtime does not).

### Grounding gate (hallucination floor)

`app/extraction/representation/grounding.py`: a mechanical (non-LLM) check that every generalized value resolves to an entry in the flat map or another materialized source. `match_type ∈ {exact, normalized, none}`. `none` → capped at `uncertain`, or `invalid` for required fields. This is Kadoa's reverse-search and NEXT-EVAL's positional-grounding, and it is what separates "reliable generalized extraction" from "an LLM guessing." `model_runtime.py` already does a weaker version of this — it is hardened and made mandatory.

### `extraction_method` axis

Add `extraction_method: Literal["deterministic","recipe","generalized","vision"]` to the per-field state (`FieldEvidenceState`) as **provenance, orthogonal to confidence**. A grounded generalized value can legitimately reach `verified`. This does not change the public record shape (it lives in field states / diagnostics, already serialized internally).

### Recipe lifecycle (make "a recipe exists" non-binary)

`cold_start → candidate (shadow) → active → degraded (per-page generalized fallback while repair compiles) → retired`. Promotion `candidate→active` requires agreement with generalized-tier shadow extraction above a threshold across a minimum page count — not just the ~3 human setup pages. Reuses the existing `SentinelObservation` challenger machinery.

### Human-in-the-loop: Extraction Profile

Mirror the acquisition profile the user already trusts. A per-`(domain, surface)` `ExtractionProfile` in extraction memory lets an operator: pin the winning source ("use Shopify product JSON, ignore DOM price"), pin field bindings, add field aliases/senses (e.g. `sale_price_after_discount` vs `list_price` — the documented price-sense failure mode), and mark required fields. The router reads it before compiling/falling back. Easy sites (Shopify + JSON-LD) need no profile; hard sites get operator-authored accuracy, and the compiled bindings double as the "code snippets for developers" the user wants as a by-product.

---

## Cost model (directional — validate against real bundles)

Now grounded in **measured** corpus tokens (audit §6), not estimates. Median scoped detail region ≈ **6–12k input tokens**; Llama-4-Maverick median $0.35/M in, $0.85/M out.
- Typical page: ~9k in × $0.35/M + ~1k out × $0.85/M ≈ **$0.0040/page**.
- Worst case all-LLM at 20k pages/day ≈ **$80/day (~$2.4k/mo)** — the *cold-start ceiling*, not steady state.
- **Steady state is far lower:** the deterministic floor already fully answers the ~55 single-SKU pages' core fields (title/price/image/brand at 80–93%), so those cost ~$0 and only call the LLM for the gaps (sale_price, occasional variant). Only the ~29 DOM-only/partial-variant pages and the 7-page hard tail run a full LLM pass. Realistic blended cost lands **well under the $1000/mo target**.
- **Token-tail handling (measured risk):** pathological pages (dir94: 162k scoped) must be capped — chunk or route to vision above 60k tokens — or a single page could cost ~$0.06 and risk context limits. The scoping fallback (Slice 0.3) is what keeps the median at 9k instead of the tail.
- Self-hosted NuExtract-3 (4B, Apache-2.0) can push the cheap-tier marginal cost toward zero for batch — benchmark in Phase 2.

Token counts are now locked from `chatgpt_audit/summary.json → representation_tokens`; re-measure only if the flat-map builder's node-selection rules change.

---

## Slices

> Execution order is strict. **Phase 0 (eval) must land first** — accuracy is the top priority and nothing after it may merge without moving the eval metric. Each slice names files, the change, and a verify step.

Phases are strictly ordered. A slice may not start until every slice before it is `DONE`. "Beats baseline" always means the Slice 0.2 scoreboard on the **91 commerce-detail** pages.

## Phase 0 — Eval harness + primitives (must land before any tier work)

### Slice 0.1: Eval corpus + human-verified labels
**Status:** IN PROGRESS — harness and unverified label proposal writer landed; 8 human-verified seed labels added, full 91-page verification still pending.
**Files:** `backend/eval/corpus.py`, `backend/eval/labels/<dir>.json`, `backend/eval/README.md`
**What:** Register the **91 commerce-detail** captures from `backend/artifacts/runs/1/results/<N>/` (exclude dirs 6, 79, 83). For each, produce a **human-verified** gold label: core fields (title, description, price, sale_price, currency, availability, brand, gtin, mpn, sku, images, category) + the full variant matrix (per-variant option values, price, availability, sku). Bootstrap proposals from JSON-LD + `record.json`, but a human confirms/corrects each — `record.json` is **not** trusted (it carries the 13 missing-price / 11 empty-variant defects). Store the audit's variant bucket per page (embedded/dom_only/partial/single_sku) as label metadata.
**Verify:** `python -m eval.corpus --stats` prints 91 labeled, 0 unlabeled; every label validates against the label schema; variant-bucket counts match the audit (7/17/12/55).

### Slice 0.2: Scorer + frozen baseline
**Status:** IN PROGRESS — baseline defect gate landed, field counts/precision/recall/F1 and variant matrix scoring run on verified labels; `eval.run --engine v3 --tier generalized --no-recipes --no-selectors` now scores candidate extraction and fails closed on regressions. `--require-pass` makes the gate exit nonzero for CI. **Gate reworked for the 8-verified-label reality (2026-07-06):** full-corpus human verification is not feasible, so the gate no longer hard-blocks on `full_corpus_not_human_verified`. It compares the candidate against the current engine measured on the **same 8 verified pages** (`baseline_on_verified_labels`) — a non-regression bar on per-field F1 and defect counts — rather than against the frozen 91-page counts (kept in the report as `frozen_baseline_defect_counts` for reference). **Cascade gate retargeted (2026-07-07):** `eval.run --engine v3 --tier cascade` now runs the candidate across all 91 commerce-detail pages, gates full-corpus record/variant-drop defects (`empty_records`, `empty_variants_where_expected`) plus verified-label field F1, and separately reports `selector_deletion_unlocked` for Slice 2.1's no-recipe/no-selector deletion bar. Field-only misses do not block deletion; dropping full product/variant records does. The latest selector-free cascade gate passes: empty records 5→2, empty variants 11→11, generalized helps pages 3/32/81/90, and selector deletion is unlocked.
**Files:** `backend/eval/score.py`, `backend/eval/run.py`, `backend/eval/reports/baseline.json`
**What:** Per-field precision/recall/F1, variant-matrix accuracy (option-set + per-variant field match), and a hallucination proxy (value absent from source). `run.py --baseline` scores today's `app.extraction.extract` and freezes the report.
**Verify:** `python -m eval.run --baseline` reproduces the audit's defect counts (**5 empty, 13 missing-price, 11 empty-variants**) within ±1. This frozen scoreboard is the number every later slice must beat.

### Slice 0.3: Flat path→text adapter + scoping fallback
**Status:** IN PROGRESS — flat-map/scoping primitives, unit coverage, and `eval.representation --audit-samples` landed. Report shows non-empty capped output, dir47 fallback, and dir94 chunk/vision routing; token counts intentionally differ from the old audit estimator because the current map emits text-bearing DOM paths only.
**Files:** `app/extraction/representation/flat_map.py`, `representation/scope.py`, `representation/__init__.py`, tests
**What:** DOM/JSON-tree → ordered `absolute_path → text` map (NEXT-EVAL rules: strip class/id/style, text-bearing nodes only). **Detail region-scoping with a hard, measured fallback:** (a) find the main product region; (b) if the scoped map < 300 tokens → widen to full flat map (fixes dir47→167); (c) if full map > 60k tokens → return a chunked/summarized map and flag for vision (fixes dir94→162k). Pure function over `app/extraction/documents.py`; no acquisition changes.
**Verify:** on the 10 audit sample dirs, scoped token counts match `chatgpt_audit/summary.json` within tolerance **except** dir47/dir94, which now hit the fallback (assert fallback fired, output non-empty and ≤ 60k).

### Slice 0.4: Grounding validator
**Status:** DONE — exact/normalized/miss unit tests pass; `eval.grounding --verified-labels` reports grounding coverage on the verified seed labels.
**Files:** `app/extraction/representation/grounding.py`, tests
**What:** `ground(value, flat_map, sources) -> GroundingResult{grounded, match_type ∈ {exact,normalized,none}, source_path}`. Exact + normalized (price/whitespace/unicode/currency) matching. No LLM.
**Verify:** unit tests: exact hit, normalized price hit (`$19.98`↔`1998`), hallucinated miss → `none`.

## Phase 1 — Tiers + router (commerce-detail)

### Slice 1.1: Generalized extractor tier (rebuild `model_runtime`)
**Status:** IN PROGRESS — runtime fallback now builds the scoped flat path→text page, passes that representation to the injectable generalized adapter, gates every published model value through `ground(...)`, and marks accepted evidence with `extraction_method="generalized"`. Hosted-provider adapter, prompt/schema validation, explicit `llm_enabled` gate, and crawl-pipeline adapter injection landed. **Eval adapter resolution is provider-agnostic and UI-aligned (2026-07-06):** `eval.run` resolves the generalized adapter from an explicit `--llm-config`, else `--provider/--model`, else the first configured provider in the catalog (`default_generalized_config_snapshot` — Mistral is the catalog default via `MISTRALAI_API_KEY`, but no provider is hardcoded). Full `eval.run --engine v3 --tier generalized` gate with a live model still remains.
**Files:** `app/extraction/model_runtime.py` (rebuild), `app/extraction/representation/*`, `app/core/config/evaluation.py`
**What:** Replace the compact-DOM input with the flat map; JSON-schema-constrained decoding; per-field schema carries **semantic senses** (`sale_price_after_discount` vs `list_price`, not `price`); every value routed through the grounding gate before becoming `Evidence`; emit `extraction_method="generalized"`. **Llama via the hosted API behind a provider-agnostic client** (no self-hosting — see Decisions).
**Verify:** `eval.run --engine v3 --tier generalized --no-recipes --no-selectors` beats baseline on commerce-detail: **price on ≥ 90/91, 0 empty, sale_price recovered where present**; grounding-failure rate < 5%.

### Slice 1.2: Deterministic tier + platform parsers (HTML `<script>` only)
**Status:** IN PROGRESS — embedded JS-state mapping now treats Shopify-style `compare_at_price` / `compareAtPrice` and list/original price aliases as `offer.original_price` for both parent product offers and variant offers, so deterministic structured extraction can recover sale/list price pairs from script state. Dedicated platform modules and full deterministic-only recovery report remain.
**Files:** `app/extraction/collectors/jsonld.py`, `collectors/js_state.py`, new `app/extraction/platforms/{shopify,next_data,sfcc}.py` (magento/woo later)
**What:** Strengthen JSON-LD/microdata/OG parsing and add platform parsers that read embedded state **from `page.html` `<script>` tags** (audit confirmed no separate network payloads): Shopify inline product JSON (`compare_at_price` → sale_price goldmine), Next.js `__NEXT_DATA__`, SFCC/Redux state. Prefer embedded state over DOM. No selectors, no LLM. Covers ~52 platform pages + the JSON-LD floor; the ~37 "unknown" lean on JSON-LD + the generalized tier.
**Verify:** deterministic-only recovery matches the audit floor (title 93%, price 87%, image 90%) and lifts **sale_price on Shopify pages to ~100%** via `compare_at_price`.

### Slice 1.3: Variant matrix extraction (dedicated — the hardest sub-problem)
**Status:** IN PROGRESS — embedded JS-state variant rows now have focused coverage for Shopify ProductJson option-name hydration (`options` + `option1/2/3`), variant price/original-price, currency, availability, SKU, and variant id. Generalized-tier prompts/schema now include variant option and variant-offer facts. DOM/generalized variant matrix extraction and full variant-page eval target remain.
**Files:** `app/extraction/variants.py`, `platforms/*` (variant readers), generalized-tier variant schema
**What:** Two-path variant extraction into the canonical matrix (per-variant option values + price + availability + sku): **(a)** embedded readers for the ~7 pages with full variant JSON (Shopify variants array, JSON-LD offers, SFCC); **(b)** the **generalized tier** for the ~29 dom_only/partial pages — flat-map the option region, extract the matrix under schema, ground every per-variant value. Guard against the audit's false-positive class (feature-flag JSON like `{"name":"off","value":false}` is not a variant).
**Verify:** on the ~36 variant pages, beat the baseline's **11 empty-variant failures** (target: ≤ 2 empty where variants exist); embedded-path pages exact-match; no feature-flag false positives.

### Slice 1.4: Record-first establishment + identity verification (adopted from V2 §7–§14)
**Status:** IN PROGRESS — single-root wrong-product captures are now rejected before publication, including the URL-only shell case where requested-URL fallback evidence was previously selected after captured product identity failed. Focused engine-level regression passes. The five audit image-contamination pages (24/34/39/40/74) now replay at ≤20 total product assets. Full attach-mechanism coverage remains.
**Files:** `app/extraction/entities.py`, `app/extraction/resolution/*`, `app/extraction/targeting.py`, new `app/extraction/attach.py`, tests
**What:** Implement the mandatory control flow that wraps every tier: (1) **establish records** (product/variants/offers) via establisher chains — boundary from structured source or grounded-LLM proposal on the scoped flat map, never a global candidate pool; (2) **verify identity** (product id/sku/canonical-URL vs requested page) before any attachment — a record failing identity is dropped, never published; (3) **attach sources only via the four mechanisms** (same-source, key join, structural containment, validated single-record) with the grounding gate enforced at attach time; (4) completeness recorded separately from confidence. This is where the audit's cross-product image contamination (5 pages) and mis-attributed variants are structurally prevented.
**Verify:** the 5 audit image-contamination pages produce zero cross-product assets; a synthetic wrong-product response fails identity and is dropped, not published; no field attaches to a record that failed identity.

### Slice 1.5: Cascade router + cold-start/fallback routing
**Status:** IN PROGRESS — active-recipe identity failure now routes through grounded model fallback and discards failed recipe/generic evidence for that fallback attempt, so stale recipe values cannot win after generalized recovery. Integration coverage proves a bad recipe URL publishes the correct grounded model record with `extractor_tier="ml"` and `model_fallback` in the decision path. Full cascade eval gate remains.
**Files:** `app/extraction/engine.py`, `app/extraction/pipeline.py`, `app/core/records/*` router glue
**What:** Explicit cascade `deterministic → recipe (cache hit) → generalized (per-page) → vision`, orchestrating the record-first flow (1.4) at each tier. Routing: `no_active_recipe|cold_start → generalized`; `identity_failure|required_source_missing|coverage_below_minimum → generalized per-page`, publish the correct record, **then** log the drift signal (existing `SentinelObservation`). No page left unextracted.
**Verify:** integration test — a page that fails recipe identity still publishes a correct grounded record; `extractor_tier` reflects the path taken; full-cascade `eval.run` ≥ baseline on all commerce-detail fields.

### Slice 1.6: Amend Anti-Complexity laws + budgets
**Status:** DONE — generalized fallback budgets now live in core config and runtime enforces the shared latency/cost/input-token ceilings before publication. Oversized flat maps degrade with a diagnostic and no model invocation. Engineering strategy now states budgeted per-page LLM fallback and no silent recipe degradation while keeping recipe replacement manual. Verified with focused model fallback, runtime, architecture, identity, and asset suites.
**Files:** `docs/ENGINEERING_STRATEGY.md`, `app/core/config/*` budget entries
**What:** Amend Law #20 (runtime LLM is a budgeted first-class tier) and add Law #21 (no page silently unextracted/degraded due to missing/drifted recipe). Add a `generalized_extraction` budget block (`budget_ms`, `model_tier`, `max_cost_usd_per_page: 0.02`, `max_input_tokens: 60000`, `escalate_to_vision_below_confidence`, `cooldown_minutes`). Law #12 (no automatic *recipe replacement*) stands — only the *per-page fallback* is automatic.
**Verify:** budgets read at runtime; a >60k-token or cost-ceiling page degrades to chunk/vision with a diagnostic, never a raw failure.

## Phase 2 — Delete selectors + recipe caching (commerce-detail)

### Slice 2.1: DELETE the selector architecture (commerce-detail, eval-gated)
**Status:** DONE — selector-deletion unlock is green for commerce-detail and the old commerce-detail selector runtime is gutted. `collectors/dom.py`, the selector-recipe harvest path, requested-field DOM selector collection, commerce-detail selector memory loading, and dead commerce-detail selector config banks were removed/guarded. Jobs/listing shared selector infra remains guarded until their corpora exist. The selector-free cascade (`eval.run --engine v3 --tier cascade --no-recipes --no-selectors`) passes the quality gate with no selector collectors: empty records 5→2, empty variants 11→11, missing price 13→18 (reported but non-blocking), and generalized helps pages 3/32/81/90.
**Files:** `app/extraction/collectors/dom.py` (gut to flat-map + record-container discovery), `app/extraction/engine.py` (remove `selector_rules` path `:414`), remove/guard `app/core/records/selectors_runtime.py`, `app/crawl/domain_memory_service.py` (selector composition), `app/models/domain_memory.py`, `app/api/selectors.py`, `app/schemas/selectors.py`, `app/core/config/selectors.py`, selector-promotion in `app/crawl/review/__init__.py`.
**What:** Remove the per-field selector banks and the persisted-selector store/replay for **commerce-detail**. For jobs/listing the shared infra is **guarded/disabled, not yet deleted** (deleted in Slice 4.2 once those corpora prove out). This is the slice that turns "patch" into "replace."
**Precondition (hard gate):** `eval.run --engine v3` (deterministic + generalized + variants, **no recipes, no selectors**) ≥ frozen baseline on **every** commerce-detail field, and strictly better on price/variants/empty-record. If any field regresses, deletion is blocked and fixed in a tier — **never** by resurrecting a selector.
**Verify:** `grep -rn "selector_rules\|DETAIL_.*_SELECTORS" app/extraction` returns nothing live; commerce-detail routes through zero selectors; test suite green.

### Slice 2.2: Recipe compiler (source-pin + schema; grounding-gated path hints only)
**Status:** DONE — compiled recipes now emit source pins + field schema from resolver contracts, and commerce-detail selector recipes compile to an empty selector set. Frozen legacy releases are also guarded so commerce-detail receives no selector rules. Runtime marks `extractor_tier="recipe"` only when a matched source-pin template actually applies via `CONTRACT_PREFERRED_SOURCE`; broken pins return no preferences and fall back to generic ranking with no stale values. `eval.run --engine v3 --tier recipe --no-selectors` replays LLM-free, passes the gate, performs zero model invocations, and sees no selector collectors. Jobs/listing selector compilation is left intact until Slice 4.x.
**Files:** `app/core/extraction_memory/templates.py`, `contract_runtime.py`, compiler module
**What:** Compile a recipe as a **source-pin + field-schema plan** (§Tier 1), never `selector_rules`. Where a stable structured source exists, pin it. Optional cost-optimization: a path hint from **multiple** captures, **grounding-re-verified every run with automatic generalized fallback** — the only cached path allowed, and it can never return a stale value silently. Shadow as `candidate`; promote to `active` only on generalized-tier agreement over a minimum page count. DOM-only sites: recipe is just "run generalized," no compile.
**Verify:** compiled recipe replays LLM-free and matches generalized within threshold on held-out pages; a deliberately-broken path hint falls back to generalized (no stale data); `eval.run --tier recipe` matches generalized at ~0 marginal cost.

### Slice 2.3: Drift → per-page fallback → repair queue
**Status:** DONE — sentinel drift observations now enqueue bounded repair items in extraction memory. Critical/suspected/needs-review recipe drift records the fallback verdict, whether a record was published, disagreement classes, and an observed model-fallback cost-savings estimate so repair work can be prioritized. Confirmed critical drift still suspends the template and future commerce-detail traffic routes away from selectors/generic stale recipe data.
**Files:** `app/extraction/sentinel.py`, extraction-memory persistence, repair-queue surface
**What:** On active-recipe identity/coverage failure: immediate per-page generalized fallback (correct record published), health event logged, existing evidence-requiring aggregation unchanged; repair candidate compiled via the multi-sample pipeline; repair item annotated with a **cost-savings-at-stake** estimate to self-prioritize.
**Verify:** simulated drift publishes correct data immediately and enqueues a repair with a $ estimate.

## Phase 3 — Human-in-the-loop + cutover

### Slice 3.1: Extraction Profile (HITL) — backend
**Status:** DONE — extraction profiles now persist per `(domain, surface)` as domain-layer operator contracts with source pins, required flags, value senses, and aliases. The knowledge API exposes profile load/save, commerce-detail CSS selector contracts now return `410`, and release snapshots consume profile source pins before generic offer resolution while preserving generalized fallback. A Shopify JSON price pin flips a mis-priced DOM/microdata page to the pinned source and reloads from extraction memory.
**Files:** `app/models/extraction_memory.py`, `app/persistence/extraction_memory.py`, `app/api/knowledge.py`
**What:** `ExtractionProfile(domain, surface)` — pinned source, field bindings, senses/aliases, required fields, overrides. Router consumes it before compile/fallback. Immutable-per-run like existing releases (future runs only).
**Verify:** a profile pinning "Shopify JSON price" flips a DOM-mis-priced page to correct; persisted and reloaded.

### Slice 3.2: Extraction Profile — frontend panel
**Status:** TODO
**Files:** `frontend/components/crawl/*` (mirror the acquisition-profile / Domain Recipe panel)
**What:** Operator UI to view winning source per field, pin/override bindings, set senses/required flags, export the compiled binding as a dev-readable snippet.
**Verify:** Vitest/Playwright — edit → save → re-run reflects the pin; export produces a valid snippet.

### Slice 3.3: Metrics + per-domain cutover
**Status:** TODO
**Files:** metrics wiring, `docs/plans/ACTIVE.md`, cutover flag
**What:** Emit generalized-vs-recipe tier split per domain, grounding-failure rate, blended $/page, promotion/demotion counts, repair cost-at-stake. Per-domain flag routes production commerce-detail traffic to V3 once its eval cell beats baseline; old path stays until green.
**Verify:** dashboards populate on a live run; V3 enabled per-domain only after commerce-detail passes.

## Phase 4 — Jobs + listing (corpus-gated; do not start without a corpus)

### Slice 4.1: Build jobs + listing corpora
**Status:** TODO — **blocked: no ground truth exists today**
**Files:** `backend/eval/labels/*` (jobs + listing cells)
**What:** Capture and human-label a jobs-detail, jobs-listing, and commerce-listing corpus (target ≥ 20 pages/cell) using the acquisition pipeline. Jobs needs `JobPosting` JSON-LD coverage measured (corpus showed 0%). Listing needs the exemplar-record representation (§Representation) exercised for the first time.
**Verify:** `eval.corpus --stats` shows ≥ 20 labeled per new cell; a listing baseline is frozen.

### Slice 4.2: Extend tiers to jobs/listing + delete shared selector infra
**Status:** TODO — **blocked until 4.1 + each cell beats its baseline**
**Files:** `app/extraction/jobs.py`, `app/extraction/listing.py`, remove the guarded selector infra from Slice 2.1
**What:** Point the same cascade at jobs/listing (jobs field schema; listing exemplar-record + apply-across-list). Once each cell beats baseline, **delete** the selector infrastructure left guarded in 2.1.
**Verify:** jobs + listing eval cells ≥ baseline with zero selectors; `grep -rn "selectors_runtime\|domain_memory" app` returns nothing live.

## Phase 5 — Network/API/GraphQL + interaction sources (corpus-gated; the V2 §15–19 machinery)

### Slice 5.1: Re-capture a network-bearing corpus
**Status:** TODO — **blocked: current corpus is HTML-only (`network_payloads_captured: false`)**
**Files:** `backend/eval/labels/*` (network-bearing captures), acquisition capture-config (read-only from extraction's side)
**What:** Using the existing acquisition network-capture (already built), persist `network_exchanges` alongside `page.html` for a set of sites whose variants/prices load via XHR/GraphQL and are **not** in any `<script>` tag. Label ground truth. This is the only way to test API/interaction extraction — do not build 5.2 against synthetic data.
**Verify:** corpus contains real captured XHR/GraphQL responses with labeled variant/price truth; count of "data only reachable via network" pages is measured.

### Slice 5.2: Network + interaction extraction tier
**Status:** TODO — **blocked until 5.1**
**Files:** new `app/extraction/adapters/network.py`, `app/extraction/interactions.py`, recipe request-template + APQ + response-matcher schema
**What:** Adopt the V2 §15–19 design **only now that it's testable**: materialize a source from a captured `NetworkExchange`; recipe request-templates with GraphQL/APQ (hash + full-query fallback); interaction snapshots (select-variant/tab/accordion/carousel) with the timing/protocol/endpoint/semantic response filter. Extraction *declares* the request; acquisition *executes* it (the seam is unchanged). Feeds the same record-first flow + grounding.
**Verify:** on the 5.1 corpus, variants/prices reachable only via network are recovered and grounded to the captured response; APQ `PERSISTED_QUERY_NOT_FOUND` falls back to full query.

---

## Doc Updates Required

- [ ] `docs/backend-architecture.md` — new representation/grounding/tier-router architecture
- [ ] `docs/CODEBASE_MAP.md` — new `app/extraction/representation/`, `app/extraction/platforms/`, `backend/eval/`
- [ ] `docs/INVARIANTS.md` — grounding gate; "no page left unextracted"; `extraction_method` ⟂ confidence
- [ ] `docs/BUSINESS_LOGIC.md` — §9 LLM decisions (runtime LLM now first-class, budgeted, grounded); Extraction Profile
- [ ] `docs/ENGINEERING_STRATEGY.md` — Anti-Complexity Laws #20 (amended) and #21 (new)
- [ ] `docs/plans/ACTIVE.md` — point to this plan

## Decisions (resolved — not open questions)

- **Generalized-tier model (RESOLVED):** **Llama via the existing hosted API — no self-hosting.** Matches the user's testing that Llama beat frontier models for this task. The client is provider-agnostic so a different model/endpoint is a config change; self-hosting (e.g. NuExtract-3 4B for batch economics) is explicitly deferred and revisited later only if cost metrics demand it. **Remove NuExtract/self-host from Phase 1–2 scope** — do not build serving infra now.
- **DOM-only steady state:** **generalized-LLM-every-page** (no persisted path cache) is the default — affordable at ≤20k/day (~$0.004/page). The grounding-gated path-hint cache (Slice 2.2) is an *optional* cost optimization enabled per-domain only if the Slice 3.3 blended-$/page metric shows a specific high-volume DOM-only domain needs it. This keeps the default architecture selector-free and simple.
- **Corpus scope:** commerce-detail is the only proven cell (91 pages). Jobs and listing are real but **corpus-gated** (Phase 4) — building their ground truth is a prerequisite task, not an afterthought. Do not delete shared selector infra until Phase 4 proves those surfaces.

## Notes

- **Sequencing rationale:** representation (0.3) + grounding (0.4) before the LLM tier (1.1) because they are the accuracy levers; deterministic floor + variants (1.2, 1.3) before the router (1.4) so the cascade has a strong non-LLM floor; **selector deletion (2.1) only after 1.1–1.4 beat the frozen baseline** so the brittle core is removed on evidence, not faith; recipes (2.2) *after* the generalized tier proves out, because a recipe is defined as a cache of the generalized answer, never a selector.
- **Source of authoritative numbers:** `chatgpt_audit/` (audit_report.md, summary.json, audit.py). Any agent needing a corpus statistic reads it there rather than re-deriving. Re-run `audit.py` only if the corpus changes.
- **Biggest residual risk:** region-scoping robustness (Slice 0.3) — the audit proved it fails on 2/10 sample pages. If the scoping fallback isn't solid, generalized-tier cost and accuracy both degrade. This is why 0.3 has explicit measured fallback thresholds and its own verify step against dir47/dir94.
