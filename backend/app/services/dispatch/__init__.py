"""Run dispatch strategy — resolves and dispatches crawl runs to Celery or local execution."""

from app.services.dispatch.base import RunDispatcher

__all__ = ["RunDispatcher"]
