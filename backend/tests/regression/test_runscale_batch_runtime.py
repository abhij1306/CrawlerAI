"""Run-lifecycle scalability: queue claiming, resume, bounded run summary."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings as app_settings
from app.core.config.runtime_settings import CELERY_TASK_ID_KEY
from app.crawl.batch_runtime import process_run
from app.crawl.pipeline.run_progress import assemble_run_summary_payload
from app.crawl.crud import create_crawl_run
from app.crawl.pipeline.types import URLProcessingResult
from app.crawl.state import (
    CONTROL_REQUEST_PAUSE,
    CrawlStatus,
    set_control_request,
    update_run_status,
)
from app.crawl.utils import normalize_target_url
from app.models.crawl_run import CrawlRun, CrawlUrlResult, claim_run


async def _make_batch_run(
    db_session: AsyncSession, test_user, urls: list[str]
) -> CrawlRun:
    return await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "batch",
            "surface": "ecommerce_detail",
            "urls": list(urls),
            "settings": {"urls": list(urls)},
        },
    )


def _fake_processor(
    processed: list[str], *, verdict: str = "success", records: int = 0
):
    async def _fake_process_single_url(*args, **kwargs) -> URLProcessingResult:
        url = str(kwargs.get("url") or "")
        processed.append(url)
        return URLProcessingResult(
            records=[{}] * records,
            verdict=verdict,
            url_metrics={"record_count": records},
        )

    return _fake_process_single_url


def _seed_url_result(
    db_session: AsyncSession,
    run: CrawlRun,
    *,
    url: str,
    verdict: str,
    record_count: int = 0,
) -> None:
    db_session.add(
        CrawlUrlResult(
            run_id=run.id,
            requested_url=url,
            normalized_url=url,
            surface=run.surface,
            verdict=verdict,
            record_count=record_count,
        )
    )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_claim_run_refuses_live_same_owner_and_allows_takeover(
    db_session: AsyncSession, test_user
) -> None:
    run = await _make_batch_run(db_session, test_user, ["https://example.com/a"])

    assert await claim_run(db_session, run_id=run.id, owner="owner-a")
    await db_session.commit()

    # A redelivery with the same dispatch token is refused while the lease lives.
    assert not await claim_run(db_session, run_id=run.id, owner="owner-a")

    # A fresh dispatch token may take over from the previous owner.
    assert await claim_run(db_session, run_id=run.id, owner="owner-b")
    await db_session.commit()
    await db_session.refresh(run)
    assert run.queue_owner == "owner-b"
    assert run.claim_count == 2
    assert run.last_claimed_at is not None

    # The same owner may reclaim once the lease has expired.
    run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    assert await claim_run(db_session, run_id=run.id, owner="owner-b")
    await db_session.commit()
    await db_session.refresh(run)
    assert run.claim_count == 3


@pytest.mark.asyncio
@pytest.mark.regression
async def test_claim_run_refused_for_terminal_run(
    db_session: AsyncSession, test_user
) -> None:
    run = await _make_batch_run(db_session, test_user, ["https://example.com/a"])
    update_run_status(run, CrawlStatus.KILLED)
    await db_session.commit()

    assert not await claim_run(db_session, run_id=run.id, owner="owner-a")


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_skips_when_claimed_by_live_owner(
    db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _make_batch_run(
        db_session,
        test_user,
        ["https://example.com/a", "https://example.com/b"],
    )
    token = "crawl-run-live-owner"
    run.update_summary(**{CELERY_TASK_ID_KEY: token})
    assert await claim_run(db_session, run_id=run.id, owner=token)
    await db_session.commit()

    processed: list[str] = []
    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_processor(processed)
    )

    await process_run(db_session, run.id)

    assert processed == []
    await db_session.refresh(run)
    assert run.status == CrawlStatus.PENDING.value
    assert run.queue_owner == token
    assert run.claim_count == 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_takes_over_from_crashed_owner(
    db_session: AsyncSession, test_user, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = await _make_batch_run(
        db_session,
        test_user,
        ["https://example.com/a", "https://example.com/b"],
    )
    # A crashed executor left a live lease behind (no celery task id in the
    # summary, so process_run claims with a fresh per-invocation token).
    assert await claim_run(db_session, run_id=run.id, owner="crashed-owner")
    await db_session.commit()

    processed: list[str] = []
    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_processor(processed)
    )

    await process_run(db_session, run.id)

    assert len(processed) == 2
    await db_session.refresh(run)
    assert run.status == CrawlStatus.COMPLETED.value
    assert run.queue_owner is None
    assert run.lease_expires_at is None
    assert run.claim_count == 2


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_reentry_skips_completed_urls(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    urls = [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    run = await _make_batch_run(db_session, test_user, urls)
    normalized = [normalize_target_url(value) for value in urls]
    _seed_url_result(
        db_session, run, url=normalized[0], verdict="success", record_count=2
    )
    _seed_url_result(
        db_session, run, url=normalized[1], verdict="blocked", record_count=3
    )
    await db_session.commit()

    processed: list[str] = []
    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url",
        _fake_processor(processed, verdict="success", records=1),
    )

    await process_run(db_session, run.id)

    assert processed == [normalized[2]]
    await db_session.refresh(run)
    assert run.status == CrawlStatus.COMPLETED.value
    summary = run.result_summary
    assert summary["completed_urls"] == 3
    assert summary["processed_urls"] == 3
    assert summary["url_verdicts"] == ["success", "blocked", "success"]
    assert summary["verdict_counts"] == {"success": 2, "blocked": 1}
    assert summary["record_count"] == 2 + 3 + 1
    assert summary["extraction_verdict"] == "partial"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_result_summary_does_not_grow_per_url(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    monkeypatch.setattr(app_settings, "run_progress_commit_interval_seconds", 0.0)
    urls = [f"https://example.com/p/{idx}" for idx in range(4)]
    run = await _make_batch_run(db_session, test_user, urls)

    committed_summaries: list[dict] = []

    async def _fake_process_single_url(*args, **kwargs) -> URLProcessingResult:
        url_run = kwargs["run"]
        committed_summaries.append(dict(url_run.result_summary or {}))
        return URLProcessingResult(
            records=[], verdict="success", url_metrics={"record_count": 0}
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_process_single_url
    )

    await process_run(db_session, run.id)

    assert len(committed_summaries) == 4
    for snapshot in committed_summaries:
        assert "url_verdicts" not in snapshot
        assert "resolved_url_list" not in snapshot
    completed_values = [
        snapshot.get("completed_urls") for snapshot in committed_summaries
    ]
    assert completed_values == [0, 1, 2, 3]

    await db_session.refresh(run)
    summary = run.result_summary
    assert summary["url_verdicts"] == ["success"] * 4
    assert "resolved_url_list" not in summary
    assert summary["completed_urls"] == 4
    assert run.queue_owner is None
    assert run.claim_count == 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_progress_commits_are_throttled_but_durable(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    monkeypatch.setattr(app_settings, "run_progress_commit_interval_seconds", 3600.0)
    urls = [f"https://example.com/p/{idx}" for idx in range(3)]
    run = await _make_batch_run(db_session, test_user, urls)

    committed_summaries: list[dict] = []

    async def _fake_process_single_url(*args, **kwargs) -> URLProcessingResult:
        url_run = kwargs["run"]
        committed_summaries.append(dict(url_run.result_summary or {}))
        return URLProcessingResult(
            records=[], verdict="success", url_metrics={"record_count": 0}
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_process_single_url
    )

    await process_run(db_session, run.id)

    # Only the first per-URL commit lands inside the throttle window; later
    # URLs stay durable via their own crawl_url_results commits, and the final
    # patch publishes the complete counters.
    completed_values = [
        snapshot.get("completed_urls") for snapshot in committed_summaries
    ]
    assert completed_values == [0, 1, 1]
    await db_session.refresh(run)
    assert run.result_summary["completed_urls"] == 3
    assert run.result_summary["url_verdicts"] == ["success"] * 3


@pytest.mark.asyncio
@pytest.mark.regression
async def test_process_run_honors_pause_control_request(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(url_batch_concurrency=1)
    urls = [
        "https://example.com/a",
        "https://example.com/b",
        "https://example.com/c",
    ]
    run = await _make_batch_run(db_session, test_user, urls)
    processed: list[str] = []

    async def _fake_process_single_url(*args, **kwargs) -> URLProcessingResult:
        url = str(kwargs.get("url") or "")
        processed.append(url)
        # A concurrent session requests a pause after the first URL.
        set_control_request(kwargs["run"], CONTROL_REQUEST_PAUSE)
        await kwargs["session"].commit()
        return URLProcessingResult(
            records=[], verdict="success", url_metrics={"record_count": 0}
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_process_single_url
    )

    await process_run(db_session, run.id)

    assert processed == [normalize_target_url(urls[0])]
    await db_session.refresh(run)
    assert run.status == CrawlStatus.PAUSED.value
    assert run.queue_owner is None


@pytest.mark.asyncio
@pytest.mark.regression
async def test_parallel_run_bounds_live_worker_tasks_to_concurrency(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    """2.11: worker-pool scheduling keeps peak live tasks at O(concurrency).

    The old up-front design materialized one task per pending URL (24 here);
    the worker pool must never exceed `concurrency` live worker tasks.
    """
    monkeypatch.setattr(app_settings, "celery_dispatch_enabled", True)
    patch_settings(url_batch_concurrency=3, browser_runtime_context_capacity=3)
    monkeypatch.setattr(app_settings, "system_max_concurrent_urls", 3, raising=False)
    urls = [f"https://example.com/p/{idx}" for idx in range(24)]
    run = await _make_batch_run(db_session, test_user, urls)
    processed: list[str] = []

    async def _fake_process_single_url(*args, **kwargs) -> URLProcessingResult:
        processed.append(str(kwargs.get("url") or ""))
        await asyncio.sleep(0.01)
        return URLProcessingResult(
            records=[], verdict="success", url_metrics={"record_count": 0}
        )

    monkeypatch.setattr(
        "app.crawl.batch_runtime.process_single_url", _fake_process_single_url
    )

    peak_live_workers = 0
    monitor_stop = asyncio.Event()

    async def _monitor() -> None:
        nonlocal peak_live_workers
        prefix = f"crawl-run-{run.id}-"
        while not monitor_stop.is_set():
            live = sum(
                1 for task in asyncio.all_tasks() if task.get_name().startswith(prefix)
            )
            peak_live_workers = max(peak_live_workers, live)
            await asyncio.sleep(0.001)

    monitor = asyncio.create_task(_monitor())
    try:
        await process_run(db_session, run.id)
    finally:
        monitor_stop.set()
        await monitor

    assert len(processed) == 24
    assert 2 <= peak_live_workers <= 3
    await db_session.refresh(run)
    assert run.status == CrawlStatus.COMPLETED.value


@pytest.mark.asyncio
@pytest.mark.regression
async def test_assemble_run_summary_payload_reconstructs_per_url_data(
    db_session: AsyncSession, test_user
) -> None:
    run = await _make_batch_run(
        db_session,
        test_user,
        ["https://example.com/a", "https://example.com/b"],
    )
    first = normalize_target_url("https://example.com/a")
    second = normalize_target_url("https://example.com/b")
    _seed_url_result(db_session, run, url=first, verdict="success", record_count=1)
    _seed_url_result(db_session, run, url=second, verdict="error", record_count=0)
    await db_session.commit()

    payload = await assemble_run_summary_payload(db_session, run)
    assert payload["url_verdicts"] == ["success", "error"]
    assert payload["resolved_url_list"] == [first, second]
    assert payload["url_count"] == 2

    # Values already persisted in the summary (e.g. a completed run's final
    # patch) win over the reconstructed ones.
    run.update_summary(url_verdicts=["blocked"])
    await db_session.commit()
    payload = await assemble_run_summary_payload(db_session, run)
    assert payload["url_verdicts"] == ["blocked"]
