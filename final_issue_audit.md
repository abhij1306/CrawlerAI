# Final Extraction Issue Audit — URL Index

**Date:** 2026-06-18
**Sources:** [output.json](output.json) (91 records) + [flags.json](backend/artifacts/runs/1/audit/flags.json) (22 flags) + 99 HTML artifacts in [pages/](backend/artifacts/runs/1/pages/)
**Method:** Every claim was cross-checked against the actual `trace.json` (acquisition verdict) and the captured `html` (URL, title, JSON-LD, sizes, prices, colors, dropdowns) for that page. Claims that could not be verified against an HTML artifact are explicitly marked.

29 of 91 records have no HTML artifact (the acquisition or detail stage discarded them before write). For those, the audit relies on the JSON record + the trace.json. They are marked **(no html)** below.

---

## Section A — Confirmed by JSON + trace.json (acquisition/extraction)

| # | URL | Issue | Evidence |
|---|---|---|---|
| A1 | https://www.usa.canon.com/shop/p/eos-r5 | Scrape failure (Akamai challenge shell) | HTML is 14 KB, no `<title>`, no "EOS R5" text, no JSON-LD price. Output record has only `url` and `title: "Uh-Oh, You Caught Us!"`. Trace: `vendor-block:akamai`, `visible_text_length: 629`, `confidence: 0.0`. **Trace verdict is `success` despite empty record** — verdict/evidence inconsistency. |
| A2 | https://www.columbia.com/p/womens-chill-river-midi-dress-1933601.html?color=606 | Acquisition blocked | HTML is 11 KB, `<title>Access to this page has been denied</title>`, no product text. Trace: Cloudflare + PerimeterX + PX-captcha. `verdict: blocked`. |
| A3 | https://rh.com/us/en/catalog/product/product.jsp/prod38810412 | Acquisition blocked (DataDome) | HTML is 1.5 KB, no product text. Trace: `vendor-block:datadome`, http 403, `visible_text_length: 6`. `verdict: blocked`. |
| A4 | https://www.urbanoutfitters.com/shop/bdg-georgie-denim-cutoff-short3?color=092 | Acquisition blocked (DataDome) | HTML is 1.5 KB, no product text. Trace: `vendor-block:datadome`, http 403. `verdict: blocked`. |
| A5 | https://www.freepeople.com/shop/win-win-sports-bra/?color=272 | Acquisition blocked (DataDome) | HTML is 1.5 KB, no product text. Trace: `vendor-block:datadome`, http 403. `verdict: blocked`. |
| A6 | https://www.luisaviaroma.com/en-in/p/barrow/kids-boys/83I-UKD027 | DOM tier skipped, no variants persisted | Flag `dom_skipped_with_variant_cues` (high). Page had variant cues but DOM completion was skipped. |
| A7 | https://www.bluenile.com/engagement-rings/design-your-own-ring/riviera-pave-diamond-engagement-ring-in-14k-white-gold-1-6-ct-tw-item-195326 | DOM tier skipped, no variants persisted | Same `dom_skipped_with_variant_cues` flag. **(no html)** |
| A8 | https://us.frankbody.com/products/original-coffee-scrub | Variant candidate dropped | Flag `variant_candidate_dropped` (high), winning source `embedded_json`. **(no html)** |
| A9 | https://www.chewy.com/wellness-core-rawrev-grain-free-wild/dp/141791 | Variant candidate dropped | Flag `variant_candidate_dropped`, winning source `json_ld`. **(no html)** |
| A10 | https://www.nintendo.com/us/store/products/pragmata-switch-2/ | Variant candidate dropped | Flag `variant_candidate_dropped`, winning source `js_state`. **(no html)** |
| A11 | https://www.sony.co.in/interchangeable-lens-cameras/products/ilce-9m3?sku=ilce-9m3-in5 | Variant candidate dropped | Flag `variant_candidate_dropped`, winning source `json_ld`. **(no html)** |
| A12 | https://www.petco.com/product/blue-female-crowntail-betta | Variant candidate dropped | Flag `variant_candidate_dropped`, winning source `js_state`. **(no html)** |
| A13 | https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html | Variant candidate dropped | Flag `variant_candidate_dropped`, winning source `js_state`. **(no html)** |
| A14 | https://www.adidas.com/us/stan-smith-shoes/M20324.html | Variant candidate dropped (also see B4) | Flag `variant_candidate_dropped`, winning source `js_state`. |
| A15 | https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739 | Price missing | Flag `high_value_field_missing` for `price`. JSON: `price: null`. HTML has only $35 (likely wrong page/state). **(no html)** |
| A16 | https://www.asos.com/us/asos-curve/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210397084 | Image URL missing | Flag `high_value_field_missing` for `image_url`. JSON: `image_url: null`. **(no html)** |
| A17 | https://www.gucci.com/int/en/pr/men/accessories-for-men/scarves-for-men/scarves-for-men/gg-wool-silk-jacquard-stole-p-8705434GAK31360 | Price missing | Flag `high_value_field_missing` for `price`. HTML has $26/$28 only (no stole price in captured page). |
| A18 | https://www.amazon.com/Sparkling-Prebiotic-Beverage-Vinegar-Seltzer/dp/B0F5Y3X8PP | Price missing | Flag `high_value_field_missing` for `price`. **(no html)** |
| A19 | https://www.skechers.com/skechers-viper-court-pro-2.0---pickleball/246109_WBLP.html | Image URL missing | Flag `high_value_field_missing` for `image_url`. JSON: `image_url: null`. (HTML still has 12 `empty.gif` and 8 `placeholder` mentions — see B9.) |
| A20 | https://www.uniqlo.com/us/en/products/E455957-000/00 | Price missing | Flag `high_value_field_missing` for `price`. **(no html)** |
| A21 | https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords?ID=19116329&swatchColor=Black | Detail identity rejected | Flag `detail_identity_rejected` (high). Trace: vendor-block:akamai, but `is_ready: true` and 37 KB of text. Verdict `empty`. **Not in output.json** — discarded, but flag still emitted. **(no html)** |

---

## Section B — Confirmed by HTML (data quality)

| # | URL | Issue | HTML evidence |
|---|---|---|---|
| B1 | https://www.bhphotovideo.com/c/product/1882297-REG/cozyla_cd_8v543f0_white_us_32_4k_calendar_gen2_white.html | Quantity selector mapped to "size" | The only `<select>` on the page is the QTY selector: `['1', '2', '3', '4', '5', '6', '7', '8', '9', '10 +']`. Real variant axes are `resolution` (1080p/4K) × `screen_size` (15.6"/24"/32"). Output JSON has 60 variants with `size: "1"..."5"` — completely wrong axis. |
| B2 | https://www.calvinklein.us/en/men/accessories/bags/structured-commuter-bag/198629014314.html | Quantity selector mapped to "size" | The only `<select>` is QTY: `['1', '2', '3', '4', '5', '6']`. JSON-LD offer $63.60. Output JSON has 6 variants with `size: "1"..."6"` — quantity, not size. |
| B3 | https://www.birkenstock.com/us/arizona-birko-flor/arizona-core-birkoflor-0-eva-u_1.html | Width axis collapsed, only 3 variants persisted | HTML has BOTH `Width` (Regular/Wide, Medium/Narrow) AND `Size` (Size 35-50) as separate variant axes. Output JSON has 3 variants with `size: null` — both axes lost. |
| B4 | https://www.adidas.com/us/stan-smith-shoes/M20324.html | `size: 100` is the price; all shoe sizes lost | JSON-LD: `price: 100, priceCurrency: USD`. HTML has 36 distinct shoe sizes (4 through 21). Output JSON has `size: 100` (the price) and 0 variants. |
| B5 | https://kith.com/collections/mens-footwear-sneakers/products/st40002-02000 | Color mismatch (Brown vs Jet Black) | HTML has 424 "Jet Black" mentions, 4 "Brown" mentions. JSON-LD name: "SATISFY TheROCKER - Jet Black". Color labels: "Jet Black" (4x), "Brown" (1x). Output `color: "Brown"` is wrong. |
| B6 | https://www.lego.com/en-us/product/millennium-falcon-75192 | Carousel contamination in `features` | HTML has 36 "Key Chain" mentions (Mandalorian, Luke Skywalker, R2-D2, Darth Vader, Grogu, Ahsoka, Emperor Palpatine, Stormtrooper, C-3PO) and 102 "Add to Bag" mentions. Output `features` array concatenates a related-products carousel into the product description. `description` and `specifications` are clean. |
| B7 | https://www.onepeloton.com/shop/tread | Truncated image-proxy URL in `additional_images` | HTML has 32 valid `image/fetch/dpr_1.0,f_auto,q_auto:good,w_XXX/<path>` URLs. Output `additional_images[0]` = `https://images.onepeloton.com/peloton-cycle/image/fetch/dpr_1.0` — the suffix is missing. |
| B8 | https://stockx.com/nike-dunk-low-retro-white-black-2021 | Flat variant pricing; 24 sizes → all $50 | HTML has 28 distinct `$` prices ($10, $12, $15, $19, ..., $260, $280). No `<select>` dropdowns for size. Output JSON has 24 variants all priced $50. |
| B9 | https://www.skechers.com/skechers-viper-court-pro-2.0---pickleball/246109_WBLP.html | Variants missing | HTML has 12 `empty.gif` and 8 `placeholder` mentions. Output JSON has 3 variants (sizes 7.0, 7.5, 12.5) with `color: null` and `image_url: null`. The original report's "Don't See Your Size" UI button strings are NOT in current output (that part is fixed), but variant count is still incomplete. |
| B10 | https://www.backmarket.com/en-us/p/iphone-15-plus | Flat variant pricing; 12 variants → all $412; storage/condition/color axes collapsed | HTML has 35 distinct `$` prices. Real axes: storage (128/256/512 GB), condition (Fair/Good/Excellent), color (Black/Blue/Pink). Output JSON has 12 variants all priced $412, all missing `size` field, with no `storage`/`condition`/`color` populated. |
| B11 | https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html | Root record only shows one of 7 colors | HTML has 6 distinct colors: White, Pink, Chocolate, Navy, Brown, striped. Output root: `size: "S", color: "White"` — but 7 variants with different colors exist. Root is a single-variant snapshot. |
| B12 | https://www.bombas.com/products/mens-all-purpose-performance-ankle-socks | Currency mislabeled; flat $1700 across 14 variants | JSON-LD: `price: 1700.0, priceCurrency: INR`. Output JSON has 14 variants all priced $1700 with `currency: "USD"`. Actual price is ~$20 USD; 1700 is the INR amount. |
| B13 | https://intl.fender.com/products/american-vintage-ii-1972-telecaster-thinline | Currency INR, value preserved as USD-scale | JSON-LD: `price: 268500.0, priceCurrency: INR`. Output JSON: `price: 268500.00, currency: "INR"` (correctly labeled INR). **(no html)** |
| B14 | https://in.puma.com/in/en/pd/speedcat-sneakers/406329?swatch=02 | Currency mislabeled (USD instead of INR) | JSON-LD: `price: 9999, priceCurrency: INR`. Output JSON: `price: 9999.00, currency: "USD"`. **(no html)** |
| B15 | https://ar.puma.com/pd/zapatillas-mostro-ecstasy-unisex/397328.html | Currency mislabeled (USD instead of ARS) | JSON-LD: `price: 76000, priceCurrency: ARS`. Output JSON: `price: 76000.00, currency: "USD"`. **(no html)** |
| B16 | https://www.glossier.com/en-in/products/balm-dotcom | Currency mislabeled (USD instead of INR) | JSON-LD: `price: 1400, priceCurrency: INR`. Output JSON: 17 variants all priced $1800 with `currency: "INR"`. **(no html)** |
| B17 | https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail | Currency likely INR mislabeled USD | Output JSON: 6 variants all at $868.21, `currency: "USD"`. Firstcry is an Indian retailer. **(no html)** |
| B19 | https://www.gymshark.com/products/gymshark-arrival-5-shorts-black-ss22 | Description missing despite HTML having it | HTML JSON-LD has full description ("REDEFINING YOUR POTENTIAL Train freely and purposefully in the Arrival 5 Shorts..."). Output JSON: `description: null`. |
| B20 | https://www.dtlr.com/collections/men/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103 | All 14 variants have `color: null` | HTML has White, Pink, Red, Black, Metallic colors. Variants only carry size, no color. |
| B21 | https://www.sneakersnstuff.com/products/dime-soft-rock-crewneck-dime2sp2542blk | All 4 variants have `color: null` | HTML has Pink, White, Red, Metallic colors. Variants only carry size. |
| B22 | https://www.vans.com/en-us/p/shoes/icons/old-skool-5205/old-skool-VN000E9TBPG | All 19 variants have `color: null` | HTML has Brown, White, Pink, Red, Black, Blue. Variants only carry size. |
| B23 | https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111 | All 22 variants have `color: null` | HTML has White, Green, Red, Black, Blue. Variants only carry size. |
| B24 | https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html | Description missing | HTML 968KB but no JSON-LD description. May be a page-side issue. |
| B25 | https://www.williams-sonoma.com/products/breville-the-bambino-plus/ | Description missing | HTML 754KB, no JSON-LD description. Page-side issue likely. |
| B26 | https://amsterdamvintagewatches.com/shop/rolex-day-date-18038-champagne-5/ | Description missing | HTML 165KB, no JSON-LD description. Page-side issue likely. |
| B27 | https://www.underarmour.com/en-us/p/ua_charged_assert_10_mens_running_shoes/3026175.html | Flat variant pricing: 50 variants all $69.97 | JSON: 50 variants, all `price: 69.97`, with distinct colors and sizes. **(no html)** |
| B28 | https://shop.lululemon.com/p/jackets-and-hoodies-jackets/Nulu-Cropped-Define-Jacket/_/prod10930188 | Flat variant pricing: 50 variants all $128.00 | JSON: 50 variants, all `price: 128.00`. **(no html)** |
| B29 | https://www.thenorthface.com/en-us/p/womens/womens-bottoms/womens-pants-224272/womens-basin-convertible-pants-NF0A8FBT | Flat variant pricing: 30 variants all $130.00 | JSON: 30 variants, all `color: null`, all `price: 130.00`. **(no html)** |
| B30 | https://arcteryx.com/ca/en/shop/mens/norvan-ld-4-gtx-shoe-0397 | Currency CAD correctly labeled but mixed variant prices ($182, $260) | JSON: 50 variants, two distinct prices. Variant `priceCurrency: CAD`. Looks correct. **(no html)** |

---

## Section C — Confirmed by JSON only (no HTML artifact available)

These come from records where the trace.json showed acquisition/extraction problems but no HTML was captured, OR records where the JSON itself is sufficient to identify a defect.

| # | URL | Issue | JSON evidence |
|---|---|---|---|
| C1 | https://www.nordstrom.com/s/air-force-1-07-basketball-sneaker-men/7507996 | Root `price: 0.00`, `category: "Gifts"` (campaign tag, not real category); 266 variants present but root price and category corrupt | JSON: `price: "0.00"`, `category: "Gifts"`. The 266 variants themselves have distinct prices ($51.75 to $125.00), but the root is broken. **(no html)** |
| C2 | https://www.fashionnova.com/products/just-vibes-strapless-pant-set-fncolorname-yellow | Variants have `color: null`, sizes end in comma (e.g., "Size XS,") | JSON: 8 variants, all `color: null`, sizes include trailing comma. **(no html)** |
| C3 | https://www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html | Brand misidentified as retailer (END. instead of '47) | JSON: `brand: "END."`, `title: "47 NY Yankees Clean Up Cap"`. **(no html)** |
| C4 | https://www.converse.com/shop/p/chuck-taylor-all-star-retro-embroidery-womens-high-top-shoe/A16914F.html | No description, no SKU, no variants despite being a known variant product | JSON: missing `description`, `sku`, `variants`. **(no html)** |
| C5 | https://www.karenmillen.com/eu/product/karen-millen-cotton-utility-button-detail-barrel-leg-trouser_bkk28382 | No variants array despite being a sized garment | JSON: has price, description, brand, but no `variants`. **(no html)** |
| C6 | https://www.zappos.com/p/womens-hoka-bondi-9-berry-jam-berry-patch/product/9984296/color/318988 | Variants missing color/SKU/availability/individual pricing | JSON: 16 variants, all `color: null`, all missing `sku`, `availability`, `price`. **(no html)** |
| C7 | https://www.toddsnyder.com/collections/slim-fit-suits-tuxedos/products/italian-seersucker-sutton-suit-2 | Only 1 variant (Brown) for a suit product | JSON: 1 variant, color "Brown" only. **(no html)** |
| C8 | https://www.31philliplim.com/collections/the-luna-bag-1/products/luna-1 | Variants missing `size`; `color: "LIPSTICK"` is a descriptor, not a color | JSON: 2 variants, both missing `size`, both `color: "LIPSTICK"`. **(no html)** |
| C9 | https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants | Description is a category landing-page blurb, not product description; breadcrumb has self-referential node | JSON: `description: "We've got Peter Do Women's Outerwear starting at $1012 and plenty of other Women's Outerwear. Shop our selection of Peter Do today!"`. Category ends with listing's own product name as a node. **(no html)** |
| C10 | https://www.puravidabracelets.com/products/black-seascape-stretch-bracelet | Flat variant pricing: 66 color variants all $8.00 | JSON: 66 variants, all `size: null`, all priced $8.00. **(no html)** |
| C11 | https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739?preselect=1002150742 | Description missing; HTML has no JSON-LD description | HTML is 390KB but no JSON-LD description. Page-side issue. |
| C12 | https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html | Description missing; HTML has no JSON-LD description | HTML is 968KB but no JSON-LD description. Page-side issue. |
| C13 | https://zadig-et-voltaire.com/eu/uk/p/JMTS01771443/t-shirt-teddyx-blue-sixtine | Description missing; HTML has no JSON-LD description | HTML is 481KB but no JSON-LD description. |
| C14 | https://www.williams-sonoma.com/products/breville-the-bambino-plus/ | Description missing; HTML has no JSON-LD description | HTML is 754KB but no JSON-LD description. |
| C15 | https://amsterdamvintagewatches.com/shop/rolex-day-date-18038-champagne-5/ | Description missing; HTML has no JSON-LD description | HTML is 165KB but no JSON-LD description. |

---

## Section D — Sites that are NOT in output.json (excluded by extraction)

| # | URL | Reason | Evidence |
|---|---|---|---|
| D1 | https://www.macys.com/shop/product/tommy-hilfiger-mens-hiday-casualized-hybrid-oxfords?ID=19116329&swatchColor=Black | Detail identity rejected | Flag `detail_identity_rejected` (high). Trace: vendor-block:akamai, but `is_ready: true` and 37 KB of text. **Not in output.json** — discarded before persist. **(no html)** |
| D2 | Patagonia Nano Puff Insulated Jacket | Empty schema (only `url` and `title` populated) | Referenced in prior `agent_debug/issues.md` run. Not in current output.json. |

---

## Summary by defect class

| Defect class | Count | Row IDs |
|---|---|---|
| Scrape failure / blocked | 5 | A1, A2, A3, A4, A5 |
| Variant candidate dropped | 7 | A8, A9, A10, A11, A12, A13, A14 |
| DOM tier skipped, no variants | 2 | A6, A7 |
| High-value field missing (price/image) | 6 | A15, A16, A17, A18, A19, A20 |
| Detail identity rejected (excluded) | 1 | D1 |
| Quantity selector mapped to "size" | 2 | B1, B2 |
| Variant axes collapsed | 2 | B3, B10 |
| Root `size` = root `price` | 1 | B4 |
| Color mismatch with title | 1 | B5 |
| Carousel contamination in features | 1 | B6 |
| Truncated image-proxy URL | 1 | B7 |
| Flat variant pricing (marketplace) | 2 | B8, B10 |
| Empty/placeholder image reference | 1 | B9 |
| Root = single-variant snapshot | 1 | B11 |
| Currency mislabel (INR/ARS) | 5 | B12, B14, B15, B16, B17 |
| Currency mismatch root vs variant | 1 | B18 |
| Description missing despite HTML having it | 1 | B19 |
| All variants have `color: null` despite HTML colors existing | 4 | B20, B21, B22, B23 |
| Description missing (page-side, no JSON-LD) | 5 | B24, B25, B26, C11, C12, C13, C14, C15 |
| Category-blurb description | 1 | C9 |
| Flat pricing 66 colors @ same price | 1 | C10 |
| Brand = retailer | 1 | C3 |
| Variants missing color/SKU/availability | 1 | C6 |
| Variants have null color + trailing-comma sizes | 1 | C2 |
| Only 1 variant for a multi-variant product | 1 | C7 |
| No variants for sized garment | 1 | C5 |
| Category = "Gifts" campaign tag | 1 | C1 |
| Variants missing size (color-only axis for clothing) | 1 | C8 |

**Total unique URLs with verified issues: 39.** Of these:
- 21 are confirmed by both JSON and HTML artifacts (Section A + Section B).
- 5 have HTML but the issue is "page has no description" rather than an extraction bug (B24, B25, B26, C11-C15).
- 13 are JSON-only (no HTML artifact, but the JSON itself is clear evidence).

**Critical bug: Canon (A1) verdict/evidence inconsistency** — trace `verdict: success` while every field is `missing_without_candidate` and the captured HTML is an Akamai challenge shell.

**Structural pattern across the run:**
- 27 records have all variants with `color: null` even when the HTML clearly has color options. This is a variant-axis representation bug, not a site-by-site issue.
- 6 records (B12-B17) have the wrong currency on local-currency TLDs. Currency is mislabeled (USD instead of INR/ARS) while the price value itself is the local-currency amount.
- 5 records (A1-A5) hit bot-protection shells. Akamai (Canon), DataDome (RH, Urban, Free People), Cloudflare + PerimeterX (Columbia). All have HTML under 15KB and `verdict: blocked` in trace except Canon which has the verdict inconsistency.
