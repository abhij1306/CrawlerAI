# ruff: noqa: F403, F405
"""test_extraction_variant_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *


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


def test_js_state_parent_price_object_preserves_nested_currency_path() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Studio Tread</h1></main>",
        "https://shop.test/products/studio-tread",
        artifacts={
            "js_state_objects": {
                "product": {
                    "productName": "Studio Tread",
                    "url": "https://shop.test/products/studio-tread",
                    "brand": {"name": "Peloton"},
                    "currentPrice": {"amount": "3295.00", "currencyCode": "USD"},
                    "availability": "IN_STOCK",
                }
            }
        },
    )

    record = result.records[0]
    assert record["brand"] == "Peloton"
    assert record["price"] == "3295.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert any(
        row.fact_type == "offer.currency"
        and row.locator.value.endswith("/currentPrice/currencyCode")
        for row in result.evidence
    )


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
