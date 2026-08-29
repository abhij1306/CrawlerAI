"""Frozen contract preference and runtime snapshot loading."""

from __future__ import annotations

import uuid

import pytest

from sqlalchemy import select

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.extraction_memory.contract_runtime import (
    contract_preferences,
    match_template,
    resolved_contract_outcomes,
)

from app.core.extraction_memory.templates import (
    fingerprint_from_parts,
    fingerprint_template,
)

from app.extraction.contracts import (
    CommerceDetailRecord,
    CollectorOutcome,
    Decision,
    Evidence,
    ExtractionResult,
    FieldEvidenceState,
    RejectedEvidence,
    ResolutionResult,
    SentinelObservation,
    SourceLocator,
)

from app.extraction.surfaces import Surface

from app.core.config.extraction_memory import (
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)

from app.models.crawl_run import CrawlRun, CrawlUrlResult

from app.models.extraction_memory import CompiledExtractionRecipe, ExtractionRecipe

from app.persistence.extraction_memory import (
    RecipeCompileError,
    activate_release_snapshot_for_run,
    active_release_snapshot_for_run,
    build_release_payload,
    compile_recipe_layers,
    create_candidate_release_snapshot,
    ensure_template,
    load_release_payload,
    record_extraction_result,
    rollback_release_snapshot_for_run,
    selector_rules_from_release,
    upsert_recipe,
)
from app.persistence.extraction_memory_observations import (
    _sentinel_template_in_scope,
)
from app.persistence.extraction_memory_sources import (
    merge_observed_sources as _merge_observed_sources,
)


def _evidence(
    evidence_id: str,
    collector_id: str,
    locator_value: str,
    fact_type: str,
    value: object = "test-value",
    *,
    subject_id: str = "entity-1",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        bundle_id="bundle-1",
        artifact_id="art-1",
        collector_id=collector_id,
        collector_version="1",
        fact_type=fact_type,
        raw_value=value,
        value=value,
        locator=SourceLocator(kind="json_pointer", value=locator_value),
        directness="direct",
        confidence=0.9,
        subject_id=subject_id,
    )


def _decision(
    fact_type: str,
    accepted_ids: tuple[str, ...],
    *,
    rule_id: str = "FIRST_BY_PRIORITY",
    rejected: tuple[RejectedEvidence, ...] = (),
    status: str = "resolved",
    entity_id: str = "entity-1",
) -> Decision:
    return Decision(
        decision_id=f"dec-{fact_type}",
        entity_id=entity_id,
        fact_type=fact_type,
        accepted_evidence_ids=accepted_ids,
        rejected=rejected,
        finding_ids=(),
        rule_id=rule_id,
        status=status,  # type: ignore[arg-type]
    )


def _resolution(*decisions: Decision) -> ResolutionResult:
    return ResolutionResult(
        primary_product_entity_id="entity-1",
        primary_offer_entity_id=None,
        decisions=decisions,
        derived_facts=(),
        unresolved_fact_types=(),
        blocking_finding_ids=(),
    )


def _snapshot(
    fingerprint: str,
    surface: str,
    contracts: list[dict],
    route_pattern: str = "",
) -> dict:
    return {
        "surface": surface,
        "graph_version": 1,
        "templates": [
            {
                "fingerprint": fingerprint,
                "route_pattern": route_pattern,
                "template_key": f"example.com:{surface}:{fingerprint}",
                "contracts": contracts,
            }
        ],
    }


def _recipe(layer: str, kind: str, payload: dict) -> ExtractionRecipe:
    return ExtractionRecipe(
        id=uuid.uuid4(),
        template_id=uuid.uuid4(),
        layer=layer,
        kind=kind,
        payload=payload,
        version=1,
    )


__all__ = [
    "EXTRACTION_MEMORY_STATUS_SUSPENDED",
    "EXTRACTION_RECIPE_KIND_CONTRACTS",
    "EXTRACTION_RECIPE_KIND_SELECTORS",
    "EXTRACTION_RECIPE_LAYER_DOMAIN",
    "EXTRACTION_RECIPE_LAYER_TEMPLATE",
    "AsyncSession",
    "CollectorOutcome",
    "CommerceDetailRecord",
    "CompiledExtractionRecipe",
    "CrawlRun",
    "CrawlUrlResult",
    "Decision",
    "Evidence",
    "ExtractionRecipe",
    "ExtractionResult",
    "FieldEvidenceState",
    "RecipeCompileError",
    "RejectedEvidence",
    "ResolutionResult",
    "SentinelObservation",
    "SourceLocator",
    "Surface",
    "_decision",
    "_evidence",
    "_merge_observed_sources",
    "_recipe",
    "_resolution",
    "_sentinel_template_in_scope",
    "_snapshot",
    "activate_release_snapshot_for_run",
    "active_release_snapshot_for_run",
    "build_release_payload",
    "compile_recipe_layers",
    "contract_preferences",
    "create_candidate_release_snapshot",
    "ensure_template",
    "fingerprint_from_parts",
    "fingerprint_template",
    "load_release_payload",
    "match_template",
    "pytest",
    "record_extraction_result",
    "resolved_contract_outcomes",
    "rollback_release_snapshot_for_run",
    "select",
    "selector_rules_from_release",
    "upsert_recipe",
    "uuid",
]
