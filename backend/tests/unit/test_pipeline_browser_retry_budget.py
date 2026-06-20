from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.acquisition.acquirer import AcquisitionRequest, AcquisitionResult
from app.acquisition.runtime_plan import AcquisitionPlan
from app.crawl.pipeline import extraction_loop
from app.crawl.pipeline.retry import stage


def _request() -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id=1,
        url="https://example.com/item",
        plan=AcquisitionPlan(surface="ecommerce_detail"),
    )


def _result(method: str = "curl_cffi") -> AcquisitionResult:
    return AcquisitionResult(
        request=_request(),
        final_url="https://example.com/item",
        html="<html></html>",
        method=method,
        status_code=200,
        browser_diagnostics={"browser_attempted": method == "browser"},
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_browser_retry_result_allows_only_one_escalation(monkeypatch) -> None:
    calls = 0

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        nonlocal calls
        calls += 1
        return _result("browser")

    async def fake_log(*args, **kwargs):
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
    )
    fetched = SimpleNamespace(acquisition_result=_result(), url_metrics={})

    first = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="empty_extraction",
    )
    second = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="low_quality_extraction",
    )

    assert first is not None
    assert second is None
    assert calls == 1
    assert context.browser_escalation_count == 1


@pytest.mark.asyncio
@pytest.mark.unit
async def test_browser_retry_result_skips_when_browser_already_attempted(monkeypatch) -> None:
    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)
    context = SimpleNamespace(
        url="https://example.com/item",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
    )
    fetched = SimpleNamespace(acquisition_result=_result("browser"), url_metrics={})

    result = await stage._acquire_browser_retry_result(
        context,
        fetched,
        retry_reason="post_extraction_challenge_shell",
        forced_browser_engine="real_chrome",
    )

    assert result is None
    assert context.browser_escalation_count == 0
