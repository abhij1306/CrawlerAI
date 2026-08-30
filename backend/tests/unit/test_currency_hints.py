from __future__ import annotations

import pytest

from app.core.shared.currency_hints import currency_hint_from_page_url

pytestmark = pytest.mark.unit


def test_locale_path_segment_infers_currency() -> None:
    assert currency_hint_from_page_url("https://shop.test/en-in/p/item") == "INR"
    assert currency_hint_from_page_url("https://shop.test/en-gb/p/item") == "GBP"
    assert currency_hint_from_page_url("https://shop.test/fr-fr/p/item") == "EUR"
    # Underscore locale separators also work.
    assert currency_hint_from_page_url("https://shop.test/en_us/p/item") == "USD"


def test_leading_country_path_segment_infers_currency() -> None:
    assert currency_hint_from_page_url("https://shop.test/us/store/item") == "USD"
    assert currency_hint_from_page_url("https://shop.test/uk/products/item") == "GBP"
    assert currency_hint_from_page_url("https://shop.test/products/us/item") is None


def test_cctld_infers_currency() -> None:
    assert currency_hint_from_page_url("https://shop.co.in/p/item") == "INR"
    assert currency_hint_from_page_url("https://shop.co.uk/p/item") == "GBP"
    assert currency_hint_from_page_url("https://shop.com.au/p/item") == "AUD"
    assert currency_hint_from_page_url("https://shop.de/p/item") == "EUR"


def test_locale_segment_outranks_cctld() -> None:
    # The per-page locale segment wins over the host-level ccTLD.
    assert currency_hint_from_page_url("https://shop.co.uk/en-in/p/item") == "INR"


def test_generic_gtld_without_locale_infers_nothing() -> None:
    # No site-specific host literals: a plain .com / .co with no locale signal
    # yields no currency rather than a guessed one.
    assert currency_hint_from_page_url("https://shop.com/products/item") is None
    assert currency_hint_from_page_url("https://brand.co/products/item") is None
    assert currency_hint_from_page_url("https://example.io/products/item") is None


def test_empty_or_invalid_url_is_safe() -> None:
    assert currency_hint_from_page_url("") is None
    assert currency_hint_from_page_url(None) is None
