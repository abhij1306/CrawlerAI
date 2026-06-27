from __future__ import annotations

import json

import pytest

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
        "Poppi Prebiotic Soda, Sparkling Water & Fruit Juice, Punch Pop, "
        "12 Oz, 12 Pack"
    )
