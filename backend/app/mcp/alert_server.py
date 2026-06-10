from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from typing import Any

import httpx

from app.mcp_server.client import extract_api_error_from_payload
from app.services.config.monitor_settings import (
    MCP_API_BASE_URL_ENV,
    MCP_API_KEY_ENV,
    MCP_DEFAULT_API_BASE_URL,
)

logger = logging.getLogger(__name__)


class AlertMCPServer:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None) -> None:
        self.api_key = api_key or os.environ.get(MCP_API_KEY_ENV, "")
        self.base_url = (base_url or os.environ.get(MCP_API_BASE_URL_ENV, MCP_DEFAULT_API_BASE_URL)).rstrip("/")

    @staticmethod
    def tools() -> list[dict[str, Any]]:
        return [
            {
                "name": "alert_product",
                "description": "Register a price or availability alert on a product URL.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                        "condition": {"type": ["string", "null"]},
                        "webhook_url": {"type": ["string", "null"]},
                        "poll_interval_seconds": {"type": "integer", "default": 300},
                        "target_fields": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": ["price", "availability"],
                        },
                    },
                    "required": ["url"],
                },
            },
            {
                "name": "get_alert_status",
                "description": "Get status and latest values for an alert.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"alert_id": {"type": "string"}},
                    "required": ["alert_id"],
                },
            },
            {
                "name": "cancel_alert",
                "description": "Cancel and delete an alert.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"alert_id": {"type": "string"}},
                    "required": ["alert_id"],
                },
            },
            {
                "name": "list_alerts",
                "description": "List alerts for the configured API key.",
                "inputSchema": {
                    "type": "object",
                    "properties": {"status": {"type": ["string", "null"]}},
                },
            },
        ]

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "alert_product":
            return await self._request("POST", "/alerts", json_body=arguments)
        if name == "get_alert_status":
            return await self._request("GET", f"/alerts/{arguments['alert_id']}")
        if name == "cancel_alert":
            return await self._request("DELETE", f"/alerts/{arguments['alert_id']}")
        if name == "list_alerts":
            status = arguments.get("status")
            params = {"status": status} if status else None
            return await self._request("GET", "/alerts", params=params)
        raise ValueError(f"Unknown tool: {name}")

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            return _tool_error("API_KEY_MISSING", f"{MCP_API_KEY_ENV} is required")
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method,
                f"{self.base_url}{path}",
                headers=headers,
                json=json_body,
                params=params,
            )
        if response.status_code == 204:
            return {"status": "ok", "data": {"cancelled": True}}
        payload = response.json()
        if response.status_code >= 400:
            api_error = extract_api_error_from_payload(payload, response.text)
            if api_error is not None:
                code, message = api_error
                return _tool_error(code, message)
            return _tool_error("API_ERROR", "API request failed")
        return payload


async def serve_stdio() -> None:
    server = AlertMCPServer()
    for line in sys.stdin:
        if not line.strip():
            continue
        response = await _handle_message(server, json.loads(line))
        payload = (
            json.dumps(response, ensure_ascii=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        os.write(sys.stdout.fileno(), payload)
        sys.stdout.flush()


async def _handle_message(server: AlertMCPServer, message: dict[str, Any]) -> dict[str, Any]:
    method = message.get("method")
    request_id = message.get("id")
    try:
        result: Any
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "serverInfo": {"name": "crawlerai", "version": "0.1.0"}}
        elif method == "tools/list":
            result = {"tools": server.tools()}
        elif method == "tools/call":
            params_value = message.get("params")
            params = params_value if isinstance(params_value, dict) else {}
            arguments_value = params.get("arguments")
            arguments = arguments_value if isinstance(arguments_value, dict) else {}
            result = await server.call_tool(str(params.get("name")), dict(arguments))
        else:
            raise ValueError(f"Unsupported method: {method}")
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.exception("MCP alert server request failed")
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32000, "message": f"{type(exc).__name__}: {exc}"},
        }


def _tool_error(code: str, message: str) -> dict[str, Any]:
    return {"status": "error", "error": {"code": code, "message": message}}


def main() -> None:
    asyncio.run(serve_stdio())


if __name__ == "__main__":
    main()
