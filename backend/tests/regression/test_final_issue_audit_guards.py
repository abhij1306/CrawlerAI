from __future__ import annotations

import pytest
from bs4 import BeautifulSoup

from app.services.extract.detail.assembly.final_cleanup import (
    repair_ecommerce_detail_record_quality,
)
from app.services.extract.detail.assembly.record_sanitization import (
    sanitize_detail_identity_scalars,
)
from app.services.extract.detail.validation import attach_detail_validation_findings
from app.services.extract.variant_normalization import normalize_variant_record
from app.services.js_state.state_normalizer import map_js_state_to_fields
from app.services.pipeline.persistence import build_extraction_decision_payload
from app.services.pipeline.extract_records import extract_records
from app.services.publish.verdict import VERDICT_PARTIAL, compute_verdict

pytestmark = pytest.mark.unit


def test_title_prefix_does_not_guess_product_model_as_brand() -> None:
    record = {
        "title": "Stan Smith Shoes",
        "url": "https://example.com/products/stan-smith-shoes",
    }

    sanitize_detail_identity_scalars(
        record,
        identity_url="https://example.com/products/stan-smith-shoes",
    )

    assert "brand" not in record


def test_shared_parent_offer_stays_explicit_on_public_variants() -> None:
    record = {
        "price": "100.00",
        "currency": "USD",
        "variants": [{"sku": "SKU-8", "size": "8"}, {"sku": "SKU-9", "size": "9"}],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"sku": "SKU-8", "size": "8", "price": "100.00", "currency": "USD"},
        {"sku": "SKU-9", "size": "9", "price": "100.00", "currency": "USD"},
    ]


def test_cross_product_variant_urls_do_not_inherit_flat_parent_offer() -> None:
    record = {
        "url": "https://market.example/products/base-shoe",
        "price": "100.00",
        "currency": "USD",
        "variants": [
            {"size": "8", "url": "https://market.example/products/base-shoe-blue"},
            {"size": "9", "url": "https://market.example/products/base-shoe-red"},
        ],
    }

    normalize_variant_record(record)
    attach_detail_validation_findings(record)

    assert record["variants"] == [
        {"size": "8", "url": "https://market.example/products/base-shoe-blue"},
        {"size": "9", "url": "https://market.example/products/base-shoe-red"},
    ]
    assert any(
        finding.get("rule_id") == "INCOMPLETE_SELLABLE_VARIANT_OFFER"
        for finding in record["_validation_findings"]
    )


def test_width_and_size_axes_survive_variant_normalization() -> None:
    record = {
        "title": "Running Shoe",
        "variants": [
            {"sku": "R-REG-8", "option_values": {"Width": "Regular", "Size": "8"}},
            {"sku": "R-WIDE-8", "option_values": {"Width": "Wide", "Size": "8"}},
        ],
    }

    normalize_variant_record(record)

    assert record["variants"] == [
        {"size": "8", "sku": "R-REG-8", "width": "Regular"},
        {"size": "8", "sku": "R-WIDE-8", "width": "Wide"},
    ]


def test_high_detail_findings_degrade_success_verdict() -> None:
    record = {
        "title": "Blocked Shell",
        "_validation_findings": [
            {"rule_id": "INSUFFICIENT_DETAIL_EVIDENCE", "severity": "high"}
        ],
    }

    verdict = compute_verdict(
        is_listing=False,
        blocked=False,
        record_count=1,
        records=[record],
    )

    assert verdict == VERDICT_PARTIAL


def test_incomplete_variant_offer_degrades_success_verdict() -> None:
    record = {
        "title": "Sneaker",
        "price": "120.00",
        "currency": "USD",
        "variants": [{"size": "8"}, {"size": "9"}],
    }
    attach_detail_validation_findings(record)

    verdict = compute_verdict(
        is_listing=False,
        blocked=False,
        record_count=1,
        records=[record],
    )

    assert verdict == VERDICT_PARTIAL


def test_quantity_select_is_not_mapped_to_size_variants() -> None:
    rows = extract_records(
        """
        <html><body><main>
          <h1>Structured Commuter Bag</h1>
          <span class="price">$63.60</span>
          <select><option>1</option><option>2</option><option>3</option></select>
        </main></body></html>
        """,
        "https://example.com/products/commuter-bag",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "price", "variants"],
    )

    assert "variants" not in rows[0]


def test_jsonld_currency_beats_url_currency_hint() -> None:
    rows = extract_records(
        """
        <html><head>
          <script type="application/ld+json">
          {"@type":"Product","name":"Speedcat Sneakers",
           "offers":{"price":"9999","priceCurrency":"INR"}}
          </script>
        </head><body><main><h1>Speedcat Sneakers</h1></main></body></html>
        """,
        "https://in.puma.com/in/en/pd/speedcat-sneakers/406329",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "price", "currency"],
    )

    assert rows[0]["currency"] == "INR"


def test_image_fetch_proxy_url_keeps_suffix() -> None:
    url = (
        "https://images.onepeloton.com/peloton-cycle/image/fetch/"
        "dpr_1.0,f_auto,q_auto:good,w_800/https://cdn.example.com/tread.jpg"
    )
    rows = extract_records(
        f"""
        <html><body><main>
          <h1>Peloton Tread</h1>
          <img src="{url}">
          <span class="price">$2995</span>
        </main></body></html>
        """,
        "https://www.onepeloton.com/shop/tread",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "image_url"],
    )

    assert rows[0]["image_url"] == url


def test_root_color_backfills_size_variants_when_all_rows_lack_color() -> None:
    record = {
        "color": "White/White",
        "price": "115.00",
        "currency": "USD",
        "image_url": "https://example.com/white.jpg",
        "variants": [
            {"size": "M 6", "barcode": "001"},
            {"size": "M 7", "barcode": "002"},
        ],
    }

    normalize_variant_record(record)

    assert [variant["color"] for variant in record["variants"]] == [
        "White/White",
        "White/White",
    ]


def test_title_color_repair_survives_variant_normalization() -> None:
    record = {
        "title": "SATISFY TheROCKER - Jet Black",
        "price": "28300.00",
        "currency": "INR",
        "variants": [
            {"color": "Jet Black", "size": "8", "sku": "SKU-8"},
            {"color": "Brown", "size": "9", "sku": "SKU-9"},
        ],
    }
    html = "<html><body><main><h1>SATISFY TheROCKER - Jet Black</h1></main></body></html>"

    repair_ecommerce_detail_record_quality(
        record,
        html=html,
        page_url="https://example.com/products/the-rocker",
        soup=BeautifulSoup(html, "html.parser"),
    )

    assert record["color"] == "Jet Black"


def test_flat_parent_price_removed_from_large_multi_axis_variant_matrix() -> None:
    record = {
        "price": "69.97",
        "currency": "USD",
        "variants": [
            {
                "color": color,
                "size": size,
                "sku": f"{color}-{size}",
                "price": "69.97",
                "currency": "USD",
            }
            for color in ("Black", "White", "Blue")
            for size in ("7", "8", "9", "10")
        ],
    }

    normalize_variant_record(record)

    assert all("price" not in variant for variant in record["variants"])
    assert any(
        finding.get("rule_id") == "FLAT_PARENT_VARIANT_OFFER_REMOVED"
        for finding in record["_validation_findings"]
    )


def test_next_dehydrated_variation_list_maps_to_size_variants() -> None:
    record = map_js_state_to_fields(
        {
            "__NEXT_DATA__": {
                "props": {
                    "pageProps": {
                        "dehydratedState": {
                            "queries": [
                                {
                                    "state": {
                                        "data": {
                                            "id": "M20324",
                                            "product_type": "inline",
                                            "name": "Stan Smith Shoes",
                                            "pricing_information": {
                                                "currentPrice": 100,
                                                "currency": "USD",
                                            },
                                            "variation_list": [
                                                {
                                                    "sku": "M20324_530",
                                                    "size": "4",
                                                    "gtin": "4054067760212",
                                                },
                                                {
                                                    "sku": "M20324_540",
                                                    "size": "4.5",
                                                    "gtin": "4054067760229",
                                                },
                                            ],
                                        }
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        },
        surface="ecommerce_detail",
        page_url="https://www.adidas.com/us/stan-smith-shoes/M20324.html",
    )

    assert record["variant_count"] == 2
    assert record["variants"][0] == {
        "sku": "M20324_530",
        "barcode": "4054067760212",
        "option_values": {"size": "4"},
        "size": "4",
    }


def test_jsonld_product_group_description_backfills_missing_description() -> None:
    rows = extract_records(
        """
        <html><head>
          <script type="application/ld+json">
          {"@type":"ProductGroup","name":"Apex T Shirt",
           "description":"Lightweight training shirt with sweat-wicking fabric.",
           "hasVariant":[{"@type":"Product","name":"Apex T Shirt Black"}]}
          </script>
        </head><body><main><h1>Apex T Shirt Black</h1></main></body></html>
        """,
        "https://example.com/products/apex-t-shirt-black",
        "ecommerce_detail",
        max_records=1,
        requested_fields=["title", "description"],
    )

    assert rows[0]["description"] == (
        "Lightweight training shirt with sweat-wicking fabric."
    )


def test_extraction_decision_payload_keeps_evidence_and_findings() -> None:
    payload = build_extraction_decision_payload(
        verdict=VERDICT_PARTIAL,
        persisted_count=1,
        records=[
            {
                "title": "Blocked Shell",
                "_evidence_graph": {"title": [{"source": "dom"}]},
                "_validation_findings": [
                    {
                        "rule_id": "INSUFFICIENT_DETAIL_EVIDENCE",
                        "severity": "high",
                    }
                ],
            }
        ],
    )

    assert payload["schema_version"] == "extraction_decision.v1"
    assert payload["verdict"] == VERDICT_PARTIAL
    assert payload["records"][0]["public_fields"] == {"title": "Blocked Shell"}
    assert payload["records"][0]["evidence_graph"] == {
        "title": [{"source": "dom"}]
    }
    assert payload["records"][0]["validation_findings"][0]["severity"] == "high"
