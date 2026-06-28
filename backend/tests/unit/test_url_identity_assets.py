from __future__ import annotations

import pytest

from app.core.records.url_identity import (
    conflicting_product_asset_urls,
    detail_urls_conflict,
)


@pytest.mark.unit
def test_detail_urls_conflict_when_embedded_product_codes_change() -> None:
    requested = "https://shop.example/women/valentino-loco-small-bag-black-p00956616"
    redirected = "https://shop.example/women/valentino-loco-small-bag-beige-p01155657"

    assert detail_urls_conflict(requested, redirected) is True


@pytest.mark.unit
def test_shared_ancestor_code_does_not_mask_changed_terminal_product_code() -> None:
    requested = "https://shop.example/season/LOOKBOOK2026/products/bag-P00956616"
    redirected = "https://shop.example/season/LOOKBOOK2026/products/shoe-P01155657"

    assert detail_urls_conflict(requested, redirected) is True


@pytest.mark.unit
def test_variant_urls_allow_distinct_codes_when_product_identity_matches() -> None:
    parent = "https://shop.example/products/trail-runner-shoe-blue-STYLE0001"
    variant = "https://shop.example/products/trail-runner-shoe-red-STYLE0002"

    assert detail_urls_conflict(parent, variant, strict_terminal_code=False) is False


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


@pytest.mark.unit
def test_color_params_do_not_reject_all_assets_without_a_matching_peer() -> None:
    product_values = ("https://shop.example/products/widget?color=77142",)
    asset_urls = (
        "https://cdn.example/images/widget-main.jpg?color=1472",
        "https://cdn.example/images/widget-side.jpg?color=318988",
    )

    assert not conflicting_product_asset_urls(product_values, asset_urls)


@pytest.mark.unit
def test_color_params_reject_only_disjoint_assets_when_one_peer_matches() -> None:
    product_values = ("https://shop.example/products/widget?color=77142",)
    asset_urls = (
        "https://cdn.example/images/widget-main.jpg?color=77142",
        "https://cdn.example/images/widget-side.jpg?color=1472",
    )

    assert conflicting_product_asset_urls(product_values, asset_urls) == frozenset(
        {"https://cdn.example/images/widget-side.jpg?color=1472"}
    )


@pytest.mark.unit
def test_nested_color_path_ids_do_not_hide_a_matching_asset_peer() -> None:
    product_values = ("https://shop.example/products/widget/color/456",)
    asset_urls = (
        "https://cdn.example/images/colors/123/colors/456/widget.jpg",
        "https://cdn.example/images/color/999/widget.jpg",
    )

    assert conflicting_product_asset_urls(product_values, asset_urls) == frozenset(
        {"https://cdn.example/images/color/999/widget.jpg"}
    )
