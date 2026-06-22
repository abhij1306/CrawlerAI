from __future__ import annotations

import logging
from typing import Any

from app.core.config.network_capture import (
    BLOCKED_BROWSER_RESOURCE_TYPES,
    BLOCKED_BROWSER_ROUTE_TOKENS,
    PROTECTED_CHALLENGE_ROUTE_TOKENS,
)

logger = logging.getLogger(__name__)


async def block_unneeded_route(route: Any) -> None:
    request = getattr(route, "request", None)
    resource_type = str(getattr(request, "resource_type", "") or "").lower()
    request_url = str(getattr(request, "url", "") or "").lower()
    if any(token in request_url for token in PROTECTED_CHALLENGE_ROUTE_TOKENS):
        await _continue_route(route, request_url=request_url, protected=True)
        return
    if resource_type in BLOCKED_BROWSER_RESOURCE_TYPES or any(
        token in request_url for token in BLOCKED_BROWSER_ROUTE_TOKENS
    ):
        await _abort_or_continue(
            route, resource_type=resource_type, request_url=request_url
        )
        return
    await _continue_route(route, request_url=request_url, protected=False)


async def _continue_route(route: Any, *, request_url: str, protected: bool) -> None:
    try:
        await route.continue_()
    except Exception:
        if protected:
            logger.debug(
                "Browser request continue failed for protected challenge url=%s",
                request_url,
                exc_info=True,
            )
        else:
            request = getattr(route, "request", None)
            logger.debug(
                "Browser request continue failed for resource_type=%s url=%s",
                str(getattr(request, "resource_type", "") or "").lower(),
                request_url,
                exc_info=True,
            )


async def _abort_or_continue(
    route: Any, *, resource_type: str, request_url: str
) -> None:
    try:
        await route.abort()
        return
    except Exception:
        logger.debug(
            "Browser request abort failed for resource_type=%s url=%s; attempting continue",
            resource_type,
            request_url,
            exc_info=True,
        )
    try:
        await route.continue_()
    except Exception:
        logger.debug(
            "Browser request continue failed after abort failure for resource_type=%s url=%s",
            resource_type,
            request_url,
            exc_info=True,
        )
