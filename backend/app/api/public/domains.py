from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.public.common import public_success
from app.core.dependencies import get_db
from app.core.public_auth import get_public_api_user
from app.models.user import User
from app.services.public_api.domain_info_service import public_domain_info

router = APIRouter(prefix="/api/v1/domains", tags=["public-domains"])


@router.get("/{domain}")
async def public_domain_get(
    domain: str,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_public_api_user)],
) -> dict[str, Any]:
    del user
    data = await public_domain_info(session, domain=domain)
    return public_success(data.model_dump(mode="json"), request)
