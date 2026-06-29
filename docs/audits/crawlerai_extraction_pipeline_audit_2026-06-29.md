# CrawlerAI Extraction Pipeline Audit

**Date:** 29 June 2026  
**Project audited:** `C:\Projects\CrawlerAI` (active Serena project)  
**Input audited:** 90 ecommerce-detail records from `Pasted text(21).txt`  
**Code changes made:** None  
**Audit approach:** Output profiling, symbolic code tracing through acquisition → collection → entity linking → resolution → validation → materialization → persistence, and review of current regression/replay coverage.

---

## 1. Executive assessment

The extraction system has a materially improved evidence and integrity model, but the active implementation still has four release-blocking architectural weaknesses:

1. **Structured-data root selection fails open.** If an exact product root cannot be selected, JS-state and JSON-LD traversal can admit the entire payload.
2. **Child ownership is asserted too early.** Generic offers and assets are assigned to the page product during collection, before product identity has been proven.
3. **Partial/review records are persisted as ordinary product rows.** Integrity metadata exists in `ExtractionResult`, but it is absent from the flat record dataset.
4. **The live acceptance gate is not reproducible everywhere.** The latest artifact replay test skips when local capture files are unavailable.

There is also a significant **data-to-code provenance mismatch**. The uploaded dataset contains failures that the current checkout has exact regression tests for:

- Back Market includes an unrelated PlayStation image, while the current unit test explicitly rejects that shape.
- DTLR publishes a Shopify variant ID as the product SKU, while the current unit test explicitly requires `HQ7978-103`.
- Shoe Palace contains other-product imagery, while current replay notes and tests claim this class is rejected.

Therefore, the first action must be replaying the exact capture bundles that produced this dataset against the current checkout. Implementing fixes directly from this JSON could duplicate already-completed work or patch stale output.

**Overall status: Not production-clean for unqualified flat exports.**

---

## 2. Dataset findings

Counts overlap; a URL can belong to multiple categories.

| Signal | Count |
|---|---:|
| Total product records | 90 |
| Records with at least one automated/manual audit signal | 68 |
| Missing top-level price | 16 |
| Missing top-level currency | 16 |
| Missing top-level availability | 21 |
| Missing primary image | 3 |
| Missing brand | 1 |
| No public variants array | 45 |
| Total variant rows present | 557 |
| Variant rows missing availability | 18 across 6 URLs |
| Variant rows missing SKU | 20 across 5 URLs |
| Variant rows missing price and currency | 25 across 5 URLs |
| Optionless variant rows | 4 |
| URLs with duplicate underlying image identities | 8 |
| URLs with malformed repeated query delimiters | 1 |
| Confirmed cross-product media contamination | 2 URLs |

These are triage signals, not all confirmed extraction defects. For example, no variants can be legitimate for a single-SKU product, and missing offer data can reflect blocked or uncaptured product APIs. The flat dataset does not include the field-state evidence needed to distinguish these cases.

---

## 3. Pipeline traced

The production crawl path does use the current extraction engine:

```text
crawl/pipeline/record_extraction_stage.py
  -> app.extraction.extract
  -> extraction/engine.py
  -> collectors
  -> entities.py
  -> resolution.py
  -> validation.py
  -> materialization.py
  -> crawl/pipeline/persistence.py
  -> public_record_firewall.py
```

The engine computes `verdict`, `data_integrity`, findings, decisions and field states. However, the persisted public record payload contains only the product row. This separation is central to several output problems below.

---

# 4. Audit findings

## AUD-01 — Output provenance does not identify the producing code or integrity state

**Severity:** Critical  
**Confidence:** Confirmed

### Evidence

The attached JSON contains product rows only. It does not identify:

- crawl/run ID;
- URL-result ID;
- capture bundle ID;
- extraction schema/build version;
- Git commit;
- verdict;
- data-integrity status;
- field evidence states;
- rejected candidates or variant drops.

The active checkout contains exact regression tests that contradict multiple attached rows:

- `backend/tests/unit/test_extraction_pipeline.py:5007-5047` rejects Back Market related-product imagery.
- `backend/tests/unit/test_extraction_pipeline.py:6143-6157` prevents a DTLR variant ID from becoming the product SKU.
- Current artifact notes state Shoe Palace recommendation images are rejected.

### Root cause

`ExtractionResult` contains the required metadata (`backend/app/extraction/contracts.py:498-528`), but `_public_record_payload()` serializes only the product model (`backend/app/crawl/pipeline/extraction_loop.py:385-389`). Persistence then stores every returned record independently of its verdict (`extraction_loop.py:393-472`).

### Required correction

Create a versioned export envelope or sidecar containing, per URL:

- `run_id`, `url_result_id`, `bundle_id`;
- extraction schema version and Git commit/build ID;
- `verdict`, `data_integrity`, transport outcome;
- field states and issue/finding IDs;
- artifact references;
- whether the public row is clean, partial, review-only, or source-limited.

A consumer-facing export should default to `data_integrity=clean`, with an explicit option to include partial/review rows.

---

## AUD-02 — Structured root selection fails open

**Severity:** Critical  
**Confidence:** Confirmed in code

### Evidence

`selected_product_root_paths()` recognizes roots primarily when an embedded object URL exactly matches the requested resource identity (`backend/app/core/records/js_state_scope.py:56-92`).

When no root is found, `path_is_within_selected_root()` returns `True` for every object (`backend/app/extraction/collectors/js_state.py:224-231`).

Both the JS-state and JSON-LD collectors rely on this behavior:

- `collectors/js_state.py:43-71`
- `collectors/jsonld.py:38-60`

### Impact

A payload that identifies the page product by ID, handle, SKU, cache key, relative URL, or another schema—but not an exact canonical URL—can cause the collector to traverse all product-like objects. Recommendation cards, search results, sibling products and cached entities can then become candidates.

This failure mode matches the observed classes:

- Back Market PlayStation image attached to an iPhone.
- Shoe Palace images/descriptions from other shirts.
- Previously observed END search-result variants and Chewy Apollo-cache contamination.

### Required correction

Root selection must be **fail-closed**:

1. Build candidate product roots from URL, relative URL, handle, product ID, SKU/MPN, title/H1 agreement and explicit schema relations.
2. Select one root or return an unresolved/ambiguous target.
3. Quarantine all other roots.
4. Never interpret “no selected root” as “the entire payload is selected.”

No hostname or product-specific exceptions should be introduced.

---

## AUD-03 — DOM collection is page-global rather than product-container scoped

**Severity:** Critical  
**Confidence:** Confirmed in code

### Evidence

`DomCollector.collect()` searches the whole document for:

- `h1`;
- `head title`;
- `[data-price]`;
- `[data-currency]`;
- `[data-sku]`;
- broad `main img` selectors.

See `backend/app/extraction/collectors/dom.py:47-121`.

All DOM offer candidates are grouped into the same `offer:dom:product` group and attached to the canonical page-product subject. Images under `main` are accepted unless token heuristics reject their surrounding context (`dom.py:179-206`).

### Impact

Modern PDPs commonly place recommendations, bundles, recently viewed cards, sticky widgets and payment modules inside `main`. Global selectors can merge unrelated prices, SKUs, images and descriptions into the selected product.

### Required correction

Introduce an explicit DOM product-root selection stage:

- derive candidate containers around H1, canonical form, product gallery, selected SKU and purchase controls;
- choose a single coherent container;
- collect scalar facts and children only inside that container;
- treat recommendation/bundle/listing containers as separate roots;
- retain unresolved candidates as rejected evidence rather than silently mapping them.

---

## AUD-04 — Collectors fabricate product ownership before identity is proven

**Severity:** Critical  
**Confidence:** Confirmed in code

### Evidence

`network_row()` creates one product subject from the final page URL, then assigns that subject as parent for every mapped offer and asset (`backend/app/extraction/collectors/js_state.py:234-328`).

Entity linking later trusts `parent_subject_id` to determine the owner (`backend/app/extraction/entities.py:707-726`). `_link_offers()` and `_link_assets()` then materialize those relationships (`entities.py:592-704`).

### Impact

Once an unrelated nested object passes broad context checks, its offer/image is no longer merely a candidate—it arrives with an asserted page-product relationship. Downstream ranking and output filtering cannot reliably undo this without losing provenance.

### Required correction

Collectors should emit:

- source-root/object identity;
- possible relation type and relation evidence;
- identity candidates;
- no final product parent unless the source explicitly provides one.

The entity graph—not the collector—must decide ownership using explicit references or strong multi-signal identity agreement.

---

## AUD-05 — Partial and review records are persisted without record-level qualification

**Severity:** Critical  
**Confidence:** Confirmed in code

### Evidence

The engine returns records for `success`, `partial` and `review` verdicts (`backend/app/extraction/engine.py:169-267`, especially the final record-selection branch).

The persistence stage serializes and persists all returned records (`backend/app/crawl/pipeline/extraction_loop.py:393-472`).

The attached dataset therefore cannot distinguish:

- a clean complete product;
- an honest source-limited product;
- a record with captured-but-rejected offer evidence;
- a review-only identity;
- a product with integrity findings.

### Impact

Downstream users interpret missing price/availability or suspicious images as ordinary field values rather than a quality state. This also makes completeness metrics misleading.

### Required correction

Keep partial records if they are useful, but make integrity impossible to lose:

- persist a mandatory URL-result foreign key and integrity class with every record;
- expose verdict/field states in exports;
- offer `clean_only`, `include_source_limited`, and `include_review` export modes;
- prevent “review” records from entering clean datasets.

---

## AUD-06 — Acquisition expectations do not match the public ecommerce schema

**Severity:** High  
**Confidence:** Confirmed in code

### Evidence

The default ecommerce acquisition contract includes only title, price and image:

`backend/app/core/config/field_mappings.py:300-314`

Browser retry targets include price, currency, title and image, but not availability or variants.

Variant retry occurs only when:

- variants were explicitly requested; or
- DOM variant cues were detected and controls appear incomplete.

See `backend/app/extraction/result_building.py:155-229`.

### Observed output

- 45/90 records have no public variants.
- 21/90 lack top-level availability.
- 18 variant rows lack availability.

Some are legitimate, but the pipeline currently treats these fields as opportunistic while the resulting schema exposes them as ordinary product capabilities.

### Required correction

Define explicit product-detail profiles:

1. **Core identity profile:** URL, title, brand, primary image.
2. **Sellable offer profile:** atomic price + currency, availability state/reason.
3. **Variant profile:** option axes, variant identity, offer and availability.

If a run expects variants, add variants and availability to acquisition requirements and browser/network capture policy. Otherwise mark them `not_requested`, not merely absent.

---

## AUD-07 — Variant representation is structurally permissive and conflates different concepts

**Severity:** High  
**Confidence:** Confirmed in code and output

### Evidence

`CommerceVariantRecord` declares transport fields, while option axes are accepted through `extra="allow"` inherited from `PublicRecord`:

- `backend/app/extraction/contracts.py:340-398`

A variant can be published with no option axis if it has an explicit ID/SKU/URL and any commercial fact:

- `backend/app/extraction/materialization.py:517-526`

Output safety also considers any transport field sufficient for actionability:

- `backend/app/core/records/output_safety.py:248-273`

### Observed output

- 20 variant rows lack SKU.
- 25 lack price/currency.
- 18 lack availability.
- 4 rows have no meaningful option axis.
- Several records expose a one-row “variant” that is functionally just the parent offer.

### Required correction

Use separate typed concepts:

- `OptionGroup` and `OptionValue`;
- `PurchasableVariant`;
- `VariantOffer`;
- `SelectedConfiguration`;
- parent product offer.

A public variant should require either a real option configuration or an explicit source relation proving that the row is a sellable child, not merely a duplicate parent offer.

---

## AUD-08 — Semantic values are still changed after resolution

**Severity:** High  
**Confidence:** Confirmed in code

### Evidence

After resolution, materialization still:

- aggregates/replaces parent price and creates price ranges;
- removes parent SKU;
- aggregates parent availability;
- derives/inherits variant identity;
- filters conflicting asset URLs.

Relevant code:

- `backend/app/extraction/materialization.py:69-145`
- `_cohere_parent_offer()`: `materialization.py:172-246`
- `backend/app/core/records/output_safety.py:44-119`
- `sanitize_materialized_record()`: `output_safety.py:171-223`

The published entity graph contains counts and root IDs, not the final post-materialization values (`backend/app/extraction/result_building.py:277-308`).

### Impact

The public record can diverge from the resolved evidence graph. A replay may show accepted decisions that do not exactly explain the final value, while safety filtering can hide the original upstream contamination.

### Required correction

Move all semantic derivations into resolution as explicit `DerivedFact` or typed decisions with evidence lineage. Materialization should serialize only. The public firewall should enforce keys, types and enums—not select product images or alter commercial meaning.

---

## AUD-09 — Asset delivery validation and deduplication are incomplete

**Severity:** Medium–High  
**Confidence:** Confirmed in output and code

### Observed output

- 8 URLs contain repeated underlying assets under different delivery transforms.
- Glossier contains URLs with two `?` query delimiters.
- Grailed repeats the primary image in additional images after query normalization.
- Back Market and Shoe Palace contain foreign-product media.

Affected duplicate-identity URLs include:

- `https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants`
- `https://www.brooklinen.com/products/plush-bath-towels`
- `https://www.selfridges.com/GB/en/product/creed-aventus-eau-de-parfum_365-83022651-AVENTUS/`
- `https://www.rockler.com/rockler-table-saw-crosscut-sled`
- `https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html`
- `https://www.sony.co.in/interchangeable-lens-cameras/products/ilce-9m3`
- `https://www.underarmour.com/en-us/p/ua_charged_assert_10_mens_running_shoes/3026175.html`
- `https://www.jcrew.com/m/ME988?display=standard&fit=Classic&colorCode=BR8825&colorProductCode=CI939`

### Code evidence

`public_asset_delivery_url()` preserves the parsed query and does not reject malformed repeated query delimiters (`backend/app/core/shared/url_utils.py:165-193`).

Materialization deduplicates by selected delivery URL, while safety filtering still performs product-identity decisions late (`output_safety.py:44-119`).

### Required correction

- Reject malformed delivery URLs as evidence defects; do not guess-repair them.
- Deduplicate using canonical asset identity before selecting primary/additional roles.
- Preserve raw URL separately from canonical delivery URL.
- Require source-root ownership before ranking.
- Test query-transform variants, extensionless CDN URLs and duplicate primary/additional assets.

---

## AUD-10 — Brand and title roles are insufficiently typed

**Severity:** Medium  
**Confidence:** Confirmed in code; URL-specific correctness requires replay

### Observed examples

- Target duvet brand is `Target.` although the title identifies Levtex Home.
- Amazon brand is `Sparkling`, apparently a title token.
- Amsterdam Vintage Watches publishes the retailer/site name instead of Rolex.
- `Thenorthface`, `Calvinklein`, `jcrew` and `Onepeloton` are poorly normalized.
- Sony has no brand and a code-only title.
- Birkenstock publishes a raw slug-like title.

### Code evidence

Brand inference can derive candidates from hostname agreement or the first title token (`backend/app/core/shared/field_coerce_text.py:137-218`).

Manufacturer, designer, vendor and generic brand keys are collapsed into `product.brand`, while seller/site/retailer roles are not represented distinctly in the public product model.

Title admission exempts URL-corroborated model codes from the code-only rejection path (`backend/app/extraction/pipeline.py:770-846`).

### Required correction

Represent separate evidence roles:

- manufacturer/brand;
- designer;
- seller;
- retailer/site;
- marketplace listing owner.

Only manufacturer/brand evidence should resolve the canonical public brand. Model-only titles should be allowed as fallback identity but produce `partial/review`, not clean title resolution, when a richer product name is expected.

---

## AUD-11 — The mandatory artifact replay gate can silently skip

**Severity:** High  
**Confidence:** Confirmed in tests

### Evidence

`test_latest_commerce_artifacts_are_integrity_clean()` skips when local artifact files are absent:

- `backend/tests/unit/test_latest_commerce_artifact_integrity.py:30-38`
- `backend/tests/unit/test_latest_commerce_artifact_integrity.py:158-170`

Synthetic tests remain valuable, but they cannot guarantee that a slightly different live payload shape is covered.

### Required correction

The release-blocking replay corpus must be reproducible in CI:

- check in compact sanitized artifacts, or download content-addressed immutable bundles;
- fail when required artifacts are unavailable;
- include the exact capture bundles behind this 90-URL dataset;
- calculate pass/fail from replayed records, findings and field states;
- never accept a skipped live-integrity gate as release-clean.

---

## AUD-12 — Architecture documentation and implementation have drifted

**Severity:** Medium  
**Confidence:** Confirmed

The active plan states that output-stage asset conflict filtering was removed, but the active `materialize_product_assets()` still calls product-asset conflict logic. The plan header also says implementation has not started while later slices are marked completed.

This drift makes it difficult to know which architecture is authoritative and reinforces the provenance problem.

### Required correction

After replaying the current artifacts:

- reconcile the plan against the active branch;
- remove completed/stale assertions;
- record the exact commit validated by each replay result;
- make architecture invariants executable tests where possible.

---

# 5. Missing-field URLs requiring artifact classification

A missing field is not automatically an extractor bug. These URLs need their stored HTML/network/diagnostic bundles replayed and classified as:

- captured and resolved;
- captured but rejected;
- conflicting;
- source unavailable;
- interaction required but not captured;
- absent from source;
- not requested.

## Missing price and currency (16)

- `https://stockx.com/nike-dunk-low-retro-white-black-2021`
- `https://www.dtlr.com/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103`
- `https://www.target.com/p/tobago-stripe-blue-twin-duvet-cover-set-levtex-home/-/A-1002150742`
- `https://www.nordstrom.com/s/air-force-1-07-basketball-sneaker-men/7507996`
- `https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html`
- `https://www.farfetch.com/in/shopping/men/philipp-plein-leather-disco-biker-jacket-item-18497263.aspx`
- `https://www.gucci.com/int/en/pr/men/accessories-for-men/scarves-for-men/scarves-for-men/gg-wool-silk-jacquard-stole-p-8705434GAK31360`
- `https://www.mrporter.com/en-us/mens/product/cartier-eyewear/accessories/aviator/pasha-aviator-style-silver-tone-sunglasses/46376663163032937`
- `https://www.net-a-porter.com/en-us/shop/product/eleuteri/jewelry-and-watches/vintage-bracelets/plus-bulgari-vintage-1980s-doppio-cuore-18-karat-gold-coral-and-diamond-bracelet/46376663163120086`
- `https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642`
- `https://www.therevolverclub.com/products/technics-sl-1200mk7`
- `https://www.amazon.com/Sparkling-Prebiotic-Beverage-Vinegar-Seltzer/dp/B0F5Y3X8PP/?th=1`
- `https://amsterdamvintagewatches.com/shop/rolex-day-date-18038-champagne-5/`
- `https://www.ralphlauren.global/in/en/the-iconic-cotton-chino-ball-cap-650310.html?cgid=women-scarves-hats-gloves&dwvar650310_colorname=Heritage Royal`
- `https://www.sephora.com/product/eadem-le-chouchou-exfoliating-softening-peptide-lip-balm-P511921`
- `https://www.chewy.com/wellness-core-rawrev-grain-free-wild/dp/141791`

## Variant rows missing price/currency (5 URLs)

- `https://www.dtlr.com/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103`
- `https://www.farfetch.com/in/shopping/men/philipp-plein-leather-disco-biker-jacket-item-18497263.aspx`
- `https://www.gucci.com/int/en/pr/men/accessories-for-men/scarves-for-men/scarves-for-men/gg-wool-silk-jacquard-stole-p-8705434GAK31360`
- `https://www.therevolverclub.com/products/technics-sl-1200mk7`
- `https://www.sephora.com/product/eadem-le-chouchou-exfoliating-softening-peptide-lip-balm-P511921`

## Variant rows missing availability (6 URLs)

- `https://www.nike.com/t/air-force-1-07-mens-shoes-jBrhbr/CW2288-111`
- `https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html`
- `https://www.gucci.com/int/en/pr/men/accessories-for-men/scarves-for-men/scarves-for-men/gg-wool-silk-jacquard-stole-p-8705434GAK31360`
- `https://www.sony.co.in/interchangeable-lens-cameras/products/ilce-9m3`
- `https://www2.hm.com/en_us/productpage.1344928003.html`
- `https://www.sephora.com/product/eadem-le-chouchou-exfoliating-softening-peptide-lip-balm-P511921`

The complete URL-wise matrix is in `crawlerai_extraction_url_issue_matrix_2026-06-29.csv`.

---

# 6. Recommended implementation order

## Phase 0 — Establish provenance and replay the exact run

1. Locate the run/URL-result IDs and capture bundles that generated the attached JSON.
2. Record active Git commit and working-tree state.
3. Replay every capture through the current `app.extraction.extract`.
4. Diff old record, current record, findings, field states, decisions and variant drops.
5. Mark each issue as current regression, already fixed/stale output, source-limited, or unproven.

**Stop rule:** Do not change production extraction code until this diff exists.

## Phase 1 — Fail-closed source-root and DOM-root selection

1. Replace “no selected roots means all paths” behavior.
2. Introduce candidate-root scoring and unresolved/ambiguous outcomes.
3. Scope DOM selectors to a selected product container.
4. Stop assigning page-product parent IDs inside generic collectors.
5. Add negative tests with recommendations, bundles, search hits and cache objects.

## Phase 2 — Make integrity part of the data contract

1. Add version/run/verdict/integrity metadata to exports.
2. Add clean-only and include-partial export modes.
3. Align acquisition requirements with the expected product profile.
4. Include variants/availability in retry policy when requested by the profile.

## Phase 3 — Make resolution the only semantic owner

1. Move parent offer/range/availability derivation into resolution.
2. Remove semantic product filtering from output safety.
3. Assert public values exactly match accepted or derived decisions.
4. Add graph/public divergence tests.

## Phase 4 — Harden variants, assets, brands and titles

1. Introduce typed variant/option/offer contracts.
2. Enforce canonical asset identity and URL validity.
3. Separate manufacturer, seller, retailer and site roles.
4. Add model-only/slug-title quality states.

## Phase 5 — Make the replay gate non-skippable

1. Materialize compact immutable artifacts in CI.
2. Add the attached run as the acceptance corpus.
3. Fail on unavailable artifacts, foreign lineage, malformed assets, namespace collisions and unqualified partial publication.

---

# 7. Acceptance criteria

The pipeline is ready for another live crawl only when all of the following hold:

- No collector maps the whole structured payload when a primary root is unresolved.
- Every public offer, variant and asset has accepted parent-relation evidence.
- Recommendation/search/cache objects cannot enter the selected product graph.
- Public records are exported with version, verdict and integrity state.
- Clean exports exclude partial and review records by default.
- Variant/availability expectations are explicit and drive acquisition retries.
- Public values exactly match accepted or derived resolution decisions.
- Duplicate/malformed image delivery URLs are rejected or canonicalized deterministically.
- Brand role cannot resolve from retailer/site evidence when manufacturer evidence exists.
- The exact 90-URL artifact replay is non-skippable and clean, with honest source-limited classifications.
- No hostname-specific or product-specific rescue branches are introduced.

---

# 8. Audit limitations

This audit had the complete flat output dataset and the active codebase, but not the capture artifacts that produced each row. Consequently:

- cross-product values visible directly in the output are confirmed defects;
- code-level fail-open and publication behaviors are confirmed defects;
- individual missing prices, currencies, availability values and variants remain unproven until their capture evidence is replayed;
- the attached dataset may have been produced by an older commit or a different working-tree state.

