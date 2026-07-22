from __future__ import annotations

import logging
from importlib import import_module
from types import SimpleNamespace

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


from app.core.config import settings
from app.core.config.runtime_settings import crawler_runtime_settings
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
