# Capture Completeness and Dynamic Content Taxonomy — Addendum to Ground-Truth Adaptive Cutover Plan v2

**Created:** 2026-06-30
**Agent:** Opus (architectural decision)
**Status:** TODO — merge into v2 before Slice 0 begins
**Predecessor documents:** Extraction Ownership and Accuracy Plan; Ground-Truth Recall and Adaptive Contract Cutover Plan v2
**Scope of this document:** patches Slice 0, Slice 2, Slice 6, Slice 8, and Section 4A only. Does not restate v2 in full.

## 1. Problem this addendum fixes

v2's `EnrichmentPlanner` treats every unresolved requested field the same way: walk the cost ladder from re-evaluating captured evidence up to bounded interaction. That ladder is correct for fields that are *genuinely absent* until the page does something. It is the wrong, expensive answer for fields that are *already present* in the live DOM but never made it into the stored capture because the capture serialization didn't look there.

These are different failure mechanisms with different owners and different costs:

| Category | Where the data lives | Recoverable from a *better* capture? | Correct fix layer | Runtime cost if misrouted to EnrichmentPlanner |
|---|---|---|---|---|
| **A — CSS-hidden, light DOM** | In the saved HTML, hidden by `display:none` / `hidden` / collapsed-tab CSS | Yes — already in `page.content()` output, just filtered by Harvest's visibility logic | Harvest: stop filtering candidates by computed visibility | Wasted re-Resolve, possibly wasted render step |
| **B — Open shadow DOM** | In the live page; standard `outerHTML`/`page.content()` does not descend into shadow roots | Yes, but only with shadow-piercing serialization at capture time | Acquisition/capture: flatten shadow roots into the stored artifact | Wasted full enrichment planner traversal, every run, every field, every domain using this pattern |
| **C — Closed shadow DOM** | `element.shadowRoot` returns `null` from outside by spec | Not via standard capture; needs CDP-level flattening, fragile | Acquisition, with a real ceiling — may stay `source_unavailable` | Same as B, plus possible false escalation to interaction/contract when capture is actually the blocker |
| **D — Fetch-on-interaction** | Not in DOM pre-interaction; requires a selection/click to trigger XHR/GraphQL | No | `EnrichmentPlanner` steps 4–7, correctly | None — this is the case the planner exists for |

v2 has no mechanism to tell these apart before spending enrichment budget. `CaptureAssessment`'s status enum (`usable / blocked / captcha / status_error / empty / partial_shell / wrong_content_type / redirect_mismatch`) implicitly treats any "usable" capture as a complete DOM representation. It isn't, if the serialization method doesn't pierce shadow roots. Confirmed by source review: the term "shadow" does not appear anywhere in v2 except in the unrelated `drift_detected` shadow-comparison mechanism in Slice 10.

The two named cases driving this addendum:

- **Sigma-Aldrich** — pack-size/grade selection drives a price/availability fetch. This is genuinely **Category D**. The existing v2 walkthrough for it is correct and should stay in Section 4A as written.
- **Zara-class fashion sites** — fit/materials/care descriptive content inside carousel or tab panels. This is very likely **Category A or B** on most modern component-library storefronts (carousels frequently render all slides in the light DOM and toggle visibility/transform via CSS; tab panels are a common shadow-DOM encapsulation target for design-system component libraries). It should usually **not** require interaction at all — and currently nothing in v2 would catch that before paying the EnrichmentPlanner's full cost ladder, including step 6 (bounded interaction) for content that was sitting in plain CSS-hidden DOM the whole time.

Action item before this addendum is accepted as architecture: confirm Sigma-Aldrich and the Zara-class case(s) are formally part of the 90-URL audited corpus with `page.html` / `record.json` / `diagnose.json` and a manual adjudication, not just illustrative examples. If they are not yet in the corpus, add them with the same rigor as the other 90 before using them to justify EnrichmentPlanner ordering — the prior critique of the Sigma-Aldrich walkthrough being unsourced still applies until this is done.

## 2. Patch: Slice 0 — Capture Serialization Audit (new sub-step, runs before residual ledger lock)

Insert as **Slice 0a**, before the existing Slice 0 replay-and-residual-ledger work.

**Goal:** convert as many of the 51 inconclusive instances and the 32 unproven `no_variants` instances from "we don't know" to "confirmed, fixable in Slice 2–4" — *before* they get permanently bucketed as `interaction_required` or routed toward contract/interaction machinery they may not need.

Steps:

1. Identify the union of URLs behind the 51 inconclusive issue instances and the 32 unproven `no_variants` cases (some overlap expected — dedupe to a single URL list).
2. Re-capture that URL list using a shadow-root-flattening serialization: recursively walk `element.shadowRoot` for every element with an open shadow root and inline the flattened content into the stored capture artifact, tagged distinctly from light-DOM content so provenance stays intact.
3. Diff field/region candidates between the original capture and the re-capture for each URL.
4. Reclassify per URL:
   - New product/variant/field evidence appears under improved serialization → **Category A or B, confirmed**. Route to Slice 2 (`collector_missed`) or Slice 4 (variant graph), not to interaction/contract territory.
   - No change under improved serialization, but DOM shows interactive controls (selects, swatches, tabs with no associated light/shadow content for inactive panels) → likely **Category D**, stays in scope for Slice 8 enrichment.
   - No change under improved serialization, no visible controls explaining the gap → candidate **Category C** or genuinely `not_present_in_captured_sources`; needs explicit manual adjudication, may resolve to `source_unavailable`.
5. Only after this reclassification does the residual ledger lock the remaining genuinely-ambiguous instances for Slice 1–10 handling.

This is a capture/acquisition-layer change only. It has zero impact on Resolve, Publish, or the contract system, and should land before Slice 1's `CaptureAssessment` work, not parallel to it — `CaptureAssessment`'s completeness judgment is more accurate once the serialization gap is closed.

**Verify**

- Every URL in the 51+32 set has one of: reclassified-confirmed, reclassified-likely-interaction, or remains-ambiguous-with-adjudication-note.
- Re-capture diff output is stored in the ignored artifact directory alongside the residual ledger, not committed.
- No regression in capture method correctness on the 22 clean-control URLs (re-capture them too as a control: flattening should not change their output).

## 3. Patch: CaptureAssessment — new completeness signal

Extend the `CaptureAssessment` contract (do not change its existing `status` enum semantics):

```python
class CaptureCompletenessSignal:
    shadow_roots_detected: int
    shadow_roots_flattened: int
    closed_shadow_roots_detected: int
    hidden_panel_dom_present: bool      # carousel/tab/accordion-shaped DOM
                                          # with no associated network call
    serialization_method_version: str
```

This is diagnostic, not blocking — it does not change `usable`/`blocked`/etc. Its purpose is to let Slice 2's diagnostic-truth classifier distinguish `collector_missed` (Category A/B, evidence was capturable and wasn't captured correctly) from genuine `interaction_required` (Category D) and `source_unavailable` (Category C, when flattening still fails). Without this signal, Slice 2's stage classification has no way to tell "Harvest missed it" apart from "the page never offered it without a click," which is exactly the ambiguity that produced 51 inconclusive instances in the first place.

## 4. Patch: Slice 2 — diagnostic truth states

Add one field state, inserted alongside the existing `collector_missed` / `interaction_required` / `not_present_in_captured_sources` set:

- `capture_incomplete` — evidence is provably absent from the *stored* capture but the `CaptureCompletenessSignal` indicates an unflattened shadow root or hidden-panel DOM exists at that location. Distinct from `collector_missed` (which assumes the evidence was capturable and Harvest's logic missed it) because the fix here is upstream, in acquisition, not in Harvest's recognizer rules.

Audit target addition: every instance reclassified under Slice 0a as Category A/B and not yet re-run through the full pipeline gets `capture_incomplete` until the corresponding acquisition fix lands, then flips to `collector_missed` or `captured_published` once Harvest correctly recognizes the now-flattened evidence.

## 5. Patch: Section 4A / EnrichmentPlanner — ordering correctness

The existing 8-step cost ladder is right in structure but **step 4 ("Capture a rendered DOM without interaction") is unsafe until Slice 0a ships**, because without shadow-flattening serialization, step 4 will silently re-render the page and still miss Category B content — burning a full render cycle per field, per run, per domain, for content a one-time capture fix would have closed for free. This directly undermines the cost-control purpose v2 was redesigned for.

Required ordering dependency, stated explicitly: **`EnrichmentPlanner` step 4 must use the same shadow-flattening serialization established in Slice 0a.** Add this as a hard precondition in Slice 8, not an implementation detail left to whoever builds it — if step 4's renderer and Slice 0a's audit script diverge in capture method, you will reintroduce the exact gap this addendum closes, just moved from "ground-truth audit time" to "every production run."

Recommended planner step re-ordering for Category-driven dispatch, replacing the generic "step 4" framing for shadow-DOM-flagged templates specifically:

```text
1. Re-evaluate already captured recognized sources
2. Use a validated source path or relation from an active template contract
3. Fetch a known product-scoped HTTP/JSON endpoint
4. Capture a rendered DOM WITH shadow-root flattening, still no interaction
   (this step alone should resolve all Category A/B gaps)
5. Wait for a known product-scoped element or response
6. Perform a bounded, field-specific interaction        ← Category D enters here
7. Request human/LLM contract assistance
8. Fail explicitly
```

This is not a new step — it's making explicit that step 4 as written in v2 is silently assumed to be shadow-aware, and that assumption needs to be a stated, tested precondition rather than implicit.

## 6. Patch: Slice 6 — template signature additions

Add structural signature features for the dynamic-content patterns this addendum names, so the contract system recognizes them declaratively instead of rediscovering per-page or per-domain:

- presence and count of shadow-DOM hosts (open vs. closed, where detectable)
- presence of carousel/tab/accordion component shapes — detect via common signals: ARIA roles (`tablist`, `tabpanel`), `data-*` state attributes, custom-element tag names following web-component naming conventions (hyphenated tags)
- presence of option-select-to-network-call coupling (the Sigma-Aldrich pattern) — detectable structurally as a `<select>`/swatch-group control with no corresponding light/shadow DOM payload for unselected states, paired with an observed or inferred product-scoped endpoint

A contract may declare `requires_shadow_flattening: bool` and `requires_select_then_fetch: tuple[field_path, ...]` as capability hints, consistent with the existing constraint that contracts may only help Harvest identify evidence and relations — these hints route capture/planner behavior, they do not write final values.

## 7. Patch: Slice 7 acceptance test — named representative templates

The existing acceptance bar ("at least five previously unseen templates corrected through replay-validated contract data, no production Python change") should name its categories explicitly rather than leaving template selection arbitrary:

- at least one Category D template (Sigma-Aldrich-class: select-triggers-fetch variant pricing)
- at least one Category A/B template (Zara-class: carousel/tab descriptive content recoverable via improved serialization alone, ideally requiring **zero** interaction budget once Slice 0a's fix is in place — this is the test that proves the addendum worked)
- remaining three may be drawn from any confirmed defect family in the residual ledger

If the Category A/B template still requires interaction after Slice 0a ships, that's a signal the shadow-flattening fix is incomplete, not that the template genuinely needs interaction — investigate before accepting it as a Category D case.

## 8. Patch: acceptance criteria additions

- Zero instances in the residual ledger are classified `interaction_required` or routed to contract/interaction enrichment when `CaptureCompletenessSignal` indicates the gap was resolvable by shadow-flattening alone.
- Re-capturing the 22 clean controls with the new serialization produces zero field-state regressions.
- Sigma-Aldrich and at least one Zara-class case are present in the audited corpus with full `page.html`/`record.json`/`diagnose.json` lineage before being cited as architectural justification anywhere in the plan.

## 9. Relative effort sizing (not calendar time — still no real timeline exists for v2 or this addendum)

| Patch | Size | Why |
|---|---|---|
| Slice 0a capture re-run + diff | S | One serialization script change, batch re-run against ≤83 URLs, no architecture impact |
| `CaptureCompletenessSignal` contract | S | New dataclass, populated at capture time |
| Slice 2 `capture_incomplete` state | S | One new enum value, classification logic already exists in shape |
| Slice 6 template signature additions | M | New structural feature extraction, needs validation against real component-library markup variety |
| EnrichmentPlanner step 4 dependency wiring | S–M | Mostly ensuring one shared serialization path is used in two places, not new logic |
| Corpus additions (Sigma-Aldrich, Zara-class) | M | Full manual adjudication per the existing 90-URL standard, not just capture |

This addendum is small relative to v2's total scope — most of it is sequencing and a contract-shape fix, not new architecture. It should land inside the existing Slice 0/2/6/8 boundaries rather than adding new slices to an already 20-slice combined plan.
