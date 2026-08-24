from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core import url_safety
from app.crawl import robots_policy


class FakeTextResponse:
    def __init__(
        self, status_code: int, text: str = "", headers: dict | None = None
    ) -> None:
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeAsyncClient:
    def __init__(self, response_factory) -> None:
        self._response_factory = response_factory

    async def __aenter__(self) -> "FakeAsyncClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url: str, **kwargs):
        del kwargs
        return await self._response_factory(url)


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    response_factory,
) -> None:
    monkeypatch.setattr(
        robots_policy.httpx,
        "AsyncClient",
        lambda **kwargs: FakeAsyncClient(response_factory),
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_check_url_crawlability_allows_url_when_robots_allows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> FakeTextResponse:
        assert url == "https://example.com/robots.txt"
        return FakeTextResponse(200, "User-agent: *\nDisallow:")

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_ALLOWED
    assert result.robots_url == "https://example.com/robots.txt"


@pytest.mark.asyncio
@pytest.mark.component
async def test_check_url_crawlability_blocks_url_when_robots_disallows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> FakeTextResponse:
        del url
        return FakeTextResponse(200, "User-agent: *\nDisallow: /private")

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability(
        "https://example.com/private/page"
    )

    assert result.allowed is False
    assert result.outcome == robots_policy.ROBOTS_DISALLOWED


@pytest.mark.asyncio
@pytest.mark.component
async def test_check_url_crawlability_allows_missing_robots(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> FakeTextResponse:
        del url
        return FakeTextResponse(404)

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_MISSING


@pytest.mark.asyncio
@pytest.mark.component
async def test_check_url_crawlability_allows_when_robots_fetch_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> FakeTextResponse:
        del url
        request = httpx.Request("GET", "https://example.com/robots.txt")
        raise httpx.ReadTimeout("timeout", request=request)

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert result.outcome == robots_policy.ROBOTS_FETCH_FAILURE
    assert result.error


@pytest.mark.asyncio
@pytest.mark.component
async def test_check_url_crawlability_treats_forbidden_robots_as_disallow_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()

    async def _response(url: str) -> FakeTextResponse:
        del url
        return FakeTextResponse(403)

    _patch_client(monkeypatch, _response)

    result = await robots_policy.check_url_crawlability("https://example.com/private")

    assert result.allowed is False
    assert result.outcome == robots_policy.ROBOTS_DISALLOWED


@pytest.mark.asyncio
@pytest.mark.component
async def test_check_url_crawlability_reuses_inflight_fetch_for_same_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()
    calls = 0

    async def _response(url: str) -> FakeTextResponse:
        nonlocal calls
        del url
        calls += 1
        await asyncio.sleep(0.05)
        return FakeTextResponse(200, "User-agent: *\nDisallow:")

    _patch_client(monkeypatch, _response)

    results = await asyncio.gather(
        robots_policy.check_url_crawlability("https://example.com/public"),
        robots_policy.check_url_crawlability("https://example.com/public?page=2"),
    )

    assert calls == 1
    assert all(result.allowed for result in results)


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_robots_snapshot_reuses_shared_client_across_domains(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()
    constructions = 0

    class _SpyClient:
        def __init__(self) -> None:
            nonlocal constructions
            constructions += 1

        async def get(self, url: str, **kwargs):
            del url, kwargs
            return FakeTextResponse(200, "User-agent: *\nDisallow:")

    monkeypatch.setattr(
        robots_policy.httpx, "AsyncClient", lambda **kwargs: _SpyClient()
    )

    first = await robots_policy.check_url_crawlability("https://one.example.com/a")
    second = await robots_policy.check_url_crawlability("https://two.example.com/b")

    assert first.allowed and second.allowed
    # 2.16: one process-wide client serves both domains.
    assert constructions == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_robots_snapshot_validates_each_redirect_hop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await robots_policy.reset_robots_policy_cache()
    requested: list[str] = []

    class _RedirectClient:
        async def get(self, url: str, **kwargs):
            del kwargs
            requested.append(url)
            if url == "https://example.com/robots.txt":
                return FakeTextResponse(
                    301, headers={"location": "https://cdn.example.com/robots.txt"}
                )
            return FakeTextResponse(200, "User-agent: *\nDisallow:")

    monkeypatch.setattr(
        robots_policy.httpx, "AsyncClient", lambda **kwargs: _RedirectClient()
    )
    validated: list[str] = []
    real_validate = url_safety.validate_public_target

    async def _spy_validate(url: str) -> None:
        validated.append(url)
        await real_validate(url)

    monkeypatch.setattr(url_safety, "validate_public_target", _spy_validate)

    result = await robots_policy.check_url_crawlability("https://example.com/public")

    assert result.allowed is True
    assert requested == [
        "https://example.com/robots.txt",
        "https://cdn.example.com/robots.txt",
    ]
    assert validated == requested
