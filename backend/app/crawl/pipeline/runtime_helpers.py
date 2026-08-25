from __future__ import annotations

import logging

from app.core.database import SessionLocal
from app.models.crawl_run import CrawlLog, CrawlRun
from app.acquisition.acquirer import PageAcquisitionResult, PageEvidence
from app.crawl.state import TERMINAL_STATUSES, CrawlStatus, update_run_status
from app.core.db_utils import mapping_or_empty
from app.core.records.field_policy import normalize_requested_field
from app.core.shared.field_coerce import LONG_TEXT_FIELDS
from app.persistence.publish import VERDICT_ERROR, is_effectively_blocked
from app.core.shared.run_summary import as_int
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError


STAGE_ACQUIRE = "ACQUIRE"
STAGE_EXTRACT = "EXTRACT"
STAGE_NORMALIZE = "NORMALIZE"
STAGE_PERSIST = "PERSIST"


async def log_event(session, run_id: int | None, level: str, message: str) -> None:
    if run_id is None:
        return
    session.add(CrawlLog(run_id=run_id, level=level, message=str(message or "")))
    await session.flush()


def log_pipeline_event(
    context,
    level: str,
    message: str,
    *,
    commit: bool = True,
) -> None:
    """Queue a crawl-log row for the URL's batched persistence.

    Per-URL DB budget: log rows accumulate in the URL's session and flush with
    the URL's other work, committed once per URL by the session owner, instead
    of one flush+commit per event (~5-8 commits per URL before). ``commit`` is
    retained for call-site compatibility; events no longer force an immediate
    commit.
    """

    del commit  # events are batched; see docstring
    if not context.config.persist_logs:
        return

    url = getattr(context, "url", None)
    run = getattr(context, "run", None)
    if run is None:
        return
    # The run row no longer stores resolved_url_list while the run executes
    # (fixed-size per-URL patches); url_count is the fixed-size stand-in.
    if url and as_int(run.summary_dict().get("url_count")) > 1:
        prefixed_message = f"[url:{url}] {message}"
    else:
        prefixed_message = message

    context.session.add(
        CrawlLog(run_id=run.id, level=level, message=str(prefixed_message or ""))
    )


def pipeline_acquisition_event_logger(context):
    """Build the acquisition-stage ``on_event`` callback for a URL context."""

    async def _log(level: str, message: str) -> None:
        log_pipeline_event(context, level, message)

    return _log


async def set_stage(
    session,
    run,
    stage: str,
    *,
    current_url: str | None = None,
    current_url_index: int | None = None,
    total_urls: int | None = None,
) -> None:
    summary = run.summary_dict()
    summary["current_stage"] = stage
    if current_url is not None:
        summary["current_url"] = current_url
    if current_url_index is not None:
        summary["current_url_index"] = current_url_index
    if total_urls is not None:
        summary["url_count"] = total_urls
    run.result_summary = summary
    await session.flush()


logger = logging.getLogger(__name__)


def browser_attempted(acquisition_result: PageAcquisitionResult) -> bool:
    return PageEvidence.from_acquisition_result(acquisition_result).browser_attempted


def browser_outcome(acquisition_result: PageAcquisitionResult) -> str:
    return PageEvidence.from_acquisition_result(acquisition_result).browser_outcome


def browser_launch_log_message(acquisition_result: PageAcquisitionResult) -> str:
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    engine = (
        str(diagnostics.get("browser_engine") or "chromium").strip().lower()
        or "chromium"
    )
    launch_mode = str(diagnostics.get("browser_launch_mode") or "").strip().lower()
    if not launch_mode:
        launch_mode = "headless"
    profile = str(diagnostics.get("browser_profile") or "").strip()
    details = [engine]
    if profile:
        details.append(f"profile: {profile}")
    return f"Launched {launch_mode} browser ({', '.join(details)})"


def effective_blocked(acquisition_result: PageAcquisitionResult) -> bool:
    return is_effectively_blocked(acquisition_result)


def suppress_empty_downstream_record_logs(
    acquisition_result: PageAcquisitionResult,
    records: list[dict[str, object]],
) -> bool:
    return not records and effective_blocked(acquisition_result)


def merge_browser_diagnostics(
    acquisition_result: PageAcquisitionResult,
    diagnostics: dict[str, object],
) -> None:
    merged = mapping_or_empty(getattr(acquisition_result, "browser_diagnostics", {}))
    merged.update(dict(diagnostics or {}))
    acquisition_result.browser_diagnostics = merged


def record_detail_expansion_extraction_outcome(
    acquisition_result: PageAcquisitionResult,
    records: list[dict[str, object]],
    *,
    requested_fields: list[str],
) -> None:
    if (
        str(getattr(acquisition_result, "method", "") or "").strip().lower()
        != "browser"
    ):
        return
    browser_diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    detail_expansion = dict(
        mapping_or_empty(browser_diagnostics.get("detail_expansion"))
    )
    try:
        clicked_count = int(str(detail_expansion.get("clicked_count", 0) or 0))
    except (TypeError, ValueError):
        clicked_count = 0
    if clicked_count <= 0:
        return
    extracted_fields = _detail_expansion_extracted_fields(
        records, requested_fields=requested_fields
    )
    detail_expansion["extraction_consumed"] = bool(extracted_fields or records)
    detail_expansion["extracted_fields"] = extracted_fields
    browser_diagnostics["detail_expansion"] = detail_expansion
    acquisition_result.browser_diagnostics = browser_diagnostics


def _detail_expansion_extracted_fields(
    records: list[dict[str, object]], *, requested_fields: list[str]
) -> list[str]:
    requested = {
        normalized
        for value in requested_fields
        if (normalized := normalize_requested_field(value))
    }
    return sorted(
        {
            str(field_name).strip().lower()
            for record in records
            if isinstance(record, dict)
            for field_name, value in record.items()
            if (
                not str(field_name).startswith("_")
                and value not in (None, "", [], {})
                and (
                    not requested
                    or str(field_name).strip().lower() in requested
                    or str(field_name).strip().lower() in LONG_TEXT_FIELDS
                )
            )
        }
    )


async def mark_run_failed(session: AsyncSession, run_id: int, error_msg: str) -> None:
    try:
        await session.rollback()
    except SQLAlchemyError:
        logger.debug(
            "Session rollback failed before failure persistence", exc_info=True
        )
    try:
        await persist_failure_state(session, run_id, error_msg)
        return
    except SQLAlchemyError:
        logger.debug(
            "Original session unusable for failure recovery; falling back to SessionLocal",
            exc_info=True,
        )
    try:
        async with SessionLocal() as recovery:
            await persist_failure_state(recovery, run_id, error_msg)
    except SQLAlchemyError:
        logger.critical(
            "Failure recovery via SessionLocal failed; "
            "run may be stuck in RUNNING state (zombie run).",
            exc_info=True,
            extra={"run_id": run_id},
        )
        return


async def persist_failure_state(
    session: AsyncSession,
    run_id: int,
    error_msg: str,
) -> None:
    run = await session.get(CrawlRun, run_id)
    if run is None:
        return
    result_summary = run.summary_dict()
    run.update_summary(
        error=error_msg,
        progress=result_summary.get("progress", 0),
        extraction_verdict=VERDICT_ERROR,
    )
    if run.status_value not in TERMINAL_STATUSES:
        update_run_status(run, CrawlStatus.FAILED)
    session.add(CrawlLog(run_id=run_id, level="error", message=error_msg))
    await session.commit()
