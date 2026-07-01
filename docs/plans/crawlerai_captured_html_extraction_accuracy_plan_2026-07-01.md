# CrawlerAI Captured-HTML Extraction Accuracy Plan

**Date:** 1 July 2026  
**Status:** COMPLETE
**Repository audited:** `C:\Projects\CrawlerAI`  
**Artifact inputs:** `1.zip` and `2.zip`  
**Mode:** Code fixes from captured HTML findings. No crawl replay, no smoke scripts, and no committed fixture/corpus gates unless explicitly requested.  
**Primary target:** Ecommerce detail extraction

## 1. Objective

Make the existing `Harvest → Resolve → Publish` pipeline reliably publish valid product data that is already present in the captured `page.html`, while continuing to reject invalid, unrelated, promotional, blocked, or ambiguous evidence.

The target contract is:

> For every requested or standard ecommerce-detail field, valid same-product data present in the captured HTML or embedded JSON must either be published with lineage or receive an accurate, stage-specific reason explaining why it was not published.

This plan does **not** aim to force every field to be populated. It aims to eliminate:

- collector blindness to supported HTML and structured-data shapes;
- valid child offers or assets becoming unowned;
- price and currency from the same source object being separated;
- valid product evidence being excluded from the selected root;
- correct variant data failing to reach the parent product where the public contract requires a parent value;
- false `MISSING_CONTRACT_FIELD` and quality findings after a clean value was published;
- retailer, marketplace, or page identity being published as product manufacturer without evidence.

## 2. Audit basis and method

The two archives contain:

- **98 result bundles**
- **96 unique URLs**
- **95 non-blocked bundles**
- **93 unique usable captures**
- **3 blocked captures**
- Current verdicts across the 96 unique URLs:
  - `success`: **40**
  - `partial`: **53**
  - `blocked`: **3**

Each result bundle was evaluated using:

1. `page.html` — source-of-truth captured HTML and embedded JSON;
2. `record.json` — published public output;
3. `diagnose.json` — field states, selected candidates, findings, joins, and publication decisions;
4. current repository code — the owning collector, entity linker, resolver, validator, and publisher.

No issue is included as a confirmed parser defect solely because a public field is empty. A plan item is treated as confirmed only when at least one of these is true:

- the valid value is directly visible in `page.html` and absent from `record.json`;
- `diagnose.json` proves the value was captured but rejected, suppressed, left unowned, or excluded from the selected target;
- the current code has a concrete unsupported source shape matching the artifact;
- the output and its own field state contradict each other.

### Current corpus signals

Across the 96 unique URLs:

| Signal | Count |
|---|---:|
| Missing brand | 19 |
| Missing description | 15 |
| Missing primary image | 10 |
| Missing parent price | 20 |
| Missing parent currency | 20 |
| Missing parent availability | 22 |
| `variant_count = 0` | 49 |
| `CHILD_JOIN_FAILED` findings | 37 |
| `EXPECTED_VARIANT_AXIS_MISSING` findings | 31 |
| `PRICE_WITHOUT_CURRENCY` findings | 39 |
| `CURRENCY_WITHOUT_PRICE` findings | 27 |
| `MISSING_CONTRACT_FIELD` findings | 62 |

These are not all extraction defects. The implementation must use the confirmed issue ledger below rather than treating these raw counts as fix targets.

## 3. Architectural decision

Retain the current architecture:

```text
CaptureBundle
  → Harvest immutable Evidence
  → select target and link entities
  → Resolve selected and derived facts
  → Publish authorized projection
  → Validate the published contract
```

Do not add:

- a post-publication repair pass;
- a site-specific hostname table;
- an enrichment-side cleanup layer;
- an LLM-generated missing-field path;
- browser-side scripts that directly assign canonical fields;
- synthesized variant cross-products.

### Current-code conclusions that supersede older audits

The current `app/core/records/js_state_scope.py` is already fail-closed: unresolved or ambiguous structured roots admit nothing. The remaining defect is **valid-data loss from incomplete root promotion, containment, and child relation propagation**, not fail-open traversal.

The current resolver already has:

- parent-to-variant offer inheritance;
- variant-to-parent uniform price and range derivation;
- variant availability aggregation;
- price-unit repair;
- asset resolution and publication projection.

The plan therefore extends these owners rather than adding parallel logic.

## 4. Confirmed issue ledger

### 4.1 Nested JSON-LD offer structures are only partially supported

| Result | URL | HTML evidence | Current output |
|---:|---|---|---|
| 2733 | MR PORTER Cartier sunglasses | `offers.priceSpecification.price = 1795.00`, `priceCurrency = USD`, `availability = InStock` | price, currency, availability missing |
| 2734 | NET-A-PORTER Bulgari bracelet | `offers.priceSpecification.price = 22500.00`, `priceCurrency = USD`, `availability = InStock` | price, currency, availability missing |
| 2741 | Decathlon padel balls | product offer contains `price = 10.99`, `priceCurrency = GBP`, `availability = OnlineOnly` | offer captured but `join_failed` |

**Code cause**

- `app/extraction/collectors/jsonld.py::_offers()` reads only direct keys in `ECOMMERCE_JSONLD_OFFER_FACT_TYPES` and recursively follows `offers`.
- It does not read `priceSpecification`.
- `DETAIL_JSONLD_PRICE_SPECIFICATION_FIELDS` exists in `app/core/config/extraction_price_rules.py` but is not used by `JsonLdCollector`.
- JSON-LD graph/child ownership is not always retained strongly enough for `entities._link_offers()`.

### 4.2 Valid ProductGroup and variant offers are collected incompletely or fail ownership joins

| Result | URL | HTML evidence | Current output |
|---:|---|---|---|
| 2709 | Nike Air Force 1 | exact product state plus variant commercial data | brand rejected as outside target; variant availability groups fail joins |
| 2726 | Farfetch Philipp Plein jacket | product/variant offer prices and currency in structured data/meta | parent and all four variants miss price/currency |
| 2760 | H&M printed T-shirt | `ProductGroup.hasVariant`; each child has SKU, size, `12.99 USD`, and `InStock` | seven variants publish without price/availability; most miss currency and size |
| 2764 | Gap pants | JSON-LD offers contain `47.00 USD`, `InStock`; page state identifies Gap | brand and full parent offer missing |
| 2745 | Sony ILCE-9M3 | selected ProductGroup contains `brand.name = SONY` | brand is captured but rejected as outside selected target |
| 2782 | J.Crew Soleil pant | exact product JSON-LD contains `brand = J.Crew` and product image | brand and primary image excluded from selected target |

**Code cause**

- `select_product_roots()` selects roots, but child objects and graph nodes do not always inherit the selected product relationship.
- `JsonLdCollector` creates parent subjects from local paths and URLs but does not model every explicit JSON-LD relation.
- `entities._variant_for()` and `_owner_product_id()` primarily use `parent_subject_id` and SKU. Explicit `@id`, `isVariantOf`, `itemOffered`, `productGroupID`, and graph references are not a complete joining vocabulary.
- `network_row()` assigns nested offer/asset evidence to a final-URL-derived product subject instead of preserving the source object's explicit relationship when available.

### 4.3 Embedded-state field mapping is too flat

| Result | URL | HTML evidence | Current output |
|---:|---|---|---|
| 2691 | StockX Nike Dunk | exact product object contains `"brand":"Nike"` | brand missing |
| 2693 | DTLR Air Jordan 5 | Shopify state has integer `21500`; OG has `215.00 USD`; product-variant payload has `{amount: 215, currencyCode: USD}` | price suppressed and currency rejected; 14 variants miss price/currency |
| 2697 | Target Levtex duvet | selected product has vendor `Levtex Home` and explicit size variation hierarchy | brand and variants missing |
| 2720 | Phase Eight dress | product state has `"brand":"Phase Eight"` | brand missing |
| 2731 | Peloton Tread | page state contains Tread price `329500`, package `basePrice`, image, slug, and product identity | brand, price, currency, availability missing |
| 2749 | Revolver Club Technics turntable | Shopify integer `18600000`; OG/analytics expose `186,000.00 INR` | price/currency missing |
| 2771 | Ralph Lauren cap | product state contains Polo Ralph Lauren identity and price data | brand and offer missing |

**Code cause**

- `ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES` maps direct object keys.
- `network_row()` maps only keys directly present on the current object.
- Common scalar carriers such as `brand.name`, `{amount, currencyCode}`, `sellingPrice.amount`, `basePrice`, or vendor arrays are not represented as typed source paths.
- Minor-unit repair is unable to act when price and currency are collected into different offer groups or when the corroborating display value is not attached to the same product/offer entity.

### 4.4 Brand roles and fallback inference are not sufficiently typed

Confirmed examples:

- Sony: structured manufacturer brand exists but is outside the selected target.
- J.Crew: structured brand exists but is outside the selected target.
- Target: product vendor `Levtex Home` is present.
- StockX: exact product object says Nike.
- Phase Eight: exact product state says Phase Eight.
- Calvin Klein and Tommy Hilfiger: product title/site metadata consistently identify the brand, but output is empty.
- Amazon must not derive `Sparkling` merely from the first title/URL token.
- Amsterdam Vintage Watches must not replace Rolex with retailer identity unless the source actually identifies it as manufacturer.

**Code cause**

- manufacturer, designer, vendor, retailer, seller, and page/site identity are eventually flattened toward `product.brand`;
- title/URL inference can create a brand candidate without a typed role;
- valid structured brand evidence can be lost earlier through root/ownership selection.

### 4.5 Full product descriptions can lose to rejected SEO excerpts, and findings are candidate-scoped instead of output-scoped

| Result | URL | HTML evidence | Current output |
|---:|---|---|---|
| 2687 | Sneakersnstuff Dime crewneck | full product description exists in product content/structured data; 320-character SEO excerpt is incomplete | description missing |
| 2784 | ASOS barrel pants | clean product description is published | still emits `DESCRIPTION_PROMOTIONAL_COPY` because another rejected candidate is promotional |

**Code cause**

- product-scoped full DOM descriptions are not always admitted or ranked above metadata excerpts;
- `validation._validate_descriptions()` creates page findings whenever *any* candidate has a quality flag, even when the selected published value is clean;
- the resolver correctly rejects promotional candidates, but validation then reports those rejected candidates as if they degraded the output.

### 4.6 Primary image policy and top-level/variant image semantics are inconsistent

| Result | URL | Evidence | Current output |
|---:|---|---|---|
| 2700 | Converse Chuck Taylor | exact product OG/microdata image | image captured but withheld |
| 2775 | MAC Eye Shadow | exact product JSON-LD and OG image | image rejected as `invalid_primary_asset` |
| 2782 | J.Crew Soleil pant | exact product JSON-LD/OG image | image outside selected target |
| 2753, 2755 | Blue Nile rings | same-product single variant publishes a valid image; field state says `captured_published` | parent `image_url` missing and validator reports missing contract field |

**Code cause**

- asset ownership failures can happen before resolution;
- `publication._asset_entries()` emits resolved asset entities but has no explicit same-product fallback from an eligible selected/single variant to parent primary image;
- contract validation checks the top-level record while field-state generation can classify a variant asset as published, producing contradictory diagnostics.

### 4.7 Parent and variant commercial semantics are ambiguous

| Result | URL | Current condition |
|---:|---|---|
| 2695 | Kith sneakers | direct parent says out of stock while several complete variants are in stock |
| 2757 | Arc'teryx shoe | 65 variants publish availability; field state says captured/published; parent availability is empty |
| 2760 | H&M shirt | child offers exist but parent offer cannot be derived because child facts were not joined/published |
| 2784 | ASOS pants | clean parent/variant output still carries a stale parent-variant availability conflict finding |

**Code cause**

- `_aggregate_variant_availability()` refuses to derive a parent value whenever a direct parent availability fact exists;
- `_validate_availability_consistency()` reports conflict but does not distinguish selected-configuration availability from product-family availability;
- top-level contract validation does not understand when eligible child values should satisfy or derive the parent contract.

### 4.8 Diagnostic truth is inconsistent with the publication projection

Confirmed contradictions:

- Blue Nile results 2753 and 2755: `image_url` field state is `captured_published`, but the parent record has no image and receives `MISSING_CONTRACT_FIELD`.
- Arc'teryx result 2757: availability is `captured_published` on variants, but parent availability is absent and receives a missing-field finding.
- H&M result 2760: currency is classified `captured_published`, but no parent or variant currency appears in the public output.
- ASOS result 2784: clean published description and availability coexist with candidate-level quality/conflict findings.

**Code cause**

- `validate_selected_contract_fields()` evaluates the serialized top-level record and uses any evidence anywhere to decide whether price/currency/availability are “exposed”;
- `projection_field_states()` can consider variant projection entries while `MISSING_CONTRACT_FIELD` uses only top-level fields;
- findings are not consistently scoped to selected product, primary offer, eligible variants, and published projection.

## 5. Explicit non-defects and exclusions

The following must not be “fixed” by inventing or rewriting values:

1. **Blocked captures**
   - 2737 Dick’s Sporting Goods
   - 2769 Lululemon
   - 2777 Columbia  
   These remain `source_unavailable`/blocked and are acquisition concerns.

2. **Invalid source prices**
   - 2698 Nordstrom exposes zero-price candidates.
   - 2730 Gucci exposes a negative price candidate.  
   Rejecting these values is correct unless another valid same-product offer exists in the capture.

3. **Selfridges equal volume prices**
   - Result 2725 contains equal prices in the captured source. The extractor must not manufacture progressive pricing.

4. **Glossier `flavor`**
   - `flavor` is already a supported canonical public variant axis in `variant_policy.py`. It must not be forced into `color`.

5. **Legitimate parent/variant price ranges**
   - Different valid variant prices are not a discrepancy. Publish the selected/default price and explicit `price_min`/`price_max` according to one documented policy.

6. **Promotional-only descriptions**
   - SEO, shipping, search-directory, and retailer copy should remain rejected when no product-specific description exists.

7. **Thin or non-product source**
   - Result 2728 Mytheresa does not contain enough confirmed product data in the capture to justify inferred values.

8. **No variants without a matrix**
   - Do not synthesize combinations from independent color/size controls. A variant array is required only when the capture contains explicit product-child relationships or a product-scoped combination matrix.

## 6. Implementation plan

### Current implementation status

**Completed bug work**

- Active plan moved to this captured-HTML accuracy plan and previous active plan queued.
- JSON-LD `priceSpecification` now emits atomic price/currency facts in one offer group.
- Schema.org `OnlineOnly` and related availability tokens are config-owned and canonicalized.
- JSON-LD `@id` / `productGroupID` aliases now help ProductGroup and standalone variant joins.
- Parent-only offers no longer emit false `CHILD_JOIN_FAILED`.
- `AggregateOffer.highPrice` is treated as `price_max`, not fake `original_price`.
- Primary offer ranking prefers complete price/currency/availability when candidates tie.
- Domain-surface contract selection updates only templates whose retained candidates contain the selected source.
- Knowledge Graph UI merged source options across grouped templates to avoid hiding valid saved sources.
- Embedded-state parent price objects now keep nested `amount` and `currencyCode` together with source-path locators.
- Slice 7 brand role metadata now distinguishes manufacturer/designer/private-label/vendor from retailer/seller/marketplace/site identity, ranks public brand candidates by role, and rejects non-manufacturer identity evidence before publication.
- Slice 8 now rejects malformed delivery URLs before role assignment, selects the next eligible asset, accepts structurally proven extensionless product images without admitting known utility assets, deduplicates by canonical identity, and derives strict selected/single-variant parent image fallback with lineage.
- Slice 9 now shares canonical variant-axis mapping across JSON-LD and embedded state, preserves `flavor`, collects JSON-LD child images, retains explicit partially complete children with stable identity and direct commercial evidence, and keeps optionless package/noise rows rejected.
- Mypy issues from the P0 changes are fixed:
  - `validation.py` promotional description evidence tuple is typed.
  - `knowledge.py` contract query result is materialized as a mutable list before sorting.

**Verification already run**

- Backend focused: `tests/component/test_knowledge_api.py`, `tests/unit/test_extraction_pipeline.py`, `tests/unit/test_variant_offer_availability_semantics.py`, `tests/unit/test_conflict_aware_product_linking.py` passed.
- Slice 3 focused: `tests/unit/test_extraction_pipeline.py -k "js_state_parent_price_object or nested_variant_options_money or shopify_vendor"` passed.
- Slice 7 focused: `tests/unit/test_extraction_pipeline.py -k "brand or vendor or retailer or title_token"`, `tests/unit/test_brand_inference.py`, ruff on touched Python files, and mypy on touched backend modules passed.
- Slices 8-9 focused: all 282 tests in `tests/unit/test_extraction_pipeline.py` passed; ruff passed on touched Python; mypy passed on the nine touched backend source files.
- Backend ruff passed for touched Python.
- `mypy .` passed for 342 backend source files.
- Frontend lint passed.

**Removed from this plan**

- Static/corpus acceptance manifest work.
- Committed fixture-based regression cases.
- Smoke scripts and replay gates.
- Slice 10 complete-PDP profile expansion, removed by explicit user direction because it broadens default runtime/retry behavior without being required for the captured-HTML accuracy fixes.

Future verification must use focused owner tests only unless the user explicitly asks for full-suite, fixture, corpus, replay, or smoke work.

**Next handoff**

No implementation slices remain. Corpus replay, smoke scripts, and fixture gates remain
out of scope unless explicitly requested.

### Slice 1 — Make diagnostics projection- and entity-aware

**Priority:** P0  
**Owners:**

- `app/extraction/validation.py`
- `app/extraction/result_building.py`
- `app/extraction/publication.py`
- `app/observability/run_report.py`

#### Work

1. Replace record-only contract validation with validation against:
   - the publication projection;
   - selected product;
   - primary offer;
   - eligible variant entries;
   - resolved asset roles.

2. Change `_sellable_offer_exposed()` and `_availability_exposed()` so unrelated, rejected, outside-target, or unowned evidence cannot make a public field mandatory.

3. Define explicit contract satisfaction by scope:
   - parent field published;
   - parent field validly derived from complete eligible variants;
   - variant-only field published but parent derivation intentionally unavailable;
   - field captured but publication policy suppressed it;
   - field genuinely absent.

4. Generate `MISSING_CONTRACT_FIELD` only when the required projection path is actually missing.

5. Scope description and offer findings to:
   - selected facts;
   - facts that blocked publication;
   - eligible child offers;
   - a bounded grouped diagnostic for irrelevant rejected candidates.

6. Keep `RECORD_COMPLETENESS` informational. It must not appear as a root cause.

#### Regression targets

- Blue Nile 2753/2755;
- Arc'teryx 2757;
- H&M 2760;
- ASOS 2784.

#### Acceptance

- zero cases where a field is `captured_published` but the required public path is absent without an explicit scope reason;
- zero `MISSING_CONTRACT_FIELD` findings caused only by outside-target or rejected candidates;
- clean published descriptions do not receive candidate-only promotional findings;
- diagnostic output remains bounded and preserves evidence IDs.

---

### Slice 2 — Complete JSON-LD Product, ProductGroup, and Offer harvesting

**Priority:** P0  
**Owners:**

- `app/extraction/collectors/jsonld.py`
- `app/core/config/field_mappings.py`
- `app/core/config/extraction_price_rules.py`
- `app/core/config/extraction_rules/`

#### Work

1. Add one recursive JSON-LD offer parser supporting:
   - `Offer`;
   - `AggregateOffer`;
   - nested `offers`;
   - `priceSpecification`;
   - `lowPrice` / `highPrice`;
   - `priceCurrency`;
   - `availability`;
   - `itemOffered`;
   - `seller`.

2. Use the existing configured price-specification vocabulary rather than adding literals inside the collector.

3. Parse nested values atomically:
   - price and currency from one `UnitPriceSpecification` receive one offer group;
   - availability attached to the containing Offer remains in that group;
   - original/high/list price remains a distinct fact, not a replacement current price.

4. Preserve explicit JSON-LD identities and relations:
   - `@id`;
   - `url`;
   - `sku`/GTIN;
   - `productGroupID`;
   - `isVariantOf`;
   - `itemOffered`;
   - `hasVariant`.

5. Define a complete configured mapping for Schema.org availability values. `OnlineOnly` must be handled through an explicit canonical policy rather than dropped or guessed.

6. Keep traversal fail-closed: only selected product roots and their proven related children are admitted.

#### Regression targets

- MR PORTER 2733 → `1795.00 USD`, availability from the same Offer;
- NET-A-PORTER 2734 → `22500.00 USD`, availability from the same Offer;
- Decathlon 2741 → `10.99 GBP`, canonical online availability;
- H&M 2760 → child SKU/size/price/currency/availability;
- Gap 2764 → exact selected product offer;
- Farfetch 2726 → variant offer completeness.

#### Acceptance

- no selected product Offer with a supported nested price shape is reported `not_present_in_captured_sources`;
- every price/currency pair shares one offer group or an explicit compatible relation;
- graph nodes unrelated to the selected product remain outside target;
- no related-product leakage.

---

### Slice 3 — Replace flat embedded-state mapping with typed structural value paths

**Priority:** P0  
**Owners:**

- `app/extraction/collectors/js_state.py`
- `app/extraction/collectors/metadata.py`
- `app/core/config/field_mappings.py`
- `app/core/config/variant_policy.py`
- `app/core/records/js_state_scope.py`

#### Work

1. Keep `network_row()` as the common mapper, but give it typed value-path readers for structural shapes such as:
   - `brand.name`;
   - product vendor arrays;
   - `{amount, currencyCode}`;
   - `currentPrice.amount`;
   - `sellingPrice.amount`;
   - `basePrice`;
   - nested inventory state;
   - variant option arrays.

2. Store the selected value path in `SourceLocator`; do not flatten the whole object blindly.

3. Require product context and exact target identity before admitting nested values:
   - canonical URL/resource identity;
   - product ID/code;
   - SKU/GTIN;
   - dominant title agreement;
   - explicit parent relation.

4. Preserve atomic commercial groups:
   - nested price and currency from the same object/path must be emitted together;
   - availability/stock from the same object joins that group;
   - source-object identity becomes part of the group key.

5. Make minor-unit conversion evidence-driven:
   - explicit configured minor-unit field;
   - explicit divisor/scale in source;
   - or corroborating same-product display/OG value and currency.

   Never divide by 100 from host identity or integer shape alone.

6. Add a structural adapter for Shopify product/variant payloads rather than interpreting all integer `price` fields identically.

#### Regression targets

- DTLR 2693 → parent and variant commercial facts from Shopify/OG evidence;
- Revolver Club 2749 → `186000.00 INR`, not `18600000`;
- Peloton 2731 → Tread/package price from product-scoped package data;
- StockX 2691 → Nike brand from exact product object;
- Target 2697 → Levtex Home vendor and explicit size hierarchy;
- Phase Eight 2720 → Phase Eight brand;
- Ralph Lauren 2771 → product brand and offer from selected product state.

#### Acceptance

- no valid same-object price/currency pair is split across independent offer entities;
- no uncorroborated minor-unit conversion;
- direct low-level maps remain configuration-owned;
- unrelated analytics/recommendation payloads remain rejected.

---

### Slice 4 — Make child ownership explicit before entity linking

**Priority:** P0  
**Owners:**

- `app/extraction/contracts.py`
- `app/extraction/collectors/jsonld.py`
- `app/extraction/collectors/js_state.py`
- `app/extraction/entities.py`
- `app/extraction/validation.py`

#### Work

1. Represent source relations explicitly on evidence:
   - source object/subject ID;
   - parent source ID;
   - relation type;
   - relation evidence IDs;
   - product/variant/offer scope.

2. Use this join precedence:

```text
explicit source relation
  > exact source subject / @id reference
  > exact SKU/GTIN
  > exact product ID or URL identity
  > same selected product-root relation
  > unresolved
```

3. Do not assign every nested offer or asset to the final-URL product during collection.

4. Extend `_variant_for()` and `_owner_product_id()` to use explicit source relations before SKU fallback.

5. Keep unresolved children as evidence and emit one grouped `CHILD_JOIN_FAILED` diagnostic with the missing key. Do not silently discard them.

6. Preserve identity namespaces:
   - product style code;
   - sellable variant SKU;
   - GTIN/barcode;
   - platform variant ID.

   Do not publish one namespace as another.

#### Regression targets

- Nike 2709;
- Decathlon 2741;
- H&M 2760;
- Farfetch 2726;
- Gap 2764;
- Sony 2745;
- J.Crew 2782.

#### Acceptance

- zero `CHILD_JOIN_FAILED` for selected-product children that carry an explicit supported relationship;
- all accepted children link to exactly one product;
- ambiguous children remain unresolved rather than being attached by page URL;
- current cross-product contamination tests continue to pass.

---

### Slice 5 — Resolve offers atomically and define parent/variant semantics

**Priority:** P1  
**Owners:**

- `app/extraction/resolution.py`
- `app/core/config/extraction_price_rules.py`
- `app/core/config/variant_policy.py`
- `app/extraction/publication.py`

#### Work

1. Resolve an offer as a coherent commercial entity, not independent field winners.

2. Price and currency compatibility must require:
   - the same offer group;
   - an explicit inherited relation;
   - or a traceable reconciliation rule.

3. Preserve direct child evidence over inherited parent values.

4. Parent price policy:
   - one uniform eligible leaf price → derive parent price;
   - multiple eligible leaf prices → derive `price_min` and `price_max`;
   - keep an explicit selected/default parent price when its scope is known;
   - never label legitimate variation as a scrape error.

5. Parent availability policy:
   - when the complete eligible child matrix is known, derive product-family availability from children;
   - keep direct parent availability as selected-configuration evidence when that is its actual scope;
   - publish one documented public meaning, preferably product-family availability, and record the rule;
   - incomplete child matrices must not override a direct parent value.

6. Parent-to-child inheritance:
   - inherit only fields proven global to the product;
   - do not overwrite direct child availability, price, or currency;
   - keep inherited lineage explicit.

7. Treat one default child without a differentiating option as internal configuration/parent evidence unless the source explicitly defines it as a sellable variant.

#### Regression targets

- Kith 2695;
- Arc'teryx 2757;
- H&M 2760;
- ASOS 2784;
- DTLR 2693;
- Farfetch 2726.

#### Acceptance

- complete in-stock variants cannot coexist with public parent `out_of_stock` without an explicit selected-configuration scope;
- parent price ranges are traceable to eligible leaf variants;
- no inherited field erases direct child evidence;
- incomplete matrices do not manufacture aggregate truth.

---

### Slice 6 — Add a product-rooted DOM collector for visible and product-panel data

**Priority:** P1  
**Owners:**

- `app/extraction/collectors/dom.py`
- `app/extraction/pipeline.py`
- `app/core/config/extraction_rules/_detail.py`

#### Work

1. Select a coherent DOM product root using:
   - product H1/title;
   - purchase form;
   - selected SKU/product ID;
   - product gallery;
   - price/buy controls.

2. Collect product facts only from that root or explicitly linked product panels.

3. Admit product-scoped hidden accordion/tab content with:
   - component-role metadata;
   - visibility metadata;
   - lower confidence than visible content;
   - recommendation/navigation/template exclusion.

4. Collect visible current price, original price, currency, and stock text as one DOM offer group.

5. Prefer a complete product description over:
   - 320-character metadata excerpts;
   - truncated connector endings;
   - generic shipping/search copy.

6. Keep all DOM selectors and structural tokens in config.

#### Regression targets

- Sneakersnstuff 2687;
- Gap 2764 visible `47.00`;
- Calvin Klein 2770;
- Tommy Hilfiger 2773;
- product pages where structured data is partial but visible DOM is complete.

#### Acceptance

- full product-panel description outranks truncated OG/meta copy;
- no recommendation card price/image is assigned to the selected product;
- DOM price and currency remain atomic;
- hidden recommendation content remains rejected.

---

### Slice 7 — Introduce typed brand roles and conservative fallback

**Priority:** P1  
**Owners:**

- `app/extraction/contracts.py`
- `app/extraction/pipeline.py`
- `app/extraction/resolution.py`
- `app/core/shared/field_coerce_text.py`
- `app/core/config/field_mappings.py`

#### Work

1. Add evidence role metadata:
   - `manufacturer`;
   - `designer`;
   - `private_label`;
   - `vendor`;
   - `retailer`;
   - `seller`;
   - `marketplace`;
   - `site_identity`;
   - `unknown`.

2. Resolve public `brand` only from manufacturer/designer/private-label evidence or a strongly corroborated fallback.

3. Preserve seller and retailer evidence without collapsing it into product brand.

4. Parse nested Brand/Organization values and product vendor arrays.

5. Use title/URL/site inference only when:
   - the source is product-scoped;
   - the candidate is corroborated by at least one other independent product signal;
   - it does not conflict with structured manufacturer evidence.

6. Keep code/model-only titles valid as identity when source data only supports the code, but do not use them to suppress a valid structured brand.

#### Regression targets

- Sony 2745;
- J.Crew 2782;
- StockX 2691;
- Target 2697;
- Phase Eight 2720;
- Ralph Lauren 2771;
- Calvin Klein 2770;
- Tommy Hilfiger 2773;
- Amazon 2752 negative control;
- Amsterdam Vintage Watches/Rolex role control.

#### Acceptance

- retailer/site identity never beats valid manufacturer evidence;
- first title token alone cannot create brand truth;
- exact structured brand on the selected product publishes;
- brand normalization preserves punctuation and spacing such as `J.Crew`.

---

### Slice 8 — Repair asset ownership, fallback, and parent projection — DONE

**Priority:** P1  
**Owners:**

- `app/extraction/collectors/jsonld.py`
- `app/extraction/collectors/dom.py`
- `app/extraction/entities.py`
- `app/extraction/resolution.py`
- `app/extraction/publication.py`
- `app/core/shared/url_utils.py`

#### Work

1. Require same-product ownership before ranking an asset.

2. Preserve raw URL, canonical asset identity, and delivery URL separately.

3. Accept extensionless CDN URLs when source type or asset relationship proves they are images.

4. If the highest-ranked asset fails delivery canonicalization, select the next eligible asset in Resolve.

5. Deduplicate before primary/additional role selection.

6. Define a strict parent fallback:
   - selected variant image;
   - or single same-product eligible variant image;
   - only when no product-owned primary image exists.

   Record a derived fact rather than mutating the record.

7. Make field state and contract validation use the same parent asset projection.

#### Regression targets

- Converse 2700;
- MAC 2775;
- J.Crew 2782;
- Blue Nile 2753/2755.

#### Acceptance

- exact product OG/JSON-LD assets are not rejected solely for URL shape;
- no parent image is reported published unless it is present on the parent projection;
- variant-to-parent fallback has explicit lineage;
- no duplicate public asset identity.

---

### Slice 9 — Complete variant matrices without synthesizing them — DONE

**Priority:** P1  
**Owners:**

- `app/extraction/collectors/jsonld.py`
- `app/extraction/collectors/js_state.py`
- `app/extraction/entities.py`
- `app/extraction/resolution.py`
- `app/core/config/variant_policy.py`

#### Work

1. Preserve explicit source axes and canonicalize aliases.

2. Keep `flavor` as `flavor`; do not rewrite it to `color`.

3. Materialize a child only when the source provides:
   - stable identity; and
   - an explicit parent relation or selected product-root relationship.

4. Recover size/color/options from the same child object or explicit option matrix.

5. Do not create a Cartesian product from separate DOM option lists.

6. Keep partially complete valid children and expose missing child fields through per-variant states rather than dropping the entire variant.

7. Apply offer inheritance only after child identity and ownership are stable.

#### Regression targets

- DTLR 2693;
- Nike 2709;
- Farfetch 2726;
- H&M 2760;
- Target 2697;
- Puma variants only where the captured source contains an explicit size matrix.

#### Acceptance

- all explicit selected-product children in the confirmed manifest publish once;
- no duplicate variant identity;
- no synthesized combinations;
- every public variant field has selected or derived lineage;
- absent size remains absent when no child-level size evidence exists.

---

### Slice 10 — Define a complete-PDP extraction profile — REMOVED

Removed by explicit user direction on 1 July 2026. The profile expansion was not
required for the captured-HTML extraction accuracy fixes and would broaden default
runtime and retry behavior.

**Priority:** P2  
**Owners:**

- `app/core/config/field_mappings.py`
- extraction request/profile configuration
- result assessment and diagnostics

The current acquisition/extraction contract gives strongest default attention to title, price, and image, while the public ecommerce model also exposes brand, description, availability, and variants.

Define profiles:

#### Core identity

- URL
- title
- brand
- primary image

#### Sellable offer

- price
- currency
- availability or an explicit availability reason

#### Variant-complete

- explicit axes
- stable child identity
- child offer
- child availability
- child image where present

For the user's target, the default production ecommerce-detail run should use **Core identity + Sellable offer**, and automatically enable **Variant-complete** when the capture contains an explicit ProductGroup, `hasVariant`, variant array, or same-product matrix.

A field must never be silently omitted. It must end as:

- published;
- captured but rejected with reason;
- captured but unowned/join failed;
- not present in captured sources;
- source unavailable;
- not requested.

## 7. Test strategy

Do not add site-specific production code. Do not add committed corpus fixtures,
fixture replay suites, smoke scripts, or manifest gates unless the user explicitly asks for corpus/replay work.

Use focused inline structural tests in the canonical owner files. Tests should model generic source shapes, not site names.

### Extend existing canonical test owners

- `backend/tests/unit/test_extraction_pipeline.py`
- `backend/tests/unit/test_description_quality.py`
- `backend/tests/unit/test_brand_inference.py`
- resolver/entity/publication tests already owning those contracts

### Required structural cases

| Signal | Required assertion |
|---:|---|
| 2733 | nested `priceSpecification` publishes `1795.00 USD` and availability |
| 2734 | nested `priceSpecification` publishes `22500.00 USD` and availability |
| 2741 | graph product Offer attaches to Decathlon product |
| 2693 | Shopify cents + corroborating display offer resolves `215.00 USD`; child rows inherit/retain offer facts |
| 2749 | Shopify cents resolve `186000.00 INR` |
| 2709 | exact Nike product brand and child availability join without related-product leakage |
| 2726 | Farfetch child offers remain attached to four variants |
| 2760 | H&M children retain SKU, size, price, currency, availability |
| 2764 | Gap exact selected offer and brand publish |
| 2745 | Sony structured brand remains on selected ProductGroup |
| 2782 | J.Crew brand and image remain on selected product |
| 2687 | full product description beats truncated excerpt |
| 2700 | valid product image is selected |
| 2775 | extensionless/structured product image is accepted |
| 2753/2755 | parent image projection and field state agree |
| 2757 | complete child availability derives or explicitly satisfies parent contract |
| 2695 | complete child availability resolves parent/product-family availability |
| 2784 | clean output has no candidate-only promotional/conflict finding |
| 2698 | zero price remains rejected |
| 2730 | negative price remains rejected |
| 2725 | equal captured variant prices remain unchanged |
| blocked controls | no product values invented |

## 8. Acceptance gates

### Field recall

- No valid supported JSON-LD Offer or ProductGroup value is marked `not_present_in_captured_sources`.
- No selected-product structured brand/image is marked `outside_selected_target`.
- No explicit supported child relation ends in `CHILD_JOIN_FAILED`.

### Output quality

- Every published price has compatible currency lineage.
- Every published parent aggregate has child lineage.
- No retailer/site identity is published as manufacturer when conflicting manufacturer evidence exists.
- No promotional-only description is published.
- No invalid zero/negative price is published.
- No unrelated product media or variants are attached.

### Diagnostic truth

- No field is simultaneously `captured_published` and absent from its required projection path.
- `MISSING_CONTRACT_FIELD` is based on selected projection scope, not arbitrary captured evidence.
- Candidate-only rejection findings do not downgrade a clean output.
- Informational completeness metrics do not appear as root causes.

### Regression safety

- Existing successful structural cases retain their valid public fields unless a focused test documents a current quality error.
- Blocked captures remain blocked/source-unavailable.
- Existing cross-product contamination and no-Cartesian-variant tests remain green.
- No hostname-specific extraction rule is added.

## 9. Recommended execution order

### P0 — Data currently present but structurally unreachable

1. Slice 1: projection-aware diagnostic truth
2. Slice 2: JSON-LD offer completeness
3. Slice 3: embedded-state typed paths and atomic offers
4. Slice 4: explicit child ownership and joins

**Checkpoint:** MR PORTER, NET-A-PORTER, Decathlon, DTLR, Nike, Farfetch, H&M, Gap, Sony, and J.Crew pass minimized structural fixtures.

### P1 — Correct semantic publication

6. Slice 5: offer and parent/variant semantics
7. Slice 6: product-rooted DOM extraction
8. Slice 7: brand roles
9. Slice 8: assets
10. Slice 9: variant completeness

**Checkpoint:** all confirmed `must_publish` rows pass; invalid and unrelated controls remain rejected.

### P2 — Production contract and release gate

11. Slice 10: complete-PDP profile
12. Run focused owner tests and lint for touched code
13. Produce a final residual ledger containing only:
    - source unavailable;
    - not present;
    - correctly rejected;
    - explicit manual schema decision.

## 10. Definition of done

The work is complete when, for the uploaded corpus:

1. every valid same-product value confirmed in captured HTML is published at the correct product/offer/variant/asset scope;
2. every omitted value has an accurate stage-specific explanation;
3. parent and variant values cannot contradict without explicit scope and lineage;
4. invalid, promotional, blocked, or unrelated evidence remains rejected;
5. diagnostics describe the published projection rather than every noisy candidate;
6. the implementation remains generic, evidence-driven, and compatible with the existing Harvest–Resolve–Publish architecture.
