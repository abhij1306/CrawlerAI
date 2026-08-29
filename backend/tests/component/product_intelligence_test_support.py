from __future__ import annotations

from decimal import Decimal

import pytest

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.product_intelligence import (
    ProductIntelligenceCandidate,
    ProductIntelligenceJob,
    ProductIntelligenceMatch,
    ProductIntelligenceSourceProduct,
)

from app.models.crawl_run import CrawlRecord

from app.schemas.product_intelligence import ProductIntelligenceDiscoveryRequest

from app.core.config.product_intelligence import (
    GOOGLE_NATIVE_HOME_URL,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED,
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT,
    SOURCE_TYPE_BRAND_DTC,
    ProductIntelligenceSettings,
    product_intelligence_settings,
)

from app.connectors.llm.config_service import get_prompt_task

from app.intelligence.discovery import (
    SearchResult,
    google_native_blocked,
    google_native_session,
    parse_google_native_results,
    parse_serpapi_immersive_results,
    parse_serpapi_shopping_results,
    build_search_queries,
    classify_source_type,
    discover_candidates,
)

from app.intelligence import discovery as discovery_module

from app.intelligence.matching import (
    build_search_result_intelligence,
    extract_product_snapshot,
    extract_search_result_snapshot,
    is_private_label,
    normalize_brand,
    score_candidate,
)

from app.connectors.llm.circuit_breaker import LLMErrorCategory

from app.connectors.llm.types import LLMTaskResult

from app.intelligence.service import (
    backfill_candidate_brand,
    poll_candidate_and_score,
    resolve_source_snapshot,
    create_product_intelligence_job,
    discover_product_intelligence_candidates,
)


def _build_candidate_intelligence(
    *, brand: str = "", title: str = "Wundermost Bodysuit"
) -> dict[str, object]:
    return {
        "canonical_record": {
            "title": title,
            "brand": brand,
            "normalized_brand": normalize_brand(brand),
            "url": "https://www.lululemon.com/products/p/wundermost-bodysuit/1.html",
            "snippet": "",
            "description": "",
        },
        "confidence_score": 0.30,
        "confidence_label": "uncertain",
        "score_reasons": {"brand_match": False},
        "cleanup_source": "deterministic_google_native",
        "llm_enrichment": {"requested": False, "applied": False},
    }


__all__ = [
    "GOOGLE_NATIVE_HOME_URL",
    "PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_QUEUED",
    "PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_CRAWL_TIMEOUT",
    "SOURCE_TYPE_BRAND_DTC",
    "AsyncSession",
    "CrawlRecord",
    "Decimal",
    "LLMErrorCategory",
    "LLMTaskResult",
    "ProductIntelligenceCandidate",
    "ProductIntelligenceDiscoveryRequest",
    "ProductIntelligenceJob",
    "ProductIntelligenceMatch",
    "ProductIntelligenceSettings",
    "ProductIntelligenceSourceProduct",
    "SearchResult",
    "backfill_candidate_brand",
    "build_search_queries",
    "build_search_result_intelligence",
    "classify_source_type",
    "create_product_intelligence_job",
    "discover_candidates",
    "discover_product_intelligence_candidates",
    "discovery_module",
    "extract_product_snapshot",
    "extract_search_result_snapshot",
    "get_prompt_task",
    "google_native_blocked",
    "google_native_session",
    "is_private_label",
    "normalize_brand",
    "parse_google_native_results",
    "parse_serpapi_immersive_results",
    "parse_serpapi_shopping_results",
    "poll_candidate_and_score",
    "product_intelligence_settings",
    "pytest",
    "resolve_source_snapshot",
    "score_candidate",
    "select",
]
