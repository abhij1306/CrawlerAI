from __future__ import annotations

import uuid
from typing import Annotated, Any
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import field_mappings
from app.core.config.extraction_memory import (
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)
from app.core.dependencies import get_current_user, get_db, require_admin
from app.core.domain_utils import normalize_domain
from app.core.extraction_memory.templates import fingerprint_from_parts, normalize_route
from app.core.records.field_policy import normalize_field_key
from app.crawl.domain_memory_service import (
    selector_rule_count,
    selector_rules_from_payload,
)
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionManifest,
    ExtractionObservation,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)
from app.models.user import User
from app.persistence.extraction_memory import (
    ensure_template,
    purge_extraction_memory,
    upsert_recipe,
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
    templates = list(
        (await session.execute(select(ExtractionTemplate))).scalars().all()
    )
    domains: dict[str, list[ExtractionTemplate]] = {}
    for template in templates:
        domains.setdefault(template.domain, []).append(template)
    return {
        "sites": [
            {
                "id": str(rows[0].id),
                "domain": domain,
                "current_version": await _site_version(session, rows),
                "projection_status": "active",
                "last_projected_run_id": max(
                    (row.last_seen_run_id or 0 for row in rows), default=0
                )
                or None,
                "last_projected_at": max(
                    (row.updated_at for row in rows), default=None
                ),
            }
            for domain, rows in sorted(domains.items())
        ]
    }


@router.get("/graph")
async def knowledge_graph(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    root_entity_id: uuid.UUID | None = None,
    domain: str = "",
    depth: int = 1,
    limit: int = 100,
) -> dict[str, Any]:
    bounded_depth, bounded_limit = min(max(depth, 0), 4), min(max(limit, 1), 500)
    query = select(ExtractionTemplate)
    if root_entity_id is not None:
        query = query.where(ExtractionTemplate.id == root_entity_id)
    if domain:
        query = query.where(ExtractionTemplate.domain == normalize_domain(domain))
    rows = list((await session.execute(query.limit(bounded_limit))).scalars().all())
    return {
        "bounds": {"depth": bounded_depth, "limit": bounded_limit},
        "nodes": [_template_node(row) for row in rows],
        "relationships": [],
    }


@router.get("/memory")
async def knowledge_memory(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    _admin: Annotated[User, Depends(require_admin)],
    domain: str = "",
) -> dict[str, Any]:
    """Read-only relational extraction-memory projection for operator UI."""
    normalized_domain = normalize_domain(domain)
    (
        templates,
        recipes,
        compiled_rows,
        observation_rows,
        manifest_rows,
        release_rows,
    ) = await _memory_rows(session, normalized_domain)
    latest_compiled = {}
    for row in compiled_rows:
        latest_compiled.setdefault(row.recipe_id, row)

    recipes_by_template: dict[uuid.UUID, list[ExtractionRecipe]] = {}
    for recipe in recipes:
        recipes_by_template.setdefault(recipe.template_id, []).append(recipe)
    verdicts_by_template: dict[uuid.UUID, dict[str, int]] = {}
    observed_at_by_template: dict[uuid.UUID, Any] = {}
    for template_id, verdict, count, observed_at in observation_rows:
        if template_id is None:
            continue
        verdicts_by_template.setdefault(template_id, {})[str(verdict)] = int(count)
        current = observed_at_by_template.get(template_id)
        if current is None or (observed_at is not None and observed_at > current):
            observed_at_by_template[template_id] = observed_at
    manifests_by_template = {
        template_id: int(count)
        for template_id, count in manifest_rows
        if template_id is not None
    }

    selector_count = sum(
        selector_rule_count(recipe.payload)
        for recipe in recipes
        if recipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS
    )
    contract_count = sum(
        len(list((recipe.payload or {}).get("contracts") or []))
        for recipe in recipes
        if recipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS
    )
    template_payloads = [
        _memory_template(
            template,
            recipes=recipes_by_template.get(template.id, []),
            latest_compiled=latest_compiled,
            verdicts=verdicts_by_template.get(template.id, {}),
            manifest_count=manifests_by_template.get(template.id, 0),
            last_observed_at=observed_at_by_template.get(template.id),
        )
        for template in templates
    ]
    return {
        "domain": normalized_domain,
        "summary": {
            "template_count": len(templates),
            "recipe_count": len(recipes),
            "selector_count": selector_count,
            "contract_count": contract_count,
            "observation_count": sum(
                sum(row.values()) for row in verdicts_by_template.values()
            ),
            "manifest_count": sum(manifests_by_template.values()),
            "release_count": sum(int(count) for _, count, _ in release_rows),
        },
        "templates": template_payloads,
        "releases": [
            {
                "surface": surface,
                "count": int(count),
                "latest_created_at": latest_created_at,
            }
            for surface, count, latest_created_at in release_rows
        ],
    }


async def _memory_rows(
    session: AsyncSession, normalized_domain: str
) -> tuple[Any, Any, Any, Any, Any, Any]:
    templates = list(
        (
            await session.execute(
                select(ExtractionTemplate)
                .where(ExtractionTemplate.domain == normalized_domain)
                .order_by(
                    ExtractionTemplate.surface, ExtractionTemplate.updated_at.desc()
                )
            )
        )
        .scalars()
        .all()
    )
    template_ids = [row.id for row in templates]
    recipes = (
        list(
            (
                await session.execute(
                    select(ExtractionRecipe)
                    .where(ExtractionRecipe.template_id.in_(template_ids))
                    .order_by(ExtractionRecipe.layer, ExtractionRecipe.kind)
                )
            )
            .scalars()
            .all()
        )
        if template_ids
        else []
    )
    recipe_ids = [row.id for row in recipes]
    compiled_rows = (
        list(
            (
                await session.execute(
                    select(CompiledExtractionRecipe)
                    .where(CompiledExtractionRecipe.recipe_id.in_(recipe_ids))
                    .order_by(CompiledExtractionRecipe.created_at.desc())
                )
            )
            .scalars()
            .all()
        )
        if recipe_ids
        else []
    )
    latest_compiled = {}
    for row in compiled_rows:
        latest_compiled.setdefault(row.recipe_id, row)

    observation_rows = (
        (
            await session.execute(
                select(
                    ExtractionObservation.template_id,
                    ExtractionObservation.verdict,
                    func.count(ExtractionObservation.id),
                    func.max(ExtractionObservation.created_at),
                )
                .where(ExtractionObservation.template_id.in_(template_ids))
                .group_by(
                    ExtractionObservation.template_id, ExtractionObservation.verdict
                )
            )
        ).all()
        if template_ids
        else []
    )
    manifest_rows = (
        (
            await session.execute(
                select(
                    ExtractionManifest.template_id, func.count(ExtractionManifest.id)
                )
                .where(ExtractionManifest.template_id.in_(template_ids))
                .group_by(ExtractionManifest.template_id)
            )
        ).all()
        if template_ids
        else []
    )
    release_rows = (
        await session.execute(
            select(
                ExtractionReleaseSnapshot.surface,
                func.count(ExtractionReleaseSnapshot.id),
                func.max(ExtractionReleaseSnapshot.created_at),
            )
            .where(ExtractionReleaseSnapshot.domain == normalized_domain)
            .group_by(ExtractionReleaseSnapshot.surface)
            .order_by(ExtractionReleaseSnapshot.surface)
        )
    ).all()
    return (
        templates,
        recipes,
        compiled_rows,
        observation_rows,
        manifest_rows,
        release_rows,
    )


@router.get("/entities/{entity_id}")
async def knowledge_entity(
    entity_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    row = await session.get(ExtractionTemplate, entity_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"entity": _template_node(row), "claims": [], "relationships": []}


@router.get("/contracts")
async def knowledge_domain_contracts(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "",
) -> dict[str, Any]:
    query = select(ExtractionTemplate)
    if domain:
        query = query.where(ExtractionTemplate.domain == normalize_domain(domain))
    if surface:
        query = query.where(ExtractionTemplate.surface == surface)
    templates = list((await session.execute(query)).scalars().all())
    contracts: list[dict] = []
    for template in templates:
        contracts.extend(await _template_contracts(session, template))
    contracts.sort(
        key=lambda row: (
            row.get("selection_origin") != "operator",
            row.get("canonical_field", ""),
        )
    )
    return {"contracts": contracts}


@router.get("/contracts/{template_id}")
async def knowledge_contracts(
    template_id: uuid.UUID,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    template = await session.get(ExtractionTemplate, template_id)
    if template is None:
        raise HTTPException(status_code=404, detail="Template not found")
    return {"contracts": await _template_contracts(session, template)}


@router.post("/contracts/selector")
async def knowledge_selector_contract(
    payload: SelectorContractRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    domain = normalize_domain(payload.domain)
    if normalize_domain(payload.url) != domain:
        raise HTTPException(status_code=422, detail="URL must belong to domain")
    template = await ensure_template(
        session,
        domain=domain,
        surface=payload.surface,
        fingerprint=fingerprint_from_parts(payload.url, payload.surface, (), ()),
        route_pattern=normalize_route(payload.url, payload.surface),
    )
    canonical_field = field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(
        normalize_field_key(payload.field_name), normalize_field_key(payload.field_name)
    )
    selected_source = f"css_recipe:{payload.css_selector.strip()}"
    contract = {
        "id": str(uuid.uuid4()),
        "template_id": str(template.id),
        "surface": payload.surface,
        "canonical_field": canonical_field,
        "candidates": [
            {"source": selected_source, "value_preview": payload.sample_value}
        ],
        "latest_values": [],
        "success_count": 0,
        "rejection_count": 0,
        "resolver_rule": "operator_selector",
        "selected_source": selected_source,
        "selection_origin": "operator",
        "selection_history": [
            {"selected_source": selected_source, "source": payload.source or "selector"}
        ],
        "status": "active",
    }
    await _store_contract(session, template, contract)
    await session.commit()
    return {"contract": contract}


@router.put("/contracts/{contract_id}/selection")
async def knowledge_contract_selection(
    contract_id: uuid.UUID,
    payload: ContractSelectionRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(get_current_user)],
) -> dict[str, Any]:
    found = await _find_contract(session, str(contract_id))
    if found is None:
        raise HTTPException(status_code=404, detail="Contract not found")
    template, contract = found
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
    contract["selected_source"] = payload.selected_source
    contract["selection_origin"] = "operator"
    history = list(contract.get("selection_history") or [])
    history.append({"selected_source": payload.selected_source, "scope": "template"})
    contract["selection_history"] = history
    await _store_contract(session, template, contract)
    await session.commit()
    return {"contract": contract, "updated_contract_count": 1}


@router.post("/rebuild")
async def knowledge_rebuild(
    payload: RebuildRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    domain = normalize_domain(payload.domain)
    versions = [
        await _recipe_version(session, row.id)
        for row in await _domain_templates(session, domain)
    ]
    current = max(versions, default=0)
    if payload.expected_version is not None and payload.expected_version != current:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Version conflict"
        )
    return {"domain": domain, "current_version": current + 1, "status": "pending"}


@router.delete("/purge")
async def knowledge_purge(
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    counts = await purge_extraction_memory(session)
    await session.commit()
    return counts


@router.delete("/sites/{domain}")
async def knowledge_delete_site(
    domain: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
) -> dict[str, Any]:
    normalized = normalize_domain(domain)
    result = await session.execute(
        delete(ExtractionTemplate).where(ExtractionTemplate.domain == normalized)
    )
    await session.commit()
    return {
        "domain": normalized,
        "deleted": int(getattr(result, "rowcount", 0) or 0),
    }


async def _domain_templates(
    session: AsyncSession, domain: str
) -> list[ExtractionTemplate]:
    return list(
        (
            await session.execute(
                select(ExtractionTemplate).where(ExtractionTemplate.domain == domain)
            )
        )
        .scalars()
        .all()
    )


async def _recipe_version(session: AsyncSession, template_id: uuid.UUID) -> int:
    versions = list(
        (
            await session.execute(
                select(ExtractionRecipe.version).where(
                    ExtractionRecipe.template_id == template_id
                )
            )
        )
        .scalars()
        .all()
    )
    return max(versions, default=1)


async def _site_version(
    session: AsyncSession, templates: list[ExtractionTemplate]
) -> int:
    versions = [await _recipe_version(session, row.id) for row in templates]
    return max(versions, default=1)


async def _template_contracts(
    session: AsyncSession, template: ExtractionTemplate
) -> list[dict]:
    recipe = await _contract_recipe(session, template.id)
    return [
        dict(row) for row in (recipe.payload.get("contracts", []) if recipe else [])
    ]


async def _contract_recipe(
    session: AsyncSession, template_id: uuid.UUID
) -> ExtractionRecipe | None:
    return (
        await session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template_id,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS,
            )
        )
    ).scalar_one_or_none()


async def _store_contract(
    session: AsyncSession, template: ExtractionTemplate, contract: dict
) -> None:
    contracts = await _template_contracts(session, template)
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


async def _find_contract(
    session: AsyncSession, contract_id: str
) -> tuple[ExtractionTemplate, dict] | None:
    for template in list(
        (await session.execute(select(ExtractionTemplate))).scalars().all()
    ):
        for contract in await _template_contracts(session, template):
            if str(contract.get("id")) == contract_id:
                return template, contract
    return None


def _template_node(row: ExtractionTemplate) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "entity_type": "page_template",
        "canonical_key": f"{row.domain}:{row.surface}:{row.fingerprint}",
        "canonical_name": row.route_pattern or row.fingerprint,
        "properties": {
            "domain": row.domain,
            "surface": row.surface,
            "route_pattern": row.route_pattern,
        },
        "status": row.status,
    }


def _memory_template(
    template: ExtractionTemplate,
    *,
    recipes: list[ExtractionRecipe],
    latest_compiled: dict[uuid.UUID, CompiledExtractionRecipe],
    verdicts: dict[str, int],
    manifest_count: int,
    last_observed_at: Any,
) -> dict[str, Any]:
    recipe_payloads = []
    for recipe in recipes:
        compiled = latest_compiled.get(recipe.id)
        recipe_payloads.append(
            {
                "id": str(recipe.id),
                "layer": recipe.layer,
                "kind": recipe.kind,
                "version": recipe.version,
                "status": recipe.status,
                "locale_policy_ref": recipe.locale_policy_ref,
                "rule_count": (
                    selector_rule_count(recipe.payload)
                    if recipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS
                    else 0
                ),
                "rules": (
                    selector_rules_from_payload(recipe.payload)
                    if recipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS
                    else []
                ),
                "contract_count": (
                    len(list((recipe.payload or {}).get("contracts") or []))
                    if recipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS
                    else 0
                ),
                "updated_at": recipe.updated_at,
                "compiled": (
                    {
                        "id": str(compiled.id),
                        "compiler_version": compiled.compiler_version,
                        "checksum": compiled.checksum,
                        "status": compiled.status,
                        "created_at": compiled.created_at,
                    }
                    if compiled is not None
                    else None
                ),
            }
        )
    return {
        "id": str(template.id),
        "surface": template.surface,
        "fingerprint": template.fingerprint,
        "route_pattern": template.route_pattern,
        "tech_signals": list(template.tech_signals or []),
        "status": template.status,
        "last_seen_run_id": template.last_seen_run_id,
        "updated_at": template.updated_at,
        "observation_count": sum(verdicts.values()),
        "observation_verdicts": verdicts,
        "manifest_count": manifest_count,
        "last_observed_at": last_observed_at,
        "recipes": recipe_payloads,
    }
