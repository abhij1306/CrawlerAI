from __future__ import annotations

from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawl.utils import normalize_target_url
from app.models.crawl_run import CrawlRun, CrawlUrlResult


DEFAULT_EXTRACTION_VERSION = "extraction.v1"


def normalized_result_url(url: str) -> str:
    normalized = normalize_target_url(url)
    return normalized or str(url or "").strip()


def acquisition_outcome(acquisition_result: Any) -> str:
    diagnostics = _mapping(getattr(acquisition_result, "browser_diagnostics", {}))
    if bool(diagnostics.get("blocked") or diagnostics.get("hard_blocked")):
        return "blocked"
    if bool(getattr(acquisition_result, "blocked", False)):
        return "blocked"
    status_code = getattr(acquisition_result, "status_code", None)
    if isinstance(status_code, int) and status_code >= 500:
        return "error"
    if not str(getattr(acquisition_result, "html", "") or "").strip():
        return "empty"
    return "success"


def url_result_values(
    *,
    run: CrawlRun,
    requested_url: str,
    acquisition_result: Any,
    extraction_result: Any,
    record_count: int,
    generation: int = 1,
    manifest_uri: str | None = None,
    extraction_version: str = DEFAULT_EXTRACTION_VERSION,
) -> dict[str, Any]:
    final_url = str(getattr(acquisition_result, "final_url", "") or requested_url)
    return {
        "run_id": run.id,
        "requested_url": str(requested_url or ""),
        "normalized_url": normalized_result_url(requested_url),
        "final_url": final_url,
        "surface": str(run.surface or ""),
        "generation": int(generation or 1),
        "acquisition_outcome": acquisition_outcome(acquisition_result),
        "verdict": str(getattr(extraction_result, "verdict", "") or "empty"),
        "extraction_version": extraction_version,
        "bundle_id": getattr(extraction_result, "bundle_id", None),
        "manifest_uri": manifest_uri,
        "record_count": int(record_count or 0),
        "error": _error_text(acquisition_result, extraction_result),
    }


async def upsert_url_result(
    session: AsyncSession,
    *,
    run: CrawlRun,
    requested_url: str,
    acquisition_result: Any,
    extraction_result: Any,
    record_count: int,
    generation: int = 1,
    manifest_uri: str | None = None,
    extraction_version: str = DEFAULT_EXTRACTION_VERSION,
) -> CrawlUrlResult:
    values = url_result_values(
        run=run,
        requested_url=requested_url,
        acquisition_result=acquisition_result,
        extraction_result=extraction_result,
        record_count=record_count,
        generation=generation,
        manifest_uri=manifest_uri,
        extraction_version=extraction_version,
    )
    row = await _find_url_result(
        session,
        run_id=int(values["run_id"]),
        normalized_url=str(values["normalized_url"]),
        surface=str(values["surface"]),
        generation=int(values["generation"]),
    )
    if row is None:
        row = CrawlUrlResult(**values)
        session.add(row)
    else:
        for key, value in values.items():
            setattr(row, key, value)
    await session.flush()
    return row


async def _find_url_result(
    session: AsyncSession,
    *,
    run_id: int,
    normalized_url: str,
    surface: str,
    generation: int,
) -> CrawlUrlResult | None:
    return await session.scalar(
        select(CrawlUrlResult).where(
            CrawlUrlResult.run_id == run_id,
            CrawlUrlResult.normalized_url == normalized_url,
            CrawlUrlResult.surface == surface,
            CrawlUrlResult.generation == generation,
        )
    )


def _error_text(acquisition_result: Any, extraction_result: Any) -> str | None:
    error = getattr(extraction_result, "error", None) or getattr(
        acquisition_result, "error", None
    )
    if error in (None, ""):
        return None
    return str(error)


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}
