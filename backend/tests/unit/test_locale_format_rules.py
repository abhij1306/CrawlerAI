from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config.locale_format_rules import (
    currency_hint_from_page_url,
    locale_hint_from_page_url,
    money_has_ambiguous_decimal,
    parse_money,
    validate_gtin,
)

pytestmark = pytest.mark.unit


def test_locale_aware_money_parsing_respects_decimal_separator() -> None:
    assert parse_money("1.299,99", locale_hint="de-DE") == Decimal("1299.99")
    assert parse_money("1,299.99", locale_hint="en-US") == Decimal("1299.99")
    assert parse_money("₹1,86,000", locale_hint="en-IN") == Decimal("186000")


def test_ambiguous_money_without_locale_uses_last_separator_and_flags() -> None:
    assert parse_money("1.299,99", locale_hint=None) == Decimal("1299.99")
    assert parse_money("1,299.99", locale_hint=None) == Decimal("1299.99")
    assert money_has_ambiguous_decimal("1.299,99", locale_hint=None) is True


def test_gtin_check_digit_validation() -> None:
    assert validate_gtin("4006381333931") is True
    assert validate_gtin("4006381333932") is False
    assert validate_gtin("1234567") is False


def test_generic_url_locale_and_currency_inference() -> None:
    assert currency_hint_from_page_url("https://shop.co.in/p/item") == "INR"
    assert currency_hint_from_page_url("https://shop.test/en-gb/p/item") == "GBP"
    assert locale_hint_from_page_url("https://shop.test/fr-fr/p/item") == "fr-fr"
    assert currency_hint_from_page_url("https://shop.com/products/item") is None
