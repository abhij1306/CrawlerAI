"""Celery broker durability config: visibility timeout must cover the task wall limit."""

from __future__ import annotations

import pytest

import app.core.celery_app as celery_module
from app import tasks
from app.core.config import settings
from app.core.config.runtime_settings import crawler_runtime_settings


@pytest.mark.unit
def test_broker_visibility_timeout_is_configured_and_covers_double_wall_limit() -> None:
    options = celery_module.celery_app.conf["broker_transport_options"]
    wall_seconds = int(crawler_runtime_settings.job_max_wall_seconds)
    assert options["visibility_timeout"] >= 2 * wall_seconds


@pytest.mark.unit
def test_broker_visibility_timeout_tracks_wall_limit(monkeypatch) -> None:
    monkeypatch.setattr(crawler_runtime_settings, "job_max_wall_seconds", 120)
    assert celery_module._broker_visibility_timeout_seconds() == 240


@pytest.mark.unit
def test_broker_visibility_timeout_honors_larger_configured_override(
    monkeypatch,
) -> None:
    monkeypatch.setattr(crawler_runtime_settings, "job_max_wall_seconds", 120)
    monkeypatch.setattr(settings, "celery_broker_visibility_timeout_seconds", 900)
    assert celery_module._broker_visibility_timeout_seconds() == 900


@pytest.mark.unit
def test_broker_visibility_timeout_covers_hard_task_time_limit() -> None:
    limits = tasks._crawl_task_time_limits()
    options = celery_module.celery_app.conf["broker_transport_options"]
    assert options["visibility_timeout"] >= 2 * limits["time_limit"]
