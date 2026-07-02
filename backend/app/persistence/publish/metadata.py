from __future__ import annotations

from app.models.extraction_memory import ExtractionOperatorLabel
from app.core.config.extraction_memory import EXTRACTION_LABEL_KIND_REVIEW_PROMOTION
from app.core.domain_utils import normalize_domain
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


async def load_domain_requested_fields(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
) -> list[str]:
    domain = normalize_domain(url)
    if not domain:
        return []
    mapping = await load_domain_field_mapping(session, domain=domain, surface=surface)
    fields: list[str] = []
    seen: set[str] = set()
    for value in mapping.values():
        name = str(value or "").strip().lower()
        if not name or name in seen:
            continue
        seen.add(name)
        fields.append(name)
    return fields


async def load_domain_field_mapping(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> dict[str, str]:
    result = await session.execute(
        select(ExtractionOperatorLabel.field_mapping)
        .where(
            ExtractionOperatorLabel.label_kind
            == EXTRACTION_LABEL_KIND_REVIEW_PROMOTION,
            ExtractionOperatorLabel.domain == domain,
            ExtractionOperatorLabel.surface == surface,
        )
        .order_by(
            ExtractionOperatorLabel.created_at.desc(),
            ExtractionOperatorLabel.id.desc(),
        )
        .limit(1)
    )
    mapping = result.scalar_one_or_none()
    return dict(mapping) if isinstance(mapping, dict) else {}
