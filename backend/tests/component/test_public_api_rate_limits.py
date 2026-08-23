from __future__ import annotations

# ruff: noqa: F403, F405
from .public_api_test_support import *
from .public_api_test_support import _retry_after, _trim


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_rate_limit_is_keyed_by_api_key(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.public.rate_limit.PUBLIC_API_READ_RATE_LIMIT", 2)
    monkeypatch.setattr("app.api.public.rate_limit.PUBLIC_API_READ_BURST_LIMIT", 2)
    previous_public_buckets = public_rate_limit_buckets_snapshot()
    try:
        clear_public_rate_limit_buckets_for_testing()
        raw_key = "crawlerai_rate_key"
        db_session.add(
            ApiKey(
                user_id=test_user.id,
                name="rate",
                key_prefix="crawlerai",
                key_hash=hash_api_key(raw_key),
                is_active=True,
            )
        )
        await db_session.commit()

        async def _override_db():
            yield db_session

        app.dependency_overrides[get_db] = _override_db
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"Authorization": f"Bearer {raw_key}"}
            first = await client.get("/api/v1/capabilities", headers=headers)
            second = await client.get("/api/v1/capabilities", headers=headers)
            third = await client.get("/api/v1/capabilities", headers=headers)
    finally:
        app.dependency_overrides.clear()
        restore_public_rate_limit_buckets_for_testing(previous_public_buckets)

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_rate_limit_headers_preserved_from_redis_window(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # With the Redis sliding window serving the buckets, the public API keeps
    # the exact X-RateLimit-*/Retry-After headers contract.
    import math

    import app.core.redis as app_redis

    class _SlidingWindowFakeRedis:
        def __init__(self) -> None:
            self._zsets: dict[str, dict[str, float]] = {}
            self.now_ms = 1_700_000_000_000
            self.eval_calls = 0

        async def eval(self, script: str, numkeys: int, *args: object):
            assert "ZREMRANGEBYSCORE" in script
            self.eval_calls += 1
            key = str(args[0])
            window_ms = int(args[1])
            max_requests = int(args[2])
            member = str(args[3])
            zset = self._zsets.setdefault(key, {})
            cutoff = self.now_ms - window_ms
            for existing, score in list(zset.items()):
                if score <= cutoff:
                    del zset[existing]
            count = len(zset)
            if count >= max_requests:
                oldest = min(zset.values()) if zset else None
                retry_after_ms = (
                    window_ms
                    if oldest is None
                    else max(1, math.ceil(oldest + window_ms - self.now_ms))
                )
                return [0, retry_after_ms, 0, retry_after_ms]
            zset[member] = self.now_ms
            oldest = min(zset.values())
            reset_ms = max(1, math.ceil(oldest + window_ms - self.now_ms))
            return [1, 0, max_requests - count - 1, reset_ms]

    fake = _SlidingWindowFakeRedis()
    monkeypatch.setattr(app_redis, "_client", fake)
    monkeypatch.setattr("app.api.public.rate_limit.PUBLIC_API_READ_RATE_LIMIT", 2)
    monkeypatch.setattr("app.api.public.rate_limit.PUBLIC_API_READ_BURST_LIMIT", 2)
    buckets_before = public_rate_limit_buckets_snapshot()
    raw_key = "crawlerai_rate_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="rate",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            headers = {"Authorization": f"Bearer {raw_key}"}
            first = await client.get("/api/v1/capabilities", headers=headers)
            second = await client.get("/api/v1/capabilities", headers=headers)
            third = await client.get("/api/v1/capabilities", headers=headers)
    finally:
        app.dependency_overrides.clear()

    assert first.status_code == 200
    assert first.headers["X-RateLimit-Limit"] == "2"
    assert first.headers["X-RateLimit-Remaining"] == "1"
    assert int(first.headers["X-RateLimit-Reset"]) > 0
    assert "Retry-After" not in first.headers
    assert second.status_code == 200
    assert second.headers["X-RateLimit-Remaining"] == "0"
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"
    assert third.headers["X-RateLimit-Remaining"] == "0"
    assert int(third.headers["Retry-After"]) > 0
    assert fake.eval_calls >= 2  # minute + burst buckets per request
    # In-process fallback buckets untouched — Redis served every request.
    assert public_rate_limit_buckets_snapshot() == buckets_before


@pytest.mark.component
def test_trim_keeps_boundary_timestamp() -> None:
    bucket = deque([10.0, 11.0, 12.0])

    _trim(bucket, 11.0)

    assert list(bucket) == [11.0, 12.0]


@pytest.mark.component
def test_retry_after_rounds_up_remaining_window() -> None:
    assert _retry_after(deque([10.0]), now=68.1, window_seconds=60) == 2
