from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_reuses_one_query_runner_for_multiple_sources(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    enter_count = 0
    seen_queries: list[str] = []

    class _Runner:
        async def __aenter__(self):
            nonlocal enter_count
            enter_count += 1

            async def _run(query: str, limit: int) -> list[SearchResult]:
                del limit
                seen_queries.append(query)
                token = len(seen_queries)
                return [
                    SearchResult(
                        url=f"https://www.levi.com/p/{token}.html",
                        payload={
                            "provider": "google_native",
                            "title": f"Product {token} 511 Jeans",
                            "price": "$55.00",
                        },
                    )
                ]

            return _run

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        "app.intelligence.service.shared_query_runner",
        lambda provider: _Runner(),
    )

    response = await discover_product_intelligence_candidates(
        db_session,
        user=test_user,
        payload={
            "source_records": [
                {
                    "source_url": "https://www.belk.com/p/one.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Product One 511 Jeans",
                        "url": "https://www.belk.com/p/one.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/two.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Product Two 511 Jeans",
                        "url": "https://www.belk.com/p/two.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "search_provider": "google_native",
            },
        },
    )

    assert response["candidate_count"] == 2
    assert enter_count == 1
    assert len(seen_queries) >= 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_returns_max_urls_per_input_source(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        quoted = query.split('"')
        title_source = (
            quoted[3]
            if len(quoted) > 3
            else quoted[1]
            if len(quoted) > 1
            else quoted[0]
        )
        title_token = title_source.split()[0]
        return [
            SearchResult(
                url=f"https://www.levi.com/p/{title_token}.html",
                payload={"provider": provider, "title": title_token},
            ),
            SearchResult(
                url=f"https://www.macys.com/p/{title_token}.html",
                payload={"provider": provider, "title": title_token},
            ),
            SearchResult(
                url=f"https://www.nordstrom.com/p/{title_token}.html",
                payload={"provider": provider, "title": title_token},
            ),
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
                    "source_url": f"https://www.belk.com/p/{index}.html",
                    "data": {
                        "brand": "Levis",
                        "title": f"Product {index} 511 Jeans",
                        "url": f"https://www.belk.com/p/{index}.html",
                    },
                }
                for index in range(4)
            ],
            "options": {
                "max_source_products": 4,
                "max_candidates_per_product": 3,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["source_count"] == 4
    assert response["candidate_count"] == 12
    assert {candidate["source_index"] for candidate in response["candidates"]} == {
        0,
        1,
        2,
        3,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_source_count_excludes_private_label(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                url="https://www.levi.com/p/511.html",
                payload={"provider": provider, "title": "511 Jeans"},
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
                    "source_url": "https://www.belk.com/p/private.html",
                    "data": {
                        "brand": "New Directions",
                        "title": "Private label shirt",
                        "url": "https://www.belk.com/p/private.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "private_label_mode": "exclude",
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert response["candidates"][0]["source_index"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_defaults_private_label_mode_to_exclude(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        del query
        return [
            SearchResult(
                url="https://www.levi.com/p/511.html",
                payload={"provider": provider, "title": "511 Jeans"},
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
                    "source_url": "https://www.belk.com/p/private.html",
                    "data": {
                        "brand": "New Directions",
                        "title": "Private label shirt",
                        "url": "https://www.belk.com/p/private.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 1,
                "search_provider": "serpapi",
            },
        },
    )

    assert response["source_count"] == 1
    assert response["candidate_count"] == 1
    assert response["candidates"][0]["source_index"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_searches_title_only_sources(
    db_session: AsyncSession,
    test_user,
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        title_token = query.split()[0]
        return [
            SearchResult(
                url=f"https://www.example-retailer.com/p/{title_token}-1.html",
                payload={"provider": provider, "title": title_token},
            ),
            SearchResult(
                url=f"https://www.example-brand.com/p/{title_token}-2.html",
                payload={"provider": provider, "title": title_token},
            ),
            SearchResult(
                url=f"https://www.example-market.com/p/{title_token}-3.html",
                payload={"provider": provider, "title": title_token},
            ),
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
                    "source_url": "https://www.belk.com/p/branded.html",
                    "data": {
                        "brand": "Levis",
                        "title": "Branded 511 Jeans",
                        "url": "https://www.belk.com/p/branded.html",
                    },
                },
                {
                    "source_url": "https://www.belk.com/p/unbranded.html",
                    "data": {
                        "title": "Unbranded Slim Jeans",
                        "url": "https://www.belk.com/p/unbranded.html",
                    },
                },
            ],
            "options": {
                "max_source_products": 2,
                "max_candidates_per_product": 3,
                "search_provider": "serpapi",
                "confidence_threshold": 0.0,
            },
        },
    )

    assert response["source_count"] == 2
    assert response["candidate_count"] == 6
    assert {candidate["source_index"] for candidate in response["candidates"]} == {0, 1}


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_candidate_poll_marks_timeout(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    job = ProductIntelligenceJob(user_id=test_user.id, options={}, summary={})
    db_session.add(job)
    await db_session.flush()
    source = ProductIntelligenceSourceProduct(
        job_id=job.id,
        source_url="https://www.belk.com/p/1",
        brand="Levi's",
        normalized_brand="levi's",
        title="511 Jeans",
        payload={},
    )
    db_session.add(source)
    await db_session.flush()
    candidate = ProductIntelligenceCandidate(
        job_id=job.id,
        source_product_id=source.id,
        url="https://www.levi.com/p/1",
        status=PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
        payload={},
    )
    db_session.add(candidate)
    await db_session.flush()

    monkeypatch.setattr(product_intelligence_settings, "candidate_poll_seconds", 0.0)
    await poll_candidate_and_score(db_session, job, candidate)

    assert candidate.status == PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT
