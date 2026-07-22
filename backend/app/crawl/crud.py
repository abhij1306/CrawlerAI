from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.telemetry import generate_correlation_id, get_correlation_id
from app.models.crawl_run import CrawlLog, CrawlRecord, CrawlRun
from app.models.crawl_settings import CrawlRunSettings
from app.crawl.events import append_log_event
from app.core.config.domain_profiles import (
    INVALID_SURFACE_VALUES,
    SURFACE_VALIDATION_ERROR,
)
from app.extraction.surfaces import parse_surface
from app.crawl.pipeline.runtime_helpers import STAGE_ACQUIRE
from app.crawl.profile import (
    merge_saved_run_profile,
    load_domain_run_profile,
)
from app.core.domain_utils import normalize_domain
from app.persistence.publish import (
    load_domain_requested_fields,
)
from app.crawl.state import ACTIVE_STATUSES, CrawlStatus
from app.models.crawl_settings import normalize_crawl_settings
from app.crawl.utils import (
    collect_target_urls,
    normalize_target_url,
    validate_extraction_contract,
)
from app.core.db_utils import escape_like_pattern
from app.core.records.field_policy import normalize_field_key, preserve_requested_fields
from app.connectors.llm.config_service import snapshot_active_configs
from app.persistence.extraction_memory import create_release_snapshot
from app.core.records.normalizers import normalize_value
from app.core.url_safety import ensure_public_crawl_targets, ensure_valid_proxy_endpoints
from app.persistence.artifacts import ArtifactRepository
from app.schemas.crawl import enforce_run_url_limit
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def create_crawl_run(
    session: AsyncSession, user_id: int, payload: dict
) -> CrawlRun:
    payload = dict(payload or {})
    payload["url"] = normalize_target_url(payload.get("url"))
    payload["urls"] = [
        normalize_target_url(value) for value in (payload.get("urls") or [])
    ]
    urls = [value for value in (payload.get("urls") or []) if value]
    primary_url = payload.get("url") or (urls[0] if urls else "")
    normalized_surface = str(payload.get("surface") or "").strip().lower()
    settings_payload = dict(payload.get("settings") or {})
    run_type = payload.get("run_type")
    if not run_type:
        raise ValueError("run_type is required")
    if not normalized_surface:
        raise ValueError("surface is required")
    if normalized_surface in INVALID_SURFACE_VALUES:
        raise ValueError(SURFACE_VALIDATION_ERROR)
    normalized_surface = parse_surface(normalized_surface).value
    if run_type == "crawl" and primary_url:
        saved_profile_record = await load_domain_run_profile(
            session,
            domain=normalize_domain(primary_url),
            surface=normalized_surface,
        )
        if saved_profile_record is not None:
            settings_payload = merge_saved_run_profile(
                settings_payload,
                saved_profile_record.profile,
                ignore_default_equivalent_values=False,
            )
    settings = normalize_crawl_settings(settings_payload)
    settings_view = CrawlRunSettings.from_value(settings)
    if run_type == "batch" and urls:
        settings = settings_view.with_updates(urls=urls).as_dict()
        settings_view = CrawlRunSettings.from_value(settings)
    final_run_urls = settings_view.urls()
    if final_run_urls:
        # Enforce the run URL cap on the FINAL settings payload too: the
        # CrawlCreate schema validator only sees the top-level urls field, so
        # settings.urls was a cap-bypass path for oversized batches.
        enforce_run_url_limit(list(final_run_urls))
    await ensure_public_crawl_targets(collect_target_urls(payload, settings_view))
    await ensure_valid_proxy_endpoints(settings_view.proxy_list())
    validate_extraction_contract(settings_view.extraction_contract())
    domain_requested_fields = await load_domain_requested_fields(
        session, url=primary_url, surface=normalized_surface
    )
    requested_fields = preserve_requested_fields(
        [
            *domain_requested_fields,
            *(payload.get("requested_fields") or []),
            *(payload.get("additional_fields") or []),
        ]
    )
    if domain_requested_fields:
        settings = settings_view.with_updates(
            domain_requested_fields=domain_requested_fields
        ).as_dict()
        settings_view = CrawlRunSettings.from_value(settings)
    settings = settings_view.with_updates(
        requested_fields=requested_fields,
        llm_config_snapshot=await snapshot_active_configs(session),
    ).as_dict()
    run = CrawlRun(
        user_id=user_id,
        run_type=run_type,
        url=primary_url,
        surface=normalized_surface,
        status=CrawlStatus.PENDING.value,
        settings=settings,
        requested_fields=requested_fields,
        result_summary={
            "url_count": max(1, len(urls)),
            "progress": 0,
            "current_stage": STAGE_ACQUIRE,
            "correlation_id": get_correlation_id() or generate_correlation_id(),
        },
    )
    session.add(run)
    await session.flush()
    release = await create_release_snapshot(
        session,
        run_id=run.id,
        domain=normalize_domain(primary_url),
        surface=normalized_surface,
    )
    run.extraction_release_snapshot_id = release.id
    await session.commit()
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    page: int,
    limit: int,
    status: str = "",
    run_type: str = "",
    url_search: str = "",
    user_id: int | None = None,
) -> tuple[list[CrawlRun], int]:
    page = max(1, page)
    query = select(CrawlRun)
    if user_id is not None:
        query = query.where(CrawlRun.user_id == user_id)
    if status:
        query = query.where(CrawlRun.status == status)
    if run_type:
        query = query.where(CrawlRun.run_type == run_type)
    if url_search:
        escaped = escape_like_pattern(url_search.lower())
        pattern = f"%{escaped}%"
        query = query.where(func.lower(CrawlRun.url).like(pattern, escape="\\"))
    # Single query: data + total via window function — eliminates the serial count round-trip
    result = await session.execute(
        query.add_columns(func.count().over().label("total"))
        .order_by(CrawlRun.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    rows = result.all()
    if rows:
        total = int(rows[0][1])
    else:
        total = int(
            (
                await session.execute(
                    select(func.count()).select_from(query.subquery())
                )
            ).scalar()
            or 0
        )
    return [row[0] for row in rows], total


async def get_run(session: AsyncSession, run_id: int) -> CrawlRun | None:
    return await session.get(CrawlRun, run_id)


async def delete_run(session: AsyncSession, run: CrawlRun) -> None:
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        return
    if db_run.is_active():
        raise ValueError(f"Cannot delete run in state: {db_run.status}")
    await session.delete(db_run)
    await session.commit()
    # 2.14: best-effort artifact cleanup after the DB delete; a disk failure
    # must not fail the delete (the retention sweeper reconciles leftovers).
    try:
        repository = ArtifactRepository(root_dir=settings.artifacts_dir)
        await asyncio.to_thread(repository.remove_run_tree, int(db_run.id))
    except Exception:
        logger.warning(
            "Failed to remove artifact tree for run=%s", db_run.id, exc_info=True
        )


async def get_run_records(
    session: AsyncSession, run_id: int, page: int, limit: int
) -> tuple[list[CrawlRecord], int]:
    page = max(1, page)
    total = int(
        (
            await session.execute(
                select(func.count())
                .select_from(CrawlRecord)
                .where(CrawlRecord.run_id == run_id)
            )
        ).scalar()
        or 0
    )
    result = await session.execute(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == run_id)
        .order_by(CrawlRecord.created_at.asc(), CrawlRecord.id.asc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    return list(result.scalars().all()), total


async def get_run_logs(
    session: AsyncSession,
    run_id: int,
    *,
    after_id: int | None = None,
    limit: int | None = None,
) -> list[CrawlLog]:
    query = (
        select(CrawlLog)
        .where(CrawlLog.run_id == run_id)
        .order_by(CrawlLog.created_at.asc())
    )
    if after_id is not None:
        query = query.where(CrawlLog.id > after_id)
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    return list(result.scalars().all())


async def get_run_and_logs(
    session: AsyncSession,
    run_id: int,
    *,
    after_id: int | None = None,
    limit: int | None = None,
) -> tuple[CrawlRun | None, list[CrawlLog]]:
    join_condition = CrawlLog.run_id == CrawlRun.id
    if after_id is not None:
        join_condition = and_(join_condition, CrawlLog.id > after_id)
    query = (
        select(CrawlRun, CrawlLog)
        .outerjoin(CrawlLog, join_condition)
        .where(CrawlRun.id == run_id)
        .order_by(CrawlLog.created_at.asc(), CrawlLog.id.asc())
    )
    if limit is not None:
        query = query.limit(limit)
    result = await session.execute(query)
    rows = list(result.all())
    if not rows:
        return None, []
    run = rows[0][0]
    logs = [log for _run, log in rows if log is not None]
    return run, logs


async def commit_selected_fields(
    session: AsyncSession,
    *,
    run: CrawlRun,
    items: list[dict],
) -> tuple[int, int]:
    if not items:
        return 0, 0
    valid_record_ids: list[int] = []
    for item in items:
        raw_record_id = item.get("record_id")
        if raw_record_id is None:
            continue
        try:
            valid_record_ids.append(int(raw_record_id))
        except (TypeError, ValueError):
            continue
    record_ids = sorted(set(valid_record_ids))
    db_run = await session.get(CrawlRun, run.id)
    if db_run is None:
        return 0, 0
    result = await session.execute(
        select(CrawlRecord).where(
            CrawlRecord.run_id == db_run.id, CrawlRecord.id.in_(record_ids)
        )
    )
    records = {record.id: record for record in result.scalars().all()}
    updated_fields = 0
    updated_record_ids: set[int] = set()

    for item in items:
        raw_record_id = item.get("record_id")
        if raw_record_id is None:
            continue
        try:
            record_id = int(raw_record_id)
        except (TypeError, ValueError):
            continue
        record = records.get(record_id)
        if record is None:
            continue
        field_name = normalize_field_key(item.get("field_name"))
        if not field_name:
            continue
        value = item.get("value")
        normalized_value = normalize_value(field_name, value)
        data = dict(record.data or {})
        data[field_name] = normalized_value
        record.data = data

        updated_fields += 1
        updated_record_ids.add(record_id)
    updated_records = len(updated_record_ids)
    await session.commit()

    if updated_fields:
        await append_log_event(
            run_id=run.id,
            level="info",
            message=f"[FIELDS] Committed {updated_fields} selected field value(s)",
            session=session,
        )
    return updated_records, updated_fields


async def active_jobs(
    session: AsyncSession, *, user_id: int | None = None
) -> list[dict]:
    query = (
        select(CrawlRun)
        .where(CrawlRun.status.in_([status.value for status in ACTIVE_STATUSES]))
        .order_by(CrawlRun.created_at.asc())
    )
    if user_id is not None:
        query = query.where(CrawlRun.user_id == user_id)
    result = await session.execute(query)
    rows = []
    for run in result.scalars().all():
        result_summary = run.summary_dict()
        rows.append(
            {
                "run_id": run.id,
                "status": run.status,
                "progress": result_summary.get("progress", 0),
                "started_at": run.created_at,
                "url": run.url,
                "type": run.run_type,
                "user_id": run.user_id,
            }
        )
    return rows
