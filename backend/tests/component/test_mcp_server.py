from __future__ import annotations

import httpx
import pytest

from app.mcp_server.client import PublicApiClient
from app.mcp_server.tools import check_domain, extract_product, list_capabilities


@pytest.mark.asyncio
@pytest.mark.component
async def test_mcp_tools_call_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[dict[str, object]] = []

    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, *, headers, json=None, params=None):
            calls.append({"method": method, "url": url, "headers": headers, "json": json, "params": params})
            return httpx.Response(200, json={"status": "ok", "data": {"ok": True}})

    monkeypatch.setattr("app.mcp_server.client.httpx.AsyncClient", _Client)
    client = PublicApiClient(api_key="secret", base_url="https://api.test/api/v1")

    product = await extract_product(client, url="https://example.com/p/1", fields=["price"], use_cache=True)
    domain = await check_domain(client, domain="example.com")
    caps = await list_capabilities()

    assert product["status"] == "ok"
    assert domain["status"] == "ok"
    assert "extract_product" in caps["data"]["tools"]
    assert "alert_product" in caps["data"]["tools"]
    assert "watches" not in caps["data"]["deferred"]
    assert calls[0] == {
        "method": "POST",
        "url": "https://api.test/api/v1/extract",
        "headers": {"Authorization": "Bearer secret"},
        "json": {
            "url": "https://example.com/p/1",
            "surface": "ecommerce",
            "fields": ["price"],
            "options": {"use_cache": True},
        },
        "params": None,
    }
    assert calls[1]["url"] == "https://api.test/api/v1/domains/example.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_mcp_client_returns_structured_api_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Client:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def request(self, method, url, *, headers, json=None, params=None):
            return httpx.Response(
                422,
                json={"status": "error", "error": {"code": "BROWSER_REQUIRED", "message": "Browser needed"}},
            )

    monkeypatch.setattr("app.mcp_server.client.httpx.AsyncClient", _Client)

    result = await PublicApiClient(api_key="secret", base_url="https://api.test/api/v1").request("POST", "/extract")

    assert result == {"status": "error", "error": {"code": "BROWSER_REQUIRED", "message": "Browser needed"}}
