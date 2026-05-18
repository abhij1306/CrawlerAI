# UCP Audit — End-to-End Test Spec
**Test Domain:** hatchcollection.com  
**Test URL:** https://www.hatchcollection.com/collections/maternity-dresses  
**Purpose:** Codex debug target — audit must produce this output before the feature is considered working  
**Instruction to Codex:** Run the audit. Compare actual output to expected output below. Fix until all assertions pass.

---

## What We Know From HTTP Inspection

Before expected outputs, here is the ground truth from an HTTP-only fetch of the site.
This is the same data the audit engine will see. Do not dispute these observations.

**Platform:** Shopify (confirmed — `meta-shopify-checkout-api-token` present, store ID 19918975)  
**UCP manifest:** `/.well-known/ucp` → **NOT fetchable / 404** (Shopify UCP opt-in not complete for this merchant)  
**Product JSON-LD:** Collection page has NO Product JSON-LD — only page metadata. JSON-LD exists on individual product pages (Shopify default schema).  
**Variants:** Products have color + size axes. "Choose options" CTA confirms multi-variant products.  
**Pricing anomaly:** Discounts are "IN CART" only — JSON-LD `offers.price` shows full price (e.g. $268.00) but humans see "25% OFF IN CART" messaging. Agent cannot see the actual purchase price.  
**Policy:** Returns at `returns.hatchcollection.com` (separate domain). No `shippingDetails` in JSON-LD. Currency is USD (text only, not ISO-structured in JSON-LD).  
**Metafields:** `additionalProperty` array in Shopify default JSON-LD is typically empty — material, GTIN, brand are not in JSON-LD unless merchant explicitly exposes them.  
**Taxonomy:** Collection page shows "Maternity Dresses" and "Maternity Swimwear" as product types. Shopify `product_type` field likely inconsistent across 87 products (mix of "Maternity Dresses", "Dresses", blank).

---

## Expected Audit Output — Dimension by Dimension

### D-UCP1: Manifest Discovery
```
manifest_found: false
capabilities_declared: []
missing_required_capabilities: ["product_discovery", "checkout", "orders"]
manifest_valid: false
raw_manifest: null
errors: ["/.well-known/ucp returned 404"]

dimension_score: 0
status: "fail"
findings:
  - finding_id: "UCP1-001"
    severity: "blocking"
    description: "UCP manifest not found at /.well-known/ucp"
    fix_guidance: "Enable Shopify UCP in your Shopify admin under Settings > Agentic Commerce. 
                   This is required for AI agents to discover and transact with your store."
    estimated_effort: "15 min"
```

**Hard gate consequence:** D-UCP1 = 0 → `d_ucp1_gate_applied: true` → `overall_score` must be ≤ 30 regardless of other dimension scores.

---

### D-UCP2: Product JSON-LD Schema
```
# Audit samples 5 product pages. Expected per-page result:
product_jsonld_found: true          # Shopify default schema is present on PDPs
required_fields_present: ["name", "offers.price", "offers.availability", "offers.priceCurrency"]
recommended_fields_present: ["description", "image"]
recommended_fields_missing: ["sku", "brand", "gtin13"]
ucp_fields_present: []              # additionalProperty array is EMPTY in Shopify default
completeness_score: 55              # required all present, recommended partial, ucp empty
missing_required: []
missing_recommended: ["sku", "brand", "gtin13"]

dimension_score: 55
status: "warning"
findings:
  - finding_id: "UCP2-001"
    severity: "warning"
    description: "additionalProperty array is empty across all sampled products. 
                  AI agents use this to filter by size, color, material."
    affected_count: 5
    fix_guidance: "Expose metafields in Shopify JSON-LD via theme customization or 
                   Shopify's product metafields API."
    estimated_effort: "1 sprint"
  - finding_id: "UCP2-002"
    severity: "warning"
    description: "brand field missing from JSON-LD on all sampled products."
    affected_count: 5
    fix_guidance: "Add brand metafield and expose in JSON-LD template."
    estimated_effort: "2 hours"
  - finding_id: "UCP2-003"
    severity: "warning"
    description: "gtin13/barcode missing from JSON-LD. Required for product identity in agent commerce."
    affected_count: 5
    fix_guidance: "Add GTIN to product metafields and expose in JSON-LD."
    estimated_effort: "1 sprint"
```

---

### D-UCP3: Metafield Coverage
```
total_products_sampled: 5
coverage_by_attribute:
  color: 1.0          # color is a variant axis — present as variant option, NOT as additionalProperty
  size: 1.0           # same — variant axis, not additionalProperty  
  material: 0.0       # not in JSON-LD additionalProperty on any sampled product
  brand: 0.0          # not in additionalProperty
  gtin: 0.0           # not in additionalProperty

# IMPORTANT NOTE FOR CODEX:
# color and size appear in variant.option_values, NOT in additionalProperty.
# D-UCP3 scores additionalProperty coverage specifically, because that is
# what AI agents consume for attribute-based filtering.
# Variant axis presence ≠ additionalProperty presence.
# Therefore effective coverage for agent filtering is:
critical_gaps: ["material", "brand", "gtin", "color", "size"]  
# all 0.0 in additionalProperty even though color/size exist as variant axes

worst_product_types: ["Maternity Dresses"]  # entire collection affected

dimension_score: 10
status: "warning"
findings:
  - finding_id: "UCP3-001"
    severity: "blocking"
    description: "No products expose attributes in JSON-LD additionalProperty. 
                  Agents filtering 'maternity dress in medium, cotton' will return 
                  zero results for this store."
    affected_count: 5
    fix_guidance: "Map Shopify variant options (size, color) and product metafields 
                   (material, fabric) to JSON-LD additionalProperty array."
    estimated_effort: "1 sprint"
```

---

### D-UCP4: Taxonomy Consistency
```
# From HTTP fetch, visible product_type values on collection page:
# "Maternity Dresses", "Maternity Swimwear" — but individual product JSON-LD
# product_type field is likely "Maternity" or blank (Shopify default behavior)

unique_raw_values: ["Maternity Dresses", "Maternity", ""]   # expected across sample
duplicate_clusters: []                                        # no exact duplicates in small sample
shallow_categories: ["Maternity", "Maternity Dresses"]       # depth < 3 levels
consistency_score: 40

dimension_score: 40
status: "warning"
findings:
  - finding_id: "UCP4-001"
    severity: "warning"
    description: "Product taxonomy depth is 1-2 levels. Google Product Taxonomy 
                  requires depth ≥ 3 for proper agent faceting. 
                  'Maternity Dresses' should be 
                  'Apparel & Accessories > Clothing > Dresses'."
    affected_count: 5
    fix_guidance: "Set Google Product Category on all products via Shopify admin 
                   (Products > [product] > Google product category field)."
    estimated_effort: "2-4 hours (bulk update via CSV)"
  - finding_id: "UCP4-002"
    severity: "warning"
    description: "Inconsistent product_type values detected: 'Maternity Dresses', 
                  'Maternity', and blank values found across sample."
    fix_guidance: "Standardize product_type field via Shopify bulk editor."
    estimated_effort: "1 hour"
```

---

### D-UCP5: Variant Fidelity
```
products_with_variants_sampled: 5
collapsed_offers_count: 0      # Shopify exposes per-variant offers correctly in JSON-LD
missing_sku_count: 0           # Shopify variant SKUs present (may be auto-generated)
missing_availability_count: 0  # availability string present per variant

# CRITICAL FINDING — not a structural collapse but a semantic delta:
# JSON-LD offers.price = $268.00 (full price)
# Human-visible price = "$268.00 — 25% OFF IN CART"
# Agent will quote $268.00 to users. Actual checkout price = $201.00.
# This is not a missing field — it is a price integrity issue.

fidelity_score: 75
dimension_score: 75
status: "warning"
findings:
  - finding_id: "UCP5-001"
    severity: "warning"
    description: "In-cart discounts (25% OFF IN CART) are not reflected in 
                  JSON-LD offers.price. AI agents will quote full price to users 
                  ($268.00) but actual checkout price is ~$201.00. 
                  This creates a trust gap in agent-led transactions."
    affected_count: 5
    fix_guidance: "Either: (a) Apply sale price directly to offers.price in JSON-LD, 
                   or (b) Add priceValidUntil and discount metadata so agents 
                   can surface the correct effective price."
    estimated_effort: "1 sprint (theme + pricing logic change)"
```

---

### D-UCP6: Policy Readability
```
structured_shipping_found: false     # No shippingDetails in JSON-LD
return_period_machine_readable: false # returns.hatchcollection.com — returns are 
                                      # processed via separate portal, no numeric 
                                      # return window in structured data
currency_is_iso4217: true            # USD is valid ISO 4217 — present in offers.priceCurrency
policy_page_http_accessible: true    # returns.hatchcollection.com returns 200 via HTTP

readability_score: 50   # 2 of 4 checks pass
dimension_score: 50
status: "warning"
findings:
  - finding_id: "UCP6-001"
    severity: "warning"
    description: "No shippingDetails in JSON-LD offers. AI agents cannot answer 
                  'how long will this take to arrive?' without structured shipping data."
    fix_guidance: "Add JSON-LD shippingDetails with shippingRate and 
                   deliveryTime (minValue/maxValue in days)."
    estimated_effort: "2 hours"
  - finding_id: "UCP6-002"
    severity: "warning"
    description: "Return period not machine-readable. Returns handled via 
                  separate portal (returns.hatchcollection.com) with no 
                  structured return window in product JSON-LD."
    fix_guidance: "Add merchantReturnPolicy to JSON-LD offers with 
                   returnPolicyCategory and merchantReturnDays."
    estimated_effort: "2 hours"
```

---

### D-UCP7: Agent-View Delta
```
# Agent mode: HTTP-only, JSON-LD + meta tags extracted, no JS execution
# Human mode: Full browser render

url: "https://www.hatchcollection.com/products/the-camilla-dress"  # sample product

agent_extracted:
  name: "The Camilla Dress"
  price: "268.00"
  currency: "USD"
  availability: "InStock"
  description: "[product description from JSON-LD]"
  additionalProperties: []      # EMPTY — key delta
  
human_visible:
  name: "The Camilla Dress"
  price: "268.00"
  sale_messaging: "25% OFF IN CART"   # agent cannot see this
  effective_price: "~201.00"          # agent cannot see this
  size_options: ["XS", "S", "M", "L", "XL", "PETITE"]   # agent cannot see these as structured data
  color_options: ["White", "..."]     # agent cannot see these as structured data
  
missing_in_agent_view:
  - "sale_messaging"       # 25% OFF IN CART not in JSON-LD
  - "effective_price"      # actual cart price not exposed
  - "size_options_structured"    # sizes visible in DOM but not in additionalProperty
  - "color_options_structured"   # colors visible in DOM but not in additionalProperty
  - "material"             # visible in product description prose but not structured
  
agent_only_signals: []     # nothing in JSON-LD that isn't also in DOM

fidelity_score: 0.45       # significant delta — agent missing key commerce signals

dimension_score: 35
status: "warning"
findings:
  - finding_id: "UCP7-001"
    severity: "blocking"
    description: "Agent view missing effective price. Agent sees $268, 
                  user pays ~$201. This is the most likely cause of agent 
                  transaction abandonment."
    fix_guidance: "Align JSON-LD price with actual transaction price."
  - finding_id: "UCP7-002"
    severity: "warning"
    description: "Size and color options visible in DOM but absent from 
                  JSON-LD additionalProperty. Agent cannot filter by these attributes."
    fix_guidance: "Expose variant options as additionalProperty in JSON-LD."
```

---

## Final Compliance Report (Asserted Values)

```python
UCPComplianceReport(
    domain = "hatchcollection.com",
    overall_score = 30,            # hard gate applied — D-UCP1 = 0
    d_ucp1_gate_applied = True,
    
    dimension_scores = [
        UCPDimensionScore("D-UCP1", score=0,  status="fail",    weight=0.20),
        UCPDimensionScore("D-UCP2", score=55, status="warning", weight=0.15),
        UCPDimensionScore("D-UCP3", score=10, status="warning", weight=0.15),
        UCPDimensionScore("D-UCP4", score=40, status="warning", weight=0.10),
        UCPDimensionScore("D-UCP5", score=75, status="warning", weight=0.15),
        UCPDimensionScore("D-UCP6", score=50, status="warning", weight=0.10),
        UCPDimensionScore("D-UCP7", score=35, status="warning", weight=0.15),
    ],
    
    total_findings = 10,
    blocking_findings = 2,    # UCP1-001, UCP3-001
    warning_findings = 8,
)

# Weighted score without gate: (0×0.20)+(55×0.15)+(10×0.15)+(40×0.10)+(75×0.15)+(50×0.10)+(35×0.15)
# = 0 + 8.25 + 1.5 + 4.0 + 11.25 + 5.0 + 5.25 = 35.25
# Gate fires (D-UCP1=0): min(35.25, 30) = 30 ✓
```

---

## Pytest Assertions for Codex

```python
# tests/services/ucp_audit/test_e2e_hatch.py
# Run ONLY after all slices 1-2F are complete and verified individually.

import pytest
from app.services.ucp_audit.scoring import UCPComplianceReport

@pytest.fixture
def hatch_report():
    # Run actual audit against hatchcollection.com with sample_size=5
    # This is an integration test — requires network access
    return run_ucp_audit("hatchcollection.com", sample_size=5)

def test_d_ucp1_manifest_not_found(hatch_report):
    d1 = get_dimension(hatch_report, "D-UCP1")
    assert d1.score == 0
    assert d1.status == "fail"
    assert any("manifest" in f.description.lower() for f in d1.findings)

def test_hard_gate_applied(hatch_report):
    assert hatch_report.d_ucp1_gate_applied is True
    assert hatch_report.overall_score <= 30

def test_d_ucp2_jsonld_present_but_incomplete(hatch_report):
    d2 = get_dimension(hatch_report, "D-UCP2")
    assert d2.score > 0          # JSON-LD exists on product pages
    assert d2.score < 80         # but incomplete (missing brand, gtin, additionalProperty)
    assert d2.status == "warning"

def test_d_ucp3_additionalproperties_empty(hatch_report):
    d3 = get_dimension(hatch_report, "D-UCP3")
    assert d3.score <= 15        # near-zero additionalProperty coverage
    assert "material" in get_critical_gaps(d3)

def test_d_ucp5_in_cart_discount_finding(hatch_report):
    d5 = get_dimension(hatch_report, "D-UCP5")
    # Variants present so score should be moderate
    assert d5.score > 50
    # But in-cart discount issue should be flagged
    finding_descriptions = [f.description.lower() for f in d5.findings]
    assert any("cart" in d or "discount" in d or "price" in d for d in finding_descriptions)

def test_d_ucp6_currency_pass_shipping_fail(hatch_report):
    d6 = get_dimension(hatch_report, "D-UCP6")
    assert d6.score >= 40        # currency + policy page pass
    assert d6.score <= 60        # but shipping + return window fail
    assert d6.status == "warning"

def test_d_ucp7_fidelity_below_threshold(hatch_report):
    d7 = get_dimension(hatch_report, "D-UCP7")
    assert d7.score < 60         # significant delta expected
    assert any("price" in f.description.lower() for f in d7.findings)

def test_total_findings_count(hatch_report):
    assert len(hatch_report.all_findings) >= 8
    blocking = [f for f in hatch_report.all_findings if f.severity == "blocking"]
    assert len(blocking) >= 1    # at minimum UCP1-001

def test_overall_score_range(hatch_report):
    assert 25 <= hatch_report.overall_score <= 30  # gate applied, reasonable base
```

---

## Debugging Sequence for Codex

If the audit returns unexpected results, debug in this order:

**Problem: overall_score > 30 despite D-UCP1 failing**  
→ Hard gate not implemented in `scoring.py`. Check: `if d_ucp1.score == 0: overall = min(overall, config.D_UCP1_GATE_MAX_SCORE)`

**Problem: D-UCP1 score not 0 (manifest "found" when it shouldn't be)**  
→ `discovery.py` not correctly handling 404. Check: 404 response → `manifest_found=False`, `score=0`

**Problem: D-UCP3 score high despite empty additionalProperty**  
→ `catalog_checks.py` is counting variant option values (color/size) as additionalProperty. Fix: only score `additionalProperty` array from JSON-LD, not variant axes.

**Problem: D-UCP2 score = 0 (JSON-LD not found)**  
→ `product_schema.py` is running on the collection URL, not product URLs. Fix: audit must sample individual product PDPs (e.g. `/products/the-camilla-dress`), not the collection listing page.

**Problem: D-UCP7 fidelity_score = 1.0 (no delta detected)**  
→ Agent mode and human mode are using the same acquisition path. Check: agent mode must be HTTP-only structured data; human mode must use browser. Verify two different code paths are being called.

**Problem: D-UCP6 policy_page_accessible = false**  
→ `returns.hatchcollection.com` is a separate domain — HTTP fetch must allow cross-domain policy URL, not restrict to base domain. Check orchestrator policy URL resolution logic.
```