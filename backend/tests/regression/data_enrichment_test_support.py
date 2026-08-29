from __future__ import annotations

import asyncio

from pathlib import Path

import pytest

from sqlalchemy import select

from sqlalchemy.exc import PendingRollbackError

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.data_enrichment import EnrichedProduct

from app.models.crawl_run import CrawlRecord

from app.schemas.data_enrichment import DataEnrichmentJobDetailResponse

from app.connectors.llm.types import LLMTaskResult

from app.core.config.data_enrichment import (
    DATA_ENRICHMENT_COLOR_FAMILY_ALIASES,
    DATA_ENRICHMENT_STATUS_DEGRADED,
    DATA_ENRICHMENT_STATUS_ENRICHED,
    DATA_ENRICHMENT_STATUS_FAILED,
    DATA_ENRICHMENT_STATUS_PENDING,
    DATA_ENRICHMENT_STATUS_RUNNING,
    DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS,
    DATA_ENRICHMENT_TAXONOMY_VERSION,
)

from app.enrichment.service import (
    run_job,
    build_deterministic_enrichment,
    build_data_enrichment_job_payload,
    create_data_enrichment_job,
    get_data_enrichment_job,
    list_data_enrichment_jobs,
)
from app.enrichment.discovery_tags import ai_discovery_allowed_tags_for_product

from app.enrichment import shopify_catalog

from app.enrichment.deterministic import normalize_price

from app.core.shared.material_terms import percentage_material_parse

from app.enrichment.deterministic import (
    category_match_values,
    category_url_context,
    plausible_size_value,
)

from app.enrichment.shopify_catalog import (
    accessory_path_conflict,
    special_token_conflict,
    sport_specific_conflict,
    taxonomy_candidate_conflicts,
    toys_vs_sports_conflict,
)

from app.enrichment.shopify_repository import TaxonomyIndex, normalize_taxonomy_token

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def _as_async(fn):
    async def _wrapped(*args, **kwargs):
        await asyncio.sleep(0)
        return fn(*args, **kwargs)

    return _wrapped


__all__ = [
    "BACKEND_ROOT",
    "DATA_ENRICHMENT_COLOR_FAMILY_ALIASES",
    "DATA_ENRICHMENT_STATUS_DEGRADED",
    "DATA_ENRICHMENT_STATUS_ENRICHED",
    "DATA_ENRICHMENT_STATUS_FAILED",
    "DATA_ENRICHMENT_STATUS_PENDING",
    "DATA_ENRICHMENT_STATUS_RUNNING",
    "DATA_ENRICHMENT_TAXONOMY_CONTEXT_ONLY_TOKENS",
    "DATA_ENRICHMENT_TAXONOMY_VERSION",
    "AsyncSession",
    "CrawlRecord",
    "DataEnrichmentJobDetailResponse",
    "EnrichedProduct",
    "LLMTaskResult",
    "Path",
    "PendingRollbackError",
    "TaxonomyIndex",
    "accessory_path_conflict",
    "ai_discovery_allowed_tags_for_product",
    "async_sessionmaker",
    "asyncio",
    "build_data_enrichment_job_payload",
    "build_deterministic_enrichment",
    "category_match_values",
    "category_url_context",
    "create_data_enrichment_job",
    "get_data_enrichment_job",
    "list_data_enrichment_jobs",
    "normalize_price",
    "normalize_taxonomy_token",
    "percentage_material_parse",
    "plausible_size_value",
    "pytest",
    "run_job",
    "select",
    "shopify_catalog",
    "special_token_conflict",
    "sport_specific_conflict",
    "taxonomy_candidate_conflicts",
    "toys_vs_sports_conflict",
]
