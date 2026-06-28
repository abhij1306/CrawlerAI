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
                {"variant_id": "image-width-1206", "width": "1206"},
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


def test_ecommerce_public_variants_keep_size_only_rows() -> None:
    record, rejected = public_record_data_for_surface(
        {
            "title": "Classic Tee",
            "url": "https://shop.test/products/classic-tee",
            "variants": [
                {"size": "S"},
                {"size": "M"},
                {"size": "L"},
            ],
        },
        surface="ecommerce_detail",
        page_url="https://shop.test/products/classic-tee",
    )

    assert rejected == {}
    assert record["variants"] == [
        {"size": "S"},
        {"size": "M"},
        {"size": "L"},
    ]
    assert record["variant_count"] == 3


def test_ecommerce_public_variants_keep_color_only_rows() -> None:
    record, rejected = public_record_data_for_surface(
        {
            "title": "Plain Mug",
            "url": "https://shop.test/products/plain-mug",
            "variants": [
                {"color": "Red"},
                {"color": "Blue"},
            ],
        },
        surface="ecommerce_detail",
        page_url="https://shop.test/products/plain-mug",
    )

    assert rejected == {}
    assert record["variants"] == [
        {"color": "Red"},
        {"color": "Blue"},
    ]
    assert record["variant_count"] == 2


def test_ecommerce_public_variants_drop_single_non_canonical_axis_rows() -> None:
    record, rejected = public_record_data_for_surface(
        {
            "title": "Display Item",
            "url": "https://shop.test/products/display",
            "variants": [
                {"material": "Cotton"},
                {"type": "Premium"},
            ],
        },
        surface="ecommerce_detail",
        page_url="https://shop.test/products/display",
    )

    assert rejected == {"variants": "empty_after_coercion"}
    assert "variants" not in record
    assert "variant_count" not in record


def test_ecommerce_detail_url_drops_revision_and_variant_query_keys() -> None:
    record, rejected = public_record_data_for_surface(
        {
            "title": "Rustic Cotton T-Shirt",
            "url": (
                "https://shop.test/products/rustic-cotton-t-shirt.html"
                "?v1=527078510&variant=123&pid=P04424306"
            ),
        },
        surface="ecommerce_detail",
        page_url="https://shop.test/products/rustic-cotton-t-shirt.html",
    )

    assert rejected == {}
    assert record["url"] == (
        "https://shop.test/products/rustic-cotton-t-shirt.html?pid=P04424306"
    )
