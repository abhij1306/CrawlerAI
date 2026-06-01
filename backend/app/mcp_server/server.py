from __future__ import annotations

import os
from typing import Any

from app.mcp_server.client import PublicApiClient
from app.mcp_server.config import api_base_url, api_key, bind_host
from app.mcp_server.tools import check_domain as _check_domain
from app.mcp_server.tools import extract_product as _extract_product
from app.mcp_server.tools import list_capabilities as _list_capabilities


def build_server():
    from fastmcp import FastMCP

    mcp = FastMCP("crawlerai")
    client = PublicApiClient(api_key=api_key(), base_url=api_base_url())

    @mcp.tool
    async def extract_product(
        url: str,
        fields: list[str] | None = None,
        use_cache: bool = False,
    ) -> dict[str, Any]:
        return await _extract_product(
            client,
            url=url,
            fields=fields,
            use_cache=use_cache,
        )

    @mcp.tool
    async def check_domain(domain: str) -> dict[str, Any]:
        return await _check_domain(client, domain=domain)

    @mcp.tool
    async def list_capabilities() -> dict[str, Any]:
        return await _list_capabilities()

    return mcp


def main() -> None:
    server = build_server()
    port = int(os.environ.get("PORT", "8001"))
    server.run(transport="sse", host=bind_host(), port=port)


if __name__ == "__main__":
    main()
