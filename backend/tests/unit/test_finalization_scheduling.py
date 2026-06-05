from __future__ import annotations

import pytest

import app.services.pipeline.extract_records as extract_records_module
from app.services.network_payload_mapper import map_network_payloads_to_fields


@pytest.mark.unit
def test_detail_postprocess_skips_redundant_finalize_for_finalized_boundary(
    monkeypatch,
) -> None:
    record = extract_records_module.finalize_record(
        {
            "title": "Widget",
            "url": "https://example.com/products/widget",
            "price": "$12.00",
        },
        surface="ecommerce_detail",
    )

    def _unexpected_finalize(*args, **kwargs):
        raise AssertionError("detail boundary record was finalized twice")

    monkeypatch.setattr(extract_records_module, "finalize_record", _unexpected_finalize)

    rows = extract_records_module._postprocess_detail_records(
        [dict(record)],
        html="<html><body><h1>Widget</h1></body></html>",
        page_url="https://example.com/products/widget",
        requested_page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
        repair_quality=False,
        finalize_rows=False,
    )

    assert rows == [record]


@pytest.mark.unit
def test_raw_detail_postprocess_keeps_public_boundary_finalization(monkeypatch) -> None:
    original_finalize = extract_records_module.finalize_record
    calls = 0

    def _counting_finalize(record, **kwargs):
        nonlocal calls
        calls += 1
        return original_finalize(record, **kwargs)

    monkeypatch.setattr(extract_records_module, "finalize_record", _counting_finalize)

    rows = extract_records_module._postprocess_detail_records(
        [{"title": " Widget ", "url": "https://example.com/products/widget"}],
        html="<html><body><h1>Widget</h1></body></html>",
        page_url="https://example.com/products/widget",
        requested_page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
        repair_quality=False,
    )

    assert calls == 1
    assert rows == [
        original_finalize(
            {"title": " Widget ", "url": "https://example.com/products/widget"},
            surface="ecommerce_detail",
        )
    ]


@pytest.mark.unit
def test_listing_price_finalizer_does_not_finalize_whole_record(monkeypatch) -> None:
    def _unexpected_finalize(*args, **kwargs):
        raise AssertionError("listing candidate was finalized as whole record")

    monkeypatch.setattr(extract_records_module, "finalize_record", _unexpected_finalize)

    rows = extract_records_module._finalize_listing_rows(
        [{"title": "Widget", "url": "https://example.com/p/widget", "price": "$12"}]
    )

    assert rows[0]["title"] == "Widget"
    assert rows[0]["url"] == "https://example.com/p/widget"


@pytest.mark.unit
def test_network_payload_mapping_keeps_detail_output_shape() -> None:
    rows = map_network_payloads_to_fields(
        [
            {
                "body": {
                    "product": {
                        "name": "Widget",
                        "sku": "WID-123",
                        "offers": {"price": "12.00"},
                    }
                }
            }
        ],
        surface="ecommerce_detail",
        page_url="https://example.com/products/widget-wid-123",
    )

    assert rows
    assert rows[0]["title"] == "Widget"
    assert rows[0]["sku"] == "WID-123"
