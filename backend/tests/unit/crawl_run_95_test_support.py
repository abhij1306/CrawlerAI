"""Distilled regressions for the crawl-run-95 architectural fixes.

Each test reproduces the minimal shape of a defect the audit
(``docs/plans/crawlerai-crawl-run-95-architectural-fixes.md``) found in real
crawl artifacts, so the fixes cannot silently regress. Fixtures are synthetic —
the audited HTML lives in the gitignored ``backend/artifacts`` tree and is not
committed.
"""

from __future__ import annotations

import json

import pytest

from app.extraction import Surface, extract

from app.extraction.contracts import CommerceDetailProjection, PublicationEntry

from app.extraction.replay import fixture_request_from_inputs

from app.extraction.result_building import projection_field_states

from tests.unit.extraction_pipeline_test_support import _extract

pytestmark = pytest.mark.unit


def _request(*requested_fields: str):
    return fixture_request_from_inputs(
        Surface("ecommerce_detail"),
        "<html><body><main><h1>x</h1></main></body></html>",
        "https://shop.test/p",
        max_records=1,
        requested_fields=requested_fields or ("title", "price", "currency"),
    )


_CONTROL_ROLE_HTML = """
<html><body><main>
<h1>Trail Shoe</h1>
<form class="product-form">
  <select name="size" id="product-size"><option value="">Choose</option>
    <option value="9">9</option><option value="10">10</option><option value="11">11</option></select>
  <select name="color" class="product-option-color"><option>Black</option><option>Red</option></select>
</form>
<select id="product-page-sort-select" aria-label="Sort by">
  <option>Featured</option><option>Price: Low to High</option><option>Newest</option></select>
<select name="country_code" id="CountryList">
  <option>United States</option><option>Canada</option><option>Mexico</option></select>
<select name="qty" id="qty-select"><option>1</option><option>2</option><option>3</option></select>
<select id="reviews-filter" data-testid="reviews-filter-dropdown">
  <option>Most recent</option><option>Highest rated</option></select>
</main></body></html>
"""


def _dom_option_values(result) -> dict[str, set[str]]:
    values: dict[str, set[str]] = {}
    for row in result.evidence:
        if row.fact_type.startswith("option.") and row.collector_id == "dom":
            values.setdefault(row.fact_type, set()).add(row.value)
    return values


def _variant_group_html(*, variants: str, group_offer: str = "") -> str:
    group_offer_block = f'"offers": {group_offer},' if group_offer else ""
    return f"""
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "ProductGroup",
      "name": "Norvan LD Shoe",
      "url": "https://shop.test/products/norvan",
      "sku": "NORVAN",
      {group_offer_block}
      "hasVariant": [{variants}]
    }}
    </script>
    """


def _variant_json(
    sku: str, size: str, *, price: str = "", availability: str = ""
) -> str:
    offer_fields = ['"priceCurrency": "CAD"']
    if price:
        offer_fields.append(f'"price": "{price}"')
    if availability:
        offer_fields.append(f'"availability": "https://schema.org/{availability}"')
    # Every embedded offer carries the *shared* product URL as its only offer
    # identity — the exact shape that used to collapse all variants into one.
    offer_fields.append('"url": "https://shop.test/products/norvan"')
    return (
        '{"@type": "Product", "sku": "%s", "size": "%s", '
        '"offers": {"@type": "Offer", %s}}' % (sku, size, ", ".join(offer_fields))
    )


def _next_data_price_html(*, price: str) -> str:
    """A Next.js ``__NEXT_DATA__`` productSummary whose price carries excess
    minor-unit precision (``128.000000``), corroborated by a JSON-LD offer at
    the true magnitude — the exact shape of audit result 81."""
    next_data = (
        '{"props": {"pageProps": {"dehydratedState": {"queries": [{"state": '
        '{"data": {"productSummary": {"name": "Define Jacket", '
        f'"price": "{price}", "currency": "USD", "sku": "PROD-1", '
        '"url": "https://shop.test/p/define/_/prod1"}}}}}]}}}}'
    )
    return f"""
    <html><head><title>Define Jacket</title>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Define Jacket",
      "sku": "PROD-1",
      "url": "https://shop.test/p/define/_/prod1",
      "offers": {{"@type": "Offer", "price": "128.00", "priceCurrency": "USD",
        "url": "https://shop.test/p/define/_/prod1"}}
    }}
    </script>
    </head>
    <body><main><h1>Define Jacket</h1><span class="price">$128 USD</span></main>
    <script id="__NEXT_DATA__" type="application/json">{next_data}</script>
    </body></html>
    """


def _compacted_description_html(*, prose: str, suffix: str) -> str:
    """A JSON-LD product whose description is valid prose followed by a
    separator-less, run-together feature list — the shape of audit result 1,
    where ``...look.\xa0Soft Rock100% Cotton14ozScreen printed`` used to
    invalidate the entire description via ``description_missing_separator``."""
    description = f"{prose} {suffix}"
    return f"""
    <html><head><title>Soft Rock Crewneck</title>
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "Product",
      "name": "Soft Rock Crewneck",
      "sku": "SKU-1",
      "url": "https://shop.test/products/soft-rock-crewneck",
      "description": {json.dumps(description)},
      "offers": {{"@type": "Offer", "price": "80.00", "priceCurrency": "USD",
        "url": "https://shop.test/products/soft-rock-crewneck"}}
    }}
    </script>
    </head>
    <body><main><h1>Soft Rock Crewneck</h1></main></body></html>
    """


def _square_crop_image_html(*, image_url: str) -> str:
    """A JSON-LD product whose primary image carries a ``_1x1_`` square-crop
    marker and a real ``?width=1440&height=1440`` render — the shape of audit
    result 89, where the ``1x1`` token wrongly rejected a 1440px image."""
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Retro Matte Lipstick",
            "sku": "M25001",
            "url": "https://shop.test/product/retro-matte",
            "image": image_url,
            "offers": {
                "@type": "Offer",
                "price": "24.00",
                "priceCurrency": "USD",
                "url": "https://shop.test/product/retro-matte",
            },
        }
    )
    return f"""
    <html><head><title>Retro Matte Lipstick</title>
    <script type="application/ld+json">{payload}</script>
    </head>
    <body><main><h1>Retro Matte Lipstick</h1></main></body></html>
    """


__all__ = [
    "_CONTROL_ROLE_HTML",
    "CommerceDetailProjection",
    "PublicationEntry",
    "Surface",
    "_compacted_description_html",
    "_dom_option_values",
    "_extract",
    "_next_data_price_html",
    "_request",
    "_square_crop_image_html",
    "_variant_group_html",
    "_variant_json",
    "extract",
    "fixture_request_from_inputs",
    "json",
    "projection_field_states",
    "pytest",
    "pytestmark",
]
