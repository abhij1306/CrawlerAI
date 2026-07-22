"""Product Intelligence / Data Enrichment job execution refactor tests.

Covers the audit 2.7 fixes:
- POST /jobs enqueues a Celery task instead of a FastAPI BackgroundTask.
- Candidate crawl polling is batched (one run-status lookup per round) instead
  of sequential per-candidate waits.
- Job summary counts use a single grouped-count query.
- Jobs stuck in ``running`` with no live task are recovered as failed.
- Enrichment batch-loads products/records (no per-product session.get N+1).
"""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.tasks as app_tasks
from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.data_enrichment import DataEnrichmentJob, EnrichedProduct
from app.models.product_intelligence import (
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceMatch,
    ProductIntelligenceSourceProduct,
)
import app.enrichment.service as de_service
import app.intelligence.service as pi_service
from app.core.config.product_intelligence import (
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS,
    product_intelligence_settings,
)
from app.intelligence.service import (
    _poll_candidates_and_score,
    dispatch_product_intelligence_job,
    recover_orphaned_product_intelligence_jobs,
    run_product_intelligence_job,
)
from app.intelligence.service_support import _update_job_summary
from app.enrichment.service import (
    create_data_enrichment_job,
    recover_orphaned_data_enrichment_jobs,
    run_data_enrichment_job,
    run_job,
)

STALE_AGE = timedelta(
    seconds=product_intelligence_settings.job_orphaned_after_seconds + 300
)


@pytest.fixture
async def api_client(db_session, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


def _make_pi_job(user_id: int, *, status: str = "queued") -> ProductIntelligenceJob:
    return ProductIntelligenceJob(user_id=user_id, status=status, options={}, summary={})


async def _make_pi_source(
    db_session: AsyncSession, job: ProductIntelligenceJob
) -> ProductIntelligenceSourceProduct:
    source = ProductIntelligenceSourceProduct(
        job_id=job.id,
        source_url="https://www.belk.com/p/levis-511",
        brand="Levi's",
        normalized_brand="levi's",
        title="Levi's 511 Slim Fit Jeans",
        payload={},
    )
    db_session.add(source)
    await db_session.flush()
    return source


def _make_candidate(
    job: ProductIntelligenceJob,
    source: ProductIntelligenceSourceProduct,
    run: CrawlRun | None,
    index: int,
) -> ProductIntelligenceCandidate:
    return ProductIntelligenceCandidate(
        job_id=job.id,
        source_product_id=source.id,
        url=f"https://www.levi.com/p/{index}",
        status=PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
        candidate_crawl_run_id=run.id if run is not None else None,
        payload={},
    )


# ---------------------------------------------------------------------------
# 1. API enqueues Celery tasks instead of BackgroundTasks
# ---------------------------------------------------------------------------


@pytest.mark.component
async def test_product_intelligence_job_create_enqueues_celery_task(
    api_client: AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple, dict]] = []

    def _fake_apply_async(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(settings, "celery_dispatch_enabled", True)
    monkeypatch.setattr(
        app_tasks.product_intelligence_run_job_task, "apply_async", _fake_apply_async
    )

    response = await api_client.post(
        "/api/product-intelligence/jobs",
        json={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/levis-511",
                    "data": {
                        "title": "Levi's 511 Slim Fit Jeans",
                        "brand": "Levi's",
                        "url": "https://www.belk.com/p/levis-511",
                    },
                }
            ]
        },
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["args"] == [body["id"]]
    assert kwargs["task_id"].startswith(f"product-intelligence-job-{body['id']}-")
    # The recorded task id lets the worker detect interrupted redeliveries.
    assert body["summary"]["celery_task_id"] == kwargs["task_id"]


@pytest.mark.component
async def test_data_enrichment_job_create_enqueues_celery_task(
    api_client: AsyncClient,
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={"title": "Navy Linen Dress", "price": "$49.99"},
    )
    db_session.add(record)
    await db_session.commit()

    calls: list[tuple[tuple, dict]] = []

    def _fake_apply_async(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(settings, "celery_dispatch_enabled", True)
    monkeypatch.setattr(
        app_tasks.data_enrichment_run_job_task, "apply_async", _fake_apply_async
    )

    response = await api_client.post(
        "/api/data-enrichment/jobs",
        json={"source_record_ids": [record.id]},
    )

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "pending"
    assert len(calls) == 1
    _, kwargs = calls[0]
    assert kwargs["args"] == [body["id"]]
    assert kwargs["task_id"].startswith(f"data-enrichment-job-{body['id']}-")
    assert body["summary"]["celery_task_id"] == kwargs["task_id"]


@pytest.mark.component
async def test_dispatch_falls_back_to_in_process_task_when_enqueue_fails(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _make_pi_job(test_user.id)
    db_session.add(job)
    await db_session.commit()

    def _raising_apply_async(*_args, **_kwargs):
        raise RuntimeError("broker down")

    ran: list[int] = []

    async def _fake_run(job_id: int, *, task_id=None) -> None:
        ran.append(job_id)

    monkeypatch.setattr(settings, "celery_dispatch_enabled", True)
    monkeypatch.setattr(
        app_tasks.product_intelligence_run_job_task,
        "apply_async",
        _raising_apply_async,
    )
    monkeypatch.setattr(pi_service, "run_product_intelligence_job", _fake_run)

    await dispatch_product_intelligence_job(db_session, job)
    await asyncio.sleep(0.05)

    assert ran == [job.id]
    assert "celery_task_id" not in dict(job.summary or {})


@pytest.mark.component
async def test_dispatch_uses_in_process_task_when_celery_dispatch_disabled(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _make_pi_job(test_user.id)
    db_session.add(job)
    await db_session.commit()

    ran: list[int] = []

    async def _fake_run(job_id: int, *, task_id=None) -> None:
        ran.append(job_id)

    monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
    monkeypatch.setattr(pi_service, "run_product_intelligence_job", _fake_run)

    await dispatch_product_intelligence_job(db_session, job)
    await asyncio.sleep(0.05)

    assert ran == [job.id]
    assert "celery_task_id" not in dict(job.summary or {})


# ---------------------------------------------------------------------------
# 2. Batched candidate polling
# ---------------------------------------------------------------------------


@pytest.mark.component
async def test_poll_candidates_batches_status_checks_and_times_out_together(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _make_pi_job(test_user.id, status="running")
    db_session.add(job)
    await db_session.flush()
    source = await _make_pi_source(db_session, job)
    candidates = []
    for index in range(5):
        run = await create_test_run(
            url=f"https://candidates.example.com/p/{index}",
            surface="ecommerce_detail",
        )
        candidate = _make_candidate(job, source, run, index)
        db_session.add(candidate)
        candidates.append(candidate)
    await db_session.commit()

    monkeypatch.setattr(product_intelligence_settings, "candidate_poll_seconds", 1.0)
    monkeypatch.setattr(
        product_intelligence_settings, "candidate_poll_interval_seconds", 0.5
    )

    statements: list[str] = []
    original_execute = db_session.execute

    async def _counting_execute(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", _counting_execute)

    started = time.monotonic()
    await _poll_candidates_and_score(db_session, job, candidates)
    elapsed = time.monotonic() - started

    for candidate in candidates:
        assert candidate.status == PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT
    # One run-status lookup per round for ALL pending candidates, not one per
    # candidate per round: ~3 rounds for a 1.0s deadline at 0.5s intervals.
    run_status_queries = [
        statement for statement in statements if "crawl_runs" in statement
    ]
    assert 0 < len(run_status_queries) <= 5
    # Sequential polling would block up to 5 x candidate_poll_seconds.
    assert elapsed < 4.0


@pytest.mark.component
async def test_poll_candidates_scores_final_runs_without_waiting(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _make_pi_job(test_user.id, status="running")
    db_session.add(job)
    await db_session.flush()
    source = await _make_pi_source(db_session, job)
    candidates = []
    for index in range(3):
        run = await create_test_run(
            url=f"https://final.example.com/p/{index}",
            surface="ecommerce_detail",
        )
        run.status = "completed"
        candidate = _make_candidate(job, source, run, index)
        db_session.add(candidate)
        candidates.append(candidate)
    await db_session.commit()

    monkeypatch.setattr(product_intelligence_settings, "candidate_poll_seconds", 30.0)

    started = time.monotonic()
    await _poll_candidates_and_score(db_session, job, candidates)
    elapsed = time.monotonic() - started

    for candidate in candidates:
        assert candidate.status == PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS
    # All three score in the first round: no poll-interval sleeps.
    assert elapsed < 2.0
    assert job.summary["candidate_count"] == 3


@pytest.mark.component
async def test_poll_candidates_observes_fresh_run_status(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Run status written by another process must be seen by the poller.

    The polling session created the run row, so its identity map holds a stale
    pre-dispatch copy (expire_on_commit=False); a worker-completed run must
    still be scored rather than timed out.
    """
    job = _make_pi_job(test_user.id, status="running")
    db_session.add(job)
    await db_session.flush()
    source = await _make_pi_source(db_session, job)
    run = await create_test_run(
        url="https://fresh.example.com/p/1",
        surface="ecommerce_detail",
    )
    candidate = _make_candidate(job, source, run, 0)
    db_session.add(candidate)
    await db_session.commit()

    # Simulate the worker finishing the run in a different session: the ORM
    # instance in this session's identity map stays stale at "pending".
    assert run.status != "completed"
    await db_session.execute(
        update(CrawlRun).where(CrawlRun.id == run.id).values(status="completed"),
        execution_options={"synchronize_session": False},
    )
    await db_session.commit()
    assert run.status != "completed"  # identity-map copy is stale

    monkeypatch.setattr(product_intelligence_settings, "candidate_poll_seconds", 5.0)
    monkeypatch.setattr(
        product_intelligence_settings, "candidate_poll_interval_seconds", 0.5
    )

    await _poll_candidates_and_score(db_session, job, [candidate])

    assert candidate.status == PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS


# ---------------------------------------------------------------------------
# 3. Grouped-count job summary
# ---------------------------------------------------------------------------


@pytest.mark.component
async def test_update_job_summary_uses_single_grouped_query(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = _make_pi_job(test_user.id)
    db_session.add(job)
    await db_session.flush()
    source = await _make_pi_source(db_session, job)
    candidates = [_make_candidate(job, source, None, index) for index in range(2)]
    for candidate in candidates:
        db_session.add(candidate)
    await db_session.flush()
    db_session.add(
        ProductIntelligenceMatch(
            job_id=job.id,
            source_product_id=source.id,
            candidate_id=candidates[0].id,
            score=0.9,
        )
    )
    await db_session.commit()

    statements: list[str] = []
    original_execute = db_session.execute

    async def _counting_execute(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", _counting_execute)

    await _update_job_summary(db_session, job)

    assert len(statements) == 1
    assert job.summary["source_count"] == 1
    assert job.summary["candidate_count"] == 2
    assert job.summary["match_count"] == 1


# ---------------------------------------------------------------------------
# 4. Stuck-running job recovery
# ---------------------------------------------------------------------------


@pytest.mark.component
async def test_recover_orphaned_product_intelligence_jobs(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    states = {"t-live": "STARTED", "t-done": "SUCCESS", "t-pending": "PENDING"}
    monkeypatch.setattr(
        pi_service, "celery_task_state", lambda task_id: states[task_id]
    )

    stale_no_task = _make_pi_job(test_user.id, status="running")
    fresh_no_task = _make_pi_job(test_user.id, status="running")
    live_task = _make_pi_job(test_user.id, status="running")
    live_task.summary = {"celery_task_id": "t-live"}
    done_task = _make_pi_job(test_user.id, status="running")
    done_task.summary = {"celery_task_id": "t-done"}
    pending_stale = _make_pi_job(test_user.id, status="running")
    pending_stale.summary = {"celery_task_id": "t-pending"}
    queued_job = _make_pi_job(test_user.id, status="queued")
    for job in (
        stale_no_task,
        fresh_no_task,
        live_task,
        done_task,
        pending_stale,
        queued_job,
    ):
        db_session.add(job)
    await db_session.commit()

    stale_time = datetime.now(UTC) - STALE_AGE
    await db_session.execute(
        update(ProductIntelligenceJob)
        .where(ProductIntelligenceJob.id.in_([stale_no_task.id, pending_stale.id]))
        .values(updated_at=stale_time),
        execution_options={"synchronize_session": False},
    )
    await db_session.commit()
    db_session.expire_all()

    recovered = await recover_orphaned_product_intelligence_jobs(db_session)

    assert recovered == 3
    for job in (stale_no_task, done_task, pending_stale):
        assert job.status == "failed"
        assert "OrphanedJobRecovery" in job.summary["error"]
        assert job.completed_at is not None
    # Untouched: fresh rows, live tasks, and queued (not yet started) jobs.
    for job in (fresh_no_task, live_task, queued_job):
        await db_session.refresh(job)
    assert fresh_no_task.status == "running"
    assert live_task.status == "running"
    assert queued_job.status == "queued"


@pytest.mark.component
async def test_run_product_intelligence_job_fails_interrupted_redelivery(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    existing_session_local_factory,
) -> None:
    monkeypatch.setattr(
        pi_service, "SessionLocal", existing_session_local_factory(db_session)
    )
    monkeypatch.setattr(pi_service, "celery_task_state", lambda _task_id: "STARTED")

    interrupted = _make_pi_job(test_user.id, status="running")
    interrupted.summary = {"celery_task_id": "task-abc"}
    other_job = _make_pi_job(test_user.id, status="running")
    other_job.summary = {"celery_task_id": "task-other"}
    db_session.add(interrupted)
    db_session.add(other_job)
    await db_session.commit()

    # Celery redelivered the same task after a worker loss: fail cleanly.
    await run_product_intelligence_job(interrupted.id, task_id="task-abc")
    assert interrupted.status == "failed"
    assert "WorkerInterrupted" in interrupted.summary["error"]

    # A different task id means another execution owns the job: leave it alone.
    await run_product_intelligence_job(other_job.id, task_id="task-abc")
    assert other_job.status == "running"


@pytest.mark.component
async def test_recover_orphaned_data_enrichment_jobs_releases_products_and_records(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/orphan",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/orphan",
        data={"title": "Orphaned Dress"},
        enrichment_status="pending",
    )
    db_session.add(record)
    job = DataEnrichmentJob(
        user_id=test_user.id,
        source_run_id=run.id,
        status="running",
        options={},
        summary={},
    )
    db_session.add(job)
    await db_session.flush()
    product = EnrichedProduct(
        job_id=job.id,
        source_run_id=run.id,
        source_record_id=record.id,
        source_url=record.source_url,
        status="pending",
        diagnostics={},
    )
    db_session.add(product)
    await db_session.commit()
    await db_session.execute(
        update(DataEnrichmentJob)
        .where(DataEnrichmentJob.id == job.id)
        .values(updated_at=datetime.now(UTC) - STALE_AGE),
        execution_options={"synchronize_session": False},
    )
    await db_session.commit()
    db_session.expire_all()

    recovered = await recover_orphaned_data_enrichment_jobs(db_session)

    assert recovered == 1
    assert job.status == "failed"
    assert "OrphanedJobRecovery" in job.summary["error"]
    assert job.completed_at is not None
    # Non-terminal products are failed and their records released for
    # re-enrichment (job creation skips records in pending/running).
    assert product.status == "failed"
    assert product.diagnostics == {"error": "job_orphaned"}
    assert record.enrichment_status == "failed"


@pytest.mark.component
async def test_run_data_enrichment_job_fails_interrupted_redelivery(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
    existing_session_local_factory,
) -> None:
    monkeypatch.setattr(
        de_service, "SessionLocal", existing_session_local_factory(db_session)
    )
    run = await create_test_run(
        url="https://example.com/products/interrupted",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/interrupted",
        data={"title": "Interrupted Dress"},
        enrichment_status="pending",
    )
    db_session.add(record)
    job = DataEnrichmentJob(
        user_id=test_user.id,
        source_run_id=run.id,
        status="running",
        options={},
        summary={"celery_task_id": "task-de-1"},
    )
    db_session.add(job)
    await db_session.flush()
    product = EnrichedProduct(
        job_id=job.id,
        source_run_id=run.id,
        source_record_id=record.id,
        source_url=record.source_url,
        status="running",
        diagnostics={},
    )
    db_session.add(product)
    await db_session.commit()

    await run_data_enrichment_job(job.id, task_id="task-de-1")

    assert job.status == "failed"
    assert "WorkerInterrupted" in job.summary["error"]
    assert product.status == "failed"
    assert record.enrichment_status == "failed"


# ---------------------------------------------------------------------------
# 5. Enrichment batch loading (N+1 fix)
# ---------------------------------------------------------------------------


@pytest.mark.component
async def test_enrichment_run_job_batch_loads_products_and_records(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/batch",
        surface="ecommerce_detail",
    )
    records = []
    for index in range(3):
        record = CrawlRecord(
            run_id=run.id,
            source_url=f"https://example.com/products/batch-{index}",
            data={"title": f"Dress {index}", "price": "$49.99", "currency": "USD"},
        )
        db_session.add(record)
        records.append(record)
    await db_session.commit()
    for record in records:
        await db_session.refresh(record)

    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id for record in records]},
    )

    get_calls = 0
    original_get = db_session.get

    async def _counting_get(*args, **kwargs):
        nonlocal get_calls
        get_calls += 1
        return await original_get(*args, **kwargs)

    statements: list[str] = []
    original_execute = db_session.execute

    async def _counting_execute(statement, *args, **kwargs):
        statements.append(str(statement))
        return await original_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "get", _counting_get)
    monkeypatch.setattr(db_session, "execute", _counting_execute)

    await run_job(db_session, job)

    product_selects = [s for s in statements if "enriched_products" in s]
    record_selects = [s for s in statements if "crawl_records" in s]
    # No per-product session.get; one refs query + one IN batch for products,
    # one IN batch for records, regardless of product count.
    assert get_calls == 0
    assert len(product_selects) == 2
    assert len(record_selects) == 1

    # Per-product result semantics are unchanged.
    await db_session.refresh(job)
    assert job.status == "enriched"
    assert job.summary["enriched_count"] == 3
    assert job.summary["failed_count"] == 0
    products = list(
        (
            await db_session.scalars(
                select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
            )
        ).all()
    )
    assert len(products) == 3
    for product in products:
        assert product.status == "enriched"
        assert product.diagnostics["deterministic"] is True
    for record in records:
        await db_session.refresh(record)
        assert record.enrichment_status == "enriched"
        assert record.enriched_at is not None
