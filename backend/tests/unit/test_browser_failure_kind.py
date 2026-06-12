from __future__ import annotations

import pytest

from app.services.acquisition.browser_diagnostics import browser_failure_kind


@pytest.mark.unit
def test_browser_failure_kind_detects_playwright_none_send_error() -> None:
    # Simulates AttributeError: Browser.new_context: 'NoneType' object has no attribute 'send'
    exc = AttributeError("Browser.new_context: 'NoneType' object has no attribute 'send'")
    assert browser_failure_kind(exc) == "browser_driver_closed"


@pytest.mark.unit
def test_browser_failure_kind_detects_playwright_none_send_underscore_error() -> None:
    # Simulates AttributeError: Browser.new_context: 'NoneType' object has no attribute '_send'
    exc = AttributeError("Browser.new_context: 'NoneType' object has no attribute '_send'")
    assert browser_failure_kind(exc) == "browser_driver_closed"


@pytest.mark.unit
def test_browser_failure_kind_detects_other_known_errors() -> None:
    # Target closed error
    exc = RuntimeError("Page.goto: Target closed")
    assert browser_failure_kind(exc) == "page_closed"

    # Connection closed
    exc = RuntimeError("Page.content: Connection closed while reading from the driver")
    assert browser_failure_kind(exc) == "browser_driver_closed"

    # Timeout
    exc = TimeoutError("Navigation timeout of 30000ms exceeded")
    assert browser_failure_kind(exc) == "timeout"


@pytest.mark.unit
def test_browser_failure_kind_detects_engine_unavailable_errors() -> None:
    assert (
        browser_failure_kind(RuntimeError("Real Chrome executable is not available"))
        == "engine_unavailable"
    )
    assert (
        browser_failure_kind(RuntimeError("Patchright package is not available"))
        == "engine_unavailable"
    )
