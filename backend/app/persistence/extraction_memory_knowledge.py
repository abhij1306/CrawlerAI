from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)
from app.core.domain_utils import normalize_domain
from app.models.extraction_memory import ExtractionRecipe, ExtractionTemplate
from app.persistence.extraction_memory import upsert_recipe


@dataclass(frozen=True, slots=True)
class KnowledgeSiteProjection:
    id: uuid.UUID
    domain: str
    current_version: int
    projection_status: str
    last_projected_run_id: int | None
    last_projected_at: datetime | None


@dataclass(frozen=True, slots=True)
class KnowledgeContractLocation:
    template: ExtractionTemplate
    contract: dict[str, Any]


async def list_knowledge_site_projections(
    session: AsyncSession,
) -> list[KnowledgeSiteProjection]:
    templates = list(
        (
            await session.execute(
                select(ExtractionTemplate).order_by(
                    ExtractionTemplate.domain,
                    ExtractionTemplate.id,
                )
            )
        )
        .scalars()
        .all()
    )
    version_rows = (
        await session.execute(
            select(
                ExtractionRecipe.template_id,
                func.max(ExtractionRecipe.version),
            ).group_by(ExtractionRecipe.template_id)
        )
    ).all()
    latest_version_by_template = {
        template_id: int(version)
        for template_id, version in version_rows
        if version is not None
    }
    domains: dict[str, list[ExtractionTemplate]] = {}
    for template in templates:
        domains.setdefault(template.domain, []).append(template)
    return [
        _site_projection(domain, rows, latest_version_by_template)
        for domain, rows in sorted(domains.items())
    ]


def _site_projection(
    domain: str,
    templates: list[ExtractionTemplate],
    latest_version_by_template: dict[uuid.UUID, int],
) -> KnowledgeSiteProjection:
    return KnowledgeSiteProjection(
        id=templates[0].id,
        domain=domain,
        current_version=max(
            (latest_version_by_template.get(row.id, 1) for row in templates),
            default=1,
        ),
        projection_status="active",
        last_projected_run_id=max(
            (row.last_seen_run_id or 0 for row in templates), default=0
        )
        or None,
        last_projected_at=max((row.updated_at for row in templates), default=None),
    )


async def list_template_contracts(
    session: AsyncSession, template: ExtractionTemplate
) -> list[dict[str, Any]]:
    recipe = await _contract_recipe(session, template.id)
    return [
        dict(row) for row in (recipe.payload.get("contracts", []) if recipe else [])
    ]


async def list_domain_contracts(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
) -> list[dict[str, Any]]:
    query = select(ExtractionTemplate)
    if domain:
        query = query.where(ExtractionTemplate.domain == normalize_domain(domain))
    if surface:
        query = query.where(ExtractionTemplate.surface == surface)
    templates = list((await session.execute(query)).scalars().all())
    contracts: list[dict[str, Any]] = []
    for template in templates:
        contracts.extend(await list_template_contracts(session, template))
    contracts.sort(
        key=lambda row: (
            row.get("selection_origin") != "operator",
            row.get("canonical_field", ""),
        )
    )
    return contracts


async def find_contract_location(
    session: AsyncSession, contract_id: str
) -> KnowledgeContractLocation | None:
    row = (
        await session.execute(
            select(ExtractionRecipe, ExtractionTemplate)
            .join(
                ExtractionTemplate,
                ExtractionRecipe.template_id == ExtractionTemplate.id,
            )
            .where(
                ExtractionRecipe.layer == EXTRACTION_RECIPE_LAYER_TEMPLATE,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS,
                ExtractionRecipe.payload["contracts"].contains(
                    [{"id": str(contract_id)}]
                ),
            )
            .limit(1)
        )
    ).first()
    if row is None:
        return None
    recipe, template = row
    contract = next(
        (
            dict(item)
            for item in recipe.payload.get("contracts", [])
            if str(item.get("id")) == str(contract_id)
        ),
        None,
    )
    if contract is None:
        return None
    return KnowledgeContractLocation(template=template, contract=contract)


def select_contract_source(
    contract: dict[str, Any], *, selected_source: str
) -> dict[str, Any]:
    contract["selected_source"] = selected_source
    contract["selection_origin"] = "operator"
    history = list(contract.get("selection_history") or [])
    history.append({"selected_source": selected_source, "scope": "template"})
    contract["selection_history"] = history
    return contract


async def store_template_contract(
    session: AsyncSession, template: ExtractionTemplate, contract: dict[str, Any]
) -> None:
    contracts = await list_template_contracts(session, template)
    contracts = [
        row for row in contracts if str(row.get("id")) != str(contract.get("id"))
    ]
    contracts.append(contract)
    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": contracts},
    )


async def _contract_recipe(
    session: AsyncSession, template_id: uuid.UUID
) -> ExtractionRecipe | None:
    return (
        await session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template_id,
                ExtractionRecipe.layer == EXTRACTION_RECIPE_LAYER_TEMPLATE,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS,
            )
        )
    ).scalar_one_or_none()
