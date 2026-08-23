from __future__ import annotations

# ruff: noqa: F403, F405
from .product_intelligence_test_support import *


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_discovery_preserves_serpapi_payload(
    monkeypatch,
) -> None:
    async def fake_search_results(
        provider: str, query: str, *, limit: int | None = None
    ) -> list[SearchResult]:
        return [
            SearchResult(
                url="https://www.levi.com/p/04511.html",
                payload={
                    "provider": "serpapi",
                    "title": "Levi's 511 Slim Fit Jeans",
                    "snippet": "Official product page",
                },
            )
        ]

    monkeypatch.setattr(
        "app.intelligence.discovery._search_results",
        fake_search_results,
    )

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
        max_candidates=1,
    )

    assert candidates[0].payload["provider"] == "serpapi"
    assert candidates[0].payload["snippet"] == "Official product page"


@pytest.mark.component
def test_product_intelligence_parses_serpapi_shopping_payload() -> None:
    results = parse_serpapi_shopping_results(
        {
            "shopping_results": [
                {
                    "position": 1,
                    "title": "Crown & Ivy Floral Midi Dress",
                    "source": "Belk",
                    "link": "https://www.example.com/p/crown-ivy-floral-midi-dress/123.html",
                    "product_id": "987654321",
                    "product_link": "https://www.google.com/search?ibp=oshop&q=dress",
                    "serpapi_immersive_product_api": "https://serpapi.com/search.json?engine=google_immersive_product&page_token=abc",
                    "price": "$49.99",
                    "extracted_price": 49.99,
                    "thumbnail": "https://example.com/image.jpg",
                    "rating": 4.8,
                    "reviews": 27,
                    "delivery": "Free delivery",
                }
            ]
        }
    )

    assert (
        results[0].url
        == "https://www.example.com/p/crown-ivy-floral-midi-dress/123.html"
    )
    assert results[0].payload["provider"] == "serpapi_shopping"
    assert results[0].payload["product_id"] == "987654321"
    assert results[0].payload["extracted_price"] == pytest.approx(49.99)
    assert results[0].payload["thumbnail"] == "https://example.com/image.jpg"


@pytest.mark.component
def test_product_intelligence_parses_serpapi_immersive_store_links() -> None:
    results = parse_serpapi_immersive_results(
        {
            "product_results": {
                "title": "Levi's 511 Slim Fit Jeans",
                "product_id": "immersive-product-id",
                "description": "Slim fit jeans.",
                "thumbnails": ["https://example.com/image.jpg"],
                "stores": [
                    {
                        "name": "Levi's",
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                        "price": "$69.50",
                        "extracted_price": 69.5,
                        "shipping": "Free shipping",
                    }
                ],
            }
        },
        parent={
            "product_id": "shopping-product-id",
            "product_link": "https://www.google.com/search?ibp=oshop&q=levi",
        },
        limit=5,
    )

    assert results[0].url == "https://www.levi.com/p/04511.html"
    assert results[0].payload["provider"] == "serpapi_immersive"
    assert results[0].payload["product_id"] == "immersive-product-id"
    assert (
        results[0].payload["product_link"]
        == "https://www.google.com/search?ibp=oshop&q=levi"
    )
    assert results[0].payload["extracted_price"] == pytest.approx(69.5)


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_searches_brand_organic_then_shopping(
    monkeypatch,
) -> None:
    engines: list[str] = []
    queries: list[str] = []

    async def fake_engine(
        query: str, *, engine: str, limit: int | None = None
    ) -> dict[str, object]:
        del limit
        engines.append(engine)
        queries.append(query)
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "source": "Levi's",
                        "link": "https://www.levi.com/p/04511.html",
                        "product_id": "shopping-product-id",
                    }
                ]
            }
        return {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Levi's 511 Slim Fit Jeans",
                    "link": "https://www.levi.com/p/04511.html",
                    "snippet": "Official product page",
                }
            ]
        }

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)

    results = await discovery_module._search_serpapi(
        "levi 511 site:levi.com",
        limit=5,
    )

    assert set(engines) == {"google_shopping", "google"}
    assert sorted(queries) == [
        "levi 511",
        "levi 511 site:levi.com",
    ]
    assert [result.payload["provider"] for result in results] == ["serpapi"]
    assert results[0].url == "https://www.levi.com/p/04511.html"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_expands_immersive_store_links(
    monkeypatch,
) -> None:
    engines: list[str] = []

    async def fake_engine(
        query: str, *, engine: str, limit: int | None = None
    ) -> dict[str, object]:
        del query, limit
        engines.append(engine)
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Columbia Men's Tamiami II Short Sleeve Shirt",
                        "source": "Columbia Sportswear",
                        "product_id": "shopping-product-id",
                        "product_link": "https://www.google.com/search?ibp=oshop&q=columbia",
                        "serpapi_immersive_product_api": "https://serpapi.com/search.json?engine=google_immersive_product&page_token=abc",
                    }
                ]
            }
        return {"organic_results": []}

    async def fake_immersive(item: dict[str, object]) -> dict[str, object]:
        assert item["product_id"] == "shopping-product-id"
        return {
            "product_results": {
                "title": "Columbia Men's Tamiami II Short Sleeve Shirt",
                "product_id": "immersive-product-id",
                "stores": [
                    {
                        "name": "Columbia Sportswear",
                        "title": "Men's PFG Tamiami II Short Sleeve Shirt",
                        "link": "https://www.columbia.com/p/mens-pfg-tamiami-ii-short-sleeve-shirt-big-FM7253.html",
                    }
                ],
            }
        }

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)
    monkeypatch.setattr(
        discovery_module, "_search_serpapi_immersive_product", fake_immersive
    )

    results = await discovery_module._search_serpapi(
        "columbia big tall tamiami II SS Shirt",
        limit=5,
    )

    assert engines == ["google_shopping"]
    assert (
        results[0].url
        == "https://www.columbia.com/p/mens-pfg-tamiami-ii-short-sleeve-shirt-big-FM7253.html"
    )
    assert results[0].payload["provider"] == "serpapi_immersive"
    assert results[0].payload["product_id"] == "immersive-product-id"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_runs_identifier_organic_without_immersive(
    monkeypatch,
) -> None:
    engines: list[str] = []

    async def fake_engine(
        query: str, *, engine: str, limit: int | None = None
    ) -> dict[str, object]:
        del limit
        engines.append(engine)
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Wrangler Relaxed Bootcut Jeans",
                        "source": "Wrangler",
                        "product_id": "shopping-product-id",
                        "link": "https://www.macys.com/p/wrangler-jeans/123.html",
                    }
                ]
            }
        return {
            "organic_results": [
                {
                    "position": 1,
                    "title": "Wrangler Relaxed Bootcut Jeans",
                    "link": "https://www.wrangler.com/shop/relaxed-bootcut-jeans.html",
                    "snippet": "Official product page.",
                }
            ]
        }

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)

    results = await discovery_module._search_serpapi(
        "wrangler relaxed bootcut jeans 1123425700 site:wrangler.com",
        limit=5,
    )

    assert engines.count("google") == 1
    assert engines.count("google_shopping") == 1
    assert [result.payload["provider"] for result in results] == [
        "serpapi",
        "serpapi_shopping",
    ]
    assert results[0].url == "https://www.wrangler.com/shop/relaxed-bootcut-jeans.html"


@pytest.mark.asyncio
@pytest.mark.component
async def test_product_intelligence_serpapi_keeps_brand_site_lookup_when_shopping_has_multiple_results(
    monkeypatch,
) -> None:
    engines: list[tuple[str, str]] = []

    async def fake_engine(
        query: str, *, engine: str, limit: int | None = None
    ) -> dict[str, object]:
        del limit
        engines.append((engine, query))
        if engine == "google_shopping":
            return {
                "shopping_results": [
                    {
                        "position": 1,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "source": "Macy's",
                        "link": "https://www.macys.com/p/levi-511/1.html",
                    },
                    {
                        "position": 2,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "source": "Amazon",
                        "link": "https://www.amazon.com/levi-511/2.html",
                    },
                ]
            }
        if query == "levi 511 site:levi.com":
            return {
                "organic_results": [
                    {
                        "position": 1,
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                        "snippet": "Official product page",
                    }
                ]
            }
        return {"organic_results": []}

    monkeypatch.setattr(discovery_module, "_search_serpapi_engine", fake_engine)

    results = await discovery_module._search_serpapi(
        "levi 511 site:levi.com",
        limit=5,
    )

    assert ("google", "levi 511 site:levi.com") in engines
    assert ("google", "levi 511") not in engines
    assert results[0].url == "https://www.levi.com/p/04511.html"
    assert results[0].payload["provider"] == "serpapi"


@pytest.mark.component
def test_product_intelligence_serpapi_shopping_query_strips_site_filters() -> None:
    assert (
        discovery_module._shopping_query(
            "wrangler relaxed bootcut jeans site:wrangler.com -site:belk.com"
        )
        == "wrangler relaxed bootcut jeans"
    )


@pytest.mark.component
def test_product_intelligence_parses_serpapi_immersive_limit_before_about_link() -> (
    None
):
    results = parse_serpapi_immersive_results(
        {
            "product_results": {
                "title": "Levi's 511 Slim Fit Jeans",
                "product_id": "immersive-product-id",
                "stores": [
                    {
                        "name": "Levi's",
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                    }
                ],
                "about_the_product": {
                    "title": "About Levi's 511 Slim Fit Jeans",
                    "link": "https://www.levi.com/us/en_us/product/511",
                    "displayed_link": "levi.com",
                },
            }
        },
        parent={"product_link": "https://www.google.com/search?ibp=oshop&q=levi"},
        limit=1,
    )

    assert len(results) == 1
    assert results[0].url == "https://www.levi.com/p/04511.html"


@pytest.mark.component
def test_product_intelligence_parses_serpapi_immersive_when_about_payload_is_not_a_dict() -> (
    None
):
    results = parse_serpapi_immersive_results(
        {
            "product_results": {
                "title": "Levi's 511 Slim Fit Jeans",
                "product_id": "immersive-product-id",
                "about_the_product": "unexpected",
                "stores": [
                    {
                        "name": "Levi's",
                        "title": "Levi's 511 Slim Fit Jeans",
                        "link": "https://www.levi.com/p/04511.html",
                    }
                ],
            }
        },
        parent={"product_link": "https://www.google.com/search?ibp=oshop&q=levi"},
        limit=5,
    )

    assert len(results) == 1
    assert results[0].payload["raw"]["product"]["description"] == ""
