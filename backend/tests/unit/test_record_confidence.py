from __future__ import annotations

import pytest

from app.core.records.confidence import score_record_confidence

pytestmark = pytest.mark.unit


def test_confidence_scores_requested_record_fields_not_source_tier_names() -> None:
    requested_fields = [
        "title",
        "brand",
        "price",
        "currency",
        "availability",
        "image_url",
        "sku",
        "url",
        "variant_count",
    ]
    record = {
        "title": "Soft Rock Crewneck",
        "brand": "Dime",
        "price": "64.00",
        "currency": "EUR",
        "availability": "out_of_stock",
        "image_url": "https://example.com/product.jpg",
        "sku": "DIME2SP2542BLK-S",
        "url": "https://example.com/products/soft-rock-crewneck",
        "variant_count": 4,
        "_field_sources": {field: ["json_ld"] for field in requested_fields},
    }

    confidence = score_record_confidence(
        record,
        surface="ecommerce_detail",
        requested_fields=requested_fields,
    )

    assert confidence["requested_fields_found_best"] == len(requested_fields)
    assert confidence["score"] >= 0.8
    assert confidence["level"] == "high"
    assert "structured" not in confidence["missing_fields"]
    assert "text" not in confidence["missing_fields"]


def test_confidence_drops_when_a_requested_field_is_missing() -> None:
    requested_fields = ["title", "price", "brand"]
    complete = {
        "title": "Example Product",
        "price": "49.00",
        "brand": "Example",
        "_field_sources": {
            "title": ["json_ld"],
            "price": ["json_ld"],
            "brand": ["json_ld"],
        },
    }
    incomplete = {
        **complete,
        "_field_sources": dict(complete["_field_sources"]),
    }
    incomplete.pop("brand")

    complete_score = score_record_confidence(
        complete,
        surface="ecommerce_detail",
        requested_fields=requested_fields,
    )
    incomplete_score = score_record_confidence(
        incomplete,
        surface="ecommerce_detail",
        requested_fields=requested_fields,
    )

    assert incomplete_score["score"] < complete_score["score"]
    assert "brand" in incomplete_score["missing_fields"]
