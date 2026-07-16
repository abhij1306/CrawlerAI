from __future__ import annotations

import pytest

from app.acquisition.listing_cards import (
    card_identities_from_html,
    cards_from_html,
    count_cards_from_html,
    selectors_for_surface,
)
from app.acquisition.traversal import _observe_unique_cards
from app.acquisition.traversal_types import TraversalResult
from app.core.listing_cards import card_rejection_reason, stable_url_identity
from app.extraction.documents import HtmlDocument
from app.extraction.surfaces import Surface, listing_schema

pytestmark = pytest.mark.unit


def test_selector_derivation_is_surface_aware_and_config_owned() -> None:
    commerce = selectors_for_surface("ecommerce_listing")
    jobs = selectors_for_surface("job_listing")

    assert "[data-product-id]" in commerce
    assert "[data-job-id]" not in commerce
    assert "[data-job-id]" in jobs
    assert "[data-product-id]" not in jobs
    assert selectors_for_surface("jobs") == jobs
    assert len(commerce) == len(set(commerce))


def test_selection_admission_identity_and_count_are_one_contract() -> None:
    html = """
    <main>
      <article class="product-card"><a href="/products/one">One Shoe</a><img src="one.jpg"></article>
      <article class="product-card duplicate"><a href="/products/one">One Shoe duplicate</a><span>$10</span></article>
      <article><a href="/collections/shoes">Shoes</a></article>
      <article style="display:none"><a href="/products/two">Two Shoe</a><img src="two.jpg"></article>
    </main>
    """

    cards = cards_from_html(
        html,
        page_url="https://shop.test/collections/all",
        surface="ecommerce_listing",
    )

    assert [card.url for card in cards] == ["https://shop.test/products/one"]
    assert card_identities_from_html(
        html,
        page_url="https://shop.test/collections/all",
        surface="ecommerce_listing",
    ) == tuple(card.identity for card in cards)
    assert count_cards_from_html(
        html,
        page_url="https://shop.test/collections/all",
        surface="ecommerce_listing",
    ) == len(cards) == 1


def test_quality_gate_rejects_weak_commerce_but_allows_off_host_jobs() -> None:
    commerce_schema = listing_schema(Surface.ECOMMERCE_LISTING)
    job_schema = listing_schema(Surface.JOB_LISTING)
    assert commerce_schema is not None
    assert job_schema is not None

    weak = HtmlDocument(
        "html", '<article><a href="/products/one">One Shoe</a></article>'
    ).css("article")[0]
    job = HtmlDocument(
        "html",
        '<article><a href="https://boards.greenhouse.io/acme/jobs/1">Backend Engineer</a><span>Remote US</span></article>',
    ).css("article")[0]

    assert (
        card_rejection_reason(
            weak,
            surface=commerce_schema,
            page_url="https://shop.test/collections/all",
            selector="article",
        )
        == "weak_generic_card"
    )
    assert (
        card_rejection_reason(
            job,
            surface=job_schema,
            page_url="https://acme.test/careers",
            selector="article",
        )
        is None
    )


def test_stable_identity_preserves_query_identity() -> None:
    assert stable_url_identity("https://jobs.test/job?id=123") != stable_url_identity(
        "https://jobs.test/job?id=456"
    )


def test_traversal_card_count_is_total_unique_observed_across_pages() -> None:
    result = TraversalResult(requested_mode="paginate")

    first = _observe_unique_cards(
        result,
        {"card_count": 2, "card_identities": ("one", "two")},
    )
    second = _observe_unique_cards(
        result,
        {"card_count": 2, "card_identities": ("two", "three")},
        additive_fallback=True,
    )

    assert first["card_count"] == 2
    assert second["card_count"] == 3
    assert result.card_count == 3
