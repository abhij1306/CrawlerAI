"""test_sitemap_resolver cases split by public behavior."""

from __future__ import annotations

from tests.component.sitemap_resolver_test_support import (
    SITEMAP_NS,
    _FakeClient,
    _SequencedFakeClient,
    _normalize_sitemap_url,
    _valid_target,
    _xml_response,
    pytest,
    resolve_category_urls_from_sitemap,
    resolve_category_urls_from_sitemap_result,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "https://example.com/sitemap.xml"),
        ("https://example.com", "https://example.com/sitemap.xml"),
        ("https://example.com/custom.xml", "https://example.com/custom.xml"),
    ],
)
@pytest.mark.component
def test_normalize_sitemap_url(raw: str, expected: str) -> None:
    assert _normalize_sitemap_url(raw) == expected


@pytest.mark.component
def test_normalize_sitemap_url_rejects_empty_domain() -> None:
    with pytest.raises(ValueError, match="empty domain"):
        _normalize_sitemap_url(" ")


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_sitemap_index_filters_final_urls_not_child_sitemaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    child_url = "https://example.com/sitemap_pages_1.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<sitemapindex xmlns="{SITEMAP_NS}">
                  <sitemap><loc>https://example.com/sitemap_products_1.xml</loc></sitemap>
                  <sitemap><loc>{child_url}</loc></sitemap>
                  <sitemap><loc>https://example.com/sitemap_pages_2.xml</loc></sitemap>
                </sitemapindex>""",
            ),
            "https://example.com/sitemap_products_1.xml": _xml_response(
                "https://example.com/sitemap_products_1.xml",
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/products/p</loc></url>
                </urlset>""",
            ),
            child_url: _xml_response(
                child_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/a</loc></url>
                  <url><loc>https://example.com/collections/b</loc></url>
                </urlset>""",
            ),
            "https://example.com/sitemap_pages_2.xml": _xml_response(
                "https://example.com/sitemap_pages_2.xml",
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/c</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    urls = await resolve_category_urls_from_sitemap("example.com", "collections", 2)

    assert urls == [
        "https://example.com/collections/a",
        "https://example.com/collections/b",
    ]
    assert fake_client.requested_urls == [
        root_url,
        "https://example.com/sitemap_products_1.xml",
        child_url,
        "https://example.com/sitemap_pages_2.xml",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_sitemap_retries_transient_root_fetch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _SequencedFakeClient(
        {
            root_url: [
                _xml_response(root_url, "busy", 503),
                _xml_response(
                    root_url,
                    f"""<urlset xmlns="{SITEMAP_NS}">
                      <url><loc>https://example.com/collections/a</loc></url>
                    </urlset>""",
                ),
            ],
        }
    )

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )
    monkeypatch.setattr("app.crawl.sitemap_resolver.asyncio.sleep", _no_sleep)

    urls = await resolve_category_urls_from_sitemap("example.com", "collections", 500)

    assert urls == ["https://example.com/collections/a"]
    assert fake_client.requested_urls == [root_url, root_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_sitemap_index_skips_failed_child_sitemaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    failed_child_url = "https://example.com/sitemap_agentic_discovery.xml"
    collections_child_url = "https://example.com/sitemap_collections_1.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<sitemapindex xmlns="{SITEMAP_NS}">
                  <sitemap><loc>{failed_child_url}</loc></sitemap>
                  <sitemap><loc>{collections_child_url}</loc></sitemap>
                </sitemapindex>""",
            ),
            failed_child_url: _xml_response(failed_child_url, "busy", 503),
            collections_child_url: _xml_response(
                collections_child_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/a</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.asyncio.sleep",
        _no_sleep,
    )

    urls = await resolve_category_urls_from_sitemap("example.com", "collections", 500)

    assert urls == ["https://example.com/collections/a"]
    assert fake_client.requested_urls == [
        root_url,
        failed_child_url,
        failed_child_url,
        failed_child_url,
        collections_child_url,
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_direct_urlset_filters_urls_and_clamps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/a</loc></url>
                  <url><loc>https://example.com/products/p</loc></url>
                  <url><loc>https://example.com/collections/b</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    urls = await resolve_category_urls_from_sitemap("example.com", "collections", 1)

    assert urls == ["https://example.com/collections/a"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_raises_when_no_final_urls_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    child_url = "https://example.com/sitemap_products_1.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<sitemapindex xmlns="{SITEMAP_NS}">
                  <sitemap><loc>{child_url}</loc></sitemap>
                </sitemapindex>""",
            ),
            child_url: _xml_response(
                child_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/products/p</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    with pytest.raises(ValueError, match="No URLs matched filter"):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_default_does_not_filter_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/pages/a</loc></url>
                  <url><loc>https://example.com/products/p</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    urls = await resolve_category_urls_from_sitemap("example.com")

    assert urls == [
        "https://example.com/pages/a",
        "https://example.com/products/p",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_category_only_filters_non_category_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/women</loc></url>
                  <url><loc>https://example.com/products/shoe-123</loc></url>
                  <url><loc>https://example.com/pages/about</loc></url>
                  <url><loc>https://example.com/shop/sale</loc></url>
                  <url><loc>https://example.com/collections/athletes</loc></url>
                  <url><loc>https://example.com/collections/gift-registry</loc></url>
                  <url><loc>https://example.com/collections/mobile-app</loc></url>
                  <url><loc>https://example.com/collections/store-directory</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    urls = await resolve_category_urls_from_sitemap(
        "example.com",
        category_only=True,
    )

    assert urls == [
        "https://example.com/collections/women",
        "https://example.com/shop/sale",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_builds_nav_tree_from_sitemap_category_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/women/dresses</loc></url>
                  <url><loc>https://example.com/collections/men/shirts</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    result = await resolve_category_urls_from_sitemap_result(
        "example.com",
        category_only=True,
    )

    assert result.nav_tree == [
        {
            "label": "Collections",
            "children": [
                {
                    "label": "Women",
                    "children": [
                        {
                            "label": "Dresses",
                            "url": "https://example.com/collections/women/dresses",
                            "children": [],
                        }
                    ],
                },
                {
                    "label": "Men",
                    "children": [
                        {
                            "label": "Shirts",
                            "url": "https://example.com/collections/men/shirts",
                            "children": [],
                        }
                    ],
                },
            ],
        }
    ]
