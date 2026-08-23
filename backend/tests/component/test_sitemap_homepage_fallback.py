"""test_sitemap_resolver cases split by public behavior."""

from __future__ import annotations

from tests.component.sitemap_resolver_test_support import (
    SITEMAP_NS,
    SecurityError,
    ValidatedTarget,
    _FakeClient,
    _valid_target,
    _xml_response,
    httpx,
    pytest,
    resolve_category_urls_from_sitemap,
    resolve_category_urls_from_sitemap_result,
    sitemap_resolver,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_homepage_fallback_nav_tree_prefers_anchor_text_labels(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    homepage_url = "https://example.com"
    fake_client = _FakeClient(
        {
            sitemap_url: _xml_response(sitemap_url, "missing", 404),
            homepage_url: httpx.Response(
                200,
                text="""
                <html><body>
                  <nav>
                    <a href="/collections/women/dresses">Women's Dresses</a>
                  </nav>
                </body></html>
                """,
                request=httpx.Request("GET", homepage_url),
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
        allow_homepage_fallback=True,
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
                            "label": "Women's Dresses",
                            "url": "https://example.com/collections/women/dresses",
                            "children": [],
                        }
                    ],
                }
            ],
        }
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_category_only_falls_back_when_sitemap_has_account_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sitemap_url = "https://www.tommy.com/sitemap.xml"
    homepage_url = "https://www.tommy.com"
    fake_client = _FakeClient(
        {
            sitemap_url: _xml_response(
                sitemap_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://www.tommy.com/myorders</loc></url>
                  <url><loc>https://www.tommy.com/store-locator</loc></url>
                  <url><loc>https://www.tommy.com/apps</loc></url>
                </urlset>""",
            ),
            homepage_url: httpx.Response(
                200,
                text="""
                <html><body>
                  <nav>
                    <a href="/women">Women</a>
                    <a href="/men">Men</a>
                    <a href="/myorders">Orders</a>
                    <a href="/store-locator">Stores</a>
                    <a href="/apps">Apps</a>
                  </nav>
                </body></html>
                """,
                # Different request host is intentional: covers relative links after redirects.
                request=httpx.Request("GET", "https://tommyhilfiger.nnnow.com/"),
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
        "https://www.tommy.com",
        allow_homepage_fallback=True,
        category_only=True,
    )

    assert result.source == "homepage"
    assert result.urls == [
        "https://tommyhilfiger.nnnow.com/women",
        "https://tommyhilfiger.nnnow.com/men",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_homepage_category_only_rejects_link_without_category_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    homepage_url = "https://example.com"
    fake_client = _FakeClient(
        {
            sitemap_url: _xml_response(
                sitemap_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/privacy</loc></url>
                </urlset>""",
            ),
            homepage_url: httpx.Response(
                200,
                text='<html><body><nav><a href="/lookbook">Explore</a></nav></body></html>',
                request=httpx.Request("GET", homepage_url),
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

    with pytest.raises(ValueError, match="No URLs found"):
        await resolve_category_urls_from_sitemap(
            "example.com",
            allow_homepage_fallback=True,
            category_only=True,
        )

    assert homepage_url in fake_client.requested_urls


@pytest.mark.asyncio
@pytest.mark.component
async def test_homepage_category_only_keeps_anchor_category_without_auto_listing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    homepage_url = "https://example.com"
    fake_client = _FakeClient(
        {
            sitemap_url: _xml_response(sitemap_url, "missing", 404),
            homepage_url: httpx.Response(
                200,
                text='<html><body><nav><a href="/women">Women</a></nav></body></html>',
                request=httpx.Request("GET", homepage_url),
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
        allow_homepage_fallback=True,
        category_only=True,
    )

    assert urls == ["https://example.com/women"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_empty_urlset_without_filter_reports_no_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<urlset xmlns="{SITEMAP_NS}"></urlset>""",
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

    with pytest.raises(ValueError, match="No URLs found in sitemap"):
        await resolve_category_urls_from_sitemap("example.com", "", 500)


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_raises_for_invalid_xml(monkeypatch: pytest.MonkeyPatch) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient({root_url: _xml_response(root_url, "<not-closed")})
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    with pytest.raises(ValueError, match="Invalid XML in sitemap"):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_raises_for_non_200(monkeypatch: pytest.MonkeyPatch) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient({root_url: _xml_response(root_url, "missing", 404)})
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    with pytest.raises(ValueError, match="returned HTTP 404"):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_rejects_unsafe_discovered_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    fake_client = _FakeClient(
        {
            root_url: _xml_response(
                root_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>http://127.0.0.1/collections/a</loc></url>
                </urlset>""",
            ),
        }
    )

    async def _reject_loopback(url: str) -> ValidatedTarget:
        if "127.0.0.1" in url:
            raise SecurityError("Target host resolves to a non-public IP address")
        return await _valid_target(url)

    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _reject_loopback,
    )

    with pytest.raises(SecurityError):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_falls_back_to_homepage_links_when_sitemap_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_sitemap_url = "https://example.com/sitemap.xml"
    locale_sitemap_url = "https://example.com/en/sitemap.xml"
    homepage_url = "https://example.com/en"
    fake_client = _FakeClient(
        {
            root_sitemap_url: _xml_response(root_sitemap_url, "missing", 404),
            locale_sitemap_url: _xml_response(locale_sitemap_url, "missing", 404),
            homepage_url: httpx.Response(
                200,
                text="""
                <html><body>
                  <nav>
                    <a href="/en/women">Women</a>
                    <a href="/en/men">Men</a>
                  </nav>
                  <main>
                    <a href="/en/products/cotton-tee-123">Cotton Tee</a>
                  </main>
                  <a href="/en/cart">Cart</a>
                  <a href="https://external.example.com/elsewhere">External</a>
                </body></html>
                """,
                request=httpx.Request("GET", homepage_url),
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
        "https://example.com/en",
        allow_homepage_fallback=True,
    )

    assert result.source == "homepage"
    assert result.urls == [
        "https://example.com/en/women",
        "https://example.com/en/men",
        "https://example.com/en/products/cotton-tee-123",
    ]
    assert fake_client.requested_urls == [
        root_sitemap_url,
        locale_sitemap_url,
        homepage_url,
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_homepage_fallback_does_not_hard_filter_by_keyword(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sitemap_url = "https://example.com/sitemap.xml"
    homepage_url = "https://example.com"
    fake_client = _FakeClient(
        {
            sitemap_url: _xml_response(sitemap_url, "missing", 404),
            homepage_url: httpx.Response(
                200,
                text="""
                <html><body>
                  <nav>
                    <a href="/women">Women</a>
                    <a href="/shop/sale">Sale</a>
                  </nav>
                  <a href="/products/widget-123">Widget</a>
                </body></html>
                """,
                request=httpx.Request("GET", homepage_url),
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
        "collections",
        5,
        allow_homepage_fallback=True,
    )

    assert urls == [
        "https://example.com/shop/sale",
        "https://example.com/women",
        "https://example.com/products/widget-123",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_homepage_fallback_caps_anchor_scan_and_validations(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    validated: list[str] = []

    async def _record_target(url: str) -> ValidatedTarget:
        validated.append(url)
        return await _valid_target(url)

    monkeypatch.setattr(sitemap_resolver, "SITEMAP_HOMEPAGE_FALLBACK_MAX_ANCHORS", 3)
    monkeypatch.setattr(
        sitemap_resolver,
        "SITEMAP_HOMEPAGE_FALLBACK_MAX_VALIDATIONS",
        2,
    )
    monkeypatch.setattr(sitemap_resolver, "validate_public_target", _record_target)

    urls = await sitemap_resolver._extract_homepage_candidate_urls(
        homepage_url="https://example.com",
        html="""
        <nav>
          <a href="/women">Women</a>
          <a href="/men">Men</a>
          <a href="/kids">Kids</a>
          <a href="/sale">Sale</a>
        </nav>
        """,
        keyword="",
        limit=10,
    )

    assert urls == ["https://example.com/women", "https://example.com/men"]
    assert validated == ["https://example.com/women", "https://example.com/men"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_homepage_fallback_requires_exact_same_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    urls = await sitemap_resolver._extract_homepage_candidate_urls(
        homepage_url="https://example.com",
        html="""
        <nav>
          <a href="http://example.com/women">Wrong Scheme</a>
          <a href="https://shop.example.com/men">Subdomain</a>
          <a href="/collections/all">All</a>
        </nav>
        """,
        keyword="",
        limit=10,
    )

    assert urls == ["https://example.com/collections/all"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolver_rejects_private_redirect_chain_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    private_url = "http://169.254.169.254/latest/meta-data"
    fake_client = _FakeClient(
        {
            root_url: httpx.Response(
                200,
                content=f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/a</loc></url>
                </urlset>""".encode(),
                request=httpx.Request("GET", root_url),
                history=[
                    httpx.Response(
                        302,
                        request=httpx.Request("GET", private_url),
                    )
                ],
            )
        }
    )

    async def _reject_private(url: str) -> ValidatedTarget:
        if "169.254.169.254" in url:
            raise SecurityError("Target host resolves to a non-public IP address")
        return await _valid_target(url)

    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.validate_public_target",
        _reject_private,
    )

    with pytest.raises(SecurityError):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)
