"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    AsyncMock,
    PageFetchResult,
    _as_async,
    crawl_fetch_runtime,
    httpx,
    pytest,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_falls_back_to_httpx_after_curl_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise httpx.TooManyRedirects("redirect loop")

    http_calls: list[str] = []

    @_as_async
    def _http_success(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        http_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>http-fallback</body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _http_success)

    @_as_async
    def _no_browser_escalation(*args, **kwargs):
        del args, kwargs
        return False

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _no_browser_escalation,
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://ar.puma.com/pd/widget.html",
        surface="ecommerce_detail",
    )

    assert result.method == "httpx"
    assert http_calls == ["https://ar.puma.com/pd/widget.html"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_attempts_curl_once_before_httpx_fallback(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    patch_settings()
    curl_calls: list[int] = []
    http_calls: list[str] = []

    @_as_async
    def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        curl_calls.append(1)
        raise httpx.ConnectTimeout("timed out")

    @_as_async
    def _http_success(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        http_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>http-fallback</body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _http_success)

    @_as_async
    def _no_browser_escalation(*args, **kwargs):
        del args, kwargs
        return False

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _no_browser_escalation,
    )
    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert result.method == "httpx"
    assert len(curl_calls) == 1
    assert http_calls == ["https://example.com/products/widget"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_only_fetch_uses_canonical_plan_and_attempt_results(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    patch_settings()

    @_as_async
    def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.ConnectTimeout("curl timed out")

    @_as_async
    def _http_success(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>planned-httpx</body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _http_success)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="http_only",
    )

    canonical_result = result.acquisition_diagnostics["result"]
    assert result.method == "httpx"
    assert [attempt["outcome"] for attempt in canonical_result["attempts"]] == [
        "error",
        "success",
    ]
    assert (
        canonical_result["selected_attempt_id"]
        == canonical_result["attempts"][1]["attempt_id"]
    )
    assert result.acquisition_diagnostics["termination_reason"] == "attempt_selected"


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_only_transport_exhaustion_does_not_fall_back_to_browser(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    patch_settings()
    browser_called = False

    @_as_async
    def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.ConnectTimeout("curl timed out")

    @_as_async
    def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.ConnectError("httpx failed")

    @_as_async
    def _unexpected_browser(*args, **kwargs):
        del args, kwargs
        nonlocal browser_called
        browser_called = True
        raise AssertionError("http_only must not run a browser attempt")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(
        crawl_fetch_runtime, "run_browser_attempts", _unexpected_browser
    )

    with pytest.raises(httpx.ConnectError, match="httpx failed") as exc_info:
        await crawl_fetch_runtime.fetch_page(
            "https://example.com/products/widget",
            surface="ecommerce_detail",
            fetch_mode="http_only",
        )

    diagnostics = exc_info.value.acquisition_diagnostics
    assert diagnostics["termination_reason"] == "http_transports_exhausted"
    assert [attempt["outcome"] for attempt in diagnostics["result"]["attempts"]] == [
        "error",
        "error",
    ]
    assert browser_called is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_falls_back_to_browser_after_curl_and_httpx_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_calls: list[str] = []

    @_as_async
    def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.TooManyRedirects("redirect loop")

    @_as_async
    def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx.ConnectError("httpx failed")

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser-rendered</body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert browser_calls == ["https://example.com/products/widget"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_returns_non_retryable_404_without_browser_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>not found</body></html>",
            status_code=404,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _unexpected_browser(url, timeout, **kwargs):
        raise AssertionError(
            f"browser fallback should not run for non-retryable status {url} {timeout} {kwargs}"
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/missing-job",
        surface="job_detail",
    )

    assert result.status_code == 404
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_returns_non_retryable_404_shell_without_browser_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html=(
                "<html><body><div id='root'></div>"
                "<script></script><script></script><script></script>"
                "</body></html>"
            ),
            status_code=404,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        raise AssertionError(
            f"browser fallback should not run for non-retryable status {url} {timeout} {kwargs}"
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/missing-spa-route",
        surface="ecommerce_detail",
    )

    assert result.status_code == 404
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_retries_406_detail_shell_with_browser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>not acceptable</body></html>",
            status_code=406,
            method="curl_cffi",
            blocked=False,
        )

    browser_calls: list[str] = []

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Pragmata</h1><span>$59.99</span></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": "patchright"},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/pragmata-switch-2",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert result.status_code == 200
    assert browser_calls == ["https://example.com/products/pragmata-switch-2"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_stops_http_waterfall_after_vendor_confirmed_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curl_proxies: list[str | None] = []
    browser_proxies: list[str | None] = []

    @_as_async
    def _vendor_blocked_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout
        curl_proxies.append(proxy)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
            headers={"x-datadome": "blocked"},
        )

    @_as_async
    def _unexpected_http(url: str, timeout: float, *, proxy: str | None = None):
        raise AssertionError(
            f"http fallback should not run after vendor-confirmed block: {url} {timeout} {proxy}"
        )

    @_as_async
    def _failing_browser(url, timeout, **kwargs):
        del timeout
        browser_proxies.append(kwargs.get("proxy"))
        raise RuntimeError(f"browser failed for {url}")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _unexpected_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _failing_browser)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright"],
    )

    with pytest.raises(RuntimeError, match="browser failed"):
        await crawl_fetch_runtime.fetch_page(
            "https://example.com/products/widget",
            proxy_list=["http://proxy-a", "http://proxy-b"],
            surface="ecommerce_detail",
        )

    assert len(curl_proxies) == 1
    assert browser_proxies == ["http://proxy-b"]
