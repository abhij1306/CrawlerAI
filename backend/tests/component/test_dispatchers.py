"""Focused behavioral tests for crawl run dispatchers (audit 4.11).

Covers ``app/workers/``:

- ``LocalRunDispatcher.dispatch``: persists the task id, starts the in-process
  task, and round-trips the refreshed run.
- ``CeleryRunDispatcher.dispatch``: enqueues with the persisted task id and
  clears the task id when the enqueue blows up.
- ``load_run_with_normalized_status`` (hoisted to ``workers/base.py`` in 3.9):
  ValueError on a missing run.
- ``RunDispatcher`` protocol conformance + ``set_task_id`` persist/clear.

DB-backed via the shared ``db_session`` / ``create_test_run`` fixtures; the
actual task execution is stubbed so tests never spawn real crawl work.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import app.workers.celery_dispatcher as celery_dispatcher_module
import app.workers.local_dispatcher as local_dispatcher_module
from app.core.config.runtime_settings import CELERY_TASK_ID_KEY
from app.crawl.state import CrawlStatus
from app.models.crawl_run import CrawlRun
from app.workers.base import (
    RunDispatcher,
    load_run_with_normalized_status,
    set_task_id,
)
from app.workers.celery_dispatcher import CeleryRunDispatcher
from app.workers.local_dispatcher import LocalRunDispatcher

pytestmark = pytest.mark.component


async def _reload_run(db_session: AsyncSession, run_id: int) -> CrawlRun:
    run = await db_session.get(CrawlRun, run_id)
    assert run is not None
    return run


# ---------------------------------------------------------------------------
# LocalRunDispatcher
# ---------------------------------------------------------------------------


async def test_local_dispatch_persists_task_id_and_round_trips_run(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/linen-dress",
        surface="ecommerce_detail",
    )
    started: list[int] = []
    monkeypatch.setattr(
        local_dispatcher_module,
        "track_local_run_task",
        lambda run_id: started.append(run_id) or None,
    )

    run_id = int(run.id)
    returned = await LocalRunDispatcher().dispatch(db_session, run)

    assert int(returned.id) == run_id
    task_id = str(returned.summary_dict()[CELERY_TASK_ID_KEY])
    assert task_id.startswith(f"crawl-run-{run_id}-")
    # The in-process task was kicked off exactly once for this run.
    assert started == [run_id]
    # The task id survives a fresh read (committed, not just in-session).
    db_session.expire_all()
    persisted = await _reload_run(db_session, run_id)
    assert persisted.summary_dict()[CELERY_TASK_ID_KEY] == task_id


async def test_local_dispatch_rejects_terminal_run(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/finished",
        surface="ecommerce_detail",
    )
    run.status = CrawlStatus.COMPLETED.value
    await db_session.commit()
    started: list[int] = []
    monkeypatch.setattr(
        local_dispatcher_module,
        "track_local_run_task",
        lambda run_id: started.append(run_id) or None,
    )

    with pytest.raises(ValueError, match="Cannot dispatch run in state"):
        await LocalRunDispatcher().dispatch(db_session, run)
    assert started == []


async def test_local_dispatch_missing_run_raises_value_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    started: list[int] = []
    monkeypatch.setattr(
        local_dispatcher_module,
        "track_local_run_task",
        lambda run_id: started.append(run_id) or None,
    )
    ghost = CrawlRun(id=999_999_999)

    with pytest.raises(ValueError, match="Run not found"):
        await LocalRunDispatcher().dispatch(db_session, ghost)
    assert started == []


# ---------------------------------------------------------------------------
# CeleryRunDispatcher
# ---------------------------------------------------------------------------


class _StubTask:
    def __init__(self, *, error: BaseException | None = None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self._error = error

    def apply_async(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        if self._error is not None:
            raise self._error


async def test_celery_dispatch_enqueues_with_persisted_task_id(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/celery-dress",
        surface="ecommerce_detail",
    )
    stub = _StubTask()
    monkeypatch.setattr(celery_dispatcher_module, "_process_run_task", lambda: stub)

    run_id = int(run.id)
    returned = await CeleryRunDispatcher().dispatch(db_session, run)

    assert len(stub.calls) == 1
    _, kwargs = stub.calls[0]
    assert kwargs["args"] == [run_id]
    task_id = str(kwargs["task_id"])
    assert task_id.startswith(f"crawl-run-{run_id}-")
    # The enqueued task id is the one persisted on the run summary.
    assert str(returned.summary_dict()[CELERY_TASK_ID_KEY]) == task_id
    db_session.expire_all()
    persisted = await _reload_run(db_session, run_id)
    assert persisted.summary_dict()[CELERY_TASK_ID_KEY] == task_id


async def test_celery_dispatch_enqueue_failure_clears_task_id(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/broker-down",
        surface="ecommerce_detail",
    )
    stub = _StubTask(error=RuntimeError("broker down"))
    monkeypatch.setattr(celery_dispatcher_module, "_process_run_task", lambda: stub)

    run_id = int(run.id)
    with pytest.raises(RuntimeError, match="broker down"):
        await CeleryRunDispatcher().dispatch(db_session, run)

    # The cleared task id is committed so the run is safe to re-dispatch.
    db_session.expire_all()
    persisted = await _reload_run(db_session, run_id)
    assert CELERY_TASK_ID_KEY not in persisted.summary_dict()


async def test_celery_dispatch_rejects_terminal_run(
    db_session: AsyncSession,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/celery-finished",
        surface="ecommerce_detail",
    )
    run.status = CrawlStatus.COMPLETED.value
    await db_session.commit()
    stub = _StubTask()
    monkeypatch.setattr(celery_dispatcher_module, "_process_run_task", lambda: stub)

    with pytest.raises(ValueError, match="Cannot dispatch run in state"):
        await CeleryRunDispatcher().dispatch(db_session, run)
    assert stub.calls == []


async def test_celery_dispatch_missing_run_raises_value_error(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stub = _StubTask()
    monkeypatch.setattr(celery_dispatcher_module, "_process_run_task", lambda: stub)
    ghost = CrawlRun(id=999_999_999)

    with pytest.raises(ValueError, match="Run not found"):
        await CeleryRunDispatcher().dispatch(db_session, ghost)
    assert stub.calls == []


# ---------------------------------------------------------------------------
# workers/base: hoisted helper + protocol
# ---------------------------------------------------------------------------


async def test_load_run_with_normalized_status_round_trip(
    db_session: AsyncSession,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/normalized",
        surface="ecommerce_detail",
    )

    loaded, status = await load_run_with_normalized_status(db_session, int(run.id))

    assert int(loaded.id) == int(run.id)
    assert status is CrawlStatus.PENDING

    with pytest.raises(ValueError, match="Run not found"):
        await load_run_with_normalized_status(db_session, 999_999_999)


async def test_set_task_id_persists_and_clears_summary_key(
    db_session: AsyncSession,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/task-id",
        surface="ecommerce_detail",
    )

    set_task_id(run, "task-abc")
    await db_session.commit()
    assert run.summary_dict()[CELERY_TASK_ID_KEY] == "task-abc"

    set_task_id(run, None)
    await db_session.commit()
    assert CELERY_TASK_ID_KEY not in run.summary_dict()


def test_run_dispatcher_protocol_conformance() -> None:
    assert isinstance(LocalRunDispatcher(), RunDispatcher)
    assert isinstance(CeleryRunDispatcher(), RunDispatcher)
    assert not isinstance(object(), RunDispatcher)
