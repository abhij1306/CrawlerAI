"""Finding 2: job retries climb past the first browser rung, budget-aware.

Unlike the B5 escalation-ladder test (which monkeypatches the retry-request
producer to force a retry each rung), this test drives the REAL extraction path
so the ``RetryRequest`` comes from ``retry_request()`` -> ``_job_retry_request``.
A shell/empty job_detail page keeps emitting a budget-aware retry
(``max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP``) after browser rung 1, and
the ladder climbs to the full rung budget (2) before exhausting honestly — the
pipeline's ``browser_escalation_count >= max_attempts`` guard is what stops it.

Only the browser fetch boundary is faked; the ``RetryRequest`` is produced by
real code.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.core.config.cascade import CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
from app.crawl.pipeline import extraction_loop
from app.crawl.pipeline.retry import stage
from app.crawl.pipeline.types import URLProcessingConfig
from app.crawl.pipeline.url_processing_context import (
    FetchedURLStage,
    URLProcessingContext,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.component]

_JOB_URL = "https://jobs.test/j/1"
# Empty job document: no records extract, so real extraction returns an empty
# verdict and ``_job_retry_request`` emits a budget-aware retry on every rung.
_EMPTY_JOB_HTML = "<html><body></body></html>"


def _acquisition_request() -> AcquisitionRequest:
    return AcquisitionRequest(
        run_id=1,
        url=_JOB_URL,
        plan=AcquisitionIntent(surface="job_detail"),
    )


def _acquisition(method: str) -> PageAcquisitionResult:
    return PageAcquisitionResult(
        request=_acquisition_request(),
        final_url=_JOB_URL,
        html=_EMPTY_JOB_HTML,
        method=method,
        status_code=200,
        browser_diagnostics={"browser_attempted": method == "browser"},
    )


async def test_job_ladder_climbs_two_real_retry_rungs(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch,
) -> None:
    run = await create_test_run(url=_JOB_URL, surface="job_detail")

    acquire_calls = 0

    async def fake_build_request(context):
        return _acquisition_request()

    async def fake_acquire(request):
        # The only faked boundary: return a browser-fetched but still-empty page,
        # so real extraction keeps producing a budget-aware retry each rung.
        nonlocal acquire_calls
        acquire_calls += 1
        return _acquisition("browser")

    monkeypatch.setattr(stage, "build_acquisition_request", fake_build_request)
    monkeypatch.setattr(stage, "acquire", fake_acquire)
    monkeypatch.setattr(extraction_loop, "acquire", fake_acquire)

    context = URLProcessingContext(
        session=db_session,
        run=run,
        url=_JOB_URL,
        config=URLProcessingConfig(),
        url_timeout_seconds=120.0,
        started_at_monotonic=0.0,
        requested_fields=["title"],
        surface="job_detail",
    )
    # Initial pass is an HTTP (non-browser) fetch that stays empty; extraction
    # emits the real first RetryRequest.
    initial = _acquisition("curl_cffi")
    fetched = FetchedURLStage(
        context=context, acquisition_result=initial, url_metrics={}
    )
    first_result, _rules = await stage._extract_records_for_acquisition(
        context, fetched
    )
    # The retry request is produced by real ``_job_retry_request`` code.
    assert first_result.retry_request is not None
    assert first_result.retry_request.required is True
    assert first_result.retry_request.max_attempts == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP

    result = await stage.retry_extraction_request_with_browser(
        context, fetched, result=first_result
    )

    # The ladder climbed the FULL rung budget (2), not just rung 1: after browser
    # rung 1, ``_job_retry_request`` still emitted a required retry (finding 2),
    # and the pipeline honestly stopped once the budget was spent.
    assert acquire_calls == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    assert context.browser_escalation_count == CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    assert CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP == 2
    assert result.verdict == "empty"
