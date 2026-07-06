# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *


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


def test_js_state_shopify_compare_at_price_maps_to_original_price() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": "Soft Rock Crewneck",
                "price": "64.00",
                "compare_at_price": "160.00",
                "currency": "EUR",
                "available": False,
            }
        }
    }

    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Soft Rock Crewneck</h1></body></html>",
        "https://shop.test/products/soft-rock-crewneck",
        artifacts=artifacts,
    )

    assert result.records
    assert result.records[0]["price"] == "64.00"
    assert result.records[0]["original_price"] == "160.00"
    assert result.records[0]["currency"] == "EUR"


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


def test_js_state_nuxt_devalue_product_variants_materialize() -> None:
    payload = [
        ["ShallowReactive", 1],
        {"productDetails-TB0A2M17W01": 2},
        {
            "id": 3,
            "name": 4,
            "url": 5,
            "currency": 6,
            "attributes": 7,
            "variants": 19,
        },
        "TB0A2M17W01",
        "Casco Cove Slide Sandal for Men in Dark Brown",
        "/en-gb/p/men-10029/casco-cove-slide-sandal-for-men-in-dark-brown-TB0A2M17W01",
        "GBP",
        [8, 13],
        {"type": 9, "label": 10, "options": 11},
        "color",
        "Color",
        [12],
        {"label": 14, "value": 15},
        {"type": 16, "label": 17, "options": 18},
        "Brown",
        "TB0A2M17W01 - BROWN",
        "size",
        "Size",
        [28, 31],
        [20, 24],
        {
            "id": 21,
            "productInventoryState": 22,
            "price": 23,
            "attributes": 27,
            "upc": 34,
        },
        "TB:0A2M17:W01:070:M:1:",
        "InStock",
        {"current": 35, "original": 36},
        {
            "id": 25,
            "productInventoryState": 26,
            "price": 23,
            "attributes": 30,
            "upc": 37,
        },
        "TB:0A2M17:W01:060:M:1:",
        "OutOfStock",
        {"color": 15, "size": 29},
        {"label": 38, "value": 29},
        "070",
        {"color": 15, "size": 32},
        {"label": 33, "value": 32},
        "060",
        "5.5",
        "198268059622",
        72,
        90,
        "198268059509",
        "6.5",
    ]
    html = f"""
    <main><h1>Casco Cove Slide Sandal for Men in Dark Brown</h1></main>
    <script id="__NUXT_DATA__" type="application/json">{json.dumps(payload)}</script>
    """

    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.timberland.com/en-gb/p/men-10029/casco-cove-slide-sandal-for-men-in-dark-brown-TB0A2M17W01",
    )

    variants = result.records[0]["variants"]
    assert variants == [
        {
            "variant_id": "TB:0A2M17:W01:060:M:1:",
            "price": "72.00",
            "currency": "GBP",
            "availability": "out_of_stock",
            "color": "Brown",
            "size": "5.5",
        },
        {
            "variant_id": "TB:0A2M17:W01:070:M:1:",
            "price": "72.00",
            "currency": "GBP",
            "availability": "in_stock",
            "color": "Brown",
            "size": "6.5",
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


def test_variant_option_endpoint_query_must_match_own_axis() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Runner Tee",
                        "url": "https://shop.test/products/runner-tee",
                        "variants": [
                            {
                                "variantId": "blue-m",
                                "sku": "RT-BLUE-M",
                                "url": "https://shop.test/on/demandware.store/Sites-shop-Site/default/Product-Variation?dwvar_1_size=Blue",
                                "color": "Blue",
                                "size": "M",
                                "price": "35",
                                "currency": "USD",
                            }
                        ],
                    }
                }
            },
        ),
    )

    assert not result.records[0].get("variants")


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
