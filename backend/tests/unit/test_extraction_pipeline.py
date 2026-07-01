from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.browser_block_detection import classify_blocked_page
from app.acquisition.browser_listing_visual import listing_visual_elements_html
from app.acquisition.browser_result_builder import build_browser_artifacts
from app.acquisition.runtime_plan import AcquisitionIntent
from app.acquisition.source_capabilities import build_source_capability_diagnostics
from app.extraction import Surface, extract
from app.extraction.pipeline import _only_slug_identity
from app.extraction.contracts import CommerceDetailRecord, ExtractionRequest
from app.extraction.contracts import Evidence
from app.core.config.extraction_rules import MAX_EVIDENCE_PER_SOURCE_OBJECT
from app.extraction.replay import (
    fixture_request_from_inputs,
    request_from_acquisition_result,
)

pytestmark = pytest.mark.unit


HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Trail Shoe",
  "brand": {"@type": "Brand", "name": "Invoro"},
  "description": "A durable trail shoe for long-distance runs.",
  "sku": "TS-1",
  "url": "https://shop.test/products/trail-shoe",
  "image": ["https://shop.test/i/trail.jpg"],
  "offers": {
    "@type": "Offer",
    "price": "129",
    "priceCurrency": "usd",
    "availability": "https://schema.org/InStock"
  },
  "hasVariant": [
    {"@type": "Product", "sku": "TS-1-BLK-9", "color": "Black", "size": "9"}
  ]
}
</script>
</head>
<body><main><h1>Trail Shoe</h1></main></body>
</html>
"""


def _extract(
    surface: str,
    html: str,
    page_url: str,
    *,
    max_records: int = 1,
    artifacts: dict[str, object] | None = None,
    network_payloads: tuple[dict[str, object], ...] = (),
    requested_fields: tuple[str, ...] = (),
):
    return extract(
        fixture_request_from_inputs(
            Surface(surface),
            html,
            page_url,
            max_records=max_records,
            artifacts=artifacts,
            network_payloads=network_payloads,
            requested_fields=requested_fields,
        )
    )


def _price_repair_facts(result, rule_id: str):
    return tuple(
        fact
        for fact in result.derived_facts
        if fact.fact_type == "offer.price" and fact.rule_id == rule_id
    )


def test_active_provider_shell_without_product_identity_is_blocked() -> None:
    marker = "px-captcha"
    classification = classify_blocked_page(
        f"<html><body><div id='{marker}'>{marker}</div></body></html>",
        200,
    )

    assert classification.blocked is True
    assert classification.outcome == "challenge_page"
    assert marker in classification.active_provider_hits


def test_js_state_source_object_evidence_budget_is_reported() -> None:
    image_urls = [
        f"https://cdn.shop.test/images/trail-shoe-{index}.jpg"
        for index in range(MAX_EVIDENCE_PER_SOURCE_OBJECT + 25)
    ]
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            "<html><body><h1>Trail Shoe</h1></body></html>",
            "https://shop.test/products/trail-shoe",
            artifacts={
                "js_state_objects": {
                    "name": "Trail Shoe",
                    "sku": "TS-1",
                    "url": "https://shop.test/products/trail-shoe",
                    "images": image_urls,
                }
            },
        )
    )

    budget_outcomes = [
        row
        for row in result.collector_outcomes
        if row.collector_id == "js_state" and row.outcome == "budget_limited"
    ]
    assert budget_outcomes
    assert "evidence_per_source_object_budget_exhausted" in str(
        budget_outcomes[0].detail
    )
    assert "assets" in budget_outcomes[0].dropped_fact_families
    assert budget_outcomes[0].dropped_source_paths
    assert (
        sum(1 for row in result.evidence if row.collector_id == "js_state")
        <= MAX_EVIDENCE_PER_SOURCE_OBJECT
    )


def test_js_state_source_object_budget_is_reported(monkeypatch) -> None:
    from app.extraction.collectors import js_state

    monkeypatch.setattr(js_state, "MAX_SOURCE_OBJECTS_PER_ARTIFACT", 2)
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            "<html><body><h1>Trail Shoe</h1></body></html>",
            "https://shop.test/products/trail-shoe",
            artifacts={
                "js_state_objects": {
                    "products": [
                        {"name": "Trail Shoe", "sku": "TS-1"},
                        {"name": "Trail Shoe Blue", "sku": "TS-2"},
                        {"name": "Trail Shoe Red", "sku": "TS-3"},
                    ]
                }
            },
        )
    )

    budget_outcomes = [
        row
        for row in result.collector_outcomes
        if row.collector_id == "js_state" and row.outcome == "budget_limited"
    ]
    assert budget_outcomes
    assert "source_object_budget_exhausted" in str(budget_outcomes[0].detail)


def test_active_provider_marker_does_not_hide_product_identity() -> None:
    marker = "px-captcha"
    classification = classify_blocked_page(
        f"""
        <html>
          <head>
            <script type="application/ld+json">
            {{
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Trail Shoe"
            }}
            </script>
          </head>
          <body>
            <main><h1>Trail Shoe</h1></main>
            <div>{marker}</div>
          </body>
        </html>
        """,
        200,
    )

    assert classification.blocked is False
    assert classification.outcome == "ok"


def test_blocked_capture_does_not_publish_public_records() -> None:
    marker = "px-captcha"
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        f"""
        <script type="application/ld+json">
        {{"@context":"https://schema.org","@type":"Product","name":"Blocked Widget","url":"https://shop.test/products/challenge-shell"}}
        </script>
        <html><body><div data-description='{marker}'>{marker}</div></body></html>
        """,
        "https://shop.test/products/challenge-shell",
    )
    blocked_capture = request.capture.model_copy(
        update={
            "blocked": True,
            "acquisition_outcome": "challenge_page",
            "browser_attempted": True,
        }
    )

    result = extract(request.model_copy(update={"capture": blocked_capture}))

    assert result.verdict == "blocked"
    assert result.records == ()
    assert result.evidence == ()
    assert len(result.evidence_dispositions) == len(result.evidence)
    assert any(
        finding.rule_id == "ACQUISITION_BLOCKED" and finding.blocking
        for finding in result.findings
    )


def test_weak_brand_token_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Mostro Ecstasy Sneakers",
          "brand": "green",
          "description": "A complete product description for a low-profile sneaker.",
          "image": "https://shop.test/images/mostro.jpg",
          "url": "https://shop.test/products/mostro-ecstasy"
        }
        </script>
        """,
        "https://shop.test/products/mostro-ecstasy",
    )

    assert result.records
    assert result.records[0].get("brand") is None
    assert result.verdict in {"partial", "review"}


def test_product_name_cannot_be_published_as_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Millennium Falcon",
          "brand": "Millennium Falcon",
          "description": "A detailed building set description for collectors.",
          "image": "https://shop.test/images/millennium-falcon.jpg",
          "url": "https://shop.test/products/millennium-falcon"
        }
        </script>
        """,
        "https://shop.test/products/millennium-falcon",
    )

    assert result.records
    assert result.records[0].get("brand") is None


def test_valid_multiword_brand_is_preserved() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Curve Wide Leg Pants",
          "brand": "ASOS DESIGN",
          "description": "Wide-leg pants with a structured drape and soft finish.",
          "image": "https://shop.test/images/curve-pants.jpg",
          "url": "https://shop.test/products/curve-wide-leg-pants"
        }
        </script>
        """,
        "https://shop.test/products/curve-wide-leg-pants",
    )

    assert result.records[0]["brand"] == "ASOS DESIGN"


def test_ellipsis_description_is_rejected_when_complete_evidence_exists() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <meta name="description" content="Complete product description with three durable balls supplied in protective tubes.">
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Padel Balls",
            "brand": "KUIKMA",
            "description": "This tri-pack contains 3 tubes of 3...",
            "image": "https://shop.test/images/padel-balls.jpg",
            "url": "https://shop.test/products/padel-balls"
          }
          </script>
        </head>
        """,
        "https://shop.test/products/padel-balls",
    )

    assert result.records
    assert result.records[0]["description"].startswith("Complete product description")


def test_product_url_can_recover_brand_prefix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Structured Commuter Backpack",
          "description": "A structured commuter backpack with padded storage.",
          "image": "https://shop.test/images/commuter-backpack.jpg",
          "url": "https://shop.test/products/calvin-klein-structured-commuter-backpack"
        }
        </script>
        """,
        "https://shop.test/products/calvin-klein-structured-commuter-backpack",
    )

    assert result.records[0]["brand"] == "Calvin Klein"


def test_product_jsp_endpoint_title_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>product.jsp</h1></main>",
        "https://shop.test/catalog/product.jsp?id=12345",
    )

    assert not result.records or result.records[0].get("title") != "product.jsp"
    assert result.verdict != "success"


def test_truncated_comma_fragment_description_loses_to_complete_copy() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <meta name="description" content="Modern, effortless bedding made from breathable cotton for everyday comfort.">
          <script type="application/ld+json">
          {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Classic Duvet Cover",
            "brand": "Brooklinen",
            "description": "Modern, effor",
            "image": "https://shop.test/images/duvet-cover.jpg",
            "url": "https://shop.test/products/classic-duvet-cover"
          }
          </script>
        </head>
        """,
        "https://shop.test/products/classic-duvet-cover",
    )

    assert result.records[0]["description"].startswith("Modern, effortless bedding")


@pytest.mark.parametrize(
    ("url", "title", "description", "image", "bad_brand", "expected"),
    [
        (
            "https://ar.puma.com/pd/zapatillas-mostro/397328.html",
            "Zapatillas Mostro Ecstasy unisex",
            "PUMA Mostro heritage sneaker.",
            "https://images.puma.com/397328.png",
            "green",
            "PUMA",
        ),
        (
            "https://www.aesop.com/candles/aganice/HM03.html",
            "Aganice Aromatique Candle",
            "Aesop home fragrance candle.",
            "https://www.aesop.com/images/Aesop_Aganice.jpg",
            "Fragrance",
            "Aesop",
        ),
        (
            "https://www.usa.canon.com/shop/p/eos-r5",
            "EOS R5 Body",
            "Canon full-frame camera body.",
            "https://s7d1.scene7.com/is/image/canon/eos-r5",
            "Register",
            "Canon",
        ),
        (
            "https://www.maccosmetics.com/product/eye-shadow",
            "Eye Shadow",
            "Highly pigmented pressed eye shadow.",
            "https://www.maccosmetics.com/media/eye-shadow.jpg",
            "& More",
            "Mac",
        ),
        (
            "https://www.karenmillen.com/product/cotton-trouser",
            "Cotton Utility Button Detail Trouser",
            "Karen Millen tailored trouser.",
            "https://media.karenmillen.com/trouser.jpg",
            "Karen",
            "Karen Millen",
        ),
        (
            "https://www.phase-eight.com/product/lucinda-dress.html",
            "Lucinda Spot Midi Dress",
            "Phase Eight occasion dress.",
            "https://www.phase-eight.com/images/lucinda.jpg",
            "Phase",
            "Phase Eight",
        ),
        (
            "https://www.calvinklein.us/bags/structured-commuter-bag.html",
            "Structured Commuter Bag",
            "Calvin Klein commuter bag.",
            "https://calvinklein.scene7.com/is/image/CalvinKlein/bag",
            "Calvin",
            "Calvin Klein",
        ),
        (
            "https://www.asos.com/asos-curve/asos-design-curve-pants/prd/1",
            "ASOS DESIGN Curve Pants",
            "ASOS DESIGN curve pants.",
            "https://images.asos-media.com/products/asos-design-curve-pants/1.jpg",
            "ASOS",
            "ASOS DESIGN",
        ),
        (
            "https://www.williams-sonoma.com/products/breville-the-bambino-plus/",
            "Breville Bambino Plus Espresso Machine",
            "Breville Bambino Plus espresso machine.",
            "https://assets.wsimgs.com/breville-bambino.jpg",
            "Breville Bambino",
            "Breville",
        ),
        (
            "https://www.firstcry.com/babyhug/babyhug-denim-top/1/product-detail",
            "Babyhug Denim Woven Sleeveless Top",
            "Babyhug denim top for children.",
            "https://cdn.test/babyhug-denim.jpg",
            "at",
            "Babyhug",
        ),
        (
            "https://www.therevolverclub.com/products/technics-sl-1200mk7",
            "Technics SL-1200MK7 Turntable",
            "Technics direct-drive turntable.",
            "https://cdn.test/technics-sl1200.jpg",
            "India | The",
            "Technics",
        ),
        (
            "https://www.lego.com/product/millennium-falcon-75192",
            "Millennium Falcon",
            "Travel the LEGO galaxy.",
            "https://www.lego.com/images/75192.png",
            "Millennium Falcon",
            "Lego",
        ),
        (
            "https://www.balmainbeauty.com/fragrance/carbone",
            "Carbone Eau de Parfum",
            "Balmain musk fragrance.",
            "https://www.balmainbeauty.com/images/carbone.png",
            "Fragrance",
            "Balmain",
        ),
    ],
)
def test_page_identity_replaces_known_weak_or_partial_brand_shapes(
    url: str,
    title: str,
    description: str,
    image: str,
    bad_brand: str,
    expected: str,
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"""
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "Product",
          "name": {json.dumps(title)},
          "brand": {json.dumps(bad_brand)},
          "description": {json.dumps(description)},
          "image": {json.dumps(image)},
          "url": {json.dumps(url)}
        }}
        </script>
        """,
        url,
    )

    assert result.records[0]["brand"].casefold() == expected.casefold()


def test_materializes_once_with_lineage_and_quality() -> None:
    result = _extract(
        "ecommerce_detail",
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "Invoro"
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert result.verdict == "success"
    assert record["_lineage"]["price"]["derived_fact_id"]
    assert record["_field_sources"]["title"] == ["jsonld"]
    assert record["_field_sources"]["price"] == ["jsonld"]
    assert result.evidence
    assert "selected" not in record["variants"][0]


def test_missing_default_contract_field_cannot_report_clean_success() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trail Shoe",
          "brand": "Invoro",
          "url": "https://shop.test/products/trail-shoe",
          "image": "https://shop.test/i/trail.jpg",
          "offers": {"price": "129", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )

    assert result.verdict == "partial"
    assert any(
        finding.rule_id == "MISSING_CONTRACT_FIELD"
        and finding.metadata.get("field") == "description"
        for finding in result.findings
    )


def test_detail_contract_reports_selected_record_completeness() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Loco Bag",
          "url": "https://shop.test/products/loco-bag"
        }
        </script>
        """,
        "https://shop.test/products/loco-bag",
    )

    assert result.records
    assert result.verdict == "partial"
    assert result.metrics.completeness_score == pytest.approx(0.4)
    missing_fields = {
        finding.metadata.get("field")
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
    }
    assert missing_fields == {"brand", "description", "image_url"}
    completeness = next(
        finding
        for finding in result.findings
        if finding.rule_id == "RECORD_COMPLETENESS"
    )
    assert completeness.metadata["missing_fields"] == (
        "brand",
        "description",
        "image_url",
    )


def test_sellable_offer_requires_atomic_price_and_currency_contract() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Complete Product",
          "brand": "Invoro",
          "description": "A complete product description with durable materials.",
          "image": "https://shop.test/i/complete.jpg",
          "url": "https://shop.test/products/complete",
          "offers": {"price": "49"}
        }
        </script>
        """,
        "https://shop.test/products/complete",
    )

    assert result.verdict == "partial"
    missing_fields = {
        finding.metadata.get("field")
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
    }
    assert {"price", "currency"} <= missing_fields


def test_explicit_visible_product_brand_label_is_collected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Classic Slip-On Shoe</h1>
          <div class="product-brand">Brand: Vans</div>
          <img data-product-image src="https://shop.test/i/slip-on.jpg">
          <div data-price="65"></div>
          <div data-currency="USD"></div>
        </main>
        """,
        "https://shop.test/products/classic-slip-on-shoe",
    )

    assert result.records[0]["brand"] == "Vans"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Vans"
        and row.collector_id == "dom"
        for row in result.evidence
    )


def test_designed_by_data_attribute_recovers_product_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Luna Leather Bag</h1>
          <span data-designer-name="3.1 Phillip Lim"></span>
          <img data-product-image src="https://shop.test/i/luna.jpg">
        </main>
        """,
        "https://shop.test/products/luna-leather-bag",
    )

    assert result.records[0]["brand"] == "3.1 Phillip Lim"


def test_jsonld_manufacturer_name_alias_recovers_nested_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Cinema Camera",
          "manufacturerName": "Sony",
          "url": "https://shop.test/products/cinema-camera",
          "image": "https://shop.test/i/camera.jpg"
        }
        </script>
        """,
        "https://shop.test/products/cinema-camera",
    )

    assert result.records[0]["brand"] == "Sony"


def test_registered_title_marker_recovers_product_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Acme® Trail Shoe</h1>
          <img data-product-image src="https://shop.test/i/trail.jpg">
        </main>
        """,
        "https://shop.test/products/acme-trail-shoe",
    )

    assert result.records[0]["brand"] == "Acme®"
    assert not any(
        row.fact_type == "product.brand"
        and row.metadata.get("derived_by") == "brand_from_title_marker"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Acme®"
        and row.rule_id == "brand_from_title_marker"
        for row in result.derived_facts
    )


def test_jsonld_brand_reference_url_is_not_public_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Basin Convertible Pants",
          "brand": {
            "@type": "Brand",
            "@id": "https://shop.test/en-us#brand"
          },
          "url": "https://shop.test/products/basin-convertible-pants",
          "offers": {"price": "130", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/basin-convertible-pants",
    )

    assert result.records
    assert result.records[0].get("brand") is None
    assert all(
        evidence.value != "https://shop.test/en-us#brand"
        or "brand_url" in evidence.flags
        for evidence in result.evidence
        if evidence.fact_type == "product.brand"
    )


def test_ecommerce_detail_homepage_does_not_materialize_promotional_product() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>All Mens Sale</h1>
          <img src="https://cdn.shop.test/promotions/sale-card.jpg">
          <button>Leggings Size Guide</button>
        </main>
        """,
        "https://shop.test/",
    )

    assert result.records == ()


def test_apostrophe_prefixed_numeric_brand_is_normalized_before_resolution() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "47 NY Yankees Clean Up Cap",
          "brand": {"@type": "Brand", "name": "'47"},
          "url": "https://retailer.test/products/47-yankees-clean-up-cap"
        }
        </script>
        """,
        "https://retailer.test/products/47-yankees-clean-up-cap",
    )

    assert result.records[0]["brand"] == "47"


def test_ecommerce_detail_locale_root_does_not_materialize_embedded_products() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/json">
        {
          "product": {
            "name": "NY Yankees Clean Up Cap",
            "price": "35",
            "currency": "USD",
            "variants": [
              {"variantId": "shoe", "sku": "U9929NF", "size": "UK 4 UK 5"}
            ]
          }
        }
        </script>
        """,
        "https://shop.test/us/",
    )

    assert result.records == ()
    assert result.verdict == "empty"


def test_jsonld_product_group_uses_shade_as_color_axis() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Eye Shadow",
      "url": "https://shop.test/products/eye-shadow",
      "hasVariant": [
        {
          "@type": "Product",
          "sku": "MY6RPE",
          "name": "Eye Shadow - Carbon - .05 oz / 1.5 g",
          "color": "Black",
          "size": ".05 oz / 1.5 g",
          "offers": {
            "@type": "Offer",
            "url": "https://shop.test/products/eye-shadow?shade=Carbon",
            "price": "25",
            "priceCurrency": "USD",
            "availability": "http://schema.org/InStock"
          }
        }
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/eye-shadow")
    assert result.records[0]["variants"] == [
        {
            "variant_id": "MY6RPE",
            "sku": "MY6RPE",
            "price": "25.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Carbon",
            "size": ".05 oz / 1.5 g",
        }
    ]


def test_gender_microdata_title_and_brand_as_variant_color_are_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        [
          {
            "@type":"ProductGroup",
            "name":"Nylon tank top - Barrow - Boys | Luisaviaroma",
            "brand":"Barrow",
            "url":"https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027",
            "offers":{"price":"7028","priceCurrency":"INR"}
          },
          {
            "@type":"Product",
            "isVariantOf":{"@id":"https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027"},
            "sku":"83I-UKD027-MDgw0-5610",
            "size":"8Y",
            "color":"Barrow",
            "offers":{"price":"7028","priceCurrency":"INR"}
          },
          {
            "@type":"Product",
            "isVariantOf":{"@id":"https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027"},
            "sku":"83I-UKD027-MDgw0-5612",
            "size":"12Y",
            "color":"Barrow",
            "offers":{"price":"7028","priceCurrency":"INR"}
          }
        ]
        </script>
        <span itemprop="name">Short-sleeved T-shirts</span>
        <main><h1>Barrow Nylon tank top</h1></main>
        """,
        "https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027",
    )

    record = result.records[0]
    assert record["title"] == "Barrow Nylon tank top"
    assert {row["size"] for row in record["variants"]} == {"8Y", "12Y"}
    assert all("color" not in row for row in record["variants"])


def test_internal_product_card_title_is_rejected_for_visible_product_heading() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/json">
        {"componentName":"Tread-Plus Product Card","description":"Internal CMS card"}
        </script>
        <main>
          <h1>Cross Training Tread</h1>
          <img src="https://cdn.shop.test/products/cross-training-tread-main.jpg">
        </main>
        """,
        "https://shop.test/shop/tread",
    )

    assert result.records[0]["title"] == "Cross Training Tread"


def test_jsonld_sibling_products_linked_to_group_materialize_as_variants() -> None:
    html = """
    <script type="application/ld+json">
    [
      {"@type":"ProductGroup","name":"Kids Tank Top","url":"https://shop.test/products/kids-tank","productGroupID":"TANK-1"},
      {"@type":"Product","IS_VARIANT_OF":{"@id":"https://shop.test/products/kids-tank"},"sku":"TANK-8","color":"Green","size":"8Y","offers":{"price":"70","priceCurrency":"USD","availability":"https://schema.org/InStock"}},
      {"@type":"Product","IS_VARIANT_OF":{"@id":"https://shop.test/products/kids-tank"},"sku":"TANK-12","color":"Green","size":"12Y","offers":{"price":"70","priceCurrency":"USD","availability":"https://schema.org/InStock"}}
    ]
    </script>
    """.replace("IS_VARIANT_OF", "is" + "VariantOf")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/kids-tank")

    assert result.records[0]["variants"] == [
        {
            "variant_id": "TANK-12",
            "sku": "TANK-12",
            "price": "70.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Green",
            "size": "12Y",
        },
        {
            "variant_id": "TANK-8",
            "sku": "TANK-8",
            "price": "70.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Green",
            "size": "8Y",
        },
    ]


def test_jsonld_one_axis_variants_with_child_offers_materialize() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Suede Sneakers",
      "url": "https://shop.test/products/suede",
      "hasVariant": [
        {
          "@type": "Product",
          "color": "Red",
          "offers": {"@type": "Offer", "price": "85", "priceCurrency": "USD"}
        },
        {
          "@type": "Product",
          "color": "Blue",
          "offers": {"@type": "Offer", "price": "80", "priceCurrency": "USD"}
        }
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/suede")
    assert result.records[0]["variants"] == [
        {"price": "80.00", "currency": "USD", "color": "Blue"},
        {"price": "85.00", "currency": "USD", "color": "Red"},
    ]


def test_js_state_image_dimensions_do_not_materialize_as_variants() -> None:
    artifacts = {
        "js_state_objects": {
            "images": [
                {"__typename": "ProductVariantImage", "width": 1206},
                {"__typename": "ProductVariantImage", "width": 4000},
            ],
            "variants": [
                {
                    "__typename": "ProductVariant",
                    "sku": "2775096",
                    "color": "Bissap Glaze",
                    "price": "24",
                    "currency": "USD",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Lip Balm</h1></body></html>",
        "https://shop.test/products/lip-balm",
        artifacts=artifacts,
    )
    assert result.records[0]["variants"] == [
        {
            "variant_id": "2775096",
            "sku": "2775096",
            "price": "24.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Bissap Glaze",
        }
    ]
    assert result.decisions


def test_identity_only_variant_with_inherited_currency_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type":"Product","name":"Cross Training Tread","url":"https://shop.test/products/tread","offers":{"priceCurrency":"USD"}}
        </script>
        """,
        "https://shop.test/products/tread",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Cross Training Tread",
                        "url": "https://shop.test/products/tread",
                        "currency": "USD",
                        "variants": [
                            {"id": "price-id-1"},
                            {"id": "price-id-2"},
                        ],
                    }
                }
            },
        ),
    )

    assert not result.records[0].get("variants")


def test_js_state_media_id_and_width_do_not_materialize_as_variant() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Lip Balm</h1></main>",
        "https://shop.test/products/lip-balm",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Lip Balm",
                    "url": "https://shop.test/products/lip-balm",
                    "price": 18,
                    "currency": "USD",
                    "media": [
                        {
                            "id": "33841425055989",
                            "width": 916,
                            "src": "https://cdn.shop.test/lip-balm.jpg",
                        }
                    ],
                }
            }
        },
    )

    assert not result.records[0].get("variants")
    assert all(row.fact_type != "variant.option.width" for row in result.evidence)


def test_responsive_layout_dimensions_do_not_materialize_as_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Rustic Cotton T-Shirt",
          "url": "https://shop.test/products/rustic-cotton-t-shirt",
          "offers": {"price": "14.90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/rustic-cotton-t-shirt",
        network_payloads=(
            {
                "body": {
                    "categories": [
                        {
                            "sdui": {
                                "responsiveLayouts": [
                                    {
                                        "id": "layout-card-1",
                                        "dimensions": {"width": 358, "height": 640},
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
        ),
    )

    assert result.records[0]["price"] == "14.90"
    assert not result.records[0].get("variants")


def test_jsonld_aggregate_offer_low_price_materializes() -> None:
    html = HTML.replace(
        '"@type": "Offer",\n    "price": "129",',
        '"@type": "AggregateOffer",\n    "lowPrice": "9.99",\n    "highPrice": "19.99",',
    )
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["price"] == "9.99"
    assert record["currency"] == "USD"


def test_jsonld_aggregate_offer_child_availability_materializes() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Bambino Plus",
          "url": "https://shop.test/products/bambino-plus",
          "image": "https://shop.test/bambino.jpg",
          "offers": {
            "@type": "AggregateOffer",
            "lowPrice": "499.95",
            "highPrice": "499.95",
            "priceCurrency": "USD",
            "offers": [
              {
                "@type": "Offer",
                "price": "499.95",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "sku": "1437371"
              },
              {
                "@type": "Offer",
                "price": "499.95",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "sku": "3302893"
              }
            ]
          }
        }
        </script>
        """,
        "https://shop.test/products/bambino-plus",
    )

    record = result.records[0]
    assert record["price"] == "499.95"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"


def test_extraction_request_has_no_artifact_payloads_field() -> None:
    assert "artifact_payloads" not in ExtractionRequest.model_fields


def test_listing_visual_capture_builds_extractable_html_artifact() -> None:
    product_url = "https://shop.test/p/classic-pants/SKU123.html"
    rows = [
        {"href": product_url, "ariaLabel": "View product"},
        {
            "href": product_url,
            "src": "https://shop.test/classic.jpg",
            "alt": "Classic Pants",
        },
        {"href": product_url, "text": "$42.95"},
    ]

    expected = listing_visual_elements_html(rows)
    artifacts = build_browser_artifacts(
        screenshot_path="",
        traversal_result=None,
        html="",
        rendered_html=None,
        rendered_listing_fragments=[],
        listing_visual_elements=rows,
    )

    assert artifacts["listing_visual_html"] == expected
    assert f'href="{product_url}"' in expected
    assert "Classic Pants" in expected
    assert "$42.95" in expected


def test_runtime_capture_bundle_uses_acquisition_metadata() -> None:
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url="https://shop.test/products/trail-shoe",
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url="https://shop.test/products/trail-shoe",
        html=HTML,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url="https://shop.test/products/trail-shoe",
        max_records=1,
    )
    assert request.capture.run_id == 42
    assert request.capture.http_status == 200
    assert request.capture.acquisition_method == "browser"
    assert request.capture.browser_attempted is True
    assert request.capture.acquisition_outcome == "ok"
    assert all(
        not artifact.storage_uri.startswith("memory://")
        for artifact in request.capture.artifacts
    )


def test_runtime_request_marks_active_selector_fields_as_user_controlled() -> None:
    url = "https://shop.test/products/trail-shoe"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html=HTML,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
        selector_rules=[
            {
                "field_name": "Product.Title",
                "css_selector": "h1",
                "is_active": True,
            },
            {
                "field_name": "price",
                "css_selector": ".price",
                "is_active": False,
            },
        ],
    )

    assert request.user_controlled_fields == ("product.title",)


def test_active_provider_shell_is_blocked_when_building_runtime_capture() -> None:
    url = "https://shop.test/products/challenge-shell"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=44,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="<html><body><div id='px-captcha'>px-captcha</div></body></html>",
        method="browser",
        status_code=307,
        blocked=False,
        browser_diagnostics={
            "browser_attempted": True,
            "browser_outcome": "usable_content",
            "challenge_evidence": [
                "provider:perimeterx",
                "provider:px-captcha",
                "active_provider:px-captcha",
            ],
            "challenge_provider_hits": ["perimeterx", "px-captcha"],
            "readiness_probes": [{"is_ready": False}],
        },
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
    )
    result = extract(request)

    assert request.capture.blocked is True
    assert result.records == ()
    assert result.verdict == "blocked"


def test_low_content_browser_shell_is_blocked_when_building_runtime_capture() -> None:
    url = "https://shop.test/products/low-content-shell"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=45,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="<html><body><div>Loading...</div></body></html>",
        method="browser",
        status_code=200,
        blocked=False,
        browser_diagnostics={
            "browser_attempted": True,
            "browser_outcome": "low_content_shell",
        },
    )

    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
    )

    assert request.capture.blocked is True
    assert extract(request).records == ()


def test_not_found_detail_does_not_publish_url_only_fallback_record() -> None:
    url = "https://shop.test/p/poppi-prebiotic-soda/-/A-88886187"
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=43,
            url=url,
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url=url,
        html="<main><div>Product Grid</div></main>",
        method="browser",
        status_code=404,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url=url,
        max_records=1,
    )

    result = extract(request)

    assert result.records == ()


def test_evidence_is_immutable() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    item = result.evidence[0]
    try:
        item.value = "changed"  # type: ignore[misc]
    except (ValidationError, TypeError):
        pass
    assert isinstance(item, Evidence)
    assert item.value != "changed"


def test_offer_price_without_currency_is_not_published() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/trail-shoe")
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert "price" not in public
    assert "currency" not in public
    assert "PRICE_WITHOUT_CURRENCY" in {finding.rule_id for finding in result.findings}


def test_offer_price_inherits_currency_from_locale_path_segment() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "").replace(
        "https://shop.test/products/trail-shoe",
        "https://shop.test/en-in/products/trail-shoe",
    )
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/en-in/products/trail-shoe"
    )
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert public.get("price") == "129.00"
    assert public.get("currency") == "INR"
    assert not any(
        row.metadata.get("derived_by") == "currency_from_page_url_hint"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "offer.currency"
        and row.value == "INR"
        and row.rule_id == "currency_from_page_url_hint"
        for row in result.derived_facts
    )


def test_offer_price_inherits_currency_from_cctld() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "").replace(
        "https://shop.test/products/trail-shoe",
        "https://shop.co.in/products/trail-shoe",
    )
    result = _extract(
        "ecommerce_detail", html, "https://shop.co.in/products/trail-shoe"
    )
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert public.get("price") == "129.00"
    assert public.get("currency") == "INR"


def test_uncorroborated_cent_magnitude_price_is_not_silently_repaired() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "name": "Runner Tee",
                    "url": "https://shop.test/products/runner-tee",
                    "price": "3499",
                    "currency": "USD",
                }
            },
        ),
    )
    assert result.records[0]["price"] == "3499.00"
    assert result.records[0]["currency"] == "USD"


def test_explicit_usd_minor_unit_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Road Hoodie</h1></main>",
        "https://shop.test/products/road-hoodie",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Road Hoodie",
                        "url": "https://shop.test/products/road-hoodie",
                        "priceInCents": 13875,
                        "currency": "USD",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "138.75"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "138.75" for fact in facts)
    assert any(
        item.fact_type == "offer.price"
        and item.raw_value == 13875
        and "explicit_minor_unit_price" not in item.flags
        for item in result.evidence
    )


def test_explicit_inr_minor_unit_variant_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Jacket</h1></main>",
        "https://shop.test/products/studio-jacket",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Studio Jacket",
                    "url": "https://shop.test/products/studio-jacket",
                    "variants": [
                        {
                            "variantId": "black-m",
                            "sku": "STUDIO-BLK-M",
                            "size": "M",
                            "priceInPaise": 2820000,
                            "currency": "INR",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["price"] == "28200.00"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "28200.00" for fact in facts)
    assert any(
        item.fact_type == "offer.price" and item.raw_value == 2820000 and not item.flags
        for item in result.evidence
    )


def test_nested_variant_minor_unit_price_is_converted_to_major_units() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Road Hoodie</h1></main>",
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "priceInfo": {
                                "priceInCents": 13875,
                                "currencyCode": "USD",
                            },
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["price"] == "138.75"
    facts = _price_repair_facts(result, "explicit_minor_unit_price")
    assert any(fact.value == "138.75" for fact in facts)
    assert any(
        item.fact_type == "offer.price"
        and item.raw_value == 13875
        and item.locator.value.endswith("/priceInCents")
        and not item.flags
        for item in result.evidence
    )


def test_zero_decimal_currency_explicit_minor_key_is_not_divided() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Tokyo Jacket</h1></main>",
        "https://shop.test/products/tokyo-jacket",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Tokyo Jacket",
                        "url": "https://shop.test/products/tokyo-jacket",
                        "priceInCents": 13875,
                        "currency": "JPY",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "13875.00"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")


def test_decimal_major_unit_price_remains_unchanged() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Jacket</h1></main>",
        "https://shop.test/products/studio-jacket",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Studio Jacket",
                        "url": "https://shop.test/products/studio-jacket",
                        "price": "28200.50",
                        "currency": "INR",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "28200.50"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")
    assert not _price_repair_facts(result, "corroborated_price_scale")


def test_independent_parent_price_corroborates_variant_minor_unit_scale() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Road Hoodie",
          "url": "https://shop.test/products/road-hoodie",
          "offers": {"price": "138.75", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "price": 13875,
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "138.75"
    assert result.records[0]["variants"][0]["price"] == "138.75"
    facts = _price_repair_facts(result, "corroborated_price_scale")
    assert any(fact.value == "138.75" for fact in facts)
    repaired_evidence_ids = {
        evidence_id for fact in facts for evidence_id in fact.input_evidence_ids
    }
    assert any(
        item.evidence_id in repaired_evidence_ids
        and item.fact_type == "offer.price"
        and item.raw_value == 13875
        for item in result.evidence
    )


def test_parent_price_band_corroborates_different_variant_minor_unit_prices() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Luna Bag",
          "url": "https://shop.test/products/luna-bag",
          "offers": {"price": "59400", "priceCurrency": "INR"}
        }
        </script>
        """,
        "https://shop.test/products/luna-bag",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Luna Bag",
                    "url": "https://shop.test/products/luna-bag",
                    "variants": [
                        {
                            "variantId": "luna-small",
                            "sku": "LUNA-S",
                            "size": "S",
                            "price": 4170000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-medium",
                            "sku": "LUNA-M",
                            "size": "M",
                            "price": 5250000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-large",
                            "sku": "LUNA-L",
                            "size": "L",
                            "price": 5940000,
                            "currency": "INR",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "59400.00"
    assert {row["size"]: row["price"] for row in result.records[0]["variants"]} == {
        "S": "41700.00",
        "M": "52500.00",
        "L": "59400.00",
    }
    repaired_evidence_ids = {
        evidence_id
        for fact in _price_repair_facts(result, "corroborated_price_scale")
        for evidence_id in fact.input_evidence_ids
    }
    assert {
        item.raw_value
        for item in result.evidence
        if item.evidence_id in repaired_evidence_ids
    } >= {4170000, 5250000, 5940000}


def test_parent_currency_outranks_stray_dom_currency_for_variant_scale() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Luna Bag","url":"https://shop.test/products/luna-bag","offers":{"price":"59500","priceCurrency":"INR"}}
        </script>
        <main><h1>Luna Bag</h1><div class="price">USD 595.00</div></main>
        """,
        "https://shop.test/products/luna-bag",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Luna Bag",
                    "url": "https://shop.test/products/luna-bag",
                    "variants": [
                        {
                            "variantId": "luna-small",
                            "sku": "LUNA-S",
                            "size": "S",
                            "price": 4170000,
                            "currency": "INR",
                        },
                        {
                            "variantId": "luna-large",
                            "sku": "LUNA-L",
                            "size": "L",
                            "price": 5950000,
                            "currency": "INR",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "59500.00"
    assert {row["size"]: row["price"] for row in result.records[0]["variants"]} == {
        "S": "41700.00",
        "L": "59500.00",
    }


def test_ten_x_peer_does_not_scale_normal_major_unit_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Arrival Shorts","url":"https://shop.test/products/arrival-shorts","offers":{"price":"20","priceCurrency":"USD"},"hasVariant":[{"@type":"Product","sku":"ARRIVAL-3XL","size":"3XL","offers":{"price":"20","priceCurrency":"USD"}}]}
        </script>
        """,
        "https://shop.test/products/arrival-shorts",
        artifacts={
            "js_state_objects": {
                "productData": {
                    "name": "Arrival Shorts",
                    "getTheLookProducts": [
                        {
                            "name": "Related Socks",
                            "variants": [
                                {
                                    "variantId": "related-socks",
                                    "sku": "SOCKS-S",
                                    "size": "S",
                                    "price": 2,
                                    "currency": "USD",
                                }
                            ],
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "20.00"
    assert result.records[0]["variants"][0]["price"] == "20.00"


def test_primary_structured_offer_outranks_conflicting_secondary_currency() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="product:price:amount" content="1400.00">
        <meta property="product:price:currency" content="USD">
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Lip Balm","url":"https://shop.test/en-in/products/lip-balm","image":"https://shop.test/lip-balm.jpg","offers":{"price":"1400","priceCurrency":"INR"}}
        </script>
        <script>
        var meta = {"product":{"id":721,"variants":[{"id":412,"price":180000,"sku":"BALM-BDAY","public_title":"Birthday"}]},"page":{"pageType":"product"}};
        </script>
        """,
        "https://shop.test/en-in/products/lip-balm",
    )

    record = result.records[0]
    assert record["price"] == "1400.00"
    assert record["currency"] == "INR"
    assert record["variants"][0]["price"] == "1800.00"
    assert record["variants"][0]["currency"] == "INR"


def test_uniform_variant_offer_populates_missing_parent_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context":"https://schema.org",
          "@type":"ProductGroup",
          "name":"Kids Tank",
          "url":"https://shop.test/products/kids-tank",
          "image":"https://shop.test/kids-tank.jpg",
          "hasVariant":[
            {"@type":"Product","sku":"TANK-S","size":"S","offers":{"price":"70","priceCurrency":"USD"}},
            {"@type":"Product","sku":"TANK-M","size":"M","offers":{"price":"70","priceCurrency":"USD"}}
          ]
        }
        </script>
        """,
        "https://shop.test/products/kids-tank",
    )

    record = result.records[0]
    assert record["price"] == "70.00"
    assert record["currency"] == "USD"
    assert record["_lineage"]["price"]["rule_id"] == ("uniform_variant_offer_aggregate")


def test_same_offer_formatted_price_corroborates_raw_minor_unit_price() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Air Jordan 5 Retro</h1></main>",
        "https://shop.test/products/air-jordan-5-retro",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Air Jordan 5 Retro",
                        "url": "https://shop.test/products/air-jordan-5-retro",
                        "price": 21500,
                        "formattedPrice": "USD 215.00",
                        "currency": "USD",
                        "variants": [
                            {
                                "variantId": "jordan-8",
                                "sku": "JORDAN-8",
                                "size": "8",
                                "price": 21500,
                                "formattedPrice": "USD 215.00",
                                "currency": "USD",
                            },
                            {
                                "variantId": "jordan-9",
                                "sku": "JORDAN-9",
                                "size": "9",
                                "price": 21500,
                                "formattedPrice": "USD 215.00",
                                "currency": "USD",
                            },
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "215.00"
    assert {row["price"] for row in result.records[0]["variants"]} == {"215.00"}
    facts = _price_repair_facts(result, "corroborated_price_scale")
    assert any(fact.value == "215.00" for fact in facts)
    assert any(
        item.fact_type == "offer.price" and item.raw_value == 21500 and not item.flags
        for item in result.evidence
    )


def test_uncorroborated_expensive_inr_price_is_not_divided() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Collector Handbag</h1></main>",
        "https://shop.test/products/collector-handbag",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Collector Handbag",
                        "url": "https://shop.test/products/collector-handbag",
                        "price": 2820000,
                        "currency": "INR",
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "2820000.00"


def test_parent_current_price_does_not_scale_variant_original_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Road Hoodie",
          "url": "https://shop.test/products/road-hoodie",
          "offers": {"price": "138.75", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/road-hoodie",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Road Hoodie",
                    "url": "https://shop.test/products/road-hoodie",
                    "variants": [
                        {
                            "variantId": "brown-m",
                            "sku": "ROAD-BRN-M",
                            "size": "M",
                            "price": "150",
                            "originalPrice": 13875,
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["price"] == "150.00"
    assert variant["original_price"] == "13875.00"
    assert not any(
        fact.rule_id == "corroborated_price_scale"
        for fact in result.derived_facts
        if fact.fact_type == "offer.original_price"
    )


def test_slug_only_detail_output_is_review_not_success() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
    )
    assert result.records
    assert result.records[0]["title"] == "rustic cotton t shirt p04424306"
    assert result.verdict == "partial"


def test_structured_title_outranks_filename_and_internal_id_url_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Linen Travel Shirt",
          "url": "https://shop.test/products/99107606086.html",
          "offers": {"price": "89", "priceCurrency": "USD"}
        }
        </script>
        <main><h1>Linen Travel Shirt</h1></main>
        """,
        "https://shop.test/products/99107606086.html",
    )

    assert result.records[0]["title"] == "Linen Travel Shirt"
    assert result.verdict == "partial"


@pytest.mark.parametrize(
    ("page_url", "html"),
    (
        (
            "https://kith.com/products/st40002-02000",
            "<main><h1>st40002 02000</h1></main>",
        ),
        (
            "https://www.amazon.com/example/dp/B0F5Y3X8PP/?th=1",
            "<main><h1>Not Added</h1></main>",
        ),
        (
            "https://shop.lululemon.com/p/jackets/_/prod10930188",
            "<main><h1>prod10930188</h1></main>",
        ),
        (
            "https://www.ralphlauren.global/in/en/the-iconic-cotton-chino-ball-cap-650310.html",
            "<html><body></body></html>",
        ),
        (
            "https://shop.test/product.do?id=12345",
            "<main><h1>product.do</h1></main>",
        ),
    ),
)
def test_identifier_placeholder_and_filename_titles_do_not_materialize(
    page_url: str,
    html: str,
) -> None:
    result = _extract(
        "ecommerce_detail",
        html,
        page_url,
        requested_fields=("title",),
    )

    assert not result.records or result.records[0].get("title") is None
    assert any(
        finding.rule_id == "MISSING_CONTRACT_FIELD"
        and finding.metadata.get("field") == "title"
        for finding in result.findings
    )
    assert any(
        finding.rule_id == "MISSING_OR_GENERIC_TITLE" for finding in result.findings
    )
    assert result.verdict in {"empty", "partial", "review"}


@pytest.mark.parametrize(
    "bad_title", ("Black", "Refurbished", "& More", "Shipping", "TALL LARGE")
)
def test_option_condition_navigation_and_shipping_titles_are_rejected_at_admission(
    bad_title: str,
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"<main><h1>{bad_title}</h1></main>",
        "https://shop.test/products/real-product-name",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "real product name"
    bad_rows = [
        row
        for row in result.evidence
        if row.fact_type == "product.title" and str(row.value) == bad_title
    ]
    assert bad_rows
    assert all("generic_title" in row.flags for row in bad_rows)
    accepted_ids = {
        evidence_id
        for decision in result.decisions
        if decision.fact_type == "product.title"
        for evidence_id in decision.accepted_evidence_ids
    }
    assert not accepted_ids.intersection(row.evidence_id for row in bad_rows)


def test_brand_boilerplate_values_are_rejected_at_admission() -> None:
    for bad_brand in (
        "Refurbished",
        "Womens",
        "the",
        "green",
        "Black",
        "Fragrance",
        "Register",
        "at",
        "India | The",
    ):
        result = _extract(
            "ecommerce_detail",
            f"""
            <head><meta property="product:brand" content="{bad_brand}"></head>
            <main><h1>Real Product Name</h1></main>
            """,
            "https://shop.test/products/real-product-name",
        )

        assert result.records
        assert result.records[0].brand is None


def test_unavailable_product_source_produces_precise_partial_field_states() -> None:
    base = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<main><h1>Unavailable Offer Product</h1></main>",
        "https://shop.test/products/unavailable-offer-product",
        requested_fields=("price", "currency", "availability"),
    )
    request = base.model_copy(
        update={
            "capture": base.capture.model_copy(
                update={
                    "acquisition_diagnostics": {
                        "source_capabilities": {
                            "product_data_source_unavailable": True,
                            "affected_field_families": (
                                "price",
                                "currency",
                                "availability",
                                "variants",
                            ),
                        }
                    }
                }
            )
        }
    )

    result = extract(request)
    states = {row.field: row for row in result.field_states}

    assert result.transport_outcome == "ok"
    assert result.data_integrity == "partial"
    assert result.verdict in {"partial", "review"}
    assert states["title"].state == "captured_published"
    assert states["price"].state == "source_unavailable"
    assert states["currency"].state == "source_unavailable"
    assert states["availability"].state == "source_unavailable"
    assert states["price"].reason_codes == ("product_data_source_unavailable",)


def test_complete_product_reports_clean_integrity_separately_from_transport() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Complete Product",
          "brand": "Complete Brand",
          "description": "A complete product-specific description.",
          "url": "https://shop.test/products/complete-product",
          "image": "https://cdn.shop.test/complete-product.jpg",
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/complete-product",
    )
    states = {row.field: row.state for row in result.field_states}

    assert result.transport_outcome == "ok"
    assert result.data_integrity == "clean"
    assert result.verdict == "success"
    assert states["title"] == "captured_published"
    assert states["price"] == "captured_published"
    assert states["currency"] == "captured_published"
    assert states["image_url"] == "captured_published"


def test_ecommerce_detail_field_states_cover_surface_and_contract_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Minimal Product",
          "url": "https://shop.test/products/minimal-product"
        }
        </script>
        """,
        "https://shop.test/products/minimal-product",
    )
    states = {row.field: row for row in result.field_states}

    for field in (
        "title",
        "url",
        "brand",
        "description",
        "image_url",
        "price",
        "currency",
        "availability",
        "variants",
        "variant_count",
    ):
        assert field in states
    assert states["title"].state == "captured_published"
    assert states["brand"].state == "not_present_in_captured_sources"
    assert states["price"].state == "not_present_in_captured_sources"
    assert states["variants"].state == "not_requested"


def test_js_state_budget_keeps_identity_and_requested_offer_group(monkeypatch) -> None:
    from app.extraction.collectors import js_state

    monkeypatch.setattr(js_state, "MAX_EVIDENCE_PER_SOURCE_OBJECT", 3)
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Trail Shoe",
                    "url": "https://shop.test/products/trail-shoe",
                    "price": "129",
                    "currency": "USD",
                    "sku": "TS-1",
                    "images": [
                        "https://cdn.shop.test/trail-1.jpg",
                        "https://cdn.shop.test/trail-2.jpg",
                    ],
                }
            }
        },
        requested_fields=("price",),
    )

    kept_facts = {
        row.fact_type for row in result.evidence if row.collector_id == "js_state"
    }
    assert {"product.url", "offer.price", "offer.currency"} <= kept_facts
    outcome = next(
        row
        for row in result.collector_outcomes
        if row.collector_id == "js_state" and row.outcome == "budget_limited"
    )
    assert "assets" in outcome.dropped_fact_families


def test_network_budget_reports_dropped_fact_families(monkeypatch) -> None:
    from app.extraction.collectors import metadata

    monkeypatch.setattr(metadata, "MAX_EVIDENCE_PER_SOURCE_OBJECT", 3)
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Trail Shoe",
                        "url": "https://shop.test/products/trail-shoe",
                        "price": "129",
                        "currency": "USD",
                        "images": [
                            "https://cdn.shop.test/trail-1.jpg",
                            "https://cdn.shop.test/trail-2.jpg",
                        ],
                    }
                },
            },
        ),
        requested_fields=("price",),
    )

    outcome = next(
        row
        for row in result.collector_outcomes
        if row.collector_id == "network" and row.outcome == "budget_limited"
    )
    assert "assets" in outcome.dropped_fact_families
    assert outcome.source_path


def test_multiple_incomplete_candidate_offers_are_grouped() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Grouped Offer Product",
          "url": "https://shop.test/products/grouped-offer-product",
          "hasVariant": [
            {"@type": "Product", "sku": "GO-1", "offers": {"price": "10"}},
            {"@type": "Product", "sku": "GO-2", "offers": {"price": "12"}},
            {"@type": "Product", "sku": "GO-3", "offers": {"price": "14"}}
          ]
        }
        </script>
        """,
        "https://shop.test/products/grouped-offer-product",
        requested_fields=("variants",),
    )

    findings = [
        row for row in result.findings if row.rule_id == "PRICE_WITHOUT_CURRENCY"
    ]

    assert len(findings) == 1
    assert findings[0].metadata["candidate_offer_count"] == 3
    assert len(findings[0].metadata["example_offer_entity_ids"]) == 3


def test_detail_text_fields_are_canonicalized_before_publication() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail &amp; Road Shoe",
          "brand": "Acme&nbsp;Run",
          "description": "<p>Fast &amp; light</p><ul><li>Mesh upper</li></ul>",
          "url": "https://shop.test/products/trail-road-shoe",
          "image": "https://cdn.shop.test/trail.jpg",
          "offers": {"price": "90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-road-shoe",
    )
    record = result.records[0]

    assert record["title"] == "Trail & Road Shoe"
    assert record["brand"] == "Acme Run"
    assert "Fast & light" in record["description"]
    assert "<" not in record["description"]
    assert "&amp;" not in record["description"]


def test_hidden_requested_product_panel_content_is_collected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Panel Product</h1>
          <section class="product-accordion">
            <div hidden data-field="description">Hidden product composition.</div>
          </section>
        </main>
        """,
        "https://shop.test/products/panel-product",
        requested_fields=("description",),
    )
    rows = [
        row
        for row in result.evidence
        if row.fact_type == "product.description"
        and "hidden_product_content" in row.flags
    ]

    assert result.records[0]["description"] == "Hidden product composition."
    assert rows
    assert rows[0].metadata["component_role"] == "product_panel"


def test_hidden_recommendation_content_is_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Panel Product</h1>
          <section class="recommendations">
            <div hidden data-field="description">Other product copy.</div>
          </section>
        </main>
        """,
        "https://shop.test/products/panel-product",
        requested_fields=("description",),
    )

    assert result.records[0].get("description") is None
    assert not [
        row
        for row in result.evidence
        if row.fact_type == "product.description"
        and str(row.value) == "Other product copy."
    ]


def test_host_title_brand_is_not_manufacturer_truth() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Marketplace Store Premium Blender",
          "url": "https://marketplacestore.test/products/premium-blender",
          "image": "https://cdn.marketplacestore.test/blender.jpg",
          "offers": {"price": "20", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://marketplacestore.test/products/premium-blender",
    )

    assert result.records[0].get("brand") is None
    assert not [
        row
        for row in result.derived_facts
        if row.fact_type == "product.brand" and row.rule_id == "brand_from_title_host"
    ]


def test_asset_publication_dedupes_delivery_identity_after_entity_decode() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Image Product",
          "brand": "Acme",
          "url": "https://shop.test/products/image-product",
          "image": [
            "https://cdn.shop.test/product.jpg?wid=400&amp;fmt=webp",
            "https://cdn.shop.test/product.jpg?wid=800&fmt=jpg"
          ],
          "offers": {"price": "20", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/image-product",
    )
    record = result.records[0]

    assert record["image_url"] == "https://cdn.shop.test/product.jpg?wid=800&fmt=jpg"
    assert "&amp;" not in record["image_url"]
    assert record.additional_images == ()


def test_offer_price_currency_shared_dom_group_publishes_as_atomic_pair() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Atomic Offer Product</h1>
          <div data-price="10"></div>
          <div data-currency="USD"></div>
        </main>
        """,
        "https://shop.test/products/atomic-offer-product",
    )

    assert result.records[0].get("price") == "10.00"
    assert result.records[0].get("currency") == "USD"
    assert {
        decision.fact_type: decision.status
        for decision in result.decisions
        if decision.fact_type in {"offer.price", "offer.currency"}
    } == {"offer.currency": "resolved", "offer.price": "resolved"}


def test_generic_size_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>size</h1></main>",
        "https://shop.test/p/tobago-stripe-blue-duvet-cover/-/A-1002150742",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "tobago stripe blue duvet cover"
    assert result.verdict == "partial"


def test_transient_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Added to Cart</h1></main>",
        "https://shop.test/Sparkling-Prebiotic-Beverage/dp/B0F5Y3X8PP/",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "Sparkling Prebiotic Beverage"
    assert result.verdict == "partial"


@pytest.mark.parametrize(
    ("bad_title", "page_url", "expected"),
    (
        ("T-Shirts", "https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027", None),
        (
            "Hats & Caps",
            "https://shop.test/us/en/products/wide-brim-sun-hat/E455957",
            "wide brim sun hat",
        ),
        ("Tread PDP - Compose Page", "https://shop.test/shop/tread", "tread"),
        ("mens footwear sneakers", "https://shop.test/products/st40002-02000", None),
        ("X", "https://shop.test/p/womens-chill-river-midi-dress-1933601.html", None),
        (
            "Interchangeable Lens Cameras",
            "https://shop.test/cameras/alpha-7-iv-full-frame-camera/ILCE7M4-B",
            "alpha 7 iv full frame camera",
        ),
        (
            "Wide Leg",
            "https://shop.test/p/wide-leg-cropped-jean/BT123",
            "wide leg cropped jean",
        ),
        (
            "Satisfy",
            "https://shop.test/products/satisfy-cloudmerino-running-tee",
            "satisfy cloudmerino running tee",
        ),
    ),
)
def test_taxonomy_and_cms_titles_use_semantic_url_identity(
    bad_title: str,
    page_url: str,
    expected: str | None,
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"<main><h1>{bad_title}</h1></main>",
        page_url,
        requested_fields=("title",),
    )

    if expected is None:
        assert result.records[0].get("title") is None
    else:
        assert result.records[0]["title"] == expected
    assert result.verdict in {"partial", "review"}


def test_measurement_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>4D</h1></main>",
        "https://shop.test/us/stan-smith-shoes/M20324.html",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "stan smith shoes"
    assert result.verdict == "partial"


def test_commerce_seo_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Buy Babyhug Denim Woven Sleeveless Top and Pant Set With Floral Print Blue Online at Best Price</h1></main>",
        "https://shop.test/brand/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == (
        "babyhug denim woven sleeveless top and pant set with floral print blue"
    )
    assert result.verdict == "partial"


def test_slug_only_detail_stub_routes_to_review_not_partial() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/breville-the-bambino-plus",
    )

    assert result.records
    assert result.records[0]["title"] == "breville the bambino plus"
    assert result.verdict == "partial"


def test_shell_h1_cannot_outrank_structured_product_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Fresh Foam X 1080v15",
          "url": "https://shop.test/products/fresh-foam-x-1080v15",
          "offers": {"price": "165", "priceCurrency": "USD"}
        }
        </script>
        <main><h1>Oops! Something went wrong</h1></main>
        """,
        "https://shop.test/products/fresh-foam-x-1080v15",
    )

    assert result.records[0]["title"] == "Fresh Foam X 1080v15"
    assert result.verdict == "partial"


def test_transient_cart_action_title_does_not_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Adding to Cart...</h1></main>",
        "https://www.amazon.com/example/dp/B0F5Y3X8PP/?th=1",
        requested_fields=("title",),
    )

    assert not result.records
    assert result.verdict != "success"


def test_truncated_title_loses_to_more_complete_url_identity() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>iPhone</h1></main>",
        "https://www.backmarket.com/en-us/p/iphone-15-plus",
    )

    assert result.records[0]["title"].casefold() == "iphone 15 plus"
    assert result.records[0]["title"] != "iPhone"
    assert result.verdict == "partial"


def test_natural_title_with_model_number_remains_admissible() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Levi 501 Jeans</h1></main>",
        "https://shop.test/products/levi-501-jeans",
    )

    assert result.records[0]["title"] == "Levi 501 Jeans"


def test_measurements_navigation_title_cannot_produce_success() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Measurements</h1>
          <div data-price="89">89</div>
          <div data-currency="USD">USD</div>
        </main>
        """,
        "https://shop.test/products/99107606086.html",
    )

    assert result.verdict != "success"
    assert not result.records or result.records[0].get("title") != "Measurements"


def test_standard_and_twitter_metadata_recover_missing_product_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <meta name="twitter:title" content="Trail Shoe">
          <meta name="description" content="A durable trail shoe for long-distance runs.">
          <meta name="brand" content="Invoro">
          <meta name="twitter:image" content="https://shop.test/i/trail.jpg">
        </head>
        <main></main>
        """,
        "https://shop.test/products/TS-100",
    )

    record = result.records[0]
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "Invoro"
    assert record["description"] == "A durable trail shoe for long-distance runs."
    assert record["image_url"] == "https://shop.test/i/trail.jpg"


def test_document_title_recovers_missing_product_heading() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head><title>Trail Shoe</title></head>
        <main><img data-product-image src="https://shop.test/i/trail.jpg"></main>
        """,
        "https://shop.test/products/TS-100",
    )

    assert result.records[0]["title"] == "Trail Shoe"
    assert result.verdict in {"partial", "review"}


def test_clean_h1_outranks_polluted_seo_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head><meta property="og:title" content="Trail Shoe | Shop Online - $129.00"></head>
        <main><h1>Trail Shoe</h1><div data-price="129">129</div><div data-currency="USD">USD</div></main>
        """,
        "https://shop.test/products/trail-shoe.html",
    )

    assert result.records[0]["title"] == "Trail Shoe"


def test_arbitrary_nested_price_object_cannot_create_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        artifacts={
            "js_state_objects": {"analytics": {"price": "999", "currency": "USD"}}
        },
    )

    assert result.records[0].get("price") is None
    assert result.records[0].get("currency") is None


def test_many_uncorroborated_dom_prices_do_not_create_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Wild Game Dry Dog Food, 18-lb bag</h1>
          <span data-price="77.48"></span>
          <span data-price="53.98"></span>
          <span data-price="59.98"></span>
          <span data-price="8.98"></span>
          <span data-price="4.50"></span>
        </main>
        """,
        "https://shop.test/dp/141791",
    )

    assert result.records
    record = result.records[0].model_dump(mode="python", exclude_none=True)
    assert "price" not in record


def test_missing_field_finding_uses_selected_public_value() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type": "Product", "name": "Trail Shoe", "brand": "N/A"}
        </script>
        """,
        "https://shop.test/products/trail-shoe",
        requested_fields=("brand",),
    )

    brand_findings = [
        finding
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
        and finding.metadata.get("field") == "brand"
    ]
    assert result.records[0].get("brand") is None
    assert len(brand_findings) == 1


def test_network_product_aliases_require_context_and_map_canonical_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Fallback</h1></main>",
        "https://shop.test/products/trail-shoe",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "productName": "Trail Shoe",
                        "brand": {"name": "Invoro"},
                        "productDescription": "Built for long trail days.",
                        "price": "129",
                        "currencyCode": "USD",
                        "inStock": True,
                        "images": [
                            "https://shop.test/images/trail-1.jpg",
                            "https://shop.test/images/trail-2.jpg",
                        ],
                    }
                }
            },
        ),
    )

    record = result.records[0]
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "Invoro"
    assert record["description"] == "Built for long trail days."
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    image_urls = {
        str(item.value)
        for item in result.evidence
        if item.fact_type == "asset.image_url"
    }
    assert image_urls == {
        "https://shop.test/images/trail-1.jpg",
        "https://shop.test/images/trail-2.jpg",
    }
    assert record["image_url"] in image_urls


def test_structured_image_objects_materialize_primary_and_additional_images() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Trail Shoe",
                        "url": "https://shop.test/products/trail-shoe",
                        "price": "129",
                        "currency": "USD",
                        "images": [
                            {
                                "url": "https://cdn.shop.test/products/trail-shoe-main.jpg"
                            },
                            {
                                "src": "https://cdn.shop.test/products/trail-shoe-side.jpg"
                            },
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["image_url"] == (
        "https://cdn.shop.test/products/trail-shoe-main.jpg"
    )
    assert result.records[0]["additional_images"] == [
        "https://cdn.shop.test/products/trail-shoe-side.jpg"
    ]


def test_access_denied_shell_does_not_succeed() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head><title>Access denied. We invite you to return at a later time to complete your purchase.</title></head>
          <body><h1>Access denied. We invite you to return at a later time to complete your purchase.</h1></body>
        </html>
        """,
        "https://us.louisvuitton.com/eng-us/products/bootleg-pants-nvprod7220319v/1AJUPQ",
    )
    assert result.verdict == "error"
    assert result.retry_request is not None
    assert result.retry_request.reason == "http_shell"


def test_punctuated_shell_title_with_offer_data_does_not_publish_record() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@type": "Product",
              "name": "Oops, Something Went Wrong.",
              "url": "https://shop.test/products/trail-shoe",
              "offers": {"price": "99", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body><h1>Oops, Something Went Wrong.</h1></body>
        </html>
        """,
        "https://shop.test/products/trail-shoe",
    )
    assert result.verdict == "error"
    assert result.records == ()
    assert result.retry_request is not None
    assert result.retry_request.reason == "http_shell"


def test_order_and_duplicate_independence() -> None:
    duplicate = HTML.replace(
        "</head>", HTML.split("<script", 1)[1].join(["<script", "</head>"])
    )
    first = tuple(
        _extract(
            "ecommerce_detail", HTML, "https://shop.test/products/trail-shoe"
        ).records
    )
    second = tuple(
        _extract(
            "ecommerce_detail", duplicate, "https://shop.test/products/trail-shoe"
        ).records
    )

    def public_values(records):
        return tuple(
            {
                key: value
                for key, value in record.model_dump(mode="python").items()
                if not key.startswith("_")
            }
            for record in records
        )

    assert public_values(first) == public_values(second)


def test_ecommerce_detail_result_is_replayable() -> None:
    result = _extract(
        "ecommerce_detail",
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["records"][0]["title"] == "Trail Shoe"
    assert payload["evidence"]
    assert payload["decisions"]


def test_ecommerce_detail_product_endpoint_query_url_publishes_dom_product() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <title>Linen-Cotton Relaxed Taper Easy Pants</title>
            <meta property="description" content="Soft linen cotton pants.">
          </head>
          <body>
            <main>
              <h1>Linen-Cotton Relaxed Taper Easy Pants</h1>
              <picture>
                <source srcset="https://cdn.shop.test/pants.png?width=737">
              </picture>
              <button>Add to bag</button>
            </main>
          </body>
        </html>
        """,
        "https://www.gap.com/browse/product.do?pid=887835012&vid=1",
    )

    assert result.verdict in {"success", "partial"}
    assert result.records[0]["title"] == "Linen-Cotton Relaxed Taper Easy Pants"
    assert result.records[0]["url"] == (
        "https://www.gap.com/browse/product.do?pid=887835012&vid=1"
    )
    assert result.records[0]["_lineage"]["url"]


def test_ecommerce_listing_cutover_materializes_with_lineage() -> None:
    html = """
    <main>
      <article class="product-card">
        <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
        <span class="price">$129.00</span>
        <img src="/images/trail.jpg">
      </article>
      <article class="product-card">
        <a href="/products/day-pack"><h2>Day Pack</h2></a>
        <span class="price">$89.00</span>
      </article>
    </main>
    """
    result = _extract(
        "ecommerce_listing",
        html,
        "https://shop.test/collections/all",
        max_records=5,
    )
    assert result.verdict == "success"
    assert result.evidence
    assert result.decisions
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "ecommerce_listing" for item in result.evidence)


def test_ecommerce_listing_result_is_replayable() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <section>
          <div class="product-tile">
            <a href="/products/trail-shoe" title="Trail Shoe">Trail Shoe</a>
            <div data-price="129.00"></div>
          </div>
        </section>
        """,
        "https://shop.test/collections/all",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows == [
        {
            "title": "Trail Shoe",
            "url": "https://shop.test/products/trail-shoe",
            "price": "129.00",
            "_lineage": rows[0]["_lineage"],
            "_subject_id": rows[0]["_subject_id"],
        }
    ]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "ecommerce_listing"
    assert payload["evidence"]
    assert payload["decisions"]


def test_ecommerce_listing_filters_docs_utility_links() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <li><a href="/docs" title="API">API</a></li>
          <li><a href="/file-download" title="File Download">File Download</a></li>
          <li><a href="/sitemap.xml" title="Sitemap">Sitemap</a></li>
          <div class="row product">
            <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
          </div>
        </main>
        """,
        "https://shop.test/products",
        max_records=5,
    )
    assert [row["title"] for row in result.records] == ["Trail Shoe"]


def test_ecommerce_listing_rejects_site_chrome_and_unproven_category_links() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <header>
          <nav>
            <ul>
              <li><a href="/customer-service/">Customer Service</a></li>
              <li><a href="/ca/en/c/womens/">Women</a></li>
            </ul>
          </nav>
        </header>
        <main>
          <ul class="category-links">
            <li><a href="/ca/en/c/mens/footwear/">Men's Footwear</a></li>
            <li><a href="#">Store Directory</a></li>
          </ul>
          <article class="product-card">
            <a href="/ca/en/shop/mens/norvan-ld-4-shoe" title="Norvan LD 4 Shoe">
              <img src="/images/norvan.jpg">
            </a>
            <span class="price">$200.00</span>
          </article>
        </main>
        <footer>
          <ul><li><a href="/returns/">Returns</a></li></ul>
        </footer>
        """,
        "https://shop.test/ca/en/c/mens/footwear-run/wid-example",
        max_records=20,
    )

    assert [row["title"] for row in result.records] == ["Norvan LD 4 Shoe"]
    assert [row["url"] for row in result.records] == [
        "https://shop.test/ca/en/shop/mens/norvan-ld-4-shoe"
    ]


def test_ecommerce_listing_keeps_generic_card_with_price_and_detail_link() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <ul>
            <li>
              <a href="/p/trail-shoe" title="Trail Shoe">Trail Shoe</a>
              <span class="price">$99.00</span>
            </li>
          </ul>
        </main>
        """,
        "https://shop.test/category/shoes",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Trail Shoe"]


def test_ecommerce_listing_reads_product_tile_metadata_after_image_link() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <div
            data-tile-type="product"
            data-cnstrc-item-name="Classic Fit Pants"
            data-cnstrc-item-id="SKU123"
          >
            <a href="/p/classic-fit-pants/SKU123.html">
              <img src="/images/classic-fit-pants.jpg" alt="Classic Fit Pants">
            </a>
            <a href="/p/classic-fit-pants/SKU123.html">Classic Fit Pants</a>
            <span>31-Inch Inseam</span>
            <span>$42.95</span>
          </div>
        </main>
        """,
        "https://shop.test/men/pants/",
        max_records=5,
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Classic Fit Pants"
    assert (
        result.records[0]["url"] == "https://shop.test/p/classic-fit-pants/SKU123.html"
    )
    assert result.records[0]["price"] == "$42.95"
    assert (
        result.records[0]["image_url"]
        == "https://shop.test/images/classic-fit-pants.jpg"
    )


def test_ecommerce_listing_uses_browser_visual_artifact_when_html_has_no_cards() -> (
    None
):
    product_url = "https://shop.test/p/classic-fit-pants/SKU123.html"
    result = _extract(
        "ecommerce_listing",
        "<main><h1>Men's Pants</h1></main>",
        "https://shop.test/men/pants/",
        max_records=5,
        artifacts={
            "listing_visual_html": (
                '<main><article data-product-id="visual-0">'
                f'<a href="{product_url}" title="View product">View product</a>'
                f'<a href="{product_url}" title="Classic Fit Pants">Classic Fit Pants</a>'
                '<img src="https://shop.test/images/classic-fit-pants.jpg">'
                '<span class="price">$42.95</span>'
                "</article></main>"
            )
        },
    )

    assert len(result.records) == 1
    assert result.records[0]["title"] == "Classic Fit Pants"
    assert result.records[0]["url"] == product_url
    assert result.records[0]["price"] == "$42.95"
    assert result.records[0]["image_url"] == (
        "https://shop.test/images/classic-fit-pants.jpg"
    )
    assert {row.artifact_id for row in result.evidence} == {"listing_visual_html"}


def test_ecommerce_listing_accepts_same_site_subdomain_detail_url() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <a href="https://www.shop.test/products/trail-shoe" title="Trail Shoe">
              <img src="/images/trail-shoe.jpg">
            </a>
            <span class="price">$120.00</span>
          </article>
          <article class="product-card">
            <a href="https://external.test/products/other" title="Other Shoe">
              <img src="/images/other-shoe.jpg">
            </a>
            <span class="price">$90.00</span>
          </article>
        </main>
        """,
        "https://m.shop.test/collections/shoes",
        max_records=5,
    )

    assert [row["url"] for row in result.records] == [
        "https://www.shop.test/products/trail-shoe"
    ]


def test_ecommerce_listing_rejects_selected_state_as_product_title() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <button class="product-title" aria-selected="true">Cor selecionada</button>
            <a href="/products/linen-pant" aria-label="View product">
              <img src="/images/linen-pant.jpg">
            </a>
            <span class="price">$79.00</span>
          </article>
        </main>
        """,
        "https://shop.test/collections/pants",
        max_records=5,
    )

    assert not result.records


def test_ecommerce_listing_uses_title_from_product_link_scope() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <article class="product-card">
            <button class="product-title" aria-selected="true">Selected blue</button>
            <a href="/products/linen-pant" title="Linen Pant">Shop now</a>
            <span class="price">$79.00</span>
          </article>
        </main>
        """,
        "https://shop.test/collections/pants",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Linen Pant"]


@pytest.mark.parametrize("badge", ("New colour", "Best seller"))
def test_ecommerce_listing_skips_merchandising_badge_for_product_title(
    badge: str,
) -> None:
    result = _extract(
        "ecommerce_listing",
        f"""
        <main>
          <article class="product-card">
            <a href="/shop/mens/kragg-shoe-0078"><span>{badge}</span></a>
            <a href="/shop/mens/kragg-shoe-0078"><h2>Kragg Shoe Men's</h2></a>
            <img src="/images/kragg-shoe.jpg">
            <span class="price">$180.00</span>
          </article>
        </main>
        """,
        "https://shop.test/ca/en/c/mens/footwear",
        max_records=5,
    )

    assert [row["title"] for row in result.records] == ["Kragg Shoe Men's"]


def test_ecommerce_listing_rejects_utility_url_families() -> None:
    utility_paths = (
        "/support/product-care",
        "/legal/accessibility",
        "/stores/city-directory",
        "/gift-registry/create",
        "/ca/en/help/product-care",
        "/mobile-app/download",
        "/athletes/team",
        "/ambassadors/join",
    )
    cards = "".join(
        f'<article class="product-card"><a href="{path}"><h2>Trail Shoe</h2></a></article>'
        for path in utility_paths
    )
    result = _extract(
        "ecommerce_listing",
        f"<main>{cards}</main>",
        "https://shop.test/collections/all",
        max_records=20,
    )

    assert not result.records


def test_ecommerce_listing_rejects_utility_label_as_title() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <article class="product-card">
          <a href="/products/trail-shoe" title="Customer Service">Learn more</a>
          <span class="price">$99.00</span>
        </article>
        """,
        "https://shop.test/collections/all",
        max_records=5,
    )

    assert not result.records


def test_js_state_dict_values_do_not_crash_dedupe() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": {"text": "Rustic Cotton T-Shirt"},
                "price": {"value": "29.90"},
                "currency": "USD",
            }
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Fallback</h1></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["price"] == "29.90"
    assert result.evidence


def test_js_state_explicit_variant_rows_are_materialized() -> None:
    artifacts = {
        "js_state_objects": {
            "variants": [
                {"id": "v1", "sku": "SKU-BLK-S", "size": "S", "color": "Black"},
                {"id": "v2", "sku": "SKU-WHT-M", "size": "M", "color": "White"},
            ]
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Rustic Cotton T-Shirt</h1></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["variants"] == [
        {"variant_id": "v1", "sku": "SKU-BLK-S", "color": "Black", "size": "S"},
        {"variant_id": "v2", "sku": "SKU-WHT-M", "color": "White", "size": "M"},
    ]


def test_js_state_nested_variant_options_and_offer_materialize() -> None:
    artifacts = {
        "js_state_objects": {
            "variants": [
                {
                    "__typename": "ProductVariant",
                    "variantId": "v-red-s",
                    "sku": "TEE-RED-S",
                    "selectedOptions": [
                        {"name": "Color", "value": "Red"},
                        {"name": "Size", "value": "S"},
                    ],
                    "price": {"value": "18.5"},
                    "currencyCode": "USD",
                    "inStock": True,
                },
                {
                    "__typename": "ProductVariant",
                    "skuId": "sku-blue-m",
                    "attributes": {"color": "Blue", "size": "M"},
                    "currentPrice": "19",
                    "currency": "USD",
                    "availability": "https://schema.org/OutOfStock",
                },
            ]
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Everyday Tee</h1></body></html>",
        "https://shop.test/products/everyday-tee",
        artifacts=artifacts,
    )
    assert result.records
    assert result.records[0]["variants"] == [
        {
            "variant_id": "sku-blue-m",
            "sku": "sku-blue-m",
            "price": "19.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "color": "Blue",
            "size": "M",
        },
        {
            "variant_id": "v-red-s",
            "sku": "TEE-RED-S",
            "price": "18.50",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Red",
            "size": "S",
        },
    ]


def test_cross_product_variant_url_does_not_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Lightweight Barrel Pants</h1></main>",
        "https://shop.test/products/lightweight-barrel-pants/prd/210397084",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Lightweight Barrel Pants",
                        "url": "https://shop.test/products/lightweight-barrel-pants/prd/210397084",
                        "price": "65",
                        "currency": "USD",
                        "variants": [
                            {
                                "variantId": "210355002",
                                "sku": "210355002",
                                "url": "https://shop.test/products/chiffon-ruffle-beach-mini-dress/prd/210355002",
                                "color": "YELLOW",
                                "price": "40",
                                "currency": "USD",
                            }
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["price"] == "65.00"
    assert not result.records[0].get("variants")


def test_dotted_window_product_assignment_materializes_size_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main><h1>Curve Barrel Pants</h1></main>
        <script>
        window.storefront.pdp.config.product = {
          "id": 210397084,
          "name": "Curve Barrel Pants",
          "productCode": "155394360",
          "url": "https://shop.test/products/curve-barrel-pants/210397084",
          "variants": [
            {"variantId": 1, "size": "US 14", "sku": "A14", "isAvailable": true},
            {"variantId": 2, "size": "US 16", "sku": "A16", "isAvailable": false}
          ]
        };
        </script>
        """,
        "https://shop.test/products/curve-barrel-pants/210397084",
    )

    variants = result.records[0].get("variants") or []
    assert [(row["size"], row["availability"]) for row in variants] == [
        ("US 14", "in_stock"),
        ("US 16", "out_of_stock"),
    ]


def test_related_product_variant_url_with_shared_family_tokens_is_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Shape Tape Concealer</h1></main>",
        "https://shop.test/p/shape-tape-concealer/base",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Shape Tape Concealer",
                        "url": "https://shop.test/p/shape-tape-concealer/base",
                        "variants": [
                            {
                                "variantId": "base",
                                "sku": "BASE",
                                "url": "https://shop.test/p/shape-tape-concealer/base?sku=BASE",
                                "price": "32",
                                "currency": "USD",
                            },
                            {
                                "variantId": "creamy",
                                "sku": "CREAMY",
                                "url": "https://shop.test/p/shape-tape-creamy-concealer/creamy",
                                "price": "32",
                                "currency": "USD",
                            },
                        ],
                    }
                }
            },
        ),
    )

    variants = result.records[0].get("variants") or []
    assert [row["sku"] for row in variants] == ["BASE"]


def test_same_product_variant_url_remains_materialized() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee/prd/210397084",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Runner Tee",
                        "url": "https://shop.test/products/runner-tee/prd/210397084",
                        "variants": [
                            {
                                "variantId": "navy-s",
                                "sku": "RT-NAVY-S",
                                "url": "https://shop.test/products/runner-tee/prd/210397084?variant=navy-s",
                                "color": "Navy",
                                "size": "S",
                                "price": "35",
                                "currency": "USD",
                            }
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["variants"][0]["sku"] == "RT-NAVY-S"
    assert result.records[0]["variants"][0]["color"] == "Navy"
    assert result.records[0]["variants"][0]["size"] == "S"


def test_shopify_numeric_option1_materializes_as_size() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Trail Shoe",
                    "url": "https://shop.test/products/trail-shoe",
                    "price": 100,
                    "currency": "USD",
                    "variants": [
                        {
                            "id": "shoe-8",
                            "sku": "SHOE-8",
                            "option1": "8",
                            "title": "8",
                            "price": 100,
                            "currency": "USD",
                        },
                        {
                            "id": "shoe-85",
                            "sku": "SHOE-85",
                            "option1": "8.5",
                            "title": "8.5",
                            "price": 100,
                            "currency": "USD",
                        },
                    ],
                }
            }
        },
    )

    assert [row["size"] for row in result.records[0]["variants"]] == ["8", "8.5"]


def test_merch_sku_label_materializes_sku_and_size() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Air Force 1</h1></main>",
        "https://shop.test/products/air-force-1",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Air Force 1",
                    "url": "https://shop.test/products/air-force-1",
                    "price": 115,
                    "currency": "USD",
                    "skus": [
                        {
                            "merchSkuId": "sku-6",
                            "label": "6",
                            "localizedLabel": "M 6 / W 7.5",
                            "productCode": "CW2288-111",
                            "availability": "IN_STOCK",
                        },
                        {
                            "merchSkuId": "sku-65",
                            "label": "6.5",
                            "localizedLabel": "M 6.5 / W 8",
                            "productCode": "CW2288-111",
                            "availability": "IN_STOCK",
                        },
                    ],
                }
            }
        },
    )

    variants = result.records[0]["variants"]
    assert [(row["sku"], row["size"]) for row in variants] == [
        ("sku-6", "6"),
        ("sku-65", "6.5"),
    ]


def test_product_container_sizes_use_matching_product_offer_only() -> None:
    page_url = "https://shop.test/products/air-force-1/CW2288-111"
    matching_product = {
        "id": "13071857",
        "colorDescription": "White/White",
        "pdpUrl": {"url": page_url},
        "prices": {"currentPrice": 115, "currency": "USD"},
        "productInfo": {"title": "Air Force 1", "url": page_url},
        "sizes": [
            {"merchSkuId": "white-8", "label": "8", "status": "ACTIVE"},
            {"merchSkuId": "white-9", "label": "9", "status": "ACTIVE"},
        ],
    }
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Air Force 1</h1></main>",
        page_url,
        artifacts={
            "js_state_objects": {
                "props": {
                    "pageProps": {
                        "colorwayImages": [
                            {
                                "id": "13071857",
                                "url": page_url,
                                "colorDescription": "White/White",
                            },
                            {
                                "id": "13071848",
                                "url": "https://shop.test/products/air-force-1/CW2288-001",
                                "colorDescription": "Black/Black",
                            },
                        ],
                        "productGroups": [
                            {
                                "products": {
                                    "CW2288-111": matching_product,
                                    "CW2288-001": {
                                        "id": "13071848",
                                        "colorDescription": "Black/Black",
                                        "pdpUrl": {
                                            "url": "https://shop.test/products/air-force-1/CW2288-001"
                                        },
                                        "prices": {
                                            "currentPrice": 120,
                                            "currency": "USD",
                                        },
                                        "productInfo": {
                                            "title": "Air Force 1",
                                            "url": "https://shop.test/products/air-force-1/CW2288-001",
                                        },
                                        "sizes": [
                                            {
                                                "merchSkuId": "black-8",
                                                "label": "8",
                                                "status": "ACTIVE",
                                            }
                                        ],
                                    },
                                }
                            }
                        ],
                        "selectedProduct": matching_product,
                    }
                }
            }
        },
    )

    record = result.records[0]
    assert record["price"] == "115.00"
    assert record["currency"] == "USD"
    assert record["variants"] == [
        {
            "variant_id": "white-8",
            "sku": "white-8",
            "price": "115.00",
            "currency": "USD",
            "size": "8",
        },
        {
            "variant_id": "white-9",
            "sku": "white-9",
            "price": "115.00",
            "currency": "USD",
            "size": "9",
        },
    ]
    assert all(row.get("sku") != "black-8" for row in record["variants"])
    assert all("color" not in row for row in record["variants"])


def test_variant_placeholder_axis_labels_are_removed() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Mostro Ecstasy</h1></main>",
        "https://shop.test/products/mostro-ecstasy",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Mostro Ecstasy",
                    "url": "https://shop.test/products/mostro-ecstasy",
                    "variants": [
                        {
                            "variantId": "mostro-1",
                            "sku": "MOSTRO-1",
                            "color": "Color",
                            "size": "Size",
                            "price": "120",
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["variant_id"] == "mostro-1"
    assert variant["sku"] == "MOSTRO-1"
    assert "color" not in variant
    assert "size" not in variant


def test_variant_axes_equal_to_identity_are_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Teddy T-Shirt</h1></main>",
        "https://shop.test/products/teddy-t-shirt",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Teddy T-Shirt",
                    "url": "https://shop.test/products/teddy-t-shirt",
                    "variants": [
                        {
                            "variantId": "teddy-blue",
                            "sku": "JMTS01771",
                            "color": "JMTS01771",
                            "size": "JMTS01771",
                            "price": "95",
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["sku"] == "JMTS01771"
    assert "color" not in variant
    assert "size" not in variant


def test_compact_alphanumeric_color_codes_are_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Soleil Pant</h1></main>",
        "https://shop.test/products/soleil-pant",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Soleil Pant",
                    "url": "https://shop.test/products/soleil-pant",
                    "variants": [
                        {
                            "variantId": "soleil-code",
                            "sku": "ME988",
                            "color": "EM0212",
                            "price": "128",
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["sku"] == "ME988"
    assert "color" not in variant


def test_opaque_numeric_variant_option_rows_do_not_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Old Skool Shoe</h1></main>",
        "https://shop.test/products/old-skool-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Old Skool Shoe",
                    "url": "https://shop.test/products/old-skool-shoe",
                    "price": "80",
                    "currency": "USD",
                    "variants": [
                        {
                            "variantId": "old-skool-db-row",
                            "sku": "OLD-SKOOL-ROW",
                            "style": "1298",
                            "width": "1343",
                            "price": "80",
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "80.00"
    assert not result.records[0].get("variants")


def test_multiple_commercial_rows_without_variant_options_are_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Connected Treadmill</h1></main>",
        "https://shop.test/products/connected-treadmill",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Connected Treadmill",
                    "url": "https://shop.test/products/connected-treadmill",
                    "price": "2995",
                    "currency": "USD",
                    "variants": [
                        {
                            "variantId": "base-package",
                            "sku": "BASE-PKG",
                            "price": "2995",
                            "currency": "USD",
                        },
                        {
                            "variantId": "warranty-package",
                            "sku": "WARRANTY-48M",
                            "price": "499",
                            "currency": "USD",
                        },
                    ],
                }
            }
        },
    )

    assert result.records[0]["price"] == "2995.00"
    assert not result.records[0].get("variants")


def test_js_state_numeric_availability_flags_materialize_as_stock_states() -> None:
    artifacts = {
        "js_state_objects": {
            "variants": [
                {
                    "__typename": "ProductVariant",
                    "variantId": "shoe-8",
                    "sku": "SHOE-8",
                    "size": "8",
                    "availability": 0,
                },
                {
                    "__typename": "ProductVariant",
                    "variantId": "shoe-9",
                    "sku": "SHOE-9",
                    "size": "9",
                    "availability": 1,
                },
            ]
        }
    }

    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Classic Shoe</h1></body></html>",
        "https://shop.test/products/classic-shoe",
        artifacts=artifacts,
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "shoe-8",
            "sku": "SHOE-8",
            "availability": "out_of_stock",
            "size": "8",
        },
        {
            "variant_id": "shoe-9",
            "sku": "SHOE-9",
            "availability": "in_stock",
            "size": "9",
        },
    ]


def test_js_state_variant_assets_and_gtin_keep_variant_ownership() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Trail Shoe",
                    "url": "https://shop.test/products/trail-shoe",
                    "variants": [
                        {
                            "variantId": "trail-9",
                            "sku": "TRAIL-9",
                            "gtin13": "1234567890123",
                            "size": "9",
                            "image": "https://cdn.shop.test/trail-9.jpg",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "trail-9",
            "sku": "TRAIL-9",
            "image_url": "https://cdn.shop.test/trail-9.jpg",
            "size": "9",
        }
    ]
    gtin = next(row for row in result.evidence if row.fact_type == "variant.gtin")
    image = next(
        row
        for row in result.evidence
        if row.fact_type == "asset.image_url" and row.collector_id == "js_state"
    )
    assert gtin.subject_id == image.parent_subject_id
    assert image.relation_type == "variant_asset"


def test_shopify_meta_assignment_keeps_default_variant_diagnostic_only() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Black Bracelet","url":"https://shop.test/products/black-bracelet","offers":{"price":"8.00","priceCurrency":"USD"}}
        </script>
        <script>
        var meta = {"product":{"id":721,"variants":[{"id":412,"price":800,"sku":"BRACELET-BLK","title":"Default Title"}]},"page":{"pageType":"product"}};
        </script>
        """,
        "https://shop.test/products/black-bracelet",
    )

    assert result.records[0]["price"] == "8.00"
    assert not result.records[0].get("variants")
    assert any(
        "default_variant_placeholder" in row.flags
        for row in result.evidence
        if row.fact_type == "variant.id"
    )


def test_shopify_vendor_and_public_title_materialize_brand_and_size() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Graphic Tee","url":"https://shop.test/products/graphic-tee","image":"https://shop.test/graphic-tee.jpg","offers":{"price":"19.98","priceCurrency":"USD"}}
        </script>
        <span itemprop="brand">Mens Short Sleeve Shirt</span>
        <script>
        var meta = {"product":{"id":721,"vendor":"JORDAN","variants":[{"id":412,"price":1998,"sku":"TEE-XS","public_title":"XS"}]},"page":{"pageType":"product"}};
        </script>
        """,
        "https://shop.test/products/graphic-tee",
    )

    assert result.records[0]["brand"] == "JORDAN"
    assert result.records[0]["variants"][0]["size"] == "XS"
    assert result.records[0]["variants"][0]["price"] == "19.98"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Mens Short Sleeve Shirt"
        and "category_as_brand" in row.flags
        for row in result.evidence
    )


def test_richer_shopify_product_axis_outranks_compact_meta_fallback() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Lip Balm","url":"https://shop.test/products/lip-balm","offers":{"price":"18","priceCurrency":"USD"}}
        </script>
        <script>
        var meta = {"product":{"id":721,"variants":[{"id":412,"price":1800,"sku":"BALM-BDAY","public_title":"Birthday"}]},"page":{"pageType":"product"}};
        </script>
        <script>
        SDG.Data.productJson = {
          "id": 721,
          "title": "Lip Balm",
          "options": ["Flavor"],
          "variants": [
            {"id":412,"price":1800,"sku":"BALM-BDAY","public_title":"Birthday","option1":"Birthday","options":["Birthday"]}
          ]
        };
        </script>
        """,
        "https://shop.test/products/lip-balm",
    )

    variant = result.records[0]["variants"][0]
    assert variant["flavor"] == "Birthday"
    assert "size" not in variant
    assert "style" not in variant


def test_compact_shopify_non_size_public_title_uses_style_fallback() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Lip Balm","url":"https://shop.test/products/lip-balm","offers":{"price":"18","priceCurrency":"USD"}}
        </script>
        <script>
        var meta = {"product":{"id":721,"variants":[{"id":412,"price":1800,"sku":"BALM-BDAY","public_title":"Birthday"}]},"page":{"pageType":"product"}};
        </script>
        """,
        "https://shop.test/products/lip-balm",
    )

    variant = result.records[0]["variants"][0]
    assert variant["style"] == "Birthday"
    assert "size" not in variant


def test_internal_brand_hierarchy_materializes_leaf_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"Bambino Plus","url":"https://shop.test/products/bambino-plus","image":"https://shop.test/bambino.jpg","offers":{"price":"499.95","priceCurrency":"USD"}}
        </script>
        """,
        "https://shop.test/products/bambino-plus",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Bambino Plus",
                        "url": "https://shop.test/products/bambino-plus",
                        "brand": "breville-parent/breville",
                    }
                }
            },
        ),
    )

    assert result.records[0]["brand"] == "Breville"


def test_nested_product_config_does_not_publish_product_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main><h1>Espresso Machine</h1></main>
        <script>
        window.__INITIAL_STATE__ = {"product":{"config":{"fabricGuide":{"name":"Guide","description":"Configuration copy","brand":"Retailer"}}}};
        </script>
        """,
        "https://shop.test/products/espresso-machine",
    )

    assert result.records[0].get("brand") is None
    assert result.records[0].get("description") is None


def test_embedded_next_state_variants_materialize_without_state_artifact() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><head>
          <script id="__NEXT_DATA__" type="application/json">
          {
            "props": {"pageProps": {"product": {
              "name": "Everyday Tee",
              "variants": [
                {
                  "id": "tee-black-s",
                  "sku": "TEE-BLK-S",
                  "size": "S",
                  "current_price": "30",
                  "currency_code": "USD",
                  "availableForSale": true
                }
              ]
            }}}
          }
          </script>
        </head><body><h1>Everyday Tee</h1></body></html>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "tee-black-s",
            "sku": "TEE-BLK-S",
            "price": "30.00",
            "currency": "USD",
            "availability": "in_stock",
            "size": "S",
        }
    ]


def test_embedded_preloaded_state_variant_aliases_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><head><script>
        window.__PRELOADED_STATE__ = {
          "product": {
            "name": "Runner Shoe",
            "skuData": [
              {
                "id": "runner-blue-9",
                "skuId": "NK-RUN-BLU-9",
                "nikeSize": "9",
                "colorway": "Blue",
                "current_price": "120",
                "currency_code": "USD",
                "available": 1
              }
            ]
          }
        };
        </script></head><body><h1>Runner Shoe</h1></body></html>
        """,
        "https://shop.test/products/runner-shoe",
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "NK-RUN-BLU-9",
            "sku": "NK-RUN-BLU-9",
            "price": "120.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Blue",
            "size": "9",
        }
    ]


def test_unrelated_application_json_does_not_create_variant() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><head>
          <script type="application/json">
          {"analytics": {"id": "event-1", "price": "999", "currency": "USD"}}
          </script>
        </head><body><h1>Everyday Tee</h1></body></html>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert not result.records[0].get("variants")
    assert result.records[0].get("price") is None


def test_embedded_product_json_in_recommendation_scope_is_ignored() -> None:
    page_url = "https://shop.test/products/luna-bag"
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Luna Bag",
          "sku": "LUNA-RED",
          "url": "https://shop.test/products/luna-bag",
          "image": "https://cdn.shop.test/luna-bag-main.jpg",
          "offers": {"price": "594", "priceCurrency": "USD"}
        }
        </script>
        <main>
          <script id="__NEXT_DATA__" type="application/json">
          {
            "product": {
              "name": "Luna Bag",
              "url": "https://shop.test/products/luna-bag",
              "variants": [
                {"id": "luna-red", "sku": "LUNA-RED", "color": "Red", "size": "O/S", "current_price": "594", "currency_code": "USD", "available": true},
                {"id": "luna-black", "sku": "LUNA-BLACK", "color": "Black", "size": "O/S", "current_price": "594", "currency_code": "USD", "available": true}
              ]
            }
          }
          </script>
          <section class="pairs-well-with product-recommendations">
            <img src="https://cdn.shop.test/PL_PS25_FTW_0044.jpg" alt="#color_ant-white">
            <script type="application/json" class="pww-product-json">
            {
              "title": "Ruched Handkerchief Dress",
              "handle": "ruched-handkerchief-dress",
              "images": ["https://cdn.shop.test/ruched-dress-main.jpg"],
              "variants": [
                {"id": "dress-4", "sku": "DRESS-4", "color": "Stone", "size": "4", "price": "417", "currency": "USD", "available": true}
              ]
            }
            </script>
          </section>
        </main>
        """,
        page_url,
    )

    record = result.records[0]
    assert record["title"] == "Luna Bag"
    assert record["image_url"] == "https://cdn.shop.test/luna-bag-main.jpg"
    assert record["variants"] == [
        {
            "variant_id": "luna-black",
            "sku": "LUNA-BLACK",
            "price": "594.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Black",
            "size": "O/S",
        },
        {
            "variant_id": "luna-red",
            "sku": "LUNA-RED",
            "price": "594.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Red",
            "size": "O/S",
        },
    ]
    assert "PL_PS25_FTW_0044" not in str(record)
    assert all(
        "dress" not in str(row.value).casefold()
        and "ruched" not in str(row.value).casefold()
        for row in result.evidence
        if row.collector_id == "js_state"
    )


def test_embedded_variants_inherit_parent_jsonld_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Stan Smith Shoes",
          "url": "https://shop.test/products/stan-smith",
          "offers": {
            "@type": "Offer",
            "price": "110",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {"pageProps": {"product": {"variants": [
            {"id": "stan-8", "sku": "M20324-8", "size": "8"},
            {"id": "stan-9", "sku": "M20324-9", "size": "9"}
          ]}}}
        }
        </script>
        """,
        "https://shop.test/products/stan-smith",
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "stan-8",
            "sku": "M20324-8",
            "price": "110.00",
            "currency": "USD",
            "availability": "in_stock",
            "size": "8",
        },
        {
            "variant_id": "stan-9",
            "sku": "M20324-9",
            "price": "110.00",
            "currency": "USD",
            "availability": "in_stock",
            "size": "9",
        },
    ]
    lineage = result.records[0]["_lineage"]["variants"]
    assert all(row["price"]["rule_id"] == "PARENT_OFFER_TO_VARIANT" for row in lineage)


def test_id_preferred_variant_with_sku_inherits_parent_offer_without_options() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Stan Smith Shoes",
          "url": "https://shop.test/products/stan-smith",
          "offers": {
            "@type": "Offer",
            "price": "110",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {"pageProps": {"product": {"variants": [
            {"id": "stan-white", "sku": "M20324-WHT"}
          ]}}}
        }
        </script>
        """,
        "https://shop.test/products/stan-smith",
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "stan-white",
            "sku": "M20324-WHT",
            "price": "110.00",
            "currency": "USD",
            "availability": "in_stock",
        }
    ]
    lineage = result.records[0]["_lineage"]["variants"][0]
    assert lineage["price"]["rule_id"] == "PARENT_OFFER_TO_VARIANT"


def test_product_group_variants_have_lineage_and_parent_subjects() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Everyday Tee",
      "url": "https://shop.test/products/everyday-tee",
      "hasVariant": [
        {"@type": "Product", "sku": "TEE-BLK-S", "color": "Black", "size": "S"},
        {"@type": "Product", "sku": "TEE-BLK-M", "color": "Black", "size": "M"}
      ]
    }
    </script>
    """
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/products/everyday-tee"
    )
    assert result.verdict == "partial"
    assert {row["variant_id"]: row for row in result.records[0]["variants"]} == {
        "TEE-BLK-S": {
            "variant_id": "TEE-BLK-S",
            "sku": "TEE-BLK-S",
            "color": "Black",
            "size": "S",
        },
        "TEE-BLK-M": {
            "variant_id": "TEE-BLK-M",
            "sku": "TEE-BLK-M",
            "color": "Black",
            "size": "M",
        },
    }
    variant_evidence = [
        item for item in result.evidence if item.fact_type.startswith("variant.")
    ]
    assert variant_evidence
    assert all(item.subject_id for item in variant_evidence)
    assert all(item.parent_subject_id for item in variant_evidence)


def test_typed_commerce_detail_record_round_trip_preserves_variants() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    typed = CommerceDetailRecord.model_validate(result.records[0])
    dumped = typed.model_dump(mode="json", exclude_none=True)
    assert dumped["variants"] == result.records[0]["variants"]
    assert dumped["_lineage"]["variants"]


def test_network_product_id_selects_requested_detail_product() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main></main>",
        "https://shop.test/men/product/adidas-originals/black-samba-og-sneakers/15199881",
        network_payloads=(
            {
                "body": {
                    "products": [
                        {
                            "productId": "18701561",
                            "productName": "Black & White Out Of Office Calf Leather Sneakers",
                            "brandName": "Off-White",
                            "finalPrice": 429,
                            "currency": "USD",
                        },
                        {
                            "productId": "15199881",
                            "productName": "Black Samba OG Sneakers",
                            "brandName": "adidas Originals",
                            "finalPrice": 100,
                            "currency": "USD",
                        },
                    ]
                }
            },
        ),
    )

    assert result.records[0]["title"] == "Black Samba OG Sneakers"
    assert result.records[0]["brand"] == "adidas Originals"


def test_url_mismatched_product_title_cannot_win_detail_resolution() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/json">
        {"products":[{"productName":"Black Warped Logo Short Sleeve T-shirt","brand":"ASICS"}]}
        </script>
        """,
        "https://shop.test/men/product/adidas-originals/black-samba-og-sneakers/15199881",
    )

    assert result.records[0]["title"] == "black samba og sneakers"


def test_related_product_root_cannot_overwrite_selected_detail_entity() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Selected Trail Shoe",
        "url": "https://shop.test/products/selected-trail-shoe",
        "sku": "SEL-1",
        "offers": {"@type": "Offer", "price": "120", "priceCurrency": "USD"}
      },
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Related Day Pack",
        "url": "https://shop.test/products/day-pack",
        "sku": "REL-1",
        "offers": {"@type": "Offer", "price": "999", "priceCurrency": "USD"}
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/selected-trail-shoe",
    )
    assert result.target.status == "resolved"
    assert result.records[0]["title"] == "Selected Trail Shoe"
    assert result.records[0]["price"] == "120.00"
    assert result.records[0]["url"] == "https://shop.test/products/selected-trail-shoe"


def test_noisy_variant_root_cannot_outrank_complete_offer_product() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Soleil pant in linen",
        "url": "https://shop.test/products/soleil-pant",
        "sku": "CI939-BR8825",
        "offers": {"@type": "Offer", "price": "14273", "priceCurrency": "INR"}
      },
      {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Linen",
        "url": "https://shop.test/products/linen",
        "hasVariant": [
          {"@type": "Product", "color": "WT0002", "url": "https://api.shop.test/99107606086.html"}
        ]
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/soleil-pant?colorCode=BR8825",
    )
    assert result.records[0]["title"] == "Soleil pant in linen"
    assert result.records[0]["price"] == "14273.00"
    assert not result.records[0].get("variants")


def test_commercial_dom_size_controls_materialize_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Classic Shorts</h1>
          <button data-size="XS" data-sku="SHORT-XS" data-price="£25.00"
                  data-currency="GBP" data-stock="1">XS</button>
          <button data-size="S" data-sku="SHORT-S" data-price="£25.00"
                  data-currency="GBP" data-stock="0">S</button>
        </main>
        """,
        "https://shop.test/products/classic-shorts",
    )

    variants = result.records[0]["variants"]
    assert {(row["size"], row["availability"]) for row in variants} == {
        ("S", "out_of_stock"),
        ("XS", "in_stock"),
    }
    assert result.records[0].get("sku") is None


def test_dom_option_controls_do_not_materialize_sellable_variants() -> None:
    html = """
    <main>
      <h1>Everyday Tee</h1>
      <select name="size">
        <option>Select size</option>
        <option>S</option>
        <option>M</option>
      </select>
      <button data-option-name="color">Black</button>
    </main>
    """
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/products/everyday-tee"
    )
    assert result.records
    assert not result.records[0].get("variants")
    option_evidence = [
        item for item in result.evidence if item.fact_type.startswith("option.")
    ]
    assert option_evidence
    assert result.graph.entity_counts["option"] == 3


def test_variant_identity_merges_sources_and_materializes_child_offer() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Everyday Tee",
      "url": "https://shop.test/products/everyday-tee",
      "hasVariant": [
        {"@type": "Product", "sku": "TEE-BLK-S", "color": "Black", "size": "S"}
      ]
    }
    </script>
    """
    artifacts = {
        "js_state_objects": {
            "variant": {
                "id": "v1",
                "sku": "TEE-BLK-S",
                "color": "Black",
                "size": "S",
                "price": "18.5",
                "currency": "USD",
                "availability": "InStock",
            }
        }
    }
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/everyday-tee",
        artifacts=artifacts,
    )
    variants = result.records[0]["variants"]
    assert variants == [
        {
            "variant_id": "v1",
            "sku": "TEE-BLK-S",
            "price": "18.50",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Black",
            "size": "S",
        }
    ]
    assert result.graph.entity_counts["variant"] == 1
    assert result.records[0]["_lineage"]["variants"][0]["price"]


def test_js_state_variant_sku_aliases_materialize_public_sku() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Shoe</h1></main>",
        "https://shop.test/products/runner-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Runner Shoe",
                    "url": "https://shop.test/products/runner-shoe",
                    "variants": [
                        {
                            "variantId": "runner-blue-9",
                            "skuCode": "NK-RUN-BLU-9",
                            "color": "Blue",
                            "size": "9",
                            "price": "120",
                            "currency": "USD",
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"][0]["sku"] == "NK-RUN-BLU-9"


def test_nested_variant_options_money_inventory_and_sku_aliases_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Velvet Lip Color</h1></main>",
        "https://shop.test/products/velvet-lip-color",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Velvet Lip Color",
                    "url": "https://shop.test/products/velvet-lip-color",
                    "variants": [
                        {
                            "variantId": "rose-mini",
                            "skuCode": "LIP-ROSE-MINI",
                            "variationType": "Shade",
                            "variationValue": "Rosewood",
                            "sizeDescription": "0.1 oz",
                            "priceInfo": {
                                "currentPrice": {"amount": "28", "currencyCode": "USD"}
                            },
                            "inventory": {"inventoryStatus": "IN_STOCK"},
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "rose-mini",
            "sku": "LIP-ROSE-MINI",
            "price": "28.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Rosewood",
            "size": "0.1 oz",
        }
    ]


def test_variant_offer_inherits_parent_commercial_facts_but_keeps_child_availability() -> (
    None
):
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Court Shoe",
          "url": "https://shop.test/products/court-shoe",
          "offers": {
            "@type": "Offer",
            "price": "95",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "COURT-WHT-8",
              "color": "White",
              "size": "8",
              "offers": {
                "@type": "Offer",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "sku": "COURT-WHT-9",
              "color": "White",
              "size": "9"
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/court-shoe",
    )

    variants = result.records[0]["variants"]
    assert variants == [
        {
            "variant_id": "COURT-WHT-8",
            "sku": "COURT-WHT-8",
            "price": "95.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "White",
            "size": "8",
        },
        {
            "variant_id": "COURT-WHT-9",
            "sku": "COURT-WHT-9",
            "price": "95.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "color": "White",
            "size": "9",
        },
    ]
    lineage = result.records[0]["_lineage"]["variants"]
    assert lineage[0]["price"]["rule_id"] == "PARENT_OFFER_TO_VARIANT"
    assert lineage[0]["availability"]["rule_id"] != "PARENT_OFFER_TO_VARIANT"
    assert lineage[1]["availability"]["rule_id"] == "PARENT_OFFER_TO_VARIANT"


def test_js_state_later_product_object_backfills_missing_variant_rows() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Bootleg Pants</h1></main>",
        "https://shop.test/products/bootleg-pants",
        artifacts={
            "js_state_objects": {
                "bootstrap": {
                    "name": "Bootleg Pants",
                    "price": "1290",
                    "currency": "USD",
                },
                "hydration": {
                    "product": {
                        "name": "Bootleg Pants",
                        "url": "https://shop.test/products/bootleg-pants",
                        "variants": [
                            {
                                "variantId": "black-s",
                                "sku": "BP-BLK-S",
                                "color": "Black",
                                "size": "S",
                                "price": {"value": "1290"},
                                "currency": "USD",
                            },
                            {
                                "variantId": "black-m",
                                "sku": "BP-BLK-M",
                                "color": "Black",
                                "size": "M",
                                "price": {"value": "1290"},
                                "currency": "USD",
                            },
                        ],
                    }
                },
            }
        },
    )
    assert {row["variant_id"]: row for row in result.records[0]["variants"]} == {
        "black-s": {
            "variant_id": "black-s",
            "sku": "BP-BLK-S",
            "price": "1290.00",
            "currency": "USD",
            "color": "Black",
            "size": "S",
        },
        "black-m": {
            "variant_id": "black-m",
            "sku": "BP-BLK-M",
            "price": "1290.00",
            "currency": "USD",
            "color": "Black",
            "size": "M",
        },
    }


def test_legacy_shopify_product_json_supplies_linked_images_and_variants() -> None:
    html = """
    <html><body>
      <script id="ProductJson--product-template" hidden>
        {
          "id": 7685845516494,
          "title": "40th Anniversary Graphic Womens Short Sleeve Shirt (Black/Red)",
          "handle": "jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1",
          "vendor": "JORDAN",
          "images": [
            "//shop.test/cdn/shop/files/47b157b3d5f17c0ca8657919596ebdd7.jpg"
          ],
          "variants": [
            {"id": 43468991627470, "title": "XS", "option1": "XS", "sku": "20959706", "price": 1998, "available": true},
            {"id": 43468991660238, "title": "S", "option1": "S", "sku": "20959704", "price": 1998, "available": false}
          ],
          "options": ["Size"]
        }
      </script>
    </body></html>
    """
    url = (
        "https://shop.test/products/"
        "jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1"
    )

    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            html,
            url,
            max_records=1,
        )
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://shop.test/cdn/shop/files/47b157b3d5f17c0ca8657919596ebdd7.jpg"
    )
    assert [(row["sku"], row["size"]) for row in record["variants"]] == [
        ("20959706", "XS"),
        ("20959704", "S"),
    ]


def test_network_variant_offer_rows_materialize_with_lineage() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "data": {
                        "product": {
                            "name": "Runner Tee",
                            "url": "https://shop.test/products/runner-tee",
                            "variants": [
                                {
                                    "variantId": "navy-s",
                                    "sku": "RT-NV-S",
                                    "color": "Navy",
                                    "size": "S",
                                    "price": "35",
                                    "currency": "USD",
                                    "available": True,
                                },
                                {
                                    "variantId": "navy-m",
                                    "sku": "RT-NV-M",
                                    "color": "Navy",
                                    "size": "M",
                                    "price": "35",
                                    "currency": "USD",
                                    "available": False,
                                },
                            ],
                        }
                    }
                }
            },
        ),
    )
    assert {row["variant_id"]: row for row in result.records[0]["variants"]} == {
        "navy-s": {
            "variant_id": "navy-s",
            "sku": "RT-NV-S",
            "price": "35.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Navy",
            "size": "S",
        },
        "navy-m": {
            "variant_id": "navy-m",
            "sku": "RT-NV-M",
            "price": "35.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "color": "Navy",
            "size": "M",
        },
    }
    assert all(row["availability"] for row in result.records[0]["_lineage"]["variants"])
    assert any(
        item.artifact_id == "network_0" and item.collector_id == "network"
        for item in result.evidence
    )


def test_mixed_numeric_and_string_identity_values_do_not_crash() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": "Rustic Cotton T-Shirt",
                "sku": 123,
                "price": "29.90",
                "currency": "USD",
            }
        }
    }
    html = '<html><body><h1>Rustic Cotton T-Shirt</h1><div data-sku="123"></div></body></html>'
    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["sku"] in {123, "123"}


def test_boolean_product_title_is_rejected_before_typed_publication() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/classic-suede",
        artifacts={
            "js_state_objects": {
                "product": {
                    "title": True,
                    "price": "90",
                    "currency": "USD",
                }
            }
        },
    )

    assert result.records
    assert result.records[0].get("title") is not True
    assert not isinstance(result.records[0].get("title"), bool)
    assert any(
        item.fact_type == "product.title"
        and item.value is True
        and "invalid_scalar_type" in item.flags
        for item in result.evidence
    )


def test_integer_variant_url_is_rejected_before_typed_publication() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Old Skool Shoe</h1></main>",
        "https://shop.test/products/old-skool-shoe",
        artifacts={
            "js_state_objects": {
                "variants": [
                    {
                        "__typename": "ProductVariant",
                        "variantId": "black-9",
                        "sku": "OLD-SKOOL-BLK-9",
                        "size": "9",
                        "url": 1079,
                    }
                ]
            }
        },
    )

    variant = result.records[0]["variants"][0]
    assert variant["sku"] == "OLD-SKOOL-BLK-9"
    assert "url" not in variant
    assert any(
        item.fact_type == "variant.url"
        and item.value == 1079
        and "invalid_scalar_type" in item.flags
        for item in result.evidence
    )


def test_valid_string_title_url_and_boolean_availability_remain_unchanged() -> None:
    variant_url = "https://shop.test/products/classic-suede?variant=black-9"
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Fallback Title</h1></main>",
        "https://shop.test/products/classic-suede",
        artifacts={
            "js_state_objects": {
                "product": {
                    "title": "Classic Suede",
                    "price": "90",
                    "currency": "USD",
                    "variants": [
                        {
                            "__typename": "ProductVariant",
                            "variantId": "black-9",
                            "sku": "CLASSIC-BLK-9",
                            "size": "9",
                            "url": variant_url,
                            "available": True,
                        }
                    ],
                }
            }
        },
    )

    assert result.records[0]["title"] == "Classic Suede"
    assert result.records[0]["variants"] == [
        {
            "variant_id": "black-9",
            "sku": "CLASSIC-BLK-9",
            "price": "90.00",
            "currency": "USD",
            "url": variant_url,
            "availability": "in_stock",
            "size": "9",
        }
    ]


def test_adapter_artifact_flows_through_evidence_engine() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/adapter-widget",
        artifacts={
            "adapter_artifacts": [
                {
                    "artifact_type": "adapter_json",
                    "adapter_name": "legacy",
                    "body": {
                        "title": "Adapter Widget",
                        "sku": "AD-1",
                        "price": "10.00",
                        "currency": "USD",
                    },
                }
            ]
        },
    )
    assert result.records
    assert result.records[0]["title"] == "Adapter Widget"
    assert result.records[0]["_lineage"]["title"]
    assert any(item.artifact_id == "adapter_0" for item in result.evidence)


def test_job_detail_cutover_materializes_with_lineage() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Staff Backend Engineer",
          "hiringOrganization": {"name": "Invoro"},
          "jobLocation": {"address": {"addressLocality": "Remote", "addressCountry": "US"}},
          "datePosted": "2026-06-01",
          "employmentType": "FULL_TIME",
          "description": "Build deterministic extraction systems.",
          "url": "https://jobs.test/staff-backend-engineer"
        }
        </script>
      </head>
      <body><main><h1>Fallback Title</h1></main></body>
    </html>
    """
    result = _extract("job_detail", html, "https://jobs.test/staff-backend-engineer")
    assert result.verdict == "success"
    assert result.records[0]["title"] == "Staff Backend Engineer"
    assert result.records[0]["company"] == "Invoro"
    assert result.records[0]["location"] == "Remote, US"
    assert result.records[0]["_lineage"]["title"]
    assert result.evidence
    assert result.decisions
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_detail" for item in result.evidence)


def test_job_detail_wrong_surface_product_returns_error_without_commerce_aliases() -> (
    None
):
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Trail Shoe",
      "offers": {"@type": "Offer", "price": "129", "priceCurrency": "USD"}
    }
    </script>
    """
    result = _extract("job_detail", html, "https://jobs.test/not-a-job")
    assert result.verdict == "wrong_surface"
    assert not result.records
    assert {finding.rule_id for finding in result.findings} == {"WRONG_SURFACE_CONTENT"}


def test_job_detail_result_is_replayable() -> None:
    result = _extract(
        "job_detail",
        """
        <main>
          <h1>Staff Backend Engineer</h1>
          <div class="company">Invoro</div>
          <div class="location">Remote</div>
          <a href="/apply/staff-backend-engineer">Apply</a>
        </main>
        """,
        "https://jobs.test/staff-backend-engineer",
        max_records=1,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows and rows[0]["title"] == "Staff Backend Engineer"
    assert rows[0]["apply_url"] == "https://jobs.test/apply/staff-backend-engineer"
    assert rows[0]["_lineage"]["title"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "job_detail"
    assert payload["evidence"]
    assert payload["decisions"]


def test_job_listing_cutover_materializes_with_lineage() -> None:
    result = _extract(
        "job_listing",
        """
        <ul>
          <li class="job-card">
            <a href="/jobs/backend"><h2>Backend Engineer</h2></a>
            <span class="company">Invoro</span>
            <span class="location">Remote</span>
          </li>
          <li class="job-card">
            <a href="/jobs/data"><h2>Data Engineer</h2></a>
            <span class="company">Invoro</span>
          </li>
        </ul>
        """,
        "https://jobs.test/careers",
        max_records=5,
    )
    assert result.verdict == "success"
    assert {row["title"] for row in result.records} == {
        "Backend Engineer",
        "Data Engineer",
    }
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_listing" for item in result.evidence)


def test_job_listing_result_is_replayable() -> None:
    result = _extract(
        "job_listing",
        """
        <article class="job-card">
          <a href="/jobs/backend" title="Backend Engineer">Backend Engineer</a>
          <span class="company">Invoro</span>
        </article>
        """,
        "https://jobs.test/careers",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows and rows[0]["title"] == "Backend Engineer"
    assert rows[0]["url"] == "https://jobs.test/jobs/backend"
    assert rows[0]["_lineage"]["title"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "job_listing"
    assert payload["evidence"]
    assert payload["decisions"]


def test_job_listing_greenhouse_table_rows_materialize() -> None:
    result = _extract(
        "job_listing",
        """
        <main><table>
          <tr class="job-post">
            <td class="cell">
              <a href="https://careers.test/positions/123">
                <p class="body body--medium">Senior Data Scientist</p>
                <p class="body body__secondary body--metadata">Remote</p>
              </a>
            </td>
          </tr>
        </table></main>
        """,
        "https://job-boards.test/embed/job_board?for=company",
        max_records=5,
    )
    assert result.records
    assert result.records[0]["title"] == "Senior Data Scientist"
    assert result.records[0]["url"] == "https://careers.test/positions/123"
    assert result.records[0]["location"] == "Remote"


def test_parent_mixed_variant_prices_publish_explicit_range_semantics() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "25",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {"price": "20", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "TEE-M",
              "size": "M",
              "offers": {"price": "25", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    record = result.records[0]
    assert record["price"] == "25.00"
    assert record["price_min"] == "20.00"
    assert record["price_max"] == "25.00"
    assert (
        record["_lineage"]["price_min"]["rule_id"] == "minimum_variant_price_aggregate"
    )


def test_direct_parent_price_is_not_replaced_by_variant_aggregate() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Relaxed-Fit Printed T-Shirt",
          "url": "https://shop.test/products/printed-tee",
          "offers": {"price": "84.99", "priceCurrency": "USD"},
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "BLUE",
              "color": "Blue",
              "offers": {"price": "84.99", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "BLUE-S",
              "color": "Blue",
              "size": "S",
              "offers": {"price": "12.99", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "BLUE-M",
              "color": "Blue",
              "size": "M",
              "offers": {"price": "12.99", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/printed-tee",
    )

    record = result.records[0]
    assert record["price"] == "84.99"
    assert record.get("price_min") in (None, "12.99")
    assert record.get("price_max") in (None, "12.99")


def test_direct_parent_availability_is_not_replaced_by_variant_aggregate() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "20",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "sku": "TEE-M",
              "size": "M",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock"
              }
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    record = result.records[0]
    assert record["availability"] == "out_of_stock"
    assert (
        record["_lineage"]["availability"]["rule_id"]
        != "variant_availability_aggregate"
    )
    assert any(
        finding.rule_id == "PARENT_VARIANT_AVAILABILITY_CONFLICT"
        for finding in result.findings
    )


def test_incomplete_variant_identity_is_diagnostic_not_public_row() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {"price": "20", "priceCurrency": "USD"},
          "hasVariant": [
            {"@type": "Product", "url": "https://shop.test/products/everyday-tee?variant=1"}
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    assert not result.records[0].get("variants")
    assert any(
        finding.rule_id == "INCOMPLETE_VARIANT_EVIDENCE" for finding in result.findings
    )


def test_non_positive_price_is_not_successful_public_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trial Pack",
          "url": "https://shop.test/products/trial-pack",
          "offers": {"price": "0.00", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trial-pack",
    )
    assert result.records[0].get("price") is None
    assert result.verdict != "success"
    assert any(finding.rule_id == "NON_POSITIVE_PRICE" for finding in result.findings)


def test_parent_availability_does_not_override_incomplete_variant_matrix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "20",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
              }
            },
            {"@type": "Product", "url": "https://shop.test/products/everyday-tee?variant=2"}
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    assert result.records[0]["availability"] == "out_of_stock"
    assert (
        result.records[0]["_lineage"]["availability"]["rule_id"]
        != "variant_availability_aggregate"
    )


def test_detail_url_falls_back_to_canonical_capture_url() -> None:
    canonical_url = "https://shop.test/products/trail-shoe"
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type": "Product", "name": "Trail Shoe", "offers": {"price": "10", "priceCurrency": "USD"}}
        </script>
        """,
        canonical_url,
    )
    assert len(result.records) == 1
    typed = CommerceDetailRecord.model_validate(result.records[0])
    assert CommerceDetailRecord.model_fields["url"].is_required()
    assert typed.url == canonical_url
    assert result.records[0]["url"] == canonical_url


def test_detail_product_url_outranks_storefront_root_and_brand_tagline_is_trimmed() -> (
    None
):
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="og:url" content="https://shop.test">
        <script type="application/ld+json">
        {"@type":"Product","name":"Arrival Shorts","brand":"Gymshark | We Do Gym","url":"https://shop.test/products/arrival-shorts","image":"https://shop.test/arrival-shorts.jpg","offers":{"price":"20","priceCurrency":"USD"}}
        </script>
        """,
        "https://shop.test/products/arrival-shorts",
    )

    assert result.records[0]["url"] == "https://shop.test/products/arrival-shorts"
    assert result.records[0]["brand"] == "Gymshark"


def test_utility_image_cannot_beat_product_image() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "image": [
            "https://shop.test/assets/discount.svg",
            "https://shop.test/products/trail-shoe-main.jpg"
          ],
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )
    assert (
        result.records[0]["image_url"]
        == "https://shop.test/products/trail-shoe-main.jpg"
    )


def test_product_asset_decision_materializes_primary_and_additional_images() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <meta property="og:image" content="https://shop.test/assets/logo.svg">
            <script type="application/ld+json">
            {
              "@type": "Product",
              "name": "Trail Shoe",
              "url": "https://shop.test/products/trail-shoe",
              "image": [
                "https://shop.test/products/trail-shoe-main.jpg",
                "https://shop.test/products/trail-shoe-side.jpg",
                "https://shop.test/assets/payment-visa.gif",
                "https://shop.test/products/trail-shoe-diagram.svg"
              ],
              "offers": {"price": "10", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body>
            <img src="https://shop.test/assets/loader.gif">
            <img src="https://shop.test/products/trail-shoe-dom.jpg">
          </body>
        </html>
        """,
        "https://shop.test/products/trail-shoe",
    )

    record = result.records[0]
    assert record["image_url"] == "https://shop.test/products/trail-shoe-main.jpg"
    assert record["additional_images"] == [
        "https://shop.test/products/trail-shoe-side.jpg",
        "https://shop.test/products/trail-shoe-diagram.svg",
    ]
    lineage = record["_lineage"]
    assert lineage["image_url"]["rule_id"] == "PRODUCT_ASSET_PRIMARY"
    assert lineage["image_url"]["evidence_ids"]
    assert [item["rule_id"] for item in lineage["additional_images"]] == [
        "PRODUCT_ASSET_ADDITIONAL",
        "PRODUCT_ASSET_ADDITIONAL",
    ]


def test_js_state_related_products_do_not_contaminate_product_assets() -> None:
    product_url = "https://www.backmarket.com/en-us/p/iphone-15-plus"
    result = _extract(
        "ecommerce_detail",
        "<main><h1>iPhone 15 Plus</h1></main>",
        product_url,
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "iPhone 15 Plus",
                    "url": product_url,
                    "images": [
                        "https://cdn.backmarket.test/iphone-15-plus-front.jpg",
                        "https://cdn.backmarket.test/iphone-15-plus-back.jpg",
                    ],
                    "price": "799",
                    "currency": "USD",
                },
                "relatedProducts": [
                    {
                        "name": "PlayStation 4 Console",
                        "url": "https://www.backmarket.com/en-us/p/playstation-4",
                        "image": (
                            "https://cdn.backmarket.test/"
                            "playstation_4_-_2_manettes_et_plus_noir.jpg"
                        ),
                        "price": "199",
                        "currency": "USD",
                    }
                ],
            }
        },
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.backmarket.test/iphone-15-plus-front.jpg"
    )
    assert record["additional_images"] == [
        "https://cdn.backmarket.test/iphone-15-plus-back.jpg"
    ]


def test_network_recommendation_products_do_not_contaminate_detail_record() -> None:
    page_url = "https://shop.test/products/breville-bambino-plus"
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Breville Bambino Plus",
          "brand": "Breville",
          "url": "https://shop.test/products/breville-bambino-plus",
          "image": [
            "https://cdn.shop.test/breville-bambino-plus-main.jpg",
            "https://cdn.shop.test/breville-bambino-plus-side.jpg"
          ],
          "offers": {"price": "499.95", "priceCurrency": "USD"}
        }
        </script>
        """,
        page_url,
        network_payloads=(
            {
                "body": {
                    "placements": [
                        {
                            "products": [
                                {
                                    "name": "DeLonghi Classic Espresso Machine",
                                    "url": "products/delonghi-classic-espresso-machine/",
                                    "image": "202618/0006/delonghi-classic-espresso-machine-1-h.jpg",
                                    "price": "199.95",
                                    "currency": "USD",
                                }
                            ]
                        }
                    ],
                    "links": [
                        {
                            "name": "Cuisinart Espresso Bar Slim Espresso Machine",
                            "image": "wcm/202610/0027/img15",
                            "price": "249.95",
                            "currency": "USD",
                        }
                    ],
                }
            },
        ),
    )

    record = result.records[0]
    assert record["title"] == "Breville Bambino Plus"
    assert record["brand"] == "Breville"
    assert record["price"] == "499.95"
    assert record["image_url"] == (
        "https://cdn.shop.test/breville-bambino-plus-main.jpg"
    )
    assert record["additional_images"] == [
        "https://cdn.shop.test/breville-bambino-plus-side.jpg"
    ]
    assert all(
        not {"delonghi", "cuisinart", "img15"}
        & set(str(row.value).casefold().replace("/", " ").split())
        for row in result.evidence
        if row.collector_id == "network"
    )


def test_valid_shopify_gallery_images_remain_materialized() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Follow The Road Pullover Hoodie",
          "url": "https://shop.test/products/follow-the-road-pullover-hoodie",
          "image": [
            "https://cdn.shopify.com/s/files/1/0001/files/hoodie-front.jpg?v=1",
            "https://cdn.shopify.com/s/files/1/0001/files/hoodie-back.jpg?v=2"
          ],
          "offers": {"price": "120", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/follow-the-road-pullover-hoodie",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shopify.com/s/files/1/0001/files/hoodie-front.jpg?v=1"
    )
    assert record["additional_images"] == [
        "https://cdn.shopify.com/s/files/1/0001/files/hoodie-back.jpg?v=2"
    ]


def test_structured_gallery_rejects_semantic_cross_product_images() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Breville Bambino Plus Espresso Machine",
          "url": "https://shop.test/products/breville-the-bambino-plus",
          "image": [
            "https://cdn.shop.test/breville-bambino-plus-espresso-machine-main.jpg",
            "https://cdn.shop.test/breville-bambino-plus-espresso-machine-side.jpg",
            "https://cdn.shop.test/breville-bambino-espresso-machine-detail.jpg",
            "https://cdn.shop.test/breville-juice-fountain-cold-xl.jpg",
            "https://cdn.shop.test/breville-toast-select-luxe-2-slice-toaster.jpg",
            "https://cdn.shop.test/red-front.jpg"
          ],
          "offers": {"price": "499.95", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/breville-the-bambino-plus",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shop.test/breville-bambino-plus-espresso-machine-main.jpg"
    )
    assert set(record["additional_images"]) == {
        "https://cdn.shop.test/breville-bambino-plus-espresso-machine-side.jpg",
        "https://cdn.shop.test/breville-bambino-espresso-machine-detail.jpg",
        "https://cdn.shop.test/red-front.jpg",
    }


def test_structured_gallery_rejects_conflicting_product_codes() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Dime Soft Rock Crewneck",
          "url": "https://shop.test/products/dime-soft-rock-crewneck-dime2sp2542blk",
          "sku": "DIME2SP2542BLK",
          "image": [
            "https://cdn.shop.test/files/DIME2SP2542BLK-1.jpg",
            "https://cdn.shop.test/files/DIME2SP2542BLK-2.jpg",
            "https://cdn.shop.test/files/M20324-01.jpg",
            "https://cdn.shop.test/files/FZ4675-744_01.jpg"
          ],
          "offers": {"price": "120", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/dime-soft-rock-crewneck-dime2sp2542blk",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/files/DIME2SP2542BLK-1.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/files/DIME2SP2542BLK-2.jpg"
    ]


def test_structured_gallery_uses_product_identity_not_first_image_as_anchor() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Dime Soft Rock Crewneck",
          "url": "https://shop.test/products/dime-soft-rock-crewneck-dime2sp2542blk",
          "sku": "DIME2SP2542BLK",
          "image": [
            "https://cdn.shop.test/files/M20324-01.jpg",
            "https://cdn.shop.test/files/DIME2SP2542BLK-1.jpg",
            "https://cdn.shop.test/files/DIME2SP2542BLK-2.jpg"
          ],
          "offers": {"price": "120", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/dime-soft-rock-crewneck-dime2sp2542blk",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/files/DIME2SP2542BLK-1.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/files/DIME2SP2542BLK-2.jpg"
    ]


def test_structured_gallery_rejects_conflicting_numeric_product_ids() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Lightweight Barrel Pants",
          "url": "https://shop.test/products/lightweight-barrel-pants/prd/210397084",
          "image": [
            "https://cdn.shop.test/images/210397084-1.jpg",
            "https://cdn.shop.test/images/210397084-2.jpg",
            "https://cdn.shop.test/images/209999999-1.jpg",
            "https://cdn.shop.test/images/208888888-2.jpg"
          ],
          "offers": {"price": "65", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/lightweight-barrel-pants/prd/210397084",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/images/210397084-1.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/images/210397084-2.jpg"
    ]


def test_banner_ugc_and_video_still_assets_are_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Premium Linen Shirt",
          "url": "https://shop.test/products/premium-linen-shirt",
          "image": [
            "https://cdn.shop.test/products/premium-linen-shirt-main.jpg",
            "https://cdn.shop.test/sub_banners/womens-accessories-handbags.jpg",
            "https://api.shop.test/ugc/SR_NETWORK_IMAGES/stylehint.png",
            "https://api.shop.test/ugc/v1/images/ugc_stylehint_user_123",
            "https://embed-ssl.wistia.com/deliveries/video-still.jpg",
            "https://image.shop.test/catalog/related-item._AC_SS300_V1_.jpg"
          ],
          "offers": {"price": "49.90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/premium-linen-shirt",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shop.test/products/premium-linen-shirt-main.jpg"
    )
    assert not record.get("additional_images")


def test_measurement_palette_review_and_sales_badge_assets_are_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Velcro Strap Set-up Blazer Pants",
          "url": "https://shop.test/products/velcro-strap-set-up",
          "image": [
            "https://media-assets.shop.test/prd/listing/46751774/product-main.jpg",
            "https://media-assets.shop.test/prd/measurement-type/3aa45206cf50493aaf9fbe60fdc235ac",
            "https://media-assets.shop.test/prd/colors/beige.png",
            "https://cdn-yotpo-images-production.yotpo.com/Product/911368921/766183162/square.jpg",
            "https://images.shop.test/assets/SellingFastLightMode.gif"
          ],
          "offers": {"price": "1012", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/velcro-strap-set-up",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://media-assets.shop.test/prd/listing/46751774/product-main.jpg"
    )
    assert not record.get("additional_images")


def test_video_thumbnail_is_not_a_product_gallery_asset() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Arizona Sandal",
          "url": "https://shop.test/products/arizona-sandal",
          "image": [
            "https://cdn.shop.test/images/arizona-main.jpg",
            "https://cdn.shop.test/images/arizona-side.jpg",
            "https://i.ytimg.com/vi/UaGZUwhd5ZU/default.jpg"
          ],
          "offers": {"price": "115", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/arizona-sandal",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/images/arizona-main.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/images/arizona-side.jpg"
    ]


def test_unanchored_alphanumeric_gallery_is_preserved() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Studio Jacket",
          "url": "https://shop.test/products/studio-jacket",
          "image": [
            "https://cdn.shop.test/images/studio123-front.jpg",
            "https://cdn.shop.test/images/editorial456-back.jpg"
          ],
          "offers": {"price": "180", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/studio-jacket",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/images/studio123-front.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/images/editorial456-back.jpg"
    ]


def test_opaque_structured_gallery_is_preserved_without_identity_anchor() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Studio Jacket",
          "url": "https://shop.test/products/studio-jacket",
          "image": [
            "https://cdn.shop.test/images/4f8c9d2a7b31-front.jpg",
            "https://cdn.shop.test/images/7a2e1c8d9f44-back.jpg"
          ],
          "offers": {"price": "180", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/studio-jacket",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/images/4f8c9d2a7b31-front.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/images/7a2e1c8d9f44-back.jpg"
    ]


def test_product_asset_filter_rejects_utility_carrier_flag_and_template_urls() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "image": [
            "https://cdn.shop.test/products/trail-shoe-main.jpg",
            "https://cdn.shop.test/products/trail-shoe-side.jpg",
            "https://cdn.shop.test/payments/Afterpay.svg",
            "https://cdn.shop.test/carriers/att.png",
            "https://cdn.shop.test/ui/left-arrow.svg",
            "https://cdn.shop.test/ui/edit.abcdef12.svg",
            "https://cdn.shop.test/ui/pig.310ddaac.svg",
            "https://cdn.shop.test/ui/Combined_Shape__2_.svg",
            "https://cdn.shop.test/ui/Order.svg",
            "https://cdn.shop.test/payments/mastercard-card.svg",
            "https://cdn.shop.test/reviews/Surfacing_Reviews_Landing_Page_on_PDP.jpg",
            "https://cdn.shop.test/images/__IMAGE_PARAMS__/trail-shoe.jpg",
            "https://cdn.shop.test/ab/images/dp/",
            "https://shop.test/collections/shoes/products/Trail%20Shoe",
            "https://cdn.shop.test/products/trail-shoe/format%26cs%3Dsrgb",
            "https://cdn.shop.test/flags/us.png",
            "https://cdn.shop.test/category/summer-collection-banner.jpg",
            "https://cdn.shop.test/dropdown/toy-directory-thumbnail.jpg",
            "https://cdn.shop.test/products/trail-shoe.jpg?w={width}"
          ],
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/products/trail-shoe-main.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/products/trail-shoe-side.jpg",
    ]


def test_product_asset_filter_rejects_tiny_peer_and_transparent_placeholder() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Rustic Cotton T-Shirt",
          "url": "https://shop.test/products/rustic-cotton-t-shirt",
          "image": [
            "https://cdn.shop.test/assets/opaque-main.jpg?w=1920",
            "https://cdn.shop.test/assets/opaque-side.jpg?w=1600",
            "https://cdn.shop.test/assets/a1b2c3.jpg?w=66",
            "https://cdn.shop.test/images/transparent-background.png"
          ],
          "offers": {"price": "14.90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/rustic-cotton-t-shirt",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/assets/opaque-main.jpg?w=1920"
    assert record["additional_images"] == [
        "https://cdn.shop.test/assets/opaque-side.jpg?w=1600"
    ]


def test_dom_product_gallery_excludes_recommendations_accessories_and_flags() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main>
          <section class="product-gallery">
            <img src="https://cdn.shop.test/products/trail-shoe-main.jpg">
            <img src="https://cdn.shop.test/products/trail-shoe-side.jpg">
          </section>
          <section class="product-recommendations">
            <img src="https://cdn.shop.test/products/day-pack-main.jpg">
          </section>
          <section class="complete-the-look accessories">
            <img src="https://cdn.shop.test/products/shoe-cleaner.jpg">
          </section>
          <aside class="carrier-logos">
            <img src="https://cdn.shop.test/carriers/verizon.png">
          </aside>
        </main>
        <footer><img src="https://cdn.shop.test/flags/gb.png"></footer>
        """,
        "https://shop.test/products/trail-shoe",
    )

    record = result.records[0]
    assert record["image_url"] == "https://cdn.shop.test/products/trail-shoe-main.jpg"
    assert record["additional_images"] == [
        "https://cdn.shop.test/products/trail-shoe-side.jpg",
    ]


def test_lazy_dom_product_images_are_collected_from_data_src_and_srcset() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main>
          <section class="product-gallery">
            <img src="https://cdn.shop.test/placeholder.svg"
                 data-src="https://cdn.shop.test/products/trail-shoe-main.jpg">
            <picture>
              <source srcset="https://cdn.shop.test/products/trail-shoe-side-small.jpg 480w, https://cdn.shop.test/products/trail-shoe-side.jpg 1200w">
            </picture>
          </section>
        </main>
        """,
        "https://shop.test/products/trail-shoe",
    )

    assert result.records[0]["image_url"] == (
        "https://cdn.shop.test/products/trail-shoe-main.jpg"
    )
    assert result.records[0]["additional_images"] == [
        "https://cdn.shop.test/products/trail-shoe-side.jpg"
    ]


def test_srcset_parser_preserves_commas_inside_cdn_image_urls() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe"
        }
        </script>
        <main>
          <section class="product-gallery">
            <source srcset="https://cdn.shop.test/trail-shoe_SR1840,1472.webp 1840w, https://cdn.shop.test/trail-shoe_SR920,736.webp 920w">
          </section>
        </main>
        """,
        "https://shop.test/products/trail-shoe",
    )

    assert result.records[0]["image_url"] == (
        "https://cdn.shop.test/trail-shoe_SR1840%2C1472.webp"
    )


def test_single_admissible_main_image_remains_a_dom_fallback() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main><img src="https://cdn.shop.test/products/trail-shoe-main.jpg"></main>
        """,
        "https://shop.test/products/trail-shoe",
    )

    assert (
        result.records[0]["image_url"]
        == "https://cdn.shop.test/products/trail-shoe-main.jpg"
    )


def test_unscoped_main_image_gallery_does_not_leak_as_product_images() -> None:
    # Several un-scoped <img> in <main> with no positive product-image scope is
    # almost always a gallery/recommendation grid. None of them should be
    # admitted as the product image (AUD-03); the single-image fallback only
    # fires when there is exactly one admissible candidate.
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        <main>
          <img src="https://cdn.shop.test/recommended/alpha.jpg">
          <img src="https://cdn.shop.test/recommended/bravo.jpg">
          <img src="https://cdn.shop.test/recommended/charlie.jpg">
        </main>
        """,
        "https://shop.test/products/trail-shoe",
    )

    record = result.records[0]
    leaked = {
        "https://cdn.shop.test/recommended/alpha.jpg",
        "https://cdn.shop.test/recommended/bravo.jpg",
        "https://cdn.shop.test/recommended/charlie.jpg",
    }
    assert record.get("image_url", "") not in leaked
    assert not (set(record.get("additional_images", [])) & leaked)


def test_asset_urls_are_normalized_and_deduped_without_dropping_variant_params() -> (
    None
):
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "image": [
            "https://cdn.shop.test/images/Trail Shoe.jpg?width=800",
            "https://cdn.shop.test/images/Trail%20Shoe.jpg?width=1200",
            "https://cdn.shop.test/images/Trail Shoe.jpg?color=red&width=800"
          ],
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )

    record = result.records[0]
    assert (
        record["image_url"]
        == "https://cdn.shop.test/images/Trail%20Shoe.jpg?width=1200"
    )
    assert record["additional_images"] == [
        "https://cdn.shop.test/images/Trail%20Shoe.jpg?color=red&width=800",
    ]
    assert record["image_url"] not in record["additional_images"]


def test_larger_transform_wins_for_same_asset_identity() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Chuck 70 Canvas",
          "url": "https://shop.test/products/chuck-70-canvas",
          "image": [
            "https://cdn.shop.test/products/chuck-70-canvas.jpg?width=71",
            "https://cdn.shop.test/products/chuck-70-canvas.jpg?width=1600",
            "https://cdn.shop.test/products/chuck-70-canvas-side.jpg?width=1400"
          ],
          "offers": {"price": "95", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/chuck-70-canvas",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shop.test/products/chuck-70-canvas.jpg?width=1600"
    )
    assert record["additional_images"] == [
        "https://cdn.shop.test/products/chuck-70-canvas-side.jpg?width=1400"
    ]


def test_https_asset_wins_over_equivalent_http_url() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Pavlova Boots",
          "url": "https://shop.test/products/pavlova-boots",
          "image": [
            "http://cdn.shop.test/products/pavlova-boots-01.jpg?width=1200",
            "https://cdn.shop.test/products/pavlova-boots-01.jpg?width=1800",
            "https://cdn.shop.test/products/pavlova-boots-02.jpg?width=1800"
          ],
          "offers": {"price": "1865", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/pavlova-boots",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shop.test/products/pavlova-boots-01.jpg?width=1800"
    )
    assert record["additional_images"] == [
        "https://cdn.shop.test/products/pavlova-boots-02.jpg?width=1800"
    ]


def test_variant_price_range_materializes_lowest_price_and_bounds() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Cloud Tee",
          "url": "https://shop.test/products/cloud-tee",
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {"price": "20", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "TEE-L",
              "size": "L",
              "offers": {"price": "24", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/cloud-tee",
    )

    record = result.records[0]
    assert record["price"] == "20.00"
    assert record["price_min"] == "20.00"
    assert record["price_max"] == "24.00"
    assert record["currency"] == "USD"
    assert record["_lineage"]["price"]["rule_id"] == ("minimum_variant_price_aggregate")


def test_missing_requested_field_has_visible_finding() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            '<script type="application/ld+json">{"@type":"Product","name":"Trail Shoe"}</script>',
            "https://shop.test/products/trail-shoe",
            requested_fields=("brand",),
        )
    )
    findings = [
        finding
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
    ]
    assert any(finding.metadata.get("field") == "brand" for finding in findings)
    assert result.verdict in {"partial", "review"}


def test_missing_core_detail_fields_request_one_rendered_capability() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Espresso Machine</h1></main>",
        "https://shop.test/products/espresso-machine",
    )

    assert result.retry_request is not None
    assert result.retry_request.reason == "dynamic_content_missing"
    assert result.retry_request.required_artifacts == (
        "rendered_html",
        "network_payloads",
    )
    assert result.retry_request.max_attempts == 1


def test_explicit_variant_controls_request_rendered_capability_without_field_request() -> (
    None
):
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Everyday Tee</h1>
          <label>Size</label><select><option>S</option><option>M</option></select>
        </main>
        """,
        "https://shop.test/products/everyday-tee",
    )

    assert not result.records[0].get("variants")
    assert result.retry_request is not None
    assert result.retry_request.reason == "explicit_variants_missing"
    assert result.retry_request.max_attempts == 1


def test_missing_requested_variants_requests_one_rendered_capability() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            """
            <main>
              <h1>Everyday Tee</h1>
              <label>Size</label><select><option>S</option><option>M</option></select>
            </main>
            """,
            "https://shop.test/products/everyday-tee",
            requested_fields=("variants",),
        )
    )
    assert not result.records[0].get("variants")
    assert result.retry_request is not None
    assert result.retry_request.reason == "explicit_variants_missing"
    assert result.retry_request.max_attempts == 1


def test_explicit_size_axis_missing_from_variants_has_visible_finding() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Court Shoe",
          "url": "https://shop.test/products/court-shoe",
          "hasVariant": [
            {"@type": "Product", "sku": "COURT-BLK", "color": "Black"},
            {"@type": "Product", "sku": "COURT-WHT", "color": "White"}
          ]
        }
        </script>
        <main>
          <label>Size</label><select><option>8</option><option>9</option></select>
        </main>
        """,
        "https://shop.test/products/court-shoe",
    )

    finding = next(
        item
        for item in result.findings
        if item.rule_id == "EXPECTED_VARIANT_AXIS_MISSING"
    )
    assert finding.metadata["axis"] == "size"
    assert finding.metadata["missing_variant_count"] == 2
    assert result.verdict in {"partial", "review"}


def test_variant_price_without_currency_is_not_public_variant_price() -> None:
    result = _extract(
        "ecommerce_detail",
        '<script type="application/ld+json">{"@type":"ProductGroup","name":"Performance Sock","url":"https://shop.test/products/performance-sock","hasVariant":[{"@type":"Product","sku":"SOCK-M","size":"M","offers":{"price":"18"}}]}</script>',
        "https://shop.test/products/performance-sock",
    )

    variant = result.records[0]["variants"][0]
    assert "price" not in variant
    assert "currency" not in variant
    assert any(item.rule_id == "PRICE_WITHOUT_CURRENCY" for item in result.findings)


def test_variant_stock_quantity_derives_availability() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Performance Sock</h1></main>",
        "https://shop.test/products/performance-sock",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Performance Sock",
                    "url": "https://shop.test/products/performance-sock",
                    "variants": [
                        {
                            "variantId": "SOCK-M",
                            "sku": "SOCK-M",
                            "size": "M",
                            "price": "18",
                            "currency": "USD",
                            "stockQuantity": 4,
                        },
                        {
                            "variantId": "SOCK-L",
                            "sku": "SOCK-L",
                            "size": "L",
                            "price": "18",
                            "currency": "USD",
                            "stockQuantity": 0,
                        },
                    ],
                }
            }
        },
    )

    assert {
        row["size"]: row["availability"] for row in result.records[0]["variants"]
    } == {
        "L": "out_of_stock",
        "M": "in_stock",
    }
    assert not any(
        item.rule_id == "VARIANT_AVAILABILITY_MISSING" for item in result.findings
    )
    assert not any(
        row.metadata.get("derived_by") == "availability_from_stock_quantity"
        for row in result.evidence
    )
    assert any(
        row.rule_id == "availability_from_stock_quantity"
        for row in result.derived_facts
    )


def test_price_symbol_currency_is_resolve_derived_not_normalized_evidence() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "offers": {"price": "$42.95"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )

    record = result.records[0]
    assert record["price"] == "42.95"
    assert record["currency"] == "USD"
    assert not any(
        row.metadata.get("derived_by") == "currency_from_price_symbol"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "offer.currency"
        and row.rule_id == "currency_from_price_symbol"
        for row in result.derived_facts
    )


def test_jsonld_variant_name_recovers_explicit_size_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "ProductGroup",
          "name": "Court Shoe",
          "url": "https://shop.test/products/court-shoe",
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "COURT-BLK-9",
              "name": "Court Shoe - Black - 9",
              "offers": {"price": "95", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/court-shoe",
    )

    assert result.records[0]["variants"][0]["size"] == "9"


def test_variant_offer_without_availability_emits_finding() -> None:
    result = _extract(
        "ecommerce_detail",
        '<script type="application/ld+json">{"@type":"ProductGroup","name":"Performance Sock","url":"https://shop.test/products/performance-sock","hasVariant":[{"@type":"Product","sku":"SOCK-M","size":"M","offers":{"price":"18","priceCurrency":"USD"}}]}</script>',
        "https://shop.test/products/performance-sock",
    )

    assert any(
        item.rule_id == "VARIANT_AVAILABILITY_MISSING" for item in result.findings
    )


def test_missing_requested_variants_without_dom_cues_requests_browser() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            "<main><h1>Everyday Tee</h1></main>",
            "https://shop.test/products/everyday-tee",
            requested_fields=("variants",),
        )
    )
    assert not result.records[0].get("variants")
    assert result.retry_request is not None
    assert result.retry_request.reason == "explicit_variants_missing"


def test_ingredient_style_percentages_do_not_trigger_missing_separator() -> None:
    description = (
        "A brightening C15% complex, A2% serum, and niacinamide10% complex "
        "for daily use."
    )
    result = _extract(
        "ecommerce_detail",
        f"""
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Daily Brightening Serum",
          "brand": "Example Labs",
          "description": {json.dumps(description)},
          "image": "https://shop.test/images/serum.jpg",
          "url": "https://shop.test/products/daily-brightening-serum"
        }}
        </script>
        """,
        "https://shop.test/products/daily-brightening-serum",
        requested_fields=("description",),
    )

    assert result.records[0]["description"] == description
    assert all(
        "description_missing_separator" not in evidence.flags
        for evidence in result.evidence
        if evidence.fact_type == "product.description"
    )


def test_compacted_description_still_triggers_missing_separator() -> None:
    description = "Crewneck100% CottonHeavyweight 14ozScreen printed logoPre-shrunk"
    result = _extract(
        "ecommerce_detail",
        f"""
        <script type="application/ld+json">
        {{
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Heavyweight Crewneck",
          "brand": "Example",
          "description": {json.dumps(description)},
          "image": "https://shop.test/images/crewneck.jpg",
          "url": "https://shop.test/products/heavyweight-crewneck"
        }}
        </script>
        """,
        "https://shop.test/products/heavyweight-crewneck",
        requested_fields=("description",),
    )

    assert any(
        "description_missing_separator" in evidence.flags
        for evidence in result.evidence
        if evidence.fact_type == "product.description"
    )
    assert result.records[0].get("description") is None


def test_direct_brand_evidence_outranks_url_derived_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Trail Shoe",
          "brand": {"@type": "Brand", "name": "Direct Brand"},
          "description": "A durable trail shoe for daily training.",
          "image": "https://shop.test/images/trail-shoe.jpg",
          "url": "https://shop.test/products/url-brand-trail-shoe"
        }
        </script>
        """,
        "https://shop.test/products/url-brand-trail-shoe",
    )

    assert result.records[0]["brand"] == "Direct Brand"


def test_product_scoped_demandware_and_nike_images_are_valid_assets() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <meta property="og:image" content="https://www.converse.com/dw/image/v2/BCZC_PRD/on/demandware.static/-/Sites-cnv-master-catalog/default/dw85fac320/images/a_107/A16914C_A_107X1.jpg?sw=406&amp;strip=false">
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "Chuck Taylor All Star Retro Embroidery",
              "url": "https://www.converse.com/shop/p/chuck-taylor-all-star-retro-embroidery-womens-high-top-shoe/A16914F.html"
            }
            </script>
            <script>
            window.__STATE__ = {"recommendations":[{"name":"Nike Air Force 1 '07","url":"https://www.nike.com/t/air-force-1-07-mens-shoes","image":"https://static.nike.com/a/images/t_default/u_9ddf04c7-2a9a-4d76-add1-d15af8f0263d,c_scale,fl_relative,w_1.0,h_1.0,fl_layer_apply/b7d9211c-26e7-431a-ac24-b0540fb3c00f/AIR+FORCE+1+%2707.png"}]};
            </script>
          </head>
        </html>
        """,
        "https://www.converse.com/shop/p/chuck-taylor-all-star-retro-embroidery-womens-high-top-shoe/A16914F.html",
    )

    record = result.records[0]
    assert record["image_url"].startswith("https://www.converse.com/dw/image/")
    assert all("nike.com" not in url for url in record["additional_images"])


def test_jsonld_brand_beats_dom_category_noise() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@context": "https://schema.org",
              "@type": "Product",
              "name": "EOS R5 Body",
              "brand": {"@type": "Brand", "name": "Canon"},
              "url": "https://www.usa.canon.com/shop/p/eos-r5",
              "image": "https://s7d1.scene7.com/is/image/canon/4147C002_eos-r5-body_primary?fmt=webp-alpha",
              "offers": {"price": "2599", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body><main><span class="product-brand">Webcam</span></main></body>
        </html>
        """,
        "https://www.usa.canon.com/shop/p/eos-r5",
    )

    assert result.records[0]["brand"] == "Canon"


def test_structured_vendor_beats_site_identity_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"40th Anniversary Graphic Womens Short Sleeve Shirt - Shoe Palace","url":"https://www.shoepalace.com/products/jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1"}
        </script>
        <script id="ProductJson--product-template" type="application/json">
        {"title":"40th Anniversary Graphic Womens Short Sleeve Shirt (Black/Red)","vendor":"JORDAN","handle":"jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1"}
        </script>
        """,
        "https://www.shoepalace.com/products/jordan-hj0139-045-40th-anniversary-graphic-womens-short-sleeve-shirt-black-red-1",
    )

    assert result.records[0]["brand"] == "JORDAN"


def test_structured_brand_beats_technology_marker_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script>
        window.__PRELOADED_STATE__ = {
          "product": {
            "name": "Women's Chill River Midi Dress",
            "brand": "Columbia",
            "c_overview": [{"options": {"name": "Omni-Freeze™"}}]
          }
        };
        </script>
        <main><h1>Women's Chill River Midi Dress</h1></main>
        """,
        "https://www.columbia.com/p/womens-chill-river-midi-dress-1933601.html",
    )

    assert result.records[0]["brand"] == "Columbia"


def test_uppercase_title_token_brand_can_be_derived_from_url() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="og:title" content="Women's HOKA Bondi 9">
        <main><h1>HOKA Bondi 9 Women's</h1></main>
        """,
        "https://www.zappos.com/p/womens-hoka-bondi-9-alabaster-birch/product/9984296/color/1108576",
    )

    assert result.records[0]["brand"] == "HOKA"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "HOKA"
        and row.rule_id == "brand_from_product_url"
        for row in result.derived_facts
    )


def test_master_sku_does_not_publish_variant_id_when_style_code_exists() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script>
        var meta = {"product":{"id":8659664797930,"title":"Jordan Air Jordan 5 Retro White Metallic","handle":"jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103","tags":["#HQ7978-103","stylenumber_HQ7978-103"],"variants":[{"id":45993954607338,"title":"11","option1":"11","sku":"19468100031","price":21500}]}};
        </script>
        <main><h1>Air Jordan 5 Retro White Metallic</h1></main>
        """,
        "https://www.dtlr.com/products/jordan-air-jordan-5-retro-white-metallic-mf-white-hq7978-103",
    )

    record = result.records[0]
    assert record.get("sku") == "HQ7978-103"
    assert record.get("sku") != "45993954607338"
    assert not any(
        row.metadata.get("derived_by") == "sku_from_url_style_code"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "product.sku"
        and row.value == "HQ7978-103"
        and row.rule_id == "sku_from_url_style_code"
        for row in result.derived_facts
    )


def test_opengraph_price_currency_pair_survives_product_page() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="og:title" content="Technics SL-1200MK7">
        <meta property="og:price:amount" content="186,000.00">
        <meta property="og:price:currency" content="INR">
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Technics SL-1200MK7",
          "url": "https://www.therevolverclub.com/products/technics-sl-1200mk7",
          "image": "https://www.therevolverclub.com/cdn/shop/files/technics-sl-1200mk7-silver.jpg",
          "offers": {"price": 186000.0, "priceCurrency": "INR"}
        }
        </script>
        """,
        "https://www.therevolverclub.com/products/technics-sl-1200mk7",
    )

    record = result.records[0]
    assert record["price"] == "186000.00"
    assert record["currency"] == "INR"


def test_product_title_cleanup_prefers_clean_name_over_site_suffix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <title>ILCE-9M3 | Interchangeable-lens Cameras | Sony India</title>
        <meta property="og:title" content="ILCE-9M3 | Interchangeable-lens Cameras | Sony India">
        <script>
        window.aemConfig = {"productName": "ILCE-9M3", "productCode": "ILCE-9M3"};
        </script>
        """,
        "https://www.sony.co.in/interchangeable-lens-cameras/products/ilce-9m3?sku=ilce-9m3-in5",
    )

    assert result.records[0]["title"] == "ILCE-9M3"


def test_leading_symbol_title_is_cleaned_when_url_has_clean_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <meta property="og:title" content="+ Bulgari Vintage 1980s Doppio Cuore bracelet - gold - One Size">
        <script type="application/ld+json">
        {"@context":"https://schema.org","@type":"Product","name":"+ Bulgari Vintage 1980s Doppio Cuore bracelet - gold - One Size","brand":"Eleuteri","url":"https://www.net-a-porter.com/en-us/shop/product/eleuteri/jewelry-and-watches/vintage-bracelets/plus-bulgari-vintage-1980s-doppio-cuore-bracelet/46376663163120086","image":"https://www.net-a-porter.com/variants/images/46376663163120086/in/w2000_q60.jpg"}
        </script>
        """,
        "https://www.net-a-porter.com/en-us/shop/product/eleuteri/jewelry-and-watches/vintage-bracelets/plus-bulgari-vintage-1980s-doppio-cuore-bracelet/46376663163120086",
    )

    assert result.records[0]["title"].startswith("Bulgari Vintage")


def test_404_detail_with_direct_identity_reaches_not_found_handling() -> None:
    url = "https://shop.test/products/trail-shoe"
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        HTML,
        url,
    )
    source_capabilities = build_source_capability_diagnostics(
        html=HTML,
        network_payloads=[],
        status_code=404,
        browser_outcome="usable_content",
    )
    capture = request.capture.model_copy(
        update={
            "http_status": 404,
            "acquisition_diagnostics": {
                "source_capabilities": source_capabilities,
            },
        }
    )

    result = extract(request.model_copy(update={"capture": capture}))

    assert source_capabilities["terminal_shell"] is False
    assert result.records
    assert result.records[0]["title"] == "Trail Shoe"


def test_nonzero_variant_count_prevents_slug_only_classification() -> None:
    base = {
        "title": "Widget",
        "url": "https://shop.test/products/widget",
    }

    assert _only_slug_identity({**base, "variant_count": 0}) is True
    assert _only_slug_identity({**base, "variant_count": 2}) is False
