from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.core.config.cascade import CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
from app.core.config.domain_profiles import CAPTURE_NETWORK_ALL_SMALL_JSON
from app.crawl.pipeline import extraction_loop
from app.crawl.pipeline.retry import stage


def _request() -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id=1,
        url="https://example.com/item",
        plan=AcquisitionIntent(surface="ecommerce_detail"),
    )


def _result(method: str = "curl_cffi") -> PageAcquisitionResult:
    return PageAcquisitionResult(
        request=_request(),
        final_url="https://example.com/item",
        html="<html></html>",
        method=method,
        status_code=200,
        browser_diagnostics={"browser_attempted": method == "browser"},
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_browser_retry_result_honors_configured_rung_bound(monkeypatch) -> None:
    # The single-rung default (max_attempts=1) still caps escalation at one
    # acquisition; the bound is the configured argument, not a hardcoded 1.
    calls = 0

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        nonlocal calls
        calls += 1
        return _result("browser")

    def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)

    context = SimpleNamespace(
        url="https://example.com/item",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
    )
    fetched = SimpleNamespace(acquisition_result=_result(), url_metrics={})

    first = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="empty_extraction",
        max_attempts=1,
    )
    second = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="low_quality_extraction",
        max_attempts=1,
    )

    assert first is not None
    assert second is None
    assert calls == 1
    assert context.browser_escalation_count == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_browser_retry_climbs_to_configured_bound(monkeypatch) -> None:
    # With max_attempts == CAP the ladder acquires up to CAP browser rungs, and
    # a browser-flagged result from an earlier rung does NOT block the next one.
    calls = 0

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        nonlocal calls
        calls += 1
        return _result("browser")

    def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)

    context = SimpleNamespace(
        url="https://example.com/item",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
    )
    fetched = SimpleNamespace(acquisition_result=_result(), url_metrics={})

    results = []
    for _ in range(CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP + 1):
        results.append(
            await stage._acquire_browser_retry_result(
                context,
                fetched,
                retry_reason="empty_extraction",
                max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP,
            )
        )
        if results[-1] is not None:
            fetched.acquisition_result = results[-1]

    assert calls == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    assert context.browser_escalation_count == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    # The rung after the bump is exhausted -> honest stop.
    assert results[-1] is None


@pytest.mark.asyncio
@pytest.mark.unit
async def test_browser_retry_network_rung_preserves_authorized_plan(
    monkeypatch,
) -> None:
    requests: list[AcquisitionRequest] = []

    async def fake_build_request(context):
        return AcquisitionRequest(
            run_id=1,
            url=context.url,
            plan=AcquisitionIntent(
                surface="job_listing",
                proxy_list=("http://proxy.test:8080",),
                traversal_mode="paginate",
                max_pages=3,
                max_scrolls=2,
            ),
            acquisition_profile={
                "capture_network": "off",
                "capture_screenshot": False,
            },
        )

    async def fake_acquire(request):
        requests.append(request)
        return _result("browser")

    def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)

    context = SimpleNamespace(
        url="https://example.com/jobs",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
    )
    fetched = SimpleNamespace(acquisition_result=_result(), url_metrics={})

    for _ in range(2):
        result = await stage._acquire_browser_retry_result(
            context,
            fetched,
            retry_reason="empty_extraction",
            required_artifacts=("rendered_html", "network_payloads"),
            max_attempts=2,
        )
        assert result is not None
        fetched.acquisition_result = result

    # Finding 5: when network_payloads is required, EVERY browser rung —
    # including the first one after an HTTP-first result — captures network
    # payloads. Previously the first rung ran with capture off and burned an
    # attempt producing an artifact that could not satisfy the requirement.
    assert [request.policy.capture_network for request in requests] == [
        CAPTURE_NETWORK_ALL_SMALL_JSON,
        CAPTURE_NETWORK_ALL_SMALL_JSON,
    ]
    for request in requests:
        assert request.plan.proxy_list == ("http://proxy.test:8080",)
        assert request.plan.traversal_mode == "paginate"
        assert request.plan.max_pages == 3
        assert request.plan.max_scrolls == 2
        assert request.policy.capture_screenshot is False
        assert 0 < request.attempt_timeout_seconds <= 120.0


@pytest.mark.asyncio
@pytest.mark.unit
async def test_browser_retry_failure_preserves_original_http_result(
    monkeypatch,
) -> None:
    logged: list[str] = []

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        raise RuntimeError(
            "Page.evaluate: Connection closed while reading from the driver"
        )

    def fake_log(_context, _level, message, **_kwargs):
        logged.append(message)

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)

    original = _result()
    context = SimpleNamespace(
        url="https://example.com/item",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
    )
    fetched = SimpleNamespace(acquisition_result=original, url_metrics={})

    result = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="empty_extraction",
    )

    assert result is None
    assert fetched.acquisition_result is original
    assert fetched.acquisition_result.method == "curl_cffi"
    assert context.browser_escalation_count == 1
    assert any("using the original HTTP payload" in message for message in logged)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_initial_browser_without_network_payloads_runs_network_retry(
    monkeypatch,
) -> None:
    requests: list[AcquisitionRequest] = []

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        requests.append(request)
        return _result("browser")

    def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)
    context = SimpleNamespace(
        url="https://example.com/item",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
    )
    fetched = SimpleNamespace(acquisition_result=_result("browser"), url_metrics={})

    result = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="post_extraction_challenge_shell",
        required_artifacts=("rendered_html", "network_payloads"),
        max_attempts=1,
    )

    assert result is not None
    assert len(requests) == 1
    assert requests[0].policy.capture_network == CAPTURE_NETWORK_ALL_SMALL_JSON
    assert context.browser_escalation_count == 1


@pytest.mark.asyncio
@pytest.mark.unit
@pytest.mark.parametrize(
    ("required_artifacts", "network_payloads"),
    [
        (("rendered_html",), []),
        (("rendered_html", "network_payloads"), [{"body": {"job": {}}}]),
    ],
)
async def test_initial_browser_skips_when_required_artifacts_already_present(
    monkeypatch,
    required_artifacts,
    network_payloads,
) -> None:
    calls = 0

    async def fake_acquire(request):
        nonlocal calls
        calls += 1
        return _result("browser")

    def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)
    context = SimpleNamespace(
        url="https://example.com/item",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
    )
    acquisition_result = _result("browser")
    acquisition_result.network_payloads = network_payloads
    fetched = SimpleNamespace(acquisition_result=acquisition_result, url_metrics={})

    result = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="empty_extraction",
        required_artifacts=required_artifacts,
        max_attempts=1,
    )

    assert result is None
    assert calls == 0
    assert context.browser_escalation_count == 0
