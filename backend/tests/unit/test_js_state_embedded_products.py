# ruff: noqa: F403, F405
"""test_extraction_js_state_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *


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


def test_js_state_parent_selling_price_and_vendor_brand_paths_publish() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><head><script id="__NEXT_DATA__" type="application/json">
        {
          "props": {"pageProps": {"product": {
            "name": "Studio Bike",
            "url": "https://shop.test/products/studio-bike",
            "vendor": [{"name": "Invoro Fitness"}],
            "sellingPrice": {
              "amount": "3295.00",
              "currencyCode": "USD",
              "availability": "IN_STOCK"
            }
          }}}
        }
        </script></head><body><h1>Studio Bike</h1></body></html>
        """,
        "https://shop.test/products/studio-bike",
    )

    record = result.records[0]
    assert record["brand"] == "Invoro Fitness"
    assert record["price"] == "3295.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    offer_rows = [
        row
        for row in result.evidence
        if row.fact_type.startswith("offer.") and "/sellingPrice/" in row.locator.value
    ]
    grouped_facts = _group_facts_by_group_id(offer_rows)
    assert any(
        facts >= {"offer.price", "offer.currency", "offer.availability"}
        for facts in grouped_facts.values()
    )
    assert any(row.locator.value.endswith("/sellingPrice/amount") for row in offer_rows)


def test_js_state_value_path_checks_complete_suffix_across_list_items() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"product":{
          "name":"List Price Product",
          "url":"https://shop.test/products/list-price-product",
          "sellingPrice":[
            {"amount":""},
            {"amount":"89.50","currencyCode":"USD"}
          ]
        }}}}
        </script>
        """,
        "https://shop.test/products/list-price-product",
    )

    assert result.records[0]["price"] == "89.50"
    assert result.records[0]["currency"] == "USD"


def test_js_state_base_price_keeps_integer_major_units_without_evidence() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><head><script id="__NEXT_DATA__" type="application/json">
        {
          "props": {"pageProps": {"product": {
            "name": "Reference Turntable",
            "url": "https://shop.test/products/reference-turntable",
            "brand": {"displayName": "Audio Guild"},
            "basePrice": {"amount": 186000, "currencyCode": "INR"}
          }}}
        }
        </script></head><body><h1>Reference Turntable</h1></body></html>
        """,
        "https://shop.test/products/reference-turntable",
    )

    record = result.records[0]
    assert record["brand"] == "Audio Guild"
    assert record["price"] == "186000.00"
    assert record["currency"] == "INR"
    assert not _price_repair_facts(result, "explicit_minor_unit_price")
    assert not _price_repair_facts(result, "corroborated_price_scale")


def test_js_state_variant_selling_price_container_is_atomic() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html><head><script id="__NEXT_DATA__" type="application/json">
        {
          "props": {"pageProps": {"product": {
            "name": "Road Hoodie",
            "url": "https://shop.test/products/road-hoodie",
            "variants": [
              {
                "variantId": "road-black-m",
                "sku": "ROAD-BLK-M",
                "size": "M",
                "sellingPrice": {
                  "amount": 215,
                  "currencyCode": "USD",
                  "availability": true
                }
              }
            ]
          }}}
        }
        </script></head><body><h1>Road Hoodie</h1></body></html>
        """,
        "https://shop.test/products/road-hoodie",
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "road-black-m",
            "sku": "ROAD-BLK-M",
            "price": "215.00",
            "currency": "USD",
            "availability": "in_stock",
            "size": "M",
        }
    ]
    rows: list[Evidence] = [
        row
        for row in result.evidence
        if row.entity_hint
        and row.entity_hint.entity_type == "variant"
        and row.fact_type.startswith("offer.")
    ]
    assert {row.fact_type for row in rows} >= {
        "offer.price",
        "offer.currency",
        "offer.availability",
    }
    grouped_facts = _group_facts_by_group_id(rows)
    assert any(
        facts >= {"offer.price", "offer.currency", "offer.availability"}
        for facts in grouped_facts.values()
    )


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
