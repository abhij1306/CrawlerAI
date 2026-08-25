from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_passes_pool_limit_to_search(
    monkeypatch,
) -> None:
    limits: list[int | None] = []

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        limits.append(limit)
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}
            ),
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 4)

    await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=5,
    )

    assert limits
    assert set(limits) == {20}


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_keeps_multiple_listings_per_domain(
    monkeypatch,
) -> None:
    # A product can be listed by multiple third-party sellers on one marketplace,
    # so discovery must keep more than one distinct listing per domain (bounded only
    # by the user's max_candidates request), not collapse to one per domain.
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.ebay.com/itm/1", payload={"title": "Levi 511"}
            ),
            SearchResult(
                url="https://www.ebay.com/itm/2", payload={"title": "Levi 511 sale"}
            ),
            SearchResult(
                url="https://www.macys.com/p/1.html", payload={"title": "Levi 511"}
            ),
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=5,
    )

    domains = sorted(candidate.domain for candidate in candidates)
    # Both eBay third-party listings survive alongside the macys listing.
    assert domains == ["ebay.com", "ebay.com", "macys.com"]
    urls = {candidate.url for candidate in candidates}
    assert "https://www.ebay.com/itm/1" in urls
    assert "https://www.ebay.com/itm/2" in urls


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_prioritizes_brand_site_over_aggregator_pool(
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        if "site:levi.com" in query:
            return [
                SearchResult(
                    url="https://thesummitbirmingham.com/buy/product/511",
                    payload={"title": "Levi 511"},
                ),
                SearchResult(
                    url="https://www.hamiltonplace.com/products/product/511",
                    payload={"title": "Levi 511"},
                ),
                SearchResult(
                    url="https://www.coolspringsgalleria.com/products/product/511",
                    payload={"title": "Levi 511"},
                ),
            ]
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html", payload={"title": "Levi 511"}
            ),
            SearchResult(
                url="https://www.macys.com/p/04511.html", payload={"title": "Levi 511"}
            ),
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 4)

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=2,
    )

    assert [candidate.domain for candidate in candidates] == ["levi.com", "macys.com"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_skips_invalid_result_urls(
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        return [
            SearchResult(
                url="javascript:void(0)",
                payload={"provider": provider, "title": "Bad scheme"},
            ),
            SearchResult(
                url="",
                payload={"provider": provider, "title": "Empty"},
            ),
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={"provider": provider, "title": "Levi 511"},
            ),
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert len(candidates) == 1
    assert candidates[0].domain == "levi.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_listing_urls_from_serpapi() -> (
    None
):
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/",
                payload={
                    "provider": "serpapi",
                    "title": "Men's Jeans & Denim",
                    "snippet": "Shop fits, washes and denim styles.",
                },
            ),
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html",
                payload={
                    "provider": "serpapi",
                    "title": "Polo Ralph Lauren Varick Slim Straight Garment-Dyed Jean",
                    "snippet": "Product page for Varick garment-dyed jeans.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Polo Ralph Lauren",
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_html_listing_urls() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "Men's Jeans & Denim",
                    "snippet": "Shop denim by fit and wash.",
                },
            ),
            SearchResult(
                url="https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html",
                payload={
                    "provider": "serpapi",
                    "title": "Polo Ralph Lauren Varick Slim Straight Garment-Dyed Jean",
                    "snippet": "Product page for Varick garment-dyed jeans.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Polo Ralph Lauren",
            "title": "Varick Slim Straight Garment-Dyed Jeans",
            "url": "https://www.belk.com/p/polo-ralph-lauren-varick-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.ralphlauren.com/men-clothing-jeans/varick-slim-straight-garment-dyed-jean/123.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_keeps_matching_slug_without_detail_marker() -> (
    None
):
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.levi.com/men/jeans/511-slim-fit-stretch-denim",
                payload={
                    "provider": "serpapi",
                    "title": "Levi's 511 Slim Fit Stretch Denim Jeans",
                    "snippet": "Official Levi's product page.",
                },
            )
        ]

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Stretch Denim Jeans",
            "url": "https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.levi.com/men/jeans/511-slim-fit-stretch-denim"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_allows_marketplace_item_ids_when_title_matches() -> (
    None
):
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.ebay.com/itm/188098451561",
                payload={
                    "provider": "serpapi_immersive",
                    "title": "Izod Men's Comfort Stretch Blue Denim Jeans",
                    "source": "eBay",
                    "product_id": "3501016343738340012",
                },
            )
        ]

    candidates = await discover_candidates(
        {
            "brand": "IZOD",
            "title": "Comfort Stretch Blue Denim Jeans",
            "sku": "3203394I39JN16",
            "url": "https://www.belk.com/p/izod-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.ebay.com/itm/188098451561"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_editorial_brand_pages() -> None:
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://eu.wrangler.com/uk-en/how%20to%20style%20bootcut%20jeans/how-to-wear-bootcut-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "How to Wear Bootcut Jeans",
                    "snippet": "A styling guide from Wrangler.",
                },
            ),
            SearchResult(
                url="https://www.wrangler.com/browse/relaxed-fit-bootcut-jeans.html",
                payload={
                    "provider": "serpapi",
                    "title": "Relaxed Fit Bootcut Jeans",
                    "snippet": "Wrangler product page.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Wrangler\u00ae",
            "title": "Wrangler\u00ae Relaxed Bootcut Jeans",
            "url": "https://www.belk.com/p/wrangler--relaxed-bootcut-jeans-/3200040112342570.html",
        },
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.wrangler.com/browse/relaxed-fit-bootcut-jeans.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_unrelated_google_native_products() -> (
    None
):
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        del query, limit
        return [
            SearchResult(
                url="https://www.levi.com/p/505-regular-fit-mens-jeans/005050260.html",
                payload={
                    "provider": "google_native",
                    "title": "Levi's 505 Regular Fit Men's Jeans",
                    "snippet": "Classic straight leg jeans.",
                },
            ),
            SearchResult(
                url="https://www.levi.com/p/511-slim-fit-mens-jeans/045112406.html",
                payload={
                    "provider": "google_native",
                    "title": "Levi's 511 Slim Fit Men's Jeans",
                    "snippet": "Slim fit jeans, style 04511-2406.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Levis",
            "title": "Men 511 Slim Fit Jeans",
            "sku": "04511-2406",
            "url": "https://www.belk.com/p/levis-511-slim-fit-jeans/1.html",
        },
        source_domain_value="belk.com",
        provider="google_native",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.levi.com/p/511-slim-fit-mens-jeans/045112406.html"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_rejects_google_native_source_domain_and_url() -> (
    None
):
    async def fake_run_query(query: str, limit: int) -> list[SearchResult]:
        assert "belk.com" not in query
        del limit
        return [
            SearchResult(
                url="https://www.belk.com/p/nike-womens-run-defy-sneakers/2900020HM9593.html",
                payload={
                    "provider": "google_native",
                    "title": "Women's Run Defy Sneakers",
                    "snippet": "Nike sneakers at Belk.",
                },
            ),
            SearchResult(
                url="https://www.nike.com/t/run-defy-womens-road-running-shoes/HM9593",
                payload={
                    "provider": "google_native",
                    "title": "Nike Run Defy Women's Road Running Shoes",
                    "snippet": "Style HM9593.",
                },
            ),
        ]

    candidates = await discover_candidates(
        {
            "brand": "Nike",
            "title": "Women's Run Defy Sneakers",
            "sku": "HM9593",
            "url": "https://www.belk.com/p/nike-womens-run-defy-sneakers/2900020HM9593.html",
        },
        source_domain_value="belk.com",
        provider="google_native",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
        run_query=fake_run_query,
    )

    assert [candidate.url for candidate in candidates] == [
        "https://www.nike.com/t/run-defy-womens-road-running-shoes/HM9593"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_keeps_search_delay_while_filling_pool(
    monkeypatch,
) -> None:
    recorded_delays: list[float] = []

    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        if query == "query one":
            return [
                SearchResult(
                    url="https://www.levi.com/p/04511.html",
                    payload={"title": "Levi 511"},
                ),
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
    monkeypatch.setattr(product_intelligence_settings, "discovery_pool_multiplier", 2)

    candidates = await discover_candidates(
        {"brand": "Levis", "title": "Men 511 Slim Fit Jeans", "sku": "04511"},
        source_domain_value="belk.com",
        provider="serpapi",
        allowed_domains=[],
        excluded_domains=[],
        max_candidates=1,
    )

    assert recorded_delays == [0.025]
    assert len(candidates) == 1
    assert candidates[0].domain == "levi.com"
