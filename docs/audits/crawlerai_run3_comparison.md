# CrawlerAI Run 3 — Defect Comparison

**Benchmark:** `crawlerai_eval_html_grounded_v3_2.json`  
**Previous defects:** `crawlerai_defects_html_grounded_v3_2.json`  
**Latest run:** `run-3.json`

## Summary

- Defects: **257 → 146** (**43.2% reduction**)
- Failing eval cases: **75 → 54** (**21 fewer**)
- **22 previously failing cases are now clean**
- **121 previous field defects are genuinely resolved**
- One important caveat: Amazon case **55** now returns **no result**. Its five previous field defects are therefore not counted as fixes; they are superseded by one `MISSING_PRODUCT_RESULT` root-cause defect.

| Area | Previous | Run 3 | Δ |
| --- | ---: | ---: | ---: |
| Product identity/page state | 4 | 3 | -1 |
| Selected variant state | 49 | 29 | -20 |
| Commercial fields | 42 | 42 | +0 |
| Variants/options | 14 | 14 | +0 |
| Product identifiers | 13 | 6 | -7 |
| Core identity/brand | 16 | 12 | -4 |
| Attributes | 59 | 25 | -34 |
| Ratings/reviews | 60 | 15 | -45 |

## What improved

The strongest improvement is in **ratings/reviews (60 → 15)**, followed by **attributes (59 → 25)** and **selected variant state (49 → 29)**. Product identifiers also improved from **13 → 6**.

High-impact fixes include:

- **StockX (case 1):** product identity is now correct — `Nike Dunk Low Retro White Black Panda` instead of the unrelated Varsity Jacket Dunk.
- **Selected state:** 20 prior color/size/fit defects are resolved across pages including Puma, Vans, Fashion Nova, Gymshark, Zappos and J.Crew.
- **Commercial extraction:** old issues were fixed on Phase Eight, Brooklinen, Breville, Fellow, New Balance and others.
- **Identifiers:** barcode/style/SKU recovery improved materially; Phase Eight, Phillip Lim, Savannahs, B&H and Chewy are examples.
- **Chewy (case 81):** variant count is now correct (`3`), and barcode/size/rating/review fields are populated.
- **22 previously failing cases are fully clean:** 7, 12, 14, 15, 16, 23, 24, 38, 42, 43, 49, 50, 53, 58, 59, 60, 62, 63, 65, 66, 68, 75.

## What regressed / needs verification

Clear engineering regressions:

- **DTLR (case 5):** price is now **`2.15` instead of `215.00`** — this looks like a decimal/cents normalization bug.
- **Peloton (case 40):** price, currency and availability disappeared; the already-problematic SKU also became missing.
- **Rockler (case 41):** availability disappeared.
- **Amazon (case 55):** the previous run returned the wrong product; Run 3 returns **no product result at all**. Product identity is no longer wrong, but acquisition/extraction coverage regressed.
- **MAC (case 77):** size options changed from the expected gram units (`1.5 g`, `1.3 g`) to ounce units (`0.05 oz`, `0.04 oz`), so option normalization is now failing.
- **Apple (case 34):** the already-wrong `price_max` degraded from a wrong value to missing, and the configurable product-family page remains unresolved.

There are also new exact-price mismatches on cases **9, 18, 45, 47, 71, 73, 74 and 80**. These look plausibly like normal retail price/sale changes rather than crawler regressions. **Re-capture those HTML pages before asking Codex to change extraction logic for them.** Case 45 (Fender) is the only previously clean case that now fails, and its sole failure is one of these price changes.

## Recommended next work

1. **Fix numeric price normalization first**, starting with DTLR's `215.00 → 2.15` failure.
2. **Restore commercial-field extraction** on Peloton/Rockler and investigate the Amazon no-result path.
3. **Finish variant completeness/state handling:** Nike is `25 vs 24`, H&M improved from `0 → 10` but still expects `50`, New Balance remains `48 vs 146`, and MAC needs unit normalization.
4. Continue selected-state and attribute cleanup after those P0 issues; those areas improved substantially but still account for many remaining defects.

The updated defect JSON intentionally remains compact: expected values stay in the eval file, while this file contains only issue codes, affected case IDs, area aggregates and a few representative examples.
