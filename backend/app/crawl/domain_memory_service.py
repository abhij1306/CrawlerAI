from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
)
from app.models.extraction_memory import ExtractionRecipe, ExtractionTemplate
from app.persistence.extraction_memory import ensure_template, upsert_recipe
from app.core.config.domain_profiles import DEFAULT_FALLBACK_SURFACE
from app.core.shared.field_coerce import safe_int as _safe_int


@dataclass(frozen=True)
class SelectorMemory:
    id: uuid.UUID
    domain: str
    surface: str
    platform: str | None
    selectors: dict
    created_at: datetime
    updated_at: datetime


def _normalized_selector_rule(row: dict[str, object]) -> dict[str, object]:
    return {
        "id": _safe_int(row.get("id"), default=0),
        "field_name": str(row.get("field_name") or "").strip().lower(),
        "css_selector": str(row.get("css_selector") or "").strip() or None,
        "sample_value": str(row.get("sample_value") or "").strip() or None,
        "source": str(row.get("source") or "domain_memory").strip(),
        "status": str(row.get("status") or "validated").strip(),
        "is_active": bool(row.get("is_active", True)),
        "source_run_id": _safe_int(row.get("source_run_id"), default=None),
    }


def _selector_rule_signature(row: dict[str, object]) -> tuple[str, str]:
    normalized = _normalized_selector_rule(row)
    return (
        str(normalized.get("field_name") or "").strip().lower(),
        str(normalized.get("css_selector") or "").strip(),
    )


async def load_domain_memory(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> SelectorMemory | None:
    result = await session.execute(
        select(ExtractionTemplate, ExtractionRecipe)
        .join(ExtractionRecipe, ExtractionRecipe.template_id == ExtractionTemplate.id)
        .where(
            ExtractionTemplate.domain == str(domain or "").strip().lower(),
            ExtractionTemplate.surface == str(surface or "").strip().lower(),
            ExtractionTemplate.fingerprint == "domain-default",
            ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS,
        )
        .order_by(ExtractionRecipe.updated_at.desc())
        .limit(1)
    )
    row = result.one_or_none()
    if row is None:
        return None
    template, recipe = row
    platforms = list(template.tech_signals or [])
    return SelectorMemory(
        id=recipe.id,
        domain=template.domain,
        surface=template.surface,
        platform=str(platforms[0]) if platforms else None,
        selectors=dict(recipe.payload),
        created_at=recipe.created_at,
        updated_at=recipe.updated_at,
    )


async def save_domain_memory(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    selectors: dict[str, object],
    platform: str | None = None,
) -> SelectorMemory:
    normalized_domain = str(domain or "").strip().lower()
    normalized_surface = str(surface or "").strip().lower()
    template = await ensure_template(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
        fingerprint="domain-default",
        route_pattern="/",
        tech_signals=[str(platform).strip().lower()] if platform else [],
    )
    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_DOMAIN,
        kind=EXTRACTION_RECIPE_KIND_SELECTORS,
        payload=dict(selectors or {}),
    )
    memory = await load_domain_memory(
        session, domain=normalized_domain, surface=normalized_surface
    )
    if memory is None:
        raise RuntimeError("Selector recipe was not persisted")
    return memory


def selector_rules_from_memory(
    memory: SelectorMemory | None,
) -> list[dict[str, object]]:
    if memory is None or not isinstance(memory.selectors, dict):
        return []
    return selector_rules_from_payload(memory.selectors)


def selector_rules_from_payload(value: object) -> list[dict[str, object]]:
    if not isinstance(value, dict):
        return []
    selectors = dict(value)
    rules = selectors.get("rules")
    if isinstance(rules, list):
        normalized: list[dict[str, object]] = []
        for row in rules:
            if not isinstance(row, dict):
                continue
            normalized.append(_normalized_selector_rule(row))
        return normalized

    fallback_rules: list[dict[str, object]] = []
    next_id = 1
    for field_name, payload in selectors.items():
        if str(field_name).startswith("_") or not isinstance(payload, dict):
            continue
        fallback_rules.append(
            _normalized_selector_rule(
                {
                    "id": next_id,
                    "field_name": str(field_name or "").strip().lower(),
                    "css_selector": payload.get("css_selector") or payload.get("css"),
                    "sample_value": payload.get("sample_value"),
                    "source": payload.get("source") or "domain_memory",
                    "status": payload.get("status") or "validated",
                    "is_active": bool(payload.get("is_active", True)),
                }
            )
        )
        next_id += 1
    return fallback_rules


def selector_rule_count(value: object) -> int:
    return sum(
        1
        for row in selector_rules_from_payload(value)
        if str(row.get("css_selector") or "").strip()
    )


async def list_selector_memories(session: AsyncSession) -> list[SelectorMemory]:
    rows = (
        await session.execute(
            select(ExtractionTemplate.domain, ExtractionTemplate.surface)
            .join(
                ExtractionRecipe, ExtractionRecipe.template_id == ExtractionTemplate.id
            )
            .where(
                ExtractionTemplate.fingerprint == "domain-default",
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS,
            )
            .order_by(ExtractionTemplate.domain, ExtractionTemplate.surface)
        )
    ).all()
    memories: list[SelectorMemory] = []
    for domain, surface in rows:
        memory = await load_domain_memory(session, domain=domain, surface=surface)
        if memory is not None:
            memories.append(memory)
    return memories


async def load_domain_selector_rules(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    normalized = str(surface or "").strip().lower()
    candidate_surfaces = (
        (DEFAULT_FALLBACK_SURFACE,)
        if normalized == DEFAULT_FALLBACK_SURFACE
        else (normalized, DEFAULT_FALLBACK_SURFACE)
    )
    for candidate_surface in candidate_surfaces:
        if not candidate_surface:
            continue
        memory = await load_domain_memory(
            session,
            domain=domain,
            surface=candidate_surface,
        )
        for row in selector_rules_from_memory(memory):
            key = _selector_rule_signature(row)
            if key in seen:
                continue
            seen.add(key)
            rules.append(row)
    return rules


def compose_runtime_selector_rules(
    saved_rules: list[dict[str, object]] | None,
    run_contract_rules: list[dict[str, object]] | None,
) -> list[dict[str, object]]:
    normalized_saved = [
        _normalized_selector_rule(row)
        for row in list(saved_rules or [])
        if isinstance(row, dict)
    ]
    normalized_run_contract = [
        _normalized_selector_rule(
            {
                **dict(row),
                "source": "run_config",
                "status": str(row.get("status") or "validated").strip(),
                "is_active": bool(row.get("is_active", True)),
            }
        )
        for row in list(run_contract_rules or [])
        if isinstance(row, dict)
    ]
    run_override_fields = {
        str(row.get("field_name") or "").strip().lower()
        for row in normalized_run_contract
        if str(row.get("field_name") or "").strip()
    }
    combined: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for row in normalized_saved:
        if str(row.get("field_name") or "").strip().lower() in run_override_fields:
            continue
        signature = _selector_rule_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        combined.append(row)
    for row in normalized_run_contract:
        signature = _selector_rule_signature(row)
        if signature in seen:
            continue
        seen.add(signature)
        combined.append(row)
    return combined
