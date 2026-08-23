# ruff: noqa: F403, F405
"""test_extraction_integrity_behavior cases split by public behavior."""

from __future__ import annotations

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


def test_product_panel_description_ignores_inline_style_text() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <main>
          <h1>Nike Dunk Low Retro White Black</h1>
          <section class="product-description">
            Product Description
            <style>.css-11s7xk7{font-family:var(--chakra-fonts-body);color:red;}</style>
            From the school-spirited College Colors Program to the vibrant Nike CO.JP collection.
          </section>
        </main>
        """,
        "https://stockx.com/nike-dunk-low-retro-white-black-2021",
    )

    description = result.records[0]["description"]
    assert "From the school-spirited College Colors Program" in description
    assert ".css-11s7xk7" not in description
    assert "font-family" not in description


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
