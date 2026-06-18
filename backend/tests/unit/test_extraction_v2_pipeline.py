from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.extraction_v2 import extract_ecommerce_detail_v2
from app.services.extraction_v2.contracts import Evidence
from app.services.pipeline.extract_records import extract_records

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


def test_v2_materializes_once_with_lineage_and_quality() -> None:
    record, replay = extract_ecommerce_detail_v2(
        HTML,
        "https://shop.test/products/trail-shoe",
    )
    assert record is not None
    assert record["title"] == "Trail Shoe"
    assert record["price"] == "129.00"
    assert record["currency"] == "USD"
    assert record["_quality_verdict"] == "success"
    assert record["_lineage"]["price"]["derived_fact_id"]
    assert replay.normalized_evidence
    assert replay.resolution.decisions


def test_evidence_is_immutable() -> None:
    _, replay = extract_ecommerce_detail_v2(HTML, "https://shop.test/products/trail-shoe")
    item = replay.normalized_evidence[0]
    try:
        item.value = "changed"  # type: ignore[misc]
    except (ValidationError, TypeError):
        pass
    assert isinstance(item, Evidence)
    assert item.value != "changed"


def test_offer_price_without_currency_is_not_published() -> None:
    html = HTML.replace('"priceCurrency": "usd",', "")
    record, replay = extract_ecommerce_detail_v2(html, "https://shop.test/products/trail-shoe")
    assert record is None
    assert "PRICE_WITHOUT_CURRENCY" in {finding.rule_id for finding in replay.findings}


def test_order_and_duplicate_independence() -> None:
    duplicate = HTML.replace("</head>", HTML.split("<script", 1)[1].join(["<script", "</head>"]))
    first, _ = extract_ecommerce_detail_v2(HTML, "https://shop.test/products/trail-shoe")
    second, _ = extract_ecommerce_detail_v2(duplicate, "https://shop.test/products/trail-shoe")
    assert first == second


def test_ecommerce_detail_cutover_uses_v2_replay_artifact() -> None:
    artifacts: dict[str, object] = {}
    rows = extract_records(
        HTML,
        "https://shop.test/products/trail-shoe",
        "ecommerce_detail",
        max_records=1,
        artifacts=artifacts,
    )
    assert rows and rows[0]["title"] == "Trail Shoe"
    assert "extraction_v2_replay" in artifacts


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
    record, replay = extract_ecommerce_detail_v2(
        "<html><body><h1>Fallback</h1></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    assert record is not None
    assert record["price"] == "29.90"
    assert replay.normalized_evidence


def test_js_state_explicit_variant_rows_are_materialized() -> None:
    artifacts = {
        "js_state_objects": {
            "variants": [
                {"id": "v1", "sku": "SKU-BLK-S", "size": "S", "color": "Black"},
                {"id": "v2", "sku": "SKU-WHT-M", "size": "M", "color": "White"},
            ]
        }
    }
    record, _ = extract_ecommerce_detail_v2(
        "<html><body><h1>Rustic Cotton T-Shirt</h1></body></html>",
        "https://www.zara.com/us/en/rustic-cotton-t-shirt-p04424306.html",
        artifacts=artifacts,
    )
    assert record is not None
    assert record["variants"] == [
        {"selected": False, "sku": "SKU-BLK-S", "color": "Black", "size": "S"},
        {"selected": False, "sku": "SKU-WHT-M", "color": "White", "size": "M"},
    ]
