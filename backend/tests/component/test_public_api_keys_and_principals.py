from __future__ import annotations

import asyncio

# ruff: noqa: F403, F405
from .public_api_test_support import *
from .public_api_test_support import (
    _count_commits,
    _password_field_name,
    _seed_public_api_key,
)
from app.core.api_key_service import delete_api_key
from app.main import _crawler_app_state


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_api_requires_api_key(public_api_client: AsyncClient) -> None:
    response = await public_api_client.get("/api/v1/capabilities")

    assert response.status_code == 401
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["error"]["code"] == PUBLIC_API_ERROR_API_KEY_REQUIRED


@pytest.mark.asyncio
@pytest.mark.component
async def test_invalid_api_key_flood_is_limited_before_database_authentication(
    public_api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    crawler_state = _crawler_app_state()
    crawler_state.public_preauth_rate_limit_buckets.clear()
    original_authenticate = authenticate_public_api_key
    auth_calls = 0

    async def _counting_authenticate(session, authorization, *, touch=True):
        nonlocal auth_calls
        auth_calls += 1
        return await original_authenticate(session, authorization, touch=touch)

    monkeypatch.setattr("app.main.authenticate_public_api_key", _counting_authenticate)
    monkeypatch.setattr("app.main.PUBLIC_API_PREAUTH_IP_RATE_LIMIT", 2)
    monkeypatch.setattr("app.main.PUBLIC_API_PREAUTH_GLOBAL_RATE_LIMIT", 100)
    try:
        responses = [
            await public_api_client.get(
                "/api/v1/capabilities",
                headers={"Authorization": f"Bearer unique-invalid-{index}"},
            )
            for index in range(3)
        ]
    finally:
        crawler_state.public_preauth_rate_limit_buckets.clear()

    assert [response.status_code for response in responses] == [401, 401, 429]
    assert auth_calls == 2


@pytest.mark.asyncio
@pytest.mark.component
async def test_api_key_crud_returns_plaintext_once_and_deletes_immediately(
    public_api_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    async def _override_user():
        return test_user

    app.dependency_overrides[get_current_user] = _override_user
    try:
        created = await public_api_client.post(
            "/api/api-keys", json={"name": "Railway"}
        )
        listed = await public_api_client.get("/api/api-keys")
        authenticated = await public_api_client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {created.json()['api_key']}"},
        )
        deleted = await public_api_client.delete(
            f"/api/api-keys/{created.json()['id']}"
        )
        listed_after = await public_api_client.get("/api/api-keys")
        rejected = await public_api_client.get(
            "/api/v1/capabilities",
            headers={"Authorization": f"Bearer {created.json()['api_key']}"},
        )
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert created.status_code == 201
    payload = created.json()
    assert payload["api_key"].startswith("cai_")
    assert payload["key_prefix"] == payload["api_key"][:12]
    assert listed.status_code == 200
    assert listed.json()[0]["name"] == "Railway"
    assert authenticated.status_code == 200
    assert deleted.status_code == 204
    assert deleted.content == b""
    assert rejected.status_code == 401
    # Deletion is permanent: the key leaves no row behind and stops being
    # listed, so its key_hash also frees up the unique index.
    assert listed_after.status_code == 200
    assert listed_after.json() == []
    stored = await db_session.scalar(select(ApiKey).where(ApiKey.id == payload["id"]))
    assert stored is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_capabilities_uses_api_key_envelope(
    public_api_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    raw_key = "crawlerai_public_test_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="test",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    response = await public_api_client.get(
        "/api/v1/capabilities",
        headers={"Authorization": f"Bearer {raw_key}"},
    )

    assert response.status_code == 200
    assert response.headers["X-RateLimit-Limit"] == "600"
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["surfaces"] == ["ecommerce"]
    assert "extract_product" in payload["data"]["tools"]
    assert "alert_product" not in payload["data"]["tools"]
    assert "watches" not in payload["data"]["deferred"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_authenticate_public_api_key_rejects_legacy_unkeyed_hash(
    db_session,
    test_user,
) -> None:
    raw_key = "crawlerai_legacy_public_test_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="legacy",
            key_prefix="crawlerai",
            key_hash="legacy-unkeyed-hash-placeholder",
            is_active=True,
        )
    )
    await db_session.commit()

    with pytest.raises(HTTPException):
        await authenticate_public_api_key(db_session, f"Bearer {raw_key}", touch=False)


@pytest.mark.asyncio
@pytest.mark.component
async def test_authenticate_public_api_key_fails_when_touch_commit_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _Session:
        def __init__(self) -> None:
            self.api_key = ApiKey(
                id=7,
                user_id=11,
                name="test",
                key_prefix="crawlerai",
                key_hash=hash_api_key("secret"),
                is_active=True,
            )
            self.user = User(
                **{
                    "id": 11,
                    "email": "test@example.com",
                    _password_field_name(hashed=True): "x",
                    "is_active": True,
                }
            )
            self.rolled_back = False

        async def scalar(self, _statement):
            return self.api_key

        async def get(self, model, _id):
            return self.user if model is User else None

        async def commit(self):
            raise SQLAlchemyError("boom")

        async def rollback(self):
            self.rolled_back = True

    monkeypatch.setattr(public_auth, "_monotonic", lambda: 1.0)
    session = _Session()
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_public_api_key(session, "Bearer secret", touch=True)

    assert exc_info.value.status_code == 503
    assert exc_info.value.detail["code"] == PUBLIC_API_ERROR_AUTH_UNAVAILABLE
    assert session.rolled_back is True


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_api_principal_cache_skips_touch_update_within_ttl(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_cached_principal_key"
    _seed_public_api_key(db_session, test_user.id, raw_key)
    await db_session.commit()
    monkeypatch.setattr(public_auth, "_monotonic", lambda: 1.0)
    commit_counts = _count_commits(db_session, monkeypatch)

    first = await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert commit_counts[0] == 1  # cold path: last_used_at touch commit

    second = await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert second == first
    # Warm hit inside the throttle window: no last_used_at UPDATE at all.
    assert commit_counts[0] == 1


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_api_principal_cache_throttled_touch_advances_after_interval(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_throttled_touch_key"
    _seed_public_api_key(db_session, test_user.id, raw_key)
    await db_session.commit()
    clock = {"now": 1_000.0}
    monkeypatch.setattr(public_auth, "_monotonic", lambda: clock["now"])
    commit_counts = _count_commits(db_session, monkeypatch)

    await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert commit_counts[0] == 1

    clock["now"] += PUBLIC_API_LAST_USED_TOUCH_SECONDS - 1
    await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert commit_counts[0] == 1  # still throttled

    clock["now"] += 2
    await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert commit_counts[0] == 2  # throttle elapsed: touch UPDATE landed


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_api_principal_cache_bounds_deletion_staleness_by_ttl(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A deleted key keeps working until the per-process cache entry expires.

    This staleness is deliberate and documented in the UI ("can take up to one
    minute"): the principal cache is per-process and there is no cross-process
    invalidation, so the TTL is the upper bound on how long a deleted key can
    still authenticate in a process that did not perform the delete.
    """
    raw_key = "crawlerai_deleted_cached_key"
    api_key = _seed_public_api_key(db_session, test_user.id, raw_key)
    await db_session.commit()
    clock = {"now": 2_000.0}
    monkeypatch.setattr(public_auth, "_monotonic", lambda: clock["now"])

    principal = await authenticate_public_api_key(db_session, f"Bearer {raw_key}")

    await db_session.delete(api_key)
    await db_session.commit()

    # Within the cache TTL the deleted key is still accepted (bounded staleness).
    cached = await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert cached == principal

    # After the TTL the deletion is observed and the key is rejected.
    clock["now"] += PUBLIC_API_PRINCIPAL_CACHE_TTL_SECONDS + 1
    with pytest.raises(HTTPException) as exc_info:
        await authenticate_public_api_key(db_session, f"Bearer {raw_key}")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
@pytest.mark.component
async def test_delete_cannot_be_undone_by_inflight_authentication_cache_fill(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_race_regression_key"
    api_key = _seed_public_api_key(db_session, test_user.id, raw_key)
    await db_session.commit()
    cache_fill_started = asyncio.Event()
    allow_cache_fill = asyncio.Event()
    original_cache_principal = public_auth._cache_principal

    async def _paused_cache_fill(key_hash, entry):
        cache_fill_started.set()
        await allow_cache_fill.wait()
        await original_cache_principal(key_hash, entry)

    monkeypatch.setattr(public_auth, "_cache_principal", _paused_cache_fill)
    authentication = asyncio.create_task(
        authenticate_public_api_key(db_session, f"Bearer {raw_key}", touch=False)
    )
    await cache_fill_started.wait()
    deletion = asyncio.create_task(
        delete_api_key(db_session, user_id=test_user.id, key_id=api_key.id)
    )
    await asyncio.sleep(0)
    assert deletion.done() is False

    allow_cache_fill.set()
    await authentication
    await deletion

    with pytest.raises(HTTPException):
        await authenticate_public_api_key(db_session, f"Bearer {raw_key}", touch=False)


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_api_principal_cache_warm_touch_failure_is_best_effort(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    raw_key = "crawlerai_best_effort_touch_key"
    _seed_public_api_key(db_session, test_user.id, raw_key)
    await db_session.commit()
    clock = {"now": 3_000.0}
    monkeypatch.setattr(public_auth, "_monotonic", lambda: clock["now"])
    # Keep the entry warm past the touch-throttle interval.
    monkeypatch.setattr(public_auth, "PUBLIC_API_PRINCIPAL_CACHE_TTL_SECONDS", 10_000)

    principal = await authenticate_public_api_key(db_session, f"Bearer {raw_key}")

    clock["now"] += PUBLIC_API_LAST_USED_TOUCH_SECONDS + 1

    async def _failing_commit():
        raise SQLAlchemyError("boom")

    monkeypatch.setattr(db_session, "commit", _failing_commit)
    with caplog.at_level(logging.ERROR, logger="app.core.public_auth"):
        warmed = await authenticate_public_api_key(db_session, f"Bearer {raw_key}")

    assert warmed == principal  # warm-path touch failure logs, never 503s
    assert "best-effort" in caplog.text


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_auth_session_closes_async_generator_override() -> None:
    session = object()
    cleaned = False

    async def _override_db():
        nonlocal cleaned
        try:
            yield session
        finally:
            cleaned = True

    request = type(
        "_Request",
        (),
        {
            "app": type(
                "_App",
                (),
                {"dependency_overrides": {get_db: _override_db}},
            )(),
        },
    )()

    async with _public_auth_session(request) as resolved:
        assert resolved is session

    assert cleaned is True
