from __future__ import annotations

import pytest

from app.core.records.url_identity import conflicting_product_asset_urls


@pytest.mark.unit
def test_short_numeric_style_code_rejects_sibling_colorway_assets() -> None:
    product_values = (
        "https://dtlr.example/products/air-jordan-5-20102",
        "Air Jordan 5 20102",
        "20102",
    )
    asset_urls = (
        "https://cdn.example/images/air-jordan-5-20102-main.jpg",
        "https://cdn.example/images/air-jordan-5-20102-side.jpg",
        "https://cdn.example/images/air-jordan-5-20101-side.jpg",
    )

    assert conflicting_product_asset_urls(product_values, asset_urls) == frozenset(
        {"https://cdn.example/images/air-jordan-5-20101-side.jpg"}
    )


@pytest.mark.unit
def test_style_code_and_color_suffix_reject_sibling_colorway_assets() -> None:
    product_values = (
        "https://www.dtlr.com/products/jordan-air-jordan-5-hq7978-103",
        "HQ7978-103",
    )
    asset_urls = (
        "https://www.dtlr.com/cdn/shop/files/jordan_HQ7978_20103_M002.jpg",
        "https://www.dtlr.com/cdn/shop/files/jordan_HQ7978_20103_M004.jpg",
        "https://www.dtlr.com/cdn/shop/files/jordan_HQ7978_20101_M003.jpg",
    )

    assert conflicting_product_asset_urls(product_values, asset_urls) == frozenset(
        {"https://www.dtlr.com/cdn/shop/files/jordan_HQ7978_20101_M003.jpg"}
    )


@pytest.mark.unit
def test_short_numeric_asset_codes_are_preserved_without_product_anchor() -> None:
    product_values = ("https://shop.example/products/air-jordan-5", "Air Jordan 5")
    asset_urls = (
        "https://cdn.example/images/air-jordan-5-20102-main.jpg",
        "https://cdn.example/images/air-jordan-5-20101-side.jpg",
    )

    assert not conflicting_product_asset_urls(product_values, asset_urls)
