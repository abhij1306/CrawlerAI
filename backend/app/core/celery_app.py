from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable, Coroutine, Mapping
from datetime import datetime
from importlib import import_module
from types import SimpleNamespace
from typing import Any, Protocol

try:
    from celery import Celery  # type: ignore[import-untyped]
except (
    ModuleNotFoundError
):  # pragma: no cover - exercised only when Celery is not installed locally.

    class Celery:  # type: ignore[no-redef]
        def __init__(self, *_args, **_kwargs) -> None:
            self.conf: dict[str, object] = {}
            self.control = SimpleNamespace(revoke=lambda *_args, **_kwargs: None)

        def task(self, *dargs, **dkwargs):
            def _decorate(func):
                func.app = self
                func.apply_async = lambda *_args, **_kwargs: None
                func.delay = lambda *_args, **_kwargs: None
                func.name = dkwargs.get("name", func.__name__)
                return func

            if dargs and callable(dargs[0]) and len(dargs) == 1 and not dkwargs:
                return _decorate(dargs[0])
            return _decorate


from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.config.runtime_settings import (
    CELERY_TASK_ID_KEY,
    crawler_runtime_settings,
)
from app.core.logfire_integration import instrument_celery

logger = logging.getLogger(__name__)


def _broker_visibility_timeout_seconds() -> int:
    """Redis broker visibility timeout for late-ack crawl tasks.

    Must comfortably exceed the hard task wall limit, otherwise a long run is
    redelivered while the first execution is still alive. Defaults to 2x
    job_max_wall_seconds; CELERY_BROKER_VISIBILITY_TIMEOUT_SECONDS may only
    raise it further.
    """
    wall_seconds = max(1, int(crawler_runtime_settings.job_max_wall_seconds))
    configured = max(0, int(settings.celery_broker_visibility_timeout_seconds or 0))
    return max(configured, 2 * wall_seconds)


celery_app = Celery(
    "crawlerai",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks"],
)

celery_app.conf.update(
    accept_content=["json"],
    task_serializer="json",
    result_serializer="json",
    enable_utc=True,
    timezone="UTC",
    task_track_started=True,
    broker_connection_retry_on_startup=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_transport_options={
        "visibility_timeout": _broker_visibility_timeout_seconds(),
    },
)
celery_app.conf.beat_schedule = {
    # 2.14: daily retention sweep of runs/{run_id}/ artifact trees (seconds).
    "maintenance-sweep-run-artifacts-daily": {
        "task": "maintenance.sweep_run_artifacts",
        "schedule": 86_400.0,
    },
}
instrument_celery()


# Result-backend states in which a task may still be queued or executing.
# PENDING also covers unknown task ids (result expired or never recorded), so
# callers should combine it with a staleness check before declaring a job
# orphaned. Anything else (SUCCESS/FAILURE/REVOKED) means the task is over.
CELERY_UNREADY_STATES = frozenset({"PENDING", "RECEIVED", "STARTED", "RETRY"})


def celery_task_state(task_id: str) -> str | None:
    """Best-effort result-backend state for a task id (None when unavailable).

    Returns None when Celery or the result backend is unavailable so callers
    can stay conservative and avoid false orphan recoveries.
    """
    try:
        return str(celery_app.AsyncResult(task_id).state)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.debug("Celery state lookup failed for task %s", task_id, exc_info=True)
        return None


class CeleryJobRow(Protocol):
    """Structural row shared by the Celery-dispatched job models.

    Member types mirror the concrete ``Mapped[...]`` columns on the job
    models exactly, since Protocol attributes are invariant.
    """

    id: int
    status: str
    completed_at: datetime | None
    summary: dict[str, Any]


def celery_task_id_of(summary: object) -> str:
    """Celery task id recorded on a job summary dict ("" when absent)."""
    if not isinstance(summary, Mapping):
        return ""
    return str(summary.get(CELERY_TASK_ID_KEY) or "")


def celery_task_is_gone(
    summary: object,
    *,
    exclude_task_id: str | None,
    stale: bool,
    pending_stale: bool | None = None,
    task_state: Callable[[str], str | None] = celery_task_state,
) -> bool:
    """True when a running job has no live Celery task behind it."""
    task_id = celery_task_id_of(summary)
    if not task_id:
        # Legacy BackgroundTasks row or in-process fallback: no task to check,
        # so only a row stale beyond the orphan window is safe to recover.
        return stale
    if exclude_task_id is not None and task_id == exclude_task_id:
        return False
    state = task_state(task_id)
    if state is None:
        # Result backend unavailable: stay conservative, never fail live work.
        return False
    if state not in CELERY_UNREADY_STATES:
        # Task finished (or was revoked) but the job was never finalized.
        return True
    if state == "PENDING":
        # PENDING covers lost/expired task records AND tasks legitimately
        # waiting in the broker queue (worker backlog). A queued task that is
        # merely stale past the normal orphan window may still run, so require
        # the longer pending window when provided. STARTED/RETRY/RECEIVED mean
        # a worker holds the task.
        return stale if pending_stale is None else pending_stale
    return False


async def enqueue_celery_job(
    session: AsyncSession,
    job: CeleryJobRow,
    *,
    task: Any,
    task_id: str,
    label: str,
) -> bool:
    """Record ``task_id`` on the job row and enqueue its Celery task.

    True when the broker accepted the task. On enqueue failure the recorded id
    is stripped again and False returned so the caller can fall back to
    in-process execution.
    """
    job.summary = {**dict(job.summary or {}), CELERY_TASK_ID_KEY: task_id}
    await session.commit()
    try:
        task.apply_async(args=[int(job.id)], task_id=task_id)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.exception(
            "Celery enqueue failed for %s job %s; falling back to in-process execution",
            label,
            job.id,
        )
        job.summary = {
            key: value
            for key, value in dict(job.summary or {}).items()
            if key != CELERY_TASK_ID_KEY
        }
        await session.commit()
        return False
    return True


_IN_PROCESS_JOB_TASKS: set[asyncio.Task[None]] = set()


def start_in_process_job(coro: Coroutine[object, object, None]) -> None:
    """Run a job coroutine as an in-process asyncio task (local-dev fallback).

    The registry holds a strong reference until completion so the task is not
    garbage-collected mid-run.
    """
    task = asyncio.create_task(coro)
    _IN_PROCESS_JOB_TASKS.add(task)
    task.add_done_callback(_IN_PROCESS_JOB_TASKS.discard)


def mark_celery_job_failed(
    job: CeleryJobRow, *, failed_status: str, now: datetime, error: str
) -> None:
    """Terminal failure stamp on a job row (status + error/recovered_at summary)."""
    job.status = failed_status
    job.completed_at = now
    job.summary = {
        **dict(job.summary or {}),
        "error": error,
        "recovered_at": now.isoformat(),
    }


# Celery worker lifecycle signals
try:
    from celery.signals import worker_process_init, worker_process_shutdown
except ImportError:
    # Stub signals when Celery is not installed
    worker_process_init = SimpleNamespace(connect=lambda func: func)  # type: ignore[assignment]
    worker_process_shutdown = SimpleNamespace(connect=lambda func: func)  # type: ignore[assignment]

# Beat stores task names, but workers still need these tasks registered on app import.
import_module("app.tasks")

# Re-exported for app.tasks, which binds the worker lifecycle hooks via
# ``@worker_process_init.connect`` / ``@worker_process_shutdown.connect``. Listed
# in __all__ so these names are recognized as intentional public re-exports.
__all__ = [
    "CELERY_UNREADY_STATES",
    "celery_app",
    "celery_task_state",
    "worker_process_init",
    "worker_process_shutdown",
]
