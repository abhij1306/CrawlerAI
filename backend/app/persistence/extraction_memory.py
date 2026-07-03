from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import hashlib
import json
import uuid
from typing import TYPE_CHECKING, cast

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_CONTRACT_CANDIDATE_LIMIT,
    EXTRACTION_CONTRACT_HISTORY_LIMIT,
    EXTRACTION_CONTRACT_OBSERVABLE_VERDICTS,
    EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
    EXTRACTION_CONTRACT_RESOLVER_OBSERVED,
    EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC,
    EXTRACTION_MANIFEST_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_MEMORY_STATUS_TRUSTED,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    EXTRACTION_RECIPE_LAYER_ORDER,
    EXTRACTION_RELEASE_VERSION,
    SENTINEL_CRITICAL_DRIFT_CONFIRMATION_THRESHOLD,
    SENTINEL_OBSERVATION_KIND,
    SENTINEL_SUSPENSION_KIND,
)
from app.core.domain_utils import normalize_domain
from app.core.config.domain_profiles import DEFAULT_FALLBACK_SURFACE
from app.core.extraction_memory.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_source_pattern,
    normalize_route,
    source_pattern,
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
    merge_payload: Callable[[dict], dict] | None = None,
) -> tuple[ExtractionRecipe, CompiledExtractionRecipe]:
    def next_payload(existing: dict | None = None) -> dict:
        if merge_payload is None:
            return dict(payload)
        return dict(merge_payload(deepcopy(existing or {})))

    recipe = (
        await session.execute(
            select(ExtractionRecipe)
            .where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.layer == layer,
                ExtractionRecipe.kind == kind,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    created = False
    if recipe is None:
        recipe = ExtractionRecipe(
            template_id=template.id,
            layer=layer,
            kind=kind,
            payload=next_payload(),
            locale_policy_ref=locale_policy_ref,
        )
        try:
            async with session.begin_nested():
                session.add(recipe)
                await session.flush()
            created = True
        except IntegrityError:
            recipe = (
                await session.execute(
                    select(ExtractionRecipe)
                    .where(
                        ExtractionRecipe.template_id == template.id,
                        ExtractionRecipe.layer == layer,
                        ExtractionRecipe.kind == kind,
                    )
                    .with_for_update()
                )
            ).scalar_one()
    if not created:
        merged_payload = next_payload(recipe.payload)
        if (
            recipe.payload != merged_payload
            or recipe.locale_policy_ref != locale_policy_ref
        ):
            recipe.payload = merged_payload
            recipe.locale_policy_ref = locale_policy_ref
            recipe.version += 1
            await session.flush()
    elif recipe.locale_policy_ref != locale_policy_ref:
        recipe.locale_policy_ref = locale_policy_ref
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
        try:
            async with session.begin_nested():
                session.add(compiled)
                await session.flush()
        except IntegrityError:
            compiled = (
                await session.execute(
                    select(CompiledExtractionRecipe).where(
                        CompiledExtractionRecipe.recipe_id == recipe.id,
                        CompiledExtractionRecipe.checksum == checksum,
                    )
                )
            ).scalar_one()
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
            if str(
                template.get("status") or ""
            ).strip().lower() == EXTRACTION_MEMORY_STATUS_SUSPENDED or bool(
                template.get("sentinel_suspended")
            ):
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
    if row is None:
        return {}
    payload = deepcopy(row.payload)
    await _overlay_suspended_templates(session, payload)
    return payload


async def _overlay_suspended_templates(
    session: AsyncSession, payload: dict[str, object]
) -> None:
    templates = payload.get("templates")
    if not isinstance(templates, list):
        return
    ids = [
        uuid.UUID(str(row.get("template_id")))
        for row in templates
        if isinstance(row, dict) and _uuid_or_none(row.get("template_id")) is not None
    ]
    if not ids:
        return
    result = await session.execute(
        select(ExtractionTemplate.id, ExtractionTemplate.status).where(
            ExtractionTemplate.id.in_(ids)
        )
    )
    statuses: dict[uuid.UUID, str] = {
        template_id: status for template_id, status in result
    }
    for row in templates:
        if not isinstance(row, dict):
            continue
        template_id = _uuid_or_none(row.get("template_id"))
        if template_id is None:
            continue
        if statuses.get(template_id) == EXTRACTION_MEMORY_STATUS_SUSPENDED:
            row["status"] = EXTRACTION_MEMORY_STATUS_SUSPENDED
            row["sentinel_suspended"] = True


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
    await _record_observed_field_preferences(
        session,
        template=template,
        surface=surface,
        result=result,
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
    await _record_sentinel_observations(
        session,
        run_id=run_id,
        url_result_id=url_result_id,
        current_domain=template.domain,
        current_surface=template.surface,
        current_route_pattern=template.route_pattern,
        result=result,
    )
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


async def _record_observed_field_preferences(
    session: AsyncSession,
    *,
    template: ExtractionTemplate,
    surface: str,
    result: ExtractionResult,
) -> None:
    if (
        result.verdict not in EXTRACTION_CONTRACT_OBSERVABLE_VERDICTS
        or not result.records
    ):
        return
    evidence_by_id = {row.evidence_id: row for row in result.evidence}
    winner_ids = {
        row.accepted_evidence_ids[0]
        for row in result.decisions
        if row.status == "resolved" and row.accepted_evidence_ids
    }
    observed_sources: dict[str, list[str]] = {}
    for state in result.field_states:
        if state.state not in {"captured_published", "captured_and_resolved"}:
            continue
        if state.field.startswith("variants."):
            continue
        winner_id = next(
            (
                evidence_id
                for evidence_id in state.evidence_ids
                if evidence_id in winner_ids
            ),
            next(iter(state.evidence_ids), None),
        )
        evidence = evidence_by_id.get(winner_id) if winner_id else None
        if evidence is None:
            continue
        source = normalize_source_pattern(
            source_pattern(evidence.collector_id, evidence.locator.value)
        )
        if source:
            observed_sources[evidence.fact_type] = [source]
    if not observed_sources:
        return

    def merge_contracts(existing_payload: dict) -> dict:
        contracts = [
            dict(row)
            for row in existing_payload.get("contracts", [])
            if isinstance(row, dict)
        ]
        contracts_by_field = {
            str(row.get("canonical_field") or ""): row for row in contracts
        }
        for canonical_field, sources in observed_sources.items():
            contract = contracts_by_field.get(canonical_field)
            if contract is None:
                selected_source = sources[0]
                contract = {
                    "id": str(uuid.uuid4()),
                    "template_id": str(template.id),
                    "surface": surface,
                    "canonical_field": canonical_field,
                    "candidates": [],
                    "latest_values": [],
                    "success_count": 0,
                    "rejection_count": 0,
                    "resolver_rule": EXTRACTION_CONTRACT_RESOLVER_OBSERVED,
                    "selected_source": selected_source,
                    "selection_origin": EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC,
                    "selection_history": [
                        {
                            "selected_source": selected_source,
                            "source": EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
                        }
                    ],
                    "status": EXTRACTION_MEMORY_STATUS_ACTIVE,
                }
                contracts.append(contract)
                contracts_by_field[canonical_field] = contract
            _merge_observed_sources(contract, sources)
        return {"contracts": contracts}

    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": []},
        merge_payload=merge_contracts,
    )


def _merge_observed_sources(contract: dict, sources: list[str]) -> None:
    canonical_sources = [
        source
        for source in (normalize_source_pattern(str(row or "")) for row in sources)
        if source
    ]
    candidates_by_source: dict[str, dict] = {}
    for candidate in contract.get("candidates", []):
        if not isinstance(candidate, dict):
            continue
        source = normalize_source_pattern(str(candidate.get("source") or ""))
        if source:
            candidates_by_source[source] = dict(candidate, source=source)
    for source in canonical_sources:
        candidate = candidates_by_source.setdefault(
            source, {"source": source, "success_count": 0}
        )
        candidate["success_count"] = int(candidate.get("success_count") or 0) + 1

    current_source = normalize_source_pattern(
        str(contract.get("selected_source") or "")
    )
    if current_source:
        contract["selected_source"] = current_source
    if current_source and current_source not in canonical_sources:
        contract["rejection_count"] = int(contract.get("rejection_count") or 0) + 1
    contract["success_count"] = int(contract.get("success_count") or 0) + 1

    ordered = sorted(
        candidates_by_source.values(),
        key=lambda row: (-int(row.get("success_count") or 0), str(row.get("source"))),
    )
    selected_candidate = candidates_by_source.get(current_source)
    limited = ordered[:EXTRACTION_CONTRACT_CANDIDATE_LIMIT]
    if selected_candidate is not None and selected_candidate not in limited:
        limited[-1:] = [selected_candidate]
    contract["candidates"] = limited

    if (
        str(contract.get("selection_origin") or "")
        != EXTRACTION_CONTRACT_SELECTION_ORIGIN_GENERIC
        or not ordered
    ):
        return
    best_source = str(ordered[0].get("source") or "")
    current_count = int(
        (candidates_by_source.get(current_source) or {}).get("success_count") or 0
    )
    best_count = int(ordered[0].get("success_count") or 0)
    selected_source = current_source if current_count == best_count else best_source
    if selected_source == current_source:
        return
    contract["selected_source"] = selected_source
    history = list(contract.get("selection_history") or [])
    history.append(
        {
            "selected_source": selected_source,
            "source": EXTRACTION_CONTRACT_OBSERVATION_SOURCE,
        }
    )
    contract["selection_history"] = history[-EXTRACTION_CONTRACT_HISTORY_LIMIT:]


async def _record_sentinel_observations(
    session: AsyncSession,
    *,
    run_id: int,
    url_result_id: int,
    current_domain: str,
    current_surface: str,
    current_route_pattern: str,
    result: ExtractionResult,
) -> None:
    for observation in result.sentinel_observations:
        claimed_template_id = _uuid_or_none(observation.template_id)
        template_id = await _sentinel_template_in_scope(
            session,
            template_id=claimed_template_id,
            domain=current_domain,
            surface=current_surface,
            route_pattern=current_route_pattern,
        )
        session.add(
            ExtractionObservation(
                template_id=template_id,
                run_id=run_id,
                url_result_id=url_result_id,
                verdict=observation.state,
                payload={
                    "kind": SENTINEL_OBSERVATION_KIND,
                    **observation.model_dump(mode="json"),
                },
            )
        )
        if observation.state == "critical_drift" and template_id is not None:
            await _suspend_confirmed_critical_drift_template(
                session,
                template_id=template_id,
                run_id=run_id,
                url_result_id=url_result_id,
            )


async def _sentinel_template_in_scope(
    session: AsyncSession,
    *,
    template_id: uuid.UUID | None,
    domain: str,
    surface: str,
    route_pattern: str,
) -> uuid.UUID | None:
    if template_id is None:
        return None
    return (
        await session.execute(
            select(ExtractionTemplate.id).where(
                ExtractionTemplate.id == template_id,
                ExtractionTemplate.domain == domain,
                ExtractionTemplate.surface == surface,
                ExtractionTemplate.route_pattern == route_pattern,
            )
        )
    ).scalar_one_or_none()


async def _suspend_confirmed_critical_drift_template(
    session: AsyncSession,
    *,
    template_id: uuid.UUID,
    run_id: int,
    url_result_id: int,
) -> None:
    with session.no_autoflush:
        template = (
            await session.execute(
                select(ExtractionTemplate)
                .where(ExtractionTemplate.id == template_id)
                .with_for_update()
            )
        ).scalar_one_or_none()
    if template is None or template.status == EXTRACTION_MEMORY_STATUS_SUSPENDED:
        return
    await session.flush()
    confirmed_count = (
        await session.execute(
            select(func.count())
            .select_from(ExtractionObservation)
            .where(
                ExtractionObservation.template_id == template_id,
                ExtractionObservation.verdict == "critical_drift",
                ExtractionObservation.payload["kind"].as_string()
                == SENTINEL_OBSERVATION_KIND,
            )
        )
    ).scalar_one()
    if confirmed_count < SENTINEL_CRITICAL_DRIFT_CONFIRMATION_THRESHOLD:
        return
    template.status = EXTRACTION_MEMORY_STATUS_SUSPENDED
    session.add(
        ExtractionObservation(
            template_id=template_id,
            run_id=run_id,
            url_result_id=url_result_id,
            verdict=EXTRACTION_MEMORY_STATUS_SUSPENDED,
            payload={
                "kind": SENTINEL_SUSPENSION_KIND,
                "template_id": str(template_id),
                "confirmed_critical_drift_count": confirmed_count,
                "next_action": "route_future_traffic_to_generic_until_recipe_is_restored",
            },
        )
    )


def _uuid_or_none(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


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
