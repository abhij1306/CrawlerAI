from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public.common import PublicApiError, public_success
from app.core.dependencies import get_db
from app.core.public_auth import get_public_api_user
from app.models.user import User
from app.schemas.public_api import PublicBatchExtractRequest, PublicExtractRequest
from app.services.config.public_api import PUBLIC_API_ERROR_WORKER_REQUIRED
from app.services.public_api.extraction_service import extract_public_product

router = APIRouter(prefix="/api/v1/extract", tags=["public-extract"])


@router.post("")
async def public_extract(
    payload: PublicExtractRequest,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_public_api_user)],
) -> dict[str, Any]:
    data = await extract_public_product(session, user_id=int(user.id), payload=payload)
    return public_success(data, request)


@router.post("/batch")
async def public_extract_batch(
    payload: PublicBatchExtractRequest,
    request: Request,
    user: Annotated[User, Depends(get_public_api_user)],
) -> dict[str, Any]:
    del payload, request, user
    raise PublicApiError(
        PUBLIC_API_ERROR_WORKER_REQUIRED,
        "Batch extraction requires worker infrastructure and is deferred in public API v1.",
        status_code=501,
    )
