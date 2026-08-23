from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import uuid4
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.celery_app import (
    celery_task_id_of,
    celery_task_is_gone,
    celery_task_state,
    enqueue_celery_job,
    mark_celery_job_failed,
    start_in_process_job,
)
from app.core.config import settings
from app.core.database import SessionLocal
from app.core.shared.coerce_primitives import (
    bounded_int,
    object_dict,
    object_list,
    positive_int,
)
from app.models.data_enrichment import DataEnrichmentJob, EnrichedProduct
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.user import User
from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_LLM_TASK,
    DATA_ENRICHMENT_SKIP_RECORD_STATUSES,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_FAILED,
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_STATUS_RUNNING,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
    ECOMMERCE_DETAIL_SURFACE,
    data_enrichment_settings,
)
from app.core.config.product_intelligence import product_intelligence_settings
from app.crawl.access_service import (
    AccessDeniedError,
    require_accessible_run,
)
from app.enrichment.deterministic import build_deterministic_enrichment
from app.core.shared.text_coerce import bounded_unique_strings as string_list
from app.enrichment.llm_diagnostics import (
    apply_llm_payload,
    build_llm_diagnostics,
    llm_prompt_context,
    missing_llm_backfill_fields,
    taxonomy_hint,
)
from app.connectors.llm.runtime import run_prompt_task
from app.connectors.llm.config_service import snapshot_active_configs
from app.intelligence.matching import source_domain

logger = logging.getLogger(__name__)


async def create_data_enrichment_job(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
) -> DataEnrichmentJob:
    options = _normalized_options(payload.get("options"))
    llm_config_snapshot = await snapshot_active_configs(
        session,
        task_types=[DATA_ENRICHMENT_LLM_TASK],
    )
    source_run_id = positive_int(payload.get("source_run_id"))
    source_records = await _load_source_records(
        session, user=user, payload=payload, options=options
    )
    if not source_records:
        raise ValueError("Data Enrichment needs at least one ecommerce detail record")
    if source_run_id is not None:
        await require_accessible_run(session, run_id=source_run_id, user=user)
    accepted_records: list[CrawlRecord] = []
    skipped_status = 0
    skipped_surface = 0
    run_ids = {record.run_id for record in source_records}
    runs_by_id = {
        run.id: run
        for run in (
            await session.scalars(select(CrawlRun).where(CrawlRun.id.in_(run_ids)))
        ).all()
    }
    for record in source_records:
        run = runs_by_id.get(record.run_id)
        if (
            run is None
            or str(run.surface or "").strip().lower() != ECOMMERCE_DETAIL_SURFACE
        ):
            skipped_surface += 1
            continue
        if (
            str(record.enrichment_status or "").strip().lower()
            in DATA_ENRICHMENT_SKIP_RECORD_STATUSES
        ):
            skipped_status += 1
            continue
        accepted_records.append(record)
    if not accepted_records:
        raise ValueError("No eligible ecommerce detail records selected")
    job = DataEnrichmentJob(
        user_id=user.id,
        source_run_id=source_run_id,
        status=DATA_ENRICHMENT_STATUS_PENDING,
        options={
            **options,
            "llm_config_snapshot": llm_config_snapshot,
            "source_record_ids": [record.id for record in accepted_records],
        },
        summary={
            "requested_count": len(source_records),
            "accepted_count": len(accepted_records),
            "skipped_status_count": skipped_status,
            "skipped_surface_count": skipped_surface,
        },
    )
    session.add(job)
    await session.flush()
    for record in accepted_records:
        record.enrichment_status = DATA_ENRICHMENT_STATUS_PENDING
        record.enriched_at = None
        await _upsert_enriched_product(session, job=job, record=record)
    await session.commit()
    await session.refresh(job)
    return job


async def dispatch_data_enrichment_job(
    session: AsyncSession, job: DataEnrichmentJob
) -> None:
    """Hand a pending job to a Celery worker; fall back to an in-process task.

    Mirrors the crawl run dispatcher: with Celery dispatch enabled the job row
    records its task id (used to detect interrupted redeliveries and orphaned
    runs); with it disabled the job runs as an in-process asyncio task, the
    legacy BackgroundTasks behavior for local development.
    """
    if settings.celery_dispatch_enabled:
        from app.tasks import data_enrichment_run_job_task

        if await enqueue_celery_job(
            session,
            job,
            task=data_enrichment_run_job_task,
            task_id=f"data-enrichment-job-{int(job.id)}-{uuid4().hex}",
            label="Data Enrichment",
        ):
            return
    start_in_process_job(run_data_enrichment_job(int(job.id)))


async def _fail_stuck_job(
    session: AsyncSession, job: DataEnrichmentJob, *, now: datetime, error: str
) -> None:
    """Fail a stuck job and release its non-terminal products/records.

    Products still pending/running are marked failed and their source records
    are reset from pending/running to failed so a later job can re-enrich them
    (job creation skips records in pending/running).
    """
    mark_celery_job_failed(
        job,
        failed_status=DATA_ENRICHMENT_STATUS_FAILED,
        now=now,
        error=error,
    )
    products = list(
        (
            await session.scalars(
                select(EnrichedProduct).where(
                    EnrichedProduct.job_id == job.id,
                    EnrichedProduct.status.in_(
                        [
                            DATA_ENRICHMENT_STATUS_PENDING,
                            DATA_ENRICHMENT_STATUS_RUNNING,
                        ]
                    ),
                )
            )
        ).all()
    )
    record_ids = [
        int(product.source_record_id)
        for product in products
        if product.source_record_id is not None
    ]
    if record_ids:
        records = list(
            (
                await session.scalars(
                    select(CrawlRecord).where(
                        CrawlRecord.id.in_(record_ids),
                        CrawlRecord.enrichment_status.in_(
                            DATA_ENRICHMENT_SKIP_RECORD_STATUSES
                        ),
                    )
                )
            ).all()
        )
        for record in records:
            record.enrichment_status = DATA_ENRICHMENT_STATUS_FAILED
    for product in products:
        product.status = DATA_ENRICHMENT_STATUS_FAILED
        product.diagnostics = {"error": "job_orphaned"}


async def recover_orphaned_data_enrichment_jobs(
    session: AsyncSession,
    *,
    exclude_task_id: str | None = None,
    now: datetime | None = None,
) -> int:
    """Fail Data Enrichment jobs stuck in ``running`` with no live task.

    Invoked on job-task entry (see ``run_data_enrichment_job``): jobs left
    ``running`` by a dead API process (legacy BackgroundTasks) or a lost worker
    are marked failed instead of lingering forever.
    """
    now = now or datetime.now(UTC)
    stale_before = now - timedelta(
        seconds=product_intelligence_settings.job_orphaned_after_seconds
    )
    pending_stale_before = now - timedelta(
        seconds=product_intelligence_settings.job_orphaned_pending_after_seconds
    )
    jobs = list(
        (
            await session.scalars(
                select(DataEnrichmentJob).where(
                    DataEnrichmentJob.status == DATA_ENRICHMENT_STATUS_RUNNING
                )
            )
        ).all()
    )
    recovered = 0
    for job in jobs:
        updated_at = job.updated_at or job.created_at or now
        stale = updated_at <= stale_before
        if not celery_task_is_gone(
            job.summary,
            exclude_task_id=exclude_task_id,
            stale=stale,
            pending_stale=updated_at <= pending_stale_before,
            task_state=celery_task_state,
        ):
            continue
        await _fail_stuck_job(
            session,
            job,
            now=now,
            error="OrphanedJobRecovery: no live Celery task for running job",
        )
        recovered += 1
    if recovered:
        logger.warning("Recovered %s orphaned Data Enrichment job(s)", recovered)
        await session.commit()
    return recovered


async def run_data_enrichment_job(job_id: int, *, task_id: str | None = None) -> None:
    async with SessionLocal() as session:
        await recover_orphaned_data_enrichment_jobs(session, exclude_task_id=task_id)
        job = await session.get(DataEnrichmentJob, job_id)
        if job is None:
            return
        if job.status == DATA_ENRICHMENT_STATUS_RUNNING:
            # A running job whose recorded task id matches ours means Celery
            # redelivered an interrupted execution (acks-late worker loss):
            # fail cleanly instead of leaving the row stuck.
            if task_id is not None and celery_task_id_of(job.summary) == task_id:
                await _fail_stuck_job(
                    session,
                    job,
                    now=datetime.now(UTC),
                    error="WorkerInterrupted: job interrupted by worker loss",
                )
                await session.commit()
            return
        if job.status != DATA_ENRICHMENT_STATUS_PENDING:
            return
        try:
            await run_job(session, job)
        except Exception as exc:  # keep jobs from sticking in ``running``
            logger.exception("Data Enrichment job failed: %s", job_id)
            if isinstance(exc, SQLAlchemyError):
                await session.rollback()
            refreshed_job = await session.get(DataEnrichmentJob, job_id)
            if refreshed_job is None:
                return
            await _fail_stuck_job(
                session,
                refreshed_job,
                now=datetime.now(UTC),
                error=f"{type(exc).__name__}: {exc}",
            )
            await session.commit()


async def list_data_enrichment_jobs(
    session: AsyncSession,
    *,
    user: User,
    limit: int = 25,
) -> list[DataEnrichmentJob]:
    statement = (
        select(DataEnrichmentJob).order_by(DataEnrichmentJob.id.desc()).limit(limit)
    )
    if user.role != "admin":
        statement = statement.where(DataEnrichmentJob.user_id == user.id)
    return list((await session.scalars(statement)).all())


async def get_data_enrichment_job(
    session: AsyncSession,
    *,
    user: User,
    job_id: int,
) -> DataEnrichmentJob:
    job = await session.get(DataEnrichmentJob, job_id)
    if job is None or (user.role != "admin" and job.user_id != user.id):
        raise LookupError("Data Enrichment job not found")
    return job


async def build_data_enrichment_job_payload(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
) -> dict[str, object]:
    products = list(
        (
            await session.scalars(
                select(EnrichedProduct)
                .where(EnrichedProduct.job_id == job.id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
    )
    return {"job": job, "enriched_products": products}


async def run_job(session: AsyncSession, job: DataEnrichmentJob) -> None:
    now = datetime.now(UTC)
    job_id = int(job.id)
    job.status = DATA_ENRICHMENT_STATUS_RUNNING
    job.summary = {**dict(job.summary or {}), "started_at": now.isoformat()}
    await session.commit()
    product_refs = [
        (int(product_id), int(source_record_id))
        for product_id, source_record_id in (
            await session.execute(
                select(EnrichedProduct.id, EnrichedProduct.source_record_id)
                .where(EnrichedProduct.job_id == job_id)
                .order_by(EnrichedProduct.id)
            )
        ).all()
        if product_id is not None and source_record_id is not None
    ]

    llm_enabled = bool((job.options or {}).get("llm_enabled"))
    products_by_id, records_by_id = await _load_job_products(
        session, product_refs=product_refs
    )
    enriched_count = 0
    failed_count = 0
    for product_id, source_record_id in product_refs:
        job, enriched = await _process_job_product(
            session,
            job=job,
            product=products_by_id.get(product_id),
            record=records_by_id.get(source_record_id),
            product_id=product_id,
            llm_enabled=llm_enabled,
        )
        if enriched:
            enriched_count += 1
        else:
            failed_count += 1
    await _complete_job(
        session,
        job=job,
        enriched_count=enriched_count,
        failed_count=failed_count,
        llm_enabled=llm_enabled,
    )


async def _load_job_products(
    session: AsyncSession, *, product_refs: list[tuple[int, int]]
) -> tuple[dict[int, EnrichedProduct], dict[int, CrawlRecord]]:
    if not product_refs:
        return {}, {}
    products = await session.scalars(
        select(EnrichedProduct).where(
            EnrichedProduct.id.in_([product_id for product_id, _ in product_refs])
        )
    )
    records = await session.scalars(
        select(CrawlRecord).where(
            CrawlRecord.id.in_([record_id for _, record_id in product_refs])
        )
    )
    return (
        {int(product.id): product for product in products.all()},
        {int(record.id): record for record in records.all()},
    )


async def _process_job_product(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    product: EnrichedProduct | None,
    record: CrawlRecord | None,
    product_id: int,
    llm_enabled: bool,
) -> tuple[DataEnrichmentJob, bool]:
    if product is None:
        return job, False
    if record is None:
        product.status = DATA_ENRICHMENT_STATUS_FAILED
        product.diagnostics = {"error": "source_record_missing"}
        return job, False
    record_id = int(record.id)
    try:
        product.status = DATA_ENRICHMENT_STATUS_RUNNING
        record.enrichment_status = DATA_ENRICHMENT_STATUS_RUNNING
        await session.commit()
        await _enrich_product(
            session,
            job=job,
            product=product,
            record=record,
            llm_enabled=llm_enabled,
        )
    except Exception as exc:  # pragma: no cover - defensive job isolation
        if isinstance(exc, SQLAlchemyError):
            await session.rollback()
            (
                refreshed_job,
                refreshed_product,
                refreshed_record,
            ) = await _reload_failed_product(
                session,
                job_id=int(job.id),
                product_id=product_id,
                record_id=record_id,
            )
            if (
                refreshed_job is None
                or refreshed_product is None
                or refreshed_record is None
            ):
                raise
            job, product, record = refreshed_job, refreshed_product, refreshed_record
        product.status = DATA_ENRICHMENT_STATUS_FAILED
        product.diagnostics = {"error": str(exc)}
        record.enrichment_status = DATA_ENRICHMENT_STATUS_FAILED
        await session.commit()
        return job, False
    product.status = DATA_ENRICHMENT_STATUS_ENRICHED
    record.enrichment_status = DATA_ENRICHMENT_STATUS_ENRICHED
    record.enriched_at = datetime.now(UTC)
    await session.commit()
    return job, True


async def _reload_failed_product(
    session: AsyncSession, *, job_id: int, product_id: int, record_id: int
) -> tuple[DataEnrichmentJob | None, EnrichedProduct | None, CrawlRecord | None]:
    job = await session.get(DataEnrichmentJob, job_id)
    product = await session.get(EnrichedProduct, product_id)
    record = await session.get(CrawlRecord, record_id)
    return job, product, record


async def _complete_job(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    enriched_count: int,
    failed_count: int,
    llm_enabled: bool,
) -> None:
    completed_at = datetime.now(UTC)
    job.completed_at = completed_at
    if failed_count and enriched_count:
        job.status = DATA_ENRICHMENT_STATUS_DEGRADED
    elif failed_count:
        job.status = DATA_ENRICHMENT_STATUS_FAILED
    else:
        job.status = DATA_ENRICHMENT_STATUS_ENRICHED
    job.summary = {
        **dict(job.summary or {}),
        "completed_at": completed_at.isoformat(),
        "enriched_count": enriched_count,
        "failed_count": failed_count,
        "llm_enabled": llm_enabled,
    }
    await session.commit()


async def _enrich_product(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    product: EnrichedProduct,
    record: CrawlRecord,
    llm_enabled: bool,
) -> None:
    data = dict(record.data or {})
    deterministic = build_deterministic_enrichment(data, source_url=record.source_url)
    category_match = deterministic.pop("_taxonomy_match", None)
    raw_category_candidates = deterministic.pop("_taxonomy_candidates", None)
    category_candidates = [
        item for item in object_list(raw_category_candidates) if isinstance(item, dict)
    ]
    product_attributes = deterministic.pop("_product_attributes", None)
    for key, value in deterministic.items():
        setattr(product, key, value)
    product.taxonomy_version = DATA_ENRICHMENT_TAXONOMY_VERSION
    diagnostics: dict[str, object] = {
        "deterministic": True,
        "llm_requested": llm_enabled,
        "category_source": "deterministic" if product.category_path else "",
        "product_category": category_match or {},
        "product_attributes": product_attributes or {},
    }
    if category_candidates:
        diagnostics["category_candidates"] = category_candidates
    if llm_enabled:
        llm_result = await _run_llm_enrichment(
            session,
            job=job,
            record=record,
            product=product,
            source_data=data,
            category_candidates=category_candidates or [],
        )
        diagnostics["llm"] = llm_result
        if llm_result.get("category_applied"):
            diagnostics["category_source"] = "llm"
    else:
        product.intent_attributes = None
        product.audience = None
        product.style_tags = None
        product.ai_discovery_tags = None
        product.suggested_bundles = None
    product.diagnostics = diagnostics


async def _run_llm_enrichment(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    record: CrawlRecord,
    product: EnrichedProduct,
    source_data: dict[str, object],
    category_candidates: list[dict[str, object]],
) -> dict[str, object]:
    prompt_context = llm_prompt_context(
        source_data,
        product=product,
        category_candidates=category_candidates,
    )
    variables: dict[str, object] = {
        "product_json": prompt_context,
        "taxonomy_hint": taxonomy_hint(
            product.category_path,
            category_candidates=category_candidates,
            missing_fields=missing_llm_backfill_fields(product),
        ),
    }
    snapshot = (job.options or {}).get("llm_config_snapshot")
    result = await run_prompt_task(
        session,
        task_type=DATA_ENRICHMENT_LLM_TASK,
        run_id=record.run_id,
        domain=source_domain(record.source_url),
        budget_scope=f"{DATA_ENRICHMENT_LLM_TASK}:{job.id}",
        timeout_seconds=data_enrichment_settings.llm_call_timeout_seconds,
        config_snapshot=snapshot if isinstance(snapshot, dict) else None,
        variables=variables,
    )
    if result.error_message:
        return {
            "applied": False,
            "error": result.error_message,
            "error_category": str(result.error_category or ""),
        }
    if isinstance(result.payload, dict):
        payload = result.payload
    else:
        model_dump = getattr(result.payload, "model_dump", None)
        if callable(model_dump):
            payload = dict(model_dump(exclude_none=True))
        else:
            payload = {}
    allowed_tags = string_list(
        prompt_context.get("ai_discovery_allowed_tags"),
        max_items=50,
        max_chars=60,
    )
    applied_fields = apply_llm_payload(product, payload, allowed_tags=allowed_tags)
    return {
        "applied": bool(applied_fields),
        "category_applied": "category_path" in applied_fields,
        "applied_fields": applied_fields,
        **build_llm_diagnostics(product, payload, applied_fields),
        "provider": result.provider or "",
        "model": result.model or "",
    }


async def _upsert_enriched_product(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    record: CrawlRecord,
) -> EnrichedProduct:
    now = datetime.now(UTC)
    reset_values = _empty_enriched_product_values()
    statement = (
        insert(EnrichedProduct)
        .values(
            job_id=job.id,
            source_run_id=record.run_id,
            source_record_id=record.id,
            source_url=record.source_url,
            status=DATA_ENRICHMENT_STATUS_PENDING,
            diagnostics={},
            created_at=now,
            updated_at=now,
            **reset_values,
        )
        .on_conflict_do_update(
            index_elements=[EnrichedProduct.source_record_id],
            index_where=EnrichedProduct.source_record_id.is_not(None),
            set_={
                "job_id": job.id,
                "source_run_id": record.run_id,
                "source_url": record.source_url,
                "status": DATA_ENRICHMENT_STATUS_PENDING,
                "diagnostics": {},
                "updated_at": now,
                **reset_values,
            },
        )
        .returning(EnrichedProduct.id)
    )
    product_id = (await session.execute(statement)).scalar_one()
    product = await session.get(EnrichedProduct, int(product_id))
    if product is None:
        raise RuntimeError(f"EnrichedProduct upsert failed: record_id={record.id}")
    return product


async def _load_source_records(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
    options: dict[str, object],
) -> list[CrawlRecord]:
    record_ids = _source_record_ids(payload)
    if record_ids:
        limited_ids = record_ids[: cast(int, options["max_source_records"])]
        query = (
            select(CrawlRecord)
            .join(CrawlRun, CrawlRun.id == CrawlRecord.run_id)
            .where(CrawlRecord.id.in_(limited_ids))
        )
        if user.role != "admin":
            query = query.where(CrawlRun.user_id == user.id)
        rows = list((await session.scalars(query)).all())
        records_by_id = {record.id: record for record in rows}
        missing_ids = [
            record_id for record_id in limited_ids if record_id not in records_by_id
        ]
        if missing_ids:
            raise AccessDeniedError("Record not found")
        return [records_by_id[record_id] for record_id in limited_ids]

    source_run_id = positive_int(payload.get("source_run_id"))
    if source_run_id is None:
        return []
    run = await require_accessible_run(session, run_id=source_run_id, user=user)
    return list(
        (
            await session.scalars(
                select(CrawlRecord)
                .where(CrawlRecord.run_id == run.id)
                .order_by(CrawlRecord.id)
                .limit(cast(int, options["max_source_records"]))
            )
        ).all()
    )


def _source_record_ids(payload: dict[str, object]) -> list[int]:
    ids = [
        parsed
        for item in object_list(payload.get("source_record_ids"))
        if (parsed := positive_int(item)) is not None
    ]
    for item in object_list(payload.get("source_records")):
        if (record_id := positive_int(object_dict(item).get("id"))) is not None:
            ids.append(record_id)
    return list(dict.fromkeys(ids))


def _normalized_options(value: object) -> dict[str, object]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    return {
        "max_source_records": bounded_int(
            raw.get("max_source_records"),
            data_enrichment_settings.max_source_records,
            ceiling=data_enrichment_settings.max_source_records,
        ),
        "llm_enabled": bool(raw.get("llm_enabled", False)),
        "taxonomy_path": str(data_enrichment_settings.taxonomy_path),
        "attributes_path": str(data_enrichment_settings.attributes_path),
        "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
        "max_concurrency": data_enrichment_settings.max_concurrency,
    }


def _empty_enriched_product_values() -> dict[str, object | None]:
    return {
        field_name: None
        for field_name in (
            "price_normalized",
            "color_family",
            "size_normalized",
            "size_system",
            "gender_normalized",
            "materials_normalized",
            "availability_normalized",
            "seo_keywords",
            "category_path",
            "taxonomy_version",
            "intent_attributes",
            "audience",
            "style_tags",
            "ai_discovery_tags",
            "suggested_bundles",
        )
    }
