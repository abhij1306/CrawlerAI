"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    AsyncMock,
    HostProtectionPolicy,
    PageFetchResult,
    PlaywrightError,
    _as_async,
    crawl_fetch_runtime,
    httpx,
    pytest,
)
from app.acquisition.events import AcquisitionEvent, AcquisitionEventKind


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_requires_a_timeout_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "acquisition_attempt_timeout_seconds",
        None,
    )

    with pytest.raises(ValueError, match="fetch_page requires timeout_seconds"):
        await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall("https://example.com/products/widget")
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_learns_browser_first_after_vendor_blocked_http_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://wellfound.com/location/united-states"
    curl_calls: list[str] = []
    browser_reasons: list[str | None] = []
    policy_loads: list[str] = []
    learned_policy = HostProtectionPolicy(host="wellfound.com")

    @_as_async
    def _vendor_blocked_curl(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
    ):
        del timeout, proxy
        curl_calls.append(request_url)
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
            headers={"x-datadome": "blocked"},
        )

    @_as_async
    def _browser_ok(request):
        browser_reasons.append(request.browser_reason)
        return PageFetchResult(
            url=request.url,
            final_url=request.url,
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    @_as_async
    def _fake_load_policy(request_url: str, *, session=None, ttl_seconds=None):
        del session, ttl_seconds
        policy_loads.append(request_url)
        return learned_policy

    @_as_async
    def _fake_note_host_hard_block(value: str | None, **kwargs):
        del value, kwargs
        nonlocal learned_policy
        learned_policy = HostProtectionPolicy(host="wellfound.com", prefer_browser=True)
        return learned_policy

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_ok)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        _fake_load_policy,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "note_host_hard_block",
        _fake_note_host_hard_block,
    )
    try:
        first = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(url, surface="job_listing")
        )
        second = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(url, surface="job_listing")
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert first.method == "browser"
    assert second.method == "browser"
    assert curl_calls == [url]
    assert policy_loads == [url, url, url]
    assert browser_reasons == ["vendor-block:datadome", "host-preference"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_learns_browser_first_after_rate_limit_http_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    curl_calls: list[str] = []
    browser_reasons: list[str | None] = []
    learned_policy = HostProtectionPolicy(host="example.com")

    @_as_async
    def _rate_limited_curl(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
    ):
        del timeout, proxy
        curl_calls.append(request_url)
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>rate limited</body></html>",
            status_code=429,
            method="curl_cffi",
            blocked=True,
        )

    @_as_async
    def _browser_ok(request):
        browser_reasons.append(request.browser_reason)
        return PageFetchResult(
            url=request.url,
            final_url=request.url,
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": "real_chrome"},
        )

    @_as_async
    def _fake_load_policy(url: str, *, session=None, ttl_seconds=None):
        del url, session, ttl_seconds
        return learned_policy

    @_as_async
    def _fake_note_host_hard_block(value: str | None, **kwargs):
        del value, kwargs
        nonlocal learned_policy
        learned_policy = HostProtectionPolicy(host="example.com", prefer_browser=True)
        return learned_policy

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _rate_limited_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_ok)
    monkeypatch.setattr(
        crawl_fetch_runtime, "try_browser_http_handoff", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        _fake_load_policy,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "note_host_hard_block",
        _fake_note_host_hard_block,
    )
    try:
        first = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(url, surface="ecommerce_detail")
        )
        second = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(url, surface="ecommerce_detail")
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert first.method == "browser"
    assert second.method == "browser"
    assert curl_calls == [url]
    assert browser_reasons == ["http-escalation", "host-preference"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_uses_cookie_handoff_before_browser_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    curl_calls: list[dict[str, object]] = []

    @_as_async
    def _fake_load_cookie_storage_state(request_url: str, **kwargs):
        assert request_url == url
        assert kwargs["browser_engine"] == "real_chrome"
        return {"cookies": [{"name": "session", "value": "ok"}]}

    @_as_async
    def _handoff_curl(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
        cookie_storage_state: dict[str, object] | None = None,
    ):
        curl_calls.append(
            {
                "url": request_url,
                "timeout": timeout,
                "proxy": proxy,
                "cookie_storage_state": cookie_storage_state,
            }
        )
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html=(
                '<html><head><script type="application/ld+json">'
                '{"@type":"Product","name":"Widget"}'
                "</script></head><body><h1>Product</h1></body></html>"
            ),
            status_code=200,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _unexpected_browser(*_args, **_kwargs):
        raise AssertionError("browser fallback should not run after handoff succeeds")

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="example.com",
                prefer_browser=True,
                real_chrome_success=True,
            )
        ),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "export_cookie_storage_state_for_domain",
        _fake_load_cookie_storage_state,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _handoff_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)
    try:
        result = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(
                url,
                surface="ecommerce_detail",
            )
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert result.method == "curl_cffi"
    assert result.browser_diagnostics["browser_http_handoff"] is True
    assert result.browser_diagnostics["handoff_cookie_engine"] == "real_chrome"
    assert curl_calls == [
        {
            "url": url,
            "timeout": 3.0,
            "proxy": None,
            "cookie_storage_state": {"cookies": [{"name": "session", "value": "ok"}]},
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_explicit_browser_preference_skips_host_handoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    browser_engines: list[str] = []

    @_as_async
    def _unexpected_load_cookie_storage_state(*_args, **_kwargs):
        raise AssertionError("explicit browser run should not export handoff cookies")

    @_as_async
    def _unexpected_curl(*_args, **_kwargs):
        raise AssertionError("explicit browser run should not use HTTP handoff")

    @_as_async
    def _browser_fetch(request):
        browser_engines.append(str(request.browser_engine))
        return PageFetchResult(
            url=request.url,
            final_url=request.url,
            html="<html><body>rendered</body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={"browser_engine": request.browser_engine},
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="example.com",
                prefer_browser=True,
                real_chrome_success=True,
            )
        ),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "export_cookie_storage_state_for_domain",
        _unexpected_load_cookie_storage_state,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _unexpected_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_fetch)
    try:
        result = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(
                url,
                surface="ecommerce_detail",
                prefer_browser=True,
                forced_browser_engine="real_chrome",
            )
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert result.method == "browser"
    assert browser_engines == ["real_chrome"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_emits_http_strategy_and_escalation_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    events: list[AcquisitionEvent] = []

    @_as_async
    def _on_event(event: AcquisitionEvent) -> None:
        events.append(event)

    @_as_async
    def _fake_curl(request_url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>thin shell</body></html>",
            status_code=200,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _fake_browser(request):
        return PageFetchResult(
            url=request.url,
            final_url=request.url,
            html="<html><body><h1>Widget Prime</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": "patchright"},
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=HostProtectionPolicy(host="example.com")),
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        AsyncMock(return_value=True),
    )
    try:
        result = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(
                url,
                surface="ecommerce_detail",
                on_event=_on_event,
            )
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert result.method == "browser"
    assert events == [
        AcquisitionEvent.strategy_selected(
            fetch_mode="auto",
            browser_first=False,
            prefer_browser=False,
            host_preference_enabled=False,
            http_timeout_seconds=10.0,
            primary_http_fetcher="curl",
            reason_code="http_first",
        ),
        AcquisitionEvent.http_attempted(
            fetcher="curl",
            timeout_seconds=10.0,
            proxy_mode="direct",
        ),
        AcquisitionEvent.browser_escalated(
            status_code=200,
            method="curl_cffi",
            reason_code="http-escalation",
        ),
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_http_only_returns_retryable_status_without_hidden_retry(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    patch_settings(force_httpx=True)
    url = "https://example.com/products/widget"
    http_attempts: list[int] = []

    @_as_async
    def _http_retryable_status(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
    ):
        del timeout, proxy
        http_attempts.append(1)
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>retry me</body></html>",
            status_code=503,
            method="httpx",
            blocked=False,
        )

    @_as_async
    def _always_escalate(*args, **kwargs):
        del args, kwargs
        return True

    @_as_async
    def _unexpected_browser(request):
        raise AssertionError(
            f"browser should not run for http_only retry path: {request}"
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _http_retryable_status)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _always_escalate,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)

    try:
        result = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(
                url,
                surface="ecommerce_detail",
                fetch_mode="http_only",
            )
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert result.method == "httpx"
    assert result.status_code == 503
    assert len(http_attempts) == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_retries_patchright_http2_protocol_error_with_real_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://www.bestbuy.com/product/widget"
    events: list[AcquisitionEvent] = []
    browser_engines: list[str] = []

    @_as_async
    def _on_event(event: AcquisitionEvent) -> None:
        events.append(event)

    @_as_async
    def _failing_curl(request_url: str, _timeout: float, *, proxy: str | None = None):
        del request_url, _timeout, proxy
        raise httpx.ReadTimeout("curl timed out")

    @_as_async
    def _failing_http(request_url: str, _timeout: float, *, proxy: str | None = None):
        del request_url, _timeout, proxy
        raise httpx.ReadTimeout("httpx timed out")

    @_as_async
    def _browser_fetch(request):
        engine = str(request.browser_engine or "")
        browser_engines.append(engine)
        if engine == "patchright":
            raise PlaywrightError(
                f"Page.goto: net::ERR_HTTP2_PROTOCOL_ERROR at {request.url}"
            )
        return PageFetchResult(
            url=request.url,
            final_url=request.url,
            html="<html><body><h1>BestBuy Widget</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_engine": engine,
                "host_policy_snapshot": dict(request.host_policy_snapshot or {}),
            },
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime, "real_chrome_browser_available", lambda: True
    )

    try:
        result = await crawl_fetch_runtime.fetch_page(
            crawl_fetch_runtime.FetchPageCall(
                url,
                surface="ecommerce_detail",
                on_event=_on_event,
            )
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert result.method == "browser"
    assert result.browser_diagnostics["browser_engine"] == "real_chrome"
    assert browser_engines == ["patchright", "real_chrome"]
    assert events[-1] == AcquisitionEvent.browser_escalated(
        status_code=0,
        method="patchright",
        reason_code="http2_protocol_error",
    )
    http_failures = [
        event for event in events if event.kind is AcquisitionEventKind.HTTP_FAILED
    ]
    assert [dict(event.facts) for event in http_failures] == [
        {"fetcher": "curl", "exception_type": "ReadTimeout"},
        {"fetcher": "httpx", "exception_type": "ReadTimeout"},
    ]
