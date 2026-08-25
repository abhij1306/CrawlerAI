"""test_batch_runtime cases split by public behavior."""

from __future__ import annotations

import asyncio

from tests.regression.batch_runtime_test_support import (
    AsyncSession,
    CommitTrackingSession,
    CrawlLog,
    CrawlRunSettings,
    PageAcquisitionResult,
    PendingRollbackError,
    SimpleNamespace,
    URLProcessingResult,
    _parallel_url_concurrency,
    _parallel_worker_record_limit,
    batch_runtime_module,
    create_crawl_run,
    extraction_loop,
    pytest,
    record_extraction_stage,
    select,
)


@pytest.mark.unit
def test_parallel_worker_record_limit_bounds_each_worker_budget() -> None:
    assert _parallel_worker_record_limit(5, 2) == 3
    assert _parallel_worker_record_limit(100, 8) == 13
    assert _parallel_worker_record_limit(1, 2) == 1


@pytest.mark.unit
def test_parallel_url_concurrency_respects_browser_runtime_capacity(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", True)
    patch_settings(
        url_batch_concurrency=8,
        browser_runtime_context_capacity=3,
    )
    settings_view = CrawlRunSettings.from_value(
        {"fetch_profile": {"fetch_mode": "auto"}}
    )

    assert _parallel_url_concurrency(10, settings_view) == 3


@pytest.mark.unit
def test_parallel_url_concurrency_does_not_browser_cap_http_only(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", True)
    monkeypatch.setattr(batch_runtime_module.settings, "system_max_concurrent_urls", 8)
    patch_settings(
        url_batch_concurrency=8,
        browser_runtime_context_capacity=3,
    )
    settings_view = CrawlRunSettings.from_value(
        {"fetch_profile": {"fetch_mode": "http_only"}}
    )

    assert _parallel_url_concurrency(10, settings_view) == 8


@pytest.mark.unit
def test_parallel_url_concurrency_is_serial_when_celery_dispatch_is_disabled(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", False)
    monkeypatch.setattr(batch_runtime_module.settings, "system_max_concurrent_urls", 8)
    patch_settings(url_batch_concurrency=8, browser_runtime_context_capacity=8)
    settings_view = CrawlRunSettings.from_value(
        {"fetch_profile": {"fetch_mode": "http_only"}}
    )

    assert _parallel_url_concurrency(10, settings_view) == 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_parallel_execute_cancels_workers_when_coordination_fails() -> None:
    class FailingState(batch_runtime_module._ParallelRunState):
        def start_workers(self) -> None:
            self.workers = [asyncio.create_task(asyncio.Event().wait())]

        def raise_worker_error(self) -> None:
            raise RuntimeError("coordination failed")

    state = FailingState(
        session=SimpleNamespace(),
        run=SimpleNamespace(id=101),
        pending_items=[],
        total_urls=1,
        progress_state=SimpleNamespace(persisted_record_count=0),
        max_records=1,
        record_limit=1,
        url_timeout_seconds=1.0,
        owner="test",
        concurrency=1,
        commit_gate=SimpleNamespace(),
    )

    with pytest.raises(RuntimeError, match="coordination failed"):
        await state.execute()

    assert state.stop_event.is_set()
    assert all(worker.cancelled() for worker in state.workers)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_acquisition_stage_releases_db_session_before_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CommitTrackingSession()
    context = SimpleNamespace(
        session=session,
        run=SimpleNamespace(id=101),
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=[],
        config=SimpleNamespace(persist_logs=False),
    )

    async def _fake_build_acquisition_request(ctx):
        ctx.session.checked_out = True
        return SimpleNamespace(url=ctx.url)

    acquire_called = False

    async def _fake_acquire(request):
        nonlocal acquire_called
        acquire_called = True
        assert session.checked_out is False
        assert session.commit_count >= 1
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html></html>",
            method="test",
            status_code=200,
        )

    monkeypatch.setattr(
        extraction_loop,
        "build_acquisition_request",
        _fake_build_acquisition_request,
    )
    monkeypatch.setattr(extraction_loop, "acquire", _fake_acquire)

    await extraction_loop._run_acquisition_stage(
        context,
        prefetched_acquisition=None,
    )

    assert acquire_called is True


@pytest.mark.asyncio
@pytest.mark.regression
async def test_extraction_memory_pending_rollback_is_not_swallowed() -> None:
    class _Nested:
        async def __aenter__(self):
            raise PendingRollbackError("flush failed earlier")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    class _Session:
        is_active = False

        def begin_nested(self):
            return _Nested()

        def add(self, *_args, **_kwargs):
            raise AssertionError("poisoned sessions must not write diagnostics")

        async def flush(self):
            raise AssertionError("poisoned sessions must not flush diagnostics")

    context = SimpleNamespace(
        session=_Session(),
        run=SimpleNamespace(id=101, extraction_release_snapshot_id=None),
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        config=SimpleNamespace(persist_logs=True),
    )
    extracted = SimpleNamespace(
        fetched=SimpleNamespace(
            acquisition_result=PageAcquisitionResult(
                request=SimpleNamespace(url=context.url),
                final_url=context.url,
                html="<html></html>",
                method="test",
                status_code=200,
            )
        ),
        result=SimpleNamespace(),
    )

    with pytest.raises(PendingRollbackError):
        await extraction_loop._record_extraction_memory(
            context,
            extracted,
            url_result_id=1,
        )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_extraction_stage_releases_db_session_after_selector_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = CommitTrackingSession()
    context = SimpleNamespace(
        session=session,
        run=SimpleNamespace(id=102),
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
        requested_fields=[],
        browser_escalation_count=0,
        escalation_attempts=[],
        # This test only asserts session release around the extraction thread;
        # the LEARN-ONCE gate is latched off (it has its own component tests).
        learn_once_attempted=True,
    )
    acquisition_result = PageAcquisitionResult(
        request=SimpleNamespace(url=context.url),
        final_url=context.url,
        html="<html></html>",
        method="test",
        status_code=200,
    )
    fetched = SimpleNamespace(
        context=context,
        acquisition_result=acquisition_result,
        url_metrics={},
    )

    async def _fake_load_selector_rules(ctx, page_url: str):
        del page_url
        ctx.session.checked_out = True
        return []

    async def _fake_run_record_extraction(ctx, *, acquisition_result, selector_rules):
        del acquisition_result, selector_rules
        assert ctx.session.checked_out is False
        assert ctx.session.commit_count >= 1
        return URLProcessingResult(records=[], verdict="empty")

    monkeypatch.setattr(
        record_extraction_stage,
        "_load_selector_rules",
        _fake_load_selector_rules,
    )
    monkeypatch.setattr(
        record_extraction_stage,
        "_run_record_extraction",
        _fake_run_record_extraction,
    )

    (
        result,
        selector_rules,
    ) = await record_extraction_stage._extract_records_for_acquisition(
        context,
        fetched,
    )

    assert result.verdict == "empty"
    assert selector_rules == []


@pytest.mark.asyncio
@pytest.mark.regression
async def test_persist_url_failure_log_prefixes_url_for_parallel_ui(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {"urls": ["https://example.com/products/missing-widget"]},
        },
    )
    url = "https://example.com/products/missing-widget"

    await batch_runtime_module._persist_url_failure_log(
        db_session,
        run_id=run.id,
        url=url,
        exc=RuntimeError("navigation failed"),
        log_message=f"URL processing failed for {url}: RuntimeError: navigation failed",
    )
    logs = (
        (
            await db_session.execute(
                select(CrawlLog).where(CrawlLog.run_id == run.id).order_by(CrawlLog.id)
            )
        )
        .scalars()
        .all()
    )

    if logs[-1].level != "warning":
        pytest.fail(f"expected warning log, got {logs[-1].level!r}")
    expected_prefix = f"[url:{url}] URL processing failed for {url}"
    if not logs[-1].message.startswith(expected_prefix):
        pytest.fail(f"expected URL-prefixed failure log, got {logs[-1].message!r}")
