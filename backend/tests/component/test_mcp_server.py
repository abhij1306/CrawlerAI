from __future__ import annotations

import httpx
import pytest
from fastmcp import Client

from app.core.config.public_api import (
    PUBLIC_API_MCP_API_KEY_ENV,
    PUBLIC_API_MCP_HOST_ENV,
    PUBLIC_API_MCP_PORT_ENV,
    PUBLIC_API_MCP_TRANSPORT_ENV,
)
from app.mcp_server.client import PublicApiClient
from app.mcp_server.config import runtime_config
from app.mcp_server import server as server_module
from app.mcp_server.server import build_server
from app.mcp_server.tools import check_domain, extract_product, list_capabilities


@pytest.mark.asyncio
@pytest.mark.component
async def test_mcp_server_registers_only_supported_tools() -> None:
    server = build_server()

    tools = await server.list_tools()
    assert [tool.name for tool in tools] == [
        "extract_product",
        "check_domain",
        "list_capabilities",
    ]

    async with Client(server) as client:
        result = await client.call_tool("list_capabilities", {})

    assert result.data == {
        "status": "ok",
        "data": {
            "version": "v1",
            "surfaces": ["ecommerce"],
            "tools": [
                "extract_product",
                "check_domain",
                "list_capabilities",
            ],
            "deferred": ["extract_batch"],
            "deployment": "self-hosted",
            "mcp": {
                "default_transport": "stdio",
                "network_scope": "loopback-only",
                "hosted": False,
            },
        },
    }


@pytest.mark.component
@pytest.mark.parametrize(
    "host",
    [
        "0.0.0.0",  # noqa: S104  # nosec B104 - fail-closed validation fixture
        "localhost",
        "mcp.example.com",
    ],
)
def test_non_loopback_network_mcp_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    host: str,
) -> None:
    monkeypatch.setenv(PUBLIC_API_MCP_API_KEY_ENV, "principal-a")
    monkeypatch.setenv(PUBLIC_API_MCP_TRANSPORT_ENV, "sse")
    monkeypatch.setenv(PUBLIC_API_MCP_HOST_ENV, host)

    with pytest.raises(RuntimeError, match="literal loopback"):
        runtime_config()


@pytest.mark.component
def test_loopback_network_mcp_is_explicitly_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PUBLIC_API_MCP_API_KEY_ENV, "principal-a")
    monkeypatch.setenv(PUBLIC_API_MCP_TRANSPORT_ENV, "sse")
    monkeypatch.setenv(PUBLIC_API_MCP_HOST_ENV, "127.0.0.1")
    monkeypatch.delenv(PUBLIC_API_MCP_PORT_ENV, raising=False)

    config = runtime_config()

    assert config.transport == "sse"
    assert config.host == "127.0.0.1"
    assert config.port == 8001


@pytest.mark.component
def test_network_mcp_rejects_invalid_port(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(PUBLIC_API_MCP_API_KEY_ENV, "principal-a")
    monkeypatch.setenv(PUBLIC_API_MCP_TRANSPORT_ENV, "sse")
    monkeypatch.setenv(PUBLIC_API_MCP_HOST_ENV, "127.0.0.1")
    monkeypatch.setenv(PUBLIC_API_MCP_PORT_ENV, "invalid")

    with pytest.raises(RuntimeError, match="PORT must be an integer"):
        runtime_config()


@pytest.mark.component
def test_mcp_defaults_to_one_local_stdio_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    class _Server:
        def run(self, *args, **kwargs) -> None:
            calls.append((args, kwargs))

    monkeypatch.setenv(PUBLIC_API_MCP_API_KEY_ENV, "principal-a")
    monkeypatch.delenv(PUBLIC_API_MCP_TRANSPORT_ENV, raising=False)
    monkeypatch.setattr(server_module, "build_server", lambda _client: _Server())

    server_module.main()

    assert calls == [((), {"transport": "stdio"})]


@pytest.mark.asyncio
@pytest.mark.component
async def test_separate_stdio_servers_keep_distinct_api_principals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_keys: list[str] = []

    async def _extract(client, **_kwargs):
        observed_keys.append(client.api_key)
        return {"status": "ok"}

    monkeypatch.setattr(server_module, "_extract_product", _extract)
    first = build_server(
        PublicApiClient(api_key="principal-a", base_url="https://api.test")
    )
    second = build_server(
        PublicApiClient(api_key="principal-b", base_url="https://api.test")
    )

    async with Client(first) as client:
        await client.call_tool("extract_product", {"url": "https://example.com/a"})
    async with Client(second) as client:
        await client.call_tool("extract_product", {"url": "https://example.com/b"})

    assert observed_keys == ["principal-a", "principal-b"]


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
            calls.append(
                {
                    "method": method,
                    "url": url,
                    "headers": headers,
                    "json": json,
                    "params": params,
                }
            )
            return httpx.Response(200, json={"status": "ok", "data": {"ok": True}})

    monkeypatch.setattr("app.mcp_server.client.httpx.AsyncClient", _Client)
    client = PublicApiClient(api_key="secret", base_url="https://api.test/api/v1")

    product = await extract_product(
        client, url="https://example.com/p/1", fields=["price"], use_cache=True
    )
    domain = await check_domain(client, domain="example.com")
    caps = list_capabilities()

    assert product["status"] == "ok"
    assert domain["status"] == "ok"
    assert "extract_product" in caps["data"]["tools"]
    assert "alert_product" not in caps["data"]["tools"]
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
async def test_mcp_client_returns_structured_api_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
                json={
                    "status": "error",
                    "error": {"code": "BROWSER_REQUIRED", "message": "Browser needed"},
                },
            )

    monkeypatch.setattr("app.mcp_server.client.httpx.AsyncClient", _Client)

    result = await PublicApiClient(
        api_key="secret", base_url="https://api.test/api/v1"
    ).request("POST", "/extract")

    assert result == {
        "status": "error",
        "error": {"code": "BROWSER_REQUIRED", "message": "Browser needed"},
    }
