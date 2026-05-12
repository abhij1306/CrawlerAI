"""Run dispatch strategy — resolves and dispatches crawl runs to Celery or local execution."""

from app.services.dispatch.base import RunDispatcher
from app.services.dispatch.celery_dispatcher import CeleryRunDispatcher
from app.services.dispatch.local_dispatcher import LocalRunDispatcher

__all__ = ["RunDispatcher", "CeleryRunDispatcher", "LocalRunDispatcher"]
