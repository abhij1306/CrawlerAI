from __future__ import annotations

import json
from types import SimpleNamespace

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.core.shared.field_coerce_text import (
    infer_brand_from_marked_title_path,
    infer_brand_from_product_url,
)
from app.extraction import Surface, extract
from app.extraction.contracts import (
    CommerceDetailProjection,
    Decision,
    Evidence,
    ExtractionResult,
    FieldEvidenceState,
    PublicationEntry,
    SourceLocator,
)
from app.extraction.replay import request_from_acquisition_result
from app.observability.diagnose import build_diagnosis

from tests.unit.extraction_pipeline_test_support import _extract


def test_verbose_semantic_error_shell_cannot_publish_url_title() -> None:
    html = """
    <html><head><title>Something went wrong</title></head>
    <body><main>
      <h1>Something went wrong.</h1>
      <p>Please try again in a moment.</p>
      <p>Additional support and navigation text makes this page longer than 120
      visible characters, but it is still not product content.</p>
    </main></body></html>
    """

    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/example-product",
        requested_fields=("title", "brand", "price"),
    )

    assert result.records == ()
    assert result.transport_outcome == "semantic_shell"
    states = {row.field: row.state for row in result.field_states}
    assert states["title"] == "source_unavailable"
    assert states["brand"] == "source_unavailable"
    assert states["price"] == "source_unavailable"


def test_production_ok_capability_does_not_mask_semantic_shell() -> None:
    html = """
    <html><head><title>Requested Product</title></head>
    <body><main><h1>Requested Product</h1></main></body></html>
    """
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=95,
            url="https://retailer.example/products/requested-product",
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url="https://errors.example/oops",
        html=html,
        method="browser",
        status_code=200,
        artifacts={},
        acquisition_diagnostics={
            "source_capabilities": {"detail_outcome": "ok"},
        },
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url="https://retailer.example/products/requested-product",
        max_records=1,
        requested_fields=("title",),
    )

    result = extract(request)

    assert result.records == ()
    assert result.transport_outcome == "semantic_shell"


def test_selected_network_root_rejects_nested_sibling_product_facts() -> None:
    payload = {
        "data": {
            "product": {
                "title": "Nike Dunk Low Retro White Black (2021)",
                "url": "https://stockx.test/nike-dunk-low-retro-white-black-2021",
                "families": {
                    "color": {
                        "members": {
                            "edges": [
                                {
                                    "node": {
                                        "title": (
                                            "Nike Dunk Low QS CO.JP Reverse "
                                            "Ultraman (2024)"
                                        ),
                                        "url": (
                                            "https://stockx.test/"
                                            "nike-dunk-low-qs-co-jp-reverse-"
                                            "ultraman-2024"
                                        ),
                                    }
                                }
                            ]
                        }
                    }
                },
            }
        }
    }

    result = _extract(
        "ecommerce_detail",
        "<html><body><h1>Nike Dunk Low Retro White Black (2021)</h1></body></html>",
        "https://stockx.test/nike-dunk-low-retro-white-black-2021",
        network_payloads=(payload,),
        requested_fields=("title",),
    )

    assert result.records[0]["title"] == "Nike Dunk Low Retro White Black (2021)"
    assert all("Reverse Ultraman" not in str(row.value) for row in result.evidence)


def test_jsonld_products_sharing_family_url_do_not_mix_title_and_price() -> None:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "Product",
                "@id": "#iphone-16",
                "name": "iPhone 16",
                "url": "https://shop.test/shop/buy-iphone/iphone-16",
                "offers": {
                    "@type": "AggregateOffer",
                    "lowPrice": "699",
                    "priceCurrency": "USD",
                },
            },
            {
                "@type": "Product",
                "@id": "#iphone-16-plus",
                "name": "iPhone 16 Plus",
                "url": "https://shop.test/shop/buy-iphone/iphone-16",
                "offers": {
                    "@type": "AggregateOffer",
                    "lowPrice": "799",
                    "priceCurrency": "USD",
                },
            },
        ],
    }
    html = (
        '<script type="application/ld+json">'
        f"{json.dumps(payload)}</script><h1>iPhone 16</h1>"
    )

    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/shop/buy-iphone/iphone-16",
        requested_fields=("title", "price", "currency"),
    )

    assert result.records[0]["title"] == "iPhone 16"
    assert result.records[0]["price"] == "699.00"
    assert result.records[0]["currency"] == "USD"


def test_nested_primary_brand_and_downstream_description_are_emitted() -> None:
    html = """
    <script>
    window.__INITIAL_STATE__ = {"product": {
      "tcin": "1002150742",
      "primary_brand": {"name": "Levtex Home"},
      "product_vendors": [{"vendor_name": "Levtex Home"}],
      "product_description": {
        "downstream_description": "Verified exact product description."
      }
    }};
    </script>
    """

    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/p/tobago-stripe-duvet-cover-set/A-1002150742",
        requested_fields=("brand", "description"),
    )

    assert result.records[0]["brand"] == "Levtex Home"
    assert result.records[0]["description"] == "Verified exact product description."


def test_embedded_data_layer_concat_json_is_admitted_without_script_execution() -> None:
    html = """
    <script>
      dataLayer = dataLayer.concat([{
        "event": "view_item",
        "ecommerce": {"detail": {"products": [{
          "id": "10015500806",
          "name": "Lucinda Spot Midi Dress",
          "brand": "Phase Eight",
          "item_brand": "Phase Eight"
        }]}}
      }]);
      dataLayer.push(nonJsonCall());
    </script>
    """

    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/product/lucinda-spot-midi-dress-10015500806.html",
        requested_fields=("brand",),
    )

    assert result.records[0]["brand"] == "Phase Eight"


def test_standalone_variant_offer_url_joins_referenced_product_group() -> None:
    payload = {
        "@context": "https://schema.org",
        "@graph": [
            {
                "@type": "ProductGroup",
                "@id": "#group-347273",
                "productGroupID": "347273",
                "name": "Pressurised Padel Balls PB Speed Tri-Pack",
            },
            {
                "@type": "Product",
                "@id": "#product-8804642",
                "isVariantOf": {"@id": "#group-347273"},
                "offers": {
                    "@type": "Offer",
                    "url": (
                        "https://shop.test/p/pressurised-padel-balls/347273/m8804642"
                    ),
                    "price": "10.99",
                    "priceCurrency": "GBP",
                    "availability": "https://schema.org/OnlineOnly",
                },
            },
        ],
    }
    html = '<script type="application/ld+json">' + json.dumps(payload) + "</script>"

    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/p/pressurised-padel-balls/347273/m8804642",
        requested_fields=("price", "currency", "availability"),
    )

    assert result.records[0]["price"] == "10.99"
    assert result.records[0]["currency"] == "GBP"
    assert result.records[0]["availability"] == "in_stock"
    assert all(row.rule_id != "CHILD_JOIN_FAILED" for row in result.findings)


def test_brand_derivation_requires_independent_manufacturer_signal() -> None:
    assert (
        infer_brand_from_product_url(
            url=(
                "https://retailer.com/products/sparkling-prebiotic-beverage-"
                "vinegar-seltzer"
            ),
            title="Sparkling Prebiotic Beverage Vinegar Seltzer",
        )
        is None
    )

    result = _extract(
        "ecommerce_detail",
        "<h1>Breville Bambino® Plus Espresso Machine</h1>",
        "https://shop.test/products/breville-the-bambino-plus/",
        requested_fields=("brand",),
    )

    assert result.records[0]["brand"] == "Breville"


def test_multiword_marked_brand_can_be_confirmed_by_path() -> None:
    assert (
        infer_brand_from_marked_title_path(
            url="https://retailer.com/products/ralph-lauren-polo-shirt",
            title="Ralph Lauren® Polo Shirt",
        )
        == "Ralph Lauren®"
    )


def test_diagnose_winner_uses_published_projection_entry() -> None:
    full = Evidence(
        evidence_id="ev-full",
        bundle_id="b",
        artifact_id="html",
        collector_id="dom",
        collector_version="1",
        fact_type="offer.price",
        raw_value="159.00",
        value="159.00",
        locator=SourceLocator(kind="css_selector", value=".full"),
        directness="direct",
        confidence=0.7,
        subject_id="offer:full",
    )
    sale = full.model_copy(
        update={
            "evidence_id": "ev-sale",
            "raw_value": "79.50",
            "value": "79.50",
            "locator": SourceLocator(kind="css_selector", value=".sale"),
            "subject_id": "offer:sale",
        }
    )
    result = ExtractionResult(
        surface="ecommerce_detail",
        bundle_id="b",
        records=({"price": "79.50"},),
        evidence=(full, sale),
        decisions=(
            Decision(
                decision_id="d-full",
                entity_id="offer:full",
                fact_type="offer.price",
                status="resolved",
                value="159.00",
                accepted_evidence_ids=("ev-full",),
                rejected=(),
                finding_ids=(),
                rule_id="dom_price",
            ),
        ),
        field_states=(
            FieldEvidenceState(
                field="price",
                state="captured_published",
                evidence_ids=("ev-sale",),
            ),
        ),
        publication=CommerceDetailProjection(
            record_entity_id="product:1",
            entries=(
                PublicationEntry(
                    path="record.price",
                    entity_id="offer:sale",
                    value="79.50",
                    selected_fact_id="sel-sale",
                    rule_id="sale_price",
                    evidence_ids=("ev-sale",),
                ),
            ),
        ),
        verdict="success",
    )

    diagnosis = build_diagnosis(
        acquisition_result=SimpleNamespace(
            browser_diagnostics={},
            acquisition_diagnostics={},
            status_code=200,
            final_url="https://shop.test/p",
            method="http",
            html="<html></html>",
        ),
        extraction_result=result,
    )

    price = next(field for field in diagnosis["fields"] if field["field"] == "price")
    assert price["winner"]["value"] == "79.50"
    assert price["winner"]["evidence_ids"] == ["ev-sale"]


def test_diagnose_suppresses_projection_winner_when_records_rejected() -> None:
    evidence_row = Evidence(
        evidence_id="ev-title",
        bundle_id="b",
        artifact_id="html",
        collector_id="url",
        collector_version="1",
        fact_type="product.title",
        raw_value="Missing Product",
        value="Missing Product",
        locator=SourceLocator(kind="url", value="https://shop.test/p"),
        directness="inferred",
        confidence=0.4,
        subject_id="product:1",
    )
    result = ExtractionResult(
        surface="ecommerce_detail",
        bundle_id="b",
        records=(),
        evidence=(evidence_row,),
        decisions=(),
        field_states=(
            FieldEvidenceState(field="title", state="source_unavailable"),
        ),
        publication=CommerceDetailProjection(
            record_entity_id="product:1",
            entries=(
                PublicationEntry(
                    path="record.title",
                    entity_id="product:1",
                    value="Missing Product",
                    rule_id="url_title",
                    evidence_ids=("ev-title",),
                ),
            ),
        ),
        verdict="empty",
    )

    diagnosis = build_diagnosis(
        acquisition_result=SimpleNamespace(
            browser_diagnostics={},
            acquisition_diagnostics={},
            status_code=200,
            final_url="https://shop.test/p",
            method="browser",
            html="<html></html>",
        ),
        extraction_result=result,
    )

    title = next(field for field in diagnosis["fields"] if field["field"] == "title")
    assert "winner" not in title
