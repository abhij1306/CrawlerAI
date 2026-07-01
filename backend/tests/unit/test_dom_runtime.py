from __future__ import annotations

import pytest

from app.acquisition.dom_runtime import flatten_shadow_dom, get_page_html


pytestmark = pytest.mark.unit


class _FakePage:
    def __init__(self, result: object, *, fail_flatten: bool = False) -> None:
        self.result = result
        self.fail_flatten = fail_flatten
        self.evaluate_calls: list[tuple[str, object]] = []

    async def evaluate(self, script: str, arg: object = None) -> object:
        self.evaluate_calls.append((script, arg))
        if "MutationObserver" in script:
            return {"observed": False}
        if self.fail_flatten:
            raise RuntimeError("browser context closed")
        return self.result

    async def content(self) -> str:
        return "<html><body>ok</body></html>"


@pytest.mark.asyncio
async def test_flatten_shadow_dom_returns_structured_counts() -> None:
    page = _FakePage(
        {
            "shadow_roots_detected": 3,
            "shadow_roots_flattened": 2,
            "closed_shadow_roots_detected": 1,
            "hidden_panel_dom_present": True,
            "serialization_method_version": "shadow-flatten.v2",
            "max_hosts": 2,
            "errors": ["shadow_host_limit_reached"],
        }
    )

    result = await flatten_shadow_dom(page)

    assert result["shadow_roots_detected"] == 3
    assert result["shadow_roots_flattened"] == 2
    assert result["closed_shadow_roots_detected"] == 1
    assert result["hidden_panel_dom_present"] is True
    assert result["max_hosts"] == 2
    assert result["errors"] == ("shadow_host_limit_reached",)
    assert page.evaluate_calls[0][1]["markerAttr"] == "data-crawlerai-shadow-host"


@pytest.mark.asyncio
async def test_get_page_html_attaches_capture_completeness() -> None:
    page = _FakePage(
        {
            "shadow_roots_detected": 1,
            "shadow_roots_flattened": 1,
            "serialization_method_version": "shadow-flatten.v2",
        }
    )

    html = await get_page_html(page)

    assert html == "<html><body>ok</body></html>"
    assert page._crawlerai_capture_completeness["shadow_roots_flattened"] == 1
    assert any("MutationObserver" in script for script, _arg in page.evaluate_calls)


@pytest.mark.asyncio
async def test_get_page_html_does_not_wait_when_no_shadow_was_flattened() -> None:
    page = _FakePage(
        {
            "shadow_roots_detected": 0,
            "shadow_roots_flattened": 0,
            "serialization_method_version": "shadow-flatten.v2",
        }
    )

    await get_page_html(page)

    assert page._crawlerai_capture_completeness["shadow_roots_flattened"] == 0
    assert not any("MutationObserver" in script for script, _arg in page.evaluate_calls)


@pytest.mark.asyncio
async def test_flatten_shadow_dom_reports_failure() -> None:
    page = _FakePage({}, fail_flatten=True)

    result = await flatten_shadow_dom(page)

    assert result["shadow_roots_flattened"] == 0
    assert result["errors"] == ("shadow_flatten_failed",)
