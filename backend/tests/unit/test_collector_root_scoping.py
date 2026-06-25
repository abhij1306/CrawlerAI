from __future__ import annotations

import pytest

from app.extraction.collectors.js_state import path_is_within_selected_root
from app.extraction.collectors.js_state import selected_product_root_paths

pytestmark = pytest.mark.unit


def test_exact_url_selects_matching_root() -> None:
    objects = (
        (
            "/products/0",
            {
                "type": "Product",
                "url": "https://shop.test/products/primary?variant=1",
            },
        ),
        ("/products/0/variants/0", {"sku": "PRIMARY-1"}),
        ("/products/1", {"url": "https://shop.test/products/related"}),
        ("/products/1/variants/0", {"sku": "RELATED-1"}),
    )
    selected = selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    )
    assert selected == ("/products/0",)
    assert path_is_within_selected_root("/products/0/variants/0", selected)
    assert not path_is_within_selected_root("/products/1/variants/0", selected)


def test_missing_exact_root_keeps_fallback_behavior() -> None:
    objects = (("/product", {"title": "No URL"}),)
    selected = selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    )
    assert selected == ()
    assert path_is_within_selected_root("/product", selected)


def test_metadata_url_match_is_not_selected_as_product_root() -> None:
    objects = (
        (
            "/seo",
            {"canonicalUrl": "https://shop.test/products/primary"},
        ),
        (
            "/product",
            {"type": "Product", "title": "Primary"},
        ),
    )

    assert selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    ) == ()


def test_nested_variant_url_promotes_to_product_ancestor() -> None:
    objects = (
        (
            "/product",
            {"type": "Product", "title": "Primary", "sku": "BASE"},
        ),
        (
            "/product/hasVariant/0",
            {
                "type": "ProductModel",
                "url": "https://shop.test/products/primary?variant=1",
                "sku": "SKU-1",
            },
        ),
    )

    assert selected_product_root_paths(
        objects, "https://shop.test/products/primary"
    ) == ("/product",)
