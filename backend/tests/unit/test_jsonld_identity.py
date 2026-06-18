from __future__ import annotations

import pytest

from bs4 import BeautifulSoup

from app.services.extract.detail.identity.jsonld_identity import (
    jsonld_item_candidate_record,
    jsonld_items,
    prune_duplicate_product_headings,
)


@pytest.mark.unit
def test_jsonld_items_preserve_top_level_identity_record_with_graph() -> None:
    payload = [
        {
            "name": "Widget Prime",
            "sku": "W-100",
            "@graph": [{"@type": "BreadcrumbList"}],
        }
    ]

    items = jsonld_items(payload)

    assert items[0]["name"] == "Widget Prime"
    assert items[1]["@type"] == "BreadcrumbList"


@pytest.mark.unit
def test_jsonld_items_ignore_invalid_graph_container_without_identity() -> None:
    assert jsonld_items({"@graph": "broken"}) == []


@pytest.mark.unit
def test_jsonld_item_candidate_record_keeps_identity_fields() -> None:
    record = jsonld_item_candidate_record(
        {
            "name": "Widget Prime",
            "productId": "PID-123",
            "mpn": "MPN-456",
            "url": "https://example.com/products/widget-prime",
            "gtin13": "0123456789012",
        }
    )

    assert record["product_id"] == "PID-123"
    assert record["part_number"] == "MPN-456"
    assert record["url"] == "https://example.com/products/widget-prime"
    assert record["barcode"] == "0123456789012"


@pytest.mark.unit
def test_prune_duplicate_product_headings_removes_pruned_only_heading() -> None:
    soup = BeautifulSoup("<html><body><h1>Widget Prime</h1></body></html>", "html.parser")

    prune_duplicate_product_headings(
        soup,
        pruned_product_names=["Widget Prime"],
    )

    assert soup.find("h1") is None
