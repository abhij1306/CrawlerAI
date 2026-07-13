from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import hashlib
import json
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_COMPILER_VERSION,
    EXTRACTION_CONTRACT_SELECTION_ORIGIN_OPERATOR,
    EXTRACTION_PROFILE_ROUTE_PATTERN,
    EXTRACTION_PROFILE_TECH_SIGNAL,
    EXTRACTION_PROFILE_TEMPLATE_FINGERPRINT,
    EXTRACTION_LABEL_KIND_V3_CUTOVER,
    EXTRACTION_MANIFEST_VERSION,
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
    EXTRACTION_RELEASE_VERSION_V2,
    EXTRACTION_RUNTIME_OBSERVATION_KIND,
    EXTRACTION_V3_CUTOVER_ACTION_ENABLE,
    EXTRACTION_V3_CUTOVER_REQUIRED_REPORT_FIELDS,
)
from app.core.domain_utils import normalize_domain
from app.core.config import field_mappings
from app.core.extraction_memory.templates import (
    extract_tech_signals,
    fingerprint_template,
    normalize_source_pattern,
    normalize_route,
)
from app.core.extraction_memory.recipe_contracts import RecipeCandidate
from app.models.crawl_run import CrawlRun
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionManifest,
    ExtractionObservation,
    ExtractionOperatorLabel,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)

if TYPE_CHECKING:
    from app.extraction.contracts import ExtractionResult


def _checksum(payload: dict) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _canonical_field(field: object) -> str:
    key = str(field or "").strip()
    normalized = key.casefold()
    return field_mappings.ECOMMERCE_DETAIL_FIELD_FACT_TYPES.get(normalized, key)


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
                CompiledExtractionRecipe.compiler_version
                == EXTRACTION_COMPILER_VERSION,
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
                        CompiledExtractionRecipe.compiler_version
                        == EXTRACTION_COMPILER_VERSION,
                    )
                )
            ).scalar_one()
    return recipe, compiled


async def save_extraction_profile(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    pins: list[dict[str, object]],
) -> dict[str, object]:
    """Persist operator-owned source pins for future release snapshots."""

    normalized_domain = normalize_domain(domain)
    normalized_surface = str(surface or "").strip().lower()
    template = await ensure_template(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
        fingerprint=EXTRACTION_PROFILE_TEMPLATE_FINGERPRINT,
        route_pattern=EXTRACTION_PROFILE_ROUTE_PATTERN,
        tech_signals=[EXTRACTION_PROFILE_TECH_SIGNAL],
    )
    contracts = [
        _profile_contract(template, normalized_surface, row)
        for row in pins
        if _profile_contract_source(row)
    ]
    await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_DOMAIN,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": contracts},
    )
    return await load_extraction_profile(
        session, domain=normalized_domain, surface=normalized_surface
    )


async def load_extraction_profile(
    session: AsyncSession, *, domain: str, surface: str
) -> dict[str, object]:
    normalized_domain = normalize_domain(domain)
    normalized_surface = str(surface or "").strip().lower()
    template = (
        await session.execute(
            select(ExtractionTemplate).where(
                ExtractionTemplate.domain == normalized_domain,
                ExtractionTemplate.surface == normalized_surface,
                ExtractionTemplate.fingerprint
                == EXTRACTION_PROFILE_TEMPLATE_FINGERPRINT,
            )
        )
    ).scalar_one_or_none()
    contracts: list[dict[str, object]] = []
    if template is not None:
        recipe = (
            await session.execute(
                select(ExtractionRecipe).where(
                    ExtractionRecipe.template_id == template.id,
                    ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_CONTRACTS,
                )
            )
        ).scalar_one_or_none()
        contracts = (
            [
                dict(row)
                for row in list((recipe.payload or {}).get("contracts") or [])
                if isinstance(row, dict)
            ]
            if recipe is not None
            else []
        )
    return {
        "domain": normalized_domain,
        "surface": normalized_surface,
        "template_id": str(template.id) if template is not None else None,
        "pins": [_profile_pin_from_contract(row) for row in contracts],
    }


def _coerce_aliases(value: object) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    return [str(alias).strip() for alias in value if str(alias).strip()]


def _profile_contract(
    template: ExtractionTemplate, surface: str, row: dict[str, object]
) -> dict[str, object]:
    canonical_field = _canonical_field(
        row.get("canonical_field") or row.get("field_name") or row.get("field")
    )
    selected_source = _profile_contract_source(row)
    return {
        "id": str(row.get("id") or uuid.uuid4()),
        "template_id": str(template.id),
        "surface": surface,
        "canonical_field": canonical_field,
        "candidates": [{"source": selected_source}],
        "latest_values": [],
        "success_count": 0,
        "rejection_count": 0,
        "resolver_rule": str(row.get("resolver_rule") or "operator_profile"),
        "selected_source": selected_source,
        "selection_origin": EXTRACTION_CONTRACT_SELECTION_ORIGIN_OPERATOR,
        "selection_history": [
            {
                "selected_source": selected_source,
                "source": "extraction_profile",
            }
        ],
        "status": str(row.get("status") or EXTRACTION_MEMORY_STATUS_ACTIVE),
        "required": bool(row.get("required", False)),
        "value_sense": str(row.get("value_sense") or "").strip(),
        "aliases": _coerce_aliases(row.get("aliases")),
    }


def _profile_contract_source(row: dict[str, object]) -> str:
    return normalize_source_pattern(str(row.get("selected_source") or ""))


def _profile_pin_from_contract(contract: dict[str, object]) -> dict[str, object]:
    return {
        "id": str(contract.get("id") or ""),
        "canonical_field": str(contract.get("canonical_field") or ""),
        "selected_source": str(contract.get("selected_source") or ""),
        "required": bool(contract.get("required", False)),
        "value_sense": str(contract.get("value_sense") or ""),
        "aliases": _coerce_aliases(contract.get("aliases")),
        "status": str(contract.get("status") or EXTRACTION_MEMORY_STATUS_ACTIVE),
    }


async def enable_extraction_v3_cutover(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    eval_report: dict[str, object],
) -> ExtractionOperatorLabel:
    """Persist the operator cutover flag after the eval gate proves the domain."""

    normalized_domain = normalize_domain(domain)
    normalized_surface = str(surface or "").strip().lower()
    if not _v3_cutover_report_passed(eval_report, surface=normalized_surface):
        raise ValueError(
            "extraction v3 cutover requires a passing commerce-detail gate"
        )
    row = ExtractionOperatorLabel(
        label_kind=EXTRACTION_LABEL_KIND_V3_CUTOVER,
        domain=normalized_domain,
        surface=normalized_surface,
        action=EXTRACTION_V3_CUTOVER_ACTION_ENABLE,
        payload={"eval_report": dict(eval_report)},
        approved_schema={},
        field_mapping={},
    )
    session.add(row)
    await session.flush()
    return row


async def extraction_v3_cutover_enabled(
    session: AsyncSession, *, domain: str, surface: str
) -> bool:
    normalized_domain = normalize_domain(domain)
    normalized_surface = str(surface or "").strip().lower()
    row = (
        await session.execute(
            select(ExtractionOperatorLabel)
            .where(
                ExtractionOperatorLabel.label_kind == EXTRACTION_LABEL_KIND_V3_CUTOVER,
                ExtractionOperatorLabel.domain == normalized_domain,
                ExtractionOperatorLabel.surface == normalized_surface,
            )
            .order_by(ExtractionOperatorLabel.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if row is None or row.action != EXTRACTION_V3_CUTOVER_ACTION_ENABLE:
        return False
    payload = row.payload if isinstance(row.payload, dict) else {}
    report = payload.get("eval_report")
    return isinstance(report, dict) and _v3_cutover_report_passed(
        report, surface=normalized_surface
    )


def _v3_cutover_report_passed(report: dict[str, object], *, surface: str) -> bool:
    if surface != EXTRACTION_V3_CUTOVER_REQUIRED_REPORT_FIELDS["surface"]:
        return False
    return all(
        report.get(key) == expected
        for key, expected in EXTRACTION_V3_CUTOVER_REQUIRED_REPORT_FIELDS.items()
    )


async def build_release_payload(
    session: AsyncSession, *, domain: str, surface: str
) -> dict[str, object]:
    from app.persistence.extraction_recipe_lifecycle import (
        build_executable_release_payload,
    )

    return await build_executable_release_payload(
        session,
        domain=normalize_domain(domain),
        surface=surface,
    )


async def create_release_snapshot(
    session: AsyncSession, *, run_id: int, domain: str, surface: str
) -> ExtractionReleaseSnapshot:
    payload = await build_release_payload(session, domain=domain, surface=surface)
    row = ExtractionReleaseSnapshot(
        run_id=run_id,
        domain=domain,
        surface=surface,
        release_version=EXTRACTION_RELEASE_VERSION_V2,
        payload=payload,
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
        release_version=EXTRACTION_RELEASE_VERSION_V2,
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
    return deepcopy(row.payload)


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
    compiled_recipe = None
    if isinstance(result.recipe_candidate, RecipeCandidate):
        from app.persistence.extraction_recipe_lifecycle import (
            record_candidate_validation,
            save_recipe_candidate,
        )

        _recipe, compiled_recipe = await save_recipe_candidate(
            session,
            template=template,
            candidate=result.recipe_candidate,
        )
        execution = result.recipe_execution
        await record_candidate_validation(
            session,
            compiled=compiled_recipe,
            sample_url=url,
            run_id=run_id,
            url_result_id=url_result_id,
            succeeded=bool(
                execution and execution.records and not execution.failure_code
            ),
        )
    await _record_active_recipe_drift(
        session,
        run_id=run_id,
        url_result_id=url_result_id,
        url=url,
        result=result,
    )
    observation = ExtractionObservation(
        template_id=template.id,
        run_id=run_id,
        url_result_id=url_result_id,
        verdict=result.verdict,
        payload={
            "kind": EXTRACTION_RUNTIME_OBSERVATION_KIND,
            "record_count": len(result.records),
            "extractor_tier": result.diagnostics.extractor_tier,
            "model_invoked": result.diagnostics.model_invoked,
            "universal_model_invocation_count": (
                result.metrics.universal_model_invocation_count
            ),
            "universal_model_ungrounded_rejection_count": (
                result.metrics.universal_model_ungrounded_rejection_count
            ),
            "universal_model_ungrounded_rejection_rate": (
                result.metrics.universal_model_ungrounded_rejection_rate
            ),
            "universal_model_cost_usd": result.metrics.universal_model_cost_usd,
            "universal_model_cost_per_1000_pages": (
                result.metrics.universal_model_cost_per_1000_pages
            ),
            "finding_rule_ids": sorted({row.rule_id for row in result.findings}),
            "recipe_candidate_id": (
                result.recipe_candidate.candidate_id
                if result.recipe_candidate is not None
                else None
            ),
            "recipe_execution_id": (
                result.recipe_execution.recipe_id
                if result.recipe_execution is not None
                else None
            ),
            "recipe_failure_code": (
                result.recipe_execution.failure_code
                if result.recipe_execution is not None
                else None
            ),
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
            compiled_recipe_id=compiled_recipe.id
            if compiled_recipe is not None
            else None,
            manifest_version=EXTRACTION_MANIFEST_VERSION,
            payload=manifest_payload,
        )
        session.add(manifest)
    else:
        manifest.release_snapshot_id = release_snapshot_id
        manifest.template_id = template.id
        manifest.compiled_recipe_id = (
            compiled_recipe.id
            if compiled_recipe is not None
            else manifest.compiled_recipe_id
        )
        manifest.payload = manifest_payload
    await session.flush()
    return manifest


async def _record_active_recipe_drift(
    session: AsyncSession,
    *,
    run_id: int,
    url_result_id: int,
    url: str,
    result: ExtractionResult,
) -> None:
    compiled_id = result.manifest_context.compiled_recipe_id
    execution = result.recipe_execution
    if not compiled_id or execution is None or execution.failure_code is None:
        return
    try:
        recipe_id = uuid.UUID(compiled_id)
    except (TypeError, ValueError):
        return
    compiled = await session.get(CompiledExtractionRecipe, recipe_id)
    if compiled is None:
        return
    from app.persistence.extraction_recipe_lifecycle import record_recipe_drift

    await record_recipe_drift(
        session,
        compiled=compiled,
        sample_url=url,
        failure_code=execution.failure_code,
        run_id=run_id,
        url_result_id=url_result_id,
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
