from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.run_access import (
    get_accessible_run_or_404 as _get_accessible_run_or_404,
    raise_http_from_exception as _raise_http_from_exception,
)
from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.crawl import (
    DomainCookieMemoryRecordResponse,
    DomainFieldFeedbackRecordResponse,
    DomainRecipeFieldActionRequest,
    DomainRecipePromoteSelectorsRequest,
    DomainRecipeResponse,
    DomainRecipeSaveRunProfileRequest,
    DomainRunProfileLookupResponse,
    DomainRunProfilePayload,
    DomainRunProfileRecordResponse,
)
from app.services.acquisition.cookie_store import list_domain_cookie_memory
from app.services.crawl.access_service import (
    RUN_NOT_FOUND_DETAIL,
)
from app.services.crawl.profile import (
    list_domain_run_profiles,
    load_domain_run_profile,
)
from app.services.domain_utils import normalize_domain
from app.services.review import (
    apply_domain_recipe_field_action,
    build_domain_recipe_payload,
    list_domain_field_feedback,
    promote_domain_recipe_selectors,
    save_domain_recipe_run_profile,
)


router = APIRouter(prefix="/api/crawls", tags=["crawls"])

RUN_NOT_FOUND_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_404_NOT_FOUND: {"description": RUN_NOT_FOUND_DETAIL},
}


def _domain_run_profile_payload(value: object) -> DomainRunProfilePayload:
    if isinstance(value, Mapping):
        return DomainRunProfilePayload.model_validate(dict(value))
    if isinstance(value, BaseModel):
        return DomainRunProfilePayload.model_validate(value.model_dump())
    raise ValueError(
        "profile payload must be a mapping or Pydantic model; "
        f"got {type(value).__name__}"
    )


@router.get("/domain-run-profile")
async def crawls_domain_run_profile_lookup(
    url: str,
    surface: str,
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
) -> DomainRunProfileLookupResponse:
    normalized_domain = normalize_domain(url)
    normalized_surface = str(surface or "").strip().lower()
    if not normalized_domain or not normalized_surface:
        return DomainRunProfileLookupResponse(
            domain=normalized_domain,
            surface=normalized_surface,
            saved_run_profile=None,
        )
    saved_profile = await load_domain_run_profile(
        session,
        domain=normalized_domain,
        surface=normalized_surface,
    )
    return DomainRunProfileLookupResponse(
        domain=normalized_domain,
        surface=normalized_surface,
        saved_run_profile=(
            _domain_run_profile_payload(saved_profile.profile)
            if saved_profile is not None
            else None
        ),
    )


@router.get("/domain-memory/run-profiles")
@router.get("/domain-run-profiles")
async def crawls_domain_run_profiles(
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "",
) -> list[DomainRunProfileRecordResponse]:
    return await _list_domain_run_profile_responses(
        session,
        domain=domain,
        surface=surface,
    )


async def _list_domain_run_profile_responses(
    session: AsyncSession,
    *,
    domain: str = "",
    surface: str = "",
) -> list[DomainRunProfileRecordResponse]:
    rows = await list_domain_run_profiles(
        session,
        domain=domain,
        surface=surface,
    )
    return [
        DomainRunProfileRecordResponse(
            id=row.id,
            domain=row.domain,
            surface=row.surface,
            profile=_domain_run_profile_payload(row.profile),
            created_at=row.created_at,
            updated_at=row.updated_at,
        )
        for row in rows
    ]

@router.get("/domain-memory/cookies")
async def crawls_domain_memory_cookies(
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    domain: str = "",
) -> list[DomainCookieMemoryRecordResponse]:
    rows = await list_domain_cookie_memory(domain, session=session)
    return [DomainCookieMemoryRecordResponse.model_validate(row) for row in rows]


@router.get("/domain-memory/field-feedback")
async def crawls_domain_memory_field_feedback(
    session: Annotated[AsyncSession, Depends(get_db)],
    _user: Annotated[User, Depends(get_current_user)],
    domain: str = "",
    surface: str = "",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DomainFieldFeedbackRecordResponse]:
    rows = await list_domain_field_feedback(
        session,
        domain=domain,
        surface=surface,
        limit=limit,
    )
    return [DomainFieldFeedbackRecordResponse.model_validate(row) for row in rows]


@router.get("/{run_id:int}/domain-recipe", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_domain_recipe(
    run_id: int,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> DomainRecipeResponse:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    payload = await build_domain_recipe_payload(session, run=run)
    return DomainRecipeResponse.model_validate(payload)


@router.post("/{run_id:int}/domain-recipe/promote-selectors", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_promote_domain_recipe_selectors(
    run_id: int,
    payload: DomainRecipePromoteSelectorsRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[dict[str, object]]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    return await promote_domain_recipe_selectors(
        session,
        run=run,
        selectors=[item.model_dump() for item in payload.selectors],
    )


@router.post("/{run_id:int}/domain-recipe/save-run-profile", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_save_domain_run_profile(
    run_id: int,
    payload: DomainRecipeSaveRunProfileRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    return await save_domain_recipe_run_profile(
        session,
        run=run,
        profile=payload.profile.model_dump(),
    )


@router.post("/{run_id:int}/domain-recipe/field-action", responses=RUN_NOT_FOUND_RESPONSE)
async def crawls_domain_recipe_field_action(
    run_id: int,
    payload: DomainRecipeFieldActionRequest,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, object]:
    run = await _get_accessible_run_or_404(session, run_id=run_id, user=user)
    try:
        return await apply_domain_recipe_field_action(
            session,
            run=run,
            action=payload.model_dump(),
        )
    except ValueError as exc:
        await session.rollback()
        _raise_http_from_exception(
            status_code=status.HTTP_400_BAD_REQUEST,
            exc=exc,
        )
