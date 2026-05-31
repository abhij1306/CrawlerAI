from __future__ import annotations

import httpx
import pytest

from app.services.crawl import sitemap_resolver
from app.services.crawl.sitemap_resolver import (
    _normalize_sitemap_url,
    resolve_category_urls_from_sitemap,
    resolve_category_urls_from_sitemap_result,
)
from app.services.url_safety import SecurityError, ValidatedTarget


SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


class _FakeClient:
    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        del headers
        self.requested_urls.append(url)
        return self._responses[url]


class _SequencedFakeClient:
    def __init__(self, responses: dict[str, list[httpx.Response]]) -> None:
        self._responses = {url: list(items) for url, items in responses.items()}
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _SequencedFakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, headers: dict[str, str]) -> httpx.Response:
        del headers
        self.requested_urls.append(url)
        responses = self._responses[url]
        if len(responses) == 1:
            return responses[0]
        return responses.pop(0)


def _xml_response(url: str, content: str, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=content.encode(),
        request=httpx.Request("GET", url),
    )


async def _valid_target(url: str) -> ValidatedTarget:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return ValidatedTarget(
        hostname=parsed.hostname or "example.com",
        scheme=parsed.scheme or "https",
        port=443,
        resolved_ips=("93.184.216.34",),
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )
    monkeypatch.setattr("app.services.crawl.sitemap_resolver.asyncio.sleep", _no_sleep)

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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    async def _no_sleep(_seconds: float) -> None:
        return None

    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.asyncio.sleep",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
        _valid_target,
    )

    urls = await resolve_category_urls_from_sitemap("example.com")

    assert urls == [
        "https://example.com/pages/a",
        "https://example.com/products/p",
    ]


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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.validate_public_target",
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
        "app.services.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: fake_client,
    )
    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.validate_public_target",
        _reject_private,
    )

    with pytest.raises(SecurityError):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)

