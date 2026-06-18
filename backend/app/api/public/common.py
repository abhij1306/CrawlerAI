from __future__ import annotations

from time import perf_counter
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

from app.services.config.public_api import PUBLIC_API_STATUS_ERROR, PUBLIC_API_STATUS_OK


class PublicApiError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


def public_success(data: Any, request: Request) -> dict[str, Any]:
    return {
        "status": PUBLIC_API_STATUS_OK,
        "data": data,
        "meta": _public_meta(request),
    }


def public_error_payload(
    request: Request,
    *,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "status": PUBLIC_API_STATUS_ERROR,
        "error": {
            "code": code,
            "message": message,
            "details": details or {},
        },
        "meta": _public_meta(request),
    }


def public_error_response(
    request: Request,
    *,
    code: str,
    message: str,
    status_code: int,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    response_headers = dict(headers or {})
    response_headers.update(public_rate_headers(request))
    return JSONResponse(
        public_error_payload(
            request,
            code=code,
            message=message,
            details=details,
        ),
        status_code=status_code,
        headers=response_headers,
    )


def public_rate_headers(request: Request) -> dict[str, str]:
    headers = getattr(request.state, "public_rate_limit_headers", None)
    return dict(headers) if isinstance(headers, dict) else {}


def _public_meta(request: Request) -> dict[str, Any]:
    meta: dict[str, Any] = {"request_id": request.headers.get("x-request-id", "")}
    started_at = getattr(request.state, "public_api_started_at", None)
    if isinstance(started_at, (int, float)):
        meta["duration_ms"] = int(max(0.0, perf_counter() - float(started_at)) * 1000)
    return meta
