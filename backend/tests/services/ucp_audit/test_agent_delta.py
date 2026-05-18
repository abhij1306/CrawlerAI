from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.ucp_audit.agent_delta import (
    build_agent_view_delta,
    extract_agent_view,
    extract_human_view,
    extract_main_crawl_human_view,
)


@dataclass(slots=True)
class DummyAcquisition:
    html: str
    final_url: str = "https://example.com/p/1"


@pytest.mark.asyncio
async def test_agent_mode_uses_http_only_and_human_mode_uses_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def fake_acquire_url(url: str, *, mode: str):
        calls.append(mode)
        html = (
            "<script type='application/ld+json'>"
            '{"@type":"Product","name":"Agent Product"}'
            "</script>"
            if mode == "http_only"
            else "<html><h1>Human Product</h1><p>$10 USD</p></html>"
        )
        return DummyAcquisition(html=html)

    def fake_extract_human(html: str, url: str) -> dict[str, object]:
        del html, url
        return {"name": "Human Product", "price": "10"}

    monkeypatch.setattr("app.services.ucp_audit.agent_delta.acquire_url", fake_acquire_url)
    monkeypatch.setattr(
        "app.services.ucp_audit.agent_delta.extract_main_crawl_human_view",
        fake_extract_human,
    )

    result = await build_agent_view_delta("https://example.com/p/1")

    assert calls == ["http_only", "browser_only"]
    assert result.agent_extracted == {
        "name": "Agent Product",
        "additionalProperties": [],
    }
    assert result.human_visible == {"name": "Human Product", "price": "10"}
    assert result.missing_in_agent_view == ["price"]


def test_main_crawl_human_view_includes_variant_axes_from_extraction_pipeline() -> None:
    html = """
    <html><body>
      <script type="application/json" id="__NEXT_DATA__">
      {
        "props": {
          "pageProps": {
            "product": {
              "id": 9002,
              "title": "Men's Wool Runner",
              "handle": "mens-wool-runners-tuke-river",
              "vendor": "Allbirds",
              "options": [{"name": "Size"}],
              "variants": [
                {
                  "id": 17874798215237,
                  "sku": "WR2MTRV090",
                  "option1": "9",
                  "available": false
                },
                {
                  "id": 17874798248005,
                  "sku": "WR2MTRV100",
                  "option1": "10",
                  "available": false
                }
              ]
            }
          }
        }
      }
      </script>
    </body></html>
    """
    acquisition = DummyAcquisition(
        html=html,
        final_url="https://www.allbirds.com/products/mens-wool-runners-tuke-river",
    )

    result = extract_main_crawl_human_view(
        acquisition,
        "https://www.allbirds.com/products/mens-wool-runners-tuke-river",
    )

    assert result["color_options"] == ["Tuke River"]
    assert result["size_options"] == ["9", "10"]
    assert [(variant["size"], variant["color"]) for variant in result["variants"]] == [
        ("9", "Tuke River"),
        ("10", "Tuke River"),
    ]


def test_fidelity_score_uses_field_overlap() -> None:
    from app.services.ucp_audit.agent_delta import compute_fidelity_score

    assert compute_fidelity_score({"name": "A"}, {"name": "A", "price": "10"}) == 0.5
    assert compute_fidelity_score({}, {"name": "A"}) == 0.0
    assert compute_fidelity_score({}, {}) == 1.0


def test_agent_view_extracts_product_group_variants() -> None:
    html = """
    <script type="application/ld+json">
    {
      "@type": "ProductGroup",
      "name": "The Ricky Slip Dress",
      "brand": {"name": "HATCH Collection"},
      "description": "A day-to-night staple.",
      "hasVariant": [{
        "@type": "Product",
        "sku": "270001",
        "gtin": "123456789012",
        "offers": {
          "@type": "Offer",
          "price": "248.00",
          "priceCurrency": "USD",
          "availability": "https://schema.org/InStock"
        }
      }]
    }
    </script>
    """

    result = extract_agent_view(html, "https://example.com/products/ricky")

    assert result["name"] == "The Ricky Slip Dress"
    assert result["price"] == "248.00"
    assert result["currency"] == "USD"
    assert result["availability"] == "InStock"
    assert result["brand"] == "HATCH Collection"
    assert result["sku"] == "270001"
    assert result["gtin"] == "123456789012"
    assert result["additionalProperties"] == []


def test_human_view_extracts_rendered_price_discount_and_options() -> None:
    html = """
    <html><body>
      <h1>The Ricky Slip Dress</h1>
      <p>Sale price</p>
      <p>$248.00</p>
      <p>25% OFF IN CART</p>
      <p>Color:</p><p>Black</p>
      <p>Select Size</p><p>0</p><p>1</p><p>2</p><p>3</p><p>4</p><p>Size Guide</p>
      <button>Add to cart</button>
    </body></html>
    """

    result = extract_human_view(html, "https://example.com/products/ricky")

    assert result["name"] == "The Ricky Slip Dress"
    assert result["price"] == "248.00"
    assert result["sale_messaging"] == "25% OFF IN CART"
    assert result["effective_price"] == "186.00"
    assert result["color_options"] == ["Black"]
    assert result["size_options"] == ["0", "1", "2", "3", "4"]


def test_human_view_scopes_price_and_filters_quantity_noise() -> None:
    html = """
    <html><body>
      <aside><p>You may also like</p><p>$100.00</p></aside>
      <main>
        <section>
          <h1>Belly Oil</h1>
          <p>$68.00</p>
          <p>25% OFF IN CART</p>
          <p>Select Size</p>
          <p>6.7 oz/195mL</p>
          <p>Decrease quantity</p>
          <p>Increase quantity</p>
          <button>Add to cart</button>
        </section>
      </main>
    </body></html>
    """

    result = extract_human_view(html, "https://example.com/products/belly-oil")

    assert result["price"] == "68.00"
    assert result["effective_price"] == "51.00"
    assert result["size_options"] == ["6.7 oz/195mL"]


def test_human_view_stops_color_options_before_addons() -> None:
    html = """
    <html><body>
      <main>
        <section>
          <h1>Homecoming</h1>
          <p>Regular Price $9</p>
          <p>Color:</p>
          <p>Homecoming</p>
          <p>Free Shipping with Orders $25+</p>
          <h4>Don't Forget to Add</h4>
          <p>Magic Off+ Remover</p>
          <p>Price $6.00</p>
        </section>
      </main>
    </body></html>
    """

    result = extract_human_view(html, "https://example.com/products/homecoming")

    assert result["price"] == "9"
    assert result["color_options"] == ["Homecoming"]


def test_human_view_filters_product_prose_from_color_options() -> None:
    html = """
    <html><body>
      <main>
        <section>
          <h1>Men's Wool Runner</h1>
          <p>$49</p>
          <p>Color</p>
          <button>Tuke River</button>
          <p>("limited", edition, cozy)</p>
          <p>Best used for walking</p>
          <p>Select Size</p>
          <button>8</button>
        </section>
      </main>
    </body></html>
    """

    result = extract_human_view(html, "https://example.com/products/mens-wool-runner")

    assert result["color_options"] == ["Tuke River"]
