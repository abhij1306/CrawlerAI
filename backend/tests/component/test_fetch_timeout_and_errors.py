"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    AsyncMock,
    BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET,
    HostProtectionPolicy,
    PageFetchResult,
    _as_async,
    _default_fetch_context,
    asyncio,
    crawl_fetch_runtime,
    httpx,
    pytest,
    time,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_uses_remaining_timeout_budget_across_http_and_browser_retries(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_retry_min_remaining_seconds=0.0)
    url = "https://example.com/products/widget"
    browser_timeouts: list[float] = []

    @_as_async
    def _load_policy(*_args, **_kwargs):
        return HostProtectionPolicy(host="example.com")

    async def _vendor_blocked_curl(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
        cookie_header: str | None = None,
    ):
        del proxy, cookie_header
        await asyncio.sleep(0.06)
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>blocked</body></html>",
            status_code=403,
            method="curl_cffi",
            blocked=True,
            headers={"x-datadome": "blocked"},
        )

    async def _browser_fetch(request_url: str, browser_budget: float, **kwargs):
        del request_url
        browser_timeouts.append(browser_budget)
        engine = str(kwargs.get("browser_engine") or "")
        if engine == "patchright":
            await asyncio.sleep(0.06)
            raise TimeoutError("patchright budget exhausted")
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_engine": engine,
                "host_policy_snapshot": dict(kwargs.get("host_policy_snapshot") or {}),
            },
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        _load_policy,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_post_block_cooldown_ms",
        0,
    )

    result = await crawl_fetch_runtime.fetch_page(
        url,
        timeout_seconds=0.2,
        surface="ecommerce_detail",
    )

    assert result.browser_diagnostics["browser_engine"] == "real_chrome"
    assert browser_timeouts[0] < 0.16
    assert browser_timeouts[1] < browser_timeouts[0]


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_caps_patchright_probe_timeout_for_vendor_block(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_vendor_block_probe_timeout_seconds=12.0)
    browser_calls: list[tuple[str, float]] = []
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=30.0,
        deadline_monotonic=time.perf_counter() + 30.0,
        run_id=None,
        surface="ecommerce_detail",
        traversal_mode=None,
        max_pages=1,
        max_scrolls=1,
        max_records=None,
        on_event=None,
        browser_reason=None,
        requested_fields=[],
        listing_recovery_mode=None,
        proxies=[None],
        proxy_profile={},
        traversal_required=False,
        fetch_mode="browser_only",
        runtime_policy={},
        host_memory_ttl_seconds=crawl_fetch_runtime.crawler_runtime_settings.coerce_host_memory_ttl_seconds(
            None
        ),
    )

    @_as_async
    def _fake_browser_fetch(url: str, browser_timeout: float, **kwargs):
        del url
        engine = str(kwargs.get("browser_engine") or "")
        browser_calls.append((engine, browser_timeout))
        if engine == "patchright":
            raise TimeoutError("patchright budget exhausted")
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": engine},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="example.com",
                patchright_blocked=True,
                prefer_browser=True,
                last_block_vendor="datadome",
            )
        ),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_post_block_cooldown_ms",
        0,
    )

    result = await crawl_fetch_runtime.run_browser_attempts(
        context,
        reason="vendor-block:datadome",
        host_policy=HostProtectionPolicy(
            host="example.com",
            patchright_blocked=True,
            prefer_browser=True,
            last_block_vendor="datadome",
        ),
    )

    assert result.browser_diagnostics["browser_engine"] == "real_chrome"
    assert browser_calls[0][0] == "patchright"
    assert browser_calls[0][1] == pytest.approx(12.0, abs=0.05)
    assert browser_calls[1][0] == "real_chrome"
    assert browser_calls[1][1] < 30.0


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_does_not_cap_patchright_just_because_real_chrome_is_queued(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_vendor_block_probe_timeout_seconds=12.0)
    browser_calls: list[tuple[str, float]] = []
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=30.0,
        deadline_monotonic=time.perf_counter() + 30.0,
        run_id=None,
        surface="ecommerce_detail",
        traversal_mode=None,
        max_pages=1,
        max_scrolls=1,
        max_records=None,
        on_event=None,
        browser_reason=None,
        requested_fields=[],
        listing_recovery_mode=None,
        proxies=[None],
        proxy_profile={},
        traversal_required=False,
        fetch_mode="browser_only",
        runtime_policy={},
        host_memory_ttl_seconds=crawl_fetch_runtime.crawler_runtime_settings.coerce_host_memory_ttl_seconds(
            None
        ),
    )

    @_as_async
    def _fake_browser_fetch(url: str, browser_timeout: float, **kwargs):
        del url
        engine = str(kwargs.get("browser_engine") or "")
        browser_calls.append((engine, browser_timeout))
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": engine},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    fresh_policy = HostProtectionPolicy(host="example.com")
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=fresh_policy),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_post_block_cooldown_ms",
        0,
    )

    result = await crawl_fetch_runtime.run_browser_attempts(
        context,
        reason="vendor-block:cloudflare",
        host_policy=fresh_policy,
    )

    assert result.browser_diagnostics["browser_engine"] == "patchright"
    assert browser_calls[0][0] == "patchright"
    assert browser_calls[0][1] > 12.1
    # Real Chrome must not be called when patchright succeeds.
    assert len(browser_calls) == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_patchright_probe_cap_bounds_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        browser_vendor_block_probe_timeout_seconds=0.01,
        browser_post_block_cooldown_ms=0,
    )
    browser_calls: list[tuple[str, float]] = []
    context = _default_fetch_context()
    context.resolved_timeout = 0.12
    context.deadline_monotonic = time.perf_counter() + 0.12

    async def _fake_browser_fetch(url: str, browser_timeout: float, **kwargs):
        del url
        engine = str(kwargs.get("browser_engine") or "")
        browser_calls.append((engine, browser_timeout))
        if engine == "patchright":
            await asyncio.sleep(0.08)
            raise TimeoutError("patchright hidden launch exceeded probe budget")
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": engine},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="example.com",
                patchright_blocked=True,
                prefer_browser=True,
                last_block_vendor="cloudflare",
            )
        ),
    )

    result = await crawl_fetch_runtime.run_browser_attempts(
        context,
        reason="vendor-block:cloudflare",
        host_policy=HostProtectionPolicy(
            host="example.com",
            patchright_blocked=True,
            prefer_browser=True,
            last_block_vendor="cloudflare",
        ),
    )

    assert result.browser_diagnostics["browser_engine"] == "real_chrome"
    assert browser_calls[0][0] == "patchright"
    assert browser_calls[0][1] == pytest.approx(0.01, abs=0.01)
    assert browser_calls[1][0] == "real_chrome"
    assert browser_calls[1][1] > 0.06


@pytest.mark.component
def test_browser_attempt_timeout_skips_patchright_probe_cap_without_vendor(
    patch_settings,
) -> None:
    patch_settings(browser_vendor_block_probe_timeout_seconds=1.0)
    context = _default_fetch_context()

    timeout_seconds = crawl_fetch_runtime._browser_attempt_timeout_seconds(
        context=context,
        reason="vendor-block:",
        browser_engine="patchright",
        engine_index=0,
        engine_attempts=["patchright", "real_chrome"],
        host_policy=HostProtectionPolicy(
            host="example.com",
            patchright_blocked=True,
            prefer_browser=True,
            last_block_vendor="datadome",
        ),
    )

    assert timeout_seconds > 1.5


@pytest.mark.component
def test_browser_attempt_timeout_does_not_cap_patchright_when_real_chrome_is_only_queued(
    patch_settings,
) -> None:
    patch_settings(browser_vendor_block_probe_timeout_seconds=1.0)
    context = _default_fetch_context()

    timeout_seconds = crawl_fetch_runtime._browser_attempt_timeout_seconds(
        context=context,
        reason="vendor-block:akamai",
        browser_engine="patchright",
        engine_index=0,
        engine_attempts=["patchright", "real_chrome"],
        host_policy=HostProtectionPolicy(host="example.com"),
    )

    assert timeout_seconds > 1.5


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_returns_http_result_when_browser_escalation_budget_is_too_low(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(browser_retry_min_remaining_seconds=20.0)
    url = "https://example.com/products/widget"
    browser_calls: list[float] = []

    @_as_async
    def _blocked_http(
        request_url: str,
        timeout: float,
        *,
        proxy: str | None = None,
        cookie_header: str | None = None,
    ):
        del timeout, proxy, cookie_header
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
    def _unexpected_browser(request_url: str, browser_timeout: float, **_kwargs):
        del request_url
        browser_calls.append(browser_timeout)
        raise AssertionError("browser should not start with insufficient budget")

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _blocked_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _unexpected_browser)
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "note_host_hard_block", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime, "apply_protected_host_backoff", AsyncMock()
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())

    result = await crawl_fetch_runtime.fetch_page(
        url,
        timeout_seconds=2.0,
        surface="ecommerce_detail",
    )

    assert result.method == "curl_cffi"
    assert result.blocked is True
    assert browser_calls == []
    assert result.browser_diagnostics["browser_escalation_skipped"] == (
        BROWSER_ESCALATION_SKIPPED_INSUFFICIENT_BUDGET
    )
    crawl_fetch_runtime._update_host_result_memory.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_skips_cookie_handoff_when_proxy_identity_would_drift(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://example.com/products/widget"
    browser_calls: list[str | None] = []

    @_as_async
    def _unexpected_export(*_args, **_kwargs):
        raise AssertionError("proxy handoff must not reuse unscoped domain cookies")

    @_as_async
    def _browser_ok(request_url, timeout, **kwargs):
        del request_url, timeout
        browser_calls.append(kwargs.get("proxy"))
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body>Rendered</body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={"browser_engine": "real_chrome"},
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
        _unexpected_export,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_ok)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["real_chrome"],
    )
    try:
        result = await crawl_fetch_runtime.fetch_page(
            url,
            surface="ecommerce_detail",
            proxy_list=["http://proxy-a"],
        )
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert result.method == "browser"
    assert browser_calls == ["http://proxy-a"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_prefers_browser_after_hard_blocked_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await crawl_fetch_runtime.reset_fetch_runtime_state()
    url = "https://wellfound.com/location/united-states"
    curl_calls: list[str] = []
    browser_reasons: list[str | None] = []
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
    def _browser_blocked(request_url, timeout, **kwargs):
        del timeout
        browser_reasons.append(kwargs.get("browser_reason"))
        return PageFetchResult(
            url=request_url,
            final_url=request_url,
            html="<html><body>still blocked</body></html>",
            status_code=403,
            method="browser",
            blocked=True,
        )

    @_as_async
    def _fake_load_policy(url: str, *, session=None, ttl_seconds=None):
        del url, session, ttl_seconds
        return learned_policy

    @_as_async
    def _fake_note_host_hard_block(value: str | None, **kwargs):
        del value, kwargs
        nonlocal learned_policy
        learned_policy = HostProtectionPolicy(host="wellfound.com", prefer_browser=True)
        return learned_policy

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _vendor_blocked_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _browser_blocked)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright"],
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
        first = await crawl_fetch_runtime.fetch_page(url, surface="job_listing")
        second = await crawl_fetch_runtime.fetch_page(url, surface="job_listing")
    finally:
        await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert first.method == "browser"
    assert second.method == "browser"
    assert first.blocked is True
    assert second.blocked is True
    assert curl_calls == [url]
    assert browser_reasons == ["vendor-block:datadome", "host-preference"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_fetch_surfaces_dns_failure_without_hidden_ipv4_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _SharedClient:
        @_as_async
        def get(self, url: str, **kwargs):
            del url, kwargs
            raise OSError(11001, "getaddrinfo failed")

    @_as_async
    def _fake_get_shared_http_client(*, proxy: str | None = None):
        del proxy
        return _SharedClient()

    monkeypatch.setattr(
        crawl_fetch_runtime, "_get_shared_http_client", _fake_get_shared_http_client
    )

    with pytest.raises(OSError, match="getaddrinfo failed"):
        await crawl_fetch_runtime._http_fetch("https://example.com/jobs", 10.0)


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_surfaces_browser_error_when_http_exhausts_and_browser_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    curl_error = httpx.ConnectError("getaddrinfo failed")
    httpx_error = httpx.ReadTimeout("httpx fallback timed out")
    browser_error = RuntimeError("browser launch failed")

    @_as_async
    def _failing_curl(url: str, timeout: float, *, proxy: str | None = None):
        del proxy
        raise curl_error

    @_as_async
    def _failing_http(url: str, timeout: float, *, proxy: str | None = None):
        del url, timeout, proxy
        raise httpx_error

    @_as_async
    def _failing_browser(url, timeout, **kwargs):
        raise browser_error

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _failing_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _failing_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _failing_browser)

    with pytest.raises(RuntimeError, match="browser launch failed") as excinfo:
        await crawl_fetch_runtime.fetch_page("https://paycomonline.net/career-page")

    assert excinfo.value.__cause__ is httpx_error
    assert excinfo.value.browser_diagnostics["browser_attempted"] is True
    assert excinfo.value.browser_diagnostics["browser_outcome"] == "navigation_failed"
    assert excinfo.value.browser_diagnostics["failure_kind"] == "navigation_error"


@pytest.mark.asyncio
@pytest.mark.component
async def test_reset_fetch_runtime_state_closes_canonical_runtime_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    @_as_async
    def _fake_shutdown_browser_runtime() -> None:
        calls.append("browser")

    @_as_async
    def _fake_close_runtime_http_client() -> None:
        calls.append("runtime_http")

    @_as_async
    def _fake_reset_pacing_state() -> None:
        calls.append("pacing")

    @_as_async
    def _fake_clear_cookie_store_cache() -> None:
        calls.append("cookie_store")

    monkeypatch.setattr(
        crawl_fetch_runtime,
        "shutdown_browser_runtime",
        _fake_shutdown_browser_runtime,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "clear_cookie_store_cache",
        _fake_clear_cookie_store_cache,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "reset_pacing_state",
        _fake_reset_pacing_state,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "close_shared_http_client",
        _fake_close_runtime_http_client,
    )
    await crawl_fetch_runtime.reset_fetch_runtime_state()

    assert calls == [
        "browser",
        "cookie_store",
        "pacing",
        "runtime_http",
    ]
