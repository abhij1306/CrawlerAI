from __future__ import annotations

import pytest

from app.services.acquisition.playwright_compat import (
    PLAYWRIGHT_RECOVERABLE_ERRORS,
    PlaywrightError,
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
