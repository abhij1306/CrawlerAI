from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.acquisition import browser_runtime
from app.services.acquisition.acquirer import (
    AcquisitionRequest,
    PageEvidence,
    acquire,
)
from app.services.acquisition.internal_api_replay import _is_safe_replay_url
from app.services.acquisition.policy import AcquisitionPolicy
from app.services.acquisition_plan import AcquisitionPlan
from app.services.crawl.utils import collect_target_urls, normalize_target_url, parse_csv_urls


@pytest.mark.component
def test_origin_warmup_state_lock_is_scoped_to_running_loop() -> None:
    async def _locks() -> tuple[asyncio.Lock, asyncio.Lock]:
        return (
            browser_runtime._origin_warmup_state_lock(),
            browser_runtime._origin_warmup_state_lock(),
        )

    first_lock, repeated_first_lock = asyncio.run(_locks())
    second_lock, repeated_second_lock = asyncio.run(_locks())

    assert first_lock is repeated_first_lock
    assert second_lock is repeated_second_lock
    assert first_lock is not second_lock


@pytest.mark.component
def test_collect_target_urls_normalizes_csv_values() -> None:
    urls = collect_target_urls(
        {"url": "https://example.com/products/widget"},
        {
            "csv_content": (
                "url\n"
                "https://example.com/products/widget?utm_source=newsletter\n"
                "https://example.com/products/other?fbclid=tracking"
            )
        },
    )

    assert urls == [
        "https://example.com/products/widget",
        "https://example.com/products/other",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_returns_public_headers_as_plain_dict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[tuple[str, str]] = []

    async def _on_event(level: str, message: str) -> None:
        events.append((level, message))

    async def _fake_fetch_page(*args, **kwargs):
        del args
        on_event = kwargs.get("on_event")
        if on_event is not None:
            await on_event(
                "info", "Launched headless browser (chromium, proxy: direct)"
            )
        return type(
            "FetchResult",
            (),
            {
                "final_url": "https://example.com/final",
                "html": "<html></html>",
                "method": "httpx",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": httpx.Headers({"content-type": "text/html"}),
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=1,
            url="https://example.com",
            plan=AcquisitionPlan(surface="ecommerce_detail"),
            on_event=_on_event,
        )
    )

    assert result.headers == {"content-type": "text/html"}
    assert isinstance(result.headers, dict)
    assert events == [
        ("info", "Acquiring https://example.com"),
        ("info", "Launched headless browser (chromium, proxy: direct)"),
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_normalizes_url_via_adapter_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_urls: list[str] = []

    async def _fake_normalize(url: str | None) -> str | None:
        return f"{url}?normalized=1"

    async def _fake_fetch_page(url: str, *args, **kwargs):
        del args, kwargs
        observed_urls.append(url)
        return type(
            "FetchResult",
            (),
            {
                "final_url": url,
                "html": "<html></html>",
                "method": "httpx",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": httpx.Headers({"content-type": "text/html"}),
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.normalize_adapter_acquisition_url",
        _fake_normalize,
    )
    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=1,
            url="https://example.com/jobs/123",
            plan=AcquisitionPlan(surface="job_detail"),
        )
    )

    assert observed_urls == ["https://example.com/jobs/123?normalized=1"]
    assert result.final_url == "https://example.com/jobs/123?normalized=1"


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_strips_pasted_encoded_url_suffix_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_urls: list[str] = []

    async def _fake_fetch_page(url: str, *args, **kwargs):
        del args, kwargs
        observed_urls.append(url)
        return type(
            "FetchResult",
            (),
            {
                "final_url": url,
                "html": "<html></html>",
                "method": "httpx",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": httpx.Headers({"content-type": "text/html"}),
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=1,
            url=(
                "https://www.harrods.com/en-gb/p/"
                "brinkhaus-emperor-100percent-arctic-duck-down-duvet-85-tog-000000000004579693%22,"
            ),
            plan=AcquisitionPlan(surface="ecommerce_detail"),
        )
    )

    expected = (
        "https://www.harrods.com/en-gb/p/"
        "brinkhaus-emperor-100percent-arctic-duck-down-duvet-85-tog-000000000004579693"
    )
    assert observed_urls == [expected]
    assert result.final_url == expected


@pytest.mark.component
def test_normalize_target_url_strips_signed_detail_context_query_params() -> None:
    normalized = normalize_target_url(
        "https://www.mouser.in/ProductDetail/Phoenix-Contact/1509524"
        "?qs=sGAEpiMZZMuGSqhhLqSWxfOEVG9XfT7wFuevx9ZKoIs05o6zFXlrHA%3D%3D"
    )

    assert normalized == "https://www.mouser.in/ProductDetail/Phoenix-Contact/1509524"


@pytest.mark.component
def test_normalize_target_url_strips_pasted_trailing_quote_and_comma() -> None:
    normalized = normalize_target_url(
        'https://www.harrods.com/en-gb/p/brinkhaus-emperor-100percent-arctic-duck-down-duvet-85-tog-000000000004579693",'
    )

    assert (
        normalized
        == "https://www.harrods.com/en-gb/p/brinkhaus-emperor-100percent-arctic-duck-down-duvet-85-tog-000000000004579693"
    )


@pytest.mark.component
def test_normalize_target_url_strips_encoded_trailing_quote_and_comma() -> None:
    normalized = normalize_target_url(
        "https://www.harrods.com/en-gb/p/brinkhaus-emperor-100percent-arctic-duck-down-duvet-85-tog-000000000004579693%22,"
    )

    assert (
        normalized
        == "https://www.harrods.com/en-gb/p/brinkhaus-emperor-100percent-arctic-duck-down-duvet-85-tog-000000000004579693"
    )


@pytest.mark.component
def test_normalize_target_url_strips_uppercase_scheme_trailing_delimiter() -> None:
    normalized = normalize_target_url('HTTPS://example.com/products/widget",')

    assert normalized == "HTTPS://example.com/products/widget"


@pytest.mark.component
def test_parse_csv_urls_accepts_uppercase_http_scheme() -> None:
    assert parse_csv_urls("url\nHTTPS://example.com/products/widget\n") == [
        "HTTPS://example.com/products/widget"
    ]


@pytest.mark.component
def test_acquisition_policy_rejects_invalid_profile_shapes() -> None:
    with pytest.raises(ValueError, match="proxy_profile"):
        AcquisitionPolicy.from_profile({"proxy_profile": ["not", "a", "mapping"]})

    with pytest.raises(ValueError, match="fetch_mode"):
        AcquisitionPolicy.from_profile({"fetch_mode": "surprise"})


@pytest.mark.component
def test_acquisition_policy_profile_maps_are_read_only() -> None:
    source_proxy_profile = {"rotation": "session"}
    policy = AcquisitionPolicy.from_profile({"proxy_profile": source_proxy_profile})
    source_proxy_profile["rotation"] = "rotating"

    assert policy.proxy_profile["rotation"] == "session"
    with pytest.raises(TypeError):
        policy.proxy_profile["rotation"] = "rotating"  # type: ignore[index]


@pytest.mark.component
def test_page_evidence_keeps_usable_content_with_vendor_block_reason_out_of_challenge_shell() -> None:
    evidence = PageEvidence.from_browser_diagnostics(
        {
            "browser_reason": "vendor-block:akamai",
            "browser_outcome": "usable_content",
            "challenge_evidence": ["provider:akamai"],
            "challenge_provider_hits": ["akamai"],
            "readiness_probes": [],
        }
    )

    assert evidence.indicates_block is False
    assert evidence.challenge_shell_reason is None


@pytest.mark.asyncio
@pytest.mark.component
@pytest.mark.parametrize(
    "url",
    [
        "https://100.64.0.1/api/products",
        "https://168.63.129.16/api/products",
    ],
)
async def test_internal_api_replay_reuses_public_target_ip_safety(url: str) -> None:
    assert await _is_safe_replay_url(url, page_url=url) is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_translates_policy_to_fetch_runtime_knobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_fetch_page(url: str, *args, **kwargs):
        del args
        captured["url"] = url
        captured.update(kwargs)
        return type(
            "FetchResult",
            (),
            {
                "final_url": url,
                "html": "<html></html>",
                "method": "browser",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": {},
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )

    await acquire(
        AcquisitionRequest(
            run_id=9,
            url="https://example.com/products/widget",
            plan=AcquisitionPlan(
                surface="ecommerce_detail",
                proxy_list=("http://proxy.example",),
            ),
            acquisition_profile={
                "fetch_mode": "browser_only",
                "prefer_browser": True,
                "retry_reason": "thin-listing retry",
                "proxy_profile": {"rotation": "session"},
                "locality_profile": {"country": "US"},
                "capture_screenshot": True,
                "prefer_curl_handoff": True,
                "handoff_cookie_engine": "real_chrome",
                "forced_browser_engine": "real_chrome",
            },
        )
    )

    assert captured["fetch_mode"] == "browser_only"
    assert captured["prefer_browser"] is True
    assert captured["browser_reason"] == "thin-listing retry"
    assert captured["listing_recovery_mode"] == "thin_listing"
    assert captured["proxy_profile"] == {"rotation": "session"}
    assert captured["locality_profile"] == {"country": "US"}
    assert captured["capture_screenshot"] is True
    assert captured["prefer_curl_handoff"] is True
    assert captured["handoff_cookie_engine"] == "real_chrome"
    assert captured["forced_browser_engine"] == "real_chrome"


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_uses_internal_api_replay_before_page_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch_page(*args, **kwargs):
        raise AssertionError("page fetch should not run when API replay succeeds")

    async def _fake_replay(*, page_url, surface, endpoints, requested_fields):
        assert page_url == "https://example.com/products/replay-widget"
        assert surface == "ecommerce_detail"
        assert requested_fields == ["title", "price"]
        assert endpoints == [
            {
                "url": "https://example.com/api/products/replay-widget.json",
                "method": "GET",
                "endpoint_type": "product_api",
                "endpoint_family": "generic",
                "source_run_id": 92,
            }
        ]
        return {
            "url": "https://example.com/api/products/replay-widget.json",
            "method": "GET",
            "status": 200,
            "content_type": "application/json",
            "endpoint_type": "product_api",
            "endpoint_family": "generic",
            "body": {
                "product": {
                    "title": "Replay Widget",
                    "price": {"amount": "19.99"},
                    "sku": "RW-100",
                    "url": "https://example.com/products/replay-widget",
                }
            },
        }

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )
    monkeypatch.setattr(
        "app.services.acquisition.acquirer.replay_internal_api_endpoints",
        _fake_replay,
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=92,
            url="https://example.com/products/replay-widget",
            plan=AcquisitionPlan(surface="ecommerce_detail"),
            requested_fields=["title", "price"],
            acquisition_profile={
                "internal_api_endpoints": [
                    {
                        "url": "https://example.com/api/products/replay-widget.json",
                        "method": "GET",
                        "endpoint_type": "product_api",
                        "endpoint_family": "generic",
                        "source_run_id": 92,
                    }
                ]
            },
        )
    )

    assert result.method == "api_replay"
    assert result.final_url == "https://example.com/products/replay-widget"
    assert result.network_payloads[0]["url"] == (
        "https://example.com/api/products/replay-widget.json"
    )
    assert result.browser_diagnostics["internal_api_replay"] is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_internal_api_replay_rejects_non_https_and_private_ip() -> None:
    assert await _is_safe_replay_url(
        "http://example.com/api/products.json",
        page_url="https://example.com/products",
    ) is False
    assert await _is_safe_replay_url(
        "https://127.0.0.1/api/products.json",
        page_url="https://127.0.0.1/products",
    ) is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_persists_runtime_policy_updates_on_result_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch_page(url: str, *args, **kwargs):
        del args, kwargs
        return type(
            "FetchResult",
            (),
            {
                "final_url": url,
                "html": "<html></html>",
                "method": "browser",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": {},
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )
    monkeypatch.setattr(
        "app.services.acquisition.acquirer.resolve_platform_runtime_policy",
        lambda *_args, **_kwargs: {"requires_browser": True},
    )

    result = await acquire(
        AcquisitionRequest(
            run_id=9,
            url="https://example.com/products/widget",
            plan=AcquisitionPlan(surface="ecommerce_detail"),
        )
    )

    assert result.request.policy is not None
    assert result.request.policy.prefer_browser is True
    assert result.request.policy.requires_browser is True
    assert result.request.acquisition_profile["prefer_browser"] is True
    assert result.request.acquisition_profile["requires_browser"] is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_acquire_applies_runtime_locality_defaults_without_overriding_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    async def _fake_fetch_page(url: str, *args, **kwargs):
        del args
        captured["url"] = url
        captured.update(kwargs)
        return type(
            "FetchResult",
            (),
            {
                "final_url": url,
                "html": "<html></html>",
                "method": "browser",
                "status_code": 200,
                "content_type": "text/html",
                "blocked": False,
                "headers": {},
                "network_payloads": [],
                "browser_diagnostics": {},
                "artifacts": {},
            },
        )()

    monkeypatch.setattr(
        "app.services.acquisition.acquirer.fetch_page",
        _fake_fetch_page,
    )
    monkeypatch.setattr(
        "app.services.acquisition.acquirer.resolve_platform_runtime_policy",
        lambda *_args, **_kwargs: {
            "requires_browser": True,
            "locality_profile": {
                "geo_country": "US",
                "language_hint": "en-US",
                "currency_hint": "USD",
                "timezone_id": "America/New_York",
            },
            "browser_context_profile": {
                "service_workers": "allow",
                "permissions": [],
                "color_scheme": None,
            },
        },
    )

    await acquire(
        AcquisitionRequest(
            run_id=10,
            url="https://www.belk.com/p/widget",
            plan=AcquisitionPlan(surface="ecommerce_detail"),
            acquisition_profile={
                "locality_profile": {
                    "language_hint": "fr-CA",
                    "browser_context_profile": {
                        "permissions": ["notifications"],
                    },
                }
            },
        )
    )

    assert captured["locality_profile"] == {
        "geo_country": "US",
        "language_hint": "fr-CA",
        "currency_hint": "USD",
        "timezone_id": "America/New_York",
        "browser_context_profile": {
            "service_workers": "allow",
            "permissions": ["notifications"],
            "color_scheme": None,
        },
    }
