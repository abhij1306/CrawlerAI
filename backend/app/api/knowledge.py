from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import field_mappings
from app.core.config.knowledge_graph import (
    KG_DEFAULT_GRAPH_DEPTH,
    KG_DEFAULT_NODE_LIMIT,
    KG_MAX_GRAPH_DEPTH,
    KG_MAX_NODE_LIMIT,
)
from app.core.dependencies import get_current_user, get_db, require_admin
from app.core.domain_utils import normalize_domain
from app.core.knowledge_graph.templates import fingerprint_from_parts, normalize_route
from app.core.records.field_policy import normalize_field_key
from app.models.knowledge_graph import (
    KGClaim,
    KGEntity,
    KGExtractionContract,
    KGRelationship,
    KGSiteVersion,
)
from app.models.user import User
from app.persistence.knowledge_graph import (
    ContractInput,
    EntityInput,
    fetch_neighborhood,
    lock_site_version,
    purge_graph,
    upsert_contracts,
    upsert_entities,
)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class ContractSelectionRequest(BaseModel):
    selected_source: str
    expected_version: int | None = None
    template_id: uuid.UUID | None = None
    surface: str | None = None
    canonical_field: str | None = None


class RebuildRequest(BaseModel):
    domain: str = Field(min_length=1)
    expected_version: int | None = None


class SelectorContractRequest(BaseModel):
    domain: str = Field(min_length=1)
    url: str = Field(min_length=1)
    surface: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    css_selector: str = Field(min_length=1)
    sample_value: str | None = None
    source: str | None = None


@router.get("/sites")
async def knowledge_sites(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    rows = (
        (
            await session.execute(
                select(KGSiteVersion).order_by(KGSiteVersion.domain.asc())
            )
        )
        .scalars()
        .all()
    )
    return {"sites": [_site_payload(row) for row in rows]}


@router.get("/graph")
async def knowledge_graph(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    root_entity_id: uuid.UUID | None = None,
    domain: str = "",
    depth: Annotated[int, Query(ge=0)] = KG_DEFAULT_GRAPH_DEPTH,
    limit: Annotated[int, Query(ge=1)] = KG_DEFAULT_NODE_LIMIT,
) -> dict[str, Any]:
    bounded_depth = min(depth, KG_MAX_GRAPH_DEPTH)
    bounded_limit = min(limit, KG_MAX_NODE_LIMIT)
    if root_entity_id is None:
        normalized_domain = domain.strip().lower()
        filters = [KGEntity.status == "active"]
        if normalized_domain:
            filters.append(
                or_(
                    KGEntity.canonical_key == normalized_domain,
                    KGEntity.canonical_key.like(f"{normalized_domain}:%"),
                )
            )
        entity_ids = [
            row[0]
            for row in (
                await session.execute(
                    select(KGEntity.id)
                    .where(*filters)
                    .order_by(KGEntity.created_at.desc())
                    .limit(bounded_limit)
                )
            ).all()
        ]
    else:
        entity_ids = await fetch_neighborhood(
            session,
            root_entity_id,
            depth=bounded_depth,
            node_limit=bounded_limit,
        )
    entities = await _entities_by_id(session, entity_ids)
    relationships = await _relationships_between(session, entity_ids)
    return {
        "bounds": {"depth": bounded_depth, "limit": bounded_limit},
        "nodes": [_entity_payload(entity) for entity in entities],
        "relationships": [_relationship_payload(rel) for rel in relationships],
    }


@router.get("/entities/{entity_id}")
async def knowledge_entity(
    entity_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    entity = await session.get(KGEntity, entity_id)
    if entity is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entity not found"
        )
    claims = (
        (
            await session.execute(
                select(KGClaim)
                .where(KGClaim.entity_id == entity_id)
                .order_by(KGClaim.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return {
        "entity": _entity_payload(entity),
        "claims": [_claim_payload(row) for row in claims],
    }


@router.get("/contracts/{template_id}")
async def knowledge_contracts(
    template_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    contracts = (
        (
            await session.execute(
                select(KGExtractionContract)
                .where(KGExtractionContract.template_id == template_id)
                .order_by(KGExtractionContract.canonical_field.asc())
            )
        )
        .scalars()
        .all()
    )
    return {"contracts": [_contract_payload(row) for row in contracts]}


@router.post("/contracts/selector")
async def knowledge_selector_contract(
    payload: SelectorContractRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    domain = _resolve_contract_domain(payload.domain, payload.url)
    surface = payload.surface.strip().lower()
    field_name = normalize_field_key(payload.field_name)
    canonical_field = _canonical_contract_field(field_name)
    selector = payload.css_selector.strip()
    source = f"css_recipe:{selector}"
    route_pattern = normalize_route(payload.url, surface)
    fingerprint = fingerprint_from_parts(payload.url, surface, (), ())
    template_key = f"{domain}:{surface}:{fingerprint}"

    await lock_site_version(session, domain)
    ids = await upsert_entities(
        session,
        [
            EntityInput("site", domain, domain, {"domain": domain}),
            EntityInput(
                "page_template",
                template_key,
                f"{domain} {surface} {route_pattern}",
                {
                    "domain": domain,
                    "surface": surface,
                    "route_pattern": route_pattern,
                    "fingerprint": fingerprint,
                    "source": "selector_contract",
                },
            ),
        ],
    )
    template_id = ids[("page_template", template_key)]
    history = [
        {
            "selected_source": source,
            "selection_origin": "operator",
            "source": payload.source or "crawl_config",
            "user_id": user.id,
            "selected_at": datetime.now(UTC).isoformat(),
        }
    ]
    await upsert_contracts(
        session,
        [
            ContractInput(
                template_id=template_id,
                surface=surface,
                canonical_field=canonical_field,
                candidates=(
                    {
                        "source": source,
                        "collector_id": "css_recipe",
                        "locator": selector,
                        "field_name": field_name,
                        "proposed_by": payload.source or "crawl_config",
                    },
                ),
                latest_values=(
                    {
                        "value": payload.sample_value or "",
                        "source": source,
                        "url": payload.url,
                    },
                ),
                success_count=1,
                resolver_rule="operator_selector",
                selected_source=source,
                selection_origin="operator",
                selection_history=history,
            )
        ],
    )
    contract = (
        await session.execute(
            select(KGExtractionContract)
            .where(KGExtractionContract.template_id == template_id)
            .where(KGExtractionContract.surface == surface)
            .where(KGExtractionContract.canonical_field == canonical_field)
        )
    ).scalar_one()
    contract.selected_source = source
    contract.selection_origin = "operator"
    await session.commit()
    await session.refresh(contract)
    return {"contract": _contract_payload(contract)}


@router.put("/contracts/{contract_id}/selection")
async def knowledge_contract_selection(
    contract_id: uuid.UUID,
    payload: ContractSelectionRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    contract = await session.get(KGExtractionContract, contract_id)
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Contract not found"
        )
    _validate_contract_scope(contract, payload)
    await _check_expected_version(
        session, contract.template_id, payload.expected_version
    )
    selected_source = payload.selected_source.strip()
    if not _source_in_candidates(selected_source, contract.candidates):
        raise HTTPException(
            status_code=422,
            detail="selected_source is not a retained candidate for this contract",
        )
    history = list(contract.selection_history or [])
    history.append(
        {
            "selected_source": selected_source,
            "selection_origin": "operator",
            "user_id": user.id,
            "selected_at": datetime.now(UTC).isoformat(),
        }
    )
    contract.selected_source = selected_source
    contract.selection_origin = "operator"
    contract.selection_history = history
    await session.commit()
    await session.refresh(contract)
    return {"contract": _contract_payload(contract)}


@router.post("/rebuild")
async def knowledge_rebuild(
    payload: RebuildRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    domain = normalize_domain(payload.domain)
    site_version = await lock_site_version(session, domain)
    if (
        payload.expected_version is not None
        and site_version.current_version != payload.expected_version
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Graph version conflict",
        )
    previous_version = int(site_version.current_version or 0)
    site_version.current_version = previous_version + 1
    await session.commit()
    return {
        "domain": site_version.domain,
        "previous_version": previous_version,
        "current_version": site_version.current_version,
        "status": site_version.projection_status,
    }


@router.delete("/purge")
async def knowledge_purge(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, int]:
    result = await purge_graph(session)
    await session.commit()
    return result


@router.delete("/sites/{domain}")
async def knowledge_delete_site(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    normalized = domain.strip().lower()
    keys = (
        await session.execute(
            select(KGEntity.id).where(
                or_(
                    KGEntity.canonical_key == normalized,
                    KGEntity.canonical_key.like(f"{normalized}:%"),
                )
            )
        )
    ).all()
    entity_ids = [row[0] for row in keys]
    if entity_ids:
        await session.execute(delete(KGEntity).where(KGEntity.id.in_(entity_ids)))
    await session.execute(
        delete(KGSiteVersion).where(KGSiteVersion.domain == normalized)
    )
    await session.commit()
    return {"domain": normalized, "entities_deleted": len(entity_ids)}


async def _entities_by_id(
    session: AsyncSession, entity_ids: list[uuid.UUID]
) -> list[KGEntity]:
    if not entity_ids:
        return []
    return list(
        (await session.execute(select(KGEntity).where(KGEntity.id.in_(entity_ids))))
        .scalars()
        .all()
    )


async def _relationships_between(
    session: AsyncSession, entity_ids: list[uuid.UUID]
) -> list[KGRelationship]:
    if not entity_ids:
        return []
    return list(
        (
            await session.execute(
                select(KGRelationship)
                .where(KGRelationship.source_entity_id.in_(entity_ids))
                .where(KGRelationship.target_entity_id.in_(entity_ids))
            )
        )
        .scalars()
        .all()
    )


def _validate_contract_scope(
    contract: KGExtractionContract, payload: ContractSelectionRequest
) -> None:
    mismatches = []
    if payload.template_id is not None and payload.template_id != contract.template_id:
        mismatches.append("template_id")
    if payload.surface is not None and payload.surface != contract.surface:
        mismatches.append("surface")
    if (
        payload.canonical_field is not None
        and payload.canonical_field != contract.canonical_field
    ):
        mismatches.append("canonical_field")
    if mismatches:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Contract scope mismatch: {', '.join(mismatches)}",
        )


async def _check_expected_version(
    session: AsyncSession, template_id: uuid.UUID, expected_version: int | None
) -> None:
    if expected_version is None:
        return
    template = await session.get(KGEntity, template_id)
    domain = _domain_from_template(template)
    if not domain:
        return
    current = (
        await session.execute(
            select(KGSiteVersion.current_version).where(KGSiteVersion.domain == domain)
        )
    ).scalar_one_or_none()
    if current != expected_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Graph version conflict",
        )


def _source_in_candidates(selected_source: str, candidates: object) -> bool:
    if not selected_source:
        return False
    for row in candidates if isinstance(candidates, list) else []:
        if isinstance(row, dict) and str(row.get("source") or "") == selected_source:
            return True
    return False


def _resolve_contract_domain(domain: str, url: str) -> str:
    normalized = normalize_domain(domain)
    parsed = urlparse(url)
    url_domain = normalize_domain(parsed.netloc)
    if not normalized or not url_domain or normalized != url_domain:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Contract domain must match the selector URL domain",
        )
    return normalized


def _canonical_contract_field(field_name: str) -> str:
    return field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(field_name, field_name)


def _domain_from_template(template: KGEntity | None) -> str:
    if template is None:
        return ""
    props = template.properties if isinstance(template.properties, dict) else {}
    domain = str(props.get("domain") or "").strip().lower()
    if domain:
        return domain
    return str(template.canonical_key or "").split(":", 1)[0].strip().lower()


def _site_payload(row: KGSiteVersion) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "domain": row.domain,
        "current_version": row.current_version,
        "projection_status": row.projection_status,
        "last_projected_run_id": row.last_projected_run_id,
        "last_projected_at": row.last_projected_at.isoformat()
        if row.last_projected_at
        else None,
    }


def _entity_payload(row: KGEntity) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entity_type": row.entity_type,
        "canonical_key": row.canonical_key,
        "canonical_name": row.canonical_name,
        "properties": dict(row.properties or {}),
        "status": row.status,
    }


def _relationship_payload(row: KGRelationship) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "source_entity_id": str(row.source_entity_id),
        "target_entity_id": str(row.target_entity_id),
        "relationship_type": row.relationship_type,
        "properties": dict(row.properties or {}),
        "confidence": row.confidence,
        "status": row.status,
    }


def _claim_payload(row: KGClaim) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entity_id": str(row.entity_id),
        "fact_type": row.fact_type,
        "value": row.value,
        "confidence": row.confidence,
        "status": row.status,
        "selection_origin": row.selection_origin,
    }


def _contract_payload(row: KGExtractionContract) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "template_id": str(row.template_id),
        "surface": row.surface,
        "canonical_field": row.canonical_field,
        "candidates": list(row.candidates or []),
        "latest_values": list(row.latest_values or []),
        "success_count": row.success_count,
        "rejection_count": row.rejection_count,
        "resolver_rule": row.resolver_rule,
        "selected_source": row.selected_source,
        "selection_origin": row.selection_origin,
        "selection_history": list(row.selection_history or []),
        "status": row.status,
    }
