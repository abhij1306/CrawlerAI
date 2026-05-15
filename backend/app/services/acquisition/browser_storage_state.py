"""Browser storage-state capture and persist-policy marking.

Owns the cohesive concern of pulling storage state from a live browser context
and routing it to `cookie_store` persistence for both run- and domain-scoped
slots. Kept separate from `browser_runtime.py` so the runtime pool module only
orchestrates page lifecycle and not storage-state I/O.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.services.acquisition.browser_diagnostics import (
    CHROMIUM_BROWSER_ENGINE as _CHROMIUM_BROWSER_ENGINE,
)
from app.services.acquisition import cookie_store
from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

RUN_STORAGE_PERSIST_ATTR = "_crawler_persist_run_storage_state"
DOMAIN_STORAGE_PERSIST_ATTR = "_crawler_persist_domain_storage_state"


def _browser_context_timeout_seconds() -> float:
    return max(
        0.1,
        float(crawler_runtime_settings.browser_context_timeout_ms) / 1000,
    )


async def persist_context_storage_state(
    context: Any,
    *,
    run_id: int | None,
    domain: str | None,
    browser_engine: str = _CHROMIUM_BROWSER_ENGINE,
    persist_run_storage_state: bool = True,
    persist_domain_storage_state: bool = True,
    timeout_seconds: float | None = None,
) -> None:
    normalized_domain = str(domain or "").strip()
    if run_id is None and not normalized_domain:
        return
    storage_state_fn = getattr(context, "storage_state", None)
    if storage_state_fn is None:
        return
    resolved_timeout_seconds = max(
        0.1,
        float(
            timeout_seconds
            if timeout_seconds is not None
            else _browser_context_timeout_seconds()
        ),
    )
    try:
        storage_state = await asyncio.wait_for(
            storage_state_fn(),
            timeout=resolved_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out capturing browser storage state for run_id=%s domain=%s after %.1fs",
            run_id,
            normalized_domain or None,
            resolved_timeout_seconds,
        )
        return
    except Exception:
        logger.debug(
            "Failed to capture browser storage state for run_id=%s domain=%s",
            run_id,
            normalized_domain or None,
            exc_info=True,
        )
        return
    if run_id is not None and persist_run_storage_state:
        try:
            await cookie_store.persist_storage_state_for_run(
                run_id,
                storage_state,
                browser_engine=browser_engine,
            )
        except Exception:
            logger.error(
                "Failed to persist browser storage state for run_id=%s",
                run_id,
                exc_info=True,
            )
    if normalized_domain and persist_domain_storage_state:
        try:
            await cookie_store.persist_storage_state_for_domain(
                normalized_domain,
                storage_state,
                browser_engine=browser_engine,
            )
        except Exception:
            logger.error(
                "Failed to persist browser storage state for domain=%s",
                normalized_domain,
                exc_info=True,
            )


def mark_storage_state_persist_policy(
    page: Any,
    *,
    persist_run_storage_state: bool,
    persist_domain_storage_state: bool,
) -> None:
    context = getattr(page, "context", None)
    if callable(context):
        try:
            context = context()
        except Exception:
            return
    if context is None:
        return
    try:
        setattr(context, RUN_STORAGE_PERSIST_ATTR, persist_run_storage_state)
    except Exception:
        logger.debug(
            "Failed to set %s on browser context", RUN_STORAGE_PERSIST_ATTR,
            exc_info=True,
        )
    try:
        setattr(context, DOMAIN_STORAGE_PERSIST_ATTR, persist_domain_storage_state)
    except Exception:
        logger.debug(
            "Failed to set %s on browser context", DOMAIN_STORAGE_PERSIST_ATTR,
            exc_info=True,
        )


__all__ = [
    "DOMAIN_STORAGE_PERSIST_ATTR",
    "RUN_STORAGE_PERSIST_ATTR",
    "mark_storage_state_persist_policy",
    "persist_context_storage_state",
]
