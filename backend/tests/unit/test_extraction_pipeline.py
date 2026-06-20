from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.extraction import Surface, extract
from app.extraction.contracts import CommerceDetailRecord, ExtractionRequest
from app.extraction.contracts import Evidence
from app.extraction.replay import (
    fixture_request_from_inputs,
    request_from_acquisition_result,
)

pytestmark = pytest.mark.unit


HTML = """
<html>
<head>
<script type="application/ld+json">
{
  "@context": "https://schema.org",
  "@type": "Product",
  "name": "Trail Shoe",
  "brand": {"@type": "Brand", "name": "Invoro"},
  "sku": "TS-1",
  "url": "https://shop.test/products/trail-shoe",
  "image": ["https://shop.test/i/trail.jpg"],
  "offers": {
    "@type": "Offer",
    "price": "129",
    "priceCurrency": "usd",
    "availability": "https://schema.org/InStock"
  },
  "hasVariant": [
    {"@type": "Product", "sku": "TS-1-BLK-9", "color": "Black", "size": "9"}
  ]
}
</script>
</head>
<body><main><h1>Trail Shoe</h1></main></body>
</html>
"""


def _extract(
    surface: str,
    html: str,
    page_url: str,
    *,
    max_records: int = 1,
    artifacts: dict[str, object] | None = None,
    network_payloads: tuple[dict[str, object], ...] = (),
):
    return extract(
        fixture_request_from_inputs(
            Surface(surface),
            html,
            page_url,
            max_records=max_records,
            artifacts=artifacts,
            network_payloads=network_payloads,
        )
    )


def test_materializes_once_with_lineage_and_quality() -> None:
    result = _extract(
        "ecommerce_detail",
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["title"] == "Trail Shoe"
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["availability"] == "in_stock"
    assert result.verdict == "success"
    assert record["_lineage"]["price"]["derived_fact_id"]
    assert result.evidence
    assert "selected" not in record["variants"][0]


def test_jsonld_product_group_uses_shade_as_color_axis() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Eye Shadow",
      "url": "https://shop.test/products/eye-shadow",
      "hasVariant": [
        {
          "@type": "Product",
          "sku": "MY6RPE",
          "name": "Eye Shadow - Carbon - .05 oz / 1.5 g",
          "color": "Black",
          "size": ".05 oz / 1.5 g",
          "offers": {
            "@type": "Offer",
            "url": "https://shop.test/products/eye-shadow?shade=Carbon",
            "price": "25",
            "priceCurrency": "USD",
            "availability": "http://schema.org/InStock"
          }
        }
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/eye-shadow")
    assert result.records[0]["variants"] == [
        {
            "sku": "MY6RPE",
            "price": "25.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Carbon",
            "size": ".05 oz / 1.5 g",
        }
    ]


def test_jsonld_one_axis_variants_with_child_offers_materialize() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Suede Sneakers",
      "url": "https://shop.test/products/suede",
      "hasVariant": [
        {
          "@type": "Product",
          "color": "Red",
          "offers": {"@type": "Offer", "price": "85", "priceCurrency": "USD"}
        },
        {
          "@type": "Product",
          "color": "Blue",
          "offers": {"@type": "Offer", "price": "80", "priceCurrency": "USD"}
        }
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/suede")
    assert result.records[0]["variants"] == [
        {"price": "80.00", "currency": "USD", "color": "Blue"},
        {"price": "85.00", "currency": "USD", "color": "Red"},
    ]


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
            "sku": "2775096",
            "price": "24.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Bissap Glaze",
        }
    ]
    assert result.decisions


def test_jsonld_aggregate_offer_low_price_materializes() -> None:
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
    assert record["price"] == "9.99"
    assert record["currency"] == "USD"


def test_extraction_request_has_no_artifact_payloads_field() -> None:
    assert "artifact_payloads" not in ExtractionRequest.model_fields


def test_runtime_capture_bundle_uses_acquisition_metadata() -> None:
    acquisition = PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=42,
            url="https://shop.test/products/trail-shoe",
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url="https://shop.test/products/trail-shoe",
        html=HTML,
        method="browser",
        status_code=200,
        artifacts={},
    )
    request = request_from_acquisition_result(
        Surface.ECOMMERCE_DETAIL,
        acquisition,
        requested_url="https://shop.test/products/trail-shoe",
        max_records=1,
    )
    assert request.capture.run_id == 42
    assert request.capture.http_status == 200
    assert request.capture.acquisition_method == "browser"
    assert request.capture.browser_attempted is True
    assert request.capture.acquisition_outcome == "ok"
    assert all(
        not artifact.storage_uri.startswith("memory://")
        for artifact in request.capture.artifacts
    )


def test_evidence_is_immutable() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    item = result.evidence[0]
    try:
        item.value = "changed"  # type: ignore[misc]
    except (ValidationError, TypeError):
        pass
    assert isinstance(item, Evidence)
    assert item.value != "changed"


def test_offer_price_without_currency_is_not_published() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "")
    result = _extract("ecommerce_detail", html, "https://shop.test/products/trail-shoe")
    assert result.records
    public = result.records[0].model_dump(mode="json", exclude_none=True)
    assert "price" not in public
    assert "currency" not in public
    assert "PRICE_WITHOUT_CURRENCY" in {finding.rule_id for finding in result.findings}


def test_uncorroborated_cent_magnitude_price_is_not_silently_repaired() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "name": "Runner Tee",
                    "url": "https://shop.test/products/runner-tee",
                    "price": "3499",
                    "currency": "USD",
                }
            },
        ),
    )
    assert result.records[0]["price"] == "3499.00"
    assert result.records[0]["currency"] == "USD"


def test_slug_only_detail_output_is_review_not_success() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
    )
    assert result.records
    assert result.records[0]["title"] == "rustic cotton t shirt p04424306.html"
    assert result.verdict == "review"


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


def test_shell_title_with_offer_data_does_not_publish_record() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <html>
          <head>
            <script type="application/ld+json">
            {
              "@type": "Product",
              "name": "Error page",
              "url": "https://shop.test/products/error-page",
              "offers": {"price": "99", "priceCurrency": "USD"}
            }
            </script>
          </head>
          <body><h1>Error page</h1></body>
        </html>
        """,
        "https://shop.test/products/error-page",
    )
    assert result.verdict == "error"
    assert result.records == ()
    assert result.retry_request is not None
    assert result.retry_request.reason == "http_shell"


def test_order_and_duplicate_independence() -> None:
    duplicate = HTML.replace("</head>", HTML.split("<script", 1)[1].join(["<script", "</head>"]))
    first = tuple(_extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe").records)
    second = tuple(_extract("ecommerce_detail", duplicate, "https://shop.test/products/trail-shoe").records)
    assert first == second


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


def test_ecommerce_listing_cutover_materializes_with_lineage() -> None:
    html = """
    <main>
      <article class="product-card">
        <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
        <span class="price">$129.00</span>
        <img src="/images/trail.jpg">
      </article>
      <article class="product-card">
        <a href="/products/day-pack"><h2>Day Pack</h2></a>
        <span class="price">$89.00</span>
      </article>
    </main>
    """
    result = _extract(
        "ecommerce_listing",
        html,
        "https://shop.test/collections/all",
        max_records=5,
    )
    assert result.verdict == "success"
    assert result.evidence
    assert result.decisions
    assert {row["title"] for row in result.records} == {"Trail Shoe", "Day Pack"}
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "ecommerce_listing" for item in result.evidence)


def test_ecommerce_listing_result_is_replayable() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <section>
          <div class="product-tile">
            <a href="/products/trail-shoe" title="Trail Shoe">Trail Shoe</a>
            <div data-price="129.00"></div>
          </div>
        </section>
        """,
        "https://shop.test/collections/all",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows == [
        {
            "title": "Trail Shoe",
            "url": "https://shop.test/products/trail-shoe",
            "price": "129.00",
            "_lineage": rows[0]["_lineage"],
            "_subject_id": rows[0]["_subject_id"],
        }
    ]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "ecommerce_listing"
    assert payload["evidence"]
    assert payload["decisions"]


def test_ecommerce_listing_filters_docs_utility_links() -> None:
    result = _extract(
        "ecommerce_listing",
        """
        <main>
          <li><a href="/docs" title="API">API</a></li>
          <li><a href="/file-download" title="File Download">File Download</a></li>
          <li><a href="/sitemap.xml" title="Sitemap">Sitemap</a></li>
          <div class="row product">
            <a href="/products/trail-shoe"><h2>Trail Shoe</h2></a>
          </div>
        </main>
        """,
        "https://shop.test/products",
        max_records=5,
    )
    assert [row["title"] for row in result.records] == ["Trail Shoe"]


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


def test_product_group_variants_have_lineage_and_parent_subjects() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Everyday Tee",
      "url": "https://shop.test/products/everyday-tee",
      "hasVariant": [
        {"@type": "Product", "sku": "TEE-BLK-S", "color": "Black", "size": "S"},
        {"@type": "Product", "sku": "TEE-BLK-M", "color": "Black", "size": "M"}
      ]
    }
    </script>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/everyday-tee")
    assert result.verdict == "partial"
    assert result.records[0]["variants"] == [
        {"sku": "TEE-BLK-S", "color": "Black", "size": "S"},
        {"sku": "TEE-BLK-M", "color": "Black", "size": "M"},
    ]
    variant_evidence = [item for item in result.evidence if item.fact_type.startswith("variant.")]
    assert variant_evidence
    assert all(item.subject_id for item in variant_evidence)
    assert all(item.parent_subject_id for item in variant_evidence)


def test_typed_commerce_detail_record_round_trip_preserves_variants() -> None:
    result = _extract("ecommerce_detail", HTML, "https://shop.test/products/trail-shoe")
    typed = CommerceDetailRecord.model_validate(result.records[0])
    dumped = typed.model_dump(mode="json", exclude_none=True)
    assert dumped["variants"] == result.records[0]["variants"]
    assert dumped["_lineage"]["variants"]


def test_related_product_root_cannot_overwrite_selected_detail_entity() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Selected Trail Shoe",
        "url": "https://shop.test/products/selected-trail-shoe",
        "sku": "SEL-1",
        "offers": {"@type": "Offer", "price": "120", "priceCurrency": "USD"}
      },
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Related Day Pack",
        "url": "https://shop.test/products/day-pack",
        "sku": "REL-1",
        "offers": {"@type": "Offer", "price": "999", "priceCurrency": "USD"}
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/selected-trail-shoe",
    )
    assert result.target.status == "resolved"
    assert result.records[0]["title"] == "Selected Trail Shoe"
    assert result.records[0]["price"] == "120.00"
    assert result.records[0]["url"] == "https://shop.test/products/selected-trail-shoe"


def test_noisy_variant_root_cannot_outrank_complete_offer_product() -> None:
    html = """
    <script type="application/ld+json">
    [
      {
        "@context": "https://schema.org",
        "@type": "Product",
        "name": "Soleil pant in linen",
        "url": "https://shop.test/products/soleil-pant",
        "sku": "CI939-BR8825",
        "offers": {"@type": "Offer", "price": "14273", "priceCurrency": "INR"}
      },
      {
        "@context": "https://schema.org",
        "@type": "ProductGroup",
        "name": "Linen",
        "url": "https://shop.test/products/linen",
        "hasVariant": [
          {"@type": "Product", "color": "WT0002", "url": "https://api.shop.test/99107606086.html"}
        ]
      }
    ]
    </script>
    """
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/soleil-pant?colorCode=BR8825",
    )
    assert result.records[0]["title"] == "Soleil pant in linen"
    assert result.records[0]["price"] == "14273.00"
    assert not result.records[0].get("variants")


def test_dom_option_controls_do_not_materialize_sellable_variants() -> None:
    html = """
    <main>
      <h1>Everyday Tee</h1>
      <select name="size">
        <option>Select size</option>
        <option>S</option>
        <option>M</option>
      </select>
      <button data-option-name="color">Black</button>
    </main>
    """
    result = _extract("ecommerce_detail", html, "https://shop.test/products/everyday-tee")
    assert result.records
    assert not result.records[0].get("variants")
    option_evidence = [item for item in result.evidence if item.fact_type.startswith("option.")]
    assert option_evidence
    assert result.graph.entity_counts["option"] == 3


def test_variant_identity_merges_sources_and_materializes_child_offer() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Everyday Tee",
      "url": "https://shop.test/products/everyday-tee",
      "hasVariant": [
        {"@type": "Product", "sku": "TEE-BLK-S", "color": "Black", "size": "S"}
      ]
    }
    </script>
    """
    artifacts = {
        "js_state_objects": {
            "variant": {
                "id": "v1",
                "sku": "TEE-BLK-S",
                "color": "Black",
                "size": "S",
                "price": "18.5",
                "currency": "USD",
                "availability": "InStock",
            }
        }
    }
    result = _extract(
        "ecommerce_detail",
        html,
        "https://shop.test/products/everyday-tee",
        artifacts=artifacts,
    )
    variants = result.records[0]["variants"]
    assert variants == [
        {
            "variant_id": "v1",
            "sku": "TEE-BLK-S",
            "price": "18.50",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Black",
            "size": "S",
        }
    ]
    assert result.graph.entity_counts["variant"] == 1
    assert result.records[0]["_lineage"]["variants"][0]["price"]


def test_js_state_later_product_object_backfills_missing_variant_rows() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Bootleg Pants</h1></main>",
        "https://shop.test/products/bootleg-pants",
        artifacts={
            "js_state_objects": {
                "bootstrap": {
                    "name": "Bootleg Pants",
                    "price": "1290",
                    "currency": "USD",
                },
                "hydration": {
                    "product": {
                        "name": "Bootleg Pants",
                        "url": "https://shop.test/products/bootleg-pants",
                        "variants": [
                            {
                                "variantId": "black-s",
                                "sku": "BP-BLK-S",
                                "color": "Black",
                                "size": "S",
                                "price": {"value": "1290"},
                                "currency": "USD",
                            },
                            {
                                "variantId": "black-m",
                                "sku": "BP-BLK-M",
                                "color": "Black",
                                "size": "M",
                                "price": {"value": "1290"},
                                "currency": "USD",
                            },
                        ],
                    }
                },
            }
        },
    )
    assert result.records[0]["variants"] == [
        {
            "variant_id": "black-s",
            "sku": "BP-BLK-S",
            "price": "1290.00",
            "currency": "USD",
            "color": "Black",
            "size": "S",
        },
        {
            "variant_id": "black-m",
            "sku": "BP-BLK-M",
            "price": "1290.00",
            "currency": "USD",
            "color": "Black",
            "size": "M",
        },
    ]


def test_network_variant_offer_rows_materialize_with_lineage() -> None:
    result = _extract(
        "ecommerce_detail",
        "<main><h1>Runner Tee</h1></main>",
        "https://shop.test/products/runner-tee",
        network_payloads=(
            {
                "body": {
                    "data": {
                        "product": {
                            "name": "Runner Tee",
                            "url": "https://shop.test/products/runner-tee",
                            "variants": [
                                {
                                    "variantId": "navy-s",
                                    "sku": "RT-NV-S",
                                    "color": "Navy",
                                    "size": "S",
                                    "price": "35",
                                    "currency": "USD",
                                    "available": True,
                                },
                                {
                                    "variantId": "navy-m",
                                    "sku": "RT-NV-M",
                                    "color": "Navy",
                                    "size": "M",
                                    "price": "35",
                                    "currency": "USD",
                                    "available": False,
                                },
                            ],
                        }
                    }
                }
            },
        ),
    )
    assert result.records[0]["variants"] == [
        {
            "variant_id": "navy-s",
            "sku": "RT-NV-S",
            "price": "35.00",
            "currency": "USD",
            "availability": "in_stock",
            "color": "Navy",
            "size": "S",
        },
        {
            "variant_id": "navy-m",
            "sku": "RT-NV-M",
            "price": "35.00",
            "currency": "USD",
            "availability": "out_of_stock",
            "color": "Navy",
            "size": "M",
        },
    ]
    assert result.records[0]["_lineage"]["variants"][0]["availability"]
    assert any(
        item.artifact_id == "network_0" and item.collector_id == "network"
        for item in result.evidence
    )


def test_mixed_numeric_and_string_identity_values_do_not_crash() -> None:
    artifacts = {
        "js_state_objects": {
            "product": {
                "title": "Rustic Cotton T-Shirt",
                "sku": 123,
                "price": "29.90",
                "currency": "USD",
            }
        }
    }
    html = '<html><body><h1>Rustic Cotton T-Shirt</h1><div data-sku="123"></div></body></html>'
    result = _extract(
        "ecommerce_detail",
        html,
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    record = result.records[0] if result.records else None
    assert record is not None
    assert record["sku"] in {123, "123"}


def test_adapter_artifact_flows_through_evidence_engine() -> None:
    result = _extract(
        "ecommerce_detail",
        "<html><body></body></html>",
        "https://shop.test/products/adapter-widget",
        artifacts={
            "adapter_artifacts": [
                {
                    "artifact_type": "adapter_json",
                    "adapter_name": "legacy",
                    "body": {
                        "title": "Adapter Widget",
                        "sku": "AD-1",
                        "price": "10.00",
                        "currency": "USD",
                    },
                }
            ]
        },
    )
    assert result.records
    assert result.records[0]["title"] == "Adapter Widget"
    assert result.records[0]["_lineage"]["title"]
    assert any(item.artifact_id == "adapter_0" for item in result.evidence)


def test_job_detail_cutover_materializes_with_lineage() -> None:
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "JobPosting",
          "title": "Staff Backend Engineer",
          "hiringOrganization": {"name": "Invoro"},
          "jobLocation": {"address": {"addressLocality": "Remote", "addressCountry": "US"}},
          "datePosted": "2026-06-01",
          "employmentType": "FULL_TIME",
          "description": "Build deterministic extraction systems.",
          "url": "https://jobs.test/staff-backend-engineer"
        }
        </script>
      </head>
      <body><main><h1>Fallback Title</h1></main></body>
    </html>
    """
    result = _extract("job_detail", html, "https://jobs.test/staff-backend-engineer")
    assert result.verdict == "success"
    assert result.records[0]["title"] == "Staff Backend Engineer"
    assert result.records[0]["company"] == "Invoro"
    assert result.records[0]["location"] == "Remote, US"
    assert result.records[0]["_lineage"]["title"]
    assert result.evidence
    assert result.decisions
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_detail" for item in result.evidence)


def test_job_detail_wrong_surface_product_returns_error_without_commerce_aliases() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Trail Shoe",
      "offers": {"@type": "Offer", "price": "129", "priceCurrency": "USD"}
    }
    </script>
    """
    result = _extract("job_detail", html, "https://jobs.test/not-a-job")
    assert result.verdict == "error"
    assert not result.records
    assert {finding.rule_id for finding in result.findings} == {"WRONG_SURFACE_CONTENT"}


def test_job_detail_result_is_replayable() -> None:
    result = _extract(
        "job_detail",
        """
        <main>
          <h1>Staff Backend Engineer</h1>
          <div class="company">Invoro</div>
          <div class="location">Remote</div>
          <a href="/apply/staff-backend-engineer">Apply</a>
        </main>
        """,
        "https://jobs.test/staff-backend-engineer",
        max_records=1,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows and rows[0]["title"] == "Staff Backend Engineer"
    assert rows[0]["apply_url"] == "https://jobs.test/apply/staff-backend-engineer"
    assert rows[0]["_lineage"]["title"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "job_detail"
    assert payload["evidence"]
    assert payload["decisions"]


def test_job_listing_cutover_materializes_with_lineage() -> None:
    result = _extract(
        "job_listing",
        """
        <ul>
          <li class="job-card">
            <a href="/jobs/backend"><h2>Backend Engineer</h2></a>
            <span class="company">Invoro</span>
            <span class="location">Remote</span>
          </li>
          <li class="job-card">
            <a href="/jobs/data"><h2>Data Engineer</h2></a>
            <span class="company">Invoro</span>
          </li>
        </ul>
        """,
        "https://jobs.test/careers",
        max_records=5,
    )
    assert result.verdict == "success"
    assert {row["title"] for row in result.records} == {"Backend Engineer", "Data Engineer"}
    assert all(row["_lineage"]["title"] for row in result.records)
    assert all(item.subject_id for item in result.evidence)
    assert all(item.surface.value == "job_listing" for item in result.evidence)


def test_job_listing_result_is_replayable() -> None:
    result = _extract(
        "job_listing",
        """
        <article class="job-card">
          <a href="/jobs/backend" title="Backend Engineer">Backend Engineer</a>
          <span class="company">Invoro</span>
        </article>
        """,
        "https://jobs.test/careers",
        max_records=3,
    )
    rows = result.model_dump(mode="json", exclude_none=True)["records"]
    assert rows and rows[0]["title"] == "Backend Engineer"
    assert rows[0]["url"] == "https://jobs.test/jobs/backend"
    assert rows[0]["_lineage"]["title"]
    payload = result.model_dump(mode="json", exclude_none=True)
    assert payload["surface"] == "job_listing"
    assert payload["evidence"]
    assert payload["decisions"]


def test_job_listing_greenhouse_table_rows_materialize() -> None:
    result = _extract(
        "job_listing",
        """
        <main><table>
          <tr class="job-post">
            <td class="cell">
              <a href="https://careers.test/positions/123">
                <p class="body body--medium">Senior Data Scientist</p>
                <p class="body body__secondary body--metadata">Remote</p>
              </a>
            </td>
          </tr>
        </table></main>
        """,
        "https://job-boards.test/embed/job_board?for=company",
        max_records=5,
    )
    assert result.records
    assert result.records[0]["title"] == "Senior Data Scientist"
    assert result.records[0]["url"] == "https://careers.test/positions/123"
    assert result.records[0]["location"] == "Remote"


def test_parent_availability_is_coherent_with_complete_variant_matrix() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "ProductGroup",
          "name": "Everyday Tee",
          "url": "https://shop.test/products/everyday-tee",
          "offers": {
            "price": "20",
            "priceCurrency": "USD",
            "availability": "https://schema.org/OutOfStock"
          },
          "hasVariant": [
            {
              "@type": "Product",
              "sku": "TEE-S",
              "size": "S",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock"
              }
            },
            {
              "@type": "Product",
              "sku": "TEE-M",
              "size": "M",
              "offers": {
                "price": "20",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock"
              }
            }
          ]
        }
        </script>
        """,
        "https://shop.test/products/everyday-tee",
    )
    record = result.records[0]
    assert record["availability"] == "in_stock"
    assert record["_lineage"]["availability"]["rule_id"] == "variant_availability_aggregate"
    assert any(finding.rule_id == "PARENT_VARIANT_AVAILABILITY_CONFLICT" for finding in result.findings)


def test_detail_url_falls_back_to_canonical_capture_url() -> None:
    result = _extract(
        "ecommerce_detail",
        """
        <script type="application/ld+json">
        {"@type": "Product", "name": "Trail Shoe", "offers": {"price": "10", "priceCurrency": "USD"}}
        </script>
        """,
        "https://shop.test/products/trail-shoe",
    )
    assert result.records[0]["url"] == "https://shop.test/products/trail-shoe"


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
    assert result.records[0]["image_url"] == "https://shop.test/products/trail-shoe-main.jpg"


def test_missing_requested_field_has_visible_finding() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            '<script type="application/ld+json">{"@type":"Product","name":"Trail Shoe"}</script>',
            "https://shop.test/products/trail-shoe",
            requested_fields=("brand",),
        )
    )
    findings = [finding for finding in result.findings if finding.rule_id == "MISSING_CONTRACT_FIELD"]
    assert any(finding.metadata.get("field") == "brand" for finding in findings)
    assert result.verdict in {"partial", "review"}


def test_missing_requested_variants_requests_one_rendered_capability() -> None:
    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            """
            <main>
              <h1>Everyday Tee</h1>
              <label>Size</label><select><option>S</option><option>M</option></select>
            </main>
            """,
            "https://shop.test/products/everyday-tee",
            requested_fields=("variants",),
        )
    )
    assert not result.records[0].get("variants")
    assert result.retry_request is not None
    assert result.retry_request.reason == "explicit_variants_missing"
    assert result.retry_request.max_attempts == 1
