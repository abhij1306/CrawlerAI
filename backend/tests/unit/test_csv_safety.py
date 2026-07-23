"""Unit tests for CSV formula-injection sanitization (audit 1.7)."""

from __future__ import annotations

import pytest

from app.core.config.export_settings import CSV_FORMULA_PREFIX_PATTERN
from app.core.shared.csv_safety import csv_safe_cell, sanitize_csv_row

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
def test_csv_safe_cell_prefixes_dangerous_leading_characters(prefix: str) -> None:
    assert csv_safe_cell(f"{prefix}SUM(A1:A10)") == f"'{prefix}SUM(A1:A10)"


@pytest.mark.parametrize(
    "value",
    [
        "Widget Prime",
        "19.99",
        " leading-space=safe",
        "",
        "=",  # still prefixed: a bare marker is still a formula attempt
        "a=b",
    ],
)
def test_csv_safe_cell_leaves_safe_strings_untouched(value: str) -> None:
    expected = f"'{value}" if CSV_FORMULA_PREFIX_PATTERN.match(value) else value
    assert csv_safe_cell(value) == expected


@pytest.mark.parametrize("value", [None, 12, 4.5, True, ["=x"]])
def test_csv_safe_cell_passes_non_strings_through(value: object) -> None:
    assert csv_safe_cell(value) is value


def test_sanitize_csv_row_sanitizes_keys_and_string_values() -> None:
    row = {
        "=cmd|'/c calc'!A1": "=HYPERLINK(\"http://evil.example\")",
        "title": "Widget",
        "price": 19.99,
        "in-stock": True,
    }

    sanitized = sanitize_csv_row(row)

    assert sanitized == {
        "'=cmd|'/c calc'!A1": "'=HYPERLINK(\"http://evil.example\")",
        "title": "Widget",
        "price": 19.99,
        "in-stock": True,
    }


def test_sanitize_csv_row_returns_new_dict() -> None:
    row = {"title": "Widget"}

    sanitized = sanitize_csv_row(row)

    assert sanitized is not row
    assert row == {"title": "Widget"}
