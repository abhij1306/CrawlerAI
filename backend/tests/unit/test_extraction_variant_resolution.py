# ruff: noqa: F403, F405
"""test_extraction_variant_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *
from app.extraction.resolution.variants import _is_axis_group_variant


def test_selected_has_variant_admits_its_declared_product_group() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "productGroupID": "TEE",
          "audience": {
            "@type": "PeopleAudience",
            "suggestedGender": "Unisex"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-BLACK-S",
              "color": "Black",
              "size": "S",
              "offers": {
                "url": "https://shop.test/products/everyday-tee-black",
                "price": "18",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "sku": "TEE-WHITE-S",
              "color": "White",
              "size": "S",
              "offers": {
                "url": "https://shop.test/products/everyday-tee-white",
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock"
              }
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee-black",
    )

    record = result.records[0]
    assert record["title"] == "Everyday Tee"
    assert record["gender"] == "Unisex"
    assert record["style_id"] == "TEE"
    assert len(record["variants"]) == 2
    assert {row["sku"] for row in record["variants"]} == {
        "TEE-BLACK-S",
        "TEE-WHITE-S",
    }


def test_selected_top_product_joins_its_matching_product_group_child() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        [
          {
            "@type": "Product",
            "name": "Everyday Sandal",
            "sku": "SANDAL-BLACK",
            "offers": {
              "url": "https://shop.test/products/everyday-sandal-black",
              "price": "40",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            }
          },
          {
            "@type": "ProductGroup",
            "name": "Everyday Sandal",
            "url": "https://shop.test/products/everyday-sandal",
            "productGroupID": "SANDAL",
            "audience": {
              "@type": "PeopleAudience",
              "suggestedGender": "Unisex"
            },
            "hasVariant": [
              {
                "@type": "Product",
                "color": "White",
                "offers": {
                  "url": "https://shop.test/products/everyday-sandal-white",
                  "price": "40",
                  "priceCurrency": "USD"
                }
              },
              {
                "@type": "Product",
                "color": "Black",
                "offers": {
                  "url": "https://shop.test/products/everyday-sandal-black",
                  "price": "40",
                  "priceCurrency": "USD"
                }
              }
            ]
          }
        ]
        </script>
        """,
        "https://shop.test/products/everyday-sandal-black",
    )

    record = result.records[0]
    assert record["sku"] == "SANDAL-BLACK"
    assert record["style_id"] == "SANDAL"
    assert record["gender"] == "Unisex"
    assert {row["color"] for row in record["variants"]} == {"White", "Black"}


def test_commercial_leaf_variants_replace_incomplete_axis_group_shell() -> None:
    shell = {
        "variant_id": "TEE-BLACK",
        "sku": "TEE-BLACK",
        "currency": "USD",
        "color": "Black",
    }
    leaf = {
        "variant_id": "TEE-BLACK-S",
        "sku": "TEE-BLACK-S",
        "price": "18.00",
        "currency": "USD",
        "availability": "in_stock",
        "color": "Black",
        "size": "S",
    }

    assert _is_axis_group_variant(shell, [shell, leaf])
    assert not _is_axis_group_variant(leaf, [shell, leaf])


def test_product_sku_excludes_sibling_style_variant_families() -> None:
    state = {
        "product": {
            "name": "Teddyx T-shirt",
            "sku": "JMTS01771443",
            "url": "https://shop.test/products/JMTS01771443/teddyx",
            "price": "91",
            "currency": "GBP",
            "variants": [
                {
                    "id": "selected-xs",
                    "sku": "JMTS01771443X02",
                    "size": "XS",
                    "price": "91",
                    "currency": "GBP",
                    "available": True,
                },
                {
                    "id": "sibling-xs",
                    "sku": "JMTS01771009X02",
                    "size": "XS",
                    "currency": "GBP",
                },
                {
                    "id": "sibling-s",
                    "sku": "JMTS01771343X03",
                    "size": "S",
                    "currency": "GBP",
                },
            ],
        }
    }
    result = _extract(
        "ecommerce_detail",
        f"""
        <script>window.__INITIAL_STATE__ = {json.dumps(state)};</script>
        <main><h1>Teddyx T-shirt</h1></main>
        """,
        "https://shop.test/products/JMTS01771443/teddyx",
        requested_fields=("sku", "variants", "price", "currency"),
    )

    assert [row["sku"] for row in result.records[0]["variants"]] == ["JMTS01771443X02"]


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


def test_target_product_group_node_id_joins_direct_state_variant() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "@id": "https://shop.test/products/everyday-tee#productgroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "hasVariant": [{
            "@type": "Product",
            "sku": "TEE-BLK-S",
            "gtin12": "725272730706",
            "color": "Black",
            "size": "S"
          }]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
        artifacts={
            "js_state_objects": {
                "variant": {
                    "id": "TEE-BLK-S",
                    "gtin": "725272730706",
                    "size": "S",
                    "price": "18.5",
                    "currency": "USD",
                }
            }
        },
    )

    assert result.records[0]["variants"] == [
        {
            "variant_id": "TEE-BLK-S",
            "sku": "TEE-BLK-S",
            "price": "18.50",
            "currency": "USD",
            "barcode": "725272730706",
            "color": "Black",
            "size": "S",
        }
    ]


def test_variant_strikethrough_price_specification_is_original_price() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Running Shoe",
          "url": "https://shop.test/products/running-shoe",
          "hasVariant": [{
            "@type": "Product",
            "sku": "SHOE-BLACK-8",
            "color": "Black",
            "size": "8",
            "offers": {
              "price": "69.97",
              "priceCurrency": "USD",
              "priceSpecification": {
                "price": "75",
                "priceCurrency": "USD",
                "priceType": "StrikethroughPrice"
              }
            }
          }]
        }
        </script>
        """,
        "https://shop.test/products/running-shoe",
    )

    assert result.records[0]["variants"][0] == {
        "variant_id": "SHOE-BLACK-8",
        "sku": "SHOE-BLACK-8",
        "price": "69.97",
        "currency": "USD",
        "original_price": "75.00",
        "color": "Black",
        "size": "8",
    }


def test_matching_gtin_merges_sources_despite_different_source_ids() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "hasVariant": [{
            "@type": "Product",
            "@id": "https://shop.test/products/everyday-tee#small",
            "sku": "TEE-SOURCE-A",
            "gtin": "5057913931872",
            "size": "S"
          }]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
        artifacts={
            "js_state_objects": {
                "variant": {
                    "id": "internal-small",
                    "sku": "TEE-SOURCE-B",
                    "gtin": "5057913931872",
                    "size": "S",
                    "price": "18.5",
                    "currency": "USD",
                }
            }
        },
    )

    assert result.graph.entity_counts["variant"] == 1
    assert result.records[0]["variants"][0]["barcode"] == "5057913931872"


def test_shared_product_sku_does_not_collapse_distinct_gtin_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Arrival Shorts",
          "url": "https://shop.test/products/arrival-shorts",
          "offers": {"price": "26", "priceCurrency": "USD"},
          "hasVariant": [
            {"@type": "Product", "sku": "ARRIVAL", "gtin": "5057913931872", "size": "XS"},
            {"@type": "Product", "sku": "ARRIVAL", "gtin": "5057913931865", "size": "S"}
          ]
        }
        </script>
        """,
        "https://shop.test/products/arrival-shorts",
    )

    variants = result.records[0]["variants"]

    assert len(variants) == 2
    assert {row["barcode"] for row in variants} == {
        "5057913931865",
        "5057913931872",
    }
    assert {row["variant_id"] for row in variants} == {
        "5057913931865",
        "5057913931872",
    }
    assert {row["sku"] for row in variants} == {"ARRIVAL"}


def test_distinct_skus_do_not_merge_when_public_options_match() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Width Runner",
          "url": "https://shop.test/products/width-runner",
          "offers": {"price": "170", "priceCurrency": "USD"},
          "hasVariant": [
            {"@type": "Product", "sku": "RUNNER-D-10", "color": "Grey", "size": "10"},
            {"@type": "Product", "sku": "RUNNER-2E-10", "color": "Grey", "size": "10"}
          ]
        }
        </script>
        """,
        "https://shop.test/products/width-runner",
    )

    variants = result.records[0]["variants"]

    assert len(variants) == 2
    assert {row["sku"] for row in variants} == {"RUNNER-D-10", "RUNNER-2E-10"}


def test_explicit_product_group_variants_may_use_distinct_product_paths() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Iconic Cotton Chino Ball Cap",
          "url": "https://shop.test/products/iconic-cotton-chino-ball-cap-650310",
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "CAP-PINK",
              "url": "https://shop.test/products/iconic-cotton-chino-ball-cap-3616854279980",
              "color": "Pink",
              "size": "One Size",
              "offers": {"price": "97", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "CAP-GREEN",
              "url": "https://shop.test/products/iconic-cotton-chino-ball-cap-3616858013504",
              "color": "Green",
              "size": "One Size",
              "offers": {"price": "97", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/iconic-cotton-chino-ball-cap-650310",
    )

    assert {row["sku"] for row in result.records[0]["variants"]} == {
        "CAP-GREEN",
        "CAP-PINK",
    }


def test_parent_title_placeholder_is_not_variant_even_with_repeated_price() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Small Eye Shadow</h1></main>",
        "https://shop.test/products/small-eye-shadow",
        artifacts={
            "js_state_objects": {
                "meta": {
                    "product": {
                        "name": "Small Eye Shadow",
                        "price": "26",
                        "currency": "USD",
                        "variants": [
                            {
                                "id": "parent-style",
                                "sku": "PARENT-STYLE",
                                "public_title": "Small Eye Shadow",
                                "price": "26",
                                "currency": "USD",
                            },
                            {
                                "id": "blue-small",
                                "sku": "BLUE-SMALL",
                                "color": "Blue",
                                "size": "Small",
                                "price": "26",
                                "currency": "USD",
                                "available": True,
                            },
                            {
                                "id": "blue-large",
                                "sku": "BLUE-LARGE",
                                "color": "Blue",
                                "size": "Large",
                                "price": "26",
                                "currency": "USD",
                                "available": True,
                            },
                        ],
                    }
                }
            }
        },
    )

    assert {row["sku"] for row in result.records[0]["variants"]} == {
        "BLUE-SMALL",
        "BLUE-LARGE",
    }
    assert result.records[0]["availability"] == "in_stock"


def test_declared_jsonld_size_uses_terminal_variant_name_segment() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Trail Mix",
      "url": "https://shop.test/products/trail-mix/large",
      "variesBy": ["https://schema.org/size"],
      "hasVariant": [
        {"@type": "Product", "name": "Trail Mix, Small bag", "url": "https://shop.test/products/trail-mix/small", "offers": {"price": "10", "priceCurrency": "USD", "availability": "https://schema.org/InStock"}},
        {"@type": "Product", "name": "Trail Mix, Large bag", "url": "https://shop.test/products/trail-mix/large", "offers": {"price": "20", "priceCurrency": "USD", "availability": "https://schema.org/OutOfStock"}}
      ]
    }
    </script>
    """
    result = _extract(
        "ecommerce_detail", html, "https://shop.test/products/trail-mix/large"
    )

    assert result.records[0]["price"] == "20.00"
    assert result.records[0]["availability"] == "out_of_stock"
    assert (
        result.records[0]["_lineage"]["availability"]["rule_id"]
        == "selected_variant_availability_aggregate"
    )
    assert result.records[0]["size"] == "Large bag"
    assert {row["size"] for row in result.records[0]["variants"]} == {
        "Large bag",
        "Small bag",
    }


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
