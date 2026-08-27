from __future__ import annotations

import logging
from functools import lru_cache

from app.connectors.amazon_adapter import AmazonAdapter
from app.connectors.platform_adapter import AdapterResult, BaseAdapter

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def registered_adapters() -> tuple[BaseAdapter, ...]:
    return (AmazonAdapter(),)


async def run_adapter(
    url: str,
    html: str,
    surface: str | None,
    *,
    proxy: str | None = None,
) -> AdapterResult | None:
    for adapter in registered_adapters():
        if not await adapter.can_handle(url, html):
            continue
        try:
            return await adapter.extract(url, html, str(surface or ""), proxy=proxy)
        except Exception:
            logger.warning(
                "Adapter %s failed open for %s surface=%s",
                adapter.name,
                url,
                surface,
                exc_info=True,
            )
            return None
    return None
