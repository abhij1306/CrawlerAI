# ruff: noqa: F403, F405
"""test_extraction_contract_behavior cases split by public behavior."""

from __future__ import annotations

from tests.unit.extraction_pipeline_test_support import *

from tests.unit.extraction_contract_test_support import (
    CollectorOutcome,
    _DETAIL_HTML,
    _DETAIL_URL,
    _DOM_ONLY_DETAIL_HTML,
    _DOM_ONLY_URL,
    _detail_result,
    adapters,
    cascade,
    surface_spec,
)


def test_js_state_image_dimensions_do_not_materialize_as_variants() -> None:
    artifacts = {
        "js_state_objects": {
            "images": [
                {"__typename": "ProductVariantImage", "width": 1206},
                {"__typename": "ProductVariantImage", "width": 4000},
            ],
            "variants": [
                {
                    "__typename": "ProductVariant",
                    "sku": "2775096",
                    "color": "Bissap Glaze",
                    "price": "24",
                    "currency": "USD",
                    "availability": "https://schema.org/InStock",
                }
            ],
        }
    }
    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Lip Balm</h1></body></html>",
        "https://shop.test/products/lip-balm",
        artifacts=artifacts,
    )
    assert result.records[0]["variants"] == [
        {
            "variant_id": "2775096",
            "sku": "2775096",
            "price": "24.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Bissap Glaze",
        }
    ]
    assert result.decisions


def test_identity_only_variant_with_inherited_currency_is_not_published() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type":"Product","name":"Cross Training Tread","url":"https://shop.test/products/tread","offers":{"priceCurrency":"USD"}}
        </script>
        """,
        "https://shop.test/products/tread",
        network_payloads=(
            {
                "body": {
                    "product": {
                        "name": "Cross Training Tread",
                        "url": "https://shop.test/products/tread",
                        "currency": "USD",
                        "variants": [
                            {"id": "price-id-1"},
                            {"id": "price-id-2"},
                        ],
                    }
                }
            },
        ),
    )

    assert not result.records[0].get("variants")


def test_js_state_media_id_and_width_do_not_materialize_as_variant() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Lip Balm</h1></main>",
        "https://shop.test/products/lip-balm",
        artifacts={
            "js_state_objects": {
                "product": {
                    "name": "Lip Balm",
                    "url": "https://shop.test/products/lip-balm",
                    "price": 18,
                    "currency": "USD",
                    "media": [
                        {
                            "id": "33841425055989",
                            "width": 916,
                            "src": "https://cdn.shop.test/lip-balm.jpg",
                        }
                    ],
                }
            }
        },
    )

    assert not result.records[0].get("variants")
    assert all(row.fact_type != "variant.option.width" for row in result.evidence)


def test_responsive_layout_dimensions_do_not_materialize_as_variants() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@type": "Product",
          "name": "Rustic Cotton T-Shirt",
          "url": "https://shop.test/products/rustic-cotton-t-shirt",
          "offers": {"price": "14.90", "priceCurrency": "USD"}
        }
        </script>
        """,
        "https://shop.test/products/rustic-cotton-t-shirt",
        network_payloads=(
            {
                "body": {
                    "categories": [
                        {
                            "sdui": {
                                "responsiveLayouts": [
                                    {
                                        "id": "layout-card-1",
                                        "dimensions": {"width": 358, "height": 640},
                                    }
                                ]
                            }
                        }
                    ]
                }
            },
        ),
    )

    assert result.records[0]["price"] == "14.90"
    assert not result.records[0].get("variants")


def test_jsonld_aggregate_offer_publishes_bounds_not_current_price() -> None:
    html = HTML.replace(
        '"@type": "Offer",\n    "price": "129",',
        '"@type": "AggregateOffer",\n    "lowPrice": "9.99",\n    "highPrice": "19.99",',
    )
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record.get("price") is None
    assert record["price_min"] == "9.99"
    assert record["price_max"] == "19.99"
    assert record.get("original_price") is None
    assert record["currency"] == "USD"


def test_jsonld_equal_aggregate_bounds_publish_exact_current_price() -> None:
    html = HTML.replace(
        '"@type": "Offer",\n    "price": "129",',
        '"@type": "AggregateOffer",\n    "lowPrice": "19.99",\n    "highPrice": "19.99",',
    )

    record = _extract(
        "ecommerce_detail", html, "https://shop.test/products/trail-shoe"
    ).records[0]

    assert record["price"] == "19.99"
    assert record["price_min"] == "19.99"
    assert record["price_max"] == "19.99"


def test_jsonld_aggregate_offer_child_availability_materializes() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Bambino Plus",
          "url": "https://shop.test/products/bambino-plus",
          "image": "https://shop.test/bambino.jpg",
          "variesBy": ["https://schema.org/size"],
          "hasVariant": [
            {"@type": "Product", "name": "Bambino Plus, Small", "url": "https://shop.test/products/bambino-plus-small"},
            {"@type": "Product", "name": "Bambino Plus, Large", "url": "https://shop.test/products/bambino-plus"}
          ],
          "offers": {
            "@type": "AggregateOffer",
            "lowPrice": "399.95",
            "highPrice": "499.95",
            "priceCurrency": "USD",
            "offers": [
              {
                "@type": "Offer",
                "url": "https://shop.test/products/bambino-plus-small",
                "price": "399.95",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock",
                "sku": "1437371"
              },
              {
                "@type": "Offer",
                "url": "https://shop.test/products/bambino-plus",
                "price": "499.95",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
                "sku": "3302893"
              }
            ]
          }
        }
        </script>
        """,
        "https://shop.test/products/bambino-plus",
    )

    record = result.records[0]
    assert record["price"] == "499.95"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert {(row["size"], row["price"]) for row in record["variants"]} == {
        ("Large", "499.95"),
        ("Small", "399.95"),
    }


def test_jsonld_offer_price_specification_materializes_atomically() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Cartier Sunglasses",
          "url": "https://shop.test/products/cartier-sunglasses",
          "image": "https://shop.test/cartier.jpg",
          "offers": {
            "@type": "Offer",
            "availability": "https://schema.org/InStock",
            "priceSpecification": {
              "@type": "UnitPriceSpecification",
              "price": "1795.00",
              "priceCurrency": "USD"
            }
          }
        }
        </script>
        """,
        "https://shop.test/products/cartier-sunglasses",
    )

    record = result.records[0]
    assert record["price"] == "1795.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    price_evidence = [row for row in result.evidence if row.fact_type == "offer.price"]
    currency_evidence = [
        row for row in result.evidence if row.fact_type == "offer.currency"
    ]
    assert price_evidence and currency_evidence
    assert price_evidence[0].group_id == currency_evidence[0].group_id


def test_jsonld_schema_online_only_availability_is_sellable() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Padel Balls",
          "url": "https://shop.test/products/padel-balls",
          "image": "https://shop.test/padel.jpg",
          "offers": {
            "@type": "Offer",
            "price": "10.99",
            "priceCurrency": "GBP",
            "availability": "https://schema.org/OnlineOnly"
          }
        }
        </script>
        """,
        "https://shop.test/products/padel-balls",
    )

    record = result.records[0]
    assert record["price"] == "10.99"
    assert record["currency"] == "GBP"
    assert record["availability"] == "in_stock"
    assert not any(
        row.fact_type == "offer.availability" and "invalid_availability" in row.flags
        for row in result.evidence
    )


def test_commerce_detail_cascade_publishes_structured_record() -> None:
    record = _detail_result().records[0]
    assert record["title"] == "Trail Runner"
    assert record["price"] == "149.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"


def test_commerce_detail_structured_floor_runs_before_dom_floor() -> None:
    """Structured-source collectors must precede the DOM collector.

    Proven via the harvest ``collector_outcomes`` ordering, with
    ``stage_outcomes`` confirming the deterministic harvest-first pipeline.
    """
    result = _detail_result()
    order = [row.collector_id for row in result.collector_outcomes]
    assert "jsonld" in order and "dom" in order
    structured_ids = {"jsonld", "opengraph", "microdata", "js_state", "network"}
    last_structured = max(
        index for index, cid in enumerate(order) if cid in structured_ids
    )
    assert last_structured < order.index("dom")
    stages = [row.stage for row in result.stage_outcomes]
    assert stages[0] == "harvest"
    assert stages.index("harvest") < stages.index("resolve") < stages.index("publish")


def test_detail_cascade_seam_orders_floors() -> None:
    """Direct seam contract: the cascade itself owns structured->DOM order.

    Exercises ``run_detail_cascade`` without the adapter, asserting the seam
    (not ``pipeline``) sequences the structured floor collectors ahead of the
    DOM floor, that its declared ``DETAIL_FLOOR_ORDER`` matches, and that the
    trailing url identity is present.
    """
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL, _DETAIL_HTML, _DETAIL_URL
    )
    spec = surface_spec(Surface.ECOMMERCE_DETAIL)
    harvest = cascade.run_detail_cascade(request, request.artifact_reader, spec)

    assert cascade.DETAIL_FLOOR_ORDER == ("structured", "dom")
    order = [row.collector_id for row in harvest.collector_outcomes]
    structured_ids = {"jsonld", "opengraph", "microdata", "js_state", "network"}
    last_structured = max(
        index for index, cid in enumerate(order) if cid in structured_ids
    )
    assert last_structured < order.index("dom")
    assert order.index("dom") < order.index("url")


def test_detail_cascade_seam_rejects_listing_spec() -> None:
    """The cardinality guard rejects a ``many``-record listing spec."""
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL, _DETAIL_HTML, _DETAIL_URL
    )
    with pytest.raises(ValueError, match="one-record surface"):
        cascade.run_detail_cascade(
            request, request.artifact_reader, surface_spec(Surface.ECOMMERCE_LISTING)
        )


def test_detail_cascade_seam_supports_both_one_record_surfaces() -> None:
    """Slice 4 registers the job_detail profile alongside ecommerce_detail.

    Both one-record surfaces now have a spec-driven collector profile, so both
    are in ``DETAIL_SUPPORTED_SURFACES`` and route through the seam without any
    ``surface ==`` branch.
    """
    assert Surface.ECOMMERCE_DETAIL in cascade.DETAIL_SUPPORTED_SURFACES
    assert Surface.JOB_DETAIL in cascade.DETAIL_SUPPORTED_SURFACES


def test_detail_cascade_seam_rejects_unsupported_one_record_surface(
    monkeypatch,
) -> None:
    """A one-record surface with no registered profile fails honestly.

    A surface absent from ``_DETAIL_SURFACE_PROFILES`` has no collector profile;
    routing it through another surface's collectors would falsely emit that
    surface's facts, so the seam rejects it rather than returning wrong-surface
    evidence. Exercised by monkeypatching job_detail out of the profile table.
    """
    monkeypatch.setattr(
        cascade,
        "_DETAIL_SURFACE_PROFILES",
        {Surface.ECOMMERCE_DETAIL: cascade._DETAIL_FLOOR_REGISTRY},
    )
    job_request = fixture_request_from_inputs(
        Surface.JOB_DETAIL, "<main><h1>Engineer</h1></main>", "https://jobs.test/e"
    )
    with pytest.raises(ValueError, match="no detail collector profile"):
        cascade.run_detail_cascade(
            job_request, job_request.artifact_reader, surface_spec(Surface.JOB_DETAIL)
        )


def test_detail_cascade_invokes_registry_floors_in_order(monkeypatch) -> None:
    """Orchestration proof: the seam drives the registry floors, not legacy.

    Instruments the profile's floor factories AND the shared
    ``run_detail_collectors`` primitive, then asserts the seam calls each floor
    factory and runs its collectors exactly once, in the declared
    structured->DOM order, and aggregates every floor's evidence. This fails if
    the implementation delegates to the legacy single-pass harvest (which would
    call neither the per-floor factories nor ``run_detail_collectors`` once per
    floor) instead of orchestrating the registry.
    """
    factory_calls: list[str] = []
    collector_batches: list[tuple[str, ...]] = []

    def _structured_probe():
        factory_calls.append("structured")
        return ("STRUCTURED_A", "STRUCTURED_B")

    def _dom_probe():
        factory_calls.append("dom")
        return ("DOM_A",)

    real_run = cascade.run_detail_collectors

    def _instrumented_run(
        collectors, bundle, reader, *, requested_fields=(), allowed_facts=None
    ):
        collector_batches.append(tuple(collectors))
        # Probe sentinels flow through here; emit one outcome per collector so
        # aggregation order is observable. Evidence stays empty (HarvestResult
        # only needs valid Evidence rows, which the outcomes stand in for here).
        outcomes = tuple(
            CollectorOutcome(
                collector_id=name, outcome="produced_evidence", evidence_count=1
            )
            for name in collectors
        )
        return (), outcomes, len(collectors)

    monkeypatch.setattr(
        cascade,
        "_DETAIL_SURFACE_PROFILES",
        {
            Surface.ECOMMERCE_DETAIL: (
                ("structured", _structured_probe),
                ("dom", _dom_probe),
            )
        },
    )
    monkeypatch.setattr(cascade, "run_detail_collectors", _instrumented_run)
    monkeypatch.setattr(
        cascade,
        "detail_recipe_requested_evidence",
        lambda *a, **k: ((), (), 0),
    )

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL, _DETAIL_HTML, _DETAIL_URL
    )
    harvest = cascade.run_detail_cascade(
        request, request.artifact_reader, surface_spec(Surface.ECOMMERCE_DETAIL)
    )

    # Factories invoked once each, structured before DOM.
    assert factory_calls == ["structured", "dom"]
    # Each floor's collector group ran through the shared primitive, in order.
    assert collector_batches == [
        ("STRUCTURED_A", "STRUCTURED_B"),
        ("DOM_A",),
    ]
    # Aggregation preserves floor order across all floors.
    assert [row.collector_id for row in harvest.collector_outcomes] == [
        "STRUCTURED_A",
        "STRUCTURED_B",
        "DOM_A",
    ]
    assert harvest.admitted_source_objects == 3
    assert real_run  # sanity: the real primitive is still importable/unchanged


def test_detail_dispatches_to_cascade(monkeypatch) -> None:
    """The commerce-detail adapter must harvest via ``run_detail_cascade``."""
    calls: list[str] = []
    real_cascade = adapters.run_detail_cascade
    monkeypatch.setattr(
        adapters,
        "run_detail_cascade",
        lambda *a, **k: (calls.append("cascade"), real_cascade(*a, **k))[1],
    )
    result = _detail_result()
    assert calls == ["cascade"]
    assert result.records[0]["title"] == "Trail Runner"


def test_dom_only_detail_cascade_carries_record_without_structured() -> None:
    """Adversarial DOM-only capture: structured floor empty, DOM floor holds."""
    monkeypatch_free = _detail_result(_DOM_ONLY_DETAIL_HTML, _DOM_ONLY_URL)
    by_id = {
        row.collector_id: row.outcome for row in monkeypatch_free.collector_outcomes
    }
    assert by_id.get("jsonld") == "no_match"
    assert by_id.get("dom") == "produced_evidence"
    assert monkeypatch_free.records
    assert monkeypatch_free.records[0]["title"] == "Canyon Pack"
