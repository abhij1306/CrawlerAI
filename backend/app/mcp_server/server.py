from __future__ import annotations

from typing import Any

from app.mcp_server.client import PublicApiClient
from app.mcp_server.config import api_base_url, api_key, runtime_config
from app.mcp_server.tools import check_domain as _check_domain
from app.mcp_server.tools import extract_product as _extract_product
from app.mcp_server.tools import list_capabilities as _list_capabilities


def build_server(client: PublicApiClient | None = None):
    from fastmcp import FastMCP  # type: ignore[import-untyped]

    mcp = FastMCP("crawlerai")
    api_client = client or PublicApiClient(api_key=api_key(), base_url=api_base_url())

    @mcp.tool
    async def extract_product(
        url: str,
        fields: list[str] | None = None,
        use_cache: bool = False,
    ) -> dict[str, Any]:
        return await _extract_product(
            api_client,
            url=url,
            fields=fields,
            use_cache=use_cache,
        )

    @mcp.tool
    async def check_domain(domain: str) -> dict[str, Any]:
        return await _check_domain(api_client, domain=domain)

    @mcp.tool
    def list_capabilities() -> dict[str, Any]:
        return _list_capabilities()

    return mcp


def main() -> None:
    config = runtime_config()
    server = build_server(
        PublicApiClient(api_key=config.api_key, base_url=config.api_base_url)
    )
    if config.transport == "stdio":
        server.run(transport="stdio")
        return
    server.run(transport="sse", host=config.host, port=config.port)


if __name__ == "__main__":
    main()
