"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    AsyncMock,
    HostProtectionPolicy,
    PageFetchResult,
    _as_async,
    asyncio,
    browser_policy,
    crawl_fetch_runtime,
    planned_http,
    pytest,
    time,
)


@pytest.mark.component
def test_resolve_proxy_attempts_preserves_order_and_deduplicates() -> None:
    proxies = browser_policy.resolve_proxy_attempts(
        [
            "socks5://proxy-b",
            "http://proxy-a",
            "socks5://proxy-b",
            "http://proxy-c",
        ]
    )

    assert proxies == [
        "socks5://proxy-b",
        "http://proxy-a",
        "http://proxy-c",
    ]


@pytest.mark.component
def test_attach_proxy_run_session_replaces_existing_session_marker() -> None:
    proxy = "socks5://user-session-oldvalue:pass@rp.scrapegw.com:6060"

    resolved = crawl_fetch_runtime._attach_proxy_run_session(proxy, run_id=42)

    assert resolved == "socks5://user-session-r42:pass@rp.scrapegw.com:6060"


@pytest.mark.component
def test_resolve_proxy_attempts_does_not_rewrite_proxy_session_by_default() -> None:
    proxies = browser_policy.resolve_proxy_attempts(
        [
            "socks5://user-session-oldvalue:pass@rp.scrapegw.com:6060",
            "socks5://user-session-other:pass@rp.scrapegw.com:6060",
        ],
        run_id=42,
    )

    assert proxies == [
        "socks5://user-session-oldvalue:pass@rp.scrapegw.com:6060",
        "socks5://user-session-other:pass@rp.scrapegw.com:6060",
    ]


@pytest.mark.component
def test_resolve_proxy_attempts_rewrites_proxy_session_when_explicitly_enabled() -> (
    None
):
    proxies = browser_policy.resolve_proxy_attempts(
        [
            "socks5://user-session-oldvalue:pass@rp.scrapegw.com:6060",
            "socks5://user-session-other:pass@rp.scrapegw.com:6060",
        ],
        run_id=42,
        proxy_profile={"session_rewrite_enabled": True},
    )

    assert proxies == [
        "socks5://user-session-r42:pass@rp.scrapegw.com:6060",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_browser_only_retries_proxies_in_user_order_and_stamps_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_proxies: list[str | None] = []

    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout
        proxy = kwargs.get("proxy")
        attempted_proxies.append(proxy)
        if proxy == "socks5://proxy-a":
            raise RuntimeError("proxy-a failed")
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={"browser_attempted": True},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright"],
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
        proxy_list=["socks5://proxy-a", "socks5://proxy-b", "socks5://proxy-a"],
    )

    assert attempted_proxies == ["socks5://proxy-a", "socks5://proxy-b"]
    assert result.method == "browser"
    assert result.browser_diagnostics["proxy_scheme"] == "socks5"
    assert result.browser_diagnostics["browser_proxy_mode"] == "launch"
    assert result.browser_diagnostics["proxy_attempt_index"] == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_records_driver_closed_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=5.0,
        deadline_monotonic=time.perf_counter() + 5.0,
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
    )

    class BrowserDriverError(Exception):
        pass

    @_as_async
    def _failing_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout, kwargs
        raise BrowserDriverError(
            "Page.content: Connection closed while reading from the driver"
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _failing_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())

    with pytest.raises(BrowserDriverError):
        await crawl_fetch_runtime.run_browser_attempts(
            context,
            reason="browser-only",
            host_policy=HostProtectionPolicy(host="example.com"),
        )

    assert context.last_browser_attempt_diagnostics["failure_kind"] == (
        "browser_driver_closed"
    )
    assert context.last_browser_attempt_diagnostics["browser_outcome"] == (
        "navigation_failed"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_browser_only_escalates_to_real_chrome_after_patchright_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_engines: list[str] = []

    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout
        attempted_engines.append(str(kwargs.get("browser_engine")))
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={
                "browser_engine": str(kwargs.get("browser_engine")),
                "browser_binary": "chrome.exe",
                "bridge_used": False,
                "escalation_lane": str(kwargs.get("escalation_lane")),
                "host_policy_snapshot": dict(kwargs.get("host_policy_snapshot") or {}),
            },
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="example.com",
                prefer_browser=True,
                patchright_blocked=True,
            )
        ),
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
    )

    assert attempted_engines == ["real_chrome"]
    assert result.browser_diagnostics["browser_engine"] == "real_chrome"
    assert result.browser_diagnostics["escalation_lane"] == "browser_only"
    assert (
        result.browser_diagnostics["host_policy_snapshot"]["patchright_blocked"] is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_browser_only_escalates_to_real_chrome_for_commerce_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_engines: list[str] = []

    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout
        attempted_engines.append(str(kwargs.get("browser_engine")))
        return PageFetchResult(
            url="https://shop.example.com/products/widget",
            final_url="https://shop.example.com/products/widget",
            html="<html><body><main>Thread</main></body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={
                "browser_engine": str(kwargs.get("browser_engine")),
                "bridge_used": False,
                "escalation_lane": str(kwargs.get("escalation_lane")),
                "host_policy_snapshot": dict(kwargs.get("host_policy_snapshot") or {}),
            },
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="shop.example.com",
                prefer_browser=True,
                patchright_blocked=True,
            )
        ),
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://shop.example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
    )

    assert attempted_engines == ["real_chrome"]
    assert result.browser_diagnostics["browser_engine"] == "real_chrome"
    assert result.browser_diagnostics["escalation_lane"] == "browser_only"
    assert (
        result.browser_diagnostics["host_policy_snapshot"]["patchright_blocked"] is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_replans_to_real_chrome_after_same_proxy_patchright_block(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_engines: list[str] = []
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=5.0,
        deadline_monotonic=time.perf_counter() + 5.0,
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
    )

    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout
        browser_engine = str(kwargs.get("browser_engine"))
        attempted_engines.append(browser_engine)
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=browser_engine == "patchright",
            browser_diagnostics={"browser_engine": browser_engine},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            side_effect=[
                HostProtectionPolicy(
                    host="example.com",
                    patchright_blocked=True,
                    prefer_browser=True,
                ),
            ]
        ),
    )

    result = await crawl_fetch_runtime.run_browser_attempts(
        context,
        reason="browser-only",
        host_policy=HostProtectionPolicy(host="example.com"),
    )

    assert attempted_engines == ["patchright", "real_chrome"]
    assert result.browser_diagnostics["browser_engine"] == "real_chrome"


@pytest.mark.asyncio
@pytest.mark.component
async def test_vendor_block_unready_patchright_usable_content_replans_to_real_chrome(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_engines: list[str] = []
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=5.0,
        deadline_monotonic=time.perf_counter() + 5.0,
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
        fetch_mode="auto",
        runtime_policy={},
    )

    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del timeout
        browser_engine = str(kwargs.get("browser_engine"))
        attempted_engines.append(browser_engine)
        if browser_engine == "patchright":
            return PageFetchResult(
                url=url,
                final_url=url,
                html="<html><body><h1>Loading</h1></body></html>",
                status_code=200,
                method="browser",
                blocked=False,
                browser_diagnostics={
                    "browser_engine": browser_engine,
                    "browser_outcome": "usable_content",
                    "readiness_probes": [{"is_ready": False}],
                },
            )
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered product</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
            browser_diagnostics={
                "browser_engine": browser_engine,
                "browser_outcome": "usable_content",
                "readiness_probes": [{"is_ready": True}],
            },
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_real_chrome_enabled",
        True,
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "real_chrome_browser_available",
        lambda: True,
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )

    result = await crawl_fetch_runtime.run_browser_attempts(
        context,
        reason="vendor-block:akamai",
        host_policy=HostProtectionPolicy(host="example.com"),
    )

    assert attempted_engines == ["patchright", "real_chrome"]
    assert result.browser_diagnostics["browser_engine"] == "real_chrome"


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_bounds_browser_runtime_wall_clock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_engines: list[str] = []
    attempted_proxies: list[str | None] = []
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=0.03,
        deadline_monotonic=time.perf_counter() + 0.03,
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
        proxies=["http://proxy-one.test", "http://proxy-two.test"],
        proxy_profile={},
        traversal_required=False,
        fetch_mode="browser_only",
        runtime_policy={},
    )

    async def _fake_browser_fetch(url: str, stage_budget: float, **kwargs):
        del url, stage_budget
        browser_engine = str(kwargs.get("browser_engine"))
        attempted_engines.append(browser_engine)
        attempted_proxies.append(kwargs.get("proxy"))
        if browser_engine == "patchright":
            await asyncio.sleep(0.08)
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={"browser_engine": browser_engine},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())

    with pytest.raises(TimeoutError):
        await crawl_fetch_runtime.run_browser_attempts(
            context,
            reason="browser-only",
            host_policy=HostProtectionPolicy(host="example.com"),
        )

    assert attempted_engines == ["patchright"]
    assert attempted_proxies == ["http://proxy-one.test"]
    assert context.last_browser_attempt_diagnostics["browser_engine"] == "patchright"
    assert context.last_browser_attempt_diagnostics["failure_stage"] == "attempt"


@pytest.mark.component
def test_usable_browser_result_without_readiness_probes_is_ready() -> None:
    result = PageFetchResult(
        url="https://example.com/products/widget",
        final_url="https://example.com/products/widget",
        html="<html><body><h1>Widget</h1></body></html>",
        status_code=200,
        method="browser",
        blocked=False,
        browser_diagnostics={"browser_outcome": "usable_content"},
    )

    assert planned_http._browser_result_is_ready(result) is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_browser_only_stamps_engine_and_lane_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={
                "browser_engine": str(kwargs.get("browser_engine")),
                "browser_binary": "C:/Program Files/Google/Chrome/Application/chrome.exe",
                "bridge_used": True,
                "escalation_lane": str(kwargs.get("escalation_lane")),
                "host_policy_snapshot": dict(kwargs.get("host_policy_snapshot") or {}),
            },
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright"],
    )
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(
            return_value=HostProtectionPolicy(
                host="example.com",
                prefer_browser=True,
                request_blocked=True,
                last_block_vendor="datadome",
            )
        ),
    )

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
        proxy_list=["socks5://proxy-a"],
    )

    assert result.browser_diagnostics["browser_engine"] == "patchright"
    assert result.browser_diagnostics["bridge_used"] is True
    assert result.browser_diagnostics["escalation_lane"] == "browser_only_proxy"
    assert result.browser_diagnostics["host_policy_snapshot"]["prefer_browser"] is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_forwards_proxy_profile_to_browser_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_proxy_profile: dict[str, object] = {}

    @_as_async
    def _fake_browser_fetch(url: str, _timeout: float, **kwargs):
        del url, _timeout
        nonlocal captured_proxy_profile
        captured_proxy_profile = dict(kwargs.get("proxy_profile") or {})
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Widget</h1></body></html>",
            status_code=200,
            method="browser",
            browser_diagnostics={"browser_attempted": True},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/products/widget",
        surface="ecommerce_detail",
        fetch_mode="browser_only",
        proxy_list=["socks5://proxy-a"],
        proxy_profile={"enabled": True, "rotation": "rotating"},
    )

    assert result.method == "browser"
    assert captured_proxy_profile == {"enabled": True, "rotation": "rotating"}


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_browser_attempts_treats_none_cooldown_as_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempted_engines: list[str] = []
    host_policy = HostProtectionPolicy(host="example.com")
    context = crawl_fetch_runtime._FetchRuntimeContext(
        url="https://example.com/products/widget",
        resolved_timeout=5.0,
        deadline_monotonic=time.perf_counter() + 5.0,
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
    )

    @_as_async
    def _fake_browser_fetch(url: str, timeout: float, **kwargs):
        del url, timeout
        browser_engine = str(kwargs.get("browser_engine"))
        attempted_engines.append(browser_engine)
        return PageFetchResult(
            url="https://example.com/products/widget",
            final_url="https://example.com/products/widget",
            html="<html><body><h1>Rendered</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=browser_engine == "patchright",
            browser_diagnostics={},
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser_fetch)
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "_browser_engine_attempts",
        lambda **_kwargs: ["patchright", "real_chrome"],
    )
    monkeypatch.setattr(crawl_fetch_runtime, "wait_for_host_slot", AsyncMock())
    monkeypatch.setattr(crawl_fetch_runtime, "_update_host_result_memory", AsyncMock())
    monkeypatch.setattr(
        crawl_fetch_runtime,
        "load_host_protection_policy",
        AsyncMock(return_value=host_policy),
    )
    monkeypatch.setattr(
        crawl_fetch_runtime.crawler_runtime_settings,
        "browser_post_block_cooldown_ms",
        None,
    )

    result = await crawl_fetch_runtime.run_browser_attempts(
        context,
        reason="browser-only",
        host_policy=host_policy,
    )

    assert attempted_engines == ["patchright", "real_chrome"]
    assert result.method == "browser"
    assert result.blocked is False
