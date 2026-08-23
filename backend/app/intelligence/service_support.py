from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.llm.runtime import run_prompt_task
from app.core.config.product_intelligence import (
    CRAWL_RUN_FINAL_STATUSES,
    PRIVATE_LABEL_EXCLUDE,
    PRIVATE_LABEL_FLAG,
    PRIVATE_LABEL_INCLUDE,
    PRODUCT_INTELLIGENCE_BRAND_INFERENCE_LLM_TASK,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_COMPLETE,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_DISCOVERED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_FAILED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS,
    PRODUCT_INTELLIGENCE_LLM_TASK,
    PRODUCT_INTELLIGENCE_REVIEW_PENDING,
    product_intelligence_settings,
)
from app.crawl.access_service import require_accessible_record, require_accessible_run
from app.crawl.crud import get_run_records
from app.intelligence.matching import (
    extract_product_snapshot,
    is_private_label,
    normalize_brand,
    score_candidate,
    source_domain,
)
from app.intelligence.candidate_urls import looks_like_product_detail_url
from app.models.crawl_run import CrawlRecord, CrawlRun
from app.models.product_intelligence import (
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceMatch,
    ProductIntelligenceSourceProduct,
)
from app.models.user import User


async def _score_candidate_if_ready(
    session: AsyncSession,
    job: ProductIntelligenceJob,
    candidate: ProductIntelligenceCandidate,
    *,
    prompt_task_runner=None,
) -> bool:
    if candidate.candidate_crawl_run_id is None:
        return False
    existing = await session.scalar(
        select(ProductIntelligenceMatch.id).where(
            ProductIntelligenceMatch.candidate_id == candidate.id
        )
    )
    if existing:
        return True
    candidate_run = await session.get(CrawlRun, candidate.candidate_crawl_run_id)
    if candidate_run is None:
        candidate.status = PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_FAILED
        return True
    if candidate_run.status not in CRAWL_RUN_FINAL_STATUSES:
        return False
    record = await session.scalar(
        select(CrawlRecord)
        .where(CrawlRecord.run_id == candidate_run.id)
        .order_by(CrawlRecord.id)
        .limit(1)
    )
    if record is None:
        candidate.status = PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_NO_RECORDS
        return True
    source_product = await session.get(
        ProductIntelligenceSourceProduct, candidate.source_product_id
    )
    if source_product is None:
        candidate.status = PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_FAILED
        return True
    source_snapshot = _source_product_payload(source_product)
    candidate_snapshot = extract_product_snapshot(
        {
            **dict(record.data or {}),
            "source_url": record.source_url,
        }
    )
    result = score_candidate(
        source=source_snapshot,
        candidate=candidate_snapshot,
        source_type=candidate.source_type,
    )
    if not _meets_confidence_threshold(
        _as_float_or_default(result.get("score"), 0.0),
        options=job.options,
    ):
        candidate.status = PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_COMPLETE
        return True
    llm_enrichment = await _build_llm_enrichment(
        session,
        job=job,
        candidate=candidate,
        source_snapshot=source_snapshot,
        candidate_snapshot=candidate_snapshot,
        deterministic_result=result,
        prompt_task_runner=prompt_task_runner,
    )
    session.add(
        _candidate_match(
            job=job,
            candidate=candidate,
            source_product=source_product,
            record=record,
            candidate_snapshot=candidate_snapshot,
            result=result,
            llm_enrichment=llm_enrichment,
        )
    )
    candidate.status = PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_COMPLETE
    return True


def _candidate_match(
    *,
    job: ProductIntelligenceJob,
    candidate: ProductIntelligenceCandidate,
    source_product: ProductIntelligenceSourceProduct,
    record: CrawlRecord,
    candidate_snapshot: dict[str, object],
    result: dict[str, object],
    llm_enrichment: dict[str, object] | None,
) -> ProductIntelligenceMatch:
    reasons_raw = result.get("reasons")
    return ProductIntelligenceMatch(
        job_id=job.id,
        source_product_id=source_product.id,
        candidate_id=candidate.id,
        candidate_record_id=record.id,
        score=_as_float_or_default(result.get("score"), 0.0),
        score_label=str(result.get("label") or ""),
        review_status=PRODUCT_INTELLIGENCE_REVIEW_PENDING,
        source_price=source_product.price,
        candidate_price=_as_price(candidate_snapshot.get("price")),
        currency=str(
            candidate_snapshot.get("currency") or source_product.currency or ""
        ),
        availability=str(candidate_snapshot.get("availability") or ""),
        candidate_url=str(candidate_snapshot.get("url") or candidate.url),
        candidate_domain=source_domain(candidate_snapshot.get("url") or candidate.url),
        score_reasons=dict(reasons_raw) if isinstance(reasons_raw, dict) else {},
        llm_enrichment=llm_enrichment,
    )


async def _resolve_source_snapshot(
    session: AsyncSession,
    *,
    raw: dict[str, object],
    llm_enabled: bool,
    prompt_task_runner=None,
) -> dict[str, object]:
    snapshot = extract_product_snapshot(raw)
    if snapshot.get("brand") or not llm_enabled:
        return snapshot
    brand = await _brand_inference_llm(
        session,
        title=str(snapshot.get("title") or ""),
        url=str(snapshot.get("url") or ""),
        snippet=str(snapshot.get("description") or ""),
        prompt_task_runner=prompt_task_runner,
    )
    if not brand:
        return snapshot
    return {**snapshot, "brand": brand, "normalized_brand": normalize_brand(brand)}


async def _backfill_candidate_brand(
    session: AsyncSession,
    *,
    source: dict[str, object],
    intelligence: dict[str, object],
    source_type: str,
    llm_enabled: bool,
    prompt_task_runner=None,
) -> dict[str, object]:
    if not llm_enabled:
        return intelligence
    canonical = intelligence.get("canonical_record")
    if not isinstance(canonical, dict) or str(canonical.get("brand") or "").strip():
        return intelligence
    brand = await _brand_inference_llm(
        session,
        title=str(canonical.get("title") or ""),
        url=str(canonical.get("url") or ""),
        snippet=str(canonical.get("snippet") or canonical.get("description") or ""),
        prompt_task_runner=prompt_task_runner,
    )
    if not brand:
        return intelligence
    updated = {**canonical, "brand": brand, "normalized_brand": normalize_brand(brand)}
    rescored = score_candidate(
        source=source, candidate=updated, source_type=source_type
    )
    return {
        **intelligence,
        "canonical_record": updated,
        "confidence_score": rescored["score"],
        "confidence_label": rescored["label"],
        "score_reasons": rescored["reasons"],
    }


async def _brand_inference_llm(
    session: AsyncSession,
    *,
    title: str,
    url: str,
    snippet: str,
    prompt_task_runner=None,
) -> str:
    if not title and not url:
        return ""
    runner = prompt_task_runner or run_prompt_task
    domain = source_domain(url)
    result = await runner(
        session,
        task_type=PRODUCT_INTELLIGENCE_BRAND_INFERENCE_LLM_TASK,
        run_id=None,
        domain=domain,
        variables={
            "product_title": title,
            "product_url": url,
            "source_domain": domain,
            "product_snippet": snippet,
        },
    )
    if result.error_message or not isinstance(result.payload, dict):
        return ""
    brand = str(result.payload.get("brand") or "").strip()
    if not brand:
        return ""
    try:
        confidence = float(result.payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    threshold = product_intelligence_settings.brand_inference_confidence_threshold
    return brand if confidence >= threshold else ""


async def _build_llm_enrichment(
    session: AsyncSession,
    *,
    job: ProductIntelligenceJob,
    candidate: ProductIntelligenceCandidate,
    source_snapshot: dict[str, object],
    candidate_snapshot: dict[str, object],
    deterministic_result: dict[str, object],
    prompt_task_runner=None,
) -> dict[str, object]:
    requested = bool((job.options or {}).get("llm_enrichment_enabled"))
    base: dict[str, object] = {
        "requested": requested,
        "applied": False,
    }
    if not requested:
        return base
    runner = prompt_task_runner or run_prompt_task
    result = await runner(
        session,
        task_type=PRODUCT_INTELLIGENCE_LLM_TASK,
        run_id=candidate.candidate_crawl_run_id,
        domain=candidate.domain,
        variables={
            "source_product_json": source_snapshot,
            "candidate_product_json": candidate_snapshot,
            "serpapi_result_json": dict(candidate.payload or {}),
            "deterministic_match_json": deterministic_result,
        },
    )
    if result.error_message:
        return {
            **base,
            "error": result.error_message,
            "error_category": str(result.error_category or ""),
        }
    return {
        **base,
        "applied": isinstance(result.payload, dict),
        "provider": result.provider or "",
        "model": result.model or "",
        "payload": result.payload if isinstance(result.payload, dict) else {},
    }


async def _update_job_summary(
    session: AsyncSession, job: ProductIntelligenceJob
) -> None:
    # One round trip: three per-table COUNT(*) scalar subqueries in a single
    # SELECT instead of three separate count queries.
    counts = (
        await session.execute(
            select(
                select(func.count())
                .select_from(ProductIntelligenceSourceProduct)
                .where(ProductIntelligenceSourceProduct.job_id == job.id)
                .scalar_subquery()
                .label("source_count"),
                select(func.count())
                .select_from(ProductIntelligenceCandidate)
                .where(ProductIntelligenceCandidate.job_id == job.id)
                .scalar_subquery()
                .label("candidate_count"),
                select(func.count())
                .select_from(ProductIntelligenceMatch)
                .where(ProductIntelligenceMatch.job_id == job.id)
                .scalar_subquery()
                .label("match_count"),
            )
        )
    ).one()
    job.summary = {
        **dict(job.summary or {}),
        "source_count": int(counts.source_count or 0),
        "candidate_count": int(counts.candidate_count or 0),
        "search_provider": str((job.options or {}).get("search_provider") or ""),
        "match_count": int(counts.match_count or 0),
        "updated_at": datetime.now(UTC).isoformat(),
    }


async def _persist_discovery_sources(
    session: AsyncSession,
    *,
    job: ProductIntelligenceJob,
    source_run_id: int | None,
    source_rows: list[dict[str, object]],
    options: dict[str, object],
    resolved_snapshots: dict[int, dict[str, object]] | None,
    prompt_task_runner=None,
) -> dict[int, int]:
    source_products_by_index: dict[int, ProductIntelligenceSourceProduct] = {}
    snapshots_lookup = resolved_snapshots or {}
    llm_enabled = bool(options.get("llm_enrichment_enabled"))
    max_sources = _option_int(
        options,
        "max_source_products",
        default=product_intelligence_settings.max_source_products,
    )
    for index, row in enumerate(source_rows[:max_sources]):
        snapshot = snapshots_lookup.get(index) or await _resolve_source_snapshot(
            session,
            raw=_row_data_payload(row),
            llm_enabled=llm_enabled,
            prompt_task_runner=prompt_task_runner,
        )
        source = ProductIntelligenceSourceProduct(
            job_id=job.id,
            source_run_id=_as_int(row.get("source_run_id")) or source_run_id,
            source_record_id=_as_int(row.get("source_record_id")),
            source_url=_resolved_source_url(row, snapshot),
            brand=str(snapshot.get("brand") or ""),
            normalized_brand=str(snapshot.get("normalized_brand") or ""),
            title=str(snapshot.get("title") or ""),
            sku=str(snapshot.get("sku") or ""),
            mpn=str(snapshot.get("mpn") or ""),
            gtin=str(snapshot.get("gtin") or ""),
            price=_as_price(snapshot.get("price")),
            currency=str(snapshot.get("currency") or ""),
            image_url=str(snapshot.get("image_url") or ""),
            is_private_label=is_private_label(snapshot.get("brand")),
            payload=snapshot,
        )
        session.add(source)
        source_products_by_index[index] = source
    await session.flush()
    return {
        index: source.id
        for index, source in source_products_by_index.items()
        if source.id is not None
    }


async def _persist_discovery_candidates(
    session: AsyncSession,
    *,
    job: ProductIntelligenceJob,
    source_product_ids_by_index: dict[int, int],
    discovered_payloads: list[dict[str, object]],
) -> None:
    for candidate_payload in discovered_payloads:
        if (
            "source_index" not in candidate_payload
            or candidate_payload.get("source_index") is None
        ):
            continue
        source_index = _as_nonnegative_int(candidate_payload.get("source_index"))
        if source_index is None:
            continue
        source_product_id = source_product_ids_by_index.get(source_index)
        if source_product_id is None:
            continue
        payload_value = candidate_payload.get("payload")
        payload_data = payload_value if isinstance(payload_value, dict) else {}
        intelligence_value = candidate_payload.get("intelligence")
        intelligence = (
            intelligence_value if isinstance(intelligence_value, dict) else {}
        )
        candidate = ProductIntelligenceCandidate(
            job_id=job.id,
            source_product_id=source_product_id,
            url=str(candidate_payload.get("url") or ""),
            domain=str(candidate_payload.get("domain") or ""),
            source_type=str(candidate_payload.get("source_type") or ""),
            query_used=str(candidate_payload.get("query_used") or ""),
            search_rank=_as_int(candidate_payload.get("search_rank")) or 0,
            payload={**payload_data, "intelligence": intelligence},
            status=PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_DISCOVERED,
        )
        session.add(candidate)
        await session.flush()
        if intelligence:
            _add_discovery_match(
                session,
                job=job,
                source_product_id=source_product_id,
                candidate=candidate,
                candidate_payload=candidate_payload,
                intelligence=intelligence,
            )


def _add_discovery_match(
    session: AsyncSession,
    *,
    job: ProductIntelligenceJob,
    source_product_id: int,
    candidate: ProductIntelligenceCandidate,
    candidate_payload: dict[str, object],
    intelligence: dict[str, object],
) -> None:
    canonical_value = intelligence.get("canonical_record")
    canonical = canonical_value if isinstance(canonical_value, dict) else {}
    score_reasons_value = intelligence.get("score_reasons")
    score_reasons = score_reasons_value if isinstance(score_reasons_value, dict) else {}
    llm_enrichment_value = intelligence.get("llm_enrichment")
    llm_enrichment = (
        llm_enrichment_value if isinstance(llm_enrichment_value, dict) else {}
    )
    session.add(
        ProductIntelligenceMatch(
            job_id=job.id,
            source_product_id=source_product_id,
            candidate_id=candidate.id,
            candidate_record_id=None,
            score=_as_float_or_default(intelligence.get("confidence_score"), 0.0),
            score_label=str(intelligence.get("confidence_label") or ""),
            review_status=PRODUCT_INTELLIGENCE_REVIEW_PENDING,
            source_price=_as_price(candidate_payload.get("source_price")),
            candidate_price=_as_price(canonical.get("price")),
            currency=str(
                canonical.get("currency")
                or candidate_payload.get("source_currency")
                or ""
            ),
            availability=str(canonical.get("availability") or ""),
            candidate_url=str(canonical.get("url") or candidate.url),
            candidate_domain=source_domain(canonical.get("url") or candidate.url),
            score_reasons=score_reasons,
            llm_enrichment=llm_enrichment,
        )
    )


async def _load_source_rows(
    session: AsyncSession,
    *,
    user: User,
    payload: dict[str, object],
    options: dict[str, object],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for record_id in _int_list(payload.get("source_record_ids")):
        record = await require_accessible_record(
            session, record_id=record_id, user=user
        )
        rows.append(_row_from_record(record))
    if rows:
        return rows

    source_run_id = _as_int(payload.get("source_run_id"))
    if source_run_id is not None:
        run = await require_accessible_run(session, run_id=source_run_id, user=user)
        records, _ = await get_run_records(
            session,
            run.id,
            1,
            _option_int(
                options,
                "max_source_products",
                default=product_intelligence_settings.max_source_products,
            ),
        )
        return [_row_from_record(record) for record in records]

    source_records = payload.get("source_records")
    source_record_items = source_records if isinstance(source_records, list) else []
    for index, item in enumerate(source_record_items):
        if not isinstance(item, dict):
            continue
        data = dict(item.get("data") or item)
        rows.append(
            {
                "source_record_id": _as_int(item.get("id")),
                "source_run_id": _as_int(item.get("run_id")),
                "source_url": str(item.get("source_url") or data.get("url") or ""),
                "data": data,
                "index": index,
            }
        )
    return rows


def _row_data_payload(row: dict[str, object]) -> dict[str, object]:
    raw_data = row.get("data")
    if isinstance(raw_data, dict):
        return {str(key): value for key, value in raw_data.items()}
    return {}


def _resolved_source_url(
    row: dict[str, object],
    snapshot: dict[str, object],
) -> str:
    row_url = str(row.get("source_url") or "").strip()
    snapshot_url = str(snapshot.get("url") or "").strip()
    if snapshot_url and (not row_url or not looks_like_product_detail_url(row_url)):
        return snapshot_url
    return row_url or snapshot_url


def _discovered_candidate_payload(
    *,
    row: dict[str, object],
    snapshot: dict[str, object],
    candidate: object,
    intelligence: dict[str, object],
    source_index: int,
    source_url: str,
) -> dict[str, object]:
    source_price = snapshot.get("price")
    return {
        "source_record_id": _as_int(row.get("source_record_id")),
        "source_run_id": _as_int(row.get("source_run_id")),
        "source_url": source_url,
        "source_title": str(snapshot.get("title") or ""),
        "source_brand": str(snapshot.get("brand") or ""),
        "source_price": float(source_price)
        if isinstance(source_price, (Decimal, float))
        else None,
        "source_currency": str(snapshot.get("currency") or ""),
        "source_index": source_index,
        "url": str(getattr(candidate, "url", "")),
        "domain": str(getattr(candidate, "domain", "")),
        "source_type": str(getattr(candidate, "source_type", "")),
        "query_used": str(getattr(candidate, "query_used", "")),
        "search_rank": getattr(candidate, "search_rank", None),
        "payload": dict(getattr(candidate, "payload", None) or {}),
        "intelligence": intelligence,
    }


def _row_from_record(record: CrawlRecord) -> dict[str, object]:
    data = dict(record.data or {})
    data.setdefault("source_url", record.source_url)
    # Prefer data["url"] (canonical extraction URL) over record.source_url (original crawl URL).
    # data["source_url"] is populated above for downstream consumers but not used here.
    source_url = str(data.get("url") or record.source_url or "").strip()
    return {
        "source_record_id": record.id,
        "source_run_id": record.run_id,
        "source_url": source_url,
        "data": data,
    }


def _source_product_payload(
    source: ProductIntelligenceSourceProduct,
) -> dict[str, object]:
    return {
        **dict(source.payload or {}),
        "title": source.title,
        "brand": source.brand,
        "normalized_brand": source.normalized_brand,
        "price": source.price,
        "currency": source.currency,
        "image_url": source.image_url,
        "url": source.source_url,
        "sku": source.sku,
        "mpn": source.mpn,
        "gtin": source.gtin,
    }


def _normalized_options(value: object) -> dict[str, object]:
    raw = dict(value or {}) if isinstance(value, dict) else {}
    return {
        "max_source_products": _bounded_int(
            raw.get("max_source_products"),
            product_intelligence_settings.max_source_products,
        ),
        "max_candidates_per_product": _bounded_int(
            raw.get("max_candidates_per_product"),
            product_intelligence_settings.max_candidates_per_product,
        ),
        "search_provider": str(
            raw.get("search_provider")
            or product_intelligence_settings.default_search_provider
        )
        .strip()
        .lower(),
        "private_label_mode": _private_label_mode(raw.get("private_label_mode")),
        "confidence_threshold": _bounded_float(
            raw.get("confidence_threshold"),
            product_intelligence_settings.confidence_threshold,
        ),
        "allowed_domains": _string_list(raw.get("allowed_domains")),
        "excluded_domains": _string_list(raw.get("excluded_domains")),
        "llm_enrichment_enabled": bool(raw.get("llm_enrichment_enabled")),
    }


def _meets_confidence_threshold(
    score: float,
    *,
    options: dict[str, object] | None,
) -> bool:
    threshold = _bounded_float(
        (options or {}).get("confidence_threshold"),
        product_intelligence_settings.confidence_threshold,
    )
    return float(score) >= threshold


def _private_label_mode(value: object) -> str:
    mode = str(value or PRIVATE_LABEL_EXCLUDE).strip().lower()
    return (
        mode
        if mode in {PRIVATE_LABEL_EXCLUDE, PRIVATE_LABEL_FLAG, PRIVATE_LABEL_INCLUDE}
        else PRIVATE_LABEL_EXCLUDE
    )


def _bounded_int(value: object, default: int) -> int:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        parsed = int(default)
    return max(1, parsed)


def _bounded_float(value: object, default: float) -> float:
    try:
        parsed = float(value) if isinstance(value, (int, float)) else float(str(value))
    except (TypeError, ValueError):
        parsed = float(default)
    return min(max(parsed, 0.0), 1.0)


def _as_float_or_default(value: object, default: float) -> float:
    try:
        return float(value) if isinstance(value, (int, float)) else float(str(value))
    except (TypeError, ValueError):
        return default


def _as_price(value: object) -> float | None:
    return float(value) if isinstance(value, (Decimal, int, float)) else None


def _as_int(value: object) -> int | None:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _as_nonnegative_int(value: object) -> int | None:
    try:
        parsed = int(value) if isinstance(value, (int, float)) else int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _option_int(options: dict[str, object], key: str, *, default: int) -> int:
    return _bounded_int(options.get(key), default)


def _int_list(value: object) -> list[int]:
    if not isinstance(value, list):
        return []
    result: list[int] = []
    for item in value:
        parsed = _as_int(item)
        if parsed is not None:
            result.append(parsed)
    return result


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        if isinstance(value, str):
            value = [line.strip() for line in value.splitlines()]
        else:
            return []
    return [
        str(item or "").strip().lower() for item in value if str(item or "").strip()
    ]
