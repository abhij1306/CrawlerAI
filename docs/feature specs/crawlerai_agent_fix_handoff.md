# CrawlerAI Crawl-95 High-Confidence Fix Handoff

**Purpose:** implementation handoff for a coding agent  
**Audit basis:** latest 95-URL crawl artifact bundle already reviewed against `page.html`, `record.json`, and `diagnose.json`  
**Repository:** CrawlerAI backend  
**Mode:** fix confirmed root causes only  
**Do not repeat:** broad repository discovery, URL-by-URL HTML review, or speculative missing-field work

---

## 1. Execution contract

The artifact audit is complete. Treat the evidence in this document as the ground truth for implementation.

### Required behavior

1. Start from the exact files and symbols listed under each issue.
2. Fix the generic architectural cause, not the individual domain.
3. Preserve the existing Harvest → Entity Assembly → Target Selection → Resolve → Publish ownership boundaries.
4. Add focused regression coverage for the supplied evidence shapes.
5. Keep unrelated missing fields unchanged unless the same patch deterministically resolves them.
6. Do not add post-publication repair, persistence cleanup, domain-specific hardcoding, or UI masking.

### Do not do

- Do not re-read all 95 HTML files.
- Do not run a broad `code_context` search before opening the listed symbols.
- Do not infer that every absent field is a parser defect.
- Do not weaken same-product guards globally to recover one field.
- Do not merge products because they share a retailer or family URL.
- Do not infer manufacturer brand from a retailer hostname or the first descriptive title word.
- Do not make a terminal shell look successful by preserving URL-derived identity.
- Do not make `diagnose.json` choose a different value than the publication projection.

### Suggested implementation order

1. **RC-05 + RC-06:** terminal shell and terminal-outcome consistency.
2. **RC-01 + RC-02:** cross-product contamination and product-node identity.
3. **RC-08:** ProductGroup / standalone variant / offer ownership.
4. **RC-03 + RC-04:** structured field and embedded-state admission gaps.
5. **RC-07 + RC-09:** unsafe brand derivation.
6. **RC-10:** diagnostic lineage.

This order reduces the risk that later extraction work is evaluated against invalid shell records or misleading diagnostics.

---

## 2. Confirmed issue index

| Code | Priority | Type | Result IDs | Confirmed impact |
|---|---|---|---|---|
| RC-01 | P0 | Data correctness | 9 | StockX publishes a sibling product title |
| RC-02 | P0 | Data correctness | 35 | Apple combines title and price from different products |
| RC-03 | P1 | Data recall | 11 | Exact Target brand and description are not emitted |
| RC-04 | P1 | Data recall | 34 | Exact Phase Eight brand payload is not admitted |
| RC-05 | P0 | Publication safety | 41 | Mytheresa error shell publishes a partial product |
| RC-06 | P1 | Outcome/diagnostics | 31, 52, 80 | Terminal failures produce contradictory field and failure diagnostics |
| RC-07 | P1 | Brand correctness | 54 | `Breville Bambino®` is published as brand instead of `Breville` |
| RC-08 | P0 | Entity ownership | 55 | Exact Decathlon offer is harvested but cannot join to the selected product |
| RC-09 | P0 | Brand correctness | 66 | Amazon descriptive word `Sparkling` is invented as manufacturer |
| RC-10 | P1 | Diagnostic lineage | 81, 86 | Diagnose reports full price although sale price is published |

---

# 3. Detailed implementation cards

## RC-01 — Sibling product admitted inside selected network root

**Priority:** P0  
**Affected result:** 9  
**URL:** `https://stockx.com/nike-dunk-low-retro-white-black-2021`

### Verified artifact facts

- Requested product: **Nike Dunk Low Retro White Black (2021)**.
- Published wrong title: **Nike Dunk Low QS CO.JP Reverse Ultraman (2024)**.
- The wrong title came from this nested network path:

```text
/data/product/families/color/members/edges/13/node/title
```

- The nested object is a related family member, not the requested product.
- Root selection chose `/data/product`.
- Prefix-based root containment then admitted all descendants under that root.

No further HTML review is required.

### Confirmed root cause

The network collector treats a selected product root as one trusted product namespace. Related products nested below the selected root are therefore allowed to emit canonical `product.*` facts.

The defect is not title ranking. The wrong sibling title should never become evidence owned by the selected product.

### Open these symbols first

- `backend/app/extraction/collectors/metadata.py`
  - `NetworkCollector.harvest`
- `backend/app/core/records/js_state_scope.py`
  - `select_product_roots`
  - `_promote_to_product_root`
  - `root_admits_path`
  - `path_is_within_selected_root`
- `backend/app/extraction/collectors/js_state.py`
  - `network_row`
  - product-context and URL-conflict helpers

### Required patch behavior

Introduce an **object-level related-product boundary** inside an otherwise selected root.

A nested object must not emit canonical product facts for the selected PDP when it represents a separate product and lacks an exact selected-product join.

Acceptable generic signals for a separate product boundary include:

- product-like object beneath collection/family/member/recommendation/search nodes;
- its own product URL, product ID, SKU, slug, or title identity;
- a value conflicting with the requested PDP identity;
- path semantics indicating members, edges, recommendations, related products, or alternatives.

Preferred design:

1. Keep root selection as a coarse admission boundary.
2. Before `network_row` emits canonical `product.*`, classify the object as:
   - selected product;
   - child offer/variant/asset of selected product;
   - separate sibling product;
   - non-product diagnostic object.
3. Either reject sibling product facts or materialize them as separate unselected product entities. Do not attach them to the selected product.

### Forbidden shortcuts

- Do not blacklist `StockX`.
- Do not blacklist only `/families/color/members`.
- Do not fix this in title ranking.
- Do not accept the sibling and hope URL-derived title wins.
- Do not weaken product root scoping.

### Focused regression shape

Construct one network payload containing:

```json
{
  "data": {
    "product": {
      "title": "Nike Dunk Low Retro White Black (2021)",
      "url": "https://stockx.com/nike-dunk-low-retro-white-black-2021",
      "families": {
        "color": {
          "members": {
            "edges": [
              {
                "node": {
                  "title": "Nike Dunk Low QS CO.JP Reverse Ultraman (2024)",
                  "url": "https://stockx.com/nike-dunk-low-qs-co-jp-reverse-ultraman-2024"
                }
              }
            ]
          }
        }
      }
    }
  }
}
```

### Done criteria

- Selected product title remains `Nike Dunk Low Retro White Black (2021)`.
- The sibling title cannot appear in selected-product decisions or projection lineage.
- The sibling object is rejected with a reason or represented as a separate unselected entity.
- Existing same-product nested offers, variants, and assets still work.

---

## RC-02 — Distinct JSON-LD products collapse on a shared family URL

**Priority:** P0  
**Affected result:** 35  
**URL:** `https://www.apple.com/shop/buy-iphone/iphone-16`

### Verified artifact facts

The captured JSON-LD contains distinct Product nodes:

- **iPhone 16**, with a low price of **699**.
- **iPhone 16 Plus**, with a low price of **799**.

Both nodes use the same family purchase URL.

The public record incorrectly combines:

- title from **iPhone 16 Plus**;
- price **699** from **iPhone 16**.

No further HTML review is required.

### Confirmed root cause

JSON-LD product subject/entity identity gives excessive weight to `url`.

When multiple distinct Product nodes share one family URL, their facts can collapse into one product entity. Scalar resolution then legally chooses values from the merged evidence pool, producing a cross-product record.

### Open these symbols first

- `backend/app/extraction/collectors/jsonld.py`
  - `_product`
  - `_jsonld_identity`
  - `_source_subject_ids`
- `backend/app/extraction/entities.py`
  - `_link_products`
  - `_product_identities`
  - `_product_identity_sets_match`
  - `_product_identity_sets_compatible`
  - `_select_primary_product_roots`

### Required patch behavior

A shared URL must not be sufficient to merge independent Product nodes when stronger node-level identity separates them.

Preserve JSON-LD node identity using, in order:

1. explicit `@id`;
2. product ID / SKU / MPN / GTIN;
3. JSON pointer or stable node path when several Product objects share a URL;
4. URL only when no contradictory product-node evidence exists.

For Product nodes sharing a family URL:

- keep separate entity candidates;
- select the requested product using URL path, node title, product ID, or other exact identity;
- bind each offer only to the Product node containing that offer;
- never resolve title from one node and price from another.

### Forbidden shortcuts

- Do not special-case Apple.
- Do not always split every JSON-LD Product sharing a URL; allow merge when a strong identity join proves the nodes are duplicate representations.
- Do not repair title or price after publication.
- Do not rank 699 versus 799 without fixing ownership.

### Focused regression shape

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "Product",
      "@id": "#iphone-16",
      "name": "iPhone 16",
      "url": "https://www.apple.com/shop/buy-iphone/iphone-16",
      "offers": {
        "@type": "AggregateOffer",
        "lowPrice": "699",
        "priceCurrency": "USD"
      }
    },
    {
      "@type": "Product",
      "@id": "#iphone-16-plus",
      "name": "iPhone 16 Plus",
      "url": "https://www.apple.com/shop/buy-iphone/iphone-16",
      "offers": {
        "@type": "AggregateOffer",
        "lowPrice": "799",
        "priceCurrency": "USD"
      }
    }
  ]
}
```

### Done criteria

- No public record mixes scalar fields from separate Product nodes.
- The selected entity has one coherent title/offer lineage.
- Duplicate JSON-LD representations with a genuine strong join can still merge.
- A public-resolution divergence guard is not used as the primary fix; entity ownership must be correct earlier.

---

## RC-03 — Selected Target fields use unmapped structured paths

**Priority:** P1  
**Affected result:** 11  
**URL:** `https://www.target.com/p/tobago-stripe-duvet-cover-set-levtex-home/-/A-1002150739?preselect=1002150742#lnk=sametab`

### Verified artifact facts

The selected exact-product state contains:

```text
primary_brand.name = "Levtex Home"
product_vendors[].vendor_name = "Levtex Home"
product_description.downstream_description = exact product prose
```

The output does not publish the exact manufacturer brand or exact description.

No further HTML review is required.

### Confirmed root cause

The generic structured mapping supports shapes such as:

```text
brand.name
vendor.name
description
productDescription
```

It does not support the verified shapes:

```text
primary_brand.name
product_vendors[].vendor_name
product_description.downstream_description
```

The selected product object is admitted, but these nested values never become evidence.

### Open these symbols first

- `backend/app/core/config/field_mappings.py`
  - `ECOMMERCE_STRUCTURED_SOURCE_FACT_TYPES`
  - `ECOMMERCE_STRUCTURED_SOURCE_VALUE_PATH_FACT_TYPES`
  - `ECOMMERCE_STRUCTURED_CONTAINER_SOURCE_KEYS`
- `backend/app/core/records/structured_variant_state.py`
  - `configured_value_path_rows`
  - configured path traversal helpers
- `backend/app/extraction/collectors/js_state.py`
  - `network_row`

### Required patch behavior

Add generic nested path support for:

```text
primary_brand.name                         -> product.brand
product_vendors[].vendor_name              -> product.brand
product_description.downstream_description -> product.description
```

Requirements:

- Retain exact source-path locator.
- Retain selected-product ownership.
- Do not flatten every arbitrary `name` field.
- Vendor values may become canonical brand only under the existing manufacturer/brand-role policy.
- If `primary_brand.name` and vendor name agree, they should corroborate rather than conflict.
- Description must remain exact source prose subject to existing description validity rules.

### Forbidden shortcuts

- Do not add a Target adapter that writes public fields.
- Do not infer `Levtex Home` from the title while ignoring exact structured evidence.
- Do not map all `vendor_name` values globally without product-root ownership.

### Focused regression shape

```json
{
  "product": {
    "tcin": "1002150742",
    "primary_brand": {
      "name": "Levtex Home"
    },
    "product_vendors": [
      {
        "vendor_name": "Levtex Home"
      }
    ],
    "product_description": {
      "downstream_description": "Verified exact product description."
    }
  }
}
```

### Done criteria

- Brand publishes `Levtex Home`.
- Description publishes the exact selected-product prose.
- The evidence locators identify the precise nested paths.
- Unrelated vendor and recommendation objects remain excluded.

---

## RC-04 — Executable `dataLayer.concat` payload is not admitted

**Priority:** P1  
**Affected result:** 34  
**URL:** `https://www.phase-eight.com/product/lucinda-spot-midi-dress-10015500806.html`

### Verified artifact facts

The captured executable script contains an exact PDP product payload using `dataLayer.concat(...)`.

Inside it, the requested product has:

```text
item_brand = "Phase Eight"
brand = "Phase Eight"
```

The public brand remains missing.

No further HTML review is required.

### Confirmed root cause

Embedded state admission currently handles:

- JSON script bodies;
- recognized direct assignments;
- JSON-decodable dotted assignments.

It does not decode bounded JSON arguments passed to:

```javascript
dataLayer.push(...)
dataLayer.concat(...)
```

`dataLayer` is also not a configured direct global assignment source.

### Open these symbols first

- `backend/app/core/records/html_helpers.py`
  - `embedded_state_payloads`
  - `_assigned_state_payloads`
  - `_decode_assigned_json`
- `backend/app/core/config/variant_policy.py`
  - `EMBEDDED_STATE_SCRIPT_SELECTOR`
  - `EMBEDDED_STATE_GLOBAL_KEYS`
  - embedded-state size and count limits
- `backend/app/extraction/collectors/js_state.py`
  - embedded payload iteration and root selection

### Required patch behavior

Add a bounded parser for JSON object/array arguments in approved state-carrier calls:

```javascript
dataLayer.push(<JSON>)
dataLayer.concat(<JSON>)
```

The parser must:

1. scan script text without executing JavaScript;
2. decode only a syntactically valid JSON object or array argument;
3. obey existing script size, payload count, object depth, and list limits;
4. feed decoded payloads through existing product-root and same-product guards;
5. preserve a source locator containing script index and call type.

### Forbidden shortcuts

- Do not execute JavaScript.
- Do not regex-extract `brand` from arbitrary script text.
- Do not trust all analytics events as product truth.
- Do not bypass root selection.
- Do not special-case Phase Eight.

### Focused regression shape

```html
<script>
  dataLayer = dataLayer.concat([
    {
      "event": "view_item",
      "ecommerce": {
        "detail": {
          "products": [
            {
              "id": "10015500806",
              "name": "Lucinda Spot Midi Dress",
              "brand": "Phase Eight",
              "item_brand": "Phase Eight"
            }
          ]
        }
      }
    }
  ]);
</script>
```

### Done criteria

- Exact product brand publishes as `Phase Eight`.
- Arbitrary non-JSON script arguments are ignored safely.
- Recommendation and unrelated analytics products remain outside the selected target.
- Parser remains bounded and non-executing.

---

## RC-05 — Semantic error shell publishes a URL-derived product record

**Priority:** P0  
**Affected result:** 41  
**URL:** `https://www.mytheresa.com/int/en/women/valentino-garavani-loco-small-floral-linen-top-handle-bag-beige-p01155657`

### Verified artifact facts

The capture visibly states:

```text
Something went wrong.
Please try again in a moment.
```

It contains no valid product JSON-LD or sellable product content.

Current behavior:

- publishes a URL-derived Valentino product title;
- returns a partial product record.

Correct behavior:

- terminal semantic shell;
- zero public records;
- detail fields `source_unavailable`;
- explicit shell failure classification.

No further HTML review is required.

### Confirmed root cause

`classify_low_content_reason` returns early when visible text length is at least 120 characters. Terminal phrases in the body are therefore not checked on a sufficiently verbose error page.

The terminal phrase registry also omits common phrases such as:

```text
something went wrong
access denied
site maintenance
temporarily unavailable
```

A URL-derived title can then survive as a thin record.

### Open these symbols first

- `backend/app/acquisition/browser_readiness.py`
  - `classify_low_content_reason`
  - `looks_like_low_content_shell`
  - browser outcome classification
- `backend/app/core/config/extraction_rules/_common.py`
  - `LOW_CONTENT_SHELL_PHRASES`
- `backend/app/extraction/engine.py`
  - `_assess`
  - `_capture_outcome`
  - `_is_semantic_detail_shell`
  - `_is_thin_detail_record`
- shell-record validator/helper used by `is_shell_record`

### Required patch behavior

Terminal error phrases must be evaluated before the generic visible-text length escape.

Use a fail-closed combination:

1. terminal phrase or terminal title;
2. no product anchors or no meaningful selected product fields;
3. URL-derived identity is the only surviving product evidence.

A long error message must not become usable content merely because it has more than 120 characters.

Expand the generic phrase vocabulary conservatively and classify with context to avoid rejecting legitimate product copy containing words such as “unavailable.”

### Forbidden shortcuts

- Do not reject all pages containing “wrong,” “denied,” or “unavailable.”
- Do not make URL-derived title a meaningful product anchor.
- Do not fix only Mytheresa.
- Do not allow shell publication and merely downgrade confidence.

### Focused regression shape

```html
<html>
  <head><title>Something went wrong</title></head>
  <body>
    <main>
      <h1>Something went wrong.</h1>
      <p>Please try again in a moment.</p>
      <p>Additional support and navigation text makes this page longer than 120 visible characters.</p>
    </main>
  </body>
</html>
```

### Done criteria

- Zero records.
- Verdict is terminal error, not partial.
- Capture outcome is semantic shell.
- Requested detail fields are `source_unavailable`.
- URL-derived title is diagnostic-only and not published.
- A genuine product page containing incidental “unavailable” text still passes when strong product anchors exist.

---

## RC-06 — Terminal outcome is not authoritative for field and failure diagnostics

**Priority:** P1  
**Affected results:** 31, 52, 80

### Affected URLs

- Result 31 — ASOS  
  `https://www.asos.com/us/asos-curve/asos-design-curve-lightweight-pull-on-barrel-pants-in-darkwash/prd/210397084#colourWayId-210397088`
- Result 52 — Dick’s Sporting Goods  
  `https://www.dickssportinggoods.com/p/birkenstock-womens-arizona-big-buckle-soft-footbed-sandals-25birwcasuwrznbgbcegp/25birwcasuwrznbgbcegp?color=Sandcastle`
- Result 80 — Louis Vuitton  
  `https://us.louisvuitton.com/eng-us/products/bootleg-pants-nvprod7220319v/1AJUPQ`

### Verified artifact facts

#### Result 31 — ASOS

- HTTP 404.
- Zero product records is correct.
- Diagnostics incorrectly retain URL-title publication semantics.
- Failure classification is `semantic_resolution` instead of a terminal input/not-found outcome.
- Only offer/variant families are marked unavailable.

#### Result 52 — Dick’s

- Site-maintenance page.
- Blocked with zero records is correct.
- Requested fields are reported `not_present_in_captured_sources`, not `source_unavailable`.

#### Result 80 — Louis Vuitton

- Explicit access-denied shell.
- Zero records is correct.
- Acquisition diagnose reports `capture_outcome: ok`.
- Fields are `not_present`.
- Failure classification reports validation rather than terminal shell/unavailable input.

### Confirmed root cause

Terminal state is derived independently in several places:

- acquisition source-capability diagnostics;
- extraction capture outcome;
- field-state construction;
- failure classification;
- observability acquisition section.

These paths do not share one authoritative normalized outcome. They can therefore contradict one another.

`build_source_capability_diagnostics` also treats generic HTTP errors as affecting only offer and variant families, although a 404 detail page makes all requested detail fields unavailable.

### Open these symbols first

- `backend/app/acquisition/source_capabilities.py`
  - `build_source_capability_diagnostics`
  - `attach_source_capability_diagnostics`
- `backend/app/extraction/engine.py`
  - `_capture_outcome`
  - `_failure_classifications`
  - `_is_semantic_detail_shell`
- `backend/app/extraction/result_building.py`
  - `projection_field_states`
  - legacy `field_evidence_states` if still reachable
- `backend/app/observability/diagnose.py`
  - `_acquisition_section`
  - `_acquisition_capture_outcome`
- capture contracts in `backend/app/extraction/contracts.py`

### Required patch behavior

Create or use one normalized terminal detail outcome with at least:

```text
ok
blocked
not_found
semantic_shell
error
```

Then reuse it for:

- verdict/capture outcome;
- all requested detail field states;
- failure classification;
- acquisition diagnose;
- retry/review behavior.

Rules:

- `blocked`, `not_found`, and `semantic_shell` make requested detail fields `source_unavailable`.
- A URL-derived title on a terminal page does not convert a field to published/resolved.
- Failure classification must distinguish not-found and shell/unavailable input from semantic resolution failure.
- Diagnose must report the normalized outcome rather than recomputing from status and `blocked` alone.

### Forbidden shortcuts

- Do not patch the three sites separately.
- Do not set every HTTP 4xx to blocked.
- Do not allow `source_capabilities` to override a stronger final capture outcome.
- Do not duplicate the terminal classification logic in another module.

### Focused regression cases

1. HTTP 404 with a URL-derived title.
2. Blocked site-maintenance HTML with HTTP 200 or retryable status.
3. HTTP 200 access-denied semantic shell.
4. Existing Lululemon blocked control from result 82.

### Done criteria

For results 31, 52, and 80:

- zero records remains correct;
- capture, verdict, field states, and failure classification agree;
- all requested detail fields are `source_unavailable`;
- no misleading published winner appears.

---

## RC-07 — Trademark-marker brand inference captures brand plus model

**Priority:** P1  
**Affected result:** 54  
**URL:** `https://www.williams-sonoma.com/products/breville-the-bambino-plus/`

### Verified artifact facts

Title:

```text
Breville Bambino® Plus Espresso Machine
```

Published brand:

```text
Breville Bambino®
```

Correct manufacturer brand:

```text
Breville
```

The registered mark belongs to the product line `Bambino`, not to the full manufacturer name.

No further HTML review is required.

### Confirmed root cause

`infer_brand_from_title_marker` takes the complete title prefix through `™` or `®` as brand.

That heuristic assumes the mark terminates a brand phrase. It cannot distinguish:

- manufacturer trademark;
- product-line trademark;
- model trademark.

`_brand_from_title` can then publish this derived value without sufficient independent manufacturer corroboration.

### Open these symbols first

- `backend/app/core/shared/field_coerce_text.py`
  - `infer_brand_from_title_marker`
  - related URL/title inference helpers
- `backend/app/extraction/resolution/__init__.py`
  - `_brand_from_title`
  - `_semantic_derived_facts`
- brand invalidity/ranking logic in:
  - `backend/app/extraction/pipeline.py`
  - `backend/app/extraction/resolution/ranking.py`

### Required patch behavior

A trademark mark alone must not define the manufacturer boundary.

Possible safe policy:

1. If exact direct brand evidence exists, do not derive a longer marker prefix.
2. If URL/path/title independently identifies a shorter leading brand, prefer the corroborated shorter value.
3. If the marked phrase extends beyond a corroborated manufacturer token, treat the extension as product/model text.
4. If no independent manufacturer signal exists, leave brand unresolved instead of inventing one.

### Forbidden shortcuts

- Do not hardcode `Breville`.
- Do not strip the last word before every trademark marker.
- Do not replace marker inference with hostname-as-manufacturer.
- Do not mutate the public brand after resolution.

### Focused regression shape

```text
URL: https://shop.test/products/breville-the-bambino-plus
Title: Breville Bambino® Plus Espresso Machine
Expected brand: Breville
Rejected derived brand: Breville Bambino®
```

Also retain positive coverage for a title where a genuinely complete brand carries the mark.

### Done criteria

- Williams-Sonoma result resolves brand as `Breville`.
- `Breville Bambino®` is not emitted as manufacturer truth.
- Legitimate marked brand names still work when corroborated.
- No hostname-only manufacturer derivation is introduced.

---

## RC-08 — Standalone JSON-LD variant offer cannot materialize ownership

**Priority:** P0  
**Affected result:** 55  
**URL:** `https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642`

### Verified artifact facts

The JSON-LD contains:

1. a `ProductGroup`;
2. a standalone `Product`;
3. `Product.isVariantOf` referencing the ProductGroup;
4. a nested `Offer` whose URL exactly matches the requested PDP;
5. exact commercial facts:
   - price `10.99`;
   - currency `GBP`;
   - schema availability `OnlineOnly`.

The collector harvests the commercial facts, but they end as `join_failed`.

No further HTML review is required.

### Confirmed root cause

The standalone Product is converted into variant evidence.

Variant materialization requires identity keys generated from:

```text
variant.id
variant.sku
variant.gtin
variant.url
selected options
```

This Product has no usable variant-level identity in those fields. Its exact requested URL exists only inside the nested Offer.

Therefore:

- `_variant_groups` rejects the provisional variant because it has no identity keys;
- no `VariantEntity` is created;
- `_variant_for` cannot bind the offer;
- the exact offer remains unowned/join-failed.

The `isVariantOf` alias proves the parent product relation, but not enough identity is carried into variant materialization.

### Open these symbols first

- `backend/app/extraction/collectors/jsonld.py`
  - `_standalone_variant`
  - `_variant`
  - `_offers`
  - `_source_subject_ids`
  - `_known_variant_subject_ids`
- `backend/app/core/config/field_mappings.py`
  - `ECOMMERCE_JSONLD_VARIANT_FACT_TYPES`
- `backend/app/extraction/entities.py`
  - `_variant_groups`
  - `_variant_identity_keys`
  - `_variant_entity`
  - `_link_offers`
  - `_variant_for`
  - `_product_for_child`
  - `_owner_product_id`

### Required patch behavior

Use the verified relation and exact offer identity without inventing a Cartesian variant.

Two acceptable designs:

#### Option A — Guarded variant identity

Allow a standalone Product to materialize as a variant when all are true:

- it has an `isVariantOf` reference resolving to the selected ProductGroup;
- it has commercial evidence;
- its nested Offer URL exactly matches the requested PDP;
- no conflicting variant identity exists.

Create a stable variant identity from the standalone Product node identity or guarded offer URL.

#### Option B — Direct parent offer ownership

When a standalone Product references the selected ProductGroup but lacks a distinct variant identity:

- attach its exact matching Offer directly to the selected product;
- do not create an optionless public variant unless the schema establishes a sellable variant entity.

Either approach must retain the `isVariantOf` lineage.

### Forbidden shortcuts

- Do not publish any unowned offer merely because its URL resembles the page.
- Do not create a fake optionless variant for every standalone Product.
- Do not delete join failure reporting.
- Do not copy variant commercial fields to the parent during Publish.
- Do not special-case Decathlon.

### Focused regression shape

```json
{
  "@context": "https://schema.org",
  "@graph": [
    {
      "@type": "ProductGroup",
      "@id": "#group-347273",
      "productGroupID": "347273",
      "name": "Pressurised Padel Balls PB Speed Tri-Pack"
    },
    {
      "@type": "Product",
      "@id": "#product-8804642",
      "isVariantOf": {
        "@id": "#group-347273"
      },
      "offers": {
        "@type": "Offer",
        "url": "https://www.decathlon.co.uk/p/pressurised-padel-balls-pb-speed-tri-pack/347273/m8804642",
        "price": "10.99",
        "priceCurrency": "GBP",
        "availability": "https://schema.org/OnlineOnly"
      }
    }
  ]
}
```

### Done criteria

- Price publishes as `10.99`.
- Currency publishes as `GBP`.
- Availability publishes through existing canonicalization.
- No `CHILD_JOIN_FAILED` remains for the exact offer.
- The offer is owned by the selected product or a correctly materialized variant.
- Unrelated standalone Products cannot attach by URL alone.

---

## RC-09 — Marketplace URL/title fallback invents a manufacturer

**Priority:** P0  
**Affected result:** 66  
**URL:** `https://www.amazon.com/Sparkling-Prebiotic-Beverage-Vinegar-Seltzer/dp/B0F5Y3X8PP/?th=1`

### Verified artifact facts

The thin capture has no reliable manufacturer or brand evidence.

Title begins:

```text
Sparkling Prebiotic Beverage Vinegar Seltzer
```

Published brand:

```text
Sparkling
```

`Sparkling` is a descriptive product word, not verified manufacturer evidence.

Correct behavior:

- brand remains absent/unresolved;
- record remains partial/reviewable as appropriate;
- no manufacturer is invented.

No further HTML review is required.

### Confirmed root cause

The marketplace fallback in `infer_brand_from_product_url` returns the first title word when:

- the first two title tokens match a long product slug;
- the path contains a product-ID signal or brand-route-like shape;
- the first word is not in a stop list.

This is lexical URL agreement, not manufacturer evidence.

### Open these symbols first

- `backend/app/core/shared/field_coerce_text.py`
  - `infer_brand_from_product_url`
  - marketplace long-slug fallback block
- `backend/app/extraction/resolution/__init__.py`
  - `_brand_from_title`
  - `_semantic_derived_facts`
- brand-role guardrails in `backend/app/extraction/pipeline.py`

### Required patch behavior

Manufacturer derivation from a marketplace title/slug requires an independent brand signal.

Acceptable corroboration may include:

- explicit structured brand/manufacturer;
- brand-specific route segment distinct from product title;
- a recognized manufacturer marker;
- repeated exact manufacturer value in independent product-owned evidence.

Not acceptable:

- the same word appearing in the title and URL;
- a numeric `/dp/` or product-ID signal;
- first-word capitalization;
- retailer hostname.

If independent corroboration is absent, return `None`.

### Forbidden shortcuts

- Do not add `Sparkling` to a stop list.
- Do not blacklist Amazon.
- Do not use the retailer hostname as manufacturer.
- Do not require all marketplace brands to be missing when exact structured evidence exists.

### Focused regression cases

Negative:

```text
URL: /Sparkling-Prebiotic-Beverage-Vinegar-Seltzer/dp/B0F5Y3X8PP
Title: Sparkling Prebiotic Beverage Vinegar Seltzer
Expected brand: None
```

Positive:

```text
URL: /Nike-Air-Max-Product-Name/dp/ABC123
Title: Nike Air Max Product Name
Independent structured brand: Nike
Expected brand: Nike
```

### Done criteria

- `Sparkling` is not published.
- Exact structured marketplace brands still publish.
- No new hostname-based manufacturer truth is introduced.
- Missing brand remains visible in field diagnostics.

---

## RC-10 — Diagnose winner differs from the published value

**Priority:** P1  
**Affected results:** 81, 86

### Affected URLs and verified facts

#### Result 81 — Calvin Klein

URL:

`https://www.calvinklein.us/en/men/accessories/bags/structured-commuter-bag/198629014314.html`

- Public record price: `79.50`.
- Diagnose winner: `159.00`.
- `159.00` is the full-price DOM candidate.
- The published value is the valid sale price.

#### Result 86 — Tommy Hilfiger

URL:

`https://usa.tommy.com/en/women/shoes-accessories/shoes/script-monogram-espadrille-sandal/TZ001658-420.html?journey=women-shoesandacc-shoes-sandalsandslides`

- Public record price: `49.50`.
- Diagnose winner: `99.00`.
- `99.00` is the full-price DOM candidate.
- The published value is the valid sale price.

No further HTML review is required.

### Confirmed root cause

`_decisions_by_public_field` maps a public field to the first resolved decision for its fact type.

It does not scope the decision to:

- the selected publication entity;
- the selected offer;
- the publication projection entry;
- the actual authorized public value.

`_winner` then displays the first accepted evidence from that unrelated resolved decision.

### Open these symbols first

- `backend/app/observability/diagnose.py`
  - `_field_section`
  - `_winner`
  - `_decisions_by_public_field`
- publication structures in:
  - `backend/app/extraction/publication.py`
  - publication projection contracts
- selected/derived fact construction in:
  - `backend/app/extraction/result_building.py`
  - `backend/app/extraction/resolution`

### Required patch behavior

Build field diagnostics from the **publication projection**, not from the first resolved decision sharing a fact type.

For each public field, expose:

- published value;
- selected entity ID;
- selected offer/variant ID when applicable;
- evidence IDs authorized by the projection;
- rule/derivation lineage;
- rejected alternatives.

The displayed `winner.value` must match the serialized public value after representation-only canonicalization.

If the public value is derived, diagnose must show the derived fact and its input evidence, not an arbitrary direct candidate.

### Forbidden shortcuts

- Do not hide `winner`.
- Do not overwrite the diagnostic value with `record.json` while retaining false evidence lineage.
- Do not choose the minimum numeric price generically.
- Do not fix only sale-price pages.

### Focused regression cases

1. Two offer price decisions: full price and sale price; projection publishes sale price.
2. Variant price plus parent price; projection publishes one scope only.
3. Derived currency/availability winner.
4. Suppressed field with no public value.

### Done criteria

- Result 81 diagnose winner is `79.50`.
- Result 86 diagnose winner is `49.50`.
- Winner evidence IDs belong to the published projection entry.
- Rejected full-price evidence remains visible as rejected/alternative evidence where appropriate.
- Diagnostic field state and public record cannot diverge silently.

---

# 4. Failed URL disposition table

These five URLs must not be treated as five parser failures.

| Result | URL | Verified capture | Correct data behavior | Remaining bug |
|---:|---|---|---|---|
| 31 | ASOS URL listed under RC-06 | HTTP 404 | Zero records | Terminal diagnostics inconsistent |
| 41 | Mytheresa URL listed under RC-05 | HTTP 200 semantic error shell | Zero records | Incorrect partial record publication |
| 52 | Dick’s URL listed under RC-06 | Site-maintenance / blocked shell | Zero records | Fields incorrectly marked `not_present` |
| 80 | Louis Vuitton URL listed under RC-06 | Access-denied shell | Zero records | Capture/failure/field diagnostics conflict |
| 82 | `https://shop.lululemon.com/p/jackets-and-hoodies-jackets/Nulu-Cropped-Define-Jacket/_/prod10930188?color=77142` | Blocked HTTP 400/API error body | Zero records and unavailable fields | **Control: no confirmed extraction bug** |

Do not “fix” result 82 unless a terminal-outcome refactor breaks it.

---

# 5. Issues deliberately excluded from implementation

The audit intentionally did **not** classify the following as bugs.

## 5.1 `source_unavailable` commercial fields

When acquisition did not capture the product source, missing price/currency/availability is not an extraction defect.

Do not add fallback guesses or hostname currency inference merely to increase completeness.

## 5.2 `captured_suppressed` parent SKU

Some parent SKUs are deliberately suppressed because sellable identity belongs to variants.

Do not publish a parent SKU unless entity and publication policy establish it as canonical product identity.

## 5.3 `captured_but_rejected` descriptions and prices

Candidates rejected for promotional copy, UI pollution, incomplete prose, installment pricing, or ambiguity must remain rejected unless a specific issue above changes their ownership or source shape.

Do not globally weaken invalidity flags.

## 5.4 Missing brand with only retailer/site identity

A retailer hostname or page identity is not manufacturer truth.

Do not add brand inference for Nintendo, reseller watch pages, Gap, Calvin Klein, Tommy Hilfiger, or similar URLs unless direct product-owned manufacturer evidence exists.

RC-07 and RC-09 are reductions of unsafe inference, not invitations to add more inference.

## 5.5 Variant-axis review findings

Some otherwise valid records remain partial because a complete variant axis is not captured.

Do not create Cartesian variants or optionless variants to clear diagnostics.

---

# 6. Cross-cutting invariants for all patches

## 6.1 Evidence ownership

Every public value must be traceable to evidence owned by:

- the selected product;
- its selected offer;
- a valid selected/eligible variant;
- a valid owned asset.

A matching text value is not an ownership relation.

## 6.2 Product identity

Use strong identities before weak identities:

1. GTIN / SKU / MPN / product ID;
2. explicit `@id` and relation aliases;
3. exact canonical PDP URL;
4. selected variant/offer URL;
5. normalized title agreement only as supporting evidence.

A family URL must not collapse distinct Product nodes by itself.

## 6.3 Brand role

Canonical public brand means manufacturer/product brand.

The following are not automatically manufacturer truth:

- retailer;
- seller;
- marketplace;
- site identity;
- first title token;
- title suffix matching host;
- product-line trademark.

## 6.4 Terminal acquisition

A terminal shell is a source limitation, not a product with missing fields.

URL-derived identity cannot make a terminal page publishable.

## 6.5 Diagnostics

`diagnose.json` must explain the value actually authorized by the publication projection.

It must not independently select another winner.

## 6.6 Generic implementation

All fixes must be expressed as reusable schema/identity/ownership rules.

No production rule may contain one of the affected domains solely to pass the regression.

---

# 7. Suggested commit slices

## Slice 1 — Terminal outcome authority

Implement RC-05 and RC-06 together.

Likely files:

```text
backend/app/acquisition/browser_readiness.py
backend/app/core/config/extraction_rules/_common.py
backend/app/acquisition/source_capabilities.py
backend/app/extraction/engine.py
backend/app/extraction/result_building.py
backend/app/observability/diagnose.py
```

Expected result:

- Mytheresa zero records.
- ASOS/Dick’s/Louis Vuitton diagnostics agree.
- Lululemon remains a correct blocked control.

## Slice 2 — Product boundary and identity

Implement RC-01 and RC-02.

Likely files:

```text
backend/app/core/records/js_state_scope.py
backend/app/extraction/collectors/js_state.py
backend/app/extraction/collectors/metadata.py
backend/app/extraction/collectors/jsonld.py
backend/app/extraction/entities.py
```

Expected result:

- StockX sibling title excluded.
- Apple Product nodes remain coherent.

## Slice 3 — JSON-LD ownership

Implement RC-08.

Likely files:

```text
backend/app/extraction/collectors/jsonld.py
backend/app/extraction/entities.py
backend/app/core/config/field_mappings.py
```

Expected result:

- Decathlon exact offer joins safely.

## Slice 4 — Structured payload coverage

Implement RC-03 and RC-04.

Likely files:

```text
backend/app/core/config/field_mappings.py
backend/app/core/records/structured_variant_state.py
backend/app/core/records/html_helpers.py
backend/app/core/config/variant_policy.py
backend/app/extraction/collectors/js_state.py
```

Expected result:

- Target brand/description publish from exact product state.
- Phase Eight brand publishes from bounded `dataLayer.concat` JSON.

## Slice 5 — Brand inference safety

Implement RC-07 and RC-09.

Likely files:

```text
backend/app/core/shared/field_coerce_text.py
backend/app/extraction/resolution/__init__.py
backend/app/extraction/pipeline.py
backend/app/extraction/resolution/ranking.py
```

Expected result:

- Breville remains manufacturer.
- Amazon `Sparkling` brand disappears.
- Existing exact structured brand coverage remains intact.

## Slice 6 — Projection-grounded diagnostics

Implement RC-10.

Likely files:

```text
backend/app/observability/diagnose.py
backend/app/extraction/publication.py
backend/app/extraction/result_building.py
backend/app/extraction/contracts.py
```

Expected result:

- Diagnose winner equals published value and lineage.

---

# 8. Regression test placement

Prefer focused tests in existing extraction behavior/regression modules rather than a new broad integration harness.

Likely homes:

```text
backend/tests/unit/test_crawl_run_95_regressions.py
backend/tests/unit/test_extraction_contract_behavior.py
backend/tests/unit/test_extraction_js_state_behavior.py
backend/tests/unit/test_extraction_integrity_behavior.py
backend/tests/unit/test_diagnose_builder.py
backend/tests/unit/test_source_capabilities.py
```

Test names should describe the invariant, not the website. Examples:

```text
test_selected_network_root_rejects_nested_sibling_product_facts
test_jsonld_products_sharing_family_url_do_not_merge_without_strong_identity
test_nested_primary_brand_and_downstream_description_are_emitted
test_embedded_data_layer_concat_json_is_admitted_without_script_execution
test_verbose_semantic_error_shell_cannot_publish_url_derived_record
test_terminal_detail_outcome_controls_all_requested_field_states
test_title_trademark_marker_cannot_expand_brand_without_corroboration
test_standalone_variant_offer_url_can_join_referenced_product_group
test_marketplace_slug_cannot_invent_brand_from_first_title_word
test_diagnose_winner_uses_published_projection_entry
```

Tests may use minimal synthetic payloads from this document. They do not need the original full HTML.

---

# 9. Final acceptance matrix

| Result | Required final behavior |
|---:|---|
| 9 | Title is the requested StockX product; sibling member cannot win |
| 11 | Brand `Levtex Home`; exact downstream description published |
| 31 | Zero records; normalized `not_found`; all requested fields unavailable |
| 34 | Brand `Phase Eight` from bounded structured payload |
| 35 | One coherent Apple Product node; no Plus-title/base-price mixture |
| 41 | Zero records; semantic shell; no URL-derived product publication |
| 52 | Zero records; blocked; requested fields unavailable |
| 54 | Brand `Breville`, not `Breville Bambino®` |
| 55 | Price `10.99`, currency `GBP`, canonical availability, no offer join failure |
| 66 | Brand absent/unresolved; never `Sparkling` |
| 80 | Zero records; semantic/access shell outcome; consistent diagnostics |
| 81 | Public price and diagnose winner both `79.50` |
| 82 | Remains a correct blocked control |
| 86 | Public price and diagnose winner both `49.50` |

---

# 10. Completion checklist

Before declaring the work complete:

- [ ] Each RC has a focused regression test.
- [ ] No affected domain name appears in production extraction logic.
- [ ] No public-field repair was added after Resolve/Publish.
- [ ] No sibling product can contribute selected-product scalar facts without an explicit join.
- [ ] Shared URLs do not collapse distinct Product nodes without stronger identity.
- [ ] Exact ProductGroup/variant/offer relationships retain ownership lineage.
- [ ] Embedded script parsing remains bounded and non-executing.
- [ ] Manufacturer inference requires independent evidence.
- [ ] Terminal outcome is represented once and reused everywhere.
- [ ] Field states agree with terminal outcome.
- [ ] Failure classifications agree with terminal outcome.
- [ ] Diagnose winner agrees with the publication projection.
- [ ] Result 82 remains unchanged as a blocked control.
- [ ] Unrelated missing/rejected/suppressed fields were not “fixed” speculatively.

---

## Final instruction to the coding agent

Implement only the confirmed root causes in RC-01 through RC-10. Use the minimal synthetic evidence shapes above for regression coverage. Do not restart the audit, do not reclassify unrelated omissions, and do not trade same-product safety for field recall.
