from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

import app.api.crawls as crawls_api
from app.core.config.run_events import RunEventKind
from app.core.dependencies import get_current_user, get_db
from app.crawl.crud import create_crawl_run
from app.main import app
from app.models.crawl_domain import CrawlStatus
from app.models.crawl_run import RunEvent
from app.schemas.common import RunEventResponse


pytestmark = [pytest.mark.asyncio, pytest.mark.component]


@pytest.fixture
async def crawls_api_client(db_session, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()


async def _run(db_session, test_user):
    return await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )


def _event(
    *, run_id: int, sequence: int, kind: RunEventKind = RunEventKind.RUN_STARTED
):
    return RunEvent(
        run_id=run_id,
        sequence=sequence,
        kind=kind.value,
        stage=None,
        url=None,
        url_scope_id=None,
        severity="info",
        outcome="progress",
        reason_code=None,
        facts={"seed_url_count": 1},
    )


async def test_events_rest_returns_run_event_shape_in_sequence_order(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await _run(db_session, test_user)
    first = _event(run_id=run.id, sequence=1)
    second = _event(run_id=run.id, sequence=2)
    db_session.add_all([second, first])
    await db_session.commit()

    async def _list_after(*, run_id: int, after_sequence: int | None, limit: int):
        assert run_id == run.id
        assert limit == 500
        return [
            event
            for event in (first, second)
            if after_sequence is None or event.sequence > after_sequence
        ]

    monkeypatch.setattr(crawls_api.run_event_timeline, "list_after", _list_after)

    response = await crawls_api_client.get(f"/api/crawls/{run.id}/events")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert [event["sequence"] for event in payload] == [1, 2]
    assert set(payload[0]) == {
        "id",
        "run_id",
        "sequence",
        "kind",
        "stage",
        "url",
        "url_scope_id",
        "severity",
        "outcome",
        "reason_code",
        "facts",
        "created_at",
    }
    assert payload[0]["kind"] == "run.started"
    assert payload[0]["facts"] == {"seed_url_count": 1}

    resumed = await crawls_api_client.get(
        f"/api/crawls/{run.id}/events", params={"after_sequence": 1}
    )
    assert [event["sequence"] for event in resumed.json()] == [2]


async def test_events_rest_validates_sequence_cursor(
    crawls_api_client: AsyncClient,
) -> None:
    response = await crawls_api_client.get(
        "/api/crawls/1/events", params={"after_sequence": -1, "limit": 2001}
    )

    assert response.status_code == 422


async def test_websocket_stream_uses_the_same_run_event_wire_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event = SimpleNamespace(
        id=7,
        run_id=101,
        sequence=4,
        kind=RunEventKind.RUN_STARTED.value,
        stage=None,
        url=None,
        url_scope_id=None,
        severity="info",
        outcome="progress",
        reason_code=None,
        facts={"seed_url_count": 1},
        created_at=datetime.now(UTC),
    )
    terminal = SimpleNamespace(status_value=CrawlStatus.COMPLETED)
    snapshots = [([event], terminal), ([], terminal)]

    async def _load_snapshot(*, run_id: int, after_sequence: int | None):
        assert run_id == 101
        assert after_sequence in (None, 4)
        return snapshots.pop(0)

    async def _sleep(_seconds: float) -> None:
        return None

    class WebSocket:
        def __init__(self) -> None:
            self.sent: list[dict] = []
            self.closed: list[tuple[int, str]] = []

        async def send_json(self, payload: dict) -> None:
            self.sent.append(payload)

        async def close(self, *, code: int, reason: str) -> None:
            self.closed.append((code, reason))

    monkeypatch.setattr(crawls_api, "load_run_event_stream_snapshot", _load_snapshot)
    monkeypatch.setattr(crawls_api.asyncio, "sleep", _sleep)
    websocket = WebSocket()

    await crawls_api._stream_run_event_snapshots(
        websocket,
        run_id=101,
        cursor=None,
        run=terminal,
        base_poll_interval_seconds=0.01,
        max_poll_interval_seconds=0.02,
        poll_interval_seconds=0.01,
        missing_run_snapshots=0,
    )

    assert websocket.sent == [
        RunEventResponse.model_validate(event, from_attributes=True).model_dump(
            mode="json"
        )
    ]
    assert websocket.closed == [(1000, "Run completed")]


async def test_events_websocket_rejects_disallowed_origin() -> None:
    class WebSocket:
        cookies: dict[str, str] = {}
        headers = {"origin": "https://evil.example"}

        def __init__(self) -> None:
            self.accepted = False
            self.closed: list[tuple[int, str]] = []

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, *, code: int, reason: str) -> None:
            self.closed.append((code, reason))

    websocket = WebSocket()
    await crawls_api.crawls_events_ws(websocket, run_id=1)

    assert websocket.accepted is False
    assert websocket.closed == [(1008, "Origin not allowed")]


async def test_events_websocket_rejects_negative_sequence_cursor() -> None:
    class WebSocket:
        cookies: dict[str, str] = {}
        headers: dict[str, str] = {}

        def __init__(self) -> None:
            self.accepted = False
            self.closed: list[tuple[int, str]] = []

        async def accept(self) -> None:
            self.accepted = True

        async def close(self, *, code: int, reason: str) -> None:
            self.closed.append((code, reason))

    websocket = WebSocket()
    await crawls_api.crawls_events_ws(websocket, run_id=1, after_sequence=-1)

    assert websocket.accepted is False
    assert websocket.closed == [(1008, "Invalid cursor")]
