from __future__ import annotations

import pytest

from app.acquisition.browser_block_detection import classify_blocked_page
from app.acquisition.browser_fetch_support import suppress_new_context_openers
from app.acquisition.browser_recovery import (
    _is_solvable_interactive_challenge,
    _is_terminal_hard_block,
)

_CF_FULL = (
    "<html><head><title>Just a moment...</title></head><body>"
    '<div class="cf-browser-verification"></div>'
    "<p>Checking your browser before accessing the site.</p>"
    '<script src="/cdn-cgi/challenge-platform/v1"></script></body></html>'
)
_CF_TURNSTILE_IFRAME = (
    "<html><head><title>Just a moment...</title></head><body>"
    '<iframe src="https://challenges.cloudflare.com/cdn-cgi/turnstile" '
    'title="Cloudflare security challenge"></iframe></body></html>'
)
# First paint before the Turnstile iframe/copy fully renders: only the "Just a
# moment" interstitial title is present.
_CF_FIRST_PAINT = (
    "<html><head><title>Just a moment...</title></head><body>"
    '<div id="challenge-stage"></div>'
    '<script src="/cdn-cgi/challenge-platform/v1"></script></body></html>'
)
_AKAMAI_DENIED = (
    "<html><head><title>Access Denied</title></head><body>"
    "<h1>Access Denied</h1>"
    "<div>Reference #18 powered and protected by akamai</div></body></html>"
)


@pytest.mark.component
@pytest.mark.parametrize("html", [_CF_FULL, _CF_TURNSTILE_IFRAME, _CF_FIRST_PAINT])
def test_cloudflare_interstitial_is_solvable_not_terminal(html: str) -> None:
    classification = classify_blocked_page(html, 403)
    assert classification.blocked is True
    assert _is_solvable_interactive_challenge(classification) is True
    # Must NOT be treated as terminal — recovery has to keep waiting so the
    # Turnstile renders and gets clicked instead of bailing immediately.
    assert _is_terminal_hard_block(classification) is False


@pytest.mark.component
def test_akamai_access_denied_stays_terminal() -> None:
    classification = classify_blocked_page(_AKAMAI_DENIED, 403)
    assert classification.blocked is True
    assert _is_solvable_interactive_challenge(classification) is False
    assert _is_terminal_hard_block(classification) is True


class _FakePage:
    def __init__(self) -> None:
        self.init_scripts: list[str] = []
        self.evaluated: list[str] = []

    async def add_init_script(self, script: str) -> None:
        self.init_scripts.append(script)

    async def evaluate(self, script: str) -> None:
        self.evaluated.append(script)


@pytest.mark.asyncio
@pytest.mark.component
async def test_suppress_new_context_openers_installs_guards() -> None:
    page = _FakePage()

    await suppress_new_context_openers(page)

    assert len(page.init_scripts) == 1
    assert len(page.evaluated) == 1
    # The guard must neutralize both new-context vectors.
    assert "window.open" in page.init_scripts[0]
    assert "_self" in page.init_scripts[0]


@pytest.mark.asyncio
@pytest.mark.component
async def test_suppress_new_context_openers_is_best_effort() -> None:
    class _BrokenPage:
        async def add_init_script(self, script: str) -> None:
            raise RuntimeError("no init script support")

        async def evaluate(self, script: str) -> None:
            raise RuntimeError("no evaluate support")

    # Must not raise even when the page rejects both calls.
    await suppress_new_context_openers(_BrokenPage())
