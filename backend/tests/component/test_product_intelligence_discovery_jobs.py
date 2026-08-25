from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_fills_requested_count_after_strong_first_query_brand_dtc(
    monkeypatch,
) -> None:
    seen_queries: list[str] = []
    recorded_delays: list[float] = []

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        if query == "query one":
            return [
                SearchResult(
                    url="https://www.levi.com/p/04511-2406.html",
                    payload={"title": "Levi's Men 511 Slim Fit Jeans"},
                )
            ]
        return [
            SearchResult(
                url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}
            ),
        ]

    async def fake_sleep(delay: float) -> None:
        recorded_delays.append(delay)

    monkeypatch.setattr(
        "app.intelligence.discovery.build_search_queries",
        lambda product: ["query one", "query two"],
    )
    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(
        "app.intelligence.discovery.asyncio.sleep",
        fake_sleep,
    )
    monkeypatch.setattr(product_intelligence_settings, "search_delay_ms", 25)

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511-2406"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=2,
    )

    assert seen_queries == ["query one", "query two"]
    assert recorded_delays == [0.025]
    assert [candidate.domain for candidate in candidates] == ["levi.com", "macys.com"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_job_stores_source_products_and_llm_option(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/new-directions-shirt/1.html",
        data={
            "brand": "New Directions",
            "title": "Relaxed Shirt",
            "price": "$19.99",
            "url": "https://www.belk.com/p/new-directions-shirt/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    job = await create_product_intelligence_job(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "llm_enrichment_enabled": True,
                "private_label_mode": "flag",
            },
        },
    )

    assert job.options["llm_enrichment_enabled"] is True
    source = await db_session.scalar(
        select(ProductIntelligenceSourceProduct).where(
            ProductIntelligenceSourceProduct.job_id == job.id
        )
    )
    assert source is not None
    assert source.is_private_label is True
    assert source.price == Decimal("19.99")


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_preview_returns_source_and_payload(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        data={
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "price": "$125.00",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick/123.html",
                payload={"provider": provider, "title": "Varick jean"},
            )
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert isinstance(response["job_id"], int)
    assert response["candidates"][0]["source_brand"] == "ralph lauren"
    assert response["candidates"][0]["payload"]["provider"] == "serpapi"
    assert (
        response["candidates"][0]["intelligence"]["canonical_record"]["title"]
        == "Varick jean"
    )
    assert (
        response["candidates"][0]["intelligence"]["canonical_record"]["price"] is None
    )
    assert response["candidates"][0]["intelligence"]["confidence_score"] >= 0
    persisted_match = await db_session.scalar(
        select(ProductIntelligenceMatch).where(
            ProductIntelligenceMatch.job_id == response["job_id"]
        )
    )
    assert persisted_match is not None
    assert persisted_match.candidate_price is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_preview_skips_search_result_llm_enrichment(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/category",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        data={
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "url": "https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        del provider, query, limit
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={
                    "provider": "serpapi",
                    "title": "Levi's Men 511 Slim Fit Jeans",
                },
            )
        ]

    async def fake_run_prompt_task(session, *, task_type, run_id, domain, variables):
        del session, run_id, domain, variables
        if task_type == "product_intelligence_enrichment":
            raise AssertionError("Discovery preview must not call enrichment LLM")
        return LLMTaskResult(
            payload={"brand": "Levis", "confidence": 0.95},
            provider="groq",
            model="llama",
        )

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(
        "app.intelligence.service.run_prompt_task",
        fake_run_prompt_task,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_run_id": run.id,
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "llm_enrichment_enabled": True,
            },
        },
    )

    assert response["candidate_count"] == 1
    assert response["candidates"][0]["intelligence"]["llm_enrichment"] == {
        "requested": False,
        "applied": False,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_prefers_row_source_url_for_query_exclusion(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    seen_queries: list[str] = []

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        return [
            SearchResult(
                url="https://www.example-brand.com/p/item.html",
                payload={"provider": "google_native", "title": "Example Item"},
            )
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.myntra.com/p/shoes/example-item.html",
                    "data": {
                        "title": "Example Item",
                        "brand": "Example Brand",
                        "url": "https://www.belk.com/p/stale-item.html",
                    },
                }
            ],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert seen_queries
    assert all("myntra.com" not in query for query in seen_queries)
    assert all("belk.com" not in query for query in seen_queries)
    assert (
        response["candidates"][0]["source_url"]
        == "https://www.myntra.com/p/shoes/example-item.html"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_uses_product_url_from_listing_record(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://www.belk.com/men/mens-clothing/jeans/",
        surface="ecommerce_listing",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url="https://www.belk.com/men/mens-clothing/jeans/",
        data={
            "brand": "Wrangler\u00ae",
            "title": "Wrangler\u00ae Relaxed Bootcut Jeans",
            "url": "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html",
            "price": "39.95",
        },
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)

    seen_queries: list[str] = []

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        del provider, limit
        seen_queries.append(query)
        return [
            SearchResult(
                url="https://www.wrangler.com/shop/relaxed-bootcut-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "Wrangler Relaxed Bootcut Jeans",
                },
            )
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_record_ids": [record.id],
            "options": {
                "max_source_products": 1,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["candidates"][0]["source_url"] == (
        "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html"
    )
    assert response["candidates"][0]["source_price"] == pytest.approx(39.95)
    assert seen_queries[0] == "site:wrangler.com wrangler Relaxed Bootcut Jeans"
