from __future__ import annotations

import pytest
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.acquisition.browser_readiness import (
    probe_browser_readiness,
    wait_for_listing_readiness,
)

pytestmark = pytest.mark.unit


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url

    def locator(self, _selector: str):
        return self

    async def count(self) -> int:
        return 0


@pytest.mark.asyncio
async def test_repeated_admitted_cards_are_ready_with_uniform_diagnostics() -> None:
    html = """
    <main>
      <article><a href="/products/one">One Shoe</a><img src="one.jpg"></article>
      <article><a href="/products/two">Two Shoe</a><img src="two.jpg"></article>
    </main>
    """
    probe = await probe_browser_readiness(
        _Page("https://shop.test/collections/all"),
        url="https://shop.test/collections/all",
        surface="ecommerce_listing",
        html=html,
    )

    assert probe["is_ready"] is True
    assert probe["readiness_terminal_state"] == "ready"
    assert probe["listing_card_count"] == 2
    assert probe["listing_card_diagnostics"]["card_count"] == 2
    assert probe["listing_card_diagnostics"]["admitted_count"] == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "text",
    ["Loading results, please wait", "Search jobs", "Continue this page in the app"],
)
async def test_listing_shells_are_observations_not_ready(text: str) -> None:
    probe = await probe_browser_readiness(
        _Page("https://jobs.test/search"),
        url="https://jobs.test/search",
        surface="job_listing",
        html=f"<html><body><main>{text}</main></body></html>",
    )

    assert probe["is_ready"] is False
    assert probe["ready_empty"] is False
    assert probe["shell_detected"] is True
    assert probe["readiness_terminal_state"] == "shell_rejected"


@pytest.mark.asyncio
async def test_surface_aware_no_results_is_terminal_ready_empty() -> None:
    probe = await probe_browser_readiness(
        _Page("https://jobs.test/search"),
        url="https://jobs.test/search",
        surface="job_listing",
        html="<html><body><main>No open positions</main></body></html>",
    )

    assert probe["is_ready"] is True
    assert probe["ready_empty"] is True
    assert probe["listing_card_count"] == 0
    assert probe["readiness_terminal_state"] == "ready_empty"


@pytest.mark.asyncio
async def test_listing_readiness_timeout_is_bounded_terminal_failure() -> None:
    class TimeoutPage(_Page):
        async def wait_for_selector(self, *args, **kwargs):
            raise PlaywrightTimeoutError("bounded timeout")

    result = await wait_for_listing_readiness(
        TimeoutPage("https://jobs.test/search"),
        "https://jobs.test/search",
        override={"selectors": ["article"], "max_wait_ms": 10},
    )

    assert result["status"] == "timed_out"
    assert result["terminal_state"] == "timed_out"
    assert result["is_ready"] is False

