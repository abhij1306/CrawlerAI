from __future__ import annotations

import httpx
import pytest

from app.services.acquisition.http_client import HttpFetchResult, request_result
from app.services.adapters import registry as adapter_registry
from app.services.adapters.base import (
    AdapterResult,
    BaseAdapter,
    PublicEndpointAdapter,
    SelectolaxJobAdapter,
)
from app.services.adapters.registry import registered_adapters, run_adapter
from app.services.adapters.workday import WorkdayAdapter
from app.services.adapters.registry import normalize_adapter_acquisition_url
from app.services.config.adapter_runtime_settings import adapter_runtime_settings
from app.services.extract.listing_candidate_ranking import (
    best_listing_candidate_set,
)




@pytest.mark.asyncio
@pytest.mark.component
async def test_request_result_applies_per_request_timeout_with_shared_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.acquisition import runtime as runtime_module

    observed_timeouts: list[float] = []

    class _FakeResponse:
        status_code = 200
        url = "https://example.com/api/jobs"
        headers = httpx.Headers({"content-type": "application/json"})
        text = '{"jobs":[{"id":1}]}'

    class _FakeClient:
        is_closed = False

        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data
            observed_timeouts.append(float(timeout))
            return _FakeResponse()

        async def aclose(self) -> None:
            self.is_closed = True

    monkeypatch.setattr(
        "app.services.acquisition.runtime.build_async_http_client",
        lambda **kwargs: _FakeClient(),
    )
    runtime_module._clear_shared_clients_for_testing()

    await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
        timeout_seconds=1.5,
    )
    await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
        timeout_seconds=3.0,
    )

    assert observed_timeouts == [1.5, 3.0]


@pytest.mark.component
def test_registered_adapters_include_workday_and_ultipro() -> None:
    names = {adapter.name for adapter in registered_adapters()}

    assert "workday" in names
    assert "ultipro_ukg" in names


@pytest.mark.component
def test_listing_dedupe_keeps_distinct_urls_with_same_job_id() -> None:
    records = best_listing_candidate_set(
        [
            (
                "adapter",
                [
                    {
                        "job_id": "123",
                        "title": "Software Engineer",
                        "url": "https://example.com/jobs/software-engineer",
                    },
                    {
                        "job_id": "123",
                        "title": "Data Engineer",
                        "url": "https://example.com/jobs/data-engineer",
                    },
                ],
            )
        ],
        page_url="https://example.com/jobs",
        surface="job_listing",
        max_records=10,
        title_is_noise=lambda _title: False,
        url_is_structural=lambda _url, _page_url: False,
        detail_like_url=lambda _url: True,
    )

    assert {record["url"] for record in records} == {
        "https://example.com/jobs/software-engineer",
        "https://example.com/jobs/data-engineer",
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_platform_owned_adp_acquisition_normalization_uses_configured_domains() -> (
    None
):
    normalized = await normalize_adapter_acquisition_url(
        "https://acme.wd5.myworkforcenow.com/recruitment/recruitment.html?jobId= 12345 "
    )

    assert normalized == (
        "https://acme.wd5.myworkforcenow.com/recruitment/recruitment.html?jobId=12345"
    )


class _AsyncSelectolaxAdapter(SelectolaxJobAdapter):
    async def can_handle(self, url: str, html: str) -> bool:
        return True

    def _extract_detail(self, parser, url: str) -> dict | None:
        return {"url": url, "title": parser.css_first("h1").text(strip=True)}

    def _extract_listing(self, parser, url: str) -> list[dict]:
        return [
            {"url": url, "title": node.text(strip=True)} for node in parser.css(".job")
        ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_adapter_allows_job_declared_adapter_without_platform_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (_UnconfiguredPublicJobAdapter(),),
    )

    result = await run_adapter(
        "https://example.com/jobs",
        "<html></html>",
        "job_listing",
    )

    assert result is not None
    assert result.records == [{"url": "https://example.com/jobs", "title": "Engineer"}]


class _UnconfiguredPublicJobAdapter(PublicEndpointAdapter):
    name = "new_public_jobs"
    platform_family = "new_public_jobs"
    job_surface_only = True

    async def can_handle(self, url: str, html: str) -> bool:
        del url, html
        return True

    async def _try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        del html, surface, proxy
        return [{"url": url, "title": "Engineer"}]


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_adapter_coerces_nullable_surface_to_empty_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _DummyAdapter()
    adapter.name = "shopify"
    adapter.platform_family = "shopify"
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (adapter,),
    )

    result = await run_adapter(
        "https://example.com/products/widget",
        "<html><body>product</body></html>",
        None,
    )

    assert result == AdapterResult()
    assert adapter.captured_surface == ""


@pytest.mark.asyncio
@pytest.mark.component
async def test_selectolax_job_adapter_keeps_sync_hooks_supported() -> None:
    adapter = _SyncSelectolaxAdapter()

    detail = await adapter.extract(
        "https://example.com/jobs/1",
        "<h1>Engineer</h1>",
        "job_detail",
    )
    listing = await adapter.extract(
        "https://example.com/jobs",
        "<div class='job'>Engineer</div>",
        "job_listing",
    )

    assert detail.records == [
        {"url": "https://example.com/jobs/1", "title": "Engineer"}
    ]
    assert listing.records == [{"url": "https://example.com/jobs", "title": "Engineer"}]


@pytest.mark.asyncio
@pytest.mark.component
async def test_request_result_honors_expect_json_without_json_content_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResponse:
        status_code = 200
        url = "https://example.com/api/jobs"
        headers = httpx.Headers({"content-type": "text/plain"})
        text = '{"jobs":[{"id":1}]}'

    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data, timeout
            return _FakeResponse()

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )

    result = await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
    )

    assert result.json_data == {"jobs": [{"id": 1}]}


class _SyncSelectolaxAdapter(SelectolaxJobAdapter):
    async def can_handle(self, url: str, html: str) -> bool:
        return True

    def _extract_detail(self, parser, url: str) -> dict | None:
        return {"url": url, "title": parser.css_first("h1").text(strip=True)}

    def _extract_listing(self, parser, url: str) -> list[dict]:
        return [
            {"url": url, "title": node.text(strip=True)} for node in parser.css(".job")
        ]


@pytest.mark.component
def test_registered_adapters_include_factory_entries_without_platform_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(adapter_registry, "configured_adapter_names", lambda: ())
    adapter_registry.registered_adapters.cache_clear()
    try:
        names = {adapter.name for adapter in adapter_registry.registered_adapters()}
    finally:
        adapter_registry.registered_adapters.cache_clear()

    assert "bullhorn" in names


@pytest.mark.asyncio
@pytest.mark.component
async def test_platform_owned_adp_acquisition_normalization_keeps_generic_flow_generic() -> (
    None
):
    normalized = await normalize_adapter_acquisition_url(
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?jobId= 12345 &lang=en_US"
    )

    assert normalized == (
        "https://workforcenow.adp.com/mascsr/default/mdf/recruitment/recruitment.html?jobId=12345&lang=en_US"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_request_result_does_not_orchestrate_browser_fetches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_methods: list[str] = []

    class _FakeResponse:
        status_code = 200
        url = "https://example.com/jobs/123"
        headers = httpx.Headers({"content-type": "text/html"})
        text = "<html><body>detail page</body></html>"

    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del url, headers, json, data, timeout
            observed_methods.append(str(method))
            return _FakeResponse()

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )

    result = await request_result(
        "https://example.com/jobs/123",
        prefer_browser=True,
    )

    assert observed_methods == ["GET"]
    assert result.text == "<html><body>detail page</body></html>"


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_adapter_skips_job_platform_adapter_for_commerce_surface(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (_ExplodingAdapter(),),
    )

    result = await run_adapter(
        "https://www.kitchenaid.com/products/widget",
        "<html><body>workday</body></html>",
        "ecommerce_listing",
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_base_adapter_request_json_uses_json_request_contract() -> None:
    adapter = _DummyAdapter()

    payload = await adapter._request_json("https://example.com/api/jobs")

    assert payload == {"ok": True}
    assert adapter.captured_expect_json is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_request_result_retries_dns_failure_with_forced_ipv4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []

    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data, timeout
            attempts.append("shared")
            raise OSError(11001, "getaddrinfo failed")

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    class _RetryClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data, timeout
            attempts.append("ipv4")
            return type(
                "_FakeResponse",
                (),
                {
                    "status_code": 200,
                    "url": "https://example.com/api/jobs",
                    "headers": httpx.Headers({"content-type": "application/json"}),
                    "text": '{"jobs":[{"id":1}]}',
                },
            )()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )
    monkeypatch.setattr(
        "app.services.acquisition.http_client.build_async_http_client",
        lambda **kwargs: _RetryClient(),
    )

    result = await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
    )

    assert attempts == ["shared", "ipv4"]
    assert result.json_data == {"jobs": [{"id": 1}]}


class _DummyAdapter(BaseAdapter):
    async def can_handle(self, url: str, html: str) -> bool:
        return True

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        self.captured_surface = surface
        return AdapterResult()

    async def _request_result(self, url: str, **kwargs) -> HttpFetchResult:
        self.captured_expect_json = bool(kwargs.get("expect_json"))
        return HttpFetchResult(
            url=url,
            final_url=url,
            text='<html><body><pre>{"ok": true}</pre></body></html>',
            status_code=200,
            headers=httpx.Headers({"content-type": "text/html"}),
            json_data={"ok": True},
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_adapter_fails_open_when_adapter_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    exploding = _ExplodingAdapter()
    exploding.name = "shopify"
    exploding.platform_family = "shopify"
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (exploding,),
    )

    result = await run_adapter(
        "https://example.com/products/widget",
        "<html><body>product</body></html>",
        "ecommerce_detail",
    )

    assert result is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_selectolax_job_adapter_awaits_async_hooks() -> None:
    adapter = _AsyncSelectolaxAdapter()

    detail = await adapter.extract(
        "https://example.com/jobs/1",
        "<h1>Engineer</h1>",
        "job_detail",
    )
    listing = await adapter.extract(
        "https://example.com/jobs",
        "<div class='job'>Engineer</div>",
        "job_listing",
    )

    assert detail.records == [
        {"url": "https://example.com/jobs/1", "title": "Engineer"}
    ]
    assert listing.records == [{"url": "https://example.com/jobs", "title": "Engineer"}]


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_adapter_forwards_proxy_to_public_endpoint_adapter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _ProxyPublicEndpointAdapter()
    monkeypatch.setattr(
        "app.services.adapters.registry.registered_adapters",
        lambda: (adapter,),
    )

    result = await run_adapter(
        "https://example.com/jobs",
        "<html></html>",
        "job_listing",
        proxy="http://proxy.example:8080",
    )

    assert result is not None
    assert result.records == [
        {"url": "https://example.com/jobs", "surface": "job_listing"}
    ]
    assert adapter.captured_proxy == "http://proxy.example:8080"


class _ExplodingAdapter(BaseAdapter):
    name = "workday"
    platform_family = "workday"

    async def can_handle(self, url: str, html: str) -> bool:
        del url, html
        return True

    async def extract(self, url: str, html: str, surface: str) -> AdapterResult:
        del url, html, surface
        raise RuntimeError("adapter failure")


@pytest.mark.asyncio
@pytest.mark.component
async def test_ats_adapter_request_timeout_comes_from_runtime_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = WorkdayAdapter()
    observed_timeouts: list[int] = []

    async def _fake_request_json(url: str, **kwargs):
        del url
        observed_timeouts.append(int(kwargs["timeout_seconds"]))
        return {"total": 0, "jobPostings": []}

    monkeypatch.setattr(adapter, "_request_json", _fake_request_json)
    monkeypatch.setattr(adapter_runtime_settings, "ats_request_timeout_seconds", 7)

    await adapter.extract(
        "https://example.wd5.myworkdayjobs.com/en-US/External",
        "",
        "job_listing",
    )

    assert observed_timeouts == [7]


@pytest.mark.asyncio
@pytest.mark.component
async def test_request_result_uses_direct_http_for_expected_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeResponse:
        status_code = 200
        url = "https://example.com/api/jobs"
        headers = httpx.Headers({"content-type": "application/json"})
        text = '<html><body><pre>{"jobs":[{"id":1}]}</pre></body></html>'

    class _FakeClient:
        async def request(
            self,
            method,
            url,
            headers=None,
            json=None,
            data=None,
            timeout=None,
        ):
            del method, url, headers, json, data, timeout
            return _FakeResponse()

    async def _fake_get_shared(*, proxy=None, force_ipv4=False):
        del proxy, force_ipv4
        return _FakeClient()

    monkeypatch.setattr(
        "app.services.acquisition.http_client.get_shared_http_client",
        _fake_get_shared,
    )

    result = await request_result(
        "https://example.com/api/jobs",
        expect_json=True,
    )

    assert result.json_data == {"jobs": [{"id": 1}]}


class _ProxyPublicEndpointAdapter(PublicEndpointAdapter):
    name = "proxy_public"
    platform_family = "workday"

    async def can_handle(self, url: str, html: str) -> bool:
        del url, html
        return True

    async def _try_public_endpoint(
        self,
        url: str,
        html: str,
        surface: str,
        *,
        proxy: str | None = None,
    ) -> list[dict]:
        self.captured_proxy = proxy
        return [{"url": url, "surface": surface}]

