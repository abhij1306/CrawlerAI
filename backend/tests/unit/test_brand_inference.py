from __future__ import annotations

import pytest

from app.core.config.url_path_markers import ECOMMERCE_DETAIL_PATH_MARKERS
from app.core.shared.field_coerce_text import infer_brand_from_product_url

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("marker", ECOMMERCE_DETAIL_PATH_MARKERS)
def test_direct_product_brand_supports_every_configured_detail_marker(
    marker: str,
) -> None:
    assert (
        infer_brand_from_product_url(
            url=f"https://shop.test/nike-air{marker}style-1",
            title="Nike Air Style 1",
        )
        == "Nike"
    )


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
        (
            "https://shop.test/products/dr-martens-1460-smooth-leather-boots",
            "Dr. Martens - 1460 Smooth Leather Boots",
            "Dr. Martens",
        ),
        (
            "https://amsterdamvintagewatches.test/shop/rolex-day-date-18038-champagne",
            "Rolex Day-Date 18038 - Amsterdam Vintage Watches",
            "Rolex",
        ),
    ],
)
def test_product_url_prefix_recovers_brand_before_title_anchor(
    url: str, title: str, expected: str
) -> None:
    assert infer_brand_from_product_url(url=url, title=title) == expected


def test_product_url_brand_prefix_requires_the_full_leading_segment() -> None:
    assert (
        infer_brand_from_product_url(
            url="https://shop.test/products/nike-running-shoe",
            title="Nike Trail - Running Shoe",
        )
        is None
    )


@pytest.mark.parametrize(
    ("url", "title", "expected"),
    [
        (
            "https://www.firstcry.com/babyhug/babyhug-denim-woven-sleeveless-top-and-pant-set/22346676",
            "Babyhug Denim Woven Sleeveless Top and Pant Set With Floral Print",
            "Babyhug",
        ),
        (
            "https://www.chewy.com/wellness-core-rawrev-grain-free-wild/dp/141791",
            "Wellness CORE+ with Freeze-Dried Pieces Adult Grain-Free High Protein",
            "Wellness",
        ),
        (
            "https://stockx.com/nike-dunk-low-retro-white-black-2021",
            "Nike Dunk Low Retro White Black Panda",
            "Nike",
        ),
    ],
)
def test_marketplace_long_slug_recovers_manufacturer_brand_from_title_leading(
    url: str, title: str, expected: str
) -> None:
    assert infer_brand_from_product_url(url=url, title=title) == expected


def test_short_brand_host_slug_does_not_steal_descriptor_as_brand() -> None:
    assert (
        infer_brand_from_product_url(
            url="https://www.calvinklein.us/bags/structured-commuter-bag.html",
            title="Structured Commuter Bag",
        )
        is None
    )


def test_long_generic_product_slug_does_not_steal_descriptor_as_brand() -> None:
    for url in (
        "https://shop.test/products/structured-commuter-bag-black-leather",
        "https://market.test/structured-commuter-bag-black-leather",
    ):
        assert (
            infer_brand_from_product_url(
                url=url,
                title="Structured Commuter Bag",
            )
            is None
        )
