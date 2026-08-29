from __future__ import annotations

import logging
from collections.abc import Mapping

from app.core.database import SessionLocal
from app.models.crawl_run import CrawlRun
from app.acquisition.acquirer import PageAcquisitionResult, PageEvidence
from app.acquisition.events import AcquisitionEvent, AcquisitionEventKind
from app.core.config.run_events import RunEventKind
from app.crawl.run_events import JsonValue, RunEventFact, run_event_timeline
from app.crawl.state import TERMINAL_STATUSES, CrawlStatus, update_run_status
from app.core.db_utils import mapping_or_empty
from app.core.records.field_policy import normalize_requested_field
from app.core.shared.field_coerce import LONG_TEXT_FIELDS
from app.persistence.publish import VERDICT_ERROR, is_effectively_blocked
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError


STAGE_ACQUIRE = "ACQUIRE"
STAGE_EXTRACT = "EXTRACT"
STAGE_NORMALIZE = "NORMALIZE"
STAGE_PERSIST = "PERSIST"


async def record_pipeline_event(
    context,
    *,
    kind: RunEventKind,
    reason_code: str | None = None,
    facts: Mapping[str, JsonValue] | None = None,
) -> None:
    config = getattr(context, "config", None)
    if config is None or not config.persist_run_events:
        return
    url = getattr(context, "url", None)
    run = getattr(context, "run", None)
    if run is None or not url:
        return
    scope = str(getattr(config, "url_scope_id", "") or "").strip()
    if not scope:
        scope = f"url:{max(1, int(getattr(config, 'url_index', 1) or 1))}"
    await run_event_timeline.record(
        run_id=run.id,
        fact=RunEventFact(
            kind=kind,
            url=str(url),
            url_scope_id=scope,
            reason_code=reason_code,
            facts=dict(facts or {}),
        ),
    )


def pipeline_acquisition_event_logger(context):
    """Build the acquisition-stage ``on_event`` callback for a URL context."""

    async def _record(event: AcquisitionEvent) -> None:
        kind, facts = _run_event_from_acquisition_event(event)
        await record_pipeline_event(
            context,
            kind=kind,
            reason_code=event.reason_code,
            facts=facts,
        )

    return _record


_ACQUISITION_RUN_EVENT_KINDS: dict[AcquisitionEventKind, RunEventKind] = {
    AcquisitionEventKind.STARTED: RunEventKind.ACQUISITION_STARTED,
    AcquisitionEventKind.STRATEGY_SELECTED: RunEventKind.ACQUISITION_STRATEGY_SELECTED,
    AcquisitionEventKind.HTTP_ATTEMPTED: RunEventKind.ACQUISITION_HTTP_ATTEMPTED,
    AcquisitionEventKind.HTTP_FAILED: RunEventKind.ACQUISITION_HTTP_FAILED,
    AcquisitionEventKind.BROWSER_LAUNCHED: RunEventKind.ACQUISITION_BROWSER_LAUNCHED,
    AcquisitionEventKind.BROWSER_PAGE_LOADED: RunEventKind.ACQUISITION_BROWSER_PAGE_LOADED,
    AcquisitionEventKind.BROWSER_FIRST_FALLBACK: RunEventKind.ACQUISITION_BROWSER_FIRST_FALLBACK,
    AcquisitionEventKind.BROWSER_ESCALATED: RunEventKind.ACQUISITION_BROWSER_ESCALATED,
    AcquisitionEventKind.PROTECTION_DETECTED: RunEventKind.ACQUISITION_PROTECTION_DETECTED,
    AcquisitionEventKind.POPUP_CLOSED: RunEventKind.ACQUISITION_POPUP_CLOSED,
    AcquisitionEventKind.BROWSER_INTERSTITIAL_DISMISSED: RunEventKind.ACQUISITION_INTERSTITIAL_DISMISSED,
    AcquisitionEventKind.TRAVERSAL_DETECTED: RunEventKind.TRAVERSAL_DETECTED,
    AcquisitionEventKind.TRAVERSAL_PROGRESSED: RunEventKind.TRAVERSAL_PROGRESS,
    AcquisitionEventKind.TRAVERSAL_SETTLED: RunEventKind.TRAVERSAL_SETTLED,
    AcquisitionEventKind.TRAVERSAL_RECOVERY_STARTED: RunEventKind.TRAVERSAL_RECOVERY_STARTED,
    AcquisitionEventKind.TRAVERSAL_COMPLETED: RunEventKind.TRAVERSAL_COMPLETED,
}


def _run_event_from_acquisition_event(
    event: AcquisitionEvent,
) -> tuple[RunEventKind, dict[str, JsonValue]]:
    facts: dict[str, JsonValue] = dict(event.facts)
    if event.kind == AcquisitionEventKind.STARTED:
        facts = {}
    elif event.kind == AcquisitionEventKind.STRATEGY_SELECTED:
        facts["strategy"] = facts.pop("fetch_mode")
        if event.reason_code:
            facts["reason"] = event.reason_code
    elif event.kind == AcquisitionEventKind.BROWSER_ESCALATED:
        facts["prior_method"] = facts.pop("method")
        if event.reason_code:
            facts["reason"] = event.reason_code
    elif event.kind == AcquisitionEventKind.TRAVERSAL_PROGRESSED:
        facts["previous_count"] = facts.pop("previous_card_count")
        facts["current_count"] = facts.pop("current_card_count")
    elif event.kind == AcquisitionEventKind.TRAVERSAL_SETTLED:
        facts = {
            "previous_count": facts["previous_card_count"],
            "record_count": facts["current_card_count"],
        }
    elif event.kind == AcquisitionEventKind.TRAVERSAL_COMPLETED:
        facts["record_count"] = facts.pop("card_count")
        facts["progress_count"] = facts.pop("progress_event_count")
    return _ACQUISITION_RUN_EVENT_KINDS[event.kind], facts


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


def effective_blocked(acquisition_result: PageAcquisitionResult) -> bool:
    return is_effectively_blocked(acquisition_result)


def suppress_empty_downstream_record_events(
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


async def mark_run_failed(
    session: AsyncSession,
    run_id: int,
    error_msg: str,
    *,
    exception_type: str | None = None,
) -> None:
    try:
        await session.rollback()
    except SQLAlchemyError:
        logger.debug(
            "Session rollback failed before failure persistence", exc_info=True
        )
    try:
        await persist_failure_state(
            session, run_id, error_msg, exception_type=exception_type
        )
        return
    except SQLAlchemyError:
        logger.debug(
            "Original session unusable for failure recovery; falling back to SessionLocal",
            exc_info=True,
        )
    try:
        async with SessionLocal() as recovery:
            await persist_failure_state(
                recovery, run_id, error_msg, exception_type=exception_type
            )
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
    *,
    exception_type: str | None = None,
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
    failure_type = str(exception_type or "").strip() or "Error"
    await run_event_timeline.record(
        run_id=run_id,
        fact=RunEventFact(
            kind=RunEventKind.RUN_FAILED,
            facts={"exception_type": failure_type},
        ),
        session=session,
    )
    await session.commit()
