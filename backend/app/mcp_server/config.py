from __future__ import annotations

import os
import ipaddress
from dataclasses import dataclass

from app.core.config.public_api import (
    PUBLIC_API_CAPABILITIES,
    PUBLIC_API_MCP_API_KEY_ENV,
    PUBLIC_API_MCP_BASE_URL_ENV,
    PUBLIC_API_MCP_DEFAULT_BASE_URL,
    PUBLIC_API_MCP_DEFAULT_HOST,
    PUBLIC_API_MCP_HOST_ENV,
    PUBLIC_API_MCP_ALLOWED_TRANSPORTS,
    PUBLIC_API_MCP_DEFAULT_TRANSPORT,
    PUBLIC_API_MCP_TRANSPORT_ENV,
)


@dataclass(frozen=True)
class McpRuntimeConfig:
    api_key: str
    api_base_url: str
    transport: str
    host: str


def api_key() -> str:
    return os.environ.get(PUBLIC_API_MCP_API_KEY_ENV, "").strip()


def api_base_url() -> str:
    return os.environ.get(
        PUBLIC_API_MCP_BASE_URL_ENV, PUBLIC_API_MCP_DEFAULT_BASE_URL
    ).rstrip("/")


def bind_host() -> str:
    return os.environ.get(PUBLIC_API_MCP_HOST_ENV, PUBLIC_API_MCP_DEFAULT_HOST).strip()


def transport() -> str:
    return (
        os.environ.get(PUBLIC_API_MCP_TRANSPORT_ENV, PUBLIC_API_MCP_DEFAULT_TRANSPORT)
        .strip()
        .lower()
    )


def _is_loopback_host(host: str) -> bool:
    normalized = str(host or "").strip().lower()
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def runtime_config() -> McpRuntimeConfig:
    configured_transport = transport()
    if configured_transport not in PUBLIC_API_MCP_ALLOWED_TRANSPORTS:
        raise RuntimeError(
            f"{PUBLIC_API_MCP_TRANSPORT_ENV} must be one of: "
            f"{', '.join(sorted(PUBLIC_API_MCP_ALLOWED_TRANSPORTS))}"
        )
    configured_host = bind_host()
    if configured_transport != "stdio" and not _is_loopback_host(configured_host):
        raise RuntimeError(
            "Network MCP is limited to a literal loopback host until per-client "
            "inbound authentication is implemented."
        )
    configured_api_key = api_key()
    if not configured_api_key:
        raise RuntimeError(f"{PUBLIC_API_MCP_API_KEY_ENV} is required")
    return McpRuntimeConfig(
        api_key=configured_api_key,
        api_base_url=api_base_url(),
        transport=configured_transport,
        host=configured_host,
    )


def capabilities() -> dict[str, object]:
    return dict(PUBLIC_API_CAPABILITIES)
