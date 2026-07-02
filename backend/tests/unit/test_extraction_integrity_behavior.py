# ruff: noqa: F403, F405
from tests.unit.extraction_pipeline_test_support import *


def test_slug_only_detail_output_is_review_not_success() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
    )
    assert result.records
    assert result.records[0]["title"] == "rustic cotton t shirt p04424306"
    assert result.verdict == "partial"


def test_structured_title_outranks_filename_and_internal_id_url_title() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Linen Travel Shirt",
          "url": "https://shop.test/products/99107606086.html",
          "offers": {"price": "89", "priceCurrency": "USD"}
        }
        </script>
        <main><h1>Linen Travel Shirt</h1></main>
        """,
        "https://shop.test/products/99107606086.html",
    )

    assert result.records[0]["title"] == "Linen Travel Shirt"
    assert result.verdict == "partial"


@pytest.mark.parametrize(
    ("page_url", "html"),
    (
        (
            "https://kith.com/products/st40002-02000",
            "<main><h1>st40002 02000</h1></main>",
        ),
        (
            "https://www.amazon.com/example/dp/B0F5Y3X8PP/?th=1",
            "<main><h1>Not Added</h1></main>",
        ),
        (
            "https://shop.lululemon.com/p/jackets/_/prod10930188",
            "<main><h1>prod10930188</h1></main>",
        ),
        (
            "https://www.ralphlauren.global/in/en/the-iconic-cotton-chino-ball-cap-650310.html",
            "<html><body></body></html>",
        ),
        (
            "https://shop.test/product.do?id=12345",
            "<main><h1>product.do</h1></main>",
        ),
    ),
)
def test_identifier_placeholder_and_filename_titles_do_not_materialize(
    page_url: str,
    html: str,
) -> None:
    result = _extract(
        "ecommerce_detail",
        html,
        page_url,
        requested_fields=("title",),
    )

    assert not result.records or result.records[0].get("title") is None
    assert any(
        finding.rule_id == "MISSING_CONTRACT_FIELD"
        and finding.metadata.get("field") == "title"
        for finding in result.findings
    )
    assert any(
        finding.rule_id == "MISSING_OR_GENERIC_TITLE" for finding in result.findings
    )
    assert result.verdict in {"empty", "partial", "review"}


@pytest.mark.parametrize(
    "bad_title", ("Black", "Refurbished", "& More", "Shipping", "TALL LARGE")
)
def test_option_condition_navigation_and_shipping_titles_are_rejected_at_admission(
    bad_title: str,
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"<main><h1>{bad_title}</h1></main>",
        "https://shop.test/products/real-product-name",
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "real product name"
    bad_rows = [
        row
        for row in result.evidence
        if row.fact_type == "product.title" and str(row.value) == bad_title
    ]
    assert bad_rows
    assert all("generic_title" in row.flags for row in bad_rows)
    accepted_ids = {
        evidence_id
        for decision in result.decisions
        if decision.fact_type == "product.title"
        for evidence_id in decision.accepted_evidence_ids
    }
    assert not accepted_ids.intersection(row.evidence_id for row in bad_rows)


def test_brand_boilerplate_values_are_rejected_at_admission() -> None:
    for bad_brand in (
        "Refurbished",
        "Womens",
        "the",
        "green",
        "Black",
        "Fragrance",
        "Register",
        "at",
        "India | The",
    ):
        result = _extract(
            "ecommerce_detail",
            f"""
            <head><meta property="product:brand" content="{bad_brand}"></head>
            <main><h1>Real Product Name</h1></main>
            """,
            "https://shop.test/products/real-product-name",
        )

        assert result.records
        assert result.records[0].brand is None


def test_unavailable_product_source_produces_precise_partial_field_states() -> None:
    base = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        "<main><h1>Unavailable Offer Product</h1></main>",
        "https://shop.test/products/unavailable-offer-product",
        requested_fields=("price", "currency", "availability"),
    )
    request = base.model_copy(
        update={
            "capture": base.capture.model_copy(
                update={
                    "acquisition_diagnostics": {
                        "source_capabilities": {
                            "product_data_source_unavailable": True,
                            "affected_field_families": (
                                "price",
                                "currency",
                                "availability",
                                "variants",
                            ),
                        }
                    }
                }
            )
        }
    )

    result = extract(request)
    states = {row.field: row for row in result.field_states}

    assert result.transport_outcome == "ok"
    assert result.data_integrity == "partial"
    assert result.verdict in {"partial", "review"}
    assert states["title"].state == "captured_published"
    assert states["price"].state == "source_unavailable"
    assert states["currency"].state == "source_unavailable"
    assert states["availability"].state == "source_unavailable"
    assert states["price"].reason_codes == ("product_data_source_unavailable",)


def test_complete_product_reports_clean_integrity_separately_from_transport() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Complete Product",
          "brand": "Complete Brand",
          "description": "A complete product-specific description.",
          "url": "https://shop.test/products/complete-product",
          "image": "https://cdn.shop.test/complete-product.jpg",
          "offers": {"price": "10", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/complete-product",
    )
    states = {row.field: row.state for row in result.field_states}

    assert result.transport_outcome == "ok"
    assert result.data_integrity == "clean"
    assert result.verdict == "success"
    assert states["title"] == "captured_published"
    assert states["price"] == "captured_published"
    assert states["currency"] == "captured_published"
    assert states["image_url"] == "captured_published"


def test_ecommerce_detail_field_states_cover_surface_and_contract_fields() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Minimal Product",
          "url": "https://shop.test/products/minimal-product"
        }
        </script>
        """,
        "https://shop.test/products/minimal-product",
    )
    states = {row.field: row for row in result.field_states}

    for field in (
        "title",
        "url",
        "brand",
        "description",
        "image_url",
        "price",
        "currency",
        "availability",
        "variants",
        "variant_count",
    ):
        assert field in states
    assert states["title"].state == "captured_published"
    assert states["brand"].state == "not_present_in_captured_sources"
    assert states["price"].state == "not_present_in_captured_sources"
    assert states["variants"].state == "not_requested"


def test_js_state_budget_keeps_identity_and_requested_offer_group(monkeypatch) -> None:
    from app.extraction.collectors import js_state

    monkeypatch.setattr(js_state, "MAX_EVIDENCE_PER_SOURCE_OBJECT", 3)
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Trail Shoe</h1></main>",
        "https://shop.test/products/trail-shoe",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Trail Shoe",
                    "url": "https://shop.test/products/trail-shoe",
                    "price": "129",
                    "currency": "USD",
                    "sku": "TS-1",
                    "images": [
                        "https://cdn.shop.test/trail-1.jpg",
                        "https://cdn.shop.test/trail-2.jpg",
                    ],
                }
            }
        },
        requested_fields=("price",),
    )

    kept_facts = {
        row.fact_type for row in result.evidence if row.collector_id == "js_state"
    }
    assert {"product.url", "offer.price", "offer.currency"} <= kept_facts
    outcome = next(
        row
        for row in result.collector_outcomes
        if row.collector_id == "js_state" and row.outcome == "budget_limited"
    )
    assert "assets" in outcome.dropped_fact_families


def test_network_budget_reports_dropped_fact_families(monkeypatch) -> None:
    from app.extraction.collectors import metadata

    monkeypatch.setattr(metadata, "MAX_EVIDENCE_PER_SOURCE_OBJECT", 3)
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
                            "https://cdn.shop.test/trail-1.jpg",
                            "https://cdn.shop.test/trail-2.jpg",
                        ],
                    }
                },
            },
        ),
        requested_fields=("price",),
    )

    outcome = next(
        row
        for row in result.collector_outcomes
        if row.collector_id == "network" and row.outcome == "budget_limited"
    )
    assert "assets" in outcome.dropped_fact_families
    assert outcome.source_path


def test_multiple_incomplete_candidate_offers_are_grouped() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Grouped Offer Product",
          "url": "https://shop.test/products/grouped-offer-product",
          "hasVariant": [
            {"@type": "Product", "sku": "GO-1", "offers": {"price": "10"}},
            {"@type": "Product", "sku": "GO-2", "offers": {"price": "12"}},
            {"@type": "Product", "sku": "GO-3", "offers": {"price": "14"}}
          ]
        }
        </script>
        """,
        "https://shop.test/products/grouped-offer-product",
        requested_fields=("variants",),
    )

    findings = [
        row for row in result.findings if row.rule_id == "PRICE_WITHOUT_CURRENCY"
    ]

    assert len(findings) == 1
    assert findings[0].metadata["candidate_offer_count"] == 3
    assert len(findings[0].metadata["example_offer_entity_ids"]) == 3


def test_detail_text_fields_are_canonicalized_before_publication() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Trail &amp; Road Shoe",
          "brand": "Acme&nbsp;Run",
          "description": "<p>Fast &amp; light</p><ul><li>Mesh upper</li></ul>",
          "url": "https://shop.test/products/trail-road-shoe",
          "image": "https://cdn.shop.test/trail.jpg",
          "offers": {"price": "90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/trail-road-shoe",
    )
    record = result.records[0]

    assert record["title"] == "Trail & Road Shoe"
    assert record["brand"] == "Acme Run"
    assert "Fast & light" in record["description"]
    assert "<" not in record["description"]
    assert "&amp;" not in record["description"]


def test_hidden_requested_product_panel_content_is_collected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Panel Product</h1>
          <section class="product-accordion">
            <div hidden data-field="description">Hidden product composition.</div>
          </section>
        </main>
        """,
        "https://shop.test/products/panel-product",
        requested_fields=("description",),
    )
    rows = [
        row
        for row in result.evidence
        if row.fact_type == "product.description"
        and "hidden_product_content" in row.flags
    ]

    assert result.records[0]["description"] == "Hidden product composition."
    assert rows
    assert rows[0].metadata["component_role"] == "product_panel"


def test_product_panel_description_is_collected_without_requested_field() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Canvas Field Jacket</h1>
          <section class="product-details">
            <div class="product-description">
              Durable cotton canvas jacket with reinforced seams and soft lining.
            </div>
          </section>
        </main>
        """,
        "https://shop.test/products/canvas-field-jacket",
    )

    assert result.records[0]["description"].startswith("Durable cotton canvas jacket")
    assert any(
        row.fact_type == "product.description"
        and row.collector_id == "dom"
        and row.metadata.get("component_role") == "product_panel"
        for row in result.evidence
    )


def test_product_panel_description_beats_hard_boundary_meta_excerpt() -> None:
    excerpt = "A" * 320
    result = _extract(
        "ecommerce_detail",
        f"""
        <html>
          <head><meta name="description" content="{excerpt}"></head>
          <body>
            <main>
              <h1>Trail Fleece</h1>
              <section class="product-description">
                Warm trail fleece with a brushed interior, secure pockets, and a relaxed fit for layering.
              </section>
            </main>
          </body>
        </html>
        """,
        "https://shop.test/products/trail-fleece",
    )

    assert result.records[0]["description"].startswith("Warm trail fleece")


def test_visible_product_offer_block_emits_atomic_dom_offer() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Wide Leg Chino</h1>
          <section class="product-purchase-panel">
            <div class="current-price">$47.00</div>
            <p class="stock-message">In stock</p>
          </section>
        </main>
        """,
        "https://shop.test/products/wide-leg-chino",
    )
    offer_rows = [
        row for row in result.evidence if row.collector_id == "dom" and row.group_id
    ]
    groups = _group_facts_by_group_id(offer_rows)

    assert result.records[0]["price"] == "47.00"
    assert result.records[0]["currency"] == "USD"
    assert result.records[0]["availability"] == "in_stock"
    assert any(
        {"offer.price", "offer.currency", "offer.availability"} <= facts
        for facts in groups.values()
    )


@pytest.mark.parametrize(
    ("price_text", "expected"),
    (
        ("€1.299,00", "1299.00"),
        ("$1,299.00", "1299.00"),
        ("₹1,86,000", "186000.00"),
    ),
)
def test_visible_dom_offer_normalizes_locale_price_grouping(
    price_text: str, expected: str
) -> None:
    result = _extract(
        "ecommerce_detail",
        f"<main><h1>Locale Product</h1><div class='current-price'>{price_text}</div></main>",
        "https://shop.test/products/locale-product",
    )

    assert result.records[0]["price"] == expected


def test_related_product_dom_offer_is_not_attached_to_selected_product() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Selected Boot</h1>
          <section class="product-purchase-panel">
            <div class="current-price">$120.00</div>
          </section>
          <section class="recommendations">
            <div class="current-price">$15.00</div>
          </section>
        </main>
        """,
        "https://shop.test/products/selected-boot",
    )

    assert result.records[0]["price"] == "120.00"


def test_hidden_recommendation_content_is_rejected() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Panel Product</h1>
          <section class="recommendations">
            <div hidden data-field="description">Other product copy.</div>
          </section>
        </main>
        """,
        "https://shop.test/products/panel-product",
        requested_fields=("description",),
    )

    assert result.records[0].get("description") is None
    assert not [
        row
        for row in result.evidence
        if row.fact_type == "product.description"
        and str(row.value) == "Other product copy."
    ]


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
          <meta name="brand" content="Invoro">
          <meta name="twitter:image" content="https://shop.test/i/trail.jpg">
        </head>
        <main></main>
        """,
        "https://shop.test/products/TS-100",
    )

    record = result.records[0]
    assert record["title"] == "Trail Shoe"
    assert record["brand"] == "Invoro"
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
                        "brand": {"name": "Invoro"},
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
    assert record["brand"] == "Invoro"
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
