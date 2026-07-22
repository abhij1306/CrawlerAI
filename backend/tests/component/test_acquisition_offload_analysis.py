from __future__ import annotations

import functools
from types import SimpleNamespace

import httpx
import pytest

from app.acquisition import runtime as acquisition_runtime
from app.extraction.documents import HtmlAnalysis


def _as_async(func):
    @functools.wraps(func)
    async def _wrapper(*args, **kwargs):
        return func(*args, **kwargs)

    return _wrapper


class _FakeGetClient:
    def __init__(self, response: object) -> None:
        self._response = response

    async def get(self, url: str, **_kwargs: object) -> object:
        del url
        return self._response


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_fetch_offloads_html_analysis_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    @_as_async
    def _fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "app.acquisition.runtime.asyncio.to_thread",
        _fake_to_thread,
    )

    client = _FakeGetClient(
        httpx.Response(
            200,
            text="<html><body>ok</body></html>",
            request=httpx.Request("GET", "https://example.com/products/1"),
        )
    )

    @_as_async
    def _fake_get_client(*, proxy: str | None = None):
        del proxy
        return client

    @_as_async
    def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    result = await acquisition_runtime.http_fetch(
        "https://example.com/products/1",
        5,
        get_client=_fake_get_client,
        blocked_html_checker=_not_blocked,
    )

    assert result.status_code == 200
    # sha256 + parse + visible-text walk + block/policy analysis all run in
    # the worker thread, never inline on the event loop.
    assert calls == [
        "analyze_html",
        "_content_aware_http_blocked",
        "resolve_platform_runtime_policy",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_offloads_request_and_analysis_off_event_loop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    @_as_async
    def _fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr(
        "app.acquisition.runtime.asyncio.to_thread",
        _fake_to_thread,
    )

    def _fake_curl_get_once(curl_requests, url, timeout_seconds, *, proxy=None, cookie_header=None):
        del curl_requests, timeout_seconds, proxy, cookie_header
        return SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url=url,
        )

    monkeypatch.setattr(
        "app.acquisition.runtime._curl_get_once",
        _fake_curl_get_once,
    )

    result = await acquisition_runtime.curl_fetch("https://example.com/products/1", 5)

    assert result.status_code == 200
    # The request hop and the blocking analysis/result build both run in the
    # worker thread, never inline on the event loop.
    assert calls == ["_fake_curl_get_once", "_curl_response_to_fetch_result"]


@pytest.mark.component
def test_html_analysis_computes_lowered_html_lazily() -> None:
    analysis = HtmlAnalysis.from_html(
        "<html><body><p>ShOuLd LoWeR</p></body></html>"
    )

    # The second full-page lowercase copy is only materialized on demand.
    assert analysis._lowered_html is None
    first = analysis.lowered_html
    assert "should lower" in first
    assert analysis._lowered_html is first
    assert analysis.lowered_html is first


@pytest.mark.component
def test_html_analysis_fields_are_unchanged() -> None:
    analysis = HtmlAnalysis.from_html(
        "<html><head><title>My Title</title></head>"
        "<body><h1>Heading</h1><p>visible text</p></body></html>"
    )

    assert analysis.title_text == "My Title"
    assert analysis.h1_present is True
    assert "visible text" in analysis.visible_text
    assert analysis.normalized_text == analysis.visible_text
    assert analysis.lowered_html == analysis.html.lower()
    assert analysis.matches_html(analysis.html)
