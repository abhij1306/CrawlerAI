"""test_crawl_fetch_runtime cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_fetch_runtime_test_support import (
    PageFetchResult,
    SimpleNamespace,
    _as_async,
    acquisition_runtime,
    classify_network_endpoint,
    crawl_fetch_runtime,
    httpx,
    pytest,
    should_capture_network_payload,
)


def _patch_curl_session(monkeypatch: pytest.MonkeyPatch, fake_get) -> None:
    import curl_cffi
    from curl_cffi import requests as curl_requests

    class _Curl:
        def setopt(self, *_args) -> None:
            return None

    class _Session:
        def __init__(self, **_kwargs) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, url: str, **kwargs):
            return fake_get(url, **kwargs)

    monkeypatch.setattr(curl_cffi, "Curl", _Curl)
    monkeypatch.setattr(curl_requests, "Session", _Session)


@pytest.mark.component
def test_should_capture_network_payload_skips_noise_and_large_declared_payloads() -> (
    None
):
    assert not should_capture_network_payload(
        url="https://cdn.cookielaw.org/consent/site/en.json",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not should_capture_network_payload(
        url="https://cdn0.forter.com/site/prop.json",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not should_capture_network_payload(
        url="https://bam.nr-data.net/1/NRBR",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not should_capture_network_payload(
        url="https://arcteryx.us-5.evergage.com/api2/event/site",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not should_capture_network_payload(
        url="https://example.com/telemetry/events",
        content_type="application/json",
        headers={},
        captured_count=0,
    )
    assert not should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "9999999"},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "512"},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"content-length": "600000"},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/products/widget/product.js",
        content_type="application/json",
        headers={"content-length": "6000000"},
        captured_count=0,
        surface="ecommerce_detail",
    )


@pytest.mark.component
def test_should_capture_network_payload_accepts_chunked_json_without_content_length() -> (
    None
):
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={"transfer-encoding": "chunked"},
        captured_count=0,
    )


@pytest.mark.component
def test_content_aware_http_blocking_ignores_vendor_headers_when_detail_signals_exist() -> (
    None
):
    html = """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Prime",
          "offers": {
            "price": "19.99",
            "priceCurrency": "USD"
          }
        }
        </script>
      </head>
      <body>
        <h1>Widget Prime</h1>
      </body>
    </html>
    """

    assert not acquisition_runtime._content_aware_http_blocked(
        httpx.Headers({"akamai-grn": "0.abc"}),
        html,
        200,
    )


@pytest.mark.component
def test_select_http_fetcher_uses_httpx_when_forced(patch_settings) -> None:
    patch_settings(force_httpx=True)
    fetcher = crawl_fetch_runtime._select_http_fetcher(object())

    assert fetcher is crawl_fetch_runtime._http_fetch


@pytest.mark.component
def test_should_capture_network_payload_ignores_misleading_content_length_when_chunked() -> (
    None
):
    assert should_capture_network_payload(
        url="https://example.com/api/products",
        content_type="application/json",
        headers={
            "transfer-encoding": "chunked",
            "content-length": "9999999",
        },
        captured_count=0,
    )


@pytest.mark.component
def test_should_capture_network_payload_accepts_react_server_component_streams() -> (
    None
):
    assert should_capture_network_payload(
        url="https://example.com/products/widget",
        content_type="text/x-component",
        headers={},
        captured_count=0,
    )


@pytest.mark.component
def test_should_capture_network_payload_accepts_trpc_and_rsc_url_hints() -> None:
    assert should_capture_network_payload(
        url="https://example.com/api/trpc/product.get",
        content_type="application/trpc+json",
        headers={},
        captured_count=0,
    )
    assert should_capture_network_payload(
        url="https://example.com/products/widget?_rsc=abc123",
        content_type="text/plain",
        headers={},
        captured_count=0,
    )


@pytest.mark.component
def test_classify_network_endpoint_uses_platform_config_family_signatures() -> None:
    assert classify_network_endpoint(
        response_url="https://boards-api.greenhouse.io/v1/boards/acme/jobs/1234",
        surface="job_detail",
    ) == {"type": "job_api", "family": "greenhouse"}
    assert classify_network_endpoint(
        response_url="https://jobs.example.com/api/positions/1234",
        surface="job_detail",
    ) == {"type": "job_api", "family": "generic"}
    assert classify_network_endpoint(
        response_url="https://shop.example.com/products/widget/product.js",
        surface="ecommerce_detail",
    ) == {"type": "product_api", "family": "shopify"}
    assert classify_network_endpoint(
        response_url="https://shop.example.com/api/variants/123",
        surface="ecommerce_detail",
    ) == {"type": "product_api", "family": "generic"}
    assert classify_network_endpoint(
        response_url="https://store.example.com/_next/data/build-id/widget.json",
        surface="ecommerce_detail",
    ) == {"type": "generic_json", "family": "nextjs"}


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_uses_runtime_owned_default_request_headers(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    captured_headers: dict[str, str] = {}
    patch_settings(
        http_user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/131.0.0.0 Safari/537.36"
        )
    )

    def _fake_get(url: str, **kwargs):
        del url
        captured_headers.update(dict(kwargs.get("headers") or {}))
        return SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url="https://example.com/products/widget",
        )

    _patch_curl_session(monkeypatch, _fake_get)
    result = await acquisition_runtime.curl_fetch(
        "https://example.com/products/widget",
        5.0,
    )

    assert result.method == "curl_cffi"
    assert captured_headers["User-Agent"].endswith("Chrome/131.0.0.0 Safari/537.36")
    assert "Accept" in captured_headers
    assert "Accept-Language" in captured_headers
    assert captured_headers["Upgrade-Insecure-Requests"] == "1"
    assert "sec-ch-ua" in captured_headers


@pytest.mark.asyncio
@pytest.mark.component
async def test_curl_fetch_coerces_blank_impersonate_target_to_none(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    captured_impersonate: list[object] = []

    def _fake_get(url: str, **kwargs):
        del url
        captured_impersonate.append(kwargs.get("impersonate"))
        return SimpleNamespace(
            text="<html><body>ok</body></html>",
            headers={"content-type": "text/html"},
            status_code=200,
            url="https://example.com/products/widget",
        )

    _patch_curl_session(monkeypatch, _fake_get)
    patch_settings(curl_impersonate_target="   ")
    await acquisition_runtime.curl_fetch(
        "https://example.com/products/widget",
        5.0,
    )

    assert captured_impersonate == [None]


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_page_waits_for_host_slot_before_http_attempt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wait_calls: list[str] = []

    @_as_async
    def _fake_wait_for_host_slot(
        url: str,
        *,
        ttl_seconds: int | None = None,
    ) -> None:
        del ttl_seconds
        wait_calls.append(url)

    @_as_async
    def _fake_curl(url: str, timeout_seconds: float, *, proxy: str | None = None):
        del timeout_seconds, proxy
        return PageFetchResult(
            url=url,
            final_url=url,
            html=(
                "<html><body><article class='product-card'>"
                "<a href='/products/widget'>Widget</a><span>$19.99</span>"
                "</article></body></html>"
            ),
            status_code=200,
            method="curl_cffi",
        )

    monkeypatch.setattr(
        crawl_fetch_runtime, "wait_for_host_slot", _fake_wait_for_host_slot
    )
    monkeypatch.setattr(crawl_fetch_runtime, "_curl_fetch", _fake_curl)

    result = await crawl_fetch_runtime.fetch_page(
        crawl_fetch_runtime.FetchPageCall(
            "https://example.com/collections/widgets",
            surface="ecommerce_listing",
        )
    )

    assert result.method == "curl_cffi"
    assert wait_calls == ["https://example.com/collections/widgets"]
