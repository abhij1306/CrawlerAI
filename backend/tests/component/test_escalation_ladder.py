"""Slice 4 / Task B5: bounded multi-rung browser escalation ladder.

The retry stage now climbs a bounded ladder rather than a single browser rung.
This test drives ``retry_extraction_request_with_browser`` with a URL that stays
empty across rungs and asserts the ladder climbs past the first browser rung and
then exhausts honestly with a terminal verdict — it does NOT assert real
network-payload data was captured (that fixture-backed assertion is the §6
acquisition-ladder slice's job).
"""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.core.config.cascade import CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
from app.extraction.contracts import ExtractionResult, RetryRequest
from app.extraction.surfaces import Surface
from app.crawl.pipeline import extraction_loop
from app.crawl.pipeline.retry import stage


def _request() -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id=1,
        url="https://jobs.test/j/1",
        plan=AcquisitionIntent(surface="job_detail"),
    )


def _acquisition(method: str = "browser") -> PageAcquisitionResult:
    return PageAcquisitionResult(
        request=_request(),
        final_url="https://jobs.test/j/1",
        html="<html></html>",
        method=method,
        status_code=200,
        browser_diagnostics={"browser_attempted": method == "browser"},
    )


def _empty_result(*, with_retry: bool) -> ExtractionResult:
    retry = (
        RetryRequest(
            required=True,
            reason="empty_extraction",
            required_artifacts=("rendered_html", "network_payloads"),
            max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP,
        )
        if with_retry
        else None
    )
    return ExtractionResult(
        surface=Surface.JOB_DETAIL,
        bundle_id="b",
        records=(),
        verdict="empty",
        retry_request=retry,
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_escalation_ladder_climbs_then_exhausts_honestly(monkeypatch) -> None:
    acquire_calls = 0
    extract_calls = 0

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        nonlocal acquire_calls
        acquire_calls += 1
        return _acquisition("browser")

    async def fake_extract(context, fetched):
        # Each rung keeps requesting a retry until the browser budget is spent,
        # so the loop is driven purely by the rung bound, not by a satisfied
        # verdict. It exhausts honestly with the terminal empty verdict.
        nonlocal extract_calls
        extract_calls += 1
        return _empty_result(with_retry=True), []

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_extract_records_for_acquisition", fake_extract)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)

    context = SimpleNamespace(
        url="https://jobs.test/j/1",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        session=None,
    )
    fetched = SimpleNamespace(acquisition_result=_acquisition("curl_cffi"), url_metrics={})

    result = await stage.retry_extraction_request_with_browser(
        context,
        fetched,
        result=_empty_result(with_retry=True),
    )

    # The ladder climbed the full configured rung budget (> 1 rung), each rung
    # re-extracted, and it stopped when the budget was spent.
    assert acquire_calls == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    assert extract_calls == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    assert context.browser_escalation_count == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    # Honest exhaustion: a terminal verdict, no infinite retry.
    assert result.verdict == "empty"


@pytest.mark.asyncio
@pytest.mark.component
async def test_escalation_ladder_stops_when_verdict_satisfied(monkeypatch) -> None:
    acquire_calls = 0

    async def fake_build_request(context):
        return _request()

    async def fake_acquire(request):
        nonlocal acquire_calls
        acquire_calls += 1
        return _acquisition("browser")

    async def fake_extract(context, fetched):
        # First (and only) rung resolves: no further retry requested.
        return (
            ExtractionResult(
                surface=Surface.JOB_DETAIL,
                bundle_id="b",
                records=(),
                verdict="success",
            ),
            [],
        )

    async def fake_log(*args, **kwargs):
        return None

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)
    monkeypatch.setattr(stage, "_extract_records_for_acquisition", fake_extract)
    monkeypatch.setattr(stage, "_log_pipeline_event", fake_log)

    context = SimpleNamespace(
        url="https://jobs.test/j/1",
        url_timeout_seconds=120.0,
        started_at_monotonic=time.monotonic(),
        requested_fields=[],
        browser_escalation_count=0,
        session=None,
    )
    fetched = SimpleNamespace(acquisition_result=_acquisition("curl_cffi"), url_metrics={})

    result = await stage.retry_extraction_request_with_browser(
        context,
        fetched,
        result=_empty_result(with_retry=True),
    )

    assert acquire_calls == 1
    assert context.browser_escalation_count == 1
    assert result.verdict == "success"
