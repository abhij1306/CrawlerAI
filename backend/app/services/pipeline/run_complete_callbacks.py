from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)

_run_complete_callbacks: dict[str, Callable[[int], Awaitable[None]]] = {}


def register_run_complete_callback(
    cb: Callable[[int], Awaitable[None]],
    *,
    key: str | None = None,
) -> None:
    callback_key = key or f"{cb.__module__}.{cb.__qualname__}:{id(cb)}"
    _run_complete_callbacks[callback_key] = cb


async def on_run_complete(run_id: int) -> None:
    for cb in list(_run_complete_callbacks.values()):
        try:
            await cb(run_id)
        except Exception:
            logger.exception("Run-complete callback failed for run=%s", run_id)
