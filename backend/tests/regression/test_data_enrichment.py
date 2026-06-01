from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import PendingRollbackError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.data_enrichment import EnrichedProduct
from app.models.crawl_run import CrawlRecord
from app.schemas.data_enrichment import DataEnrichmentJobDetailResponse
from app.services.llm.types import LLMTaskResult
from app.services.config.data_enrichment import (
    DATA_ENRICHMENT_COLOR_FAMILY_ALIASES,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_FAILED,
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_STATUS_RUNNING,
    DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
)
from app.services.data_enrichment.service import (
    ai_discovery_allowed_tags_for_product,
    run_job,
    build_deterministic_enrichment,
    build_data_enrichment_job_payload,
    create_data_enrichment_job,
    get_data_enrichment_job,
    list_data_enrichment_jobs,
)
from app.services.data_enrichment import shopify_catalog
from app.services.data_enrichment.deterministic import normalize_price
from app.services.data_enrichment.deterministic import (
    category_match_values,
    category_url_context,
    percentage_material_parse,
    plausible_size_value,
)
from app.services.data_enrichment.shopify_catalog import (
    accessory_path_conflict,
    normalize_taxonomy_token,
    special_token_conflict,
    sport_specific_conflict,
    taxonomy_candidate_conflicts,
    toys_vs_sports_conflict,
)

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _as_async(fn):
    async def _wrapped(*args, **kwargs):
        await asyncio.sleep(0)
        return fn(*args, **kwargs)

    return _wrapped


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
        "app.services.data_enrichment.service._enrich_product",
        _blocking_enrich_product,
    )

    task = asyncio.create_task(run_job(db_session, job))
    await asyncio.wait_for(started.wait(), timeout=2)
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )
    async with session_factory() as check_session:
        visible_job = await check_session.get(type(job), job.id)

    release.set()
    await task

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
        "app.services.data_enrichment.service._enrich_product",
        _blocking_second_product,
    )

    task = asyncio.create_task(run_job(db_session, job))
    await asyncio.wait_for(first_done.wait(), timeout=2)
    await asyncio.wait_for(second_started.wait(), timeout=2)
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

    release.set()
    await task

    assert visible_products[0].status == DATA_ENRICHMENT_STATUS_ENRICHED
    assert visible_products[1].status in {
        DATA_ENRICHMENT_STATUS_PENDING,
        DATA_ENRICHMENT_STATUS_RUNNING,
    }


@pytest.mark.regression
def test_plausible_size_value_accepts_known_numeric_system_before_strong_gate() -> None:
    assert plausible_size_value(
        "42",
        aliases={},
        systems={"numeric": {"42"}},
        require_strong=False,
    )


@pytest.mark.regression
def test_percentage_material_parse_trims_context_near_percentage() -> None:
    assert percentage_material_parse("Made with cotton 60 percent and polyester 40%.") == [
        "cotton",
        "polyester",
    ]


@pytest.mark.regression
def test_category_url_context_returns_none_for_malformed_input() -> None:
    assert category_url_context("http://[bad") is None


@pytest.mark.regression
def test_normalize_taxonomy_token_keeps_size_tokens_and_singularizes() -> None:
    assert normalize_taxonomy_token("s") == "s"
    assert normalize_taxonomy_token("m") == "m"
    assert normalize_taxonomy_token("l") == "l"
    assert normalize_taxonomy_token("handbags") == "bag"
    assert normalize_taxonomy_token("dresses") == "dress"


@pytest.mark.regression
def test_taxonomy_conflict_helpers_keep_accessory_and_sport_rules_explicit() -> None:
    assert accessory_path_conflict(
        "electronics > audio > audio accessories",
        {"headphone"},
    )
    assert not accessory_path_conflict(
        "electronics > audio > audio accessories",
        {"case"},
    )
    assert toys_vs_sports_conflict("toys & games > games", {"fitness"})
    assert not toys_vs_sports_conflict("toys & games > building toys", {"toy"})
    assert sport_specific_conflict({"soccer"}, {"basketball"})
    assert special_token_conflict({"ball"}, {"basketball"})
    assert taxonomy_candidate_conflicts(
        {"fitness"},
        "Toys & Games > Games",
    )


@pytest.mark.regression
def test_normalize_price_range_rejects_trailing_noise() -> None:
    assert normalize_price(
        {"price": "$10 - $20 each"},
        source_url="https://example.com/products/widget",
    ) == {"price_min": 10.0, "price_max": 20.0, "currency": "USD"}
    noisy = normalize_price(
        {"price": "$10 - $20 random words"},
        source_url="https://example.com/products/widget",
    )
    assert noisy == {"amount": 10.0, "currency": "USD"}


@pytest.mark.regression
def test_data_enrichment_variant_fit_does_not_become_size() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Cotton Trouser",
            "category": "Pants",
            "variants": [
                {
                    "size": "medium",
                    "fit": "regular fit",
                    "width": "wide",
                }
            ],
        },
        source_url="https://example.com/products/trouser",
    )

    assert enrichment["size_normalized"] == ["M"]


@pytest.mark.regression
def test_data_enrichment_category_uses_primary_category_before_title_noise() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "KitchenAid 13-cup food processor",
            "brand": "KitchenAid",
            "category": "Kitchen Appliances",
        },
        source_url="https://example.com/products/food-processor",
    )

    assert (
        enrichment["category_path"]
        == "Home & Garden > Kitchen & Dining > Kitchen Appliances"
    )
    assert "Cup Sleeves" not in str(enrichment["category_path"])


@pytest.mark.regression
def test_data_enrichment_exact_shopify_path_match_wins() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Navy Linen Midi Dress",
            "category": "Apparel & Accessories > Clothing > Dresses",
        },
        source_url="https://example.com/products/dress",
    )

    assert enrichment["category_path"] == "Apparel & Accessories > Clothing > Dresses"
    assert enrichment["_taxonomy_match"]["source"] == "exact_path"


@pytest.mark.regression
def test_data_enrichment_phrase_match_inputs_exclude_bulky_evidence_fields() -> None:
    values = category_match_values(
        {
            "title": "leather disco biker jacket",
            "category": "Men > Clothing > Leather Jackets",
            "description": "Short description says apparel accessory token.",
            "materials": "Lamb Skin/glass/Polyester/Spandex/Elastane/Polyester",
            "specifications": {"fit": "regular", "care": "professional clean only"},
        }
    )

    flattened = " ".join(str(value) for value in values)

    assert "leather disco biker jacket" in flattened
    assert "Men > Clothing > Leather Jackets" in flattened
    assert "Short description says apparel accessory token" not in flattened
    assert "Lamb Skin" not in flattened
    assert "professional clean only" not in flattened


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_uses_index_lookup() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10-2",
        "category_path": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "attribute_handles": [],
    }
    taxonomy_index = shopify_catalog.TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={"coats jackets": (row,)},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "coats jackets",
        taxonomy_index,
        source_tokens={"leather", "coats", "jackets"},
    )

    assert match is not None
    assert match["category_path"] == row["category_path"]


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_allows_token_subset_match() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10-2",
        "category_path": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "leaf": "Coats & Jackets",
        "path_match_tokens": {"apparel", "accessory", "clothing", "outerwear", "coat", "jacket"},
        "attribute_handles": [],
    }
    taxonomy_index = shopify_catalog.TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(row,),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "outerwear jacket",
        taxonomy_index,
        source_tokens={"leather", "outerwear", "jacket"},
    )

    assert match is not None
    assert match["category_path"] == row["category_path"]


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_rejects_generic_subset_match() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10-2",
        "category_path": "Apparel & Accessories > Clothing > Outerwear > Coats & Jackets",
        "leaf": "Coats & Jackets",
        "path_match_tokens": {"apparel", "accessory", "clothing", "outerwear", "coat", "jacket"},
        "attribute_handles": [],
    }
    taxonomy_index = shopify_catalog.TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(row,),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "apparel clothing",
        taxonomy_index,
        source_tokens={"apparel", "clothing"},
    )

    assert match is None


@pytest.mark.regression
def test_data_enrichment_taxonomy_path_phrase_does_not_reject_valid_accessory_term() -> None:
    row = {
        "category_id": "gid://shopify/TaxonomyCategory/aa-1-10",
        "category_path": "Apparel & Accessories > Clothing Accessories",
        "path_match_tokens": {"apparel", "accessory", "clothing"},
        "attribute_handles": [],
    }
    taxonomy_index = shopify_catalog.TaxonomyIndex(
        version=DATA_ENRICHMENT_TAXONOMY_VERSION,
        categories=(row,),
        exact_lookup={},
        leaf_lookup={},
        path_phrase_lookup={"clothing accessory": (row,)},
        id_lookup={},
    )

    match = shopify_catalog.phrase_path_category_match(
        "clothing accessory",
        taxonomy_index,
        source_tokens={"clothing", "accessory"},
    )

    assert match is not None
    assert match["category_path"] == row["category_path"]


@pytest.mark.regression
def test_data_enrichment_color_aliases_cover_common_retail_names() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Wrap Dress",
            "category": "Dresses",
            "color": "Blush",
        },
        source_url="https://example.com/products/wrap-dress",
    )

    assert enrichment["color_family"] == "pink"


@pytest.mark.regression
def test_data_enrichment_context_only_tokens_exclude_product_terms() -> None:
    assert not {"s", "single", "star"} & set(DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS)


@pytest.mark.regression
def test_data_enrichment_color_aliases_do_not_mix_blue_green_intermediates() -> None:
    assert "teal" not in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES["blue"]
    assert "turquoise" not in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES["blue"]
    assert "teal" not in DATA_ENRICHMENT_COLOR_FAMILY_ALIASES["green"]


@pytest.mark.regression
def test_data_enrichment_size_split_handles_semicolon_and_middle_dot() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Running Shoe",
            "product_type": "Shoes",
            "size": "38; 40 · 42",
        },
        source_url="https://example.com/products/running-shoe",
    )

    assert enrichment["size_normalized"] == ["38", "40", "42"]
    assert enrichment["size_system"] == "numeric"


@pytest.mark.regression
def test_data_enrichment_price_infers_firstcry_currency() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Black Seascape Stretch Bracelet",
            "price": "868.21",
            "category": "Bracelets",
        },
        source_url="https://www.firstcry.com/example/product-detail",
    )

    assert enrichment["price_normalized"] == {"amount": 868.21, "currency": "INR"}


@pytest.mark.regression
def test_data_enrichment_seo_keywords_include_title_bigrams() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Black Seascape Stretch Bracelet",
            "price": "868.21",
            "category": "Bracelets",
        },
        source_url="https://www.firstcry.com/example/product-detail",
    )

    assert "black seascape" in set(enrichment["seo_keywords"] or [])


@pytest.mark.regression
def test_data_enrichment_seo_keywords_preserve_brand_phrase_and_dedupe_stems() -> None:
    enrichment = build_deterministic_enrichment(
        {
            "title": "Running Run Jacket",
            "brand": "Calvin Klein",
            "category": "Jackets",
        },
        source_url="https://example.com/products/run-jacket",
    )

    keywords = set(enrichment["seo_keywords"] or [])
    assert "calvin klein" in keywords
    assert not {"running", "run"} <= keywords


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
        "app.services.data_enrichment.service._enrich_product",
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
        "app.services.data_enrichment.service.run_prompt_task",
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
        "app.services.data_enrichment.service.run_prompt_task",
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
        "app.services.data_enrichment.service.run_prompt_task",
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
