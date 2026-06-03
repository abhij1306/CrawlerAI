"""Optional Pydantic Logfire wiring for external OpenTelemetry export."""

from __future__ import annotations

import logging
import sys
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any, cast
from urllib.parse import urlsplit, urlunsplit

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger("app.core.logfire")
_MAX_ATTRIBUTE_LENGTH = 500


class _LogfireState:
    configured = False
    fastapi_instrumented = False
    celery_instrumented = False


def configure_logfire() -> bool:
    """Configure Logfire once when explicitly enabled."""
    if not settings.logfire_enabled:
        return False
    if _running_under_pytest() and not settings.logfire_enabled_in_tests:
        return False
    if _LogfireState.configured:
        return True

    try:
        import logfire
    except ModuleNotFoundError:
        logger.warning("Logfire enabled but package is not installed")
        return False

    token = settings.logfire_token.strip() or None
    logfire.configure(
        send_to_logfire=settings.logfire_send_to_logfire,
        token=token,
        service_name=settings.logfire_service_name,
        environment=settings.logfire_environment or settings.app_env,
        console=False,
        inspect_arguments=False,
    )
    _LogfireState.configured = True
    if token is None and settings.logfire_send_to_logfire is not False:
        logger.warning(
            "Logfire enabled without LOGFIRE_TOKEN; cloud export is disabled"
        )
    return True


def instrument_fastapi(app: FastAPI) -> bool:
    """Instrument FastAPI requests when Logfire is enabled."""
    if _LogfireState.fastapi_instrumented or not configure_logfire():
        return _LogfireState.fastapi_instrumented

    import logfire

    logfire.instrument_fastapi(
        app,
        capture_headers=bool(settings.logfire_capture_headers),
    )
    _LogfireState.fastapi_instrumented = True
    return True


def instrument_celery() -> bool:
    """Instrument Celery producers and workers when Logfire is enabled."""
    if _LogfireState.celery_instrumented or not configure_logfire():
        return _LogfireState.celery_instrumented

    import logfire

    logfire.instrument_celery()
    _LogfireState.celery_instrumented = True
    return True


@contextmanager
def logfire_span(name: str, **attributes: object) -> Iterator[Any]:
    """Create a Logfire span, or a no-op context when Logfire is disabled."""
    if not settings.logfire_enabled or not configure_logfire():
        with nullcontext(None) as span:
            yield span
        return

    try:
        import logfire
    except ModuleNotFoundError:
        with nullcontext(None) as span:
            yield span
        return

    safe_attributes = cast(dict[str, Any], _safe_logfire_attributes(attributes))
    with logfire.span(
        str(name),
        **safe_attributes,
    ) as span:
        yield span


def _safe_logfire_attributes(attributes: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in attributes.items():
        normalized_key = str(key or "").strip()
        if not normalized_key:
            continue
        normalized_value = _safe_logfire_value(value, key=normalized_key)
        if normalized_value is not None:
            safe[normalized_key] = normalized_value
    return safe


def _running_under_pytest() -> bool:
    return "pytest" in sys.modules


def _safe_logfire_value(value: object, *, key: str = "") -> object | None:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _redact_logfire_url_value(key, value)[:_MAX_ATTRIBUTE_LENGTH]
    if isinstance(value, tuple | list | set):
        return [
            item
            for item in (_safe_logfire_value(member, key=key) for member in value)
            if item is not None
        ][:_MAX_ATTRIBUTE_LENGTH]
    return str(value)[:_MAX_ATTRIBUTE_LENGTH]


def _redact_logfire_url_value(key: str, value: str) -> str:
    if "url" not in key.casefold():
        return value
    parsed = urlsplit(value)
    if not parsed.scheme or not parsed.netloc:
        return value
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def set_logfire_attributes(span: Any, **attributes: object) -> None:
    if span is None or not hasattr(span, "set_attributes"):
        return
    safe_attributes = _safe_logfire_attributes(attributes)
    if not safe_attributes:
        return
    span.set_attributes(safe_attributes)


def reset_logfire_state_for_tests() -> None:
    _LogfireState.configured = False
    _LogfireState.fastapi_instrumented = False
    _LogfireState.celery_instrumented = False


__all__ = [
    "configure_logfire",
    "instrument_celery",
    "instrument_fastapi",
    "logfire_span",
    "reset_logfire_state_for_tests",
    "set_logfire_attributes",
]
