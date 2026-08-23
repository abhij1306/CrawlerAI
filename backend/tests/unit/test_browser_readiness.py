from __future__ import annotations

import pytest
from patchright.async_api import TimeoutError as PlaywrightTimeoutError

from app.acquisition.browser_readiness import (
    probe_browser_readiness,
    wait_for_listing_readiness,
)
from app.acquisition.browser_page_helpers import ready_probe_supports_fast_finalize

pytestmark = pytest.mark.unit


class _Page:
    def __init__(self, url: str) -> None:
        self.url = url

    def locator(self, _selector: str):
        return self

    async def count(self) -> int:
        return 0


@pytest.mark.parametrize("status_code", (404, 500, 503))
def test_verified_extractability_does_not_fast_finalize_http_errors(
    status_code: int,
) -> None:
    assert (
        ready_probe_supports_fast_finalize(
            [],
            surface="ecommerce_detail",
            status_code=status_code,
            expansion_diagnostics={
                "extractability": {
                    "verified": True,
                    "matched_requested_fields": ["title"],
                }
            },
        )
        is False
    )


def test_verified_extractability_fast_finalizes_successful_response() -> None:
    assert (
        ready_probe_supports_fast_finalize(
            [],
            surface="ecommerce_detail",
            status_code=200,
            expansion_diagnostics={
                "extractability": {
                    "verified": True,
                    "extractable_fields": ["title"],
                }
            },
        )
        is True
    )


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
    ["Loading results, please wait", "Continue this page in the app"],
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
async def test_permanent_search_chrome_is_not_a_shell() -> None:
    # Finding 3: "Search jobs" is permanent search-UI chrome that coexists with
    # legitimate empty results. It must NOT shell-reject the page — the probe
    # keeps observing (no cards, no no-results text) instead of terminally
    # rejecting a page that could still settle into a valid empty result.
    probe = await probe_browser_readiness(
        _Page("https://jobs.test/search"),
        url="https://jobs.test/search",
        surface="job_listing",
        html="<html><body><main>Search jobs</main></body></html>",
    )

    assert probe["is_ready"] is False
    assert probe["shell_detected"] is False
    assert probe["readiness_terminal_state"] == "observing"


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
async def test_loading_shell_with_stale_no_results_text_is_not_ready_empty() -> None:
    # A loading SPA can carry stale "no jobs found" copy while the shell is
    # still hydrating. Shell evidence must override the broad no-results match
    # so the page is NOT fast-finalized as terminal-empty.
    probe = await probe_browser_readiness(
        _Page("https://jobs.test/search"),
        url="https://jobs.test/search",
        surface="job_listing",
        html=(
            "<html><body><main>Loading results, please wait."
            " No jobs found</main></body></html>"
        ),
    )

    assert probe["shell_detected"] is True
    assert probe["ready_empty"] is False
    assert probe["is_ready"] is False
    assert probe["readiness_terminal_state"] == "shell_rejected"


@pytest.mark.asyncio
async def test_shadow_dom_board_counts_rendered_fragments_like_extraction() -> None:
    # The top-level HTML is a JS shell; cards exist only in the rendered
    # fragment capture that extraction reads via LISTING_HTML_ARTIFACT_IDS.
    # Readiness must count that same artifact set instead of reporting 0.
    fragment = (
        '<div class="job"><a href="/careers/positions/301">Staff Engineer</a>'
        "<span>Remote</span></div>"
        '<div class="job"><a href="/careers/positions/302">QA Engineer</a>'
        "<span>Sydney</span></div>"
        '<div class="job"><a href="/careers/positions/303">Designer role</a>'
        "<span>Tokyo</span></div>"
    )

    class FragmentPage(_Page):
        async def evaluate(self, _script, _args=None):
            return [fragment]

    probe = await probe_browser_readiness(
        FragmentPage("https://careers.acme.test/jobs"),
        url="https://careers.acme.test/jobs",
        surface="job_listing",
        html="<html><body><div id='root'></div></body></html>",
    )

    assert probe["listing_card_count"] == 3
    assert probe["is_ready"] is True
    assert probe["readiness_terminal_state"] == "ready"


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
