from __future__ import annotations

from typing import TYPE_CHECKING
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_MEMORY_STATUS_SUSPENDED,
    SENTINEL_CRITICAL_DRIFT_CONFIRMATION_THRESHOLD,
    SENTINEL_OBSERVATION_KIND,
    SENTINEL_SUSPENSION_KIND,
)
from app.models.extraction_memory import ExtractionObservation, ExtractionTemplate

if TYPE_CHECKING:
    from app.extraction.contracts import ExtractionResult


async def record_sentinel_observations(
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
        template_id = await _sentinel_template_in_scope(
            session,
            template_id=_uuid_or_none(observation.template_id),
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
