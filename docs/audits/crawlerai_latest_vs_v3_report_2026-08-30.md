# CrawlerAI — Latest Crawl vs v3.2 / Run-3 Baseline

**Date:** 2026-08-30
**Latest input:** `results(1).zip`
**Baseline:** `run-3.json` evaluated against `crawlerai_eval_html_grounded_v3_2.json` / `crawlerai_defects_run3.json`

## Executive conclusion

The latest crawl is a material improvement over Run-3, especially in enrichment, variants/options, attributes, identifiers, and recovery of previously missing commercial fields. It is not yet ready to call the v3 benchmark 'solved': selected-state extraction remains the largest correctness gap, commercial-field gaps remain substantial, Amazon still has no result, and a new retailer-as-brand regression pattern has appeared on three sites.

The safest headline is: **55 of the 146 Run-3 tracked defects are now resolved (37.7%), leaving 91 of those old defects persistent.** This is a tracked-backlog comparison, **not** a claim that the latest run has exactly 91 total defects, because the latest crawl also has new benchmark deviations and dynamic fields can legitimately drift.

## Headline metrics

| Metric | Run-3 v3 baseline | Latest | Change / interpretation |
|---|---:|---:|---|
| Returned benchmark results | 80 / 82 | 81 / 82 | +1; second Zara selected-state capture is now present; Amazon still missing |
| Run-3 tracked defects still present | 146 | 91 | **55 resolved (-37.7%)** |
| Cases carrying Run-3 tracked defects | 54 | 46 | 8 fewer cases still carry an old defect |
| Diagnostic verdict | n/a | 59 success / 22 partial | all 81 transports completed |
| Universal model invocations | n/a | 0 | latest run is deterministic for all 81 outputs |
| Average record completeness | n/a | 96.0% | median 100%; minimum 42.9% |

### Important denominator note

The benchmark has 82 cases but only 81 unique product URLs because Zara is represented twice for two selected states. The latest archive contains 81 record outputs: both Zara states are present, while Amazon case 55 remains absent. Therefore the benchmark return coverage is **81/82**, not 81/81.

## Run-3 tracked defect reduction by area

| Area | Run-3 defects | Old defects remaining | Resolved | Reduction |
|---|---:|---:|---:|---:|
| Product identity / page state | 3 | 3 | 0 | 0.0% |
| Selected variant state | 29 | 24 | 5 | 17.2% |
| Commercial fields | 42 | 30 | 12 | 28.6% |
| Variants / options | 14 | 6 | 8 | 57.1% |
| Product identifiers | 6 | 3 | 3 | 50.0% |
| Core identity / brand | 12 | 3 | 9 | 75.0% |
| Attributes | 25 | 11 | 14 | 56.0% |
| Ratings / reviews | 15 | 11 | 4 | 26.7% |
| **Total** | **146** | **91** | **55** | **37.7%** |

### Interpretation

- **Best progress:** core identity/brand old defects (75% resolved), variants/options (57.1%), attributes (56.0%), and identifiers (50.0%).
- **Still the largest blocker:** selected variant state — only 5 of 29 old defects resolved; 24 remain.
- **Commercial fields:** 12 of 42 old defects resolved, but 30 remain. Treat exact price/availability mismatches separately from missing fields because those values are dynamic.
- **Product identity/page state:** no net progress in the three Run-3 tracked issues; the Amazon missing-result case remains one of them.

## Coverage growth on the same 80 products returned in both runs

Coverage is not accuracy, but the enrichment gains are large and explain much of the defect reduction.

| Field | Run-3 present | Latest present | Δ |
|---|---:|---:|---:|
| `brand` | 70/80 | 80/80 | +10 |
| `price` | 69/80 | 72/80 | +3 |
| `currency` | 69/80 | 72/80 | +3 |
| `availability` | 64/80 | 69/80 | +5 |
| `sku` | 50/80 | 52/80 | +2 |
| `barcode` | 5/80 | 6/80 | +1 |
| `style_id` | 17/80 | 22/80 | +5 |
| `color` | 25/80 | 32/80 | +7 |
| `materials` | 12/80 | 30/80 | +18 |
| `gender` | 23/80 | 26/80 | +3 |
| `condition` | 1/80 | 27/80 | +26 |
| `rating` | 27/80 | 29/80 | +2 |
| `review_count` | 27/80 | 29/80 | +2 |
| `original_price` | 2/80 | 4/80 | +2 |
| `variants` | 45/80 | 46/80 | +1 |

Most notable: **brand +10, materials +18, condition +26, color +7, availability +5, style_id +5, price +3, currency +3**. However, populated fields must still be source-correct; the brand regression below is the clearest example of why coverage alone cannot be used as an accuracy score.

## Confirmed / high-confidence improvements

- **DTLR / Air Jordan 5:** the Run-3 decimal normalization failure (`2.15` instead of `215.00`) is fixed; latest price is `215.00`, and the selected color is recovered.
- **Gymshark Arrival 5 Shorts:** variant count now matches the v3 target of **7**, with the expected size axis recovered.
- **H&M Relaxed-Fit Printed T-Shirt:** price, currency, availability, material, gender, rating/review presence and the **50-variant** target are now recovered. Selected color and original price still need work.
- **New Balance 1080v15:** variant count now matches the **146** target. Selected color/availability semantics are still not fully aligned.
- **Ulta Shape Tape Concealer:** selected color, price, currency, availability and brand are recovered; rating/review fields are present.
- **Rockler:** material and availability regressions from Run-3 are recovered.
- **Eight previously failing cases clear every defect that was explicitly tracked in Run-3:** 5, 25, 27, 31, 33, 37, 41, 81. This does not mean every current dynamic field is guaranteed identical to the old capture.

## New regression pattern: retailer incorrectly promoted to brand

This is the clearest new stable regression and should be treated as P0 because it can corrupt feed identity even when record completeness improves.

| Case | Expected brand | Latest brand |
|---|---|---|
| 36 — selfridges.com | CREED | **Selfridges** |
| 44 — williams-sonoma.com | Breville | **Williams Sonoma** |
| 56 — amsterdamvintagewatches.com | Rolex | **Amsterdam Vintage Watches** |

Likely failure mode: the resolver is allowing the host/publisher/merchant identity to outrank product-scoped brand/manufacturer evidence. Add a regression test that a retailer domain cannot become `brand` when product-scoped JSON-LD, embedded state, or PDP evidence identifies a different brand.

## Other new benchmark deviations — do not hard-classify without live revalidation

Compared with fields that were clean in Run-3, the latest output has **20 benchmark deviations**: **9 title changes, 3 price changes, 3 brand changes, 2 availability changes, 2 variant-count changes and 1 size-options change**. Only the three brand changes above are clearly wrong from stable identity semantics. The rest include canonical-title simplifications and dynamic price/inventory/options changes, so they should be live-revalidated before being called regressions.

Examples include current price changes on Kith, Phase Eight and ROAM; availability changes on ROAM and Uniqlo; and variant/option changes on Sephora and Balmain Beauty.

## Remaining high-priority v3 defects

### P0 — selected state / product binding

**24 of the 29 Run-3 selected-state defects remain.** Representative unresolved cases include StockX selected color/commercial state, Target selected color + size, Nike selected color, Fashion Nova selected color, Gucci selected color, Polo Ralph Lauren selected color, and Jo Malone / Balmain selected size.

Recommended fix direction: keep product identity selection separate from selected-offer/selected-variant state; require URL/query/variant-specific evidence to win over generic product-level JSON-LD when a selected state is encoded in the request.

### P0 — missing commercial pairs

The latest diagnostics independently confirm the same weakness: among partial records, the most common missing contract fields are **price (8)** and **currency (8)**, followed by description (4), image (2), and availability (2). High-value persistent examples are Adidas, StockX, Sneaker Politics and Nintendo/Pragmata.

### P0 — acquisition / result coverage

**Amazon case 55 still has no product result.** Do not treat the absence as a resolved wrong-product bug; it remains an acquisition/extraction coverage failure.

### P1 — remaining variant/options gaps

Variants/options improved from 14 to 6 old defects, but unresolved benchmark cases still include Apple price-range/variant semantics, Breville variant count, Polo Ralph Lauren variant count, and MAC option normalization.

### P1 — ratings/reviews

11 of 15 old rating/review defects remain. These should remain presence/grounding checks rather than exact-value fixtures because the values are volatile.

## Latest diagnostic health

- `diagnose.v3` present for **81/81** outputs.
- Transport outcome `ok`: **81/81**.
- Verdict: **59 success**, **22 partial**.
- Universal model calls: **0**; reported universal model cost: **$0.00**.
- Average contract completeness: **96.0%**; median **100%**.
- No diagnostic `failure_classifications` were emitted.
- Partial verdicts are driven mainly by missing contract fields, incomplete variant evidence / expected axes, and price-currency pairing findings.

This is a strong architectural signal: the deterministic pipeline is extracting substantially more data without falling back to a universal model. The next improvements should target evidence ranking/state binding rather than adding a broader model fallback.

## Recommended engineering order

1. **Fix retailer-as-brand regression first** and add deterministic cross-retailer fixtures (Selfridges/CREED, Williams Sonoma/Breville, Amsterdam/Rolex).
2. **Selected-state binding:** attack the 24 persistent defects by making requested URL/query/variant state a first-class scoring signal.
3. **Commercial completeness:** focus on missing price+currency pairs before exact dynamic-price deltas; prioritize Adidas, StockX, Sneaker Politics and Nintendo.
4. **Finish variant/options cases** while preserving boundary precision; do not inflate counts with sibling products or UI controls.
5. **Amazon acquisition fallback:** keep this separate from extraction correctness.
6. **Revalidate the 17 non-brand new benchmark deviations live** before adding regression fixtures; titles, prices, inventory and option sets can legitimately change.

## Decision

**Proceed with the current architecture.** The latest run shows real, broad improvement and retains deterministic zero-model execution. I would not redesign the extraction stack. The next milestone should be to eliminate the new brand precedence regression and cut the selected-state + missing-commercial backlog; those two areas now dominate the remaining correctness risk.

---

### Method

The comparison matches latest records to the v3.2 benchmark by normalized product identity/URL, including known route aliases for Converse, Nike, Fashion Nova, New Balance, Calvin Klein and MAC. The two Zara captures are matched by selected-state price. Run-3 defect status is re-evaluated against the v3.2 expected/constraint semantics; volatile rating/review and locale-sensitive fields are treated non-brittly. New deviations are only called confirmed regressions where stable identity semantics make the error clear.
