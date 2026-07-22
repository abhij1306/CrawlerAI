from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.models.user import User
from app.schemas.api_key import ApiKeyCreate, ApiKeyCreatedResponse, ApiKeyResponse
from app.core.api_key_service import create_api_key, list_api_keys

router = APIRouter(prefix="/api/api-keys", tags=["api-keys"])


@router.post("", status_code=status.HTTP_201_CREATED)
async def api_key_create(
    payload: ApiKeyCreate,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> ApiKeyCreatedResponse:
    row, raw_key = await create_api_key(
        session,
        user_id=int(user.id),
        name=payload.name,
    )
    return ApiKeyCreatedResponse(
        id=int(row.id),
        name=row.name,
        key_prefix=row.key_prefix,
        is_active=bool(row.is_active),
        last_used_at=row.last_used_at,
        created_at=row.created_at,
        api_key=raw_key,
    )


@router.get("")
async def api_key_list(
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> list[ApiKeyResponse]:
    rows = await list_api_keys(session, user_id=int(user.id))
    return [ApiKeyResponse.model_validate(row, from_attributes=True) for row in rows]
