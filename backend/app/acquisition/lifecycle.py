from __future__ import annotations

from app.acquisition.http_client import close_shared_http_client as close_adapter_client
from app.acquisition.runtime import close_shared_http_client as close_runtime_client


async def close_shared_http_client() -> None:
    await close_runtime_client()
    await close_adapter_client()
