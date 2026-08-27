from __future__ import annotations

import pytest

from app.core.records.url_identity import (
    conflicting_product_asset_urls,
    detail_title_has_seo_pollution,
    detail_title_from_url,
    detail_url_looks_like_product,
    detail_url_resource_identity,
)
from app.core.shared.url_utils import (
    ensure_scheme,
    identity_token,
    is_placeholder_image_url,
    is_utility_image_url,
    low_resolution_asset_urls,
    public_asset_delivery_url,
    absolute_url,
    asset_url_identity,
    extract_urls,
    same_host,
)


@pytest.mark.unit
def test_opaque_terminal_detail_segment_does_not_fall_back_to_category_title() -> None:
    assert (
        detail_title_from_url(
            "https://kith.test/collections/mens-footwear-sneakers/products/st40002-02000"
        )
        == ""
    )


def test_detail_title_ignores_suffix_after_opaque_detail_identity() -> None:
    url = (
        "https://shop.test/zapcase-motorola-compatible-protection/"
        "dp/B0CSP8GZ5R/ref=pd_ci_mcx_mh_mcx_views_2_image?th=1"
    )

    assert detail_title_from_url(url) == "zapcase motorola compatible protection"
    assert (
        detail_title_from_url(
            "https://shop.test/womens/categories/clothing/pants/wide-leg/ME988"
        )
        == ""
    )
    assert (
        detail_title_from_url("https://shop.test/browse/product.do?pid=887835012") == ""
    )


def test_descriptive_html_detail_url_has_resource_identity() -> None:
    url = (
        "https://www.endclothing.com/us/"
        "47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html?queryID=tracking"
    )
    assert detail_url_resource_identity(url) == (
        "www.endclothing.com/us/47-ny-yankees-clean-up-cap-b-rgw17gws-vn.html"
    )


def test_normalized_title_is_not_penalized_for_removed_site_suffix() -> None:
    assert not detail_title_has_seo_pollution(
        "Arizona Birko-Flor in Color Black",
        "Arizona Birko-Flor in Color Black | Example Store",
        ["arizona", "birko", "flor", "in", "color", "black"],
    )


def test_product_endpoint_with_identity_query_has_resource_identity() -> None:
    url = "https://shop.test/browse/product.do?pid=887835012&vid=1"

    assert detail_title_from_url(url) == ""
    assert detail_url_looks_like_product(url) is True
    assert detail_url_resource_identity(url) == "shop.test/browse/product.do"


def test_absolute_url_repairs_relative_and_bare_host_values() -> None:
    assert absolute_url("https://example.com/a/page", "../p") == "https://example.com/p"
    assert absolute_url("https://example.com/a/page", "?q=1") == (
        "https://example.com/a/page?q=1"
    )
    assert absolute_url("https://example.com/a/page", "#details") == (
        "https://example.com/a/page#details"
    )
    assert absolute_url("https://example.com", "cdn.example.com") == (
        "https://cdn.example.com"
    )
    assert absolute_url("https://example.com", "") == ""
    assert (
        absolute_url(
            "https://www.carhartt.com/en-eu/c/men/t-shirts/short-sleeved/eum3000076",
            "en-eu/p/irvine-relaxed-truck-t-shirt/107455",
        )
        == "https://www.carhartt.com/en-eu/p/irvine-relaxed-truck-t-shirt/107455"
    )


@pytest.mark.unit
def test_ensure_scheme_preserves_relative_and_existing_scheme() -> None:
    assert ensure_scheme("example.com") == "https://example.com"
    assert ensure_scheme("/path") == "/path"
    assert ensure_scheme("javascript:void(0)") == "javascript:void(0)"
    assert ensure_scheme("http://example.com") == "http://example.com"


@pytest.mark.unit
def test_asset_url_identity_encodes_paths_and_keeps_meaningful_params() -> None:
    assert asset_url_identity("https://cdn.test/i/Trail Shoe.jpg?width=800") == (
        "https://cdn.test/i/Trail%20Shoe.jpg?width=800",
        "https://cdn.test/i/Trail%20Shoe.jpg",
    )
    assert asset_url_identity(
        "https://cdn.test/i/Trail%20Shoe.jpg?color=red&width=800"
    ) == (
        "https://cdn.test/i/Trail%20Shoe.jpg?color=red&width=800",
        "https://cdn.test/i/Trail%20Shoe.jpg?color=red",
    )


@pytest.mark.unit
def test_asset_url_identity_decodes_html_entities_before_parsing() -> None:
    assert asset_url_identity(
        "https://cdn.shop.test/image.jpg?wid=800&amp;fmt=webp&amp;product=shoe"
    ) == (
        "https://cdn.shop.test/image.jpg?wid=800&fmt=webp&product=shoe",
        "https://cdn.shop.test/image.jpg?product=shoe",
    )


@pytest.mark.unit
def test_public_asset_delivery_url_decodes_html_entities_before_parsing() -> None:
    assert (
        public_asset_delivery_url(
            "https://cdn.shop.test/image.jpg?wid=800&amp;fmt=webp&amp;product=shoe"
        )
        == "https://cdn.shop.test/image.jpg?wid=800&fmt=webp&product=shoe"
    )


@pytest.mark.unit
def test_asset_url_identity_ignores_cdn_path_transforms() -> None:
    vans_thumbnail = (
        "https://assets.vans.com/images/t_Thumbnail/v1769548026/"
        "VN000E9TBPG-ALT1/Old-Skool-Shoe-VANS-ALT1.png"
    )
    vans_large = (
        "https://assets.vans.com/images/t_img/c_fill,g_center,f_auto,h_2500,w_2000/"
        "v1769548026/VN000E9TBPG-ALT1/Old-Skool-Shoe-VANS-ALT1.png"
    )
    puma_large = (
        "https://images.puma.com/image/upload/"
        "f_auto,q_auto,b_rgb:fafafa,w_2000,h_2000/global/406329/02/fnd/IND/fmt/png/"
        "Speedcat-Sneakers"
    )
    puma_small = (
        "https://images.puma.com/image/upload/"
        "f_auto,q_auto,b_rgb:fafafa,w_600,h_600/global/406329/02/fnd/IND/fmt/png/"
        "Speedcat-Sneakers"
    )

    assert asset_url_identity(vans_thumbnail)[1] == asset_url_identity(vans_large)[1]
    assert asset_url_identity(puma_large)[1] == asset_url_identity(puma_small)[1]


@pytest.mark.unit
def test_same_host_and_extract_urls_trim_malformed_candidates() -> None:
    assert same_host("https://example.com/a", "https://example.com/b")
    assert not same_host("https://example.com/a", "https://other.test/b")
    assert extract_urls(
        "See https://example.com/a), https://example.com/b.",
        "https://example.com",
    ) == ["https://example.com/a", "https://example.com/b"]
    assert extract_urls("https://example.com/ahttps://example.com/b", "https://x") == []
    assert extract_urls(
        {"image": {"url": "/img.png"}},
        "https://example.com/p",
    ) == ["https://example.com/img.png"]
    assert extract_urls(["/a", "/a", "/B"], "https://example.com") == [
        "https://example.com/a",
        "https://example.com/B",
    ]


@pytest.mark.unit
def test_placeholder_images_are_rejected() -> None:
    assert is_placeholder_image_url("https://via.placeholder.com/100")
    assert extract_urls("https://via.placeholder.com/100", "https://example.com") == []


@pytest.mark.unit
def test_shopify_no_image_storefront_asset_is_rejected() -> None:
    """Shopify renders a `no-image-*` placeholder GIF inside JSON-LD when the
    real product image is only available via og:image / DOM. Reject the
    placeholder so a valid image candidate can win.
    """
    glossier_no_image = (
        "https://www.glossier.com/cdn/shopifycloud/storefront/assets/"
        "no-image-2048-a2addb12_348x.gif"
    )
    assert is_placeholder_image_url(glossier_no_image)
    # Real Shopify CDN product images must still pass.
    real_shopify_cdn = (
        "https://cdn.shopify.com/s/files/1/0939/9055/1893/files/"
        "DIME2SP2542BLK-1.jpg?v=1745568172"
    )
    assert not is_placeholder_image_url(real_shopify_cdn)


@pytest.mark.unit
def test_navigation_and_label_only_image_urls_are_rejected() -> None:
    assert is_utility_image_url("https://cdn.test/images/MegaNavPromo_WhatsNew.jpg")
    assert is_utility_image_url("https://cdn.test/products/pants/Front%20view")


@pytest.mark.unit
@pytest.mark.parametrize(
    "filename",
    [
        "amex.svg",
        "mastercard.svg",
        "affirm.svg",
        "visa-card.svg",
        "applepay.svg",
        "apple-pay.svg",
        "apple_pay.svg",
    ],
)
def test_payment_provider_svg_urls_are_rejected(filename: str) -> None:
    assert is_utility_image_url(f"https://cdn.test/assets/{filename}")


def test_single_low_resolution_primary_candidate_is_rejected() -> None:
    image = "https://cdn.test/product.jpg?sw=71"
    assert low_resolution_asset_urls((image,)) == frozenset({image})


def test_single_descriptive_foreign_gallery_asset_is_rejected() -> None:
    opaque = "https://cdn.test/6bdb04d9-1f2b-4511-a911.jpg"
    foreign = "https://cdn.test/sourcing_images/playstation_4_two_controllers.jpg"
    assert conflicting_product_asset_urls(
        ("iPhone 15 Plus Unlocked", "https://shop.test/iphone-15-plus"),
        (opaque, foreign),
    ) == frozenset({foreign})


def test_identity_token_does_not_singularize_double_s_words() -> None:
    assert identity_token("dress") == "dress"
    assert identity_token("glass") == "glass"
    assert identity_token("shoes") == "shoe"


def test_public_asset_delivery_url_repairs_nested_single_slash_https_url() -> None:
    from app.core.shared.url_utils import public_asset_delivery_url

    value = "https://shop.test/w_1024/https:/images.ctfassets.net/path/image.png"
    assert public_asset_delivery_url(value) == (
        "https://images.ctfassets.net/path/image.png"
    )


def test_public_asset_delivery_url_repairs_duplicated_delivery_host_path() -> None:
    from app.core.shared.url_utils import public_asset_delivery_url

    value = (
        "https://www.brooklinen.com//www.brooklinen.com/cdn/shop/files/"
        "BK7885_1.jpg?v=1775832414&width=1200"
    )

    assert public_asset_delivery_url(value) == (
        "https://www.brooklinen.com/cdn/shop/files/BK7885_1.jpg?v=1775832414&width=1200"
    )


def test_public_asset_delivery_url_rejects_doubled_query_string() -> None:
    from app.core.shared.url_utils import public_asset_delivery_url

    # Two literal "?" is malformed concatenation of two query strings; a real
    # query value would percent-encode an embedded "?".
    value = "https://cdn.shop.test/files/image.jpg?width=800?v=12345"
    assert public_asset_delivery_url(value) is None
    # A single, well-formed query string is preserved unchanged.
    assert (
        public_asset_delivery_url("https://cdn.shop.test/files/image.jpg?width=800")
        == "https://cdn.shop.test/files/image.jpg?width=800"
    )


def test_utility_image_rejects_generic_default_asset() -> None:
    assert is_utility_image_url(
        "https://shop.test/resources/images/canon-image-default.webp"
    )
