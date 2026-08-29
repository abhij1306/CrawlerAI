from __future__ import annotations

import time
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_run import CrawlRun
from app.acquisition.acquirer import PageAcquisitionResult
from app.acquisition.runtime_plan import AcquisitionIntent
from app.core.config.runtime_settings import crawler_runtime_settings
from app.extraction.contracts import ExtractionResult
from app.crawl.pipeline.types import URLProcessingConfig


@dataclass(slots=True)
class URLProcessingContext:
    session: AsyncSession
    run: CrawlRun
    url: str
    config: URLProcessingConfig
    url_timeout_seconds: float
    started_at_monotonic: float
    requested_fields: list[str] = field(default_factory=list)
    surface: str = ""
    browser_escalation_count: int = 0
    escalation_attempts: list[dict[str, object]] = field(default_factory=list)
    # Per-URL LEARN-ONCE latch (finding 5): learning is attempted at most once per
    # URL across the HTTP pass and any browser retry, and only after the final
    # attempt. Set the first time ``_maybe_learn_once`` actually attempts learning.
    learn_once_attempted: bool = False


@dataclass(slots=True)
class FetchedURLStage:
    context: URLProcessingContext
    acquisition_result: PageAcquisitionResult
    url_metrics: dict[str, object]


@dataclass(slots=True)
class ExtractedURLStage:
    fetched: FetchedURLStage
    result: ExtractionResult


def resolve_run_param(
    plan_value: object | None,
    config_value: object | None,
    default_value: int,
    *,
    min_value: int = 1,
) -> int:
    for candidate in (plan_value, config_value):
        if candidate is None:
            continue
        try:
            resolved = int(
                float(candidate)
                if isinstance(candidate, (int, float))
                else float(str(candidate))
            )
        except (TypeError, ValueError):
            continue
        if resolved >= int(min_value):
            return resolved
    return int(default_value)


def resolved_url_processing_config(
    config: URLProcessingConfig,
    *,
    surface: str,
) -> URLProcessingConfig:
    plan = config.resolved_acquisition_plan(surface=surface)
    safety_iteration_cap = int(crawler_runtime_settings.traversal_max_iterations_cap)
    return URLProcessingConfig.from_acquisition_plan(
        AcquisitionIntent(
            surface=surface,
            proxy_list=tuple(plan.proxy_list or config.proxy_list),
            traversal_mode=plan.traversal_mode or config.traversal_mode,
            max_pages=min(
                resolve_run_param(plan.max_pages, config.max_pages, config.max_pages),
                safety_iteration_cap,
            ),
            max_scrolls=min(
                resolve_run_param(
                    plan.max_scrolls, config.max_scrolls, config.max_scrolls
                ),
                safety_iteration_cap,
            ),
            max_records=resolve_run_param(
                plan.max_records, config.max_records, config.max_records
            ),
            sleep_ms=resolve_run_param(
                plan.sleep_ms, config.sleep_ms, config.sleep_ms, min_value=0
            ),
        ),
        update_run_state=config.update_run_state,
        persist_run_events=config.persist_run_events,
        url_index=config.url_index,
        url_count=config.url_count,
        url_scope_id=config.url_scope_id,
        prefetch_only=config.prefetch_only,
        record_writer=config.record_writer,
        url_timeout_seconds=config.url_timeout_seconds,
    )


def build_url_processing_context(
    *,
    session: AsyncSession,
    run: CrawlRun,
    url: str,
    config: URLProcessingConfig,
) -> URLProcessingContext:
    settings_view = run.settings_view
    resolved_timeout = (
        float(config.url_timeout_seconds)
        if config.url_timeout_seconds is not None
        else settings_view.url_timeout_seconds()
        if settings_view.get("url_timeout_seconds") not in (None, "")
        else crawler_runtime_settings.default_url_process_timeout_seconds()
    )
    resolved_config = resolved_url_processing_config(
        config,
        surface=run.surface,
    )
    if not str(resolved_config.url_scope_id or "").strip():
        resolved_config.url_scope_id = f"url:{resolved_config.url_index}"
    return URLProcessingContext(
        session=session,
        run=run,
        url=url,
        config=resolved_config,
        url_timeout_seconds=float(resolved_timeout),
        started_at_monotonic=time.monotonic(),
        requested_fields=list(run.requested_fields or []),
        surface=run.surface,
    )
