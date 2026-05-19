from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy import select

from app.api.product_intelligence import router as product_intelligence_router
from app.core.celery_app import celery_app
from app.models.monitor import MonitorEvent, MonitorJob
from app.models.notification import InAppNotification
from app.services.config.monitor_settings import (
    MONITOR_EVENT_FIELD_CHANGED,
    MONITOR_PRIORITY_BACKGROUND,
    MONITOR_STATUS_ACTIVE,
    NOTIFICATION_STATUS_SENT,
    SKIP_HEAD_CHECK_KEY,
)
from app.services.monitor_alert_service import create_monitor_change_notification
from app.services.monitor_change_detection import (
    ensure_monitor_change_detection_registered,
)
from app.services.monitor_scheduler_service import MonitorSchedulerService
from app.services.monitor_service import create_monitor
from app.services.pipeline import run_complete_callbacks


def test_product_intelligence_create_monitor_accepts_omitted_body() -> None:
    route = next(
        route
        for route in product_intelligence_router.routes
        if getattr(route, "path", "")
        == "/api/product-intelligence/jobs/{job_id}/create-monitor"
    )

    assert [param.name for param in route.dependant.body_params] == ["payload"]
    assert route.dependant.body_params[0].default is None


def test_monitor_celery_tasks_registered_on_app_import() -> None:
    assert "monitor.check_due_jobs" in celery_app.tasks
    assert "monitor.purge_expired_snapshots" in celery_app.tasks


def test_monitor_change_detection_registration_replaces_stale_callback(monkeypatch):
    monkeypatch.setattr(run_complete_callbacks, "_run_complete_callbacks", {})

    ensure_monitor_change_detection_registered()
    ensure_monitor_change_detection_registered()

    assert list(run_complete_callbacks._run_complete_callbacks) == [
        "monitor_change_detection"
    ]


@pytest.mark.asyncio
async def test_dispatch_monitor_run_starts_created_run(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def fake_create_run(session, user_id, payload):
        calls.append(("create", user_id))
        assert payload["settings"]["monitor_id"] == 42
        return SimpleNamespace(id=123)

    async def fake_dispatch_run(session, run):
        calls.append(("dispatch", run.id))
        return run

    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.create_crawl_run_from_payload",
        fake_create_run,
    )
    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.dispatch_run",
        fake_dispatch_run,
    )

    monitor = SimpleNamespace(
        id=42,
        user_id=7,
        status=MONITOR_STATUS_ACTIVE,
        settings={},
        surface="ecommerce_detail",
        requested_fields=["price"],
    )

    run_ids = await MonitorSchedulerService().dispatch_monitor_run(
        SimpleNamespace(),
        monitor,
        ["https://example.com/p/1"],
    )

    assert run_ids == [123]
    assert calls == [("create", 7), ("dispatch", 123)]


@pytest.mark.asyncio
async def test_ecommerce_monitor_defaults_to_skip_head_check(db_session, test_user):
    monitor = await create_monitor(
        db_session,
        user=test_user,
        payload={
            "name": "price watch",
            "urls": ["https://example.com/product/1"],
            "surface": "ecommerce_detail",
            "tracked_fields": ["price"],
            "schedule_interval_hours": 24,
            "priority": MONITOR_PRIORITY_BACKGROUND,
        },
    )

    assert monitor.settings[SKIP_HEAD_CHECK_KEY] is True


@pytest.mark.asyncio
async def test_monitor_alert_creates_unread_notification(db_session, test_user):
    monitor = MonitorJob(
        user_id=test_user.id,
        name="price watch",
        urls=["https://example.com/product/1"],
        domains=["example.com"],
        surface="ecommerce_detail",
        tracked_fields=["price"],
        schedule_interval_hours=24,
        priority=MONITOR_PRIORITY_BACKGROUND,
        retention_days=30,
        settings={SKIP_HEAD_CHECK_KEY: True},
        requested_fields=["price"],
        status=MONITOR_STATUS_ACTIVE,
    )
    db_session.add(monitor)
    await db_session.flush()
    event = MonitorEvent(
        monitor_id=monitor.id,
        run_id=None,
        source_url="https://example.com/product/1",
        event_type=MONITOR_EVENT_FIELD_CHANGED,
        field_name="price",
        old_value="19.99",
        new_value="17.99",
    )

    notification = await create_monitor_change_notification(
        db_session,
        monitor=monitor,
        events=[event],
    )
    await db_session.commit()

    assert notification is not None
    assert event.notification_status == NOTIFICATION_STATUS_SENT
    row = await db_session.scalar(select(InAppNotification))
    assert row is not None
    assert row.user_id == test_user.id
    assert row.monitor_id == monitor.id
    assert row.event_count == 1
    assert row.read is False
