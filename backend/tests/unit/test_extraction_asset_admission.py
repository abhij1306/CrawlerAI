# ruff: noqa: F403, F405
"""test_extraction_asset_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *


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
        not any(
            term in str(row.value).casefold()
            for term in {"delonghi", "cuisinart", "img15"}
        )
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
