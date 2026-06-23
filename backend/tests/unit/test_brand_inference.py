from __future__ import annotations

import pytest

from app.core.shared.field_coerce_text import infer_brand_from_product_url

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        (
            "https://www.nordstrom.com/s/nike-air-force-1-07-basketball-sneaker-men/7507996",
            "Air Force 1 '07 Basketball Sneaker",
            "Nike",
        ),
        (
            "https://stockx.com/nike-dunk-low-retro-white-black-2021",
            "Dunk Low Retro White Black",
            "Nike",
        ),
        (
            "https://www.grailed.com/listings/92502018-peter-do-velcro-strap-set-up-blazer-pants",
            "Velcro Strap Set-up Blazer / Pants",
            "Peter Do",
        ),
    ],
)
def test_product_url_prefix_recovers_brand_before_title_anchor(
    url: str, title: str, expected: str
) -> None:
    assert infer_brand_from_product_url(url=url, title=title) == expected
