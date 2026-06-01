from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from fastapi import FastAPI

from app.core import logfire_integration
from app.core.config import settings


@pytest.fixture(autouse=True)
def reset_logfire_state(monkeypatch):
    logfire_integration.reset_logfire_state_for_tests()
    monkeypatch.delitem(sys.modules, "logfire", raising=False)
    yield
    logfire_integration.reset_logfire_state_for_tests()
    monkeypatch.delitem(sys.modules, "logfire", raising=False)


@pytest.mark.component
def test_logfire_disabled_skips_configuration(monkeypatch) -> None:
    monkeypatch.setattr(settings, "logfire_enabled", False)

    assert logfire_integration.configure_logfire() is False


@pytest.mark.component
def test_logfire_configures_once_and_instruments(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    fake_logfire = SimpleNamespace(
        configure=lambda **kwargs: calls.append(("configure", kwargs)),
        instrument_fastapi=lambda app, **kwargs: calls.append(
            ("fastapi", {"app": app, **kwargs})
        ),
        instrument_celery=lambda **kwargs: calls.append(("celery", kwargs)),
    )
    monkeypatch.setitem(sys.modules, "logfire", fake_logfire)
    monkeypatch.setattr(settings, "logfire_enabled", True)
    monkeypatch.setattr(settings, "logfire_token", "token-123")
    monkeypatch.setattr(settings, "logfire_service_name", "invoro-test")
    monkeypatch.setattr(settings, "logfire_environment", "staging")
    monkeypatch.setattr(settings, "logfire_capture_headers", False)

    app = FastAPI()

    assert logfire_integration.instrument_fastapi(app) is True
    assert logfire_integration.instrument_celery() is True
    assert logfire_integration.instrument_fastapi(app) is True

    configure_calls = [call for call in calls if call[0] == "configure"]
    fastapi_calls = [call for call in calls if call[0] == "fastapi"]
    celery_calls = [call for call in calls if call[0] == "celery"]
    assert configure_calls == [
        (
            "configure",
            {
                "send_to_logfire": "if-token-present",
                "token": "token-123",
                "service_name": "invoro-test",
                "environment": "staging",
                "console": False,
            },
        )
    ]
    assert len(fastapi_calls) == 1
    assert fastapi_calls[0][1]["capture_headers"] is False
    assert len(celery_calls) == 1
