from __future__ import annotations

from app.services.ucp_audit.product_schema import score_product_schema


def test_product_jsonld_found_and_scored() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Aero Tee",
      "sku": "SKU-1",
      "brand": {"name": "Cube"},
      "gtin13": "1234567890123",
      "description": "A tee",
      "image": "https://example.com/image.jpg",
      "category": "Apparel > Shirts > Tees",
      "additionalProperty": [{"name": "color", "value": "Blue"}],
      "offers": {
        "@type": "Offer",
        "price": "10.00",
        "availability": "https://schema.org/InStock",
        "priceCurrency": "USD"
      }
    }
    </script></head></html>
    """

    result = score_product_schema("https://example.com/p/1", html)

    assert result.product_jsonld_found is True
    assert result.missing_required == []
    assert result.missing_recommended == []
    assert result.raw_product_type == "Apparel > Shirts > Tees"
    assert result.raw_additional_properties == [{"name": "color", "value": "Blue"}]
    assert result.raw_offers
    assert result.completeness_score == 100


def test_missing_required_fields_are_reported() -> None:
    html = """
    <html><head><script type="application/ld+json">
    {"@type": "Product", "name": "Aero Tee"}
    </script></head></html>
    """

    result = score_product_schema("https://example.com/p/1", html)

    assert result.product_jsonld_found is True
    assert result.missing_required == [
        "offers.price",
        "offers.availability",
        "offers.priceCurrency",
    ]
    assert result.completeness_score < 100


def test_multiple_jsonld_blocks_selects_product() -> None:
    html = """
    <html><head>
    <script type="application/ld+json">{"@type": "Organization", "name": "Store"}</script>
    <script type="application/ld+json">
    {"@type": "Product", "name": "Aero Tee", "offers": {"price": "10", "availability": "InStock", "priceCurrency": "USD"}}
    </script>
    </head></html>
    """

    result = score_product_schema("https://example.com/p/1", html)

    assert result.product_jsonld_found is True
    assert result.required_fields_present == [
        "name",
        "offers.price",
        "offers.availability",
        "offers.priceCurrency",
    ]
