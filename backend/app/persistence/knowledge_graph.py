"""Knowledge Graph repository — the only storage seam for the graph (Slice 5).

Transactional batch upserts, per-site projection serialization via site-version
row locking, bounded recursive-CTE neighbourhood reads, and the explicit graph
purge. The run-complete projector (Slices 6-8) drives these; extraction never
imports this module (enforced by the architecture ratchet).

All upserts are idempotent on their natural keys, so re-projecting a run can
never duplicate nodes, edges, claims, or contracts.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import case, delete, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.knowledge_graph import (
    KG_DEFAULT_GRAPH_DEPTH,
    KG_DEFAULT_NODE_LIMIT,
    KG_MAX_GRAPH_DEPTH,
    KG_MAX_NODE_LIMIT,
    KG_SNAPSHOT_CONTRACT_LIMIT,
    KG_SNAPSHOT_TEMPLATE_LIMIT,
)
from app.models.knowledge_graph import (
    KGAssertionEvidence,
    KGClaim,
    KGEntity,
    KGExtractionContract,
    KGRelationship,
    KGSiteVersion,
)

# Child-before-parent so cascades never fire against an already-empty parent.
_PURGE_ORDER: tuple[Any, ...] = (
    KGAssertionEvidence,
    KGExtractionContract,
    KGClaim,
    KGRelationship,
    KGEntity,
    KGSiteVersion,
)


def compute_value_hash(value: object) -> str:
    """Stable sha256 over a claim value; key-order independent."""
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class EntityInput:
    entity_type: str
    canonical_key: str
    canonical_name: str = ""
    properties: Mapping[str, object] = field(default_factory=dict)
    status: str = "active"


@dataclass(frozen=True)
class RelationshipInput:
    source_entity_id: uuid.UUID
    target_entity_id: uuid.UUID
    relationship_type: str
    properties: Mapping[str, object] = field(default_factory=dict)
    confidence: float = 1.0
    status: str = "active"


@dataclass(frozen=True)
class ClaimInput:
    entity_id: uuid.UUID
    fact_type: str
    value: object
    value_hash: str | None = None
    confidence: float = 1.0
    selection_origin: str = "generic"
    status: str = "active"


@dataclass(frozen=True)
class ContractInput:
    template_id: uuid.UUID
    surface: str
    canonical_field: str
    candidates: Sequence[object] = field(default_factory=tuple)
    latest_values: Sequence[object] = field(default_factory=tuple)
    success_count: int = 0
    rejection_count: int = 0
    resolver_rule: str = ""
    selected_source: str = ""
    selection_origin: str = "generic"
    selection_history: Sequence[object] = field(default_factory=tuple)
    status: str = "active"


async def lock_site_version(
    session: AsyncSession,
    domain: str,
) -> KGSiteVersion:
    """Get-or-create the per-domain freeze anchor under a row lock.

    Serializes concurrent per-site projection: a second projector for the same
    domain blocks on ``FOR UPDATE`` until the first transaction commits.
    """
    normalized = domain.strip().lower()
    statement = pg_insert(KGSiteVersion).values(
        id=uuid.uuid4(),
        domain=normalized,
        current_version=1,
        projection_status="pending",
        properties={},
        created_at=func.now(),
        updated_at=func.now(),
    )
    await session.execute(
        statement.on_conflict_do_nothing(index_elements=[KGSiteVersion.domain])
    )
    # Re-select with the lock held so callers always own the row.
    return (
        await session.execute(
            select(KGSiteVersion)
            .where(KGSiteVersion.domain == normalized)
            .with_for_update()
        )
    ).scalar_one()


async def upsert_entities(
    session: AsyncSession,
    entities: Iterable[EntityInput],
) -> dict[tuple[str, str], uuid.UUID]:
    """Batch-upsert entities on (entity_type, canonical_key); return id map."""
    result: dict[tuple[str, str], uuid.UUID] = {}
    rows = [
        {
            "id": uuid.uuid4(),
            "entity_type": entity.entity_type,
            "canonical_key": entity.canonical_key,
            "canonical_name": entity.canonical_name,
            "properties": dict(entity.properties),
            "status": entity.status,
        }
        for entity in entities
    ]
    if not rows:
        return result
    insert_stmt = pg_insert(KGEntity).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[KGEntity.entity_type, KGEntity.canonical_key],
        set_={
            "canonical_name": insert_stmt.excluded.canonical_name,
            "properties": insert_stmt.excluded.properties,
            "status": insert_stmt.excluded.status,
            "last_seen_at": func.now(),
        },
    ).returning(KGEntity.id, KGEntity.entity_type, KGEntity.canonical_key)
    for entity_id, entity_type, canonical_key in await session.execute(upsert_stmt):
        result[(entity_type, canonical_key)] = entity_id
    return result


async def upsert_relationships(
    session: AsyncSession,
    relationships: Iterable[RelationshipInput],
) -> int:
    """Batch-upsert edges on (source, target, type); return row count."""
    rows = [
        {
            "id": uuid.uuid4(),
            "source_entity_id": rel.source_entity_id,
            "target_entity_id": rel.target_entity_id,
            "relationship_type": rel.relationship_type,
            "properties": dict(rel.properties),
            "confidence": rel.confidence,
            "status": rel.status,
        }
        for rel in relationships
    ]
    if not rows:
        return 0
    insert_stmt = pg_insert(KGRelationship).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[
            KGRelationship.source_entity_id,
            KGRelationship.target_entity_id,
            KGRelationship.relationship_type,
        ],
        set_={
            "properties": insert_stmt.excluded.properties,
            "confidence": insert_stmt.excluded.confidence,
            "status": insert_stmt.excluded.status,
            "updated_at": func.now(),
        },
    ).returning(KGRelationship.id)
    return len((await session.execute(upsert_stmt)).all())


async def upsert_claims(
    session: AsyncSession,
    claims: Iterable[ClaimInput],
) -> list[uuid.UUID]:
    """Batch-upsert claims on (entity_id, fact_type, value_hash)."""
    rows_by_key: dict[tuple[uuid.UUID, str, str], dict[str, object]] = {}
    for claim in claims:
        value_hash = claim.value_hash or compute_value_hash(claim.value)
        rows_by_key[(claim.entity_id, claim.fact_type, value_hash)] = {
            "id": uuid.uuid4(),
            "entity_id": claim.entity_id,
            "fact_type": claim.fact_type,
            "value": claim.value,
            "value_hash": value_hash,
            "confidence": claim.confidence,
            "status": claim.status,
            "selection_origin": claim.selection_origin,
        }
    rows = list(rows_by_key.values())
    if not rows:
        return []
    insert_stmt = pg_insert(KGClaim).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[KGClaim.entity_id, KGClaim.fact_type, KGClaim.value_hash],
        set_={
            "confidence": insert_stmt.excluded.confidence,
            "status": insert_stmt.excluded.status,
            "selection_origin": insert_stmt.excluded.selection_origin,
            "updated_at": func.now(),
        },
    ).returning(KGClaim.id)
    return [row[0] for row in await session.execute(upsert_stmt)]


async def add_evidence(
    session: AsyncSession,
    *,
    claim_id: uuid.UUID | None = None,
    relationship_id: uuid.UUID | None = None,
    source_run_id: int | None = None,
    collector: str = "",
    locator: str = "",
    value_preview: str = "",
    directness: str = "",
    confidence: float = 1.0,
    rejected: bool = False,
    rejection_reason: str | None = None,
    properties: Mapping[str, object] | None = None,
) -> KGAssertionEvidence:
    """Attach bounded provenance to exactly one claim or relationship."""
    if (claim_id is None) == (relationship_id is None):
        raise ValueError("evidence must attach to exactly one claim or relationship")
    evidence = KGAssertionEvidence(
        claim_id=claim_id,
        relationship_id=relationship_id,
        source_run_id=source_run_id,
        collector=collector,
        locator=locator,
        value_preview=value_preview,
        directness=directness,
        confidence=confidence,
        rejected=rejected,
        rejection_reason=rejection_reason,
        properties=dict(properties or {}),
    )
    session.add(evidence)
    await session.flush()
    return evidence


async def upsert_contracts(
    session: AsyncSession,
    contracts: Iterable[ContractInput],
) -> int:
    """Batch-upsert contracts on (template_id, surface, canonical_field)."""
    rows = [
        {
            "id": uuid.uuid4(),
            "template_id": contract.template_id,
            "surface": contract.surface,
            "canonical_field": contract.canonical_field,
            "candidates": list(contract.candidates),
            "latest_values": list(contract.latest_values),
            "success_count": contract.success_count,
            "rejection_count": contract.rejection_count,
            "resolver_rule": contract.resolver_rule,
            "selected_source": contract.selected_source,
            "selection_origin": contract.selection_origin,
            "selection_history": list(contract.selection_history),
            "status": contract.status,
        }
        for contract in contracts
    ]
    if not rows:
        return 0
    insert_stmt = pg_insert(KGExtractionContract).values(rows)
    upsert_stmt = insert_stmt.on_conflict_do_update(
        index_elements=[
            KGExtractionContract.template_id,
            KGExtractionContract.surface,
            KGExtractionContract.canonical_field,
        ],
        set_={
            "candidates": insert_stmt.excluded.candidates,
            "latest_values": insert_stmt.excluded.latest_values,
            "success_count": insert_stmt.excluded.success_count,
            "rejection_count": insert_stmt.excluded.rejection_count,
            "resolver_rule": insert_stmt.excluded.resolver_rule,
            "selected_source": case(
                (
                    insert_stmt.excluded.selection_origin == "operator",
                    insert_stmt.excluded.selected_source,
                ),
                (
                    KGExtractionContract.selection_origin == "operator",
                    KGExtractionContract.selected_source,
                ),
                else_=insert_stmt.excluded.selected_source,
            ),
            "selection_origin": case(
                (
                    insert_stmt.excluded.selection_origin == "operator",
                    insert_stmt.excluded.selection_origin,
                ),
                (
                    KGExtractionContract.selection_origin == "operator",
                    KGExtractionContract.selection_origin,
                ),
                else_=insert_stmt.excluded.selection_origin,
            ),
            "selection_history": case(
                (
                    insert_stmt.excluded.selection_origin == "operator",
                    KGExtractionContract.selection_history.op("||")(
                        insert_stmt.excluded.selection_history
                    ),
                ),
                (
                    KGExtractionContract.selection_origin == "operator",
                    KGExtractionContract.selection_history,
                ),
                else_=insert_stmt.excluded.selection_history,
            ),
            "status": insert_stmt.excluded.status,
            "updated_at": func.now(),
        },
    ).returning(KGExtractionContract.id)
    return len((await session.execute(upsert_stmt)).all())


def _clamp(value: int, default: int, maximum: int) -> int:
    if value <= 0:
        return default
    return min(value, maximum)


async def fetch_neighborhood(
    session: AsyncSession,
    root_entity_id: uuid.UUID,
    *,
    depth: int = KG_DEFAULT_GRAPH_DEPTH,
    node_limit: int = KG_DEFAULT_NODE_LIMIT,
) -> list[uuid.UUID]:
    """Return entity ids within ``depth`` hops of the root, bounded by limit.

    A recursive CTE walks ``kg_relationships`` in both directions; the result is
    bounded by ``node_limit`` so the read can never fan out unboundedly.
    """
    bounded_depth = _clamp(depth, KG_DEFAULT_GRAPH_DEPTH, KG_MAX_GRAPH_DEPTH)
    bounded_limit = _clamp(node_limit, KG_DEFAULT_NODE_LIMIT, KG_MAX_NODE_LIMIT)
    statement = text(
        """
        WITH RECURSIVE neighbourhood(entity_id, hop) AS (
            SELECT CAST(:root AS UUID) AS entity_id, 0 AS hop
            UNION
            SELECT next_id, n.hop + 1
            FROM neighbourhood n
            JOIN LATERAL (
                SELECT r.target_entity_id AS next_id
                FROM kg_relationships r
                WHERE r.source_entity_id = n.entity_id
                UNION
                SELECT r.source_entity_id AS next_id
                FROM kg_relationships r
                WHERE r.target_entity_id = n.entity_id
            ) edges ON TRUE
            WHERE n.hop < :max_depth
        )
        SELECT DISTINCT entity_id FROM neighbourhood LIMIT :node_limit
        """
    ).bindparams(
        root=str(root_entity_id),
        max_depth=bounded_depth,
        node_limit=bounded_limit,
    )
    return [row[0] for row in await session.execute(statement)]


async def count_graph_rows(session: AsyncSession) -> dict[str, int]:
    """Row counts per KG table — used by reset reporting and tests."""
    counts: dict[str, int] = {}
    for model in _PURGE_ORDER:
        counts[model.__tablename__] = int(
            (await session.execute(select(func.count()).select_from(model))).scalar()
            or 0
        )
    return counts


async def purge_graph(session: AsyncSession) -> dict[str, int]:
    """Delete the entire Knowledge Graph; leaves all other tables untouched."""
    counts = await count_graph_rows(session)
    for model in _PURGE_ORDER:
        await session.execute(delete(model))
    return {f"{table}_deleted": value for table, value in counts.items()}


async def load_runtime_snapshot(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> dict[str, object]:
    """Freeze graph contracts into a runtime snapshot for extraction.

    Loads bounded templates and their contracts for (domain, surface) at run
    creation time. The returned dict is stored as extraction_runtime_snapshot on
    the CrawlRun and passed to the engine as ExtractionRequest.runtime_snapshot.
    Returns {} when no templates exist yet (first crawl of a domain).
    """
    normalized = domain.strip().lower()
    prefix = f"{normalized}:{surface}:"

    template_rows = (
        await session.execute(
            select(KGEntity.id, KGEntity.canonical_key, KGEntity.properties)
            .where(KGEntity.entity_type == "page_template")
            .where(KGEntity.canonical_key.like(f"{prefix}%"))
            .where(KGEntity.status == "active")
            .limit(KG_SNAPSHOT_TEMPLATE_LIMIT)
        )
    ).all()

    if not template_rows:
        return {}

    template_ids = [row[0] for row in template_rows]
    template_meta: dict[uuid.UUID, dict[str, object]] = {
        row[0]: {"key": row[1], "props": dict(row[2] or {})} for row in template_rows
    }

    contract_rows = (
        await session.execute(
            select(
                KGExtractionContract.template_id,
                KGExtractionContract.canonical_field,
                KGExtractionContract.selected_source,
                KGExtractionContract.selection_origin,
                KGExtractionContract.resolver_rule,
            )
            .where(KGExtractionContract.template_id.in_(template_ids))
            .where(KGExtractionContract.surface == surface)
            .where(KGExtractionContract.status == "active")
        )
    ).all()

    contracts_by_template: dict[uuid.UUID, list[dict[str, object]]] = {
        tid: [] for tid in template_ids
    }
    for (
        template_id,
        canonical_field,
        selected_source,
        selection_origin,
        resolver_rule,
    ) in contract_rows:
        bucket = contracts_by_template.get(template_id)
        if bucket is not None and len(bucket) < KG_SNAPSHOT_CONTRACT_LIMIT:
            bucket.append(
                {
                    "canonical_field": canonical_field,
                    "selected_source": selected_source,
                    "selection_origin": selection_origin,
                    "resolver_rule": resolver_rule,
                }
            )

    version = (
        await session.execute(
            select(KGSiteVersion.current_version).where(
                KGSiteVersion.domain == normalized
            )
        )
    ).scalar_one_or_none()

    templates = []
    for tid, meta in template_meta.items():
        props = meta["props"]
        fingerprint = (
            str(props.get("fingerprint", "")) if isinstance(props, Mapping) else ""
        )
        if not fingerprint:
            continue
        templates.append(
            {
                "fingerprint": fingerprint,
                "route_pattern": (
                    str(props.get("route_pattern", ""))
                    if isinstance(props, Mapping)
                    else ""
                ),
                "template_key": meta["key"],
                "contracts": contracts_by_template.get(tid, []),
            }
        )

    return {
        "surface": surface,
        "graph_version": version or 0,
        "templates": templates,
    }
