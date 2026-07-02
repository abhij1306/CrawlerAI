from __future__ import annotations

import hashlib
import json
import uuid
from typing import TYPE_CHECKING, cast

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_MANIFEST_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_TRUSTED,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_ORDER,
    EXTRACTION_RELEASE_VERSION,
)
from app.core.domain_utils import normalize_domain
from app.core.config.domain_profiles import DEFAULT_FALLBACK_SURFACE
from app.core.extraction_memory.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_route,
)
from app.models.crawl_run import CrawlRun
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


class RecipeCompileError(ValueError):
    """Recipe layers cannot be merged into one bounded runtime recipe."""


def compile_recipe_layers(recipes: list[ExtractionRecipe]) -> dict[str, object]:
    """Flatten scoped recipe layers into one bounded payload.

    Higher layers may override lower layers. Two recipes at the same layer/kind
    that define different rules for the same field are ambiguous and fail
    closed.
    """

    ordered = sorted(
        recipes,
        key=lambda row: (
            _layer_rank(row.layer),
            row.kind,
            row.version,
            str(row.id),
        ),
    )
    selectors: dict[str, dict[str, object]] = {}
    contracts: dict[str, dict[str, object]] = {}
    provenance: list[dict[str, object]] = []
    layer_signatures: dict[tuple[str, str, str], str] = {}
    for recipe in ordered:
        payload = dict(recipe.payload or {})
        provenance.append(
            {
                "recipe_id": str(recipe.id),
                "layer": recipe.layer,
                "kind": recipe.kind,
                "version": recipe.version,
            }
        )
        if recipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS:
            for row in list(payload.get("rules") or []):
                if not isinstance(row, dict):
                    continue
                field = str(row.get("field_name") or row.get("canonical_field") or "")
                selector = str(row.get("css_selector") or "")
                _merge_layer_rule(
                    selectors,
                    layer_signatures,
                    recipe=recipe,
                    field=field,
                    value=selector,
                    payload=dict(row),
                )
        elif recipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS:
            for row in list(payload.get("contracts") or []):
                if not isinstance(row, dict):
                    continue
                field = str(row.get("canonical_field") or row.get("field_name") or "")
                selected = str(row.get("selected_source") or "")
                _merge_layer_rule(
                    contracts,
                    layer_signatures,
                    recipe=recipe,
                    field=field,
                    value=selected,
                    payload=dict(row),
                )
    return {
        "compiler_version": EXTRACTION_COMPILER_VERSION,
        "selector_rules": list(selectors.values()),
        "contracts": list(contracts.values()),
        "provenance": provenance,
    }


def _merge_layer_rule(
    target: dict[str, dict[str, object]],
    layer_signatures: dict[tuple[str, str, str], str],
    *,
    recipe: ExtractionRecipe,
    field: str,
    value: str,
    payload: dict[str, object],
) -> None:
    field_key = field.strip().lower()
    value_key = value.strip()
    if not field_key or not value_key:
        return
    layer_key = (recipe.layer, recipe.kind, field_key)
    existing = layer_signatures.get(layer_key)
    if existing is not None and existing != value_key:
        raise RecipeCompileError(
            f"ambiguous {recipe.kind} override for {field_key} at {recipe.layer}"
        )
    layer_signatures[layer_key] = value_key
    target[field_key] = dict(payload)


def _layer_rank(layer: str) -> int:
    try:
        return EXTRACTION_RECIPE_LAYER_ORDER.index(layer)
    except ValueError:
        return len(EXTRACTION_RECIPE_LAYER_ORDER)


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
                    ExtractionTemplate.status.in_(
                        (
                            EXTRACTION_MEMORY_STATUS_ACTIVE,
                            EXTRACTION_MEMORY_STATUS_TRUSTED,
                        )
                    ),
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
        compiled_recipe = compile_recipe_layers(recipes)
        contracts = list(cast(list[dict], compiled_recipe["contracts"]))
        selector_rules = list(cast(list[dict], compiled_recipe["selector_rules"]))
        template_rows.append(
            {
                "template_id": str(template.id),
                "fingerprint": template.fingerprint,
                "surface": template.surface,
                "route_pattern": template.route_pattern,
                "status": template.status,
                "contracts": contracts,
                "selector_rules": selector_rules,
                "compiled_recipe": compiled_recipe,
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


async def create_candidate_release_snapshot(
    session: AsyncSession, *, domain: str, surface: str
) -> ExtractionReleaseSnapshot:
    """Create an immutable candidate release without making it active for a run."""

    row = ExtractionReleaseSnapshot(
        run_id=None,
        domain=domain,
        surface=surface,
        release_version=EXTRACTION_RELEASE_VERSION,
        payload=await build_release_payload(session, domain=domain, surface=surface),
    )
    session.add(row)
    await session.flush()
    return row


async def active_release_snapshot_for_run(
    session: AsyncSession, *, run_id: int
) -> ExtractionReleaseSnapshot | None:
    return (
        await session.execute(
            select(ExtractionReleaseSnapshot).where(
                ExtractionReleaseSnapshot.run_id == run_id
            )
        )
    ).scalar_one_or_none()


async def activate_release_snapshot_for_run(
    session: AsyncSession, *, run_id: int, release_snapshot_id: uuid.UUID
) -> ExtractionReleaseSnapshot:
    """Atomically point a run at an existing immutable release snapshot."""

    run = (
        await session.execute(
            select(CrawlRun).where(CrawlRun.id == run_id).with_for_update()
        )
    ).scalar_one_or_none()
    if run is None:
        raise ValueError(f"unknown crawl run: {run_id}")
    target = (
        await session.execute(
            select(ExtractionReleaseSnapshot)
            .where(ExtractionReleaseSnapshot.id == release_snapshot_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if target is None:
        raise ValueError(f"unknown release snapshot: {release_snapshot_id}")
    if target.run_id not in {None, run_id}:
        raise ValueError("release snapshot is already active for another run")
    if target.domain != normalize_domain(run.url) or target.surface != run.surface:
        raise ValueError("release snapshot is incompatible with crawl run")
    current = await active_release_snapshot_for_run(session, run_id=run_id)
    if current is not None and current.id != target.id:
        current.run_id = None
        await session.flush()
    target.run_id = run_id
    run.extraction_release_snapshot_id = target.id
    await session.flush()
    return target


async def rollback_release_snapshot_for_run(
    session: AsyncSession, *, run_id: int, target_release_snapshot_id: uuid.UUID
) -> ExtractionReleaseSnapshot:
    """Rollback by re-pointing the run; release payload history stays immutable."""

    return await activate_release_snapshot_for_run(
        session,
        run_id=run_id,
        release_snapshot_id=target_release_snapshot_id,
    )


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
