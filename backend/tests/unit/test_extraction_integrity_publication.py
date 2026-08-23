# ruff: noqa: F403, F405
"""test_extraction_integrity_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *


def test_host_title_brand_is_not_manufacturer_truth() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Marketplace Store Premium Blender",
          "url": "https://marketplacestore.test/products/premium-blender",
          "image": "https://cdn.marketplacestore.test/blender.jpg",
          "offers": {"price": "20", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://marketplacestore.test/products/premium-blender",
    )

    assert result.records[0].get("brand") is None
    assert not [
        row
        for row in result.derived_facts
        if row.fact_type == "product.brand" and row.rule_id == "brand_from_title_host"
    ]


def test_asset_publication_dedupes_delivery_identity_after_entity_decode() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Image Product",
          "brand": "Acme",
          "url": "https://shop.test/products/image-product",
          "image": [
            "https://cdn.shop.test/product.jpg?wid=400&amp;fmt=webp",
            "https://cdn.shop.test/product.jpg?wid=800&fmt=jpg"
          ],
          "offers": {"price": "20", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/image-product",
    )
    record = result.records[0]

    assert record["image_url"] == "https://cdn.shop.test/product.jpg?wid=800&fmt=jpg"
    assert "&amp;" not in record["image_url"]
    assert record.additional_images == ()


def test_offer_price_currency_shared_dom_group_publishes_as_atomic_pair() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Atomic Offer Product</h1>
          <div data-price="10"></div>
          <div data-currency="USD"></div>
        </main>
        """,
        "https://shop.test/products/atomic-offer-product",
    )

    assert result.records[0].get("price") == "10.00"
    assert result.records[0].get("currency") == "USD"
    assert {
        decision.fact_type: decision.status
        for decision in result.decisions
        if decision.fact_type in {"offer.price", "offer.currency"}
    } == {"offer.currency": "resolved", "offer.price": "resolved"}


def test_generic_size_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>size</h1></main>",
        "https://shop.test/p/tobago-stripe-blue-duvet-cover/-/A-1002150742",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "tobago stripe blue duvet cover"
    assert result.verdict == "partial"


def test_transient_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Added to Cart</h1></main>",
        "https://shop.test/Sparkling-Prebiotic-Beverage/dp/B0F5Y3X8PP/",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "Sparkling Prebiotic Beverage"
    assert result.verdict == "partial"


@pytest.mark.parametrize(
    ("bad_title", "page_url", "expected"),
    (
        ("T-Shirts", "https://shop.test/en-in/p/barrow/kids-boys/83I-UKD027", None),
        (
            "Hats & Caps",
            "https://shop.test/us/en/products/wide-brim-sun-hat/E455957",
            "wide brim sun hat",
        ),
        ("Tread PDP - Compose Page", "https://shop.test/shop/tread", "tread"),
        ("mens footwear sneakers", "https://shop.test/products/st40002-02000", None),
        ("X", "https://shop.test/p/womens-chill-river-midi-dress-1933601.html", None),
        (
            "Interchangeable Lens Cameras",
            "https://shop.test/cameras/alpha-7-iv-full-frame-camera/ILCE7M4-B",
            "alpha 7 iv full frame camera",
        ),
        (
            "Wide Leg",
            "https://shop.test/p/wide-leg-cropped-jean/BT123",
            "wide leg cropped jean",
        ),
        (
            "Satisfy",
            "https://shop.test/products/satisfy-cloudmerino-running-tee",
            "satisfy cloudmerino running tee",
        ),
    ),
)
def test_taxonomy_and_cms_titles_use_semantic_url_identity(
    bad_title: str,
    page_url: str,
    expected: str | None,
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"<main><h1>{bad_title}</h1></main>",
        page_url,
        requested_fields=("title",),
    )

    if expected is None:
        assert result.records[0].get("title") is None
    else:
        assert result.records[0]["title"] == expected
    assert result.verdict in {"partial", "review"}


def test_measurement_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>4D</h1></main>",
        "https://shop.test/us/stan-smith-shoes/M20324.html",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "stan smith shoes"
    assert result.verdict == "partial"


def test_commerce_seo_title_uses_semantic_url_segment() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Buy Babyhug Denim Woven Sleeveless Top and Pant Set With Floral Print Blue Online at Best Price</h1></main>",
        "https://shop.test/brand/babyhug-denim-woven-sleeveless-top-and-pant-set-with-floral-print-blue/22346676/product-detail",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == (
        "babyhug denim woven sleeveless top and pant set with floral print blue"
    )
    assert result.verdict == "partial"


def test_slug_only_detail_stub_routes_to_review_not_partial() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/breville-the-bambino-plus",
    )

    assert result.records
    assert result.records[0]["title"] == "breville the bambino plus"
    assert result.verdict == "partial"


def test_shell_h1_cannot_outrank_structured_product_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Fresh Foam X 1080v15",
          "url": "https://shop.test/products/fresh-foam-x-1080v15",
          "offers": {"price": "165", "priceCurrency": "USD"}
        }
        </script>
        <main><h1>Oops! Something went wrong</h1></main>
        """,
        "https://shop.test/products/fresh-foam-x-1080v15",
    )

    assert result.records[0]["title"] == "Fresh Foam X 1080v15"
    assert result.verdict == "partial"


def test_transient_cart_action_title_does_not_materialize() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Adding to Cart...</h1></main>",
        "https://www.amazon.com/example/dp/B0F5Y3X8PP/?th=1",
        requested_fields=("title",),
    )

    assert not result.records
    assert result.verdict != "success"


def test_truncated_title_loses_to_more_complete_url_identity() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>iPhone</h1></main>",
        "https://www.backmarket.com/en-us/p/iphone-15-plus",
    )

    assert result.records[0]["title"].casefold() == "iphone 15 plus"
    assert result.records[0]["title"] != "iPhone"
    assert result.verdict == "partial"


def test_natural_title_with_model_number_remains_admissible() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Levi 501 Jeans</h1></main>",
        "https://shop.test/products/levi-501-jeans",
    )

    assert result.records[0]["title"] == "Levi 501 Jeans"


def test_measurements_navigation_title_cannot_produce_success() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Measurements</h1>
          <div data-price="89">89</div>
          <div data-currency="USD">USD</div>
        </main>
        """,
        "https://shop.test/products/99107606086.html",
    )

    assert result.verdict != "success"
    assert not result.records or result.records[0].get("title") != "Measurements"


def test_standard_and_twitter_metadata_recover_missing_product_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head>
          <meta name="twitter:title" content="Trail Shoe">
          <meta name="description" content="A durable trail shoe for long-distance runs.">
          <meta name="brand" content="ExampleCo">
          <meta name="twitter:image" content="https://shop.test/i/trail.jpg">
        </head>
        <main></main>
        """,
        "https://shop.test/products/TS-100",
    )

    record = result.records[0]
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "ExampleCo"
    assert record["description"] == "A durable trail shoe for long-distance runs."
    assert record["image_url"] == "https://shop.test/i/trail.jpg"


def test_document_title_recovers_missing_product_heading() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head><title>Trail Shoe</title></head>
        <main><img data-product-image src="https://shop.test/i/trail.jpg"></main>
        """,
        "https://shop.test/products/TS-100",
    )

    assert result.records[0]["title"] == "Trail Shoe"
    assert result.verdict in {"partial", "review"}


def test_clean_h1_outranks_polluted_seo_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <head><meta property="og:title" content="Trail Shoe | Shop Online - $129.00"></head>
        <main><h1>Trail Shoe</h1><div data-price="129">129</div><div data-currency="USD">USD</div></main>
        """,
        "https://shop.test/products/trail-shoe.html",
    )

    assert result.records[0]["title"] == "Trail Shoe"


def test_arbitrary_nested_price_object_cannot_create_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        artifacts={
            "js_state_objects": {"analytics": {"price": "999", "currency": "USD"}}
        },
    )

    assert result.records[0].get("price") is None
    assert result.records[0].get("currency") is None


def test_many_uncorroborated_dom_prices_do_not_create_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Wild Game Dry Dog Food, 18-lb bag</h1>
          <span data-price="77.48"></span>
          <span data-price="53.98"></span>
          <span data-price="59.98"></span>
          <span data-price="8.98"></span>
          <span data-price="4.50"></span>
        </main>
        """,
        "https://shop.test/dp/141791",
    )

    assert result.records
    record = result.records[0].model_dump(mode="python", exclude_none=True)
    assert "price" not in record


def test_missing_field_finding_uses_selected_public_value() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type": "Product", "name": "Trail Shoe", "brand": "N/A"}
        </script>
        """,
        "https://shop.test/products/trail-shoe",
        requested_fields=("brand",),
    )

    brand_findings = [
        finding
        for finding in result.findings
        if finding.rule_id == "MISSING_CONTRACT_FIELD"
        and finding.metadata.get("field") == "brand"
    ]
    assert result.records[0].get("brand") is None
    assert len(brand_findings) == 1


def test_network_product_aliases_require_context_and_map_canonical_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Fallback</h1></main>",
        "https://shop.test/products/trail-shoe",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "productName": "Trail Shoe",
                        "brand": {"name": "ExampleCo"},
                        "productDescription": "Built for long trail days.",
                        "price": "129",
                        "currencyCode": "USD",
                        "inStock": True,
                        "images": [
                            "https://shop.test/images/trail-1.jpg",
                            "https://shop.test/images/trail-2.jpg",
                        ],
                    }
                }
            },
        ),
    )

    record = result.records[0]
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "ExampleCo"
    assert record["description"] == "Built for long trail days."
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    image_urls = {
        str(item.value)
        for item in result.evidence
        if item.fact_type == "asset.image_url"
    }
    assert image_urls == {
        "https://shop.test/images/trail-1.jpg",
        "https://shop.test/images/trail-2.jpg",
    }
    assert record["image_url"] in image_urls


def test_structured_image_objects_materialize_primary_and_additional_images() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Trail Shoe",
                        "url": "https://shop.test/products/trail-shoe",
                        "price": "129",
                        "currency": "USD",
                        "images": [
                            {
                                "url": "https://cdn.shop.test/products/trail-shoe-main.jpg"
                            },
                            {
                                "src": "https://cdn.shop.test/products/trail-shoe-side.jpg"
                            },
                        ],
                    }
                }
            },
        ),
    )

    assert result.records[0]["image_url"] == (
        "https://cdn.shop.test/products/trail-shoe-main.jpg"
    )
    assert result.records[0]["additional_images"] == [
        "https://cdn.shop.test/products/trail-shoe-side.jpg"
    ]


def test_access_denied_shell_does_not_succeed() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head><title>Access denied. We invite you to return at a later time to complete your purchase.</title></head>
          <body><h1>Access denied. We invite you to return at a later time to complete your purchase.</h1></body>
        </html>
        """,
        "https://us.louisvuitton.com/eng-us/products/bootleg-pants-nvprod7220319v/1AJUPQ",
    )
    assert result.verdict == "error"
    assert result.retry_request is not None
    assert result.retry_request.reason == "http_shell"


def test_punctuated_shell_title_with_offer_data_does_not_publish_record() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@type": "Product",
              "name": "Oops, Something Went Wrong.",
              "url": "https://shop.test/products/trail-shoe",
              "offers": {"price": "99", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body><h1>Oops, Something Went Wrong.</h1></body>
        </html>
        """,
        "https://shop.test/products/trail-shoe",
    )
    assert result.verdict == "error"
    assert result.records == ()
    assert result.retry_request is not None
    assert result.retry_request.reason == "http_shell"


def test_order_and_duplicate_independence() -> None:
    duplicate = HTML.replace(
        "</head>", HTML.split("<script", 1)[1].join(["<script", "</head>"])
    )
    first = tuple(
        _extract(
            "ecommerce_detail", HTML, "https://shop.test/products/trail-shoe"
        ).records
    )
    second = tuple(
        _extract(
            "ecommerce_detail", duplicate, "https://shop.test/products/trail-shoe"
        ).records
    )

    def public_values(records):
        return tuple(
            {
                key: value
                for key, value in record.model_dump(mode="python").items()
                if not key.startswith("_")
            }
            for record in records
        )

    assert public_values(first) == public_values(second)


def test_ecommerce_detail_result_is_replayable() -> None:
    result = _extract(
        "ecommerce_detail",
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["records"][0]["title"] == "Trail Shoe"
    assert payload["evidence"]
    assert payload["decisions"]


def test_ecommerce_detail_product_endpoint_query_url_publishes_dom_product() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <title>Linen-Cotton Relaxed Taper Easy Pants</title>
            <meta property="description" content="Soft linen cotton pants.">
          </head>
          <body>
            <main>
              <h1>Linen-Cotton Relaxed Taper Easy Pants</h1>
              <picture>
                <source srcset="https://cdn.shop.test/pants.png?width=737">
              </picture>
              <button>Add to bag</button>
            </main>
          </body>
        </html>
        """,
        "https://www.gap.com/browse/product.do?pid=887835012&vid=1",
    )

    assert result.verdict in {"success", "partial"}
    assert result.records[0]["title"] == "Linen-Cotton Relaxed Taper Easy Pants"
    assert result.records[0]["url"] == (
        "https://www.gap.com/browse/product.do?pid=887835012&vid=1"
    )
    assert result.records[0]["_lineage"]["url"]
