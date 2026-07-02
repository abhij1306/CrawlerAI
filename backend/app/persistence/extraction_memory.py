from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_MANIFEST_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_RELEASE_VERSION,
)
from app.core.domain_utils import normalize_domain
from app.core.config.domain_profiles import DEFAULT_FALLBACK_SURFACE
from app.core.extraction_memory.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_route,
)
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionManifest,
    ExtractionObservation,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)

if TYPE_CHECKING:
    from app.extraction.contracts import ExtractionResult


def _checksum(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


async def ensure_template(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    fingerprint: str,
    route_pattern: str = "",
    tech_signals: list[str] | None = None,
    run_id: int | None = None,
) -> ExtractionTemplate:
    normalized_domain = str(domain or "").strip().lower()
    row = (
        await session.execute(
            select(ExtractionTemplate).where(
                ExtractionTemplate.domain == normalized_domain,
                ExtractionTemplate.surface == surface,
                ExtractionTemplate.fingerprint == fingerprint,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ExtractionTemplate(
            domain=normalized_domain,
            surface=surface,
            fingerprint=fingerprint,
            route_pattern=route_pattern,
            tech_signals=list(tech_signals or []),
            last_seen_run_id=run_id,
        )
        session.add(row)
    else:
        row.route_pattern = route_pattern or row.route_pattern
        row.tech_signals = list(tech_signals or row.tech_signals)
        row.last_seen_run_id = run_id or row.last_seen_run_id
    await session.flush()
    return row


async def upsert_recipe(
    session: AsyncSession,
    *,
    template: ExtractionTemplate,
    layer: str,
    kind: str,
    payload: dict,
    locale_policy_ref: str | None = None,
) -> tuple[ExtractionRecipe, CompiledExtractionRecipe]:
    recipe = (
        await session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.layer == layer,
                ExtractionRecipe.kind == kind,
            )
        )
    ).scalar_one_or_none()
    if recipe is None:
        recipe = ExtractionRecipe(
            template_id=template.id,
            layer=layer,
            kind=kind,
            payload=dict(payload),
            locale_policy_ref=locale_policy_ref,
        )
        session.add(recipe)
        await session.flush()
    elif recipe.payload != payload or recipe.locale_policy_ref != locale_policy_ref:
        recipe.payload = dict(payload)
        recipe.locale_policy_ref = locale_policy_ref
        recipe.version += 1
        await session.flush()
    checksum = _checksum(recipe.payload)
    compiled = (
        await session.execute(
            select(CompiledExtractionRecipe).where(
                CompiledExtractionRecipe.recipe_id == recipe.id,
                CompiledExtractionRecipe.checksum == checksum,
            )
        )
    ).scalar_one_or_none()
    if compiled is None:
        compiled = CompiledExtractionRecipe(
            recipe_id=recipe.id,
            compiler_version=EXTRACTION_COMPILER_VERSION,
            checksum=checksum,
            payload=dict(recipe.payload),
        )
        session.add(compiled)
        await session.flush()
    return recipe, compiled


async def build_release_payload(
    session: AsyncSession, *, domain: str, surface: str
) -> dict[str, object]:
    templates = list(
        (
            await session.execute(
                select(ExtractionTemplate).where(
                    ExtractionTemplate.domain == str(domain or "").strip().lower(),
                    ExtractionTemplate.surface.in_((surface, DEFAULT_FALLBACK_SURFACE)),
                    ExtractionTemplate.status == EXTRACTION_MEMORY_STATUS_ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    template_rows: list[dict[str, object]] = []
    for template in templates:
        recipes = list(
            (
                await session.execute(
                    select(ExtractionRecipe).where(
                        ExtractionRecipe.template_id == template.id,
                        ExtractionRecipe.status == EXTRACTION_MEMORY_STATUS_ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        )
        contracts: list[dict] = []
        selector_rules: list[dict] = []
        for recipe in recipes:
            if recipe.kind == "contracts":
                contracts.extend(list(recipe.payload.get("contracts") or []))
            elif recipe.kind == "selectors":
                selector_rules.extend(list(recipe.payload.get("rules") or []))
        template_rows.append(
            {
                "template_id": str(template.id),
                "fingerprint": template.fingerprint,
                "surface": template.surface,
                "route_pattern": template.route_pattern,
                "contracts": contracts,
                "selector_rules": selector_rules,
            }
        )
    return {"domain": domain, "surface": surface, "templates": template_rows}


def selector_rules_from_release(
    payload: dict[str, object], *, surface: str
) -> list[dict[str, object]]:
    raw_templates = payload.get("templates")
    templates = list(raw_templates) if isinstance(raw_templates, list) else []
    ordered_surfaces = (surface, DEFAULT_FALLBACK_SURFACE)
    rules: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for candidate_surface in ordered_surfaces:
        for template in templates:
            if not isinstance(template, dict):
                continue
            if str(template.get("surface") or "") != candidate_surface:
                continue
            for row in list(template.get("selector_rules") or []):
                if not isinstance(row, dict):
                    continue
                signature = (
                    str(row.get("field_name") or "").strip().lower(),
                    str(row.get("css_selector") or "").strip(),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                rules.append(dict(row))
    return rules


async def create_release_snapshot(
    session: AsyncSession, *, run_id: int, domain: str, surface: str
) -> ExtractionReleaseSnapshot:
    row = ExtractionReleaseSnapshot(
        run_id=run_id,
        domain=domain,
        surface=surface,
        release_version=EXTRACTION_RELEASE_VERSION,
        payload=await build_release_payload(session, domain=domain, surface=surface),
    )
    session.add(row)
    await session.flush()
    return row


async def load_release_payload(
    session: AsyncSession, release_snapshot_id: uuid.UUID | None
) -> dict[str, object]:
    if release_snapshot_id is None:
        return {}
    row = await session.get(ExtractionReleaseSnapshot, release_snapshot_id)
    return dict(row.payload) if row is not None else {}


async def record_extraction_result(
    session: AsyncSession,
    *,
    run_id: int,
    url_result_id: int,
    release_snapshot_id: uuid.UUID | None,
    url: str,
    surface: str,
    result: ExtractionResult,
) -> ExtractionManifest:
    template = await ensure_template(
        session,
        domain=normalize_domain(url),
        surface=surface,
        fingerprint=fingerprint_template(url, surface, result),
        route_pattern=normalize_route(url, surface),
        tech_signals=extract_tech_signals(result),
        run_id=run_id,
    )
    observation = ExtractionObservation(
        template_id=template.id,
        run_id=run_id,
        url_result_id=url_result_id,
        verdict=result.verdict,
        payload={
            "record_count": len(result.records),
            "finding_rule_ids": sorted({row.rule_id for row in result.findings}),
            "contract_outcomes": [
                row.model_dump(mode="json") for row in result.contract_outcomes
            ],
        },
    )
    session.add(observation)
    manifest = (
        await session.execute(
            select(ExtractionManifest).where(
                ExtractionManifest.url_result_id == url_result_id
            )
        )
    ).scalar_one_or_none()
    manifest_payload = {
        "fingerprint": template.fingerprint,
        "route_pattern": template.route_pattern,
    }
    if manifest is None:
        manifest = ExtractionManifest(
            run_id=run_id,
            url_result_id=url_result_id,
            release_snapshot_id=release_snapshot_id,
            template_id=template.id,
            manifest_version=EXTRACTION_MANIFEST_VERSION,
            payload=manifest_payload,
        )
        session.add(manifest)
    else:
        manifest.release_snapshot_id = release_snapshot_id
        manifest.template_id = template.id
        manifest.payload = manifest_payload
    await session.flush()
    return manifest


async def purge_extraction_memory(session: AsyncSession) -> dict[str, int]:
    models = (
        ExtractionManifest,
        ExtractionObservation,
        ExtractionReleaseSnapshot,
        CompiledExtractionRecipe,
        ExtractionRecipe,
        ExtractionTemplate,
    )
    counts: dict[str, int] = {}
    for model in models:
        key = f"{model.__tablename__}_deleted"
        counts[key] = int(
            await session.scalar(select(func.count()).select_from(model)) or 0
        )
        await session.execute(delete(model))
    return counts
