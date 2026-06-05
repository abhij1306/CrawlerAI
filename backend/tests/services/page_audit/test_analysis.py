from __future__ import annotations

import pytest

from app.services.page_audit.analysis import analyze_page

pytestmark = pytest.mark.unit


def _checks_by_id(rows: list[dict[str, object]]) -> dict[str, dict[str, object]]:
    return {str(row["id"]): row for row in rows}


def test_analyze_page_reports_source_metadata_and_structured_data() -> None:
    source_html = """
    <html lang="en">
      <head>
        <title>Useful product page title that fits the recommended length</title>
        <meta name="description" content="A complete description that gives search engines and visitors enough useful page context while staying within the recommended metadata length for this technical audit.">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <link rel="canonical" href="https://example.com/product">
        <meta property="og:title" content="Useful product">
        <meta property="og:description" content="Useful product description">
        <meta property="og:image" content="https://cdn.example.com/product.jpg">
        <meta property="og:url" content="https://example.com/product">
        <meta name="twitter:card" content="summary_large_image">
        <meta name="twitter:image" content="https://cdn.example.com/product.jpg">
        <script type="application/ld+json">
          {"@context":"https://schema.org","@type":"Product","name":"Useful product"}
        </script>
      </head>
      <body><h1>Useful product</h1></body>
    </html>
    """

    report = analyze_page(
        url="https://example.com/product",
        source_html=source_html,
        dom_html=source_html,
    )

    checks = _checks_by_id(report["source_checks"])
    assert checks["title_exists"]["passed"] is True
    assert checks["canonical_matches_url"]["passed"] is True
    assert checks["jsonld_parseable"]["passed"] is True
    assert checks["schema_product_present"]["passed"] is True
    assert report["scores"]["seo"] > 80


def test_analyze_page_reports_dom_performance_accessibility_and_form_failures() -> None:
    source_html = "<html><head><title>Short</title></head><body><h1>Page</h1></body></html>"
    dom_html = """
    <html>
      <head>
        <title>Short</title>
        <script src="/blocking.js"></script>
      </head>
      <body>
        <section class="hero"><img src="/hero.jpg" loading="lazy"></section>
        <img src="/missing-alt.jpg">
        <form><input type="email"></form>
        <a href="#missing">Jump</a>
        <a href="https://outside.example/path" target="_blank">Outside</a>
      </body>
    </html>
    """

    report = analyze_page(
        url="https://example.com/page",
        source_html=source_html,
        dom_html=dom_html,
    )

    checks = _checks_by_id(report["dom_checks"])
    assert checks["lcp_candidate_lazy_loaded"]["passed"] is False
    assert checks["images_have_alt"]["passed"] is False
    assert checks["render_blocking_scripts"]["passed"] is False
    assert checks["forms_have_action"]["passed"] is False
    assert checks["inputs_have_labels"]["passed"] is False
    assert checks["anchor_targets_exist"]["passed"] is False
    assert checks["external_blank_links_secure"]["passed"] is False
    assert report["critical_failures"]


def test_analyze_page_reports_source_dom_differences() -> None:
    source_html = """
    <html><head><title>Page</title></head>
    <body><main><p>Server text</p></main></body></html>
    """
    dom_html = """
    <html><head><title>Page</title>
      <script type="application/ld+json">{"@type":"Article"}</script>
    </head><body><main>
      <h1>Client heading</h1>
      <p>Server text</p>
      <p>Client rendered paragraph with useful content.</p>
      <a href="/client-route">Client route</a>
    </main></body></html>
    """

    report = analyze_page(
        url="https://example.com/page",
        source_html=source_html,
        dom_html=dom_html,
    )

    checks = _checks_by_id(report["diff_checks"])
    assert checks["content_present_in_source"]["passed"] is False
    assert checks["links_present_in_source"]["passed"] is False
    assert checks["h1_present_in_source"]["passed"] is False
    assert checks["schema_present_in_source"]["passed"] is False
    assert report["render_summary"]["dom_only_link_count"] == 1


def test_analyze_page_only_adds_ecommerce_checks_when_product_signals_exist() -> None:
    generic = analyze_page(
        url="https://example.com/about",
        source_html="<html><body><h1>About</h1></body></html>",
        dom_html="<html><body><h1>About</h1></body></html>",
    )
    product = analyze_page(
        url="https://example.com/product",
        source_html=(
            "<html><body><h1>Product</h1><span itemprop='price'>10</span>"
            "<button class='add-to-cart'>Add to cart</button></body></html>"
        ),
        dom_html=(
            "<html><body><h1>Product</h1><span itemprop='price'>10</span>"
            "<button class='add-to-cart'>Add to cart</button></body></html>"
        ),
    )

    assert generic["scores"]["ecommerce_readiness"] is None
    product_checks = _checks_by_id(product["dom_checks"])
    assert product_checks["ecommerce_price_present"]["passed"] is True
    assert product_checks["ecommerce_add_to_cart_present"]["passed"] is True
    assert product["scores"]["ecommerce_readiness"] is not None
