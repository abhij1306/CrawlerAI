from __future__ import annotations

import httpx
import pytest

from app.crawl import robots_policy
from app.crawl.sitemap_resolver import resolve_category_urls_from_sitemap
from app.core.url_safety import SecurityError

SITEMAP_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


class _FakeAsyncClient:
    """httpx.AsyncClient stand-in recording every requested URL."""

    def __init__(self, responses: dict[str, httpx.Response]) -> None:
        self._responses = responses
        self.requested_urls: list[str] = []

    async def __aenter__(self) -> _FakeAsyncClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, **_kwargs: object) -> httpx.Response:
        self.requested_urls.append(url)
        return self._responses[url]


def _redirect(url: str, location: str) -> httpx.Response:
    return httpx.Response(
        302,
        headers={"location": location},
        request=httpx.Request("GET", url),
    )


def _ok(url: str, text: str) -> httpx.Response:
    return httpx.Response(200, text=text, request=httpx.Request("GET", url))


@pytest.mark.asyncio
@pytest.mark.component
async def test_robots_fetch_blocks_redirect_to_private_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()
    robots_url = "https://example.com/robots.txt"
    private_url = "http://169.254.169.254/latest/meta-data"
    client = _FakeAsyncClient({robots_url: _redirect(robots_url, private_url)})
    monkeypatch.setattr(
        robots_policy.httpx,
        "AsyncClient",
        lambda **kwargs: client,
    )

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    # A non-public redirect target is a robots fetch failure (fail open,
    # consistent with unreachable robots) and is never requested.
    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_FETCH_FAILURE
    assert result.error
    assert client.requested_urls == [robots_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_robots_fetch_follows_redirect_to_public_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()
    robots_url = "https://example.com/robots.txt"
    public_url = "https://cdn.example/robots.txt"
    client = _FakeAsyncClient(
        {
            robots_url: _redirect(robots_url, public_url),
            public_url: _ok(public_url, "User-agent: *\nDisallow: /private"),
        }
    )
    monkeypatch.setattr(
        robots_policy.httpx,
        "AsyncClient",
        lambda **kwargs: client,
    )

    allowed = await robots_policy.check_url_crawlability("https://example.com/public")
    disallowed = await robots_policy.check_url_crawlability(
        "https://example.com/private/page"
    )

    assert allowed.allowed is True
    assert allowed.outcome == robots_policy.ROBOTS_ALLOWED
    assert disallowed.allowed is False
    assert disallowed.outcome == robots_policy.ROBOTS_DISALLOWED
    assert client.requested_urls == [robots_url, public_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_sitemap_fetch_blocks_redirect_to_private_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    private_url = "http://169.254.169.254/latest/meta-data"
    client = _FakeAsyncClient({root_url: _redirect(root_url, private_url)})
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: client,
    )

    with pytest.raises(SecurityError):
        await resolve_category_urls_from_sitemap("example.com", "collections", 500)

    assert client.requested_urls == [root_url]


@pytest.mark.asyncio
@pytest.mark.component
async def test_sitemap_fetch_follows_redirect_to_public_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root_url = "https://example.com/sitemap.xml"
    real_url = "https://example.com/sitemap_real.xml"
    client = _FakeAsyncClient(
        {
            root_url: _redirect(root_url, real_url),
            real_url: _ok(
                real_url,
                f"""<urlset xmlns="{SITEMAP_NS}">
                  <url><loc>https://example.com/collections/a</loc></url>
                </urlset>""",
            ),
        }
    )
    monkeypatch.setattr(
        "app.crawl.sitemap_resolver.httpx.AsyncClient",
        lambda **kwargs: client,
    )

    urls = await resolve_category_urls_from_sitemap("example.com", "collections", 500)

    assert urls == ["https://example.com/collections/a"]
    assert client.requested_urls == [root_url, real_url]
