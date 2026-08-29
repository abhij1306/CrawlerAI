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
from app.models.crawl_run import CrawlRecord, CrawlRun, CrawlUrlResult, RunEvent
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
from app.models.extraction_memory import ExtractionOperatorLabel, ExtractionTemplate
from app.core.config.extraction_memory import (
    EXTRACTION_LABEL_KIND_FIELD_FEEDBACK,
    EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
)
from app.models.llm import LLMCostLog
from app.persistence.extraction_memory import purge_extraction_memory
from app.acquisition.cookie_store import clear_cookie_store_cache
from app.acquisition.rate_limiter import reset_pacing_state
from app.acquisition.fetch.fetch_context import reset_fetch_runtime_state
from app.crawl.state import ACTIVE_STATUSES
from app.crawl.robots_policy import reset_robots_policy_cache
from app.core.domain_utils import normalize_domain
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


async def reset_domain_memory(session: AsyncSession) -> dict:
    async with _session_transaction(session):
        counts = await _reset_domain_memory_db(session)
        graph_counts = await purge_extraction_memory(session)
    return {
        **counts,
        **graph_counts,
        **await _reset_domain_memory_runtime_state(),
    }


async def _reset_crawl_data_db(session: AsyncSession) -> dict:
    counts = await _reset_bucket_db(
        session,
        [
            ("crawl_runs_deleted", CrawlRun),
            ("crawl_url_results_deleted", CrawlUrlResult),
            ("crawl_records_deleted", CrawlRecord),
            ("run_events_deleted", RunEvent),
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
    artifacts_dir = Path(settings.artifacts_dir).resolve()  # noqa: ASYNC240 - bounded local cleanup
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
            RunEvent,
            CrawlRecord,
            CrawlUrlResult,
            LLMCostLog,
            CrawlRun,
        ],
        "run_events",
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
