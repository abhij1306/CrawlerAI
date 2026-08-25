from __future__ import annotations

import json

import pytest

from app.core.records.title_normalization import normalize_detail_marketplace_title
from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs

pytestmark = pytest.mark.unit


def test_amazon_search_title_markup_is_removed() -> None:
    polluted = (
        "Amazon.com : Poppi Prebiotic Soda, Sparkling Water & Fruit Juice, "
        "Punch Pop, 12 Oz, 12 Pack : Grocery & Gourmet Food"
    )
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": polluted,
            "url": "https://www.amazon.com/example/dp/B0F5Y3X8PP",
            "offers": {"price": "19.99", "priceCurrency": "USD"},
        }
    )
    html = (
        "<html><head><script type='application/ld+json'>"
        f"{payload}"
        "</script></head><body></body></html>"
    )

    result = extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            html,
            "https://www.amazon.com/example/dp/B0F5Y3X8PP",
            max_records=1,
        )
    )

    assert result.records[0]["title"] == (
        "Poppi Prebiotic Soda, Sparkling Water & Fruit Juice, Punch Pop, 12 Oz, 12 Pack"
    )


def test_two_segment_pipe_title_needs_host_corroboration() -> None:
    """A short trailing segment after a pipe has the same shape whether it is
    the site's name or part of the product's own name, so shape alone must not
    decide it. Only the page host can, and it is consulted before the segment
    is dropped rather than after."""
    url = "https://www.kitchenaid.com/products/food-processor"

    # Two words and shorter than the leading segment - site-suffix shape - but
    # the host does not corroborate it, so it is product identity.
    assert (
        normalize_detail_marketplace_title(
            "13-Cup Food Processor | Contour Silver", page_url=url
        )
        == "13-Cup Food Processor | Contour Silver"
    )
    # The host does corroborate this one.
    assert (
        normalize_detail_marketplace_title(
            "13-Cup Food Processor | KitchenAid", page_url=url
        )
        == "13-Cup Food Processor"
    )
