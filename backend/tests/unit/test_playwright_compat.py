from __future__ import annotations

import pytest

from app.acquisition.browser_capture import (
    PLAYWRIGHT_RECOVERABLE_ERRORS,
    PlaywrightError,
    _decode_network_payload,
    is_recoverable_playwright_error,
)


@pytest.mark.unit
def test_recoverable_playwright_errors_exclude_plain_runtime_error() -> None:
    assert RuntimeError not in PLAYWRIGHT_RECOVERABLE_ERRORS
    assert not is_recoverable_playwright_error(RuntimeError("application bug"))


@pytest.mark.unit
def test_recoverable_playwright_error_accepts_whitelisted_runtime_message() -> None:
    assert is_recoverable_playwright_error(RuntimeError("Page.goto: Target closed"))


@pytest.mark.unit
def test_recoverable_playwright_error_accepts_playwright_error() -> None:
    assert is_recoverable_playwright_error(PlaywrightError("driver failed"))


@pytest.mark.unit
def test_truncated_json_payload_repairs_complete_prefix() -> None:
    payload = (
        b'{"product":{"variants":['
        b'{"sku":"S-1","currency":"INR"},'
        b'{"sku":"S-2","currency":"INR","color":"Black","cu'
    )
    assert _decode_network_payload(payload, content_type="application/json") == {
        "product": {
            "variants": [
                {"sku": "S-1", "currency": "INR"},
                {"sku": "S-2", "currency": "INR", "color": "Black"},
            ]
        }
    }


@pytest.mark.unit
def test_truncated_json_payload_does_not_invent_incomplete_value() -> None:
    payload = b'{"product":{"title":"Speedcat","description":"Partially cut'
    assert _decode_network_payload(payload, content_type="application/json") == {
        "product": {"title": "Speedcat"}
    }
