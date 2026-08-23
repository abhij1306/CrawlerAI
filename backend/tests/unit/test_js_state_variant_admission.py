# ruff: noqa: F403, F405
"""test_extraction_js_state_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *


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
