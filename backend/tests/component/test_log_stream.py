from __future__ import annotations

import logging
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

import app.api.crawls as crawls_api
import app.services.crawl.crud as crawl_crud
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
