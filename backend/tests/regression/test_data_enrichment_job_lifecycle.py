from __future__ import annotations

# ruff: noqa: F403, F405
from .data_enrichment_test_support import *


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_job_creates_pending_rows(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={
            "title": "Navy Linen Dress",
            "price": "$49.99",
            "currency": "USD",
            "category": "Women > Dresses",
            "gender": "women",
        },
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )

    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()
    await db_session.refresh(record)

    assert job.status == DATA_ENRICHMENT_STATUS_PENDING
    assert job.summary["accepted_count"] == 1
    assert record.enrichment_status == DATA_ENRICHMENT_STATUS_PENDING
    assert product.source_record_id == record.id
    assert product.status == DATA_ENRICHMENT_STATUS_PENDING
    assert product.price_normalized is None
    assert product.gender_normalized is None


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_allows_already_enriched_records(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={"title": "Linen Dress"},
        enrichment_status=DATA_ENRICHMENT_STATUS_ENRICHED,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()
    await db_session.refresh(record)

    assert job.summary["accepted_count"] == 1
    assert record.enrichment_status == DATA_ENRICHMENT_STATUS_PENDING
    assert product.source_record_id == record.id


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_skips_active_records(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={"title": "Linen Dress"},
        enrichment_status=DATA_ENRICHMENT_STATUS_RUNNING,
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    with pytest.raises(
        ValueError, match="No eligible ecommerce detail records selected"
    ):
        await create_data_enrichment_job(
            db_session,
            user=test_user,
            payload={"source_record_ids": [record.id]},
        )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_rejects_non_ecommerce_detail_records(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://jobs.example.com/job/123",
        surface="job_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://jobs.example.com/job/123",
        data={"title": "Engineer"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    with pytest.raises(
        ValueError, match="No eligible ecommerce detail records selected"
    ):
        await create_data_enrichment_job(
            db_session,
            user=test_user,
            payload={"source_record_ids": [record.id]},
        )


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_job_detail_payload_serializes(
    db_session: AsyncSession,
    create_test_run,
    test_user,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={"title": "Linen Dress"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id]},
    )

    jobs = await list_data_enrichment_jobs(db_session, user=test_user)
    loaded = await get_data_enrichment_job(db_session, user=test_user, job_id=job.id)
    payload = await build_data_enrichment_job_payload(db_session, job=loaded)
    response = DataEnrichmentJobDetailResponse.model_validate(payload)

    assert [row.id for row in jobs] == [job.id]
    assert response.job.id == job.id
    assert len(response.enriched_products) == 1


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_job_commits_running_before_product_work(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/navy-linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/navy-linen-dress",
        data={"title": "Navy Linen Midi Dress", "category": "Dresses"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": False}},
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def _blocking_enrich_product(*args, **kwargs):
        del args, kwargs
        started.set()
        await release.wait()

    monkeypatch.setattr(
        "app.enrichment.service._enrich_product",
        _blocking_enrich_product,
    )

    task = asyncio.create_task(run_job(db_session, job))
    try:
        try:
            await asyncio.wait_for(started.wait(), timeout=2)
        except TimeoutError:
            task.cancel()
            raise
        session_factory = async_sessionmaker(
            db_session.bind,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        async with session_factory() as check_session:
            visible_job = await check_session.get(type(job), job.id)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)

    assert visible_job is not None
    assert visible_job.status == DATA_ENRICHMENT_STATUS_RUNNING


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_commits_product_progress_between_records(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/navy-linen-dress",
        surface="ecommerce_detail",
    )
    records = [
        CrawlRecord(
            run_id=run.id,
            source_url=f"https://example.com/products/{index}",
            data={"title": f"Navy Linen Dress {index}", "category": "Dresses"},
        )
        for index in range(2)
    ]
    db_session.add_all(records)
    await db_session.commit()
    for record in records:
        await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={
            "source_record_ids": [record.id for record in records],
            "options": {"llm_enabled": False},
        },
    )
    first_done = asyncio.Event()
    second_started = asyncio.Event()
    release = asyncio.Event()
    calls = 0

    async def _blocking_second_product(*args, **kwargs):
        nonlocal calls
        del args, kwargs
        calls += 1
        if calls == 1:
            first_done.set()
            return
        second_started.set()
        await release.wait()

    monkeypatch.setattr(
        "app.enrichment.service._enrich_product",
        _blocking_second_product,
    )

    task = asyncio.create_task(run_job(db_session, job))
    try:
        try:
            await asyncio.wait_for(first_done.wait(), timeout=2)
            await asyncio.wait_for(second_started.wait(), timeout=2)
        except TimeoutError:
            task.cancel()
            raise
        session_factory = async_sessionmaker(
            db_session.bind,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        async with session_factory() as check_session:
            visible_products = list(
                (
                    await check_session.scalars(
                        select(EnrichedProduct)
                        .where(EnrichedProduct.job_id == job.id)
                        .order_by(EnrichedProduct.id)
                    )
                ).all()
            )
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)

    assert visible_products[0].status == DATA_ENRICHMENT_STATUS_ENRICHED
    assert visible_products[1].status in {
        DATA_ENRICHMENT_STATUS_PENDING,
        DATA_ENRICHMENT_STATUS_RUNNING,
    }
