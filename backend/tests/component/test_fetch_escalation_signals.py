"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    FakeBodyResponse,
    PageFetchResult,
    SimpleNamespace,
    _as_async,
    asyncio,
    browser_background_tasks,
    browser_capture,
    crawl_fetch_runtime,
    http_fetch,
    pytest,
    read_network_payload_body,
    should_escalate_to_browser_async,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_rejects_oversized_body_before_decode() -> None:
    response = FakeBodyResponse(b"x" * 3_500_000)

    body = await read_network_payload_body(response)

    assert body.outcome == "too_large"
    assert body.body is None
    assert response.body_calls == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_accepts_small_body_when_content_length_too_large() -> (
    None
):
    response = FakeBodyResponse(
        b"x",
        headers={"content-length": "3500000"},
    )

    body = await read_network_payload_body(response)

    assert body.outcome == "read"
    assert body.body == b"x"
    assert response.body_calls == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_accepts_large_but_in_budget_body() -> None:
    response = FakeBodyResponse(b"x" * 600_000)

    body = await read_network_payload_body(response)

    assert body.outcome == "read"
    assert body.body == b"x" * 600_000
    assert response.body_calls == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_accepts_high_value_large_body_with_scaled_budget() -> (
    None
):
    response = FakeBodyResponse(
        b"x" * 3_500_000,
        url="https://example.com/products/widget/product.js",
    )

    body = await read_network_payload_body(response, surface="ecommerce_detail")

    assert body.outcome == "read"
    assert body.body == b"x" * 3_500_000
    assert response.body_calls == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_marks_closed_page_failures_explicitly() -> (
    None
):
    response = FakeBodyResponse(error=RuntimeError("Target closed"))

    result = await read_network_payload_body(response)

    assert result.outcome == "response_closed"
    assert result.body is None
    assert "RuntimeError" in str(result.error)


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_marks_generic_read_failures_explicitly() -> (
    None
):
    response = FakeBodyResponse(error=RuntimeError("socket reset"))

    result = await read_network_payload_body(response)

    assert result.outcome == "read_error"
    assert result.body is None
    assert "socket reset" in str(result.error)


@pytest.mark.asyncio
@pytest.mark.component
async def test_read_network_payload_body_maps_read_timeouts_to_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release = asyncio.Event()

    class SlowBodyResponse:
        url = "https://example.com/product.json"

        async def body(self) -> bytes:
            await release.wait()
            raise RuntimeError("Target closed")

    monkeypatch.setattr(browser_capture, "_payload_read_timeout_seconds", lambda: 0)

    result = await read_network_payload_body(SlowBodyResponse())

    assert result.outcome == "timeout"
    assert result.body is None
    release.set()
    await browser_background_tasks.drain_browser_background_tasks()


@pytest.mark.asyncio
@pytest.mark.component
async def test_should_escalate_to_browser_async_uses_thread_offload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[object] = []

    @_as_async
    def _fake_to_thread(func, *args, **kwargs):
        calls.append(func.__name__)
        return func(*args, **kwargs)

    monkeypatch.setattr("app.acquisition.runtime.asyncio.to_thread", _fake_to_thread)

    result = await should_escalate_to_browser_async(
        PageFetchResult(
            url="https://example.com",
            final_url="https://example.com",
            html="<html><body><div id='__next'></div><script></script><script></script><script></script></body></html>",
            status_code=200,
            method="httpx",
            blocked=False,
        )
    )

    assert result is True
    assert calls == ["should_escalate_to_browser"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_fetch_populates_platform_family_from_response_url() -> None:
    class _FakeClient:
        @_as_async
        def get(self, url: str, timeout: float, **kwargs) -> SimpleNamespace:
            del url, timeout, kwargs
            return SimpleNamespace(
                text="<html><body>Jobs</body></html>",
                headers={"content-type": "text/html"},
                status_code=200,
                url="https://boards.greenhouse.io/acme",
            )

    @_as_async
    def _fake_get_client(*, proxy: str | None = None):
        del proxy
        return _FakeClient()

    @_as_async
    def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    result = await http_fetch(
        "https://example.com/jobs",
        5,
        get_client=_fake_get_client,
        blocked_html_checker=_not_blocked,
    )

    assert result.platform_family == "greenhouse"


@pytest.mark.asyncio
@pytest.mark.component
async def test_http_fetch_accepts_legacy_client_builder_keyword() -> None:
    class _FakeClient:
        @_as_async
        def get(self, url: str, timeout: float, **kwargs) -> SimpleNamespace:
            del url, timeout, kwargs
            return SimpleNamespace(
                text="<html><body>ok</body></html>",
                headers={"content-type": "text/html"},
                status_code=200,
                url="https://example.com/products/widget",
            )

    @_as_async
    def _legacy_client_builder(*, proxy: str | None = None):
        assert proxy is None
        return _FakeClient()

    @_as_async
    def _not_blocked(*_args, **_kwargs) -> bool:
        return False

    result = await http_fetch(
        "https://example.com/products/widget",
        5,
        client_builder=_legacy_client_builder,
        blocked_html_checker=_not_blocked,
    )

    assert result.final_url == "https://example.com/products/widget"


@pytest.mark.asyncio
@pytest.mark.component
async def test_detail_surface_without_signals_escalates_even_when_html_is_not_a_js_shell() -> (
    None
):
    listing_shell_html = (
        "<html><body><h1>Careers</h1>"
        + "<ul>"
        + "".join(f"<li><a href='#'>Job {index}</a></li>" for index in range(20))
        + "</ul>"
        + "<p>"
        + ("Lots of visible non-detail copy. " * 30)
        + "</p>"
        + "</body></html>"
    )
    result = PageFetchResult(
        url="https://ats.example.com/careers?ShowJob=123",
        final_url="https://ats.example.com/careers?ShowJob=123",
        html=listing_shell_html,
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="job_detail") is True
    assert (
        await should_escalate_to_browser_async(result, surface="job_listing") is False
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_should_escalate_to_browser_async_uses_runtime_policy_for_missing_detail_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.acquisition.runtime.resolve_platform_runtime_policy",
        lambda url, html="", *, surface=None: {
            "family": None,
            "requires_browser": False,
            "proxy_policy": None,
            "http_browser_escalation": {
                "js_shell_without_detail_signals": False,
                "missing_detail_signals": False,
                "listing_shell_without_listing_signals": False,
            },
        },
    )
    result = PageFetchResult(
        url="https://ats.example.com/careers?ShowJob=123",
        final_url="https://ats.example.com/careers?ShowJob=123",
        html=(
            "<html><body><h1>Careers</h1>"
            + "<ul>"
            + "".join(f"<li><a href='#'>Job {index}</a></li>" for index in range(20))
            + "</ul>"
            + "<p>"
            + ("Lots of visible non-detail copy. " * 30)
            + "</p>"
            + "</body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert await should_escalate_to_browser_async(result, surface="job_detail") is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_listing_hash_router_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://practicesoftwaretesting.com/#/",
        final_url="https://practicesoftwaretesting.com/#/",
        html=(
            "<html><body><div id='root'></div>"
            "<script></script><script></script><script></script>"
            "</body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert (
        await should_escalate_to_browser_async(result, surface="ecommerce_listing")
        is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_listing_202_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://www.govplanet.com/for-sale/equipment",
        final_url="https://www.govplanet.com/for-sale/equipment",
        html=(
            "<html><body><div id='app'></div>"
            "<script type='application/json'>{\"pending\":true}</script>"
            "<script></script><script></script>"
            "</body></html>"
        ),
        status_code=202,
        method="httpx",
        blocked=False,
    )

    assert (
        await should_escalate_to_browser_async(result, surface="ecommerce_listing")
        is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_listing_single_product_json_ld_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://shop.example.com/hair-care/hair-straighteners",
        final_url="https://shop.example.com/hair-care/hair-straighteners",
        html=(
            "<html><body><h1>Hair straighteners</h1>"
            "<script type='application/ld+json'>"
            '{"@context":"https://schema.org","@type":"Product","name":"SEO Product"}'
            "</script>"
            "<script>window.dataLayer=[{pageInfo:{pageType:'catalog/category/view'}}]</script>"
            "<div id='layer-product-list'></div>"
            "<p>" + ("Category copy. " * 80) + "</p>"
            "</body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert (
        await should_escalate_to_browser_async(result, surface="ecommerce_listing")
        is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_detail_shell_copy_with_detail_words_still_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://shop.example.com/products/widget",
        final_url="https://shop.example.com/products/widget",
        html=(
            "<html><body><div id='__next'></div>"
            "<main><h1>Widget</h1>"
            "<p>Add to cart, shipping, reviews, and product details load in the app.</p>"
            "</main><script></script><script></script><script></script>"
            "</body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert (
        await should_escalate_to_browser_async(result, surface="ecommerce_detail")
        is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_js_disabled_placeholder_shell_escalates_to_browser() -> None:
    result = PageFetchResult(
        url="https://example.com/for-sale/mixer-truck",
        final_url="https://example.com/for-sale/mixer-truck",
        html=(
            "<html><head><title>JavaScript is disabled</title></head>"
            "<body><noscript>Please enable JavaScript to continue.</noscript>"
            "<main><h1>JavaScript is disabled</h1></main></body></html>"
        ),
        status_code=200,
        method="httpx",
        blocked=False,
    )

    assert (
        await should_escalate_to_browser_async(result, surface="ecommerce_detail")
        is True
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_uses_browser_for_js_disabled_placeholder_shell(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    @_as_async
    def _fake_curl(url: str, timeout: float, *, proxy: str | None = None):
        del timeout, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html=(
                "<html><head><title>JavaScript is disabled</title></head>"
                "<body><noscript>Please enable JavaScript to continue.</noscript>"
                "<main><h1>JavaScript is disabled</h1></main></body></html>"
            ),
            status_code=200,
            method="curl_cffi",
            blocked=False,
        )

    @_as_async
    def _unexpected_http(url: str, timeout: float, *, proxy: str | None = None):
        raise AssertionError(
            f"http fallback should not run when curl already returned a JS-disabled shell: {url} {timeout} {proxy}"
        )

    browser_calls: list[str] = []

    @_as_async
    def _fake_browser(url, timeout, **kwargs):
        del timeout, kwargs
        browser_calls.append(url)
        return PageFetchResult(
            url=url,
            final_url=url,
            html="<html><body><h1>Rendered listing</h1></body></html>",
            status_code=200,
            method="browser",
            blocked=False,
        )

    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)
    monkeypatch.setattr(crawl_fetch_runtime, "_http_fetch", _unexpected_http)
    monkeypatch.setattr(crawl_fetch_runtime, "_browser_fetch", _fake_browser)

    result = await crawl_fetch_runtime.fetch_page(
        "https://example.com/for-sale/mixer-truck",
        surface="ecommerce_detail",
    )

    assert result.method == "browser"
    assert browser_calls == ["https://example.com/for-sale/mixer-truck"]
