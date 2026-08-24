"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    AsyncMock,
    HostProtectionPolicy,
    PageFetchResult,
    _as_async,
    _default_fetch_context,
    crawl_fetch_runtime,
    planned_http,
    pytest,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_real_chrome_cookie_contract_tries_curl_cffi_handoff_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    calls: list[dict[str, object]] = []

    @_as_async
    def _load_cookie_storage_state(request_url, **kwargs):
        calls.append({"url": request_url, "engine": kwargs.get("browser_engine")})
        return {"cookies": [{"name": "session", "value": "ok"}]}

    @_as_async
    def _curl_fetch(
        request_url, timeout_seconds, *, proxy=None, cookie_storage_state=None
    ):
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>ok</body></html>",
            status_code=200,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _browser_unexpected(*_args, **_kwargs):
        raise AssertionError("browser should not run when handoff succeeds")

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=HostProtectionPolicy(host="example.com")),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "export_cookie_storage_state_for_domain",
        _load_cookie_storage_state,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _curl_fetch)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_unexpected)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        AsyncMock(return_value=False),
    )

    result = await crawl_fetch_runtime.fetch_page(
        url,
        surface="ecommerce_detail",
        prefer_curl_handoff=True,
        handoff_cookie_engine="real_chrome",
        forced_browser_engine="real_chrome",
    )

    assert result.method == "curl_cffi"
    assert result.browser_diagnostics["browser_http_handoff"] is True
    assert calls == [{"url": url, "engine": "real_chrome"}]


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_handoff_failure_falls_back_to_real_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    engines: list[str] = []

    @_as_async
    def _load_cookie_storage_state(*_args, **_kwargs):
        return {"cookies": [{"name": "session", "value": "bad"}]}

    @_as_async
    def _curl_fetch(
        request_url, timeout_seconds, *, proxy=None, cookie_storage_state=None
    ):
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
        )

    @_as_async
    def _browser_fetch(request_url, timeout_seconds, **kwargs):
        engines.append(str(kwargs.get("browser_engine")))
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>rendered</body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={"browser_engine": kwargs.get("browser_engine")},
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=HostProtectionPolicy(host="example.com")),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "export_cookie_storage_state_for_domain",
        _load_cookie_storage_state,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _curl_fetch)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_fetch)

    result = await crawl_fetch_runtime.fetch_page(
        url,
        surface="ecommerce_detail",
        prefer_curl_handoff=True,
        handoff_cookie_engine="real_chrome",
        forced_browser_engine="real_chrome",
    )

    assert result.method == "browser"
    assert engines == ["real_chrome"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_preserves_requested_fields_on_http_to_browser_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requested_fields: list[str] = []

    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _fake_should_escalate(*args, **kwargs):
        del args, kwargs
        return True

    @_as_async
    def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        proxies: list[str | None] | None = None,
        **_kwargs,
    ):
        del (
            context,
            reason,
            listing_recovery_mode,
            proxies,
            _kwargs,
        )
        nonlocal captured_requested_fields
        captured_requested_fields = list(requested_fields or [])
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_should_escalate_to_browser_async",
        _fake_should_escalate,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "run_browser_attempts",
        _fake_run_browser_attempts,
    )

    await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=["product measurements"],
    )

    assert captured_requested_fields == ["product measurements"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_preserves_requested_fields_on_browser_first_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_requested_fields: list[str] = []

    @_as_async
    def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        proxies: list[str | None] | None = None,
        **_kwargs,
    ):
        del (
            context,
            reason,
            listing_recovery_mode,
            proxies,
            _kwargs,
        )
        nonlocal captured_requested_fields
        captured_requested_fields = list(requested_fields or [])
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "run_browser_attempts",
        _fake_run_browser_attempts,
    )

    await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        prefer_browser=True,
        requested_fields=["product measurements"],
    )

    assert captured_requested_fields == ["product measurements"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_does_not_use_browser_first_for_detail_requested_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    browser_called = False
    http_called = False

    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del url, timeout_seconds, proxy
        nonlocal http_called
        http_called = True
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html=(
                "<html><head><script type='application/ld+json'>"
                '{"@context":"https://schema.org","@type":"Product",'
                '"name":"Widget","offers":{"price":"19.99","priceCurrency":"USD"}}'
                "</script></head><body><h1>Widget</h1></body></html>"
            ),
            status_code=200,
            method="curl_cffi",
        )

    @_as_async
    def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        proxies: list[str | None] | None = None,
        **_kwargs,
    ):
        del (
            context,
            listing_recovery_mode,
            proxies,
            _kwargs,
        )
        del requested_fields, reason
        nonlocal browser_called
        browser_called = True
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "run_browser_attempts",
        _fake_run_browser_attempts,
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=["CAS Number", "Molecular Formula"],
    )

    assert result.method == "curl_cffi"
    assert http_called is True
    assert browser_called is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_prefer_browser_falls_back_to_http_after_browser_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    @_as_async
    def _failing_browser(*_args, **_kwargs):
        calls.append("browser")
        raise TimeoutError("Page.goto: Timeout 15000ms exceeded")

    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        calls.append("curl")
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="curl_cffi",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "run_browser_attempts", _failing_browser)
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)

    result = await crawl_fetch_runtime.fetch_page(
        "https://www.harrods.com/en-gb/p/widget",
        surface="ecommerce_detail",
        prefer_browser=True,
    )

    assert calls == ["browser", "curl"]
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_forced_browser_only_never_falls_back_to_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    @_as_async
    def _failing_browser(*_args, **_kwargs):
        calls.append("browser")
        raise TimeoutError("real Chrome attempt timed out")

    @_as_async
    def _unexpected_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del url, timeout_seconds, proxy
        calls.append("curl")
        raise AssertionError("targeted browser-only retry must not fall back to HTTP")

    monkeypatch.setattr(crawl_fetch_runtime, "run_browser_attempts", _failing_browser)
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _unexpected_curl)

    with pytest.raises(TimeoutError, match="real Chrome attempt timed out"):
        await crawl_fetch_runtime.fetch_page(
            "https://www.mytheresa.com/int/en/women/product",
            surface="ecommerce_detail",
            fetch_mode="browser_only",
            prefer_browser=True,
            forced_browser_engine="real_chrome",
        )

    assert calls == ["browser"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_kitchenaid_prefer_browser_timeout_falls_back_to_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    url = "https://www.kitchenaid.com/countertop-appliances/food-processors/processors/p.13-cup-food-processor.KFP1318CU.html"

    @_as_async
    def _failing_browser(*_args, **_kwargs):
        calls.append("browser")
        raise TimeoutError("Browser navigation stage exceeded timeout_seconds=45.00")

    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        calls.append("curl")
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>13 Cup Food Processor</h1></body></html>",
            status_code=200,
            method="curl_cffi",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "run_browser_attempts", _failing_browser)
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)

    result = await crawl_fetch_runtime.fetch_page(
        url,
        surface="ecommerce_detail",
        prefer_browser=True,
    )

    assert calls == ["browser", "curl"]
    assert result.method == "curl_cffi"


@pytest.mark.asyncio
@pytest.mark.component
async def test_handle_http_result_retries_browser_after_browser_first_failure_and_block(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_retry_min_remaining_seconds=0.0)
    context = _default_fetch_context()
    context.fetch_mode = "auto"
    context.browser_first_failed = True
    context.last_browser_attempt_diagnostics = {"failure_kind": "timeout"}
    browser_calls: list[list[str]] = []

    async def _fake_run_browser_attempts(*_args, **kwargs):
        browser_calls.append(list(kwargs.get("requested_fields") or []))
        return PageFetchResult(
            url=context.url,
            final_url=context.url,
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": "patchright"},
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "run_browser_attempts",
        _fake_run_browser_attempts,
    )
    monkeypatch.setattr(
        planned_http,
        "browser_escalation_allowed",
        lambda **_kwargs: True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime, "apply_protected_host_backoff", AsyncMock()
    )
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=HostProtectionPolicy(host="example.com")),
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())

    result, vendor_block_confirmed = await crawl_fetch_runtime._handle_http_result(
        context,
        result=PageFetchResult(
            url=context.url,
            final_url=context.url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
        ),
        proxy=None,
    )

    assert isinstance(result, PageFetchResult)
    assert result.method == "browser"
    assert vendor_block_confirmed is False
    assert browser_calls == [[]]


@pytest.mark.asyncio
@pytest.mark.component
async def test_vendor_block_remains_blocked_when_browser_never_becomes_ready(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_retry_min_remaining_seconds=0.0)
    context = _default_fetch_context()
    context.fetch_mode = "auto"

    async def _fake_browser(*_args, **_kwargs):
        return PageFetchResult(
            url=context.url,
            final_url=context.url,
            html="<html><body>challenge shell</body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_outcome": "usable_content",
                "readiness_probes": [{"is_ready": False, "detail_like": False}],
            },
        )

    monkeypatch.setattr(
        planned_http, "vendor_confirmed_block", lambda _result: "akamai"
    )
    monkeypatch.setattr(
        planned_http, "browser_escalation_allowed", lambda **_kwargs: True
    )
    monkeypatch.setattr(crawl_fetch_runtime, "run_browser_attempts", _fake_browser)
    monkeypatch.setattr(
        crawl_fetch_runtime, "apply_protected_host_backoff", AsyncMock()
    )
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=HostProtectionPolicy(host="example.com")),
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())

    result, vendor_block_confirmed = await crawl_fetch_runtime._handle_http_result(
        context,
        result=PageFetchResult(
            url=context.url,
            final_url=context.url,
            html="blocked",
            status_code=200,
            method="curl_cffi",
        ),
        proxy=None,
    )

    assert isinstance(result, PageFetchResult)
    assert result.blocked is True
    assert vendor_block_confirmed is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_browser_only_skips_http_fetchers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _unexpected_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        raise AssertionError(
            f"curl should not run for browser_only: {url} {timeout_seconds} {proxy}"
        )

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser</body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _unexpected_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
    )

    assert result.method == "browser"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_http_only_disables_browser_escalation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _fake_should_escalate(*args, **kwargs):
        del args, kwargs
        return True

    @_as_async
    def _unexpected_browser(url, timeout, **kwargs):
        raise AssertionError(
            f"browser should not run for http_only: {url} {timeout} {kwargs}"
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime, "_should_escalate_to_browser_async", _fake_should_escalate
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="http_only",
    )

    assert result.method == "curl_cffi"
    assert result.status_code == 403


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_http_then_browser_escalates_after_http_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>challenge</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _fake_should_escalate(*args, **kwargs):
        del args, kwargs
        return True

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser</body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime, "_should_escalate_to_browser_async", _fake_should_escalate
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="http_then_browser",
    )

    assert result.method == "browser"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_prefers_browser_from_learned_host_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _unexpected_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        raise AssertionError(
            f"http should be skipped for learned browser-first host: {url} {timeout_seconds} {proxy}"
        )

    @_as_async
    def _fake_load_policy(url: str, *, session=None, ttl_seconds=None):
        del session, ttl_seconds
        return HostProtectionPolicy(host="example.com", prefer_browser=True)

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>browser</body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _unexpected_curl)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        _fake_load_policy,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_preserves_proxy_list_on_browser_first_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_proxies: list[str | None] | None = None

    @_as_async
    def _fake_run_browser_attempts(
        context,
        *,
        reason: str,
        requested_fields: list[str] | None = None,
        listing_recovery_mode: str | None = None,
        proxies: list[str | None] | None = None,
        **_kwargs,
    ):
        del (
            context,
            reason,
            requested_fields,
            listing_recovery_mode,
            _kwargs,
        )
        nonlocal captured_proxies
        captured_proxies = list(proxies or [])
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
        )

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "run_browser_attempts",
        _fake_run_browser_attempts,
    )

    await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        prefer_browser=True,
        proxy_list=["http://proxy-one", "http://proxy-two"],
    )

    assert (captured_proxies or []) == ["http://proxy-one", "http://proxy-two"]
