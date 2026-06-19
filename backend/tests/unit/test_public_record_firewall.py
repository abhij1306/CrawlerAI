from __future__ import annotations

import pytest

from app.core.records.public_record_firewall import public_record_data_for_surface

pytestmark = pytest.mark.unit


def test_ecommerce_public_variants_drop_width_only_artifacts_and_selected() -> None:
    record, rejected = public_record_data_for_surface(
        {
            "title": "Lip Balm",
            "url": "https://shop.test/products/lip-balm",
            "variants": [
                {"width": "1206", "selected": False},
                {
                    "sku": "2775096",
                    "color": "Bissap Glaze",
                    "price": "24.00",
                    "currency": "USD",
                    "availability": "in_stock",
                    "selected": False,
                },
            ],
        },
        surface="ecommerce_detail",
        page_url="https://shop.test/products/lip-balm",
    )

    assert rejected == {}
    assert record["variants"] == [
        {
            "sku": "2775096",
            "color": "Bissap Glaze",
            "price": "24.00",
            "currency": "USD",
            "availability": "in_stock",
        }
    ]
    assert record["variant_count"] == 1
