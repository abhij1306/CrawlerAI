from __future__ import annotations

import pytest

from app.services.adapters.shopify import ShopifyAdapter




@pytest.mark.component
def test_shopify_adapter_preserves_localized_product_path() -> None:
    adapter = ShopifyAdapter()

    record = adapter._build_product_record(
        {
            "title": "Widget",
            "vendor": "Acme",
            "handle": "widget",
            "images": [],
            "tags": [],
            "variants": [
                {"id": 101, "option1": "M", "options": ["M"], "price": 2500},
            ],
            "options": [{"name": "Size"}],
        },
        page_url="https://example.com/en-lb/products/widget?variant=101",
        surface="ecommerce_detail",
    )

    assert record["url"] == "https://example.com/en-lb/products/widget"
    assert record["variants"][0]["url"] == (
        "https://example.com/en-lb/products/widget?variant=101"
    )


@pytest.mark.component
def test_shopify_adapter_recovers_locale_prefix_without_products_marker() -> None:
    adapter = ShopifyAdapter()

    record = adapter._build_product_record(
        {
            "title": "Widget",
            "vendor": "Acme",
            "handle": "widget",
            "images": [],
            "tags": [],
            "variants": [],
        },
        page_url="https://example.com/en-lb?variant=101",
        surface="ecommerce_detail",
    )

    assert record["url"] == "https://example.com/en-lb/products/widget"


@pytest.mark.component
def test_shopify_adapter_strips_blank_and_empty_tags() -> None:
    adapter = ShopifyAdapter()

    record = adapter._build_product_record(
        {
            "title": "Widget",
            "vendor": "Acme",
            "handle": "widget",
            "images": [],
            "tags": " featured, , new  , ",
            "variants": [],
        },
        page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert record["tags"] == ["featured", "new"]


@pytest.mark.component
def test_shopify_adapter_treats_blank_tag_string_as_empty_list() -> None:
    adapter = ShopifyAdapter()

    record = adapter._build_product_record(
        {
            "title": "Widget",
            "vendor": "Acme",
            "handle": "widget",
            "images": [],
            "tags": "   ",
            "variants": [],
        },
        page_url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert record["tags"] == []


@pytest.mark.component
def test_shopify_adapter_reads_shopifyanalytics_meta_with_unquoted_product() -> None:
    adapter = ShopifyAdapter()
    html = """
    <script>
      ShopifyAnalytics.meta = {product: {
        "id": 7,
        "title": "Inline Widget",
        "vendor": "Acme",
        "variants": [{"id": 11, "price": 2500, "available": true}]
      }};
    </script>
    """

    records = adapter._extract_embedded_product(
        html,
        "https://example.com/products/widget",
    )

    assert records[0]["title"] == "Inline Widget"
    assert records[0]["price"] == "25"

