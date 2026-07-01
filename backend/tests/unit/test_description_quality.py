from __future__ import annotations

import json

import pytest

from app.extraction import Surface, extract
from app.extraction.replay import fixture_request_from_inputs

pytestmark = pytest.mark.unit


def _extract(html: str):
    return extract(
        fixture_request_from_inputs(
            Surface.ECOMMERCE_DETAIL,
            html,
            "https://shop.test/products/complete-description",
            max_records=1,
        )
    )


def _product_html(*, description: str, meta_description: str | None = None) -> str:
    meta = (
        f'<meta property="og:description" content="{meta_description}">'
        if meta_description is not None
        else ""
    )
    payload = json.dumps(
        {
            "@context": "https://schema.org",
            "@type": "Product",
            "name": "Complete Description Product",
            "url": "https://shop.test/products/complete-description",
            "description": description,
            "offers": {"price": "10", "priceCurrency": "USD"},
        }
    )
    return f"<html><head>{meta}<script type='application/ld+json'>{payload}</script></head><body><h1>Complete Description Product</h1></body></html>"


def test_exact_320_character_description_is_preserved_and_diagnosed() -> None:
    description = ("Complete product details with durable construction. " * 8)[:320]
    assert len(description) == 320

    result = _extract(_product_html(description=description))

    assert result.records[0]["description"] == description
    assert any(
        finding.rule_id == "DESCRIPTION_HARD_BOUNDARY" for finding in result.findings
    )
    evidence = [
        row for row in result.evidence if row.fact_type == "product.description"
    ]
    assert any("description_hard_boundary" in row.flags for row in evidence)


def test_full_product_description_outranks_boundary_meta_excerpt() -> None:
    excerpt = ("Short catalogue excerpt without a complete ending " * 9)[:320]
    full = (
        "This is the complete product-specific description. "
        "It explains materials, construction, care, and intended use without "
        "shipping or search-directory promotional copy."
    )

    result = _extract(_product_html(description=full, meta_description=excerpt))

    assert result.records[0]["description"] == full


def test_clean_product_description_suppresses_candidate_only_promotional_finding() -> None:
    promotional = (
        "Shop this product online today with free shipping, lowest prices, "
        "exclusive offers and fast delivery. Buy now."
    )
    clean = (
        "Tailored barrel pants in structured cotton twill with a fixed waist, "
        "front pleats, side pockets, and a tapered ankle-length leg."
    )

    result = _extract(_product_html(description=clean, meta_description=promotional))

    assert result.records[0]["description"] == clean
    assert not any(
        finding.rule_id == "DESCRIPTION_PROMOTIONAL_COPY" for finding in result.findings
    )


def test_legitimate_camelcase_and_model_tokens_are_not_split() -> None:
    description = "Works with iPhone, eBay, PowerShot, PlayStation, and Canon Log3."

    result = _extract(_product_html(description=description))

    assert result.records[0]["description"] == description


def test_promotional_search_copy_cannot_become_product_description() -> None:
    promotional = (
        "Shop this product online today with free shipping, lowest prices, "
        "exclusive offers and fast delivery. Buy now."
    )

    result = _extract(
        _product_html(description=promotional, meta_description=promotional)
    )

    assert result.records[0].get("description") is None
    assert any(
        finding.rule_id == "DESCRIPTION_PROMOTIONAL_COPY" for finding in result.findings
    )


@pytest.mark.parametrize(
    "description",
    [
        "Buy Arizona Birko-Flor at Birkenstock US.",
        "Web PDP Default Layout, Mix and Match Carousel on Home Categories",
        "Find Velcro Strap Set-up Blazer / Pants and more items on grailed.com",
        (
            "Discover Cotton Utility Button Detail Barrel Leg Trouser available "
            "to buy online with quick delivery and easy return options. Shop now!"
        ),
    ],
)
def test_generic_ui_and_retailer_copy_cannot_become_description(
    description: str,
) -> None:
    result = _extract(_product_html(description=description))

    assert result.records[0].get("description") is None


def test_description_ending_with_incomplete_connector_is_rejected() -> None:
    incomplete = (
        "Step into the spotlight with this bracelet. It is comfortable, durable, "
        "easy to wear, and designed to make a bold statement. Easy on and"
    )

    result = _extract(_product_html(description=incomplete))

    assert result.records[0].get("description") is None
    assert any(
        finding.rule_id == "DESCRIPTION_INCOMPLETE_ENDING"
        for finding in result.findings
    )
