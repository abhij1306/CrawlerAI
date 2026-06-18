from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.crawl.site_link_discovery import discover_rendered_category_links
from app.services.crawl.sitemap_resolver import (
    SitemapResolutionResult,
    resolve_category_urls_with_site_links,
)
from app.services.url_safety import ValidatedTarget


@dataclass(slots=True)
class _FetchResult:
    final_url: str
    html: str
    status_code: int = 200
    method: str = "browser"
    blocked: bool = False


async def _valid_target(url: str) -> ValidatedTarget:
    from urllib.parse import urlparse

    parsed = urlparse(url)
    return ValidatedTarget(
        hostname=parsed.hostname or "example.com",
        scheme=parsed.scheme or "https",
        port=443,
        resolved_ips=("93.184.216.34",),
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_rendered_discovery_harvests_category_links_and_rejects_utility(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    async def _fake_fetch(url: str, **kwargs: object) -> _FetchResult:
        calls.append(url)
        assert kwargs["prefer_browser"] is True
        return _FetchResult(
            final_url=url,
            html="""
            <html><body>
              <nav>
                <a href="/en-us/women/bags/">Bags</a>
                <a href="/en-us/client-service">Client Service</a>
                <a href="/en-us/stores">Stores</a>
                <a href="https://other.example/women">Women</a>
              </nav>
            </body></html>
            """,
        )

    monkeypatch.setattr(
        "app.services.crawl.site_link_discovery.validate_public_target",
        _valid_target,
    )

    result = await discover_rendered_category_links(
        "https://example.com",
        limit=5,
        max_depth=0,
        max_pages=2,
        fetch_page_impl=_fake_fetch,
    )

    assert result.urls == ["https://example.com/en-us/women/bags/"]
    assert result.source == "rendered_site_links"
    assert calls == ["https://example.com"]
    assert result.diagnostics["rejected"]["utility_or_asset"] == 2
    assert result.diagnostics["rejected"]["off_origin"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_rendered_discovery_follows_nested_category_links(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = {
        "https://example.com": """
            <html><body><nav>
              <a href="/women">Women</a>
            </nav></body></html>
        """,
        "https://example.com/women": """
            <html><body><nav>
              <a href="/women/shoes">Shoes</a>
              <a href="/experience">Experience</a>
            </nav></body></html>
        """,
        "https://example.com/women/shoes": "<html><body></body></html>",
    }
    calls: list[str] = []

    async def _fake_fetch(url: str, **_kwargs: object) -> _FetchResult:
        calls.append(url)
        return _FetchResult(final_url=url, html=pages[url])

    monkeypatch.setattr(
        "app.services.crawl.site_link_discovery.validate_public_target",
        _valid_target,
    )

    result = await discover_rendered_category_links(
        "https://example.com",
        limit=5,
        max_depth=2,
        max_pages=3,
        fetch_page_impl=_fake_fetch,
    )

    assert "https://example.com/women" in result.urls
    assert "https://example.com/women/shoes" in result.urls
    assert "https://example.com/experience" not in result.urls
    assert calls == [
        "https://example.com",
        "https://example.com/women",
        "https://example.com/women/shoes",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_rendered_discovery_validation_keeps_listing_signal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_fetch(url: str, **_kwargs: object) -> _FetchResult:
        if url == "https://example.com":
            return _FetchResult(
                final_url=url,
                html="<nav><a href='/collections/bags'>Bags</a></nav>",
            )
        return _FetchResult(
            final_url=url,
            html="""
            <main>
              <a class="product-card" href="/products/1">$10 Bag</a>
              <a class="product-card" href="/products/2">$20 Bag</a>
              <a class="product-card" href="/products/3">$30 Bag</a>
              <a class="product-card" href="/products/4">$40 Bag</a>
            </main>
            """,
        )

    monkeypatch.setattr(
        "app.services.crawl.site_link_discovery.validate_public_target",
        _valid_target,
    )

    result = await discover_rendered_category_links(
        "https://example.com",
        limit=5,
        max_depth=1,
        max_pages=2,
        validate_candidates=True,
        fetch_page_impl=_fake_fetch,
    )

    assert result.urls == ["https://example.com/collections/bags"]
    assert result.diagnostics["validation_checked"] == 1
    assert result.diagnostics["validation_kept"] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_resolver_uses_rendered_fallback_after_static_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_static_result(**_kwargs: object) -> SitemapResolutionResult:
        raise ValueError("Sitemap fetch failed")

    async def _fake_rendered(
        seed_url: str,
        **_kwargs: object,
    ) -> SitemapResolutionResult:
        assert seed_url == "https://example.com"
        return SitemapResolutionResult(
            urls=["https://example.com/collections/bags"],
            source="rendered_site_links",
        )

    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.resolve_category_urls_from_sitemap_result",
        _fake_static_result,
    )
    monkeypatch.setattr(
        "app.services.crawl.site_link_discovery.discover_rendered_category_links",
        _fake_rendered,
    )

    result = await resolve_category_urls_with_site_links(
        "https://example.com",
        max_urls=5,
        category_only=True,
    )

    assert result.urls == ["https://example.com/collections/bags"]
    assert result.source == "rendered_site_links"
    assert result.diagnostics["static_error"]["error_type"] == "ValueError"


@pytest.mark.asyncio
@pytest.mark.component
async def test_shared_resolver_keeps_strong_static_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rendered_called = False

    async def _fake_static_result(**_kwargs: object) -> SitemapResolutionResult:
        return SitemapResolutionResult(
            urls=[
                "https://example.com/collections/a",
                "https://example.com/collections/b",
                "https://example.com/collections/c",
                "https://example.com/collections/d",
                "https://example.com/collections/e",
            ],
            source="sitemap",
        )

    async def _fake_rendered(
        seed_url: str,
        **_kwargs: object,
    ) -> SitemapResolutionResult:
        nonlocal rendered_called
        rendered_called = True
        return SitemapResolutionResult(urls=[seed_url], source="rendered_site_links")

    monkeypatch.setattr(
        "app.services.crawl.sitemap_resolver.resolve_category_urls_from_sitemap_result",
        _fake_static_result,
    )
    monkeypatch.setattr(
        "app.services.crawl.site_link_discovery.discover_rendered_category_links",
        _fake_rendered,
    )

    result = await resolve_category_urls_with_site_links("https://example.com")

    assert result.source == "sitemap"
    assert rendered_called is False
