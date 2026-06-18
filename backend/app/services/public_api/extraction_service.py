from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public.common import PublicApiError
from app.models.crawl_run import CrawlRecord
from app.schemas.public_api import PublicExtractRequest
from app.services.config.public_api import (
    PUBLIC_API_DEFAULT_FIELDS_BY_SURFACE,
    PUBLIC_API_ERROR_BOT_BLOCK,
    PUBLIC_API_ERROR_BROWSER_REQUIRED,
    PUBLIC_API_ERROR_EXTRACTION_FAILED,
    PUBLIC_API_ERROR_INVALID_FIELD,
    PUBLIC_API_ERROR_INVALID_SURFACE,
    PUBLIC_API_ERROR_INVALID_URL,
    PUBLIC_API_ERROR_TIMEOUT,
    PUBLIC_API_ERROR_URL_UNREACHABLE,
    PUBLIC_API_FIELD_ALIASES,
)
from app.services.crawl.crud import create_crawl_run
from app.services.crawl.state import CrawlStatus, update_run_status
from app.services.field_policy import canonical_fields_for_surface, normalize_field_key
from app.services.pipeline.extraction_loop import process_single_url
from app.services.pipeline.runtime_helpers import log_event, mark_run_failed
from app.services.pipeline.types import URLProcessingConfig
from app.services.platform_policy import resolve_platform_runtime_policy
from app.services.publish import VERDICT_BLOCKED, VERDICT_ERROR, VERDICT_EMPTY
from app.services.surface_resolver import (
    SurfaceResolution,
    public_surface_for_internal,
    resolve_public_surface,
)


async def extract_public_product(
    session: AsyncSession,
    *,
    user_id: int,
    payload: PublicExtractRequest,
) -> dict[str, Any]:
    url = _validate_url(payload.url)
    surface_resolution = _internal_surface(payload.surface, url=url)
    surface = surface_resolution.surface
    if _platform_requires_browser(url, surface):
        raise PublicApiError(
            PUBLIC_API_ERROR_BROWSER_REQUIRED,
            "This domain requires browser rendering, which is not enabled in public API v1.",
            status_code=422,
        )
    requested_fields = _public_requested_fields(payload.fields, surface=surface)
    run = await create_crawl_run(
        session,
        user_id,
        {
            "run_type": "crawl",
            "url": url,
            "surface": surface,
            "requested_fields": requested_fields,
            "settings": _public_http_only_settings(
                payload.options.max_wait_seconds,
                surface_resolution=surface_resolution.as_dict(),
            ),
        },
    )
    update_run_status(run, CrawlStatus.RUNNING)
    await log_event(session, run.id, "info", "Starting public HTTP-only extraction")
    await session.commit()

    try:
        config = URLProcessingConfig.from_acquisition_plan(
            run.settings_view.acquisition_plan(surface=surface, max_records=1),
            update_run_state=True,
            persist_logs=True,
        )
        result = await asyncio.wait_for(
            process_single_url(session=session, run=run, url=url, config=config),
            timeout=float(payload.options.max_wait_seconds),
        )
    except TimeoutError as exc:
        await mark_run_failed(
            session,
            run.id,
            f"Public extraction timed out after {payload.options.max_wait_seconds}s",
        )
        raise PublicApiError(
            PUBLIC_API_ERROR_TIMEOUT,
            "Extraction timed out.",
            status_code=504,
        ) from exc
    except ValueError as exc:
        await mark_run_failed(session, run.id, str(exc))
        raise PublicApiError(
            PUBLIC_API_ERROR_URL_UNREACHABLE,
            str(exc),
            status_code=422,
        ) from exc
    except Exception as exc:
        await mark_run_failed(session, run.id, f"{type(exc).__name__}: {exc}")
        raise PublicApiError(
            PUBLIC_API_ERROR_EXTRACTION_FAILED,
            "Extraction failed.",
            status_code=500,
            details={"error_type": type(exc).__name__},
        ) from exc

    try:
        verdict = str(getattr(result, "verdict", "") or "")
        metrics = dict(getattr(result, "url_metrics", {}) or {})
        if _browser_was_required(metrics):
            raise PublicApiError(
                PUBLIC_API_ERROR_BROWSER_REQUIRED,
                "This URL requires browser rendering.",
                status_code=422,
            )
        if verdict == VERDICT_BLOCKED or bool(metrics.get("blocked")):
            raise PublicApiError(
                PUBLIC_API_ERROR_BOT_BLOCK,
                "Target blocked HTTP acquisition.",
                status_code=403,
            )
        if verdict in {VERDICT_ERROR, VERDICT_EMPTY}:
            raise PublicApiError(
                PUBLIC_API_ERROR_EXTRACTION_FAILED,
                "No public product record was extracted.",
                status_code=422,
            )

        record = await _first_record(session, run_id=int(run.id))
        if record is None:
            raise PublicApiError(
                PUBLIC_API_ERROR_EXTRACTION_FAILED,
                "No public product record was extracted.",
                status_code=422,
            )
    except PublicApiError as exc:
        await mark_run_failed(session, run.id, exc.message)
        raise
    update_run_status(run, CrawlStatus.COMPLETED)
    await session.commit()
    return _shape_record_response(
        record,
        requested_fields=requested_fields,
        surface=surface,
    )


def _validate_url(value: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise PublicApiError(
            PUBLIC_API_ERROR_INVALID_URL,
            "Only absolute http:// and https:// URLs are supported.",
            status_code=422,
        )
    return url


def _internal_surface(value: str, *, url: str) -> SurfaceResolution:
    resolution = resolve_public_surface(value, url=url)
    if resolution is None:
        raise PublicApiError(
            PUBLIC_API_ERROR_INVALID_SURFACE,
            "Unsupported public extraction surface.",
            status_code=422,
        )
    return resolution


def _public_requested_fields(values: list[str], *, surface: str) -> list[str]:
    public_fields = list(
        values
        or PUBLIC_API_DEFAULT_FIELDS_BY_SURFACE.get(
            surface,
            canonical_fields_for_surface(surface),
        )
    )
    allowed = set(canonical_fields_for_surface(surface))
    normalized: list[str] = []
    for original in public_fields:
        key = normalize_field_key(original)
        canonical = PUBLIC_API_FIELD_ALIASES.get(key, key)
        if canonical not in allowed:
            raise PublicApiError(
                PUBLIC_API_ERROR_INVALID_FIELD,
                f"Field is not supported for {public_surface_for_internal(surface)} extraction: {original}",
                status_code=422,
                details={"field": original},
            )
        if canonical not in normalized:
            normalized.append(canonical)
    return normalized


def _public_http_only_settings(
    max_wait_seconds: int,
    *,
    surface_resolution: dict[str, object],
) -> dict[str, Any]:
    return {
        "max_records": 1,
        "respect_robots_txt": False,
        "llm_enabled": False,
        "url_timeout_seconds": max_wait_seconds,
        "fetch_profile": {
            "fetch_mode": "http_only",
            "extraction_source": "raw_html",
            "js_mode": "off",
            "include_iframes": False,
            "traversal_mode": None,
            "request_delay_ms": 0,
            "max_pages": 1,
            "max_scrolls": 1,
        },
        "diagnostics_profile": {
            "capture_html": False,
            "capture_screenshot": False,
            "capture_network": "off",
            "capture_response_headers": True,
            "capture_browser_diagnostics": False,
        },
        "acquisition_contract": {
            "preferred_browser_engine": "auto",
            "prefer_browser": False,
            "handoff_eligible": False,
            "handoff_cookie_engine": "auto",
            "required_rendering": False,
            "required_traversal": False,
            "required_network_payloads": False,
            "stale_after_failures": {"failure_count": 0, "stale": False},
        },
        "public_api": True,
        "surface_resolution": surface_resolution,
        "use_cache": "noop_v1",
    }


def _platform_requires_browser(url: str, surface: str) -> bool:
    policy = resolve_platform_runtime_policy(url, surface=surface)
    return bool(policy.get("requires_browser"))


def _browser_was_required(metrics: dict[str, Any]) -> bool:
    diagnostics = metrics.get("browser_diagnostics")
    if isinstance(diagnostics, dict) and diagnostics.get("browser_attempted"):
        return True
    failure_reason = str(metrics.get("failure_reason") or metrics.get("browser_outcome") or "")
    return "render" in failure_reason.lower() or "browser" in failure_reason.lower()


async def _first_record(session: AsyncSession, *, run_id: int) -> CrawlRecord | None:
    result = await session.execute(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == run_id)
        .order_by(CrawlRecord.created_at.asc(), CrawlRecord.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


def _shape_record_response(
    record: CrawlRecord,
    *,
    requested_fields: list[str],
    surface: str,
) -> dict[str, Any]:
    data = dict(record.data or {})
    fields = {field: data.get(field) for field in requested_fields if field in data}
    source_trace = dict(record.source_trace or {})
    crawl_method = _crawl_method(record, source_trace=source_trace)
    return {
        "url": record.source_url,
        "surface": public_surface_for_internal(surface),
        "extracted_at": record.created_at or datetime.now(UTC),
        "crawl_method": crawl_method,
        "fields": fields,
    }


def _crawl_method(record: CrawlRecord, *, source_trace: dict[str, Any]) -> str:
    for payload in (
        source_trace,
        dict(record.discovered_data or {}),
        dict(record.raw_data or {}),
    ):
        for key in ("crawl_method", "fetch_method", "acquisition_method", "method"):
            value = str(payload.get(key) or "").strip().lower()
            if value:
                return value
    return "http"
