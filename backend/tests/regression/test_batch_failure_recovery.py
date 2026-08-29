"""test_batch_runtime cases split by public behavior."""

from __future__ import annotations

from app.core.config.run_events import RunEventKind
from app.models.crawl_run import RunEvent
from tests.regression.batch_runtime_test_support import (
    AsyncSession,
    CrawlRecord,
    PendingRollbackError,
    URLProcessingResult,
    batch_runtime_module,
    create_crawl_run,
    get_run_records,
    process_run,
    pytest,
    select,
)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_commits_callback_failure_before_completion(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )

    async def _fake_process_single_url(*_args, **_kwargs):
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    async def _callback_failures(_run_id: int) -> tuple[str, ...]:
        return ("CallbackFailure",)

    monkeypatch.setattr(
        batch_runtime_module,
        "process_single_url",
        _fake_process_single_url,
    )
    monkeypatch.setattr(
        batch_runtime_module,
        "on_run_complete",
        _callback_failures,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    events = (
        (
            await db_session.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run.id)
                .order_by(RunEvent.sequence)
            )
        )
        .scalars()
        .all()
    )

    assert run.status == "completed"
    assert [event.kind for event in events[-2:]] == [
        RunEventKind.RUN_CALLBACK_FAILED.value,
        RunEventKind.RUN_COMPLETED.value,
    ]
    assert events[-2].facts == {"exception_type": "CallbackFailure"}


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_continues_after_sqlalchemy_url_error(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/bad-widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _poisoned_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "bad-widget" in url:
            raise PendingRollbackError("flush failed earlier")
        session = kwargs["session"]
        session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"title": "Widget Prime", "url": url},
                raw_data={},
                discovered_data={},
                source_trace={},
            )
        )
        await session.flush()
        return URLProcessingResult(
            records=[{"title": "Widget Prime", "url": url}],
            verdict="success",
            url_metrics={"record_count": 1},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _poisoned_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_continues_when_failure_event_persistence_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/bad-widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _failing_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "bad-widget" in url:
            raise RuntimeError("extractor failed")
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    async def _failing_failure_event(*args, **kwargs):
        del args, kwargs
        raise PendingRollbackError("failure event flush failed")

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _failing_process_single_url,
    )
    monkeypatch.setattr(
        "app.crawl.batch_runtime._persist_url_failure_event",
        _failing_failure_event,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_continues_when_failure_event_persistence_raises_non_sql_exception(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/bad-widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _failing_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "bad-widget" in url:
            raise RuntimeError("extractor failed")
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    async def _failing_failure_event(*args, **kwargs):
        del args, kwargs
        raise ValueError("unexpected recovery failure")

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _failing_process_single_url,
    )
    monkeypatch.setattr(
        "app.crawl.batch_runtime._persist_url_failure_event",
        _failing_failure_event,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_records_browser_exception_diagnostics_and_continues(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/location-gated",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "location-gated" in url:
            exc = RuntimeError("location popup blocked browser")
            exc.browser_diagnostics = {
                "browser_attempted": True,
                "browser_outcome": "location_required",
                "failure_reason": "location_required",
            }
            raise exc
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert run.result_summary["acquisition_summary"]["failure_reasons"] == {
        "location_required": 1,
    }


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_continues_after_generic_browser_driver_error(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://example.com/products/driver-closed",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    class BrowserDriverError(Exception):
        pass

    async def _fake_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        if "driver-closed" in url:
            exc = BrowserDriverError(
                "Page.content: Connection closed while reading from the driver"
            )
            exc.browser_diagnostics = {
                "browser_attempted": True,
                "browser_outcome": "navigation_failed",
                "failure_reason": "browser_driver_closed",
            }
            raise exc
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert run.result_summary["acquisition_summary"]["failure_reasons"] == {
        "browser_driver_closed": 1,
    }
