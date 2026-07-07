# Dashboard aggregation service.
from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

from app.core.config import BASE_DIR, PROJECT_ROOT, settings
from app.models.data_enrichment import (
    DataEnrichmentJob,
    EnrichedProduct,
)
from app.models.crawl_run import CrawlLog, CrawlRecord, CrawlRun, CrawlUrlResult
from app.models.domain_memory import (
    DomainCookieMemory,
    DomainRunProfile,
    HostProtectionMemory,
)
from app.models.product_intelligence import (
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceMatch,
    ProductIntelligenceSourceProduct,
)
from app.models.extraction_memory import (
    ExtractionObservation,
    ExtractionOperatorLabel,
    ExtractionTemplate,
)
from app.core.config.extraction_memory import (
    EXTRACTION_LABEL_KIND_V3_CUTOVER,
    EXTRACTION_LABEL_KIND_FIELD_FEEDBACK,
    EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_RUNTIME_OBSERVATION_KIND,
    EXTRACTION_TIER_GENERALIZED,
    EXTRACTION_TIER_ML,
    EXTRACTION_TIER_UNKNOWN,
    RECIPE_REPAIR_QUEUE_KIND,
)
from app.models.llm import LLMCostLog
from app.persistence.extraction_memory import purge_extraction_memory
from app.acquisition.cookie_store import clear_cookie_store_cache
from app.acquisition.rate_limiter import reset_pacing_state
from app.acquisition.fetch.fetch_context import reset_fetch_runtime_state
from app.crawl.state import ACTIVE_STATUSES
from app.crawl.robots_policy import reset_robots_policy_cache
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.domain_utils import normalize_domain
from app.observability.runtime_metrics import snapshot as runtime_metrics_snapshot
from sqlalchemy import bindparam, delete, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def build_dashboard(session: AsyncSession, *, user_id: int | None = None) -> dict:
    # total_runs + active_runs in one round-trip via aggregate filter
    counts_stmt = select(
        func.count().label("total_runs"),
        func.count()
        .filter(CrawlRun.status.in_([s.value for s in ACTIVE_STATUSES]))
        .label("active_runs"),
    )
    if user_id is not None:
        counts_stmt = counts_stmt.where(CrawlRun.user_id == user_id)
    counts_row = (await session.execute(counts_stmt)).one()
    total_runs = int(counts_row.total_runs or 0)
    active_runs = int(counts_row.active_runs or 0)

    if user_id is None:
        total_records = int(
            (
                await session.execute(select(func.count()).select_from(CrawlRecord))
            ).scalar()
            or 0
        )
    else:
        total_records = int(
            (
                await session.execute(
                    select(func.count())
                    .select_from(CrawlRecord)
                    .join(CrawlRun, CrawlRun.id == CrawlRecord.run_id)
                    .where(CrawlRun.user_id == user_id)
                )
            ).scalar()
            or 0
        )
    recent_stmt = select(CrawlRun).order_by(CrawlRun.created_at.desc()).limit(10)
    if user_id is not None:
        recent_stmt = recent_stmt.where(CrawlRun.user_id == user_id)
    recent_result = await session.execute(recent_stmt)
    recent_runs = list(recent_result.scalars().all())
    # Cap to 500 most recent runs — avoids full table scan; sufficient for top-5 domains
    domain_stmt = select(CrawlRun.url).order_by(CrawlRun.created_at.desc()).limit(500)
    if user_id is not None:
        domain_stmt = domain_stmt.where(CrawlRun.user_id == user_id)
    domain_rows = await session.execute(domain_stmt)
    counts: dict[str, int] = {}
    for url in domain_rows.scalars().all():
        domain = normalize_domain(url or "") or "unknown"
        counts[domain] = counts.get(domain, 0) + 1
    top_domains = [
        {"domain": key, "count": value}
        for key, value in sorted(
            counts.items(), key=lambda item: item[1], reverse=True
        )[:5]
    ]
    return {
        "total_runs": total_runs,
        "active_runs": active_runs,
        "total_records": total_records,
        "recent_runs": recent_runs,
        "top_domains": top_domains,
    }


async def reset_application_data(session: AsyncSession) -> dict:
    async with _session_transaction(session):
        crawl_reset = await _reset_crawl_data_db(session)
        memory_reset = await _reset_domain_memory_db(session)
        graph_reset = await purge_extraction_memory(session)
        intelligence_reset = await _reset_product_intelligence_db(session)
        enrichment_reset = await _reset_data_enrichment_db(session)
    return {
        **crawl_reset,
        **await _reset_crawl_runtime_state(),
        **memory_reset,
        **graph_reset,
        **intelligence_reset,
        **enrichment_reset,
    }


async def reset_crawl_data(session: AsyncSession) -> dict:
    async with _session_transaction(session):
        counts = await _reset_crawl_data_db(session)
    return {
        **counts,
        **await _reset_crawl_runtime_state(),
    }


async def reset_domain_memory(session: AsyncSession) -> dict:
    async with _session_transaction(session):
        counts = await _reset_domain_memory_db(session)
        graph_counts = await purge_extraction_memory(session)
    return {
        **counts,
        **graph_counts,
        **await _reset_domain_memory_runtime_state(),
    }


async def reset_product_intelligence(session: AsyncSession) -> dict:
    async with _session_transaction(session):
        return await _reset_product_intelligence_db(session)


async def reset_data_enrichment(session: AsyncSession) -> dict:
    async with _session_transaction(session):
        return await _reset_data_enrichment_db(session)


async def reset_knowledge_graph(session: AsyncSession) -> dict:
    """Compatibility endpoint for explicitly purging extraction memory.

    This path removes only the graph. Domain Memory and application resets also
    remove it as part of their wider forget-everything semantics.
    """
    async with _session_transaction(session):
        return await purge_extraction_memory(session)


async def _reset_crawl_data_db(session: AsyncSession) -> dict:
    counts = await _reset_bucket_db(
        session,
        [
            ("crawl_runs_deleted", CrawlRun),
            ("crawl_url_results_deleted", CrawlUrlResult),
            ("crawl_records_deleted", CrawlRecord),
            ("crawl_logs_deleted", CrawlLog),
            ("llm_cost_logs_deleted", LLMCostLog),
        ],
    )
    counts["review_promotions_deleted"] = await _count_labels(
        session, EXTRACTION_LABEL_KIND_REVIEW_PROMOTION
    )
    await _reset_crawl_data_tables(session)
    return counts


async def _reset_domain_memory_db(session: AsyncSession) -> dict:
    counts = await _reset_bucket_db(
        session,
        [
            ("domain_run_profiles_deleted", DomainRunProfile),
            ("domain_cookie_memory_deleted", DomainCookieMemory),
            ("host_protection_memory_deleted", HostProtectionMemory),
        ],
    )
    counts["domain_field_feedback_deleted"] = await _count_labels(
        session, EXTRACTION_LABEL_KIND_FIELD_FEEDBACK
    )
    counts["domain_memory_deleted"] = int(
        await session.scalar(
            select(func.count())
            .select_from(ExtractionTemplate)
            .where(ExtractionTemplate.fingerprint == "domain-default")
        )
        or 0
    )
    await _reset_domain_memory_tables(session)
    return counts


async def _reset_product_intelligence_db(session: AsyncSession) -> dict:
    counts = await _reset_bucket_db(
        session,
        [
            ("product_intelligence_jobs_deleted", ProductIntelligenceJob),
            ("product_intelligence_sources_deleted", ProductIntelligenceSourceProduct),
            ("product_intelligence_candidates_deleted", ProductIntelligenceCandidate),
            ("product_intelligence_matches_deleted", ProductIntelligenceMatch),
        ],
    )
    await _reset_product_intelligence_tables(session)
    return counts


async def _reset_data_enrichment_db(session: AsyncSession) -> dict:
    counts = await _reset_bucket_db(
        session,
        [
            ("data_enrichment_jobs_deleted", DataEnrichmentJob),
            ("enriched_products_deleted", EnrichedProduct),
        ],
    )
    await _reset_data_enrichment_tables(session)
    return counts


async def _reset_crawl_runtime_state() -> dict:
    await reset_fetch_runtime_state()
    await reset_pacing_state()
    await reset_robots_policy_cache()

    artifacts_removed = _reset_directory(settings.artifacts_dir)
    legacy_artifacts_dir = BASE_DIR / "artifacts"
    artifacts_dir = Path(settings.artifacts_dir).resolve()
    if (
        not _looks_like_test_artifacts_dir(artifacts_dir)
        and artifacts_dir.is_relative_to(PROJECT_ROOT.resolve())
        and legacy_artifacts_dir.resolve() != artifacts_dir
    ):
        artifacts_removed += _reset_directory(
            legacy_artifacts_dir, create_if_missing=False
        )
    cookies_removed = _reset_directory(settings.cookie_store_dir)
    return {
        "artifacts_removed": artifacts_removed,
        "cookies_removed": cookies_removed,
        "knowledge_base_reset": False,
    }


def _looks_like_test_artifacts_dir(path: Path) -> bool:
    return any(str(part).startswith(".pytest") for part in path.parts)


async def _reset_domain_memory_runtime_state() -> dict:
    await clear_cookie_store_cache()
    cookies_removed = _reset_directory(settings.cookie_store_dir)
    return {
        "cookies_removed": cookies_removed,
    }


@asynccontextmanager
async def _session_transaction(session: AsyncSession):
    had_outer_transaction = session.in_transaction()
    transaction = session.begin_nested() if had_outer_transaction else session.begin()
    async with transaction:
        yield


session_transaction = _session_transaction


async def _count_rows(session: AsyncSession, model: type) -> int:
    return int(
        (await session.execute(select(func.count()).select_from(model))).scalar() or 0
    )


async def _count_labels(session: AsyncSession, label_kind: str) -> int:
    return int(
        await session.scalar(
            select(func.count())
            .select_from(ExtractionOperatorLabel)
            .where(ExtractionOperatorLabel.label_kind == label_kind)
        )
        or 0
    )


async def _reset_bucket_db(
    session: AsyncSession,
    deleted: list[tuple[str, type]],
    *,
    preserved: list[tuple[str, type]] | None = None,
    zeroed: tuple[str, ...] = (),
) -> dict[str, int]:
    counts = {key: await _count_rows(session, model) for key, model in deleted}
    counts.update({key: 0 for key in zeroed})
    if preserved:
        counts.update(
            {key: await _count_rows(session, model) for key, model in preserved}
        )
    return counts


async def _reset_crawl_data_tables(session: AsyncSession) -> None:
    await session.execute(
        delete(ExtractionOperatorLabel).where(
            ExtractionOperatorLabel.label_kind == EXTRACTION_LABEL_KIND_REVIEW_PROMOTION
        )
    )
    await _reset_bucket_tables(
        session,
        [
            CrawlLog,
            CrawlRecord,
            CrawlUrlResult,
            LLMCostLog,
            CrawlRun,
        ],
        "crawl_logs",
        "crawl_records",
        "crawl_url_results",
        "llm_cost_log",
        "crawl_runs",
    )


async def _reset_domain_memory_tables(session: AsyncSession) -> None:
    await session.execute(
        delete(ExtractionOperatorLabel).where(
            ExtractionOperatorLabel.label_kind == EXTRACTION_LABEL_KIND_FIELD_FEEDBACK
        )
    )
    await _reset_bucket_tables(
        session,
        [
            DomainCookieMemory,
            HostProtectionMemory,
            DomainRunProfile,
        ],
        "domain_cookie_memory",
        "host_protection_memory",
        "domain_run_profiles",
    )


async def _reset_product_intelligence_tables(session: AsyncSession) -> None:
    await _reset_bucket_tables(
        session,
        [
            ProductIntelligenceMatch,
            ProductIntelligenceCandidate,
            ProductIntelligenceSourceProduct,
            ProductIntelligenceJob,
        ],
        "product_intelligence_matches",
        "product_intelligence_candidates",
        "product_intelligence_source_products",
        "product_intelligence_jobs",
    )


async def _reset_data_enrichment_tables(session: AsyncSession) -> None:
    await _reset_bucket_tables(
        session,
        [EnrichedProduct, DataEnrichmentJob],
        "enriched_products",
        "data_enrichment_jobs",
    )


async def _reset_bucket_tables(
    session: AsyncSession,
    models: list[type],
    *table_names: str,
) -> None:
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    for model in models:
        await session.execute(delete(model))
    if dialect_name == "postgresql":
        await _reset_postgres_identities(session, *table_names)
        return
    if dialect_name == "sqlite" and await _sqlite_sequence_exists(session):
        statement = text(
            "DELETE FROM sqlite_sequence WHERE name IN :table_names"
        ).bindparams(bindparam("table_names", expanding=True))
        await session.execute(statement, {"table_names": tuple(table_names)})


async def _sqlite_sequence_exists(session: AsyncSession) -> bool:
    return bool(
        (
            await session.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = 'sqlite_sequence'"
                )
            )
        ).scalar()
    )


async def _reset_postgres_identities(
    session: AsyncSession,
    *table_names: str,
) -> None:
    for table_name in table_names:
        await session.execute(
            text("SELECT setval(pg_get_serial_sequence(:table_name, 'id'), 1, false)"),
            {"table_name": table_name},
        )


def _reset_directory(path, *, create_if_missing: bool = True) -> int:
    if not path.exists():
        if create_if_missing:
            path.mkdir(parents=True, exist_ok=True)
        return 0
    removed = 0
    for child in path.iterdir():
        try:
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
            if not child.exists():
                removed += 1
            else:
                logger.warning("Failed to remove path during reset: %s", child)
        except FileNotFoundError:
            removed += 1
        except PermissionError:
            logger.warning("Skipped locked path during reset: %s", child)
        except OSError:
            logger.exception("Failed to remove path during reset: %s", child)
    if create_if_missing:
        path.mkdir(parents=True, exist_ok=True)
    return removed


async def build_operational_metrics(session: AsyncSession) -> dict:
    """Build lightweight runtime + DB-backed operational metrics."""
    runtime = await runtime_metrics_snapshot()
    long_run_threshold_seconds = crawler_runtime_settings.long_run_threshold_seconds
    stalled_run_threshold_seconds = (
        crawler_runtime_settings.stalled_run_threshold_seconds
    )
    run_duration_rows = await session.execute(
        select(
            CrawlRun.created_at,
            CrawlRun.completed_at,
        )
        .where(CrawlRun.created_at.is_not(None))
        .order_by(CrawlRun.created_at.desc())
        .limit(crawler_runtime_settings.max_duration_sample_size)
    )
    durations_seconds: list[float] = []
    long_running_count = 0
    active_without_stage_count = 0
    active_stalled_no_progress_count = 0
    active_status_values = {status.value for status in ACTIVE_STATUSES}
    from datetime import UTC, datetime

    now = datetime.now(UTC)
    for created_at, completed_at in run_duration_rows:
        created_ts = (
            created_at.replace(tzinfo=UTC)
            if getattr(created_at, "tzinfo", None) is None
            else created_at.astimezone(UTC)
        )
        completed_ts = (
            completed_at.replace(tzinfo=UTC)
            if completed_at is not None
            and getattr(completed_at, "tzinfo", None) is None
            else completed_at.astimezone(UTC)
            if completed_at is not None
            else None
        )
        end_time = completed_ts or now
        duration = max(0.0, (end_time - created_ts).total_seconds())
        durations_seconds.append(duration)
    active_rows = await session.execute(
        select(CrawlRun.created_at, CrawlRun.updated_at, CrawlRun.result_summary).where(
            CrawlRun.status.in_(list(active_status_values))
        )
    )
    for created_at, updated_at, result_summary in active_rows:
        if not created_at:
            continue
        summary = result_summary if isinstance(result_summary, dict) else {}
        current_stage = str(summary.get("current_stage") or "").strip()
        created_ts = (
            created_at.replace(tzinfo=UTC)
            if getattr(created_at, "tzinfo", None) is None
            else created_at.astimezone(UTC)
        )
        active_duration = max(0.0, (now - created_ts).total_seconds())
        if active_duration >= long_run_threshold_seconds:
            long_running_count += 1
        if not current_stage:
            active_without_stage_count += 1
            if updated_at is not None:
                updated_ts = (
                    updated_at.replace(tzinfo=UTC)
                    if getattr(updated_at, "tzinfo", None) is None
                    else updated_at.astimezone(UTC)
                )
                seconds_since_update = max(0.0, (now - updated_ts).total_seconds())
                if seconds_since_update >= stalled_run_threshold_seconds:
                    active_stalled_no_progress_count += 1
    avg_duration = (
        round(sum(durations_seconds) / len(durations_seconds), 2)
        if durations_seconds
        else 0.0
    )
    extraction_v3 = await _build_extraction_v3_metrics(session)
    return {
        "runtime_counters": {
            "db_lock_errors_total": int(runtime.get("db_lock_errors_total", 0)),
            "db_lock_retries_total": int(runtime.get("db_lock_retries_total", 0)),
            "browser_launch_failures_total": int(
                runtime.get("browser_launch_failures_total", 0)
            ),
            "proxy_exhaustion_total": int(runtime.get("proxy_exhaustion_total", 0)),
        },
        "run_duration": {
            "active_long_running_threshold_seconds": long_run_threshold_seconds,
            "active_long_running_count": long_running_count,
            "average_duration_seconds": avg_duration,
        },
        "active_health": {
            "stalled_run_threshold_seconds": stalled_run_threshold_seconds,
            "active_without_stage_count": active_without_stage_count,
            "active_stalled_no_progress_count": active_stalled_no_progress_count,
        },
        "extraction_v3": extraction_v3,
    }


async def _build_extraction_v3_metrics(session: AsyncSession) -> dict:
    rows = (
        await session.execute(
            select(ExtractionObservation, ExtractionTemplate)
            .join(
                ExtractionTemplate,
                ExtractionObservation.template_id == ExtractionTemplate.id,
                isouter=True,
            )
            .order_by(ExtractionObservation.created_at.desc())
            .limit(crawler_runtime_settings.extraction_metrics_sample_size)
        )
    ).all()
    domains: dict[tuple[str, str], dict[str, object]] = {}
    repair_cost_at_stake_per_1000_usd = 0.0
    runtime_observation_count = 0
    total_cost_usd = 0.0
    for observation, template in rows:
        payload = observation.payload if isinstance(observation.payload, dict) else {}
        if payload.get("kind") == RECIPE_REPAIR_QUEUE_KIND:
            repair_cost_at_stake_per_1000_usd += _repair_cost_per_1000(payload)
            continue
        if payload.get("kind") != EXTRACTION_RUNTIME_OBSERVATION_KIND:
            continue
        runtime_observation_count += 1
        domain = template.domain if template is not None else "unknown"
        surface = template.surface if template is not None else "unknown"
        stats = _domain_extraction_metrics(domains, domain=domain, surface=surface)
        stats["page_count"] = int(stats["page_count"]) + 1
        tier = _metric_tier(str(payload.get("extractor_tier") or EXTRACTION_TIER_UNKNOWN))
        tier_split = dict(stats["tier_split"])
        tier_split[tier] = int(tier_split.get(tier, 0)) + 1
        stats["tier_split"] = tier_split
        cost_usd = _safe_float(payload.get("universal_model_cost_usd"))
        total_cost_usd += cost_usd
        stats["model_cost_usd"] = round(float(stats["model_cost_usd"]) + cost_usd, 6)
        invocations = _safe_int(payload.get("universal_model_invocation_count"))
        stats["model_invocations"] = int(stats["model_invocations"]) + invocations
        if invocations:
            stats["grounding_rate_sample_count"] = (
                int(stats["grounding_rate_sample_count"]) + invocations
            )
            stats["grounding_failure_rate_sum"] = float(
                stats["grounding_failure_rate_sum"]
            ) + _safe_float(payload.get("universal_model_ungrounded_rejection_rate"))

    domain_rows = []
    for (domain, surface), stats in sorted(domains.items()):
        page_count = max(1, int(stats["page_count"]))
        sample_count = int(stats["grounding_rate_sample_count"])
        grounding_rate = (
            round(float(stats["grounding_failure_rate_sum"]) / sample_count, 4)
            if sample_count
            else 0.0
        )
        cost_usd = float(stats["model_cost_usd"])
        domain_rows.append(
            {
                "domain": domain,
                "surface": surface,
                "page_count": int(stats["page_count"]),
                "tier_split": stats["tier_split"],
                "grounding_failure_rate": grounding_rate,
                "blended_cost_usd_per_page": round(cost_usd / page_count, 6),
                "model_invocations": int(stats["model_invocations"]),
            }
        )

    promotions_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ExtractionOperatorLabel)
            .where(
                ExtractionOperatorLabel.label_kind.in_(
                    (
                        EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
                        EXTRACTION_LABEL_KIND_V3_CUTOVER,
                    )
                )
            )
        )
        or 0
    )
    demotions_count = int(
        await session.scalar(
            select(func.count())
            .select_from(ExtractionTemplate)
            .where(ExtractionTemplate.status == EXTRACTION_MEMORY_STATUS_SUSPENDED)
        )
        or 0
    )
    return {
        "runtime_observation_count": runtime_observation_count,
        "domains": domain_rows,
        "promotion_count": promotions_count,
        "demotion_count": demotions_count,
        "repair_cost_at_stake_per_1000_usd": round(
            repair_cost_at_stake_per_1000_usd, 6
        ),
        "blended_cost_usd_per_page": round(
            total_cost_usd / runtime_observation_count, 6
        )
        if runtime_observation_count
        else 0.0,
    }


def _domain_extraction_metrics(
    domains: dict[tuple[str, str], dict[str, object]], *, domain: str, surface: str
) -> dict[str, object]:
    return domains.setdefault(
        (domain, surface),
        {
            "page_count": 0,
            "tier_split": {},
            "model_cost_usd": 0.0,
            "model_invocations": 0,
            "grounding_rate_sample_count": 0,
            "grounding_failure_rate_sum": 0.0,
        },
    )


def _metric_tier(tier: str) -> str:
    if tier == EXTRACTION_TIER_ML:
        return EXTRACTION_TIER_GENERALIZED
    return tier or EXTRACTION_TIER_UNKNOWN


def _repair_cost_per_1000(payload: dict[str, object]) -> float:
    estimate = payload.get("estimated_cost_savings_at_stake")
    if not isinstance(estimate, dict):
        return 0.0
    return _safe_float(estimate.get("per_1000_pages"))


def _safe_int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_float(value: object) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
