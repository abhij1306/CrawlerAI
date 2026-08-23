from __future__ import annotations

from copy import deepcopy
from typing import cast
import uuid

from cachetools import LRUCache
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_MEMORY_STATUS_TRUSTED,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_EXECUTABLE,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_ORDER,
    EXTRACTION_RELEASE_PAYLOAD_CACHE_MAX_ENTRIES,
    EXTRACTION_RELEASE_VERSION,
)
from app.core.config.domain_profiles import DEFAULT_FALLBACK_SURFACE
from app.core.domain_utils import normalize_domain
from app.models.crawl_run import CrawlRun
from app.models.extraction_memory import (
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)


class RecipeCompileError(ValueError):
    """Recipe layers cannot be merged into one bounded runtime recipe."""


def compile_recipe_layers(recipes: list[ExtractionRecipe]) -> dict[str, object]:
    """Flatten scoped recipe layers into one bounded payload."""

    selectors: dict[str, dict[str, object]] = {}
    contracts: dict[str, dict[str, object]] = {}
    provenance: list[dict[str, object]] = []
    layer_signatures: dict[tuple[str, str, str], str] = {}
    for recipe in sorted(recipes, key=_recipe_order):
        provenance.append(_recipe_provenance(recipe))
        _merge_recipe_rules(
            recipe,
            selectors=selectors,
            contracts=contracts,
            layer_signatures=layer_signatures,
        )
    return {
        "compiler_version": EXTRACTION_COMPILER_VERSION,
        "selector_rules": list(selectors.values()),
        "contracts": list(contracts.values()),
        "provenance": provenance,
    }


def _recipe_order(recipe: ExtractionRecipe) -> tuple[int, str, int, str]:
    return (_layer_rank(recipe.layer), recipe.kind, recipe.version, str(recipe.id))


def _recipe_provenance(recipe: ExtractionRecipe) -> dict[str, object]:
    return {
        "recipe_id": str(recipe.id),
        "layer": recipe.layer,
        "kind": recipe.kind,
        "version": recipe.version,
    }


def _merge_recipe_rules(
    recipe: ExtractionRecipe,
    *,
    selectors: dict[str, dict[str, object]],
    contracts: dict[str, dict[str, object]],
    layer_signatures: dict[tuple[str, str, str], str],
) -> None:
    payload = dict(recipe.payload or {})
    if recipe.kind == EXTRACTION_RECIPE_KIND_SELECTORS:
        _merge_rule_rows(
            recipe,
            rows=payload.get("rules"),
            target=selectors,
            layer_signatures=layer_signatures,
            field_keys=("field_name", "canonical_field"),
            value_key="css_selector",
        )
    elif recipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS:
        _merge_rule_rows(
            recipe,
            rows=payload.get("contracts"),
            target=contracts,
            layer_signatures=layer_signatures,
            field_keys=("canonical_field", "field_name"),
            value_key="selected_source",
        )


def _merge_rule_rows(
    recipe: ExtractionRecipe,
    *,
    rows: object,
    target: dict[str, dict[str, object]],
    layer_signatures: dict[tuple[str, str, str], str],
    field_keys: tuple[str, str],
    value_key: str,
) -> None:
    for row in _dict_rows(rows):
        field = str(row.get(field_keys[0]) or row.get(field_keys[1]) or "")
        _merge_layer_rule(
            target,
            layer_signatures,
            recipe=recipe,
            field=field,
            value=str(row.get(value_key) or ""),
            payload=dict(row),
        )


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
        template_rows.append(_release_template_row(template, recipes))
    return {
        "schema_version": EXTRACTION_RELEASE_VERSION,
        "domain": domain,
        "surface": surface,
        "templates": template_rows,
    }


def _release_template_row(
    template: ExtractionTemplate, recipes: list[ExtractionRecipe]
) -> dict[str, object]:
    compiled_recipe = compile_recipe_layers(recipes)
    row: dict[str, object] = {
        "template_id": str(template.id),
        "fingerprint": template.fingerprint,
        "surface": template.surface,
        "route_pattern": template.route_pattern,
        "status": template.status,
        "contracts": list(cast(list[dict], compiled_recipe["contracts"])),
        "selector_rules": list(cast(list[dict], compiled_recipe["selector_rules"])),
        "compiled_recipe": compiled_recipe,
    }
    executable = _executable_recipe_block(recipes)
    if executable is not None:
        row["executable_recipe"] = executable["recipe"]
        row["confidence"] = executable["confidence"]
    return row


def _executable_recipe_block(
    recipes: list[ExtractionRecipe],
) -> dict[str, object] | None:
    executable = [
        recipe
        for recipe in recipes
        if recipe.kind == EXTRACTION_RECIPE_KIND_EXECUTABLE
        and isinstance(recipe.payload, dict)
    ]
    if not executable:
        return None
    winner = max(
        executable,
        key=lambda recipe: (
            float(dict(recipe.payload).get("_confidence") or 0.0),
            recipe.version,
        ),
    )
    return {
        "recipe": {
            key: value
            for key, value in dict(winner.payload).items()
            if not str(key).startswith("_")
        },
        "confidence": float(dict(winner.payload).get("_confidence") or 0.0),
    }


def selector_rules_from_release(
    payload: dict[str, object], *, surface: str
) -> list[dict[str, object]]:
    rules: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    for candidate_surface in (surface, DEFAULT_FALLBACK_SURFACE):
        for template in _active_templates(payload, candidate_surface):
            for row in _selector_rule_rows(template):
                signature = (
                    str(row.get("field_name") or "").strip().lower(),
                    str(row.get("css_selector") or "").strip(),
                )
                if signature in seen:
                    continue
                seen.add(signature)
                rules.append(dict(row))
    return rules


def _active_templates(
    payload: dict[str, object], surface: str
) -> list[dict[str, object]]:
    raw_templates = payload.get("templates")
    templates = list(raw_templates) if isinstance(raw_templates, list) else []
    return [
        template
        for template in templates
        if isinstance(template, dict)
        and str(template.get("surface") or "") == surface
        and str(template.get("status") or "").strip().lower()
        != EXTRACTION_MEMORY_STATUS_SUSPENDED
        and not bool(template.get("sentinel_suspended"))
    ]


def _selector_rule_rows(template: dict[str, object]) -> list[dict[str, object]]:
    return _dict_rows(template.get("selector_rules"))


def _dict_rows(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


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
    return await activate_release_snapshot_for_run(
        session,
        run_id=run_id,
        release_snapshot_id=target_release_snapshot_id,
    )


_release_payload_cache: LRUCache[uuid.UUID, dict[str, object]] = LRUCache(
    maxsize=EXTRACTION_RELEASE_PAYLOAD_CACHE_MAX_ENTRIES
)


def reset_release_payload_cache() -> None:
    _release_payload_cache.clear()


async def load_release_payload(
    session: AsyncSession, release_snapshot_id: uuid.UUID | None
) -> dict[str, object]:
    if release_snapshot_id is None:
        return {}
    cached = _release_payload_cache.get(release_snapshot_id)
    if cached is not None:
        return deepcopy(cached)
    row = await session.get(ExtractionReleaseSnapshot, release_snapshot_id)
    if row is None:
        return {}
    payload = deepcopy(row.payload)
    _release_payload_cache[release_snapshot_id] = deepcopy(payload)
    return payload
