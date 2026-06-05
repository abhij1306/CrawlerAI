from __future__ import annotations

import pytest

from app.services.surface_resolver import resolve_public_surface, resolve_surface

pytestmark = pytest.mark.unit


def test_resolve_auto_codeforces_homepage_to_content_detail() -> None:
    result = resolve_surface("auto", url="https://codeforces.com/", crawl_module="category")

    assert result.surface == "content_detail"
    assert result.confidence == pytest.approx(0.4)
    assert "fallback_content_surface" in result.evidence


def test_resolve_auto_codeforces_blog_entry_to_article_detail() -> None:
    result = resolve_surface(
        "auto",
        url="https://codeforces.com/blog/entry/153802",
        crawl_module="pdp",
    )

    assert result.surface == "article_detail"


def test_resolve_auto_forum_thread_url_to_forum_detail() -> None:
    result = resolve_surface(
        "auto",
        url="https://community.example.com/thread/123",
        crawl_module="pdp",
    )

    assert result.surface == "forum_detail"


def test_resolve_auto_ecommerce_product_url_to_detail() -> None:
    result = resolve_surface(
        "auto",
        url="https://shop.example.com/products/widget",
        crawl_module="pdp",
    )

    assert result.surface == "ecommerce_detail"


def test_resolve_auto_generic_ecommerce_category_segment_to_listing() -> None:
    result = resolve_surface(
        "auto",
        url="https://www.balenciaga.com/en-en/gifts/gifts-for-home",
        crawl_module="category",
    )

    assert result.surface == "ecommerce_listing"
    assert "ecommerce_listing_segment_signal" in result.evidence


def test_resolve_auto_sku_html_product_slug_to_detail() -> None:
    result = resolve_surface(
        "auto",
        url="https://www.balenciaga.com/en-en/beijing-coffee-cup-black-666275T01011004.html",
        crawl_module="pdp",
    )

    assert result.surface == "ecommerce_detail"
    assert "ecommerce_detail_sku_html_signal" in result.evidence


def test_resolve_auto_multi_token_html_product_slug_to_detail() -> None:
    result = resolve_surface(
        "auto",
        url="https://shop.example.com/en-us/black-leather-card-holder.html",
        crawl_module="pdp",
    )

    assert result.surface == "ecommerce_detail"
    assert "ecommerce_detail_html_slug_signal" in result.evidence


def test_resolve_auto_listing_path_wins_over_html_product_shape() -> None:
    result = resolve_surface(
        "auto",
        url="https://shop.example.com/category/sale-product-black-12345.html",
        crawl_module="category",
    )

    assert result.surface == "ecommerce_listing"
    assert "ecommerce_listing_url_signal" in result.evidence


def test_resolve_explicit_surface_bypasses_auto_detection() -> None:
    result = resolve_surface(
        "job_detail",
        url="https://codeforces.com/blog/entry/153802",
        crawl_module="pdp",
    )

    assert result.surface == "job_detail"
    assert result.confidence == pytest.approx(1.0)
    assert result.evidence == ["explicit_surface"]


def test_resolve_public_auto_returns_internal_surface() -> None:
    result = resolve_public_surface("auto", url="https://codeforces.com/")

    assert result is not None
    assert result.surface == "content_detail"


def test_resolve_auto_does_not_treat_generic_tables_as_listing() -> None:
    html = """
    <html><body>
      <h1>Reference Page</h1>
      <table>
        <tr><th>Name</th><th>Value</th></tr>
        <tr><td>Alpha</td><td>1</td></tr>
        <tr><td>Beta</td><td>2</td></tr>
        <tr><td>Gamma</td><td>3</td></tr>
      </table>
    </body></html>
    """

    result = resolve_surface(
        "auto",
        url="https://example.com/reference",
        html=html,
        crawl_module="category",
    )

    assert result.surface == "content_detail"


def test_resolve_auto_does_not_treat_article_cards_as_listing_by_default() -> None:
    html = """
    <html><body>
      <article><h2>First update</h2></article>
      <article><h2>Second update</h2></article>
      <article><h2>Third update</h2></article>
    </body></html>
    """

    result = resolve_surface(
        "auto",
        url="https://example.com/",
        html=html,
        crawl_module="category",
    )

    assert result.surface == "content_detail"
