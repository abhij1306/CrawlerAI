"""Knowledge Graph projection service (Slice 6).

Converts ExtractionResult observations into graph writes. This is the only
component that writes to canonical graph tables (feature spec §6.2, §8).

The projector is called at run completion and operates in a transactional batch:
it fingerprints the page template, projects entities/relationships/claims from
Evidence tuples, and updates extraction contracts with observed outcomes.

Extraction never imports this module (enforced by architecture test).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.knowledge_graph import (
    KG_CLAIM_VALUE_PREVIEW_LIMIT,
    KG_CONTRACT_RETAINED_VALUE_LIMIT,
)
from app.core.domain_utils import normalize_domain
from app.core.knowledge_graph.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_route,
)
from app.extraction.contracts import Decision, Evidence, ExtractionResult
from app.models.crawl_run import CrawlRun
from app.models.knowledge_graph import KGClaim
from app.persistence.knowledge_graph import (
    ClaimInput,
    ContractInput,
    EntityInput,
    RelationshipInput,
    add_evidence,
    compute_value_hash,
    lock_site_version,
    upsert_claims,
    upsert_contracts,
    upsert_entities,
    upsert_relationships,
)

if TYPE_CHECKING:
    import uuid


async def project_extraction_result(
    session: AsyncSession,
    run_id: int,
    url: str,
    result: ExtractionResult,
) -> dict[str, int]:
    """Project ExtractionResult into Knowledge Graph tables.

    Returns counts of entities/relationships/claims created or updated.
    """
    domain = normalize_domain(url)
    site_version = await lock_site_version(session, domain)
    source_run_id = await _existing_run_id(session, run_id)

    # Build template skeleton
    template_fingerprint = fingerprint_template(url, result.surface.value, result)
    template_key = f"{domain}:{result.surface.value}:{template_fingerprint}"
    route_pattern = normalize_route(url, result.surface.value)
    route_key = f"{domain}:{route_pattern}"

    site_entity = EntityInput(
        entity_type="site",
        canonical_key=domain,
        canonical_name=domain,
        properties={"domain": domain},
    )

    route_entity = EntityInput(
        entity_type="route_pattern",
        canonical_key=route_key,
        canonical_name=f"{domain} {route_pattern}",
        properties={"domain": domain, "pattern": route_pattern},
    )

    template_entity = EntityInput(
        entity_type="page_template",
        canonical_key=template_key,
        canonical_name=f"{domain} {result.surface.value}",
        properties={
            "domain": domain,
            "surface": result.surface.value,
            "fingerprint": template_fingerprint,
            "route_pattern": route_pattern,
        },
    )

    page_entity = EntityInput(
        entity_type="page",
        canonical_key=url,
        canonical_name=url,
        properties={"url": url, "run_id": run_id},
    )

    entity_inputs = [site_entity, route_entity, template_entity, page_entity]

    # Technology entities from collector outcomes
    tech_signals = extract_tech_signals(result)
    tech_entities: list[EntityInput] = []
    for tech in tech_signals:
        tech_key = f"{domain}:{tech}"
        tech_entities.append(
            EntityInput(
                entity_type="technology",
                canonical_key=tech_key,
                canonical_name=tech,
                properties={"name": tech},
            )
        )
    entity_inputs.extend(tech_entities)

    entity_map = await upsert_entities(session, entity_inputs)

    site_id = entity_map[("site", domain)]
    template_id = entity_map[("page_template", template_key)]
    route_id = entity_map[("route_pattern", route_key)]
    page_id = entity_map[("page", url)]

    # Build template skeleton relationships
    relationships: list[RelationshipInput] = []

    relationships.append(
        RelationshipInput(
            source_entity_id=site_id,
            target_entity_id=template_id,
            relationship_type="SITE_HAS_TEMPLATE",
        )
    )

    relationships.append(
        RelationshipInput(
            source_entity_id=template_id,
            target_entity_id=route_id,
            relationship_type="TEMPLATE_MATCHES_ROUTE",
        )
    )

    relationships.append(
        RelationshipInput(
            source_entity_id=page_id,
            target_entity_id=template_id,
            relationship_type="PAGE_INSTANCE_OF_TEMPLATE",
        )
    )

    for tech_entity in tech_entities:
        tech_id = entity_map[(tech_entity.entity_type, tech_entity.canonical_key)]
        relationships.append(
            RelationshipInput(
                source_entity_id=site_id,
                target_entity_id=tech_id,
                relationship_type="SITE_USES_TECHNOLOGY",
            )
        )

    # Project Evidence into product/offer/brand entities and claims
    # Deduplicate entities by (entity_type, canonical_key)
    seen_entities: set[tuple[str, str]] = set()
    product_entities: list[EntityInput] = []
    claim_inputs: list[ClaimInput] = []

    for evidence in result.evidence:
        if evidence.subject_scope in ("product", "offer", "brand", "category"):
            entity_type = evidence.subject_scope
            canonical_key = f"{domain}:{evidence.subject_id}"
            entity_key = (entity_type, canonical_key)

            if entity_key not in seen_entities:
                product_entities.append(
                    EntityInput(
                        entity_type=entity_type,
                        canonical_key=canonical_key,
                        canonical_name="",
                        properties={},
                    )
                )
                seen_entities.add(entity_key)

    if product_entities:
        entity_map.update(await upsert_entities(session, product_entities))

    # Build claims and PAGE_MENTIONS_PRODUCT relationships
    seen_products: set[uuid.UUID] = set()
    rejected_by_evidence_id = _rejections_by_evidence_id(result.decisions)
    claim_evidence_by_key: dict[
        tuple[uuid.UUID, str, str], list[tuple[Evidence, str | None]]
    ] = {}
    for evidence in result.evidence:
        if evidence.subject_scope in ("product", "offer", "brand", "category"):
            entity_key = (evidence.subject_scope, f"{domain}:{evidence.subject_id}")
            if entity_key in entity_map:
                entity_id = entity_map[entity_key]

                if (
                    evidence.subject_scope == "product"
                    and entity_id not in seen_products
                ):
                    relationships.append(
                        RelationshipInput(
                            source_entity_id=page_id,
                            target_entity_id=entity_id,
                            relationship_type="PAGE_MENTIONS_PRODUCT",
                        )
                    )
                    seen_products.add(entity_id)

                claim_value = {"raw": evidence.raw_value, "processed": evidence.value}
                claim_inputs.append(
                    ClaimInput(
                        entity_id=entity_id,
                        fact_type=evidence.fact_type,
                        value=claim_value,
                        confidence=evidence.confidence,
                    )
                )
                claim_key = (
                    entity_id,
                    evidence.fact_type,
                    compute_value_hash(claim_value),
                )
                claim_evidence_by_key.setdefault(claim_key, []).append(
                    (evidence, rejected_by_evidence_id.get(evidence.evidence_id))
                )

    await upsert_relationships(session, relationships)
    claim_ids = await upsert_claims(session, claim_inputs) if claim_inputs else []
    if claim_evidence_by_key:
        claim_id_by_key = await _claim_ids_by_key(session, claim_evidence_by_key)
        for key, evidence_rows in claim_evidence_by_key.items():
            claim_id = claim_id_by_key.get(key)
            if claim_id is None:
                continue
            for evidence, rejection_reason in evidence_rows:
                await add_evidence(
                    session,
                    claim_id=claim_id,
                    source_run_id=source_run_id,
                    collector=evidence.collector_id,
                    locator=evidence.locator.value if evidence.locator else "",
                    value_preview=_value_preview(evidence.value),
                    directness=evidence.directness,
                    confidence=evidence.confidence,
                    rejected=rejection_reason is not None,
                    rejection_reason=rejection_reason,
                    properties={"evidence_id": evidence.evidence_id},
                )

    # Project extraction contracts from decisions
    contract_inputs = await _project_contracts(
        session, template_id, result.surface.value, result.decisions, result.evidence
    )
    await upsert_contracts(session, contract_inputs)
    site_version.current_version = int(site_version.current_version or 0) + 1
    site_version.projection_status = "projected"
    site_version.last_projected_run_id = source_run_id
    site_version.last_projected_at = datetime.now(UTC)
    await session.flush()

    return {
        "entities_upserted": len(entity_map),
        "relationships_upserted": len(relationships),
        "claims_upserted": len(claim_ids),
        "contracts_upserted": len(contract_inputs),
    }


async def _project_contracts(
    session: AsyncSession,
    template_id: uuid.UUID,
    surface: str,
    decisions: tuple[Decision, ...],
    evidence: tuple[Evidence, ...],
) -> list[ContractInput]:
    """Project decisions into extraction contracts."""
    evidence_by_id = {e.evidence_id: e for e in evidence}
    contracts: list[ContractInput] = []

    for decision in decisions:
        canonical_field = decision.fact_type

        # Winner (first accepted evidence)
        winner = None
        if decision.accepted_evidence_ids:
            winner = evidence_by_id.get(decision.accepted_evidence_ids[0])
        selected_source = _source_descriptor(winner) if winner else ""

        # Candidates with rejection reasons
        candidates: list[dict] = []
        for rej in decision.rejected[:KG_CONTRACT_RETAINED_VALUE_LIMIT]:
            rej_evidence = evidence_by_id.get(rej.evidence_id)
            if rej_evidence:
                candidates.append(
                    {
                        "source": _source_descriptor(rej_evidence),
                        "rejected": True,
                        "reason": rej.reason,
                        "confidence": rej_evidence.confidence,
                    }
                )

        if winner:
            candidates.insert(
                0,
                {
                    "source": _source_descriptor(winner),
                    "rejected": False,
                    "reason": "",
                    "confidence": winner.confidence,
                },
            )

        # Latest values
        latest_values = []
        if winner:
            latest_values.append(
                {
                    "value": winner.value,
                    "raw": winner.raw_value,
                }
            )

        contracts.append(
            ContractInput(
                template_id=template_id,
                surface=surface,
                canonical_field=canonical_field,
                candidates=candidates[:KG_CONTRACT_RETAINED_VALUE_LIMIT],
                latest_values=latest_values[:KG_CONTRACT_RETAINED_VALUE_LIMIT],
                success_count=1 if decision.status == "resolved" else 0,
                rejection_count=len(decision.rejected),
                resolver_rule=decision.rule_id,
                selected_source=selected_source,
                selection_origin="generic",
            )
        )

    return contracts


async def _existing_run_id(session: AsyncSession, run_id: int) -> int | None:
    return (
        await session.execute(select(CrawlRun.id).where(CrawlRun.id == int(run_id)))
    ).scalar_one_or_none()


def _rejections_by_evidence_id(decisions: tuple[Decision, ...]) -> dict[str, str]:
    return {
        rejected.evidence_id: rejected.reason
        for decision in decisions
        for rejected in decision.rejected
    }


async def _claim_ids_by_key(
    session: AsyncSession,
    keys: Mapping[tuple[uuid.UUID, str, str], object],
) -> dict[tuple[uuid.UUID, str, str], uuid.UUID]:
    entity_ids = {key[0] for key in keys}
    rows = (
        await session.execute(
            select(
                KGClaim.id, KGClaim.entity_id, KGClaim.fact_type, KGClaim.value_hash
            ).where(KGClaim.entity_id.in_(entity_ids))
        )
    ).all()
    wanted = set(keys)
    result: dict[tuple[uuid.UUID, str, str], uuid.UUID] = {}
    for claim_id, entity_id, fact_type, value_hash in rows:
        key = (entity_id, fact_type, value_hash)
        if key in wanted:
            result[key] = claim_id
    return result


def _value_preview(value: object) -> str:
    if isinstance(value, str):
        text = value
    else:
        text = json.dumps(value, sort_keys=True, default=str)
    return text[:KG_CLAIM_VALUE_PREVIEW_LIMIT]


def _source_descriptor(evidence: Evidence) -> str:
    """Build human-readable source descriptor from evidence."""
    parts = [evidence.collector_id]
    if evidence.locator:
        parts.append(evidence.locator.value[:80])
    return ":".join(parts)
