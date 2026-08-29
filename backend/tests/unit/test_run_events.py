from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import runpy
from typing import Any, cast

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.run_events import RunEventKind
from app.crawl.pipeline.runtime_helpers import persist_failure_state
from app.crawl.run_events import RunEventFact, RunEventTimeline
from app.crawl.state import CrawlStatus, update_run_status
from app.schemas.common import RunEventResponse


pytestmark = [pytest.mark.unit, pytest.mark.asyncio]


class _SessionContext:
    def __init__(self, session: "_RecordingSession") -> None:
        self.session = session

    async def __aenter__(self) -> "_RecordingSession":
        return self.session

    async def __aexit__(
        self,
        exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> bool:
        self.session.context_exceptions.append(exc_type)
        return False


class _SavepointContext:
    def __init__(self, session: "_RecordingSession") -> None:
        self.session = session

    async def __aenter__(self) -> "_RecordingSession":
        self.session.savepoints_entered += 1
        return self.session

    async def __aexit__(
        self,
        exc_type: object,
        _exc: object,
        _traceback: object,
    ) -> bool:
        self.session.savepoint_exception = exc_type
        return False


class _Result:
    def __init__(self, rows: list[Any]) -> None:
        self.rows = rows

    def scalars(self) -> "_Result":
        return self

    def all(self) -> list[Any]:
        return self.rows


class _RecordingSession:
    def __init__(self, sequences: list[int]) -> None:
        self._sequences = iter(sequences)
        self.rows: list[object] = []
        self.query_rows: list[object] = []
        self.scalar_calls: list[tuple[object, tuple[object, ...]]] = []
        self.query: object | None = None
        self.flushes = 0
        self.commits = 0
        self.rollbacks = 0
        self.savepoints_entered = 0
        self.savepoint_exception: object | None = None
        self.context_exceptions: list[object] = []

    async def scalar(self, statement: object, *args: object) -> int:
        self.scalar_calls.append((statement, args))
        return next(self._sequences)

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    def begin_nested(self) -> _SavepointContext:
        return _SavepointContext(self)

    async def execute(self, query: object) -> _Result:
        self.query = query
        return _Result(self.query_rows)


class _SessionFactory:
    def __init__(self, session: _RecordingSession) -> None:
        self.session = session

    def __call__(self) -> _SessionContext:
        return _SessionContext(self.session)


def _timeline(session: _RecordingSession) -> RunEventTimeline:
    return RunEventTimeline(
        cast(async_sessionmaker[AsyncSession], _SessionFactory(session))
    )


async def test_timeline_validates_structured_run_event_facts() -> None:
    timeline = RunEventTimeline(cast(async_sessionmaker[AsyncSession], object()))

    with pytest.raises(TypeError, match="kind"):
        await timeline.record(
            run_id=1,
            fact=RunEventFact(kind=cast(RunEventKind, "run.started")),
        )
    with pytest.raises(ValueError, match="missing required facts"):
        await timeline.record(
            run_id=1,
            fact=RunEventFact(kind=RunEventKind.RUN_STARTED),
        )
    with pytest.raises(ValueError, match="requires URL and URL scope"):
        await timeline.record(
            run_id=1,
            fact=RunEventFact(
                kind=RunEventKind.URL_STARTED,
                facts={"index": 1, "total": 1},
            ),
        )
    with pytest.raises(ValueError, match="finite numbers"):
        await timeline.record(
            run_id=1,
            fact=RunEventFact(
                kind=RunEventKind.RUN_STARTED,
                facts={"seed_url_count": float("nan")},
            ),
        )


async def test_timeline_sequences_and_cursors_run_events() -> None:
    session = _RecordingSession([1, 2, 3])
    timeline = _timeline(session)

    first = await timeline.record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.RUN_STARTED,
            facts={"seed_url_count": 1},
        ),
    )
    second = await timeline.record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.URL_STARTED,
            url="https://example.com/products/widget",
            url_scope_id="url:1",
            facts={"index": 1, "total": 1},
        ),
    )
    third = await timeline.record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.RUN_LIMIT_REACHED,
            facts={"limit_name": "max_records", "limit_value": 10},
        ),
    )

    assert first is not None and second is not None and third is not None
    assert [event.sequence for event in (first, second, third)] == [1, 2, 3]
    session.query_rows = [second, third]
    assert [
        event.sequence
        for event in await timeline.list_after(run_id=42, after_sequence=first.sequence)
    ] == [2, 3]
    assert session.commits == 3
    assert "ORDER BY run_events.sequence ASC" in str(session.query)
    assert "run_events.sequence >" in str(session.query)


async def test_timeline_normalizes_blank_run_scope_before_persistence() -> None:
    session = _RecordingSession([1])

    event = await _timeline(session).record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.RUN_STARTED,
            url="   ",
            url_scope_id="   ",
            facts={"seed_url_count": 1},
        ),
    )

    assert event is not None
    assert event.url is None
    assert event.url_scope_id is None


async def test_timeline_accepts_open_acquisition_reason_code() -> None:
    session = _RecordingSession([1])

    event = await _timeline(session).record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.ACQUISITION_BROWSER_ESCALATED,
            url="https://example.com/products/widget",
            url_scope_id="url:1",
            reason_code="vendor-block:example-shield",
            facts={
                "status_code": 403,
                "prior_method": "httpx",
                "reason": "vendor-block:example-shield",
            },
        ),
    )

    assert event is not None
    assert event.reason_code == "vendor-block:example-shield"


async def test_timeline_uses_bound_session_savepoint_for_atomic_insert() -> None:
    session = _RecordingSession([7])

    event = await _timeline(session).record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.RUN_STARTED,
            facts={"seed_url_count": 1},
        ),
        session=cast(AsyncSession, session),
    )

    assert event is not None
    assert event.sequence == 7
    assert session.savepoints_entered == 1
    assert session.savepoint_exception is None
    assert session.commits == 0
    assert session.rollbacks == 0
    assert len(session.scalar_calls) == 1
    statement, args = session.scalar_calls[0]
    assert "UPDATE crawl_runs" in str(statement)
    assert "RETURNING crawl_runs.run_event_sequence" in str(statement)
    assert args == ()
    assert session.rows == [event]
    assert session.flushes == 1


async def test_timeline_returns_none_when_persistence_is_unavailable() -> None:
    class FailingSession:
        async def scalar(self, _statement: object, *_args: object):
            raise OperationalError(
                "UPDATE crawl_runs", {}, RuntimeError("database offline")
            )

        async def rollback(self) -> None:
            return None

    class FailingSessionContext:
        async def __aenter__(self) -> FailingSession:
            return FailingSession()

        async def __aexit__(self, *_args: object) -> bool:
            return False

    def failing_session() -> FailingSessionContext:
        return FailingSessionContext()

    timeline = RunEventTimeline(cast(async_sessionmaker[AsyncSession], failing_session))

    assert (
        await timeline.record(
            run_id=1,
            fact=RunEventFact(
                kind=RunEventKind.RUN_STARTED,
                facts={"seed_url_count": 1},
            ),
        )
        is None
    )


async def test_timeline_savepoint_failure_leaves_outer_session_usable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _failing_scalar(_statement: object, *_args: object) -> int:
        raise OperationalError(
            "UPDATE crawl_runs", {}, RuntimeError("database offline")
        )

    monkeypatch.setattr(db_session, "scalar", _failing_scalar)

    result = await RunEventTimeline(
        cast(async_sessionmaker[AsyncSession], object())
    ).record(
        run_id=42,
        fact=RunEventFact(
            kind=RunEventKind.RUN_STARTED,
            facts={"seed_url_count": 1},
        ),
        session=db_session,
    )

    assert result is None
    assert (await db_session.execute(text("SELECT 1"))).scalar_one() == 1


async def test_failure_event_uses_explicit_exception_type(
    db_session: AsyncSession,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/widget", surface="ecommerce_detail"
    )
    update_run_status(run, CrawlStatus.RUNNING)
    await db_session.commit()

    await persist_failure_state(
        db_session,
        run.id,
        "misleading-prefix: failure detail",
        exception_type="ActualFailure",
    )

    events = await RunEventTimeline(
        async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    ).list_after(run_id=run.id)
    assert events[-1].facts == {"exception_type": "ActualFailure"}


async def test_run_events_are_append_only_but_parent_cascade_is_allowed(
    db_session: AsyncSession,
    create_test_run,
) -> None:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic"
        / "versions"
        / "20260703_0001_greenfield_schema.py"
    )
    migration = runpy.run_path(str(migration_path))
    await db_session.execute(text(migration["_RUN_EVENTS_APPEND_ONLY_FUNCTION_SQL"]))
    await db_session.execute(text(migration["_RUN_EVENTS_APPEND_ONLY_TRIGGER_SQL"]))
    run = await create_test_run(
        url="https://example.com/products/widget",
        surface="ecommerce_detail",
    )
    event = await RunEventTimeline(
        cast(async_sessionmaker[AsyncSession], object())
    ).record(
        run_id=run.id,
        fact=RunEventFact(
            kind=RunEventKind.RUN_STARTED,
            facts={"seed_url_count": 1},
        ),
        session=db_session,
    )
    assert event is not None
    await db_session.commit()
    event_id = event.id
    run_id = run.id

    with pytest.raises(DBAPIError, match="run_events are append-only"):
        await db_session.execute(
            text("UPDATE run_events SET outcome = 'failed' WHERE id = :event_id"),
            {"event_id": event_id},
        )
    await db_session.rollback()

    with pytest.raises(DBAPIError, match="run_events are append-only"):
        await db_session.execute(
            text("DELETE FROM run_events WHERE id = :event_id"),
            {"event_id": event_id},
        )
    await db_session.rollback()

    await db_session.execute(
        text("DELETE FROM crawl_runs WHERE id = :run_id"), {"run_id": run_id}
    )
    await db_session.commit()
    remaining = await db_session.scalar(
        text("SELECT count(*) FROM run_events WHERE id = :event_id"),
        {"event_id": event_id},
    )
    assert remaining == 0


async def test_run_event_response_has_exact_wire_shape() -> None:
    event = type(
        "Event",
        (),
        {
            "id": 7,
            "run_id": 42,
            "sequence": 1,
            "kind": "url.started",
            "stage": "acquisition",
            "url": "https://example.com/products/widget",
            "url_scope_id": "url:1",
            "severity": "info",
            "outcome": "progress",
            "reason_code": None,
            "facts": {"index": 1, "total": 1},
            "created_at": datetime(2026, 1, 2, tzinfo=UTC),
        },
    )()

    payload = RunEventResponse.model_validate(event, from_attributes=True).model_dump(
        mode="json"
    )

    assert payload == {
        "id": event.id,
        "run_id": 42,
        "sequence": 1,
        "kind": "url.started",
        "stage": "acquisition",
        "url": "https://example.com/products/widget",
        "url_scope_id": "url:1",
        "severity": "info",
        "outcome": "progress",
        "reason_code": None,
        "facts": {"index": 1, "total": 1},
        "created_at": "2026-01-02T00:00:00Z",
    }
