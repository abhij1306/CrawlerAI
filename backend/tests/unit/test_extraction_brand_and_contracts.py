# ruff: noqa: F403, F405
"""test_extraction_contract_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *

from tests.unit.extraction_contract_test_support import (
    json,
)


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
            "Karen",
        ),
        (
            "https://www.phase-eight.com/product/lucinda-dress.html",
            "Lucinda Spot Midi Dress",
            "Phase Eight occasion dress.",
            "https://www.phase-eight.com/images/lucinda.jpg",
            "Phase",
            "Phase",
        ),
        (
            "https://www.calvinklein.us/bags/structured-commuter-bag.html",
            "Structured Commuter Bag",
            "Calvin Klein commuter bag.",
            "https://calvinklein.scene7.com/is/image/CalvinKlein/bag",
            "Calvin",
            "Calvin",
        ),
        (
            "https://www.asos.com/asos-curve/asos-design-curve-pants/prd/1",
            "ASOS DESIGN Curve Pants",
            "ASOS DESIGN curve pants.",
            "https://images.asos-media.com/products/asos-design-curve-pants/1.jpg",
            "ASOS",
            "ASOS",
        ),
        (
            "https://www.williams-sonoma.com/products/breville-the-bambino-plus/",
            "Breville Bambino Plus Espresso Machine",
            "Breville Bambino Plus espresso machine.",
            "https://assets.wsimgs.com/breville-bambino.jpg",
            "Breville Bambino",
            "Breville Bambino",
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
def test_page_identity_only_replaces_invalid_explicit_brand_shapes(
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
    assert record["brand"] == "ExampleCo"
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
          "brand": "ExampleCo",
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
    # Price + currency are unconditionally part of the completeness contract
    # (Crawl-Run-2 §4.5), so a name+url-only record scores 2/7 and reports the
    # commercial fields as missing alongside the descriptive ones.
    assert result.metrics.completeness_score == pytest.approx(2 / 7)
    missing_fields = {
        finding.metadata.get("field")
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
    }
    assert missing_fields == {
        "brand",
        "description",
        "image_url",
        "price",
        "currency",
    }
    completeness = next(
        finding
        for finding in result.findings
        if finding.rule_id == "RECORD_COMPLETENESS"
    )
    assert completeness.metadata["missing_fields"] == (
        "brand",
        "description",
        "image_url",
        "price",
        "currency",
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
          "brand": "ExampleCo",
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


def test_page_title_site_identity_beats_uncorroborated_product_title_token() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <title>Secret Halo Diamond Ring | Brilliant Earth</title>
          <meta property="og:title" content="Secret Halo Diamond Ring">
          <meta property="og:site_name" content="Brilliant Earth">
        </head>
        <main>
          <h1>Secret Halo Diamond Ring</h1>
          <p data-description="A refined diamond ring with a hidden halo."></p>
        </main>
        """,
        "https://www.brilliantearth.com/Secret-Halo-Diamond-Ring-BE1D13065/",
        requested_fields=("brand",),
    )

    assert result.records[0]["brand"] == "Brilliant Earth"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Brilliant Earth"
        and row.rule_id == "page_identity"
        for row in result.derived_facts
    )


def test_locale_prefixed_jsonld_product_keeps_target_identifiers_and_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "WebPage",
          "url": "https://shop.test/secret-halo-BE1D13065.html",
          "name": "Secret Halo Ring"
        }
        </script>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "url": "https://shop.test/en-gb/secret-halo-BE1D13065.html",
          "name": "Secret Halo Ring",
          "brand": {"@type": "Brand", "name": "Example Jeweller"},
          "sku": "BE1D13065-14KY",
          "mpn": "BE1D13065-14KY",
          "offers": {
            "@type": "Offer",
            "price": "1090",
            "priceCurrency": "USD",
            "availability": "https://schema.org/InStock"
          }
        }
        </script>
        """,
        "https://shop.test/secret-halo-BE1D13065.html",
        requested_fields=("brand", "sku", "mpn", "price", "currency", "availability"),
    )

    record = result.records[0]
    assert record["brand"] == "Example Jeweller"
    assert record["sku"] == "BE1D13065-14KY"
    assert record["mpn"] == "BE1D13065-14KY"
    assert record["price"] == "1090.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"


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
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Sony"
        and row.brand_role == "manufacturer"
        for row in result.evidence
    )


def test_structured_manufacturer_beats_retailer_identity_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Day-Date 18038 Champagne",
          "manufacturer": {"@type": "Brand", "name": "Rolex"},
          "url": "https://amsterdamvintagewatches.test/shop/rolex-day-date-18038-champagne",
          "offers": {"seller": {"@type": "Organization", "name": "Amsterdam Vintage Watches"}}
        }
        </script>
        <main><span class="product-brand retailer-name">Amsterdam Vintage Watches</span></main>
        """,
        "https://amsterdamvintagewatches.test/shop/rolex-day-date-18038-champagne",
    )

    assert result.records[0]["brand"] == "Rolex"
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Amsterdam Vintage Watches"
        and row.brand_role == "retailer"
        and "non_manufacturer_brand_role" in row.flags
        for row in result.evidence
    )


def test_js_state_store_container_does_not_reclassify_product_brand() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script id="__NEXT_DATA__" type="application/json">
        {"props":{"store":{"product":{
          "name":"Studio Monitor",
          "url":"https://shop.test/products/studio-monitor",
          "brand":{"name":"Audio Guild"}
        }}}}
        </script>
        <main><h1>Studio Monitor</h1></main>
        """,
        "https://shop.test/products/studio-monitor",
    )

    assert result.records[0]["brand"] == "Audio Guild"


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

    # The marker still bounds the brand name, but it is legal notation rather
    # than part of the name, so it is not published.
    assert result.records[0]["brand"] == "Acme"
    assert not any(
        row.fact_type == "product.brand"
        and row.metadata.get("derived_by") == "brand_from_title_marker"
        for row in result.evidence
    )
    assert any(
        row.fact_type == "product.brand"
        and row.value == "Acme"
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


def test_jsonld_variant_prefers_explicit_color_over_malformed_url_shade() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Trail Pants",
          "url": "https://shop.test/products/trail-pants?color=2EL",
          "hasVariant": [{
            "@type": "Product",
            "sku": "PANTS-CEDAR-M",
            "color": "Cedar",
            "size": "M",
            "offers": {
              "url": "https://shop.test/products/trail-pants?color=2EL?color=2EL&size=M",
              "price": "91",
              "priceCurrency": "USD"
            }
          }]
        }
        </script>
        """,
        "https://shop.test/products/trail-pants?color=2EL",
    )

    assert result.records[0]["variants"][0]["color"] == "Cedar"


def test_jsonld_variant_keeps_uppercase_named_color() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Linen Shirt",
          "url": "https://shop.test/products/linen-shirt",
          "hasVariant": [{
            "@type": "Product",
            "sku": "SHIRT-BROWN-M",
            "color": "BROWN",
            "size": "M",
            "offers": {"price": "49.9", "priceCurrency": "USD"}
          }]
        }
        </script>
        """,
        "https://shop.test/products/linen-shirt",
    )

    assert result.records[0]["variants"][0]["color"] == "BROWN"


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


def test_jsonld_productgroup_id_links_standalone_variant_offers() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@type": "ProductGroup",
        "@id": "https://shop.test/schema/group/sony-a9",
        "productGroupID": "ILCE-9M3",
        "name": "Sony Alpha 9 III",
        "brand": {"@type": "Brand", "name": "SONY"}
      },
      {
        "@type": "Product",
        "isVariantOf": {"@id": "https://shop.test/schema/group/sony-a9"},
        "sku": "ILCE-9M3-BODY",
        "offers": {
          "@type": "Offer",
          "price": "5999.99",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }
      }
    ]
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/sony-a9")

    record = result.records[0]
    assert record["brand"] == "SONY"
    assert record["price"] == "5999.99"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert record["variants"] == [
        {
            "variant_id": "ILCE-9M3-BODY",
            "sku": "ILCE-9M3-BODY",
            "price": "5999.99",
            "currency": "USD",
            "availability": "in_stock",
        }
    ]
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )


def test_jsonld_item_offered_offer_links_to_explicit_variant_subject() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@type": "ProductGroup",
        "@id": "https://shop.test/schema/group/shirt",
        "name": "Linen Shirt",
        "url": "https://shop.test/products/linen-shirt",
        "offers": {
          "@type": "Offer",
          "itemOffered": {"@type": "Product", "@id": "https://shop.test/schema/variant/shirt-m"},
          "price": "40.00",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }
      },
      {
        "@type": "Product",
        "@id": "https://shop.test/schema/variant/shirt-m",
        "isVariantOf": {"@id": "https://shop.test/schema/group/shirt"},
        "sku": "SHIRT-M",
        "size": "M"
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/products/linen-shirt"
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "SHIRT-M",
            "sku": "SHIRT-M",
            "price": "40.00",
            "currency": "USD",
            "availability": "in_stock",
            "size": "M",
        }
    ]
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )


def test_jsonld_product_item_offered_preserves_product_offer_scope() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "@id": "https://shop.test/schema/product/desk",
          "name": "Writing Desk",
          "url": "https://shop.test/products/writing-desk",
          "offers": {
            "@type": "Offer",
            "itemOffered": {
              "@type": "Product",
              "@id": "https://shop.test/schema/product/desk"
            },
            "price": "250.00",
            "priceCurrency": "USD"
          }
        }
        </script>
        """,
        "https://shop.test/products/writing-desk",
    )

    assert result.records[0]["price"] == "250.00"
    assert not any(
        finding.rule_id == "CHILD_JOIN_FAILED" for finding in result.findings
    )


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
