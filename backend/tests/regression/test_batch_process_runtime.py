"""test_batch_runtime cases split by public behavior."""

from __future__ import annotations

from app.core.config.run_events import RunEventKind
from tests.regression.batch_runtime_test_support import (
    AsyncSession,
    PageAcquisitionResult,
    URLProcessingResult,
    _detail_html,
    _listing_shell_html,
    async_sessionmaker,
    asyncio,
    batch_runtime_module,
    create_crawl_run,
    get_run_records,
    process_run,
    pytest,
)


@pytest.fixture(autouse=True)
def _disable_run_event_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _record(**_kwargs) -> None:
        return None

    monkeypatch.setattr(batch_runtime_module.run_event_timeline, "record", _record)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_persists_detail_records(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget-prime",
            "surface": "ecommerce_detail",
        },
    )

    async def _fake_acquire(request):
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.last_heartbeat_at is not None
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"
    assert rows[0].data["price"] == "19.99"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_marks_empty_listing_as_listing_detection_failed(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/category/widgets",
            "surface": "ecommerce_listing",
        },
    )

    async def _fake_acquire(request):
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_listing_shell_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "listing_detection_failed"
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_tracks_failure_reason_counts(
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
                    "https://example.com/search?q=widget",
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        url = str(kwargs.get("url") or "")
        if "search" in url:
            return URLProcessingResult(
                records=[],
                verdict="empty",
                url_metrics={"record_count": 0, "failure_reason": "non_detail_seed"},
            )
        return URLProcessingResult(
            records=[],
            verdict="blocked",
            url_metrics={"record_count": 0, "failure_reason": "challenge_shell"},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.result_summary["acquisition_summary"]["failure_reasons"] == {
        "non_detail_seed": 1,
        "challenge_shell": 1,
    }


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_starts_with_fresh_batch_progress(
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
                    "https://example.com/products/stale-a",
                    "https://example.com/products/stale-b",
                ],
            },
        },
    )
    run.update_summary(
        url_verdicts=["success", "blocked"],
        completed_urls=2,
        processed_urls=2,
        verdict_counts={"success": 1, "blocked": 1},
        acquisition_summary={"methods": {"stale": 2}},
    )
    await db_session.commit()

    async def _fake_process_single_url(*args, **kwargs):
        url = str(kwargs.get("url") or "")
        if "stale-a" in url:
            return URLProcessingResult(
                records=[],
                verdict="error",
                url_metrics={"record_count": 0, "method": "fresh"},
            )
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0, "method": "fresh"},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.result_summary["url_verdicts"] == ["error", "success"]
    assert run.result_summary["completed_urls"] == 2
    assert run.result_summary["verdict_counts"] == {"error": 1, "success": 1}
    assert run.result_summary["acquisition_summary"]["methods"] == {"fresh": 2}


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_defaults_to_sequential_batch_url_processing(
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
                    "https://example-one.com/products/one",
                    "https://example-two.com/products/two",
                    "https://example-three.com/products/three",
                ],
            },
        },
    )
    seen: list[tuple[str, object]] = []

    async def _fake_process_single_url(*args, **kwargs):
        del args
        seen.append((str(kwargs.get("url") or ""), kwargs["session"]))
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

    assert [url for url, _session_id in seen] == [
        "https://example-one.com/products/one",
        "https://example-two.com/products/two",
        "https://example-three.com/products/three",
    ]
    assert len({id(session) for _url, session in seen}) == 3
    assert all(session is not db_session for _url, session in seen)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_uses_url_batch_concurrency_setting(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", True)
    patch_settings(
        url_batch_concurrency=2,
        browser_runtime_context_capacity=2,
    )
    monkeypatch.setattr(
        batch_runtime_module.settings,
        "system_max_concurrent_urls",
        2,
        raising=False,
    )
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "urls": [
                    "https://one.example.com/products/one",
                    "https://two.example.com/products/two",
                    "https://three.example.com/products/three",
                ],
            },
        },
    )
    active = 0
    max_active = 0
    second_active = asyncio.Event()

    async def _fake_process_single_url(*args, **kwargs):
        nonlocal active, max_active
        del args
        active += 1
        max_active = max(max_active, active)
        if active > 1:
            second_active.set()
        try:
            if active == 1:
                await asyncio.wait_for(second_active.wait(), timeout=0.5)
            else:
                await asyncio.sleep(0.01)
        finally:
            active -= 1
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0, "url": str(kwargs.get("url") or "")},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert max_active == 2
    assert run.result_summary["url_verdicts"] == ["success", "success", "success"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_runs_same_domain_batch_urls_in_parallel(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", True)
    patch_settings(
        url_batch_concurrency=3,
        browser_runtime_context_capacity=3,
    )
    monkeypatch.setattr(
        batch_runtime_module.settings,
        "system_max_concurrent_urls",
        3,
        raising=False,
    )
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "fetch_profile": {"fetch_mode": "http_only"},
                "url_batch_concurrency": 3,
                "urls": [
                    "https://example.com/products/one",
                    "https://example.com/products/two",
                    "https://example.com/products/three",
                ],
            },
        },
    )
    active = 0
    max_active = 0
    second_active = asyncio.Event()

    async def _fake_process_single_url(*args, **kwargs):
        nonlocal active, max_active
        del args, kwargs
        active += 1
        max_active = max(max_active, active)
        if active > 1:
            second_active.set()
        try:
            if active == 1:
                try:
                    await asyncio.wait_for(second_active.wait(), timeout=0.5)
                except asyncio.TimeoutError:
                    # Expected when concurrency is not opened by the runtime.
                    pass
            else:
                await asyncio.sleep(0.01)
        finally:
            active -= 1
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )
    session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
    )
    monkeypatch.setattr("app.crawl.batch_runtime.SessionLocal", session_factory)

    await process_run(db_session, run.id)

    assert max_active > 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_parallel_run_does_not_mislabel_nested_timeout_as_url_deadline(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=2, browser_runtime_context_capacity=2)
    monkeypatch.setattr(
        batch_runtime_module.settings,
        "system_max_concurrent_urls",
        2,
        raising=False,
    )
    failing_url = "https://example.com/products/browser-timeout"
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "fetch_profile": {"fetch_mode": "http_only"},
                "url_batch_concurrency": 2,
                "urls": [
                    failing_url,
                    "https://example.com/products/widget-prime",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        if kwargs["url"] == failing_url:
            raise TimeoutError(
                "Browser navigation stage exceeded timeout_seconds=45.00"
            )
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )
    session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
    )
    monkeypatch.setattr("app.crawl.batch_runtime.SessionLocal", session_factory)
    recorded: list[tuple[int, object]] = []

    async def _record(*, run_id: int, fact, **_kwargs) -> None:
        recorded.append((run_id, fact))

    monkeypatch.setattr(batch_runtime_module.run_event_timeline, "record", _record)

    await process_run(db_session, run.id)
    failures = [
        fact for _run_id, fact in recorded if fact.kind == RunEventKind.URL_FAILED
    ]

    assert [event.url for event in failures] == [failing_url]
    assert failures[0].reason_code == "exception"
    assert failures[0].facts == {"exception_type": "TimeoutError"}
