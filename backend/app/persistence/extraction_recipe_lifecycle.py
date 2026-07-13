"""Storage-only lifecycle for executable recipe candidates and releases."""

from __future__ import annotations

from copy import deepcopy
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_MEMORY_STATUS_ACTIVE,
    EXTRACTION_MEMORY_STATUS_PROVISIONAL,
    EXTRACTION_MEMORY_STATUS_RETIRED,
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    EXTRACTION_RECIPE_DRIFT_DISTINCT_FAILURES,
    EXTRACTION_RECIPE_KIND_EXECUTABLE_V2,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
    EXTRACTION_RECIPE_PROMOTION_DISTINCT_SAMPLES,
    EXTRACTION_RELEASE_VERSION_V2,
)
from app.core.extraction_memory.recipe_contracts import RecipeCandidate
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionObservation,
    ExtractionRecipe,
    ExtractionReleaseSnapshot,
    ExtractionTemplate,
)
from app.persistence.extraction_memory import upsert_recipe

RECIPE_CANDIDATE_VALIDATION_KIND = "recipe_candidate_validation"
RECIPE_EXECUTION_DRIFT_KIND = "recipe_execution_drift"


async def save_recipe_candidate(
    session: AsyncSession,
    *,
    template: ExtractionTemplate,
    candidate: RecipeCandidate,
) -> tuple[ExtractionRecipe, CompiledExtractionRecipe]:
    """Store one immutable compiled candidate without making it active."""

    existing_recipe = (
        await session.execute(
            select(ExtractionRecipe).where(
                ExtractionRecipe.template_id == template.id,
                ExtractionRecipe.layer == EXTRACTION_RECIPE_LAYER_TEMPLATE,
                ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_EXECUTABLE_V2,
            )
        )
    ).scalar_one_or_none()
    active_ids = (
        {
            row.id
            for row in (
                await session.execute(
                    select(CompiledExtractionRecipe).where(
                        CompiledExtractionRecipe.recipe_id == existing_recipe.id,
                        CompiledExtractionRecipe.status
                        == EXTRACTION_MEMORY_STATUS_ACTIVE,
                    )
                )
            )
            .scalars()
            .all()
        }
        if existing_recipe is not None
        else set()
    )
    recipe, compiled = await upsert_recipe(
        session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_EXECUTABLE_V2,
        payload=candidate.recipe.model_dump(mode="json"),
    )
    if not active_ids:
        recipe.status = EXTRACTION_MEMORY_STATUS_PROVISIONAL
    if compiled.id not in active_ids:
        compiled.status = EXTRACTION_MEMORY_STATUS_PROVISIONAL
    await session.flush()
    return recipe, compiled


async def record_candidate_validation(
    session: AsyncSession,
    *,
    compiled: CompiledExtractionRecipe,
    sample_url: str,
    run_id: int | None = None,
    url_result_id: int | None = None,
    succeeded: bool,
    explicit_approval: bool = False,
) -> bool:
    """Promote after distinct successful samples or explicit grounded approval."""

    recipe = await session.get(ExtractionRecipe, compiled.recipe_id)
    if recipe is None:
        raise ValueError("compiled recipe has no source recipe")
    observation = ExtractionObservation(
        template_id=recipe.template_id,
        run_id=run_id,
        url_result_id=url_result_id,
        verdict="success" if succeeded else "invalid",
        payload={
            "kind": RECIPE_CANDIDATE_VALIDATION_KIND,
            "compiled_recipe_id": str(compiled.id),
            "sample_url": sample_url,
            "succeeded": succeeded,
            "explicit_approval": explicit_approval,
        },
    )
    session.add(observation)
    await session.flush()
    successful_urls = await _distinct_observation_urls(
        session,
        compiled_id=compiled.id,
        kind=RECIPE_CANDIDATE_VALIDATION_KIND,
        verdict="success",
    )
    if (
        explicit_approval
        or len(successful_urls) >= EXTRACTION_RECIPE_PROMOTION_DISTINCT_SAMPLES
    ):
        await activate_recipe_candidate(session, compiled=compiled)
        return True
    return False


async def activate_recipe_candidate(
    session: AsyncSession, *, compiled: CompiledExtractionRecipe
) -> None:
    recipe = await session.get(ExtractionRecipe, compiled.recipe_id)
    if recipe is None:
        raise ValueError("compiled recipe has no source recipe")
    siblings = list(
        (
            await session.execute(
                select(CompiledExtractionRecipe).where(
                    CompiledExtractionRecipe.recipe_id == recipe.id
                )
            )
        )
        .scalars()
        .all()
    )
    for sibling in siblings:
        if (
            sibling.id != compiled.id
            and sibling.status == EXTRACTION_MEMORY_STATUS_ACTIVE
        ):
            sibling.status = EXTRACTION_MEMORY_STATUS_RETIRED
    compiled.status = EXTRACTION_MEMORY_STATUS_ACTIVE
    recipe.status = EXTRACTION_MEMORY_STATUS_ACTIVE
    recipe.payload = deepcopy(compiled.payload)
    await session.flush()


async def record_recipe_drift(
    session: AsyncSession,
    *,
    compiled: CompiledExtractionRecipe,
    sample_url: str,
    failure_code: str,
    run_id: int | None = None,
    url_result_id: int | None = None,
) -> bool:
    recipe = await session.get(ExtractionRecipe, compiled.recipe_id)
    if recipe is None:
        raise ValueError("compiled recipe has no source recipe")
    session.add(
        ExtractionObservation(
            template_id=recipe.template_id,
            run_id=run_id,
            url_result_id=url_result_id,
            verdict="critical_drift",
            payload={
                "kind": RECIPE_EXECUTION_DRIFT_KIND,
                "compiled_recipe_id": str(compiled.id),
                "sample_url": sample_url,
                "failure_code": failure_code,
            },
        )
    )
    await session.flush()
    failed_urls = await _distinct_observation_urls(
        session,
        compiled_id=compiled.id,
        kind=RECIPE_EXECUTION_DRIFT_KIND,
        verdict="critical_drift",
    )
    if len(failed_urls) < EXTRACTION_RECIPE_DRIFT_DISTINCT_FAILURES:
        return False
    compiled.status = EXTRACTION_MEMORY_STATUS_SUSPENDED
    recipe.status = EXTRACTION_MEMORY_STATUS_SUSPENDED
    await session.flush()
    return True


async def build_executable_release_payload(
    session: AsyncSession, *, domain: str, surface: str
) -> dict[str, object]:
    templates = list(
        (
            await session.execute(
                select(ExtractionTemplate).where(
                    ExtractionTemplate.domain == domain.strip().lower(),
                    ExtractionTemplate.surface == surface,
                    ExtractionTemplate.status == EXTRACTION_MEMORY_STATUS_ACTIVE,
                )
            )
        )
        .scalars()
        .all()
    )
    rows: list[dict[str, object]] = []
    for template in templates:
        active = await _active_compiled_recipe(session, template_id=template.id)
        if active is None:
            continue
        rows.append(
            {
                "template_id": str(template.id),
                "compiled_recipe_id": str(active.id),
                "template_signature": template.fingerprint,
                "route_pattern": template.route_pattern,
                "compiled_recipe": deepcopy(active.payload),
            }
        )
    return {
        "schema_version": EXTRACTION_RELEASE_VERSION_V2,
        "domain": domain.strip().lower(),
        "surface": surface,
        "templates": rows,
    }


async def create_executable_release_snapshot(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    run_id: int | None = None,
) -> ExtractionReleaseSnapshot:
    row = ExtractionReleaseSnapshot(
        run_id=run_id,
        domain=domain.strip().lower(),
        surface=surface,
        release_version=EXTRACTION_RELEASE_VERSION_V2,
        payload=await build_executable_release_payload(
            session, domain=domain, surface=surface
        ),
    )
    session.add(row)
    await session.flush()
    return row


async def _active_compiled_recipe(
    session: AsyncSession, *, template_id: uuid.UUID
) -> CompiledExtractionRecipe | None:
    return (
        (
            await session.execute(
                select(CompiledExtractionRecipe)
                .join(ExtractionRecipe)
                .where(
                    ExtractionRecipe.template_id == template_id,
                    ExtractionRecipe.kind == EXTRACTION_RECIPE_KIND_EXECUTABLE_V2,
                    CompiledExtractionRecipe.status == EXTRACTION_MEMORY_STATUS_ACTIVE,
                )
                .order_by(CompiledExtractionRecipe.created_at.desc())
            )
        )
        .scalars()
        .first()
    )


async def _distinct_observation_urls(
    session: AsyncSession,
    *,
    compiled_id: uuid.UUID,
    kind: str,
    verdict: str,
) -> set[str]:
    sample_url = ExtractionObservation.payload["sample_url"].astext
    rows = await session.execute(
        select(sample_url)
        .distinct()
        .where(
            ExtractionObservation.verdict == verdict,
            ExtractionObservation.payload["kind"].astext == kind,
            ExtractionObservation.payload["compiled_recipe_id"].astext
            == str(compiled_id),
            sample_url != "",
        )
    )
    return {str(value) for value in rows.scalars().all() if value}
