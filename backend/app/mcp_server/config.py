from __future__ import annotations

import os

from app.services.config.public_api import (
    PUBLIC_API_CAPABILITIES,
    PUBLIC_API_MCP_API_KEY_ENV,
    PUBLIC_API_MCP_BASE_URL_ENV,
    PUBLIC_API_MCP_DEFAULT_BASE_URL,
    PUBLIC_API_MCP_DEFAULT_HOST,
    PUBLIC_API_MCP_HOST_ENV,
)


def api_key() -> str:
    return os.environ.get(PUBLIC_API_MCP_API_KEY_ENV, "").strip()


def api_base_url() -> str:
    return os.environ.get(PUBLIC_API_MCP_BASE_URL_ENV, PUBLIC_API_MCP_DEFAULT_BASE_URL).rstrip("/")


def bind_host() -> str:
    return os.environ.get(PUBLIC_API_MCP_HOST_ENV, PUBLIC_API_MCP_DEFAULT_HOST).strip()


def capabilities() -> dict[str, object]:
    return dict(PUBLIC_API_CAPABILITIES)
