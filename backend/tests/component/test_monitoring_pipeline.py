from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
import httpx
from sqlalchemy import select

from app.api.product_intelligence import router as product_intelligence_router
from app.core.celery_app import celery_app
from app.core.config import settings
from app.models.crawl_run import CrawlRun
from app.models.monitor import MonitorEvent, MonitorJob
from app.models.notification import InAppNotification
from app.services.dispatch import local_dispatcher as local_dispatch_module
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


def _route_by_path(path: str):
    for route in product_intelligence_router.routes:
        if getattr(route, "path", "") == path:
            return route
    raise AssertionError(f"Route not found: {path}")


@pytest.mark.component
def test_product_intelligence_create_monitor_accepts_omitted_body() -> None:
    route = _route_by_path(
        "/api/product-intelligence/jobs/{job_id}/create-monitor"
    )

    assert [param.name for param in route.dependant.body_params] == ["payload"]
    assert route.dependant.body_params[0].default is None


@pytest.mark.component
def test_monitor_celery_tasks_registered_on_app_import() -> None:
    assert "monitor.check_due_jobs" in celery_app.tasks
    assert "monitor.purge_expired_snapshots" in celery_app.tasks


@pytest.mark.component
def test_monitor_change_detection_registration_replaces_stale_callback(monkeypatch):
    monkeypatch.setattr(run_complete_callbacks, "_run_complete_callbacks", {})

    ensure_monitor_change_detection_registered()
    ensure_monitor_change_detection_registered()

    assert list(run_complete_callbacks._run_complete_callbacks) == [
        "monitor_change_detection"
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_dispatch_monitor_run_uses_dispatched_run_from_payload_factory(monkeypatch):
    calls: list[tuple[str, int]] = []

    async def fake_create_run(session, user_id, payload):
        calls.append(("create", user_id))
        assert payload["settings"]["monitor_id"] == 42
        return SimpleNamespace(id=123)

    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.create_crawl_run_from_payload",
        fake_create_run,
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
    assert calls == [("create", 7)]


@pytest.mark.asyncio
@pytest.mark.component
async def test_dispatch_monitor_run_does_not_redispatch_new_run(
    db_session,
    test_user,
    monkeypatch,
):
    monkeypatch.setattr(settings, "celery_dispatch_enabled", False)
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

    created_tasks: list[int] = []

    def _fake_track(run_id: int) -> asyncio.Task[None]:
        created_tasks.append(run_id)
        task = asyncio.create_task(asyncio.sleep(60))
        local_dispatch_module._local_run_tasks[run_id] = task
        return task

    monkeypatch.setattr(local_dispatch_module, "track_local_run_task", _fake_track)

    run_ids = await MonitorSchedulerService().dispatch_monitor_run(
        db_session,
        monitor,
        list(monitor.urls or []),
    )

    assert len(run_ids) == 1
    assert created_tasks == run_ids

    run = await db_session.get(CrawlRun, run_ids[0])
    assert run is not None
    assert run.status == "pending"

    local_task = local_dispatch_module._local_run_tasks.pop(run_ids[0], None)
    if local_task is not None:
        local_task.cancel()
        await asyncio.gather(local_task, return_exceptions=True)


@pytest.mark.asyncio
@pytest.mark.component
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
@pytest.mark.component
async def test_monitor_head_challenge_falls_back_to_get_hash(monkeypatch):
    calls: list[str] = []

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def head(self, url: str):
            calls.append(f"HEAD {url}")
            return httpx.Response(403, headers={"Cf-Mitigated": "challenge"})

    async def _fake_hash(_client, url: str):
        calls.append(f"GET {url}")
        return "hash-1"

    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.monitor_scheduler_service._stream_content_hash",
        _fake_hash,
    )
    state = SimpleNamespace(
        last_etag=None,
        last_modified=None,
        last_content_hash=None,
        last_checked_at=None,
        last_changed_at=None,
        consecutive_unchanged_count=0,
    )

    changed = await MonitorSchedulerService().pre_check_url("https://codeforces.com/", state)

    assert changed is True
    assert state.last_content_hash == "hash-1"
    assert calls == ["HEAD https://codeforces.com/", "GET https://codeforces.com/"]


@pytest.mark.asyncio
@pytest.mark.component
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


@pytest.mark.asyncio
@pytest.mark.component
async def test_monitor_pre_check_unchanged_detection(monkeypatch):
    """Second call with same hash should detect no change."""

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def head(self, url: str):
            return httpx.Response(403, headers={"Cf-Mitigated": "challenge"})

    async def _fake_hash(_client, url: str):
        return "stable-hash"

    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.monitor_scheduler_service._stream_content_hash",
        _fake_hash,
    )
    state = SimpleNamespace(
        last_etag=None,
        last_modified=None,
        last_content_hash=None,
        last_checked_at=None,
        last_changed_at=None,
        consecutive_unchanged_count=0,
    )

    # First call — changed because no prior hash
    changed = await MonitorSchedulerService().pre_check_url("https://example.com/", state)
    assert changed is True
    assert state.last_content_hash == "stable-hash"

    # Second call — same hash, should be unchanged
    changed = await MonitorSchedulerService().pre_check_url("https://example.com/", state)
    assert changed is False
    assert state.consecutive_unchanged_count == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_monitor_pre_check_status_only_fallback(monkeypatch):
    """Non-Cf-Mitigated 405/429 should fall back to _stream_content_hash."""

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def head(self, url: str):
            return httpx.Response(405)

    hash_calls: list[str] = []

    async def _fake_hash(_client, url: str):
        hash_calls.append(url)
        return "fallback-hash"

    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.monitor_scheduler_service._stream_content_hash",
        _fake_hash,
    )
    state = SimpleNamespace(
        last_etag=None,
        last_modified=None,
        last_content_hash=None,
        last_checked_at=None,
        last_changed_at=None,
        consecutive_unchanged_count=0,
    )

    changed = await MonitorSchedulerService().pre_check_url("https://example.com/", state)
    assert changed is True
    assert state.last_content_hash == "fallback-hash"
    assert hash_calls == ["https://example.com/"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_monitor_pre_check_none_hash_no_overwrite(monkeypatch):
    """When _stream_content_hash returns None, treat as no-change and don't overwrite hash."""

    class _FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def head(self, url: str):
            return httpx.Response(403, headers={"Cf-Mitigated": "challenge"})

    async def _fake_hash(_client, url: str):
        return None

    monkeypatch.setattr(
        "app.services.monitor_scheduler_service.httpx.AsyncClient",
        lambda **_kwargs: _FakeClient(),
    )
    monkeypatch.setattr(
        "app.services.monitor_scheduler_service._stream_content_hash",
        _fake_hash,
    )
    state = SimpleNamespace(
        last_etag=None,
        last_modified=None,
        last_content_hash="existing-hash",
        last_checked_at=None,
        last_changed_at=None,
        consecutive_unchanged_count=0,
    )

    changed = await MonitorSchedulerService().pre_check_url("https://example.com/", state)
    # None hash with existing prior hash => treat as changed, but keep prior hash.
    assert changed is True
    # Should not overwrite existing hash
    assert state.last_content_hash == "existing-hash"
    assert state.consecutive_unchanged_count == 0
