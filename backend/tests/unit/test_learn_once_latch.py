from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.crawl.pipeline import record_extraction_stage as stage
from app.crawl.pipeline.url_processing_context import URLProcessingContext
from app.core.config.cascade import CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
from app.extraction.contracts import CapabilityRequest, ExtractionResult
from app.extraction.surfaces import Surface

pytestmark = pytest.mark.unit


def _acquisition_result(*, method: str = "curl_cffi") -> PageAcquisitionResult:
    return PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=1,
            url="https://shop.test/p/1",
            plan=AcquisitionIntent(surface="ecommerce_detail"),
        ),
        final_url="https://shop.test/p/1",
        html="<html></html>",
        method=method,
        status_code=200,
        browser_diagnostics={"browser_attempted": method == "browser"},
    )


def _context() -> URLProcessingContext:
    run = SimpleNamespace(
        id=1,
        settings_view=SimpleNamespace(llm_enabled=lambda: True),
        extraction_release_snapshot_id=None,
    )
    return URLProcessingContext(
        session=SimpleNamespace(),
        run=run,  # type: ignore[arg-type]
        url="https://shop.test/p/1",
        config=SimpleNamespace(max_records=10),  # type: ignore[arg-type]
        url_timeout_seconds=120.0,
        started_at_monotonic=0.0,
        requested_fields=["title"],
        surface="ecommerce_detail",
    )


def _empty_result(*, retry_required: bool, max_attempts: int = 1) -> ExtractionResult:
    retry = (
        CapabilityRequest(
            required=True,
            reason="empty_extraction",
            required_artifacts=("rendered_html",),
            max_attempts=max_attempts,
        )
        if retry_required
        else None
    )
    return ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        records=(),
        verdict="empty",
        retry_request=retry,
    )


@pytest.mark.asyncio
async def test_maybe_learn_once_defers_when_browser_retry_pending(monkeypatch) -> None:
    # Finding 5: on the HTTP pass, when a browser retry is still pending, learning
    # must be deferred (not attempted) so it only fires after the final attempt.
    calls: list[int] = []

    async def fake_learn(*_args, **_kwargs):
        calls.append(1)
        return False

    monkeypatch.setattr(stage, "request_from_acquisition_result", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.crawl.pipeline.learn_once.learn_recipe_after_extraction", fake_learn
    )

    context = _context()
    await stage._maybe_learn_once(
        context,
        acquisition_result=_acquisition_result(method="curl_cffi"),
        selector_rules=[],
        result=_empty_result(retry_required=True),
    )

    assert calls == []
    assert context.learn_once_attempted is False


@pytest.mark.asyncio
async def test_maybe_learn_once_latches_after_first_attempt(monkeypatch) -> None:
    # Finding 5: once learning has been attempted (post-browser final pass), the
    # latch short-circuits any repeat call threaded through the retry.
    calls: list[int] = []

    async def fake_learn(*_args, **_kwargs):
        calls.append(1)
        return False

    async def fake_snapshot(_context):
        return {}

    monkeypatch.setattr(stage, "_load_runtime_snapshot", fake_snapshot)
    monkeypatch.setattr(stage, "request_from_acquisition_result", lambda *a, **k: None)
    monkeypatch.setattr(stage, "select_active_recipe", lambda *a, **k: None)
    monkeypatch.setattr(
        "app.crawl.pipeline.learn_once.learn_recipe_after_extraction", fake_learn
    )

    context = _context()
    browser_result = _acquisition_result(method="browser")
    final_result = _empty_result(retry_required=False)

    # First call (final attempt, browser already used) attempts learning once.
    await stage._maybe_learn_once(
        context,
        acquisition_result=browser_result,
        selector_rules=[],
        result=final_result,
    )
    # A second call (e.g. threaded through a retry) is short-circuited by the latch.
    await stage._maybe_learn_once(
        context,
        acquisition_result=browser_result,
        selector_rules=[],
        result=final_result,
    )

    assert calls == [1]
    assert context.learn_once_attempted is True


def _budget_context(*, escalation_count: int) -> URLProcessingContext:
    context = _context()
    context.browser_escalation_count = escalation_count
    return context


def test_browser_retry_pending_defers_mid_ladder() -> None:
    # Finding 3: with max_attempts=2 and one browser rung already climbed, a
    # still-required retry means a further rung will run, so learning must be
    # deferred (budget remains: escalation_count 1 < max_attempts 2).
    context = _budget_context(escalation_count=1)
    result = _empty_result(
        retry_required=True, max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    )
    assert (
        stage._browser_retry_pending(
            context,
            _acquisition_result(method="browser"),
            result,
        )
        is True
    )


def test_browser_retry_pending_fires_at_exhaustion() -> None:
    # Finding 3: at the rung budget ceiling (escalation_count == max_attempts) no
    # further rung will run, so learning may fire now.
    context = _budget_context(escalation_count=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP)
    result = _empty_result(
        retry_required=True, max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    )
    assert (
        stage._browser_retry_pending(
            context,
            _acquisition_result(method="browser"),
            result,
        )
        is False
    )


def test_browser_retry_pending_initial_browser_short_circuit() -> None:
    # Finding 3: initial-browser short-circuit — nothing escalated yet
    # (escalation_count == 0) but the first pass already browser-fetched the page,
    # so retry/stage.py climbs NO rung. Learning must be allowed now (not deferred
    # forever) even though a retry is nominally required with budget remaining.
    context = _budget_context(escalation_count=0)
    result = _empty_result(
        retry_required=True, max_attempts=CASCADE_CAPABILITY_MAX_ATTEMPTS_CAP
    )
    assert (
        stage._browser_retry_pending(
            context,
            _acquisition_result(method="browser"),
            result,
        )
        is False
    )
