from __future__ import annotations

from app.core.database import SessionLocal
from app.core.security import TokenDecodeError, decode_access_token
from app.models.crawl_run import CrawlLog, CrawlRun
from app.models.user import User
from app.services.crawl.access_service import require_accessible_run
from app.services.crawl.crud import get_run_and_logs


async def resolve_log_stream_user(token: str | None) -> User | None:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
        user_id = int(payload["sub"])
        token_version = int(payload.get("ver", 0))
    except (TokenDecodeError, KeyError, ValueError):
        return None

    async with SessionLocal() as session:
        user = await session.get(User, user_id)
        if user is None or not user.is_active:
            return None
        user_token_version = user.token_version if user.token_version is not None else 0
        if user_token_version != token_version:
            return None
        return user


async def load_log_stream_snapshot(
    *,
    run_id: int,
    after_id: int | None,
) -> tuple[list[CrawlLog], CrawlRun | None]:
    async with SessionLocal() as session:
        run, rows = await get_run_and_logs(
            session, run_id, after_id=after_id, limit=500
        )
    return rows, run


async def load_accessible_log_run(*, run_id: int, user: User) -> CrawlRun:
    async with SessionLocal() as session:
        return await require_accessible_run(session, run_id=run_id, user=user)


__all__ = [
    "load_accessible_log_run",
    "load_log_stream_snapshot",
    "resolve_log_stream_user",
]
