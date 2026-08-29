from __future__ import annotations

from app.core.database import SessionLocal
from app.core.security import TokenDecodeError, decode_access_token
from app.crawl.access_service import require_accessible_run
from app.crawl.run_events import run_event_timeline
from app.models.crawl_run import CrawlRun, RunEvent
from app.models.user import User


async def resolve_run_event_stream_user(token: str | None) -> User | None:
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


async def load_run_event_stream_snapshot(
    *,
    run_id: int,
    after_sequence: int | None,
) -> tuple[list[RunEvent], CrawlRun | None]:
    events = await run_event_timeline.list_after(
        run_id=run_id, after_sequence=after_sequence, limit=500
    )
    async with SessionLocal() as session:
        run = await session.get(CrawlRun, run_id)
    return events, run


async def load_accessible_run_event_run(*, run_id: int, user: User) -> CrawlRun:
    async with SessionLocal() as session:
        return await require_accessible_run(session, run_id=run_id, user=user)


__all__ = [
    "load_accessible_run_event_run",
    "load_run_event_stream_snapshot",
    "resolve_run_event_stream_user",
]
