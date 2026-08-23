from __future__ import annotations

import pytest

from app.core.records.normalizers import normalize_decimal_price, normalize_value

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("value", ("1", "89", "100"))
def test_plain_integral_price_strings_are_not_ambiguous(value: str) -> None:
    assert normalize_decimal_price(value) == value


def test_integral_price_still_supports_explicit_cent_interpretation() -> None:
    assert normalize_decimal_price("100", interpret_integral_as_cents=True) == "1"


def test_embedded_short_integer_requires_price_context() -> None:
    assert normalize_decimal_price("SKU 10") is None
    assert normalize_decimal_price("Price 10") == "10"
    assert normalize_decimal_price("USD 10") == "10"


@pytest.mark.parametrize("value", ("-1", "-12.50", "−12.50"))
def test_decimal_fields_reject_negative_plain_numeric_strings(value: str) -> None:
    assert normalize_value("price", value) == ""
