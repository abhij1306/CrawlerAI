"""Unit tests for detail image candidate filtering."""
from __future__ import annotations

import pytest

from app.services.extract.detail.images.cleanup import (
    _detail_image_candidate_is_usable,
    detail_image_matches_primary_family,
)
from app.services.dom.image_extraction import canonical_image_url


@pytest.mark.unit
def test_walmart_pdp_url_is_rejected_from_additional_images() -> None:
    """Walmart additional_images surfaced PDP URLs (no image extension, with
    ``/ip/`` segment) instead of real product images. A URL whose path has
    no image extension AND looks like a PDP segment must be filtered.
    """
    identity = (
        "https://www.walmart.com/ip/Apple-AirPods-with-Charging-Case-2nd-Generation/604342441"
    )
    pdp = (
        "https://www.walmart.com/ip/Apple-AirPods-with-Charging-Case-2nd-Generation/"
        "D88D543AD9E843C0A93F1A4DFE93BDF2"
    )
    assert not _detail_image_candidate_is_usable(pdp, identity_url=identity)


@pytest.mark.unit
def test_real_walmart_image_is_kept() -> None:
    identity = (
        "https://www.walmart.com/ip/Apple-AirPods-with-Charging-Case-2nd-Generation/604342441"
    )
    real = (
        "https://i5.walmartimages.com/asr/b6247579-386a-4bda-99aa-01e44801bc33."
        "49db04f5e5b8d7f329c6580455e2e010.jpeg?odnHeight=160&odnWidth=160"
    )
    assert _detail_image_candidate_is_usable(real, identity_url=identity)


@pytest.mark.unit
def test_pdp_segment_with_image_extension_passes() -> None:
    """A path containing ``/products/`` IS legitimate when the URL still has
    an image extension or a known image-asset path token. Do not over-filter.
    """
    identity = "https://example.com/products/widget"
    image = "https://cdn.example.com/products/widget-front.jpg"
    assert _detail_image_candidate_is_usable(image, identity_url=identity)


@pytest.mark.unit
def test_primary_code_without_candidate_code_still_uses_family_tokens() -> None:
    primary = "https://cdn.example.com/images/AB12345-widget-front.jpg"
    candidate = "https://cdn.example.com/images/widget-jacket-side.jpg"

    assert detail_image_matches_primary_family(
        candidate,
        primary_image=primary,
        title="Widget jacket",
    )


@pytest.mark.unit
def test_shopify_canonical_image_keeps_store_identity_with_query() -> None:
    left = canonical_image_url(
        "https://store-a.myshopify.com/cdn/shop/files/widget.jpg?v=1&width=200"
    )
    right = canonical_image_url(
        "https://store-b.myshopify.com/cdn/shop/files/widget.jpg?v=1&width=200"
    )

    assert left == "https://store-a.myshopify.com/files/widget?v=1"
    assert right == "https://store-b.myshopify.com/files/widget?v=1"
    assert left != right
