from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import app.api.crawls as crawls_api
import app.crawl.crud as crawl_crud
from app.models.crawl_run import CrawlLog


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_run_and_logs_returns_run_even_without_logs(
    db_session,
    test_user,
) -> None:
    run = await crawl_crud.create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )

    loaded_run, rows = await crawl_crud.get_run_and_logs(db_session, run.id, limit=500)

    assert loaded_run is not None
    assert loaded_run.id == run.id
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_run_and_logs_applies_after_id_filter(
    db_session,
    test_user,
) -> None:
    run = await crawl_crud.create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )
    first = CrawlLog(run_id=run.id, level="info", message="first")
    second = CrawlLog(run_id=run.id, level="info", message="second")
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)

    loaded_run, rows = await crawl_crud.get_run_and_logs(
        db_session,
        run.id,
        after_id=first.id,
        limit=500,
    )

    assert loaded_run is not None
    assert loaded_run.id == run.id
    assert [row.message for row in rows] == ["second"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_treats_protocol_attribute_error_as_disconnect(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _DisconnectingWebSocket:
        cookies: dict[str, str] = {}
        headers: dict[str, str] = {}
        accepted = False
        closed: list[tuple[int, str]] = []

        async def accept(self) -> None:
            self.accepted = True

        async def send_json(self, payload: dict) -> None:
            del payload
            raise AttributeError(
                "'WebSocketProtocol' object has no attribute 'transfer_data_task'"
            )

        async def close(self, *, code: int, reason: str) -> None:
            self.closed.append((code, reason))

    async def _resolve_user(_token: str | None):
        return SimpleNamespace(id=1, role="admin")

    async def _load_run(*, run_id: int, user):
        del run_id, user
        return SimpleNamespace(status_value="running")

    async def _load_snapshot(*, run_id: int, after_id: int | None):
        del after_id
        return (
            [
                SimpleNamespace(
                    id=1,
                    run_id=run_id,
                    level="info",
                    message="hello",
                    created_at=datetime.now(UTC),
                )
            ],
            SimpleNamespace(status_value="running"),
        )

    websocket = _DisconnectingWebSocket()
    monkeypatch.setattr(crawls_api, "resolve_log_stream_user", _resolve_user)
    monkeypatch.setattr(crawls_api, "load_accessible_log_run", _load_run)
    monkeypatch.setattr(crawls_api, "load_log_stream_snapshot", _load_snapshot)

    with caplog.at_level(logging.ERROR, logger=crawls_api.logger.name):
        await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.accepted is True
    assert not caplog.records
    assert websocket.closed == []


class _OriginWebSocket:
    def __init__(self, headers: dict[str, str]) -> None:
        self.cookies: dict[str, str] = {}
        self.headers = headers
        self.accepted = False
        self.closed: list[tuple[int, str]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        del payload

    async def close(self, *, code: int, reason: str) -> None:
        self.closed.append((code, reason))


def _patch_log_stream_mocks(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _resolve_user(_token: str | None):
        return SimpleNamespace(id=1, role="admin")

    async def _load_run(*, run_id: int, user):
        del run_id, user
        return SimpleNamespace(status_value="completed")

    async def _load_snapshot(*, run_id: int, after_id: int | None):
        del run_id, after_id
        return ([], SimpleNamespace(status_value="completed"))

    monkeypatch.setattr(crawls_api, "resolve_log_stream_user", _resolve_user)
    monkeypatch.setattr(crawls_api, "load_accessible_log_run", _load_run)
    monkeypatch.setattr(crawls_api, "load_log_stream_snapshot", _load_snapshot)


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_rejects_disallowed_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    websocket = _OriginWebSocket({"origin": "https://evil.example"})

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.accepted is False
    assert websocket.closed == [(1008, "Origin not allowed")]


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_allows_configured_frontend_origin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_log_stream_mocks(monkeypatch)
    origin = crawls_api.get_frontend_origins()[0]
    websocket = _OriginWebSocket({"origin": origin})

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.accepted is True
    # Terminal status with no rows closes cleanly with code 1000.
    assert websocket.closed == [(1000, "Run completed")]


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_allows_missing_origin_for_non_browser_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_log_stream_mocks(monkeypatch)
    websocket = _OriginWebSocket({})

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.accepted is True
    assert websocket.closed == [(1000, "Run completed")]


class _BackoffWebSocket:
    def __init__(self) -> None:
        self.cookies: dict[str, str] = {}
        self.headers: dict[str, str] = {}
        self.accepted = False
        self.sent: list[dict] = []
        self.closed: list[tuple[int, str]] = []

    async def accept(self) -> None:
        self.accepted = True

    async def send_json(self, payload: dict) -> None:
        self.sent.append(payload)

    async def close(self, *, code: int, reason: str) -> None:
        self.closed.append((code, reason))


def _log_row(row_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=row_id,
        run_id=1,
        level="info",
        message=f"log {row_id}",
        created_at=datetime.now(UTC),
    )


def _patch_backoff_stream(
    monkeypatch: pytest.MonkeyPatch,
    snapshots: list[tuple[list, SimpleNamespace]],
    *,
    initial_status: str = "running",
) -> list[float]:
    async def _resolve_user(_token: str | None):
        return SimpleNamespace(id=1, role="admin")

    async def _load_run(*, run_id: int, user):
        del run_id, user
        return SimpleNamespace(status_value=initial_status)

    scripted = list(snapshots)

    async def _load_snapshot(*, run_id: int, after_id: int | None):
        del run_id, after_id
        return scripted.pop(0)

    sleeps: list[float] = []

    async def _fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(crawls_api, "resolve_log_stream_user", _resolve_user)
    monkeypatch.setattr(crawls_api, "load_accessible_log_run", _load_run)
    monkeypatch.setattr(crawls_api, "load_log_stream_snapshot", _load_snapshot)
    monkeypatch.setattr(crawls_api.asyncio, "sleep", _fake_sleep)
    return sleeps


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_backs_off_on_empty_polls_and_resets_on_new_rows(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        crawls_api.crawler_runtime_settings,
        cooperative_sleep_poll_ms=250,
        log_stream_max_poll_ms=5000,
    )
    running = SimpleNamespace(status_value="running")
    sleeps = _patch_backoff_stream(
        monkeypatch,
        [
            ([], running),
            ([], running),
            ([_log_row(1)], running),
            ([], running),
            ([], running),
            ([], SimpleNamespace(status_value="completed")),
        ],
    )
    websocket = _BackoffWebSocket()

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.closed == [(1000, "Run completed")]
    assert len(websocket.sent) == 1
    # 250ms base doubles while idle; new rows reset it to the base cadence.
    assert sleeps == [0.25, 0.5, 1.0, 0.25, 0.5]


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_resets_interval_on_non_terminal_status_change(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        crawls_api.crawler_runtime_settings,
        cooperative_sleep_poll_ms=250,
        log_stream_max_poll_ms=5000,
    )
    running = SimpleNamespace(status_value="running")
    paused = SimpleNamespace(status_value="paused")
    sleeps = _patch_backoff_stream(
        monkeypatch,
        [
            ([], running),
            ([], running),
            ([], paused),
            ([], paused),
            ([], SimpleNamespace(status_value="completed")),
        ],
    )
    websocket = _BackoffWebSocket()

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.closed == [(1000, "Run completed")]
    # The status change poll resets the next interval to the 250ms base.
    assert sleeps == [0.25, 0.5, 1.0, 0.25]


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_caps_backoff_at_configured_max(
    monkeypatch: pytest.MonkeyPatch,
    patch_settings,
) -> None:
    patch_settings(
        crawls_api.crawler_runtime_settings,
        cooperative_sleep_poll_ms=250,
        log_stream_max_poll_ms=1000,
    )
    running = SimpleNamespace(status_value="running")
    sleeps = _patch_backoff_stream(
        monkeypatch,
        [
            ([], running),
            ([], running),
            ([], running),
            ([], running),
            ([], running),
            ([], running),
            ([], SimpleNamespace(status_value="completed")),
        ],
    )
    websocket = _BackoffWebSocket()

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert sleeps == [0.25, 0.5, 1.0, 1.0, 1.0, 1.0]


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_ws_terminal_close_is_immediate_without_sleep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sleeps = _patch_backoff_stream(
        monkeypatch,
        [([], SimpleNamespace(status_value="completed"))],
        initial_status="completed",
    )
    websocket = _BackoffWebSocket()

    await crawls_api.crawls_logs_ws(websocket, run_id=1)

    assert websocket.closed == [(1000, "Run completed")]
    assert sleeps == []
