from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio

from app.models.crawl_settings import CrawlRunSettings
from app.services.crawl import batch_runtime as batch_runtime_module
from app.services.crawl.batch_runtime import (
    _parallel_url_concurrency,
    _parallel_worker_record_limit,
    process_run,
)
from app.services.config.sitemap import SITEMAP_DEFAULT_MAX_URLS
from app.services.acquisition.acquirer import AcquisitionResult
from app.services.crawl.crud import create_crawl_run, get_run_records
from app.models.crawl_run import CrawlLog, CrawlRecord
from app.services.pipeline.types import URLProcessingResult
from app.services.robots_policy import (
    ROBOTS_ALLOWED,
    ROBOTS_FETCH_FAILURE,
    ROBOTS_MISSING,
    RobotsPolicyResult,
)
from sqlalchemy import select
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest_asyncio.fixture(autouse=True)
async def _use_test_session_local_for_parallel_urls(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(batch_runtime_module, "SessionLocal", session_factory)


def _detail_html() -> str:
    return """
    <html>
      <head>
        <script type="application/ld+json">
        {
          "@context": "https://schema.org",
          "@type": "Product",
          "name": "Widget Prime",
          "description": "A deterministic widget",
          "sku": "W-100",
          "offers": {"price": "19.99", "availability": "InStock"}
        }
        </script>
      </head>
      <body><h1>Widget Prime</h1></body>
    </html>
    """


@pytest.mark.unit
def test_parallel_worker_record_limit_bounds_each_worker_budget() -> None:
    assert _parallel_worker_record_limit(5, 2) == 3
    assert _parallel_worker_record_limit(100, 8) == 13
    assert _parallel_worker_record_limit(1, 2) == 1


@pytest.mark.unit
def test_parallel_url_concurrency_respects_browser_runtime_capacity(
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=8, browser_runtime_context_capacity=3)
    settings_view = CrawlRunSettings.from_value(
        {"fetch_profile": {"fetch_mode": "auto"}}
    )

    assert _parallel_url_concurrency(10, settings_view) == 3


@pytest.mark.unit
def test_parallel_url_concurrency_does_not_browser_cap_http_only(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    monkeypatch.setattr(batch_runtime_module.settings, "system_max_concurrent_urls", 8)
    patch_settings(url_batch_concurrency=8, browser_runtime_context_capacity=3)
    settings_view = CrawlRunSettings.from_value(
        {"fetch_profile": {"fetch_mode": "http_only"}}
    )

    assert _parallel_url_concurrency(10, settings_view) == 8


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
        await db_session.execute(
            select(CrawlLog).where(CrawlLog.run_id == run.id).order_by(CrawlLog.id)
        )
    ).scalars().all()

    if logs[-1].level != "warning":
        pytest.fail(f"expected warning log, got {logs[-1].level!r}")
    expected_prefix = f"[url:{url}] URL processing failed for {url}"
    if not logs[-1].message.startswith(expected_prefix):
        pytest.fail(f"expected URL-prefixed failure log, got {logs[-1].message!r}")


def _listing_shell_html() -> str:
    return "<html><body><h1>Empty category</h1></body></html>"


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
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

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
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_listing_shell_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

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
        "app.services.crawl.batch_runtime.process_single_url",
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
        "app.services.crawl.batch_runtime.process_single_url",
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
    seen: list[tuple[str, int]] = []

    async def _fake_process_single_url(*args, **kwargs):
        del args
        seen.append((str(kwargs.get("url") or ""), id(kwargs["session"])))
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)

    assert [url for url, _session_id in seen] == [
        "https://example-one.com/products/one",
        "https://example-two.com/products/two",
        "https://example-three.com/products/three",
    ]
    assert {session_id for _url, session_id in seen} == {id(db_session)}


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_uses_url_batch_concurrency_setting(
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
        "app.services.crawl.batch_runtime.process_single_url",
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
    patch_settings(url_batch_concurrency=3, browser_runtime_context_capacity=3)
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
        "app.services.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )
    session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
    )
    monkeypatch.setattr("app.services.crawl.batch_runtime.SessionLocal", session_factory)

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
        "app.services.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )
    session_factory = async_sessionmaker(
        bind=db_session.bind,
        expire_on_commit=False,
    )
    monkeypatch.setattr("app.services.crawl.batch_runtime.SessionLocal", session_factory)

    await process_run(db_session, run.id)
    logs = (
        await db_session.execute(
            select(CrawlLog).where(CrawlLog.run_id == run.id).order_by(CrawlLog.id)
        )
    ).scalars().all()
    messages = [log.message for log in logs]

    assert any(
        f"URL processing failed for {failing_url}: TimeoutError: "
        "Browser navigation stage exceeded timeout_seconds=45.00" in message
        for message in messages
    )
    assert not any(
        f"URL processing timed out for {failing_url}" in message
        for message in messages
    )


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
        "app.services.crawl.batch_runtime.process_single_url",
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

    monkeypatch.setattr("app.services.pipeline.extraction_loop.check_url_crawlability", _disallow)
    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _unexpected_acquire)

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
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.check_url_crawlability", _disallow)
    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    rows, total = await get_run_records(db_session, run.id, 1, 20)

    assert acquire_calls == ["https://example.com/private/widget-prime"]
    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert total == 1
    assert rows[0].data["title"] == "Widget Prime"


@pytest.mark.asyncio
@pytest.mark.parametrize("robots_outcome", [ROBOTS_ALLOWED, ROBOTS_MISSING, ROBOTS_FETCH_FAILURE])
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
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.check_url_crawlability", _allow)
    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

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
        "app.services.crawl.batch_runtime.process_single_url",
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
        url_process_timeout_buffer_seconds=0.03,
        acquisition_attempt_timeout_seconds=0.02,
    )

    async def _slow_process_single_url(*args, **kwargs):
        del args, kwargs
        await asyncio.sleep(0.025)
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _slow_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "success"
    assert run.result_summary["url_verdicts"] == ["success"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_preserves_requested_fields_for_every_url(
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
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "requested_fields": ["materials"],
        },
    )
    captured_requested_fields: list[list[str]] = []

    async def _fake_acquire(request):
        captured_requested_fields.append(list(request.requested_fields))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_requested_fields == [["materials"], ["materials"]]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_preserves_proxy_list_for_every_url(
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
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "settings": {
                "proxy_enabled": True,
                "proxy_list": ["http://proxy-a", "http://proxy-b"],
                "proxy_profile": {
                    "enabled": True,
                    "proxy_list": ["http://proxy-a", "http://proxy-b"],
                },
            },
        },
    )
    captured_proxy_lists: list[list[str]] = []

    async def _fake_acquire(request):
        captured_proxy_lists.append(list(request.proxy_list))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_proxy_lists == [
        ["http://proxy-a", "http://proxy-b"],
        ["http://proxy-a", "http://proxy-b"],
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_preserves_exact_requested_section_labels_for_every_url(
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
            "urls": [
                "https://example.com/products/widget-1",
                "https://example.com/products/widget-2",
            ],
            "surface": "ecommerce_detail",
            "additional_fields": ["Features & Benefits"],
        },
    )
    captured_requested_fields: list[list[str]] = []

    async def _fake_acquire(request):
        captured_requested_fields.append(list(request.requested_fields))
        return AcquisitionResult(
            request=request,
            final_url=request.url,
            html=_detail_html(),
            method="test",
            status_code=200,
        )

    monkeypatch.setattr("app.services.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    assert captured_requested_fields == [
        ["Features & Benefits"],
        ["Features & Benefits"],
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_resolves_urls_from_sitemap_settings(
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
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
                "sitemap_filter_keyword": "collections",
                "sitemap_max_urls": 2,
            },
        },
    )
    resolved_inputs: list[tuple[str, str, int, bool]] = []
    processed_urls: list[str] = []

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        resolved_inputs.append(
            (domain, filter_keyword, max_urls, allow_homepage_fallback)
        )
        return [
            "https://example.com/collections/a",
            "https://example.com/collections/b",
        ]

    async def _fake_process_single_url(*args, **kwargs):
        del args
        url = str(kwargs.get("url") or "")
        processed_urls.append(url)
        return URLProcessingResult(
            records=[],
            verdict="success",
            url_metrics={"record_count": 0},
        )

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert resolved_inputs == [("example.com", "collections", 2, False)]
    assert processed_urls == [
        "https://example.com/collections/a",
        "https://example.com/collections/b",
    ]
    assert run.result_summary["url_count"] == 2
    assert run.result_summary["resolved_url_list"] == processed_urls


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_defaults_bad_sitemap_max_urls(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
                "sitemap_max_urls": "not-a-number",
            },
        },
    )
    resolved_inputs: list[int] = []

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        del domain, filter_keyword, allow_homepage_fallback
        resolved_inputs.append(max_urls)
        return ["https://example.com/collections/a"]

    async def _fake_process_single_url(*args, **kwargs):
        del args, kwargs
        return URLProcessingResult(records=[], verdict="success")

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)

    assert resolved_inputs == [SITEMAP_DEFAULT_MAX_URLS]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_marks_failed_when_sitemap_resolution_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_listing",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
                "sitemap_filter_keyword": "collections",
            },
        },
    )

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        del domain, filter_keyword, max_urls, allow_homepage_fallback
        raise ValueError(
            "Sitemap fetch failed: https://example.com/sitemap.xml returned HTTP 503"
        )

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)
    logs = (
        await db_session.execute(
            select(CrawlLog.message).where(CrawlLog.run_id == run.id)
        )
    ).scalars().all()

    assert run.status == "failed"
    assert run.completed_at is not None
    assert (
        run.result_summary["error"]
        == "ValueError: Sitemap fetch failed: https://example.com/sitemap.xml returned HTTP 503"
    )
    assert logs == [
        "ValueError: Sitemap fetch failed: https://example.com/sitemap.xml returned HTTP 503"
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_batch_run_enables_homepage_fallback_for_auto_surface(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "auto",
            "url": "https://example.com",
            "settings": {
                "sitemap_domain": "example.com",
            },
        },
    )
    resolved_flags: list[bool] = []

    async def _fake_resolve_category_urls_from_sitemap(
        domain: str,
        filter_keyword: str,
        max_urls: int,
        allow_homepage_fallback: bool = False,
    ) -> list[str]:
        del domain, filter_keyword, max_urls
        resolved_flags.append(allow_homepage_fallback)
        return ["https://example.com/women"]

    async def _fake_process_single_url(*args, **kwargs):
        del args, kwargs
        return URLProcessingResult(records=[], verdict="success")

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.resolve_category_urls_from_sitemap",
        _fake_resolve_category_urls_from_sitemap,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _fake_process_single_url,
    )

    await process_run(db_session, run.id)

    assert resolved_flags == [True]


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
        "app.services.crawl.batch_runtime.process_single_url",
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
async def test_process_run_continues_when_failure_log_persistence_fails(
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

    async def _failing_failure_log(*args, **kwargs):
        del args, kwargs
        raise PendingRollbackError("failure log flush failed")

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _failing_process_single_url,
    )
    monkeypatch.setattr(
        "app.services.crawl.batch_runtime._persist_url_failure_log",
        _failing_failure_log,
    )

    await process_run(db_session, run.id)
    await db_session.refresh(run)

    assert run.status == "completed"
    assert run.result_summary["extraction_verdict"] == "partial"
    assert run.result_summary["url_verdicts"] == ["error", "success"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_continues_when_failure_log_persistence_raises_non_sql_exception(
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

    async def _failing_failure_log(*args, **kwargs):
        del args, kwargs
        raise ValueError("unexpected recovery failure")

    monkeypatch.setattr(
        "app.services.crawl.batch_runtime.process_single_url",
        _failing_process_single_url,
    )
    monkeypatch.setattr(
        "app.services.crawl.batch_runtime._persist_url_failure_log",
        _failing_failure_log,
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
        "app.services.crawl.batch_runtime.process_single_url",
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
        "app.services.crawl.batch_runtime.process_single_url",
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
