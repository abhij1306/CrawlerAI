"""Compatibility routes for extraction-memory reads and operator source selection.

Live surface (every route has a production frontend caller in the Domain
Memory workspace):

- ``GET /api/knowledge/sites`` — per-domain extraction-memory site rows.
- ``GET /api/knowledge/contracts`` — stored source-selection contracts for a
  domain/surface.
- ``PUT /api/knowledge/contracts/{contract_id}/selection`` — operator source
  selection on one contract.

Handlers are thin HTTP adapters; query and projection assembly lives in
``app/persistence/extraction_memory_knowledge.py``.
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.persistence.extraction_memory_knowledge import (
    find_contract_location,
    list_domain_contracts,
    list_knowledge_site_projections,
    select_contract_source,
    store_template_contract,
)

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])


class ContractSelectionRequest(BaseModel):
    selected_source: str
    expected_version: int | None = None
    template_id: uuid.UUID | None = None
    surface: str | None = None
    canonical_field: str | None = None


@router.get("/sites")
async def knowledge_sites(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    return {
        "sites": [
            {
                "id": str(site.id),
                "domain": site.domain,
                "current_version": site.current_version,
                "projection_status": site.projection_status,
                "last_projected_run_id": site.last_projected_run_id,
                "last_projected_at": site.last_projected_at,
            }
            for site in await list_knowledge_site_projections(session)
        ]
    }


@router.get("/contracts")
async def knowledge_domain_contracts(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "",
) -> dict[str, Any]:
    return {
        "contracts": await list_domain_contracts(
            session,
            domain=domain,
            surface=surface,
        )
    }


@router.put("/contracts/{contract_id}/selection")
async def knowledge_contract_selection(
    contract_id: uuid.UUID,
    payload: ContractSelectionRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    location = await find_contract_location(session, str(contract_id))
    if location is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    template, contract = location.template, location.contract
    if payload.template_id and payload.template_id != template.id:
        raise HTTPException(status_code=409, detail="Template scope mismatch")
    if payload.surface and payload.surface != contract.get("surface"):
        raise HTTPException(status_code=409, detail="Surface scope mismatch")
    if payload.canonical_field and payload.canonical_field != contract.get(
        "canonical_field"
    ):
        raise HTTPException(status_code=409, detail="Field scope mismatch")
    candidates = {
        str(row.get("source") or "") for row in contract.get("candidates", [])
    }
    if payload.selected_source not in candidates:
        raise HTTPException(
            status_code=422, detail="Selected source is not a candidate"
        )
    updated = select_contract_source(contract, selected_source=payload.selected_source)
    await store_template_contract(session, template, updated)
    await session.commit()
    return {"contract": updated, "updated_contract_count": 1}
