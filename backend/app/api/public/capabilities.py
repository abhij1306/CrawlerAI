from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request

from app.api.public.common import public_success
from app.core.public_auth import get_public_api_user
from app.models.user import User
from app.services.config.public_api import PUBLIC_API_CAPABILITIES

router = APIRouter(prefix="/api/v1/capabilities", tags=["public-capabilities"])


@router.get("")
async def public_capabilities(
    request: Request,
    user: Annotated[User, Depends(get_public_api_user)],
) -> dict[str, Any]:
    del user
    return public_success(dict(PUBLIC_API_CAPABILITIES), request)
