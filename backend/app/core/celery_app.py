from __future__ import annotations

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
from app.services.config.monitor_settings import (
    SCHEDULER_DRIVER_CELERY,
    SCHEDULER_POLL_INTERVAL_SECONDS,
)

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
)

# Celery worker lifecycle signals
try:
    from celery.signals import worker_process_init, worker_process_shutdown
except ImportError:
    # Stub signals when Celery is not installed
    worker_process_init = SimpleNamespace(connect=lambda func: func)  # type: ignore[assignment]
    worker_process_shutdown = SimpleNamespace(connect=lambda func: func)  # type: ignore[assignment]

# Beat stores task names, but workers still need these tasks registered on app import.
import_module("app.tasks")

if settings.scheduler_driver == SCHEDULER_DRIVER_CELERY:
    celery_app.conf.beat_schedule = {
        "monitor-check-due": {
            "task": "monitor.check_due_jobs",
            "schedule": float(SCHEDULER_POLL_INTERVAL_SECONDS),
        },
        "monitor-purge": {
            "task": "monitor.purge_expired_snapshots",
            "schedule": 86400.0,
        },
    }

# Re-exported for app.tasks, which binds the worker lifecycle hooks via
# ``@worker_process_init.connect`` / ``@worker_process_shutdown.connect``. Listed
# in __all__ so these names are recognized as intentional public re-exports.
__all__ = [
    "celery_app",
    "worker_process_init",
    "worker_process_shutdown",
]
