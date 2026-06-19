from __future__ import annotations

from app.acquisition.runtime_plan import AcquisitionPlan
from app.connectors.adapters.base import AdapterResult


def available_adapter_names() -> tuple[str, ...]:
    return ()


def registered_adapters() -> tuple[object, ...]:
    return ()


async def resolve_adapter(url: str, html: str) -> None:
    del url, html
    return None


async def normalize_adapter_acquisition_url(url: str | None) -> str | None:
    return url


async def run_adapter(
    url: str,
    html: str,
    surface: str | None,
    *,
    proxy: str | None = None,
) -> AdapterResult | None:
    del url, html, surface, proxy
    return None


async def try_blocked_adapter_recovery(
    url: str,
    plan: AcquisitionPlan,
    *,
    proxy_list: list[str] | None = None,
) -> AdapterResult | None:
    del url, plan, proxy_list
    return None
