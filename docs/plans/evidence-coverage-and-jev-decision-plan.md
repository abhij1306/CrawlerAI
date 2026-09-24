# Plan: Generic Crawl Correctness Before Conditional JEV

**Created:** 2026-09-24
**Agent:** Codex
**Status:** DONE — deterministic corrections verified; JEV no-go
**Touches buckets:** evidence admission, request selection, entity/offer ownership, acquisition, evaluation, conditional LLM connector

## Goal

Fix the crawl's correctness defects through reusable evidence, field-validity, ownership, selection-intent, offer, and acquisition rules. The cited retailers prove behavior in regression fixtures; implementation must work on an unseen retailer. After deterministic corrections, evaluate whether JEV improves a genuine choice among valid, grounded candidates. Add no production JEV path without measured benefit.

## Hard implementation rule

**No new domain-, retailer-, or URL-specific extraction/resolution branches may be introduced for any cited audit case unless the site exposes a genuinely proprietary source format requiring an adapter. Cited retailers are regression fixtures only. Every correctness change must be expressed as a reusable evidence, field-validity, ownership, selection-intent, offer, or acquisition rule and demonstrated on at least one unrelated positive and negative case.**

Before adding a function, mapping, file, or config rule, search for and extend its existing owner. Do not create a parallel admission layer or expand `VARIANT_URL_AXIS_PARAMS` with one retailer's parameter names. Inspect the production diff for retailer/host literals, exact URL parameter names, and case-specific conditionals. A genuine proprietary adapter requires documented source shape, target binding, and generic contract tests.

## Evidence and current decision

- The supplied `docs/audits/crawlerai_latest.json` has 80 records. `backend/artifacts/runs/1/results/` has 81 HTML/record/diagnosis sets but 80 unique URLs. Two Zara captures share URL, color, and price; duplicate collapse likely explains the count. The supplied JSON and artifacts differ in some URL encodings and fields, so each defect must join to its own capture and frozen request contract.
- Published invalid values include `{{ shop.name }}` as brand, `- / null` as size, `Gender` as gender, and color text that absorbs `Previous Next`. These expose different structural faults: unresolved template syntax, all-sentinel values, bounded field type, and DOM boundary leakage. A site/value blacklist or post-publication cleanup would miss the underlying faults.
- Selfridges/CREED, Williams Sonoma/Breville, and Amsterdam Vintage Watches/Rolex expose brand role or target-ownership failure. Argentina Puma's `189999.00 USD` conflicts with first-party ARS in its capture; the published currency came from a DOM price node. Fix existing semantic roles and atomic offer ownership, not retailer or locale-host exceptions.
- Request query/fragment state matters for Target, Uniqlo, Ralph Lauren, and Balmain. Uniqlo publishes an unmapped option code `004` as size. Balmain hash ID `189322` maps to the captured active 50 ml `B02I01` variant, while top-level SKU is the 30 ml `B1Q501`; the four-row size matrix is current. Target's color/size and Ralph Lauren's color were `not_requested`, so their absence alone is not a requested-field failure.
- StockX commercial fields are diagnosed as absent from captured sources. Peloton and Apple have partial/content-selection problems. Birkenstock's valid product description was rejected while consent copy won; Apple, Converse, and Peloton publish UI or bare identity text. Classify captured evidence before changing acquisition or resolution.
- Generic ARIA/native selected-state and scoped material collection already exist. Many historical material/rating benchmark misses are `not_requested` in the paired run diagnosis. A two-request JEV probe picked manually supplied blocks, but did not show incremental value. TypeSafe's [API](https://docs.typesafe.ai/api) returns typed decisions; its [model notes](https://docs.typesafe.ai/model-jaggedness/jev-1.13) warn about numeric precision, irrelevant state, and adversarial content.

**Decision:** No production JEV integration now. Test it only after the four generic correctness slices.

## Acceptance Criteria

- [x] Every cited defect maps to a `page.html`, `record.json`, `diagnose.json`, frozen requested-field contract, and current owner. The 80/81 difference is explained by input/result identity or a typed missing result, without fabricating output.
- [x] The hard implementation rule above holds for every production change. Each changed rule has unrelated positive and negative coverage alongside cited retailer examples.
- [x] Invalid template, sentinel, audience, and leaked control values are rejected at admission/scope. Valid neighboring values and numeric sizes remain admissible.
- [x] Query, fragment, and path intent binds to an existing same-product matrix or abstains. Opaque codes remain internal.
- [x] Corroborated product brand, atomic offer currency, product description, and material ownership rules are enforced without retailer branches.
- [x] Source absence and collector/resolver failures are separated for StockX, Uniqlo, Peloton, and Apple in the paired case audit.
- [x] JEV no-go is recorded: no proven held-out ambiguity with qualifying incremental gain, so no production integration or model call was made.
- [x] Focused verification and canonical affected gates pass under repository policy; no full local suite was run.

## Do Not Touch

- Publish, persistence, enrichment, or exports to repair extraction values. The first faulty owner must change.
- `backend/app/crawl/site_link_discovery.py`; product-detail captures do not measure category-link relevance.
- Historical benchmark values merely to match old dynamic price/stock or the stale three-variant Balmain expectation.
- User `surface`, traversal, proxy, diagnostics, or `llm_enabled` controls.

## Slices

### Slice 1: Evidence contract hardening
**Status:** DONE
**Files:** existing `backend/app/extraction/pipeline.py`, `backend/app/extraction/collectors/dom.py`, `backend/app/extraction/collectors/dom_scoping.py`, `backend/app/extraction/resolution/decisions.py`, `backend/app/core/records/attribute_normalization.py`, relevant `backend/app/core/config/` owner, focused tests; existing evaluation/diagnosis readers for case classification
**What:** Join each cited record to its capture and frozen field contract. Harden existing evidence admission in order: source scope, field type, semantic role, and target ownership. Reject unresolved template expressions by syntax; reject values composed entirely of null/sentinel tokens; enforce the configured gender enum; keep unmapped option identities internal. Fix color/description DOM node boundaries so sibling controls and consent text never enter a candidate. Do not add a giant `BAD_VALUES` list, broad cleanup regex, or new admission framework. Record concrete rejection reasons.
**Verify:** The cited invalid values and Birkenstock consent block fail in focused tests; valid product text and a numeric size with genuine source semantics still pass. Each rule has unrelated positive and negative cases. A case table distinguishes `not_requested`, absent capture, invalid candidate, and wrong winner.

### Slice 2: Request Selection Intent
**Status:** DONE
**Files:** existing `backend/app/core/records/url_identity.py`, `backend/app/core/config/variant_policy.py`, `backend/app/extraction/product_options.py`, `backend/app/extraction/entities.py`, `backend/app/extraction/targeting.py`, `backend/app/extraction/resolution/variants.py`, focused tests
**What:** Consolidate existing request-axis parsing into one typed selection-intent path in the current owner, instead of parallel URL parsers. Preserve source (`query`, `fragment`, or `path`), raw key/value, possible canonical axis, and identity strength. Normalize parameter morphology generically; handle opaque identity tokens independently of axis labels. Bind intent only through exact same-product option/variant/SKU evidence; map codes to public labels only when a source supplies that mapping. Keep product identity distinct from selected offer. Do not add retailer parameter branches or grow an alias dictionary for the cited URLs.
**Verify:** Target, Uniqlo, Ralph Lauren, and Balmain are fixtures for the generic binding; Balmain hash `189322` selects 50 ml `B02I01`, and `004` does not publish without a size mapping. Unrelated query, fragment, and path cases prove both successful binding and fail-closed behavior. No `not_requested` axis is silently published.

### Slice 3: Evidence and offer ownership
**Status:** DONE
**Files:** existing `backend/app/extraction/entities.py`, `backend/app/extraction/targeting.py`, `backend/app/extraction/resolution/ranking.py`, `backend/app/extraction/resolution/price_units.py`, `backend/app/extraction/resolution/derived.py`, `backend/app/extraction/collectors/dom_product_attributes.py`, `backend/app/core/config/locale_format_rules.py`, focused tests
**What:** Enforce existing semantic roles and target ownership across brand, offer, description, and material evidence. A target-owned product brand prevents retailer/site identity from winning; keep legitimate private labels. Price and currency resolve as a source-backed pair for the same offer; prefer explicit ARS over an ambiguous dollar symbol, using generic locale evidence rather than an `ar.puma.com` exception. Product descriptions/materials must belong to the requested product and valid content block; explicit product-detail material outranks weaker metadata. Abstain when no valid block survives.
**Verify:** The three retailer/brand pairs, Puma currency, Birkenstock description, and Sneakersnstuff material are fixtures. Unrelated private-label, mixed-offer currency, related-product text, valid product-description, and no-valid-description cases prove both positive and negative behavior.

### Slice 4: Source absence versus resolver failure
**Status:** DONE
**Files:** existing `backend/app/acquisition/` and `backend/app/extraction/collectors/` only if a captured observation is lost there; `backend/app/extraction/targeting.py`, `backend/app/extraction/resolution/`, and `backend/app/observability/` only for a proven ownership/diagnosis defect; focused tests
**What:** Trace StockX, Uniqlo, Peloton, and Apple through acquisition, structured/network/DOM collection, target selection, and Resolve. Classify each missing commercial, product-family, or description fact as uncaptured, uncollected, rejected, or misbound. Fix the earliest losing owner with a generic rule. Keep source-unavailable and partial outcomes visible; do not retry a usable page solely to fill defaults or synthesize commerce facts. Confirm the duplicate Zara result explains 80 unique outputs; fix run reporting only if an input outcome is truly lost.
**Verify:** Capture-backed tests show recovered facts only where target-bound evidence exists, accurate failure/partial classifications otherwise, and one unrelated positive and negative for each new acquisition or ownership rule. Input occurrence and record deduplication counts reconcile.

### Slice 5: Offline JEV decision
**Status:** DONE — no qualifying ambiguity; no model call
**Files:** existing `backend/app/evaluation/` tooling and a focused decision note; no production connector
**What:** After Slices 1–4, identify cases with two or more valid, target-owned, field-compatible, source-located candidates that deterministic rules still cannot distinguish. Give a pinned JEV version bounded candidate IDs/text and `none`. Compare against deterministic ranking on held-out cases; measure correct recovery, false publication, abstention, wrong-product choice, tokens, cost, latency, and failures. The two hand-picked probe calls do not count. If no real ambiguity or gain remains, record no-go and stop JEV work.
**Verify:** Per-case note contains source locators, baseline/JEV outcomes, threshold rationale, and a clear go/no-go against acceptance criteria.

### Slice 6: Integrate JEV only if Slice 5 passes
**Status:** NOT PROMOTED — Slice 5 no-go
**Files:** current `backend/app/connectors/llm/`, `backend/app/core/config/llm_runtime.py`, extraction orchestration/resolution, existing diagnosis and cost owners, focused tests; name exact files after Slice 5
**What:** Add one typed candidate-ID decision behind frozen run `llm_enabled` and active provider config, after deterministic admission and only for unresolved ambiguity. Pin the evaluated model. Bound candidate count, state size, timeout, retry, budget, and threshold in central config. Record model/version, candidate IDs, probabilities, selection/abstention, cost, and failure in existing diagnostics. On `none`, low probability, error, or timeout, retain unresolved deterministic state. Never generate a value or replace an accepted deterministic fact.
**Verify:** Disabled runs make zero calls; every chosen ID has a retained locator; failures/abstentions remain visible and harmless; selected state, brand ownership, and commercial pairing cannot be overridden. Unrelated positive and negative tests demonstrate the generic decision seam. Run canonical repository gates after all implementation edits.

## Doc Updates Required

- [x] `docs/backend-architecture.md` — document evidence, selection, ownership, source absence, and JEV decision.
- [x] `docs/CODEBASE_MAP.md` — structured scope ownership clarified.
- [x] `docs/INVARIANTS.md` and `docs/BUSINESS_LOGIC.md` — changed hard and user-visible contracts recorded.

## Notes

- Cited retailers may appear in tests and audit fixtures, never as new generic production branches. A proprietary adapter needs separate source-format evidence.
- This revises the existing active plan; it does not start a second plan. `AGENTS.md` and `docs/agent/PLAN_PROTOCOL.md` require confirmation before implementing a newly created non-trivial plan.
- The user confirmed implementation on 2026-09-24. Case joins, original field statuses, and JEV no-go rationale are in `docs/audits/evidence-coverage-and-jev-decision.md`.
- The first affected selector run passed 1,107 backend tests and found one URL/DOM selection handoff regression. The exact failure was fixed; the retry-delta selector passed 702 affected tests. Static gates passed. This plan never ran a full suite.
