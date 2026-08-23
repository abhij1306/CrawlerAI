from __future__ import annotations

# ruff: noqa: F403, F405
from .data_enrichment_test_support import *
from .data_enrichment_test_support import _as_async


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_rolls_back_after_sqlalchemy_product_failure(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/batch",
        surface="ecommerce_detail",
    )
    bad_record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/bad",
        data={"title": "Bad Shirt", "category": "Shirts"},
    )
    good_record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/good",
        data={"title": "Good Shirt", "category": "Shirts"},
    )
    db_session.add_all([bad_record, good_record])
    await db_session.commit()
    await db_session.refresh(bad_record)
    await db_session.refresh(good_record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [bad_record.id, good_record.id]},
    )
    calls = 0
    original_rollback = db_session.rollback
    rollbacks = 0

    async def counted_rollback() -> None:
        nonlocal rollbacks
        rollbacks += 1
        await original_rollback()

    def fake_enrich_product(session, *, job, product, record, llm_enabled):
        nonlocal calls
        del session, job, llm_enabled
        calls += 1
        if calls == 1:
            raise PendingRollbackError("flush failed earlier")
        product.category_path = "Apparel & Accessories > Clothing > Shirts"
        product.diagnostics = {"deterministic": True}

    monkeypatch.setattr(db_session, "rollback", counted_rollback)
    monkeypatch.setattr(
        "app.enrichment.service._enrich_product",
        _as_async(fake_enrich_product),
    )

    await run_job(db_session, job)
    products = list(
        (
            await db_session.scalars(
                select(EnrichedProduct)
                .where(EnrichedProduct.job_id == job.id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
    )

    assert rollbacks == 1
    assert job.status == DATA_ENRICHMENT_STATUS_DEGRADED
    assert [product.status for product in products] == [
        DATA_ENRICHMENT_STATUS_FAILED,
        DATA_ENRICHMENT_STATUS_ENRICHED,
    ]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_llm_does_not_overwrite_deterministic_fields(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    def fake_run_prompt_task(
        session,
        *,
        task_type,
        run_id,
        domain,
        variables,
        budget_scope,
        timeout_seconds,
        config_snapshot=None,
    ):
        del (
            session,
            task_type,
            run_id,
            domain,
            variables,
            budget_scope,
            timeout_seconds,
            config_snapshot,
        )
        return LLMTaskResult(
            payload={
                "category_path": "Apparel & Accessories > Clothing > Shirts",
                "color_family": "red",
                "size_normalized": ["XL"],
                "gender_normalized": "male",
                "materials_normalized": ["wool"],
                "availability_normalized": "out_of_stock",
                "intent_attributes": ["useful"],
                "audience": ["linen dress shoppers"],
                "style_tags": ["sharp"],
                "ai_discovery_tags": ["linen-dress"],
                "suggested_bundles": ["boots"],
            }
        )

    monkeypatch.setattr(
        "app.enrichment.service.run_prompt_task",
        _as_async(fake_run_prompt_task),
    )
    run = await create_test_run(
        url="https://example.com/products/mystery",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/dress",
        data={
            "title": "Linen Dress",
            "category": "Dresses",
            "color": "navy",
            "size": "medium",
            "gender": "women",
            "materials": "linen",
            "availability": "In stock",
        },
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": True}},
    )

    await run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()

    assert product.category_path == "Apparel & Accessories > Clothing > Dresses"
    assert product.color_family == "blue"
    assert product.size_normalized == ["M"]
    assert product.gender_normalized == "female"
    assert product.materials_normalized == ["linen"]
    assert product.availability_normalized == "in_stock"
    assert product.intent_attributes == ["useful"]
    assert product.audience == ["linen dress shoppers"]
    assert product.suggested_bundles == ["boots"]


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_llm_filters_ai_discovery_tags_to_allowed_evidence(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    def fake_run_prompt_task(
        session,
        *,
        task_type,
        run_id,
        domain,
        variables,
        budget_scope,
        timeout_seconds,
        config_snapshot=None,
    ):
        del (
            session,
            task_type,
            run_id,
            domain,
            variables,
            budget_scope,
            timeout_seconds,
            config_snapshot,
        )
        return LLMTaskResult(
            payload={
                "intent_attributes": ["summer weddings"],
                "ai_discovery_tags": ["linen-dress", "cosmic-made-up-tag"],
            }
        )

    monkeypatch.setattr(
        "app.enrichment.service.run_prompt_task",
        _as_async(fake_run_prompt_task),
    )
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/linen-dress",
        data={
            "title": "Linen Dress",
            "category": "Dresses",
            "materials": "linen",
        },
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": True}},
    )

    with caplog.at_level("WARNING"):
        await run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()

    assert product.ai_discovery_tags == ["linen-dress"]
    assert "cosmic-made-up-tag" in caplog.text


@pytest.mark.regression
def test_ai_discovery_allowed_tags_prioritizes_source_importance() -> None:
    product = EnrichedProduct(
        seo_keywords=[f"seo-{index}" for index in range(55)],
        category_path="Apparel & Accessories > Clothing > Dresses",
        color_family="blue",
        gender_normalized="female",
        materials_normalized=["linen"],
        size_normalized=["M"],
    )

    tags = ai_discovery_allowed_tags_for_product(product)

    assert len(tags) == 50
    assert tags[:2] == ["seo-0", "seo-1"]
    assert "apparel-accessories-clothing-dresses" not in tags


@pytest.mark.asyncio
@pytest.mark.regression
async def test_data_enrichment_llm_ignores_non_dict_payload(
    db_session: AsyncSession,
    create_test_run,
    test_user,
    monkeypatch,
) -> None:
    def fake_run_prompt_task(
        session,
        *,
        task_type,
        run_id,
        domain,
        variables,
        budget_scope,
        timeout_seconds,
        config_snapshot=None,
    ):
        del (
            session,
            task_type,
            run_id,
            domain,
            variables,
            budget_scope,
            timeout_seconds,
            config_snapshot,
        )
        return LLMTaskResult(payload="bad-payload")

    monkeypatch.setattr(
        "app.enrichment.service.run_prompt_task",
        _as_async(fake_run_prompt_task),
    )
    run = await create_test_run(
        url="https://example.com/products/dress",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://example.com/products/dress",
        data={"title": "Linen Dress", "category": "Dresses"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    job = await create_data_enrichment_job(
        db_session,
        user=test_user,
        payload={"source_record_ids": [record.id], "options": {"llm_enabled": True}},
    )

    await run_job(db_session, job)
    product = (
        await db_session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.job_id == job.id)
        )
    ).one()

    assert product.category_path == "Apparel & Accessories > Clothing > Dresses"
    assert product.diagnostics["llm"]["applied"] is False
