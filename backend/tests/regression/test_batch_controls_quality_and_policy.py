"""test_batch_runtime cases split by public behavior."""

from __future__ import annotations

from app.core.config.run_events import RunEventKind
from tests.regression.batch_runtime_test_support import (
    AsyncSession,
    CONTROL_REQUEST_KILL,
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    PageAcquisitionResult,
    ROBOTS_ALLOWED,
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    RobotsPolicyResult,
    URLProcessingResult,
    _detail_html,
    asyncio,
    batch_runtime_module,
    create_crawl_run,
    get_run_records,
    process_run,
    pytest,
    set_control_request,
)


@pytest.fixture(autouse=True)
def _disable_run_event_persistence(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _record(**_kwargs) -> None:
        return None

    monkeypatch.setattr(batch_runtime_module.run_event_timeline, "record", _record)


@pytest.mark.asyncio
@pytest.mark.regression
@pytest.mark.parametrize(
    ("control_request", "expected_status"),
    [
        (CONTROL_REQUEST_PAUSE, CrawlStatus.PAUSED.value),
        (CONTROL_REQUEST_KILL, CrawlStatus.KILLED.value),
    ],
)
async def test_parallel_process_run_honors_control_request(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
    control_request: str,
    expected_status: str,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", True)
    patch_settings(url_batch_concurrency=2, browser_runtime_context_capacity=2)
    monkeypatch.setattr(
        batch_runtime_module.settings,
        "system_max_concurrent_urls",
        2,
        raising=False,
    )
    urls = [f"https://example.com/products/{suffix}" for suffix in ("a", "b", "c", "d")]
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "fetch_profile": {"fetch_mode": "http_only"},
                "urls": urls,
            },
        },
    )
    started: list[str] = []

    async def _fake_process_single_url(*args, **kwargs):
        url = str(kwargs.get("url") or "")
        started.append(url)
        if url.endswith("/a"):
            # A concurrent session requests pause/kill during the first URL.
            set_control_request(kwargs["run"], control_request)
            await kwargs["session"].commit()
        else:
            # In-flight URLs run to completion after the stop is observed.
            await asyncio.sleep(1.0)
        return URLProcessingResult(
            records=[], verdict="success", url_metrics={"record_count": 0}
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_process_single_url
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == expected_status
    assert run.queue_owner is None
    # The two workers genuinely ran in parallel...
    assert len(started) >= 2
    # ...and the stop was observed before the fourth URL was pulled (the
    # one-second in-flight sleeps keep the checkpoint deterministic even when
    # the control-request commit is slow on a busy local database).
    assert len(started) <= 3
    assert "https://example.com/products/d" not in started


@pytest.mark.asyncio
@pytest.mark.regression
async def test_parallel_process_run_stops_after_max_records(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "celery_dispatch_enabled", True)
    patch_settings(url_batch_concurrency=2, browser_runtime_context_capacity=2)
    monkeypatch.setattr(
        batch_runtime_module.settings,
        "system_max_concurrent_urls",
        2,
        raising=False,
    )
    urls = [f"https://example.com/products/{idx}" for idx in range(6)]
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "settings": {
                "fetch_profile": {"fetch_mode": "http_only"},
                "max_records": 3,
                "urls": urls,
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        del args, kwargs
        return URLProcessingResult(
            records=[{}, {}],
            verdict="success",
            url_metrics={"record_count": 2},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_process_single_url
    )
    recorded: list[tuple[int, object]] = []

    async def _record(*, run_id: int, fact, **_kwargs) -> None:
        recorded.append((run_id, fact))

    monkeypatch.setattr(batch_runtime_module.run_event_timeline, "record", _record)

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert any(
        event.kind == RunEventKind.RUN_LIMIT_REACHED
        and event.facts == {"limit_name": "max_records", "limit_value": 3}
        for _run_id, event in recorded
    )
    assert run.result_summary["record_count"] >= 3


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_aggregates_quality_summary_from_url_metrics(
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
                    "https://example.com/products/widget-prime",
                    "https://example.com/products/widget-lite",
                ],
            },
        },
    )

    async def _fake_process_single_url(*args, **kwargs):
        url = str(kwargs.get("url") or "")
        if "lite" in url:
            return URLProcessingResult(
                records=[],
                verdict="partial",
                url_metrics={
                    "record_count": 0,
                    "quality_summary": {
                        "score": 0.4,
                        "level": "low",
                        "requested_fields_total": 4,
                        "requested_fields_found_best": 2,
                        "variant_completeness": {
                            "applicable": True,
                            "complete": False,
                        },
                    },
                },
            )
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={
                "record_count": 0,
                "quality_summary": {
                    "score": 0.9,
                    "level": "high",
                    "requested_fields_total": 4,
                    "requested_fields_found_best": 4,
                    "variant_completeness": {
                        "applicable": True,
                        "complete": True,
                    },
                },
            },
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.result_summary["quality_summary"] == {
        "level": "medium",
        "score": 0.65,
        "scored_urls": 2,
        "level_counts": {
            "high": 1,
            "low": 1,
        },
        "listing_incomplete_urls": 0,
        "variant_incomplete_urls": 1,
        "requested_fields_total": 4,
        "requested_fields_found_best": 4,
    }


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_blocks_disallowed_url_before_acquire(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/private/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": True},
        },
    )

    async def _disallow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=False,
            outcome="disallowed",
            robots_url="https://example.com/robots.txt",
        )

    async def _unexpected_acquire(request):
        raise AssertionError(f"acquire should not run for {request.url}")

    monkeypatch.setattr(
        "app.crawl.pipeline.extraction_loop.check_url_crawlability", _disallow
    )
    monkeypatch.setattr(
        "app.crawl.pipeline.extraction_loop.acquire", _unexpected_acquire
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "blocked"
    assert run.result_summary["url_verdicts"] == ["blocked"]
    assert total == 0
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_ignores_robots_when_disabled_in_settings(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/private/widget-prime",
            "surface": "ecommerce_detail",
            "settings": {"respect_robots_txt": False},
        },
    )
    acquire_calls: list[str] = []

    async def _disallow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=False,
            outcome="disallowed",
            robots_url="https://example.com/robots.txt",
        )

    async def _fake_acquire(request):
        acquire_calls.append(request.url)
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr(
        "app.crawl.pipeline.extraction_loop.check_url_crawlability", _disallow
    )
    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert acquire_calls == ["https://example.com/private/widget-prime"]
    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "robots_outcome", [ROBOTS_ALLOWED, ROBOTS_MISSING, ROBOTS_FETCH_FAILURE]
)
@pytest.mark.regression
async def test_process_run_continues_when_robots_allows_or_fails_open(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    robots_outcome: str,
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
    acquire_calls: list[str] = []

    async def _allow(url: str, *, user_agent: str = "*") -> RobotsPolicyResult:
        del user_agent
        return RobotsPolicyResult(
            allowed=True,
            outcome=robots_outcome,
            robots_url="https://example.com/robots.txt",
            error="timeout" if robots_outcome == ROBOTS_FETCH_FAILURE else None,
        )

    async def _fake_acquire(request):
        acquire_calls.append(request.url)
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr(
        "app.crawl.pipeline.extraction_loop.check_url_crawlability", _allow
    )
    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert acquire_calls == ["https://example.com/products/widget-prime"]
    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_enforces_url_timeout_from_settings(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/slow-widget",
            "surface": "ecommerce_detail",
            "settings": {"url_timeout_seconds": 0.01},
        },
    )

    async def _slow_process_single_url(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.05)
        raise AssertionError("timeout should fire before this returns")

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _slow_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "error"
    assert run.result_summary["url_verdicts"] == ["error"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_default_timeout_includes_acquisition_slack(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/slow-widget",
            "surface": "ecommerce_detail",
        },
    )

    patch_settings(
        url_process_timeout_seconds=0.01,
        url_process_timeout_buffer_seconds=0.08,
        acquisition_attempt_timeout_seconds=0.08,
    )

    async def _slow_process_single_url(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.05)
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _slow_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert run.result_summary["url_verdicts"] == ["success"]
