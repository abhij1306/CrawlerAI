"""Acquisition facade for the pure surface-aware listing-card owner."""

from __future__ import annotations

from typing import Any

from selectolax.lexbor import LexborHTMLParser

from app.core.listing_cards import (
    ListingCard,
    ListingCardDiagnostics,
    card_is_admitted,
    card_quality_score,
    card_rejection_reason,
    derive_card_selectors,
    select_listing_cards,
    select_listing_cards_with_diagnostics,
    stable_card_identity,
    unique_card_count,
)
from app.extraction.surfaces import listing_surface_spec


def selectors_for_surface(surface: str) -> tuple[str, ...]:
    return derive_card_selectors(listing_surface_spec(surface))


def cards_from_html(
    html: str,
    *,
    page_url: str,
    surface: str,
    limit: int | None = None,
) -> tuple[ListingCard, ...]:
    if not str(html or "").strip():
        return ()
    return select_listing_cards(
        LexborHTMLParser(str(html)),
        surface=listing_surface_spec(surface),
        page_url=page_url,
        limit=limit,
    )


def card_diagnostics_from_html(
    html: str,
    *,
    page_url: str,
    surface: str,
) -> dict[str, object]:
    if not str(html or "").strip():
        return ListingCardDiagnostics().as_dict()
    return select_listing_cards_with_diagnostics(
        LexborHTMLParser(str(html)),
        surface=listing_surface_spec(surface),
        page_url=page_url,
    ).diagnostics.as_dict()


def card_identities_from_html(
    html: str, *, page_url: str, surface: str
) -> tuple[str, ...]:
    return tuple(
        card.identity
        for card in cards_from_html(html, page_url=page_url, surface=surface)
    )


def count_cards_from_html(html: str, *, page_url: str, surface: str) -> int:
    return unique_card_count(
        card_identities_from_html(html, page_url=page_url, surface=surface)
    )


def card_fragments_from_html(
    html: str,
    *,
    page_url: str,
    surface: str,
    limit: int,
) -> tuple[str, ...]:
    return tuple(
        str(getattr(card.node, "html", "") or "").strip()
        for card in cards_from_html(
            html,
            page_url=page_url,
            surface=surface,
            limit=limit,
        )
        if str(getattr(card.node, "html", "") or "").strip()
    )


async def count_listing_cards(
    page: Any, *, surface: str, allow_heuristic: bool = True
) -> int:
    """Count the same admitted identities readiness and extraction consume."""

    del allow_heuristic
    from app.acquisition.dom_runtime import get_page_html

    html = await get_page_html(page, flatten_shadow=False)
    return count_cards_from_html(
        html,
        page_url=str(getattr(page, "url", "") or ""),
        surface=surface,
    )


__all__ = [
    "ListingCard",
    "card_diagnostics_from_html",
    "card_fragments_from_html",
    "card_identities_from_html",
    "card_is_admitted",
    "card_quality_score",
    "card_rejection_reason",
    "cards_from_html",
    "count_cards_from_html",
    "count_listing_cards",
    "select_listing_cards",
    "selectors_for_surface",
    "stable_card_identity",
    "unique_card_count",
]
