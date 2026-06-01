"""Optional Pydantic Logfire wiring for external OpenTelemetry export."""

from __future__ import annotations

import logging

from fastapi import FastAPI

from app.core.config import settings

logger = logging.getLogger("app.core.logfire")
_configured = False
_fastapi_instrumented = False
_celery_instrumented = False


def configure_logfire() -> bool:
    """Configure Logfire once when explicitly enabled."""
    global _configured
    if not settings.logfire_enabled:
        return False
    if _configured:
        return True

    try:
        import logfire
    except ModuleNotFoundError:
        logger.warning("Logfire enabled but package is not installed")
        return False

    token = settings.logfire_token.strip() or None
    logfire.configure(
        send_to_logfire="if-token-present",
        token=token,
        service_name=settings.logfire_service_name,
        environment=settings.logfire_environment or settings.app_env,
        console=False,
    )
    _configured = True
    if token is None:
        logger.warning("Logfire enabled without LOGFIRE_TOKEN; cloud export is disabled")
    return True


def instrument_fastapi(app: FastAPI) -> bool:
    """Instrument FastAPI requests when Logfire is enabled."""
    global _fastapi_instrumented
    if _fastapi_instrumented or not configure_logfire():
        return _fastapi_instrumented

    import logfire

    logfire.instrument_fastapi(
        app,
        capture_headers=bool(settings.logfire_capture_headers),
    )
    _fastapi_instrumented = True
    return True


def instrument_celery() -> bool:
    """Instrument Celery producers and workers when Logfire is enabled."""
    global _celery_instrumented
    if _celery_instrumented or not configure_logfire():
        return _celery_instrumented

    import logfire

    logfire.instrument_celery()
    _celery_instrumented = True
    return True


def reset_logfire_state_for_tests() -> None:
    global _configured, _fastapi_instrumented, _celery_instrumented
    _configured = False
    _fastapi_instrumented = False
    _celery_instrumented = False


__all__ = [
    "configure_logfire",
    "instrument_celery",
    "instrument_fastapi",
    "reset_logfire_state_for_tests",
]
