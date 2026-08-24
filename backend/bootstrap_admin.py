"""Explicit create-only initial administrator command."""

from __future__ import annotations

import asyncio

from app.core.auth_service import bootstrap_admin_user
from app.core.database import SessionLocal, dispose_engine


async def bootstrap_admin() -> int:
    try:
        async with SessionLocal() as session:
            user = await bootstrap_admin_user(session)
        if user is None:
            print("Admin bootstrap disabled or already consumed.")
        else:
            print(f"Created initial admin user id={user.id}.")
        return 0
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(bootstrap_admin()))
