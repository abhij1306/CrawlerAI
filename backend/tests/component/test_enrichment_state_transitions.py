"""Focused behavioral tests for Data Enrichment state transitions (audit 4.11).

Covers ``app/enrichment/service.py``:

- ``create_data_enrichment_job``: job + records + products land in ``pending``
  and ineligible records are skipped (or reject the job outright).
- ``run_job``: pending -> running -> enriched / degraded / failed rollups, and
  per-record ``enrichment_status`` rollups into the job status.
- ``_fail_stuck_job``: terminal failure stamp + product/record release.
- ``recover_orphaned_data_enrichment_jobs``: running -> failed only after the
  orphan threshold.
- ``run_data_enrichment_job``: the task-entry path end to end.

DB-backed, following the ``tests/component/test_pi_de_job_tasks.py`` fixtures.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import app.enrichment.service as de_service
from app.core.config.product_intelligence import product_intelligence_settings
from app.enrichment.service import (
    _fail_stuck_job,
    create_data_enrichment_job,
    recover_orphaned_data_enrichment_jobs,
    run_data_enrichment_job,
    run_job,
)
from app.models.crawl_run import CrawlRecord
from app.models.data_enrichment import DataEnrichmentJob, EnrichedProduct

pytestmark = pytest.mark.component

STALE_AGE = timedelta(
    seconds=product_intelligence_settings.job_orphaned_after_seconds + 300
)


async def _make_record(
    db_session: AsyncSession,
    run,
    url: str,
    *,
    title: str,
    enrichment_status: str | None = None,
) -> CrawlRecord:
    record = CrawlRecord(
        run_id=run.id,
        source_url=url,
        data={"title": title, "price": "$49.99", "currency": "USD"},
        enrichment_status=enrichment_status,
    )
    db_session.add(record)
    await db_session.flush()
    return record


async def _job_products(
    db_session: AsyncSession, job: DataEnrichmentJob
) -> list[EnrichedProduct]:
    return list(
        (
            await db_session.scalars(
                select(EnrichedProduct)
                .where(EnrichedProduct.job_id == job.id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
    )


# ---------------------------------------------------------------------------
# create -> pending
# ---------------------------------------------------------------------------


async def test_create_job_lands_pending_with_records_and_products(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record_a = await _make_record(
        db_session, run, "https://example.com/products/linen-dress", title="Dress A"
    )
    record_b = await _make_record(
        db_session, run, "https://example.com/products/silk-shirt", title="Shirt B"
    )
    await db_session.commit()

    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record_a.id, record_b.id]},
    )

    assert job.status == "pending"
    assert job.summary["requested_count"] == 2
    assert job.summary["accepted_count"] == 2
    assert job.summary["skipped_status_count"] == 0
    assert job.summary["skipped_surface_count"] == 0
    assert job.options["source_record_ids"] == [record_a.id, record_b.id]

    for record in (record_a, record_b):
        await db_session.refresh(record)
        assert record.enrichment_status == "pending"
        assert record.enriched_at is None

    products = await _job_products(db_session, job)
    assert len(products) == 2
    for product in products:
        assert product.status == "pending"
        assert product.source_record_id in {record_a.id, record_b.id}


async def test_create_job_skips_ineligible_records(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    detail_run = await create_test_run(
        url="https://example.com/products/eligible",
        surface="ecommerce_detail",
    )
    listing_run = await create_test_run(
        url="https://example.com/category/dresses",
        surface="ecommerce_listing",
    )
    eligible = await _make_record(
        db_session, detail_run, "https://example.com/products/eligible", title="Good"
    )
    in_flight = await _make_record(
        db_session,
        detail_run,
        "https://example.com/products/in-flight",
        title="In Flight",
        enrichment_status="running",
    )
    wrong_surface = await _make_record(
        db_session, listing_run, "https://example.com/category/dresses", title="Card"
    )
    await db_session.commit()

    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={
            "source_record_ids": [eligible.id, in_flight.id, wrong_surface.id]
        },
    )

    assert job.status == "pending"
    assert job.summary["accepted_count"] == 1
    assert job.summary["skipped_status_count"] == 1
    assert job.summary["skipped_surface_count"] == 1
    assert job.options["source_record_ids"] == [eligible.id]


async def test_create_job_rejects_when_nothing_is_eligible(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/eligible",
        surface="ecommerce_detail",
    )
    record = await _make_record(
        db_session,
        run,
        "https://example.com/products/eligible",
        title="Running",
        enrichment_status="running",
    )
    await db_session.commit()

    with pytest.raises(ValueError, match="No eligible ecommerce detail records"):
        await create_data_enrichment_job(
            db_session,
            user=test_user,
            payload={"source_record_ids": [record.id]},
        )

    with pytest.raises(ValueError, match="at least one ecommerce detail record"):
        await create_data_enrichment_job(
            db_session,
            user=test_user,
            payload={"source_record_ids": []},
        )


# ---------------------------------------------------------------------------
# run_job: pending -> running -> enriched / degraded / failed
# ---------------------------------------------------------------------------


async def test_run_job_transitions_to_enriched_and_rolls_up_records(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    records = [
        await _make_record(
            db_session,
            run,
            f"https://example.com/products/dress-{index}",
            title=f"Dress {index}",
        )
        for index in range(2)
    ]
    await db_session.commit()
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id for record in records]},
    )

    await run_job(db_session, job)

    await db_session.refresh(job)
    assert job.status == "enriched"
    assert job.completed_at is not None
    assert job.summary["started_at"]
    assert job.summary["completed_at"]
    assert job.summary["enriched_count"] == 2
    assert job.summary["failed_count"] == 0

    for product in await _job_products(db_session, job):
        assert product.status == "enriched"
        assert product.diagnostics["deterministic"] is True
    for record in records:
        await db_session.refresh(record)
        assert record.enrichment_status == "enriched"
        assert record.enriched_at is not None


async def test_run_job_partial_failure_rolls_up_degraded(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/mixed",
        surface="ecommerce_detail",
    )
    good = await _make_record(
        db_session, run, "https://example.com/products/good", title="Good Dress"
    )
    bad = await _make_record(
        db_session, run, "https://example.com/products/bad", title="Bad Dress"
    )
    await db_session.commit()
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [good.id, bad.id]},
    )

    original_enrich = de_service._enrich_product

    async def _exploding_enrich(session, *, job, product, record, llm_enabled):
        if record.id == bad.id:
            raise RuntimeError("boom")
        await original_enrich(
            session, job=job, product=product, record=record, llm_enabled=llm_enabled
        )

    monkeypatch.setattr(de_service, "_enrich_product", _exploding_enrich)

    await run_job(db_session, job)

    await db_session.refresh(job)
    assert job.status == "degraded"
    assert job.summary["enriched_count"] == 1
    assert job.summary["failed_count"] == 1

    products = {
        product.source_record_id: product
        for product in await _job_products(db_session, job)
    }
    assert products[good.id].status == "enriched"
    assert products[bad.id].status == "failed"
    assert products[bad.id].diagnostics == {"error": "boom"}

    await db_session.refresh(good)
    await db_session.refresh(bad)
    assert good.enrichment_status == "enriched"
    assert good.enriched_at is not None
    assert bad.enrichment_status == "failed"
    assert bad.enriched_at is None


async def test_run_job_total_failure_rolls_up_failed(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/broken",
        surface="ecommerce_detail",
    )
    record = await _make_record(
        db_session, run, "https://example.com/products/broken", title="Broken"
    )
    await db_session.commit()
    job = await create_data_enrichment_job(
        db_session, user=test_user, payload={"source_record_ids": [record.id]}
    )

    async def _always_explode(session, *, job, product, record, llm_enabled):
        raise RuntimeError("deterministic pipeline down")

    monkeypatch.setattr(de_service, "_enrich_product", _always_explode)

    await run_job(db_session, job)

    await db_session.refresh(job)
    assert job.status == "failed"
    assert job.summary["enriched_count"] == 0
    assert job.summary["failed_count"] == 1
    await db_session.refresh(record)
    assert record.enrichment_status == "failed"


# ---------------------------------------------------------------------------
# _fail_stuck_job + orphan recovery
# ---------------------------------------------------------------------------


async def test_fail_stuck_job_stamps_failure_and_releases_records(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/stuck",
        surface="ecommerce_detail",
    )
    record = await _make_record(
        db_session,
        run,
        "https://example.com/products/stuck",
        title="Stuck",
        enrichment_status="running",
    )
    job = DataEnrichmentJob(
        user_id=test_user.id,
        source_run_id=run.id,
        status="running",
        options={},
        summary={"celery_task_id": "task-stuck-1"},
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

    now = datetime.now(UTC)
    await _fail_stuck_job(db_session, job, now=now, error="WorkerInterrupted: test")

    assert job.status == "failed"
    assert job.completed_at == now
    assert job.summary["error"] == "WorkerInterrupted: test"
    assert job.summary["recovered_at"] == now.isoformat()
    assert product.status == "failed"
    assert product.diagnostics == {"error": "job_orphaned"}
    # Released so a later job can re-enrich it (creation skips pending/running).
    assert record.enrichment_status == "failed"


async def test_recover_orphaned_jobs_fails_only_stale_running_jobs(
    db_session: AsyncSession,
    test_user,
) -> None:
    stale_running = DataEnrichmentJob(
        user_id=test_user.id, status="running", options={}, summary={}
    )
    fresh_running = DataEnrichmentJob(
        user_id=test_user.id, status="running", options={}, summary={}
    )
    pending_job = DataEnrichmentJob(
        user_id=test_user.id, status="pending", options={}, summary={}
    )
    for job in (stale_running, fresh_running, pending_job):
        db_session.add(job)
    await db_session.commit()
    await db_session.execute(
        update(DataEnrichmentJob)
        .where(DataEnrichmentJob.id == stale_running.id)
        .values(updated_at=datetime.now(UTC) - STALE_AGE),
        execution_options={"synchronize_session": False},
    )
    await db_session.commit()
    db_session.expire_all()

    recovered = await recover_orphaned_data_enrichment_jobs(db_session)

    assert recovered == 1
    await db_session.refresh(stale_running)
    assert stale_running.status == "failed"
    assert "OrphanedJobRecovery" in stale_running.summary["error"]
    assert stale_running.completed_at is not None
    # Fresh running jobs and non-running jobs are left alone.
    await db_session.refresh(fresh_running)
    await db_session.refresh(pending_job)
    assert fresh_running.status == "running"
    assert pending_job.status == "pending"


# ---------------------------------------------------------------------------
# run_data_enrichment_job (task entry path)
# ---------------------------------------------------------------------------


async def test_task_entry_runs_pending_job_to_enriched(
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
        url="https://example.com/products/entry",
        surface="ecommerce_detail",
    )
    record = await _make_record(
        db_session, run, "https://example.com/products/entry", title="Entry Dress"
    )
    await db_session.commit()
    job = await create_data_enrichment_job(
        db_session, user=test_user, payload={"source_record_ids": [record.id]}
    )

    await run_data_enrichment_job(int(job.id))

    await db_session.refresh(job)
    assert job.status == "enriched"
    await db_session.refresh(record)
    assert record.enrichment_status == "enriched"


async def test_task_entry_leaves_terminal_and_missing_jobs_alone(
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
        url="https://example.com/products/terminal",
        surface="ecommerce_detail",
    )
    record = await _make_record(
        db_session, run, "https://example.com/products/terminal", title="Done Dress"
    )
    await db_session.commit()
    job = await create_data_enrichment_job(
        db_session, user=test_user, payload={"source_record_ids": [record.id]}
    )
    await run_job(db_session, job)
    await db_session.refresh(job)
    assert job.status == "enriched"

    # A terminal job is not re-run...
    await run_data_enrichment_job(int(job.id))
    await db_session.refresh(job)
    assert job.status == "enriched"
    assert job.summary["enriched_count"] == 1

    # ...and a deleted/unknown job id is a quiet no-op.
    await run_data_enrichment_job(int(job.id) + 999_999)
