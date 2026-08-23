# ruff: noqa: F403, F405
"""test_extraction_asset_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *


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
