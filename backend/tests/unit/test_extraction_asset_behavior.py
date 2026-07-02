# ruff: noqa: F403, F405
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


def test_invalid_top_ranked_asset_falls_back_to_next_delivery_url() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail Shoe",
          "url": "https://shop.test/products/trail-shoe",
          "image": [
            "https://cdn.shop.test/products/trail-shoe-main?width=1200?format=webp",
            "https://cdn.shop.test/products/trail-shoe-side?width=1200"
          ],
          "offers": {"price": "95", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )

    assert result.records[0]["image_url"] == (
        "https://cdn.shop.test/products/trail-shoe-side?width=1200"
    )


def test_single_same_product_variant_image_derives_parent_primary_image() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Solitaire Ring",
          "url": "https://shop.test/products/solitaire-ring",
          "hasVariant": [{
            "@type": "Product",
            "sku": "RING-7",
            "size": "7",
            "image": "https://cdn.shop.test/products/solitaire-ring-size-7",
            "offers": {
              "price": "1299",
              "priceCurrency": "USD",
              "availability": "https://schema.org/InStock"
            }
          }]
        }
        </script>
        """,
        "https://shop.test/products/solitaire-ring",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shop.test/products/solitaire-ring-size-7"
    )
    assert record["variants"][0]["image_url"] == record["image_url"]
    assert record["_lineage"]["image_url"]["rule_id"] == (
        "VARIANT_ASSET_PARENT_FALLBACK"
    )


def test_variant_parent_asset_fallback_uses_only_usable_variant_assets() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Solitaire Ring",
          "url": "https://shop.test/products/solitaire-ring",
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "RING-7",
              "size": "7",
              "image": "https://cdn.shop.test/products/solitaire-ring-size-7",
              "offers": {"price": "1299", "priceCurrency": "USD"}
            },
            {
              "@type": "Product",
              "sku": "RING-8",
              "size": "8",
              "image": "https://cdn.shop.test/products/solitaire-ring-size-8?placeholder=true",
              "offers": {"price": "1299", "priceCurrency": "USD"}
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/solitaire-ring",
    )

    record = result.records[0]
    assert record["image_url"] == (
        "https://cdn.shop.test/products/solitaire-ring-size-7"
    )
    assert record["_lineage"]["image_url"]["rule_id"] == (
        "VARIANT_ASSET_PARENT_FALLBACK"
    )


def test_jsonld_variant_axes_are_canonicalized_without_rewriting_flavor() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Protein Mix",
          "url": "https://shop.test/products/protein-mix",
          "variesBy": ["https://schema.org/flavor", "Colour"],
          "hasVariant": [{
            "@type": "Product",
            "sku": "MIX-VANILLA",
            "colour": "Cream",
            "additionalProperty": {
              "@type": "PropertyValue",
              "name": "Flavour",
              "value": "Vanilla"
            },
            "offers": {"price": "30", "priceCurrency": "USD"}
          }]
        }
        </script>
        """,
        "https://shop.test/products/protein-mix",
    )

    variant = result.records[0]["variants"][0]
    assert variant["flavor"] == "Vanilla"
    assert variant["color"] == "Cream"
    assert variant.get("flavor") != variant.get("color")


def test_variant_axis_uri_trimming_does_not_accept_plain_slash_labels() -> None:
    assert canonical_variant_axis("https://schema.org/color") == "color"
    assert canonical_variant_axis("color/size") is None
    assert canonical_variant_axis("fit/style") is None
