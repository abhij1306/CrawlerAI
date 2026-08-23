# ruff: noqa: F403, F405
"""test_extraction_js_state_behavior cases split by public behavior."""

from __future__ import annotations

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
