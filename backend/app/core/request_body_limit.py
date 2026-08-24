from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse

from app.core.config import settings
from app.core.config.auth_security import (
    CSV_UPLOAD_PATH,
    PUBLIC_API_PATH_PREFIX,
    REQUEST_BODY_TOO_LARGE_DETAIL,
)

AsgiCallable = Callable[
    [
        dict[str, Any],
        Callable[[], Awaitable[dict[str, Any]]],
        Callable[[dict[str, Any]], Awaitable[None]],
    ],
    Awaitable[None],
]


class RequestBodyTooLarge(Exception):
    pass


class RequestBodyLimitMiddleware:
    """Reject request bodies before framework parsing or multipart spooling."""

    def __init__(self, app: AsgiCallable) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        limit = request_body_limit_bytes(str(scope.get("path") or ""))
        content_length = _content_length(scope)
        if content_length is not None and content_length > limit:
            await _too_large_response(scope, receive, send)
            return
        consumed = 0
        response_started = False

        async def limited_receive():
            nonlocal consumed
            message = await receive()
            if message.get("type") == "http.request":
                consumed += len(message.get("body", b""))
                if consumed > limit:
                    raise RequestBodyTooLarge
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message.get("type") == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, tracking_send)
        except RequestBodyTooLarge:
            if not response_started:
                await _too_large_response(scope, receive, send)


def request_body_limit_bytes(path: str) -> int:
    if path == CSV_UPLOAD_PATH:
        return int(settings.csv_upload_max_bytes) + int(
            settings.multipart_overhead_max_bytes
        )
    if path.startswith(PUBLIC_API_PATH_PREFIX):
        return int(settings.public_api_request_body_max_bytes)
    return int(settings.request_body_max_bytes)


def _content_length(scope: dict[str, Any]) -> int | None:
    for name, value in scope.get("headers") or ():
        if name.lower() != b"content-length":
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            return None
        return max(0, parsed)
    return None


async def _too_large_response(scope, receive, send) -> None:
    response = JSONResponse(
        {"detail": REQUEST_BODY_TOO_LARGE_DETAIL},
        status_code=413,
    )
    await response(scope, receive, send)
