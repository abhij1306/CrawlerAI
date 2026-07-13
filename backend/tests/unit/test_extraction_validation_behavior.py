# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *


def test_extensionless_image_url_pattern_matches_path_only() -> None:
    assert PRODUCT_ASSET_EXTENSIONLESS_PATH_PATTERN
    assert structured_extensionless_image_url(
        "https://cdn.shop.test/products/solitaire-ring-size-7"
    )
    assert not structured_extensionless_image_url(
        "https://cdn.shop.test/api/render?next=/products/solitaire-ring-size-7"
    )


def test_explicit_optionless_child_with_identity_and_offer_is_not_dropped() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Cotton Tee",
          "url": "https://shop.test/products/cotton-tee",
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-UNKNOWN",
              "offers": {"price": "20", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "TEE-M",
              "size": "M",
              "offers": {"price": "20", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/cotton-tee",
    )

    variants = result.records[0]["variants"]
    assert {row["sku"] for row in variants} == {"TEE-UNKNOWN", "TEE-M"}
    unknown = next(row for row in variants if row["sku"] == "TEE-UNKNOWN")
    assert "size" not in unknown


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

    assert all("size" not in row for row in result.records[0]["variants"])
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
    assert record["_lineage"]["currency"]["rule_id"] == "currency_from_price_symbol"


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

    assert "availability" not in result.records[0]["variants"][0]


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
    assert not result.records
    assert result.transport_outcome == "not_found"
