from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from app.models.crawl_run import CrawlRun
from app.crawl.pipeline.types import URLProcessingResult
from app.persistence.publish import VERDICT_ERROR
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class URLProcessingDeadlineExceeded(TimeoutError):
    pass


async def run_url_processing_with_timeout(operation, timeout_seconds: float):
    deadline = asyncio.timeout(max(0.001, float(timeout_seconds)))
    try:
        async with deadline:
            return await operation
    except TimeoutError as exc:
        if not deadline.expired():
            raise
        raise URLProcessingDeadlineExceeded(
            f"URL processing exceeded timeout_seconds={timeout_seconds}"
        ) from exc


async def rollback_url_session(session: AsyncSession, *, context: str) -> bool:
    try:
        await session.rollback()
        session.expire_all()
        return True
    except Exception:
        logger.debug("Session rollback failed during %s", context, exc_info=True)
        return False


async def recover_url_failure(
    session: AsyncSession,
    *,
    session_factory,
    persist_failure_log: Callable[..., Awaitable[CrawlRun]],
    run: CrawlRun | None = None,
    run_id: int,
    url: str,
    exc: BaseException,
    log_message: str,
) -> tuple[CrawlRun, URLProcessingResult]:
    await rollback_url_session(session, context="URL failure recovery")
    if run is not None:
        try:
            session.expire(run)
            await session.refresh(run)
        except Exception:
            logger.debug(
                "Failed to refresh run during URL failure recovery", exc_info=True
            )
            await rollback_url_session(session, context="failed run refresh recovery")
    recovery_error: Exception | None = None
    try:
        run = await persist_failure_log(
            session,
            run_id=run_id,
            url=url,
            exc=exc,
            log_message=log_message,
        )
    except Exception as original_session_error:
        recovery_error = original_session_error
        logger.debug(
            "Original session unusable for URL failure recovery; falling back to SessionLocal",
            exc_info=True,
        )
        await rollback_url_session(session, context="before URL recovery fallback")
        try:
            async with session_factory() as recovery:
                await persist_failure_log(
                    recovery,
                    run_id=run_id,
                    url=url,
                    exc=exc,
                    log_message=log_message,
                )
        except Exception as fallback_error:
            recovery_error = fallback_error
            logger.exception(
                "Failed to persist URL failure log for run=%s url=%s",
                run_id,
                url,
            )
        await rollback_url_session(session, context="after URL recovery fallback")
        try:
            reloaded_run = await session.get(CrawlRun, run_id, populate_existing=True)
        except Exception as reload_error:
            logger.debug(
                "Failed to reload run after URL failure recovery; keeping current instance",
                exc_info=True,
            )
            await rollback_url_session(session, context="after reload failure")
            if run is None:
                raise RuntimeError(
                    f"Original session unusable after URL failure recovery for run {run_id}"
                ) from reload_error
        else:
            if reloaded_run is not None:
                run = reloaded_run
    if run is None:
        raise RuntimeError(f"Run {run_id} disappeared after URL failure") from exc
    metrics = _url_failure_metrics(exc)
    if recovery_error is not None:
        metrics["failure_log_persistence_error"] = (
            f"{type(recovery_error).__name__}: {recovery_error}"
        )
        metrics["failure_log_persisted"] = False
    return run, URLProcessingResult(
        records=[],
        verdict=VERDICT_ERROR,
        url_metrics=metrics,
    )


def _url_failure_metrics(exc: BaseException) -> dict[str, object]:
    metrics: dict[str, object] = {"error": f"{type(exc).__name__}: {exc}"}
    browser_diagnostics = getattr(exc, "browser_diagnostics", None)
    if not isinstance(browser_diagnostics, dict):
        return metrics
    diagnostics = dict(browser_diagnostics)
    metrics["browser_diagnostics"] = diagnostics
    for key in ("failure_reason", "browser_outcome"):
        value = str(diagnostics.get(key) or "").strip()
        if value:
            metrics[key] = value
    if diagnostics.get("browser_attempted") is not None:
        metrics["browser_attempted"] = bool(diagnostics.get("browser_attempted"))
    return metrics
