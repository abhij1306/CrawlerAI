from __future__ import annotations

import httpx

import pytest

from app.crawl import sitemap_resolver

from app.crawl.sitemap_resolver import (
    _normalize_sitemap_url,
    resolve_category_urls_from_sitemap,
    resolve_category_urls_from_sitemap_result,
)

from app.core.url_safety import SecurityError, ValidatedTarget

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


__all__ = [
    "SITEMAP_NS",
    "SecurityError",
    "ValidatedTarget",
    "_FakeClient",
    "_SequencedFakeClient",
    "_normalize_sitemap_url",
    "_valid_target",
    "_xml_response",
    "httpx",
    "pytest",
    "resolve_category_urls_from_sitemap",
    "resolve_category_urls_from_sitemap_result",
    "sitemap_resolver",
]
