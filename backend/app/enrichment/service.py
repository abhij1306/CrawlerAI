from __future__ import annotations
import logging
from datetime import UTC, datetime
from typing import cast
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import SessionLocal
from app.core.shared.coerce_primitives import bounded_int, object_dict, object_list, positive_int
from app.models.data_enrichment import DataEnrichmentJob, EnrichedProduct
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.user import User
from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_LLM_BACKFILL_FIELDS,
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
from app.crawl.access_service import (
    require_accessible_record,
    require_accessible_run,
)
from app.enrichment.deterministic import (
    build_deterministic_enrichment,
    load_attribute_repository,
    load_taxonomy_index,
    normalize_from_terms,
    normalize_materials,
    normalize_sizes,
    without_empty,
)
from app.core.shared.text_coerce import bounded_unique_strings as string_list
from app.enrichment.discovery_tags import (
    ai_discovery_allowed_tags_for_product,
    discovery_tag_slug,
)
from app.enrichment.llm_diagnostics import build_llm_diagnostics
from app.enrichment.shopify_catalog import (
    category_attribute_handles,
    repository_terms,
    taxonomy_reference_for_category_path,
    term_dict,
)
from app.core.shared.field_coerce import (
    clean_text,
    strip_html_tags,
    text_or_none,
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
    for record in source_records:
        run = await session.get(CrawlRun, record.run_id)
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


async def run_data_enrichment_job(job_id: int) -> None:
    async with SessionLocal() as session:
        job = await session.get(DataEnrichmentJob, job_id)
        if job is None or job.status != DATA_ENRICHMENT_STATUS_PENDING:
            return
        await run_job(session, job)


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

    enriched_count = 0
    failed_count = 0
    llm_enabled = bool((job.options or {}).get("llm_enabled"))
    for product_id, source_record_id in product_refs:
        product = await session.get(EnrichedProduct, product_id)
        record = await session.get(CrawlRecord, source_record_id)
        if product is None or record is None:
            if product is None:
                failed_count += 1
                continue
            product.status = DATA_ENRICHMENT_STATUS_FAILED
            product.diagnostics = {"error": "source_record_missing"}
            failed_count += 1
            continue
        record_id = record.id
        try:
            product.status = DATA_ENRICHMENT_STATUS_RUNNING
            record.enrichment_status = DATA_ENRICHMENT_STATUS_RUNNING
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
                refreshed_job = await session.get(DataEnrichmentJob, job_id)
                refreshed_product = await session.get(EnrichedProduct, product_id)
                refreshed_record = await session.get(CrawlRecord, record_id)
                if (
                    refreshed_job is None
                    or refreshed_product is None
                    or refreshed_record is None
                ):
                    raise
                job = refreshed_job
                product = refreshed_product
                record = refreshed_record
            product.status = DATA_ENRICHMENT_STATUS_FAILED
            product.diagnostics = {"error": str(exc)}
            record.enrichment_status = DATA_ENRICHMENT_STATUS_FAILED
            failed_count += 1
            await session.commit()
        else:
            product.status = DATA_ENRICHMENT_STATUS_ENRICHED
            record.enrichment_status = DATA_ENRICHMENT_STATUS_ENRICHED
            record.enriched_at = datetime.now(UTC)
            enriched_count += 1
            await session.commit()

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
    prompt_context = _llm_prompt_context(
        source_data,
        product=product,
        category_candidates=category_candidates,
    )
    variables: dict[str, object] = {
        "product_json": prompt_context,
        "taxonomy_hint": _taxonomy_hint(
            product.category_path,
            category_candidates=category_candidates,
            missing_fields=_missing_llm_backfill_fields(product),
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
    applied_fields = _apply_llm_payload(product, payload, allowed_tags=allowed_tags)
    return {
        "applied": bool(applied_fields),
        "category_applied": "category_path" in applied_fields,
        "applied_fields": applied_fields,
        **build_llm_diagnostics(product, payload, applied_fields),
        "provider": result.provider or "",
        "model": result.model or "",
    }
def _apply_llm_payload(
    product: EnrichedProduct,
    payload: dict[str, object],
    *,
    allowed_tags: list[str] | None = None,
) -> list[str]:
    applied: list[str] = []
    repository = load_attribute_repository()
    terms = repository_terms(repository)
    category_path = text_or_none(payload.get("category_path"))
    if product.category_path is None and category_path:
        if taxonomy_reference := taxonomy_reference_for_category_path(
            category_path,
            load_taxonomy_index(),
        ):
            product.category_path = str(taxonomy_reference.get("category_path") or "")
            applied.append("category_path")
    for field_name, term_name in (
        ("color_family", "color_families"),
        ("gender_normalized", "gender_terms"),
        ("availability_normalized", "availability_terms"),
    ):
        if getattr(product, field_name) is not None:
            continue
        raw_value = payload.get(field_name)
        normalized = normalize_from_terms(
            string_list(raw_value, max_items=1, max_chars=60) or [raw_value],
            term_dict(terms, term_name),
        )
        if normalized:
            setattr(product, field_name, normalized)
            applied.append(field_name)
    if product.size_normalized is None:
        category_match = _category_match_for_product_path(product.category_path)
        size_normalized, size_system = normalize_sizes(
            {
                "size": payload.get("size_normalized"),
                "size_system": payload.get("size_system"),
                "category": product.category_path,
            },
            terms=terms,
            category_match=category_match,
        )
        if size_normalized:
            product.size_normalized = size_normalized
            applied.append("size_normalized")
        if product.size_system is None and size_system:
            product.size_system = size_system
            applied.append("size_system")
    if product.size_system is None:
        size_system = text_or_none(payload.get("size_system"))
        known_systems = {
            str(key)
            for key in object_dict(term_dict(terms, "size_systems").get("systems"))
        }
        if size_system and size_system in known_systems:
            product.size_system = size_system
            applied.append("size_system")
    if product.materials_normalized is None:
        materials_normalized = normalize_materials(
            {"materials": payload.get("materials_normalized")}, terms=terms
        )
        if materials_normalized:
            product.materials_normalized = materials_normalized
            applied.append("materials_normalized")
    for field_name in (
        "intent_attributes",
        "audience",
        "style_tags",
        "ai_discovery_tags",
        "suggested_bundles",
    ):
        max_chars = (
            data_enrichment_settings.llm_semantic_list_item_chars
            if field_name in {"intent_attributes", "audience", "style_tags"}
            else 60
        )
        values = string_list(payload.get(field_name), max_items=10, max_chars=max_chars)
        if field_name == "ai_discovery_tags":
            allowed = set(allowed_tags or ai_discovery_allowed_tags_for_product(product))
            kept: list[str] = []
            discarded: list[dict[str, str]] = []
            for value in values:
                slug = discovery_tag_slug(value)
                if slug and slug in allowed:
                    kept.append(slug)
                elif slug:
                    discarded.append({"value": str(value), "slug": slug})
            if discarded:
                logger.warning(
                    "Discarded unsupported ai_discovery_tags for product_id=%s: %s",
                    product.id,
                    discarded,
                )
            values = kept
        setattr(product, field_name, values or None)
        if values:
            applied.append(field_name)
    product.taxonomy_version = DATA_ENRICHMENT_TAXONOMY_VERSION
    return applied


def _category_match_for_product_path(category_path: str | None) -> dict[str, object] | None:
    if not category_path:
        return None
    if not (reference := taxonomy_reference_for_category_path(
        category_path, load_taxonomy_index()
    )):
        return None
    return {
        "category_path": str(reference.get("category_path") or category_path),
        "taxonomy_reference": reference,
    }


async def _upsert_enriched_product(
    session: AsyncSession,
    *,
    job: DataEnrichmentJob,
    record: CrawlRecord,
) -> EnrichedProduct:
    existing = (
        await session.scalars(
            select(EnrichedProduct).where(EnrichedProduct.source_record_id == record.id)
        )
    ).first()
    if existing is not None:
        existing.job_id = job.id
        existing.source_run_id = record.run_id
        existing.source_url = record.source_url
        existing.status = DATA_ENRICHMENT_STATUS_PENDING
        _clear_enriched_fields(existing)
        existing.diagnostics = {}
        return existing
    product = EnrichedProduct(
        job_id=job.id,
        source_run_id=record.run_id,
        source_record_id=record.id,
        source_url=record.source_url,
        status=DATA_ENRICHMENT_STATUS_PENDING,
        diagnostics={},
    )
    session.add(product)
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
        records: list[CrawlRecord] = []
        for record_id in record_ids[: cast(int, options["max_source_records"])]:
            records.append(
                await require_accessible_record(session, record_id=record_id, user=user)
            )
        return records

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


def _missing_llm_backfill_fields(product: EnrichedProduct) -> list[str]:
    return [
        str(name)
        for name in DATA_ENRICHMENT_LLM_BACKFILL_FIELDS
        if getattr(product, name) in (None, "", [], {})
    ]


def _llm_prompt_context(
    source_data: dict[str, object],
    *,
    product: EnrichedProduct,
    category_candidates: list[dict[str, object]],
) -> dict[str, object]:
    description = clean_text(strip_html_tags(source_data.get("description")))
    category_anchor = product.category_path or text_or_none(
        category_candidates[0].get("category_path") if category_candidates else None
    )
    context = without_empty(
        {
            "title": clean_text(source_data.get("title")),
            "brand": clean_text(source_data.get("brand")),
            "category": clean_text(source_data.get("category")),
            "product_type": clean_text(source_data.get("product_type")),
            "price_normalized": product.price_normalized,
            "color_family": product.color_family,
            "size_normalized": product.size_normalized,
            "size_system": product.size_system,
            "gender_normalized": product.gender_normalized,
            "materials_normalized": product.materials_normalized,
            "availability_normalized": product.availability_normalized,
            "seo_keywords": product.seo_keywords,
            "category_path": product.category_path,
            "taxonomy_version": DATA_ENRICHMENT_TAXONOMY_VERSION,
            "missing_backfill_fields": _missing_llm_backfill_fields(product),
            "taxonomy_candidates": [
                _taxonomy_candidate_context(candidate)
                for candidate in category_candidates[
                    : data_enrichment_settings.llm_taxonomy_hint_count
                ]
            ],
            "category_attributes": category_attribute_handles(
                category_anchor,
                load_taxonomy_index(),
            ),
            "ai_discovery_allowed_tags": ai_discovery_allowed_tags_for_product(product),
        }
    )
    if description:
        context["description_excerpt"] = description[
            : data_enrichment_settings.llm_description_excerpt_chars
        ]
    return context


def _taxonomy_candidate_context(candidate: dict[str, object]) -> dict[str, object]:
    taxonomy_reference = object_dict(candidate.get("taxonomy_reference"))
    return without_empty(
        {
            "category_id": candidate.get("category_id"),
            "category_path": candidate.get("category_path"),
            "score": candidate.get("score"),
            "source": candidate.get("source"),
            "taxonomy_version": candidate.get("taxonomy_version")
            or taxonomy_reference.get("taxonomy_version")
            or DATA_ENRICHMENT_TAXONOMY_VERSION,
            "attribute_handles": object_list(taxonomy_reference.get("attribute_handles")),
        }
    )


def _taxonomy_hint(
    category_path: str | None,
    *,
    category_candidates: list[dict[str, object]],
    missing_fields: list[str],
) -> str:
    if category_path:
        guidance = f"Current deterministic category is {category_path}."
    else:
        candidate_paths = ", ".join(
            str(item.get("category_path") or "")
            for item in category_candidates[: data_enrichment_settings.llm_taxonomy_hint_count]
            if str(item.get("category_path") or "").strip()
        )
        guidance = f"Prefer one of these candidates when supported by evidence: {candidate_paths}."
        if not candidate_paths:
            guidance = "Return only real Shopify category paths."
    return (
        f"Use Shopify taxonomy version {DATA_ENRICHMENT_TAXONOMY_VERSION}. {guidance} "
        f"Only fill missing fields: {', '.join(missing_fields) or 'none'}."
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
def _clear_enriched_fields(product: EnrichedProduct) -> None:
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
    ):
        setattr(product, field_name, None)
