from __future__ import annotations

from datetime import UTC, datetime
from weakref import WeakKeyDictionary

from sqlalchemy import inspect, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.domain_memory import DomainRunProfile
from app.core.domain_utils import normalize_domain

from .normalization import normalize_domain_run_profile

# Per-URL DB budget: profile loads run up to 4x per URL and each used to pay a
# ``has_table`` introspection query. Table existence is stable for the life of
# a bound engine (migrations run at deploy time), so the result is memoized per
# bind. Weak keys drop entries when a (test-scoped) engine is disposed.
_DOMAIN_RUN_PROFILES_TABLE_CHECKS: WeakKeyDictionary = WeakKeyDictionary()


def reset_domain_run_profiles_table_cache() -> None:
    """Drop memoized ``has_table`` results (test isolation / post-migration)."""

    _DOMAIN_RUN_PROFILES_TABLE_CHECKS.clear()


async def _has_domain_run_profiles_table(session: AsyncSession) -> bool:
    bind = session.get_bind()
    if bind is not None:
        cached = _DOMAIN_RUN_PROFILES_TABLE_CHECKS.get(bind)
        if cached is not None:
            return bool(cached)
    exists = bool(
        await session.run_sync(
            lambda sync_session: inspect(sync_session.connection()).has_table(
                "domain_run_profiles"
            )
        )
    )
    if bind is not None:
        _DOMAIN_RUN_PROFILES_TABLE_CHECKS[bind] = exists
    return exists


async def load_domain_run_profile(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
) -> DomainRunProfile | None:
    normalized_domain = normalize_domain(domain or "")
    normalized_surface = str(surface or "").strip().lower()
    if not await _has_domain_run_profiles_table(session):
        return None
    result = await session.execute(
        select(DomainRunProfile)
        .where(
            DomainRunProfile.domain == normalized_domain,
            DomainRunProfile.surface == normalized_surface,
        )
        .order_by(DomainRunProfile.updated_at.desc(), DomainRunProfile.id.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_domain_run_profiles(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
) -> list[DomainRunProfile]:
    statement = select(DomainRunProfile)
    normalized_domain = normalize_domain(domain or "") if domain else ""
    normalized_surface = str(surface or "").strip().lower()
    if normalized_domain:
        statement = statement.where(DomainRunProfile.domain == normalized_domain)
    if normalized_surface:
        statement = statement.where(DomainRunProfile.surface == normalized_surface)
    if not await _has_domain_run_profiles_table(session):
        return []
    result = await session.execute(
        statement.order_by(
            DomainRunProfile.domain.asc(),
            DomainRunProfile.surface.asc(),
            DomainRunProfile.updated_at.desc(),
            DomainRunProfile.id.desc(),
        )
    )
    return list(result.scalars().all())


async def save_domain_run_profile(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    profile: object,
    source_run_id: int,
    commit: bool = False,
    existing_record: DomainRunProfile | None = None,
) -> dict[str, object]:
    normalized_domain = normalize_domain(domain or "")
    normalized_surface = str(surface or "").strip().lower()
    existing = existing_record
    if existing is None:
        existing = await load_domain_run_profile(
            session,
            domain=normalized_domain,
            surface=normalized_surface,
        )
    saved_at = datetime.now(UTC).isoformat()
    normalized_profile = normalize_domain_run_profile(
        profile,
        source_run_id=source_run_id,
        saved_at=saved_at,
    )
    if existing is None:
        statement = (
            insert(DomainRunProfile)
            .values(
                domain=normalized_domain,
                surface=normalized_surface,
                profile=normalized_profile,
            )
            .on_conflict_do_update(
                index_elements=(
                    DomainRunProfile.domain,
                    DomainRunProfile.surface,
                ),
                set_={
                    "profile": normalized_profile,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(DomainRunProfile.id)
        )
        profile_id = (await session.execute(statement)).scalar_one()
        existing = await session.get(DomainRunProfile, profile_id)
        if existing is None:
            raise RuntimeError("domain run profile upsert returned no record")
        existing.profile = normalized_profile
    else:
        existing.profile = normalized_profile
    if commit:
        await session.commit()
        await session.refresh(existing)
    else:
        await session.flush()
    return dict(existing.profile or {})
