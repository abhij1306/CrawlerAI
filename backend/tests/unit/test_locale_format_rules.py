from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.config.locale_format_rules import (
    _currency_from_host_hint,
    currency_hint_from_page_url,
    currency_hint_from_page_url_with_scope,
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


def test_unknown_locale_hint_does_not_suppress_ambiguous_money_flag() -> None:
    assert money_has_ambiguous_decimal("1.299,99", locale_hint="xx-ZZ") is True
    assert money_has_ambiguous_decimal("1.299,99", locale_hint="de-DE") is False


def test_lone_decimal_separator_keeps_machine_price_shape_across_locales() -> None:
    assert parse_money("12.50", locale_hint="de-DE") == Decimal("12.50")
    assert parse_money("12,50", locale_hint="en-US") == Decimal("12.50")


def test_over_precise_lone_decimal_is_not_read_as_grouping() -> None:
    # An ERP/JSON feed emits "128.000000" (six-place minor units). A grouping
    # separator only ever produces three-digit groups, so a lone separator with
    # a >=4-digit tail must be an over-precise decimal point — never delete it
    # (which multiplied the value by 1,000,000 and published 128000000).
    assert parse_money("128.000000") == Decimal("128.000000")
    assert parse_money("128,000000") == Decimal("128.000000")
    assert parse_money("1234.5678") == Decimal("1234.5678")
    # A single three-digit tail stays ambiguous (thousands), and genuine
    # multi-group thousands separators are still collapsed.
    assert parse_money("1.234") == Decimal("1234")
    assert parse_money("1.234.567") == Decimal("1234567")


def test_gtin_check_digit_validation() -> None:
    assert validate_gtin("4006381333931") is True
    assert validate_gtin("4006381333932") is False
    assert validate_gtin("1234567") is False


def test_generic_url_locale_and_currency_inference() -> None:
    assert currency_hint_from_page_url("https://shop.co.in/p/item") == "INR"
    assert currency_hint_from_page_url("https://shop.test/en-gb/p/item") == "GBP"
    assert locale_hint_from_page_url("https://shop.test/fr-fr/p/item") == "fr-fr"
    assert currency_hint_from_page_url("https://shop.com/products/item") is None


@pytest.mark.parametrize("hostname", ("firstcry.com", "www.firstcry.com"))
def test_host_currency_hint_matches_exact_host_and_subdomain(hostname: str) -> None:
    assert _currency_from_host_hint(hostname) == "INR"
    assert currency_hint_from_page_url_with_scope(f"https://{hostname}/p/item") == (
        "INR",
        True,
    )


def test_host_currency_hint_rejects_suffix_without_label_boundary() -> None:
    assert _currency_from_host_hint("notfirstcry.com") is None
    assert currency_hint_from_page_url_with_scope("https://notfirstcry.com/p/item") == (
        None,
        False,
    )
