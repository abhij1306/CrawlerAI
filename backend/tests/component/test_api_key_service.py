from __future__ import annotations

import pytest

from app.core.public_auth import hash_api_key
from app.services.api_key_service import create_api_key, list_api_keys, revoke_api_key


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_api_key_returns_plaintext_once_and_stores_hash(
    db_session,
    test_user,
) -> None:
    row, raw_key = await create_api_key(
        db_session,
        user_id=test_user.id,
        name=" Console key ",
    )

    assert raw_key.startswith("cai_")
    assert row.name == "Console key"
    assert row.key_hash == hash_api_key(raw_key)
    assert row.key_hash != raw_key
    assert row.key_prefix == raw_key[: len(row.key_prefix)]


@pytest.mark.asyncio
@pytest.mark.component
async def test_list_and_revoke_api_keys_are_user_scoped(db_session, test_user) -> None:
    row, _ = await create_api_key(
        db_session,
        user_id=test_user.id,
        name="Console key",
    )

    listed = await list_api_keys(db_session, user_id=test_user.id)
    revoked = await revoke_api_key(
        db_session,
        user_id=test_user.id,
        key_id=row.id,
    )

    assert [item.id for item in listed] == [row.id]
    assert revoked.is_active is False
    assert revoked.last_used_at is not None
    with pytest.raises(LookupError):
        await revoke_api_key(db_session, user_id=test_user.id + 999, key_id=row.id)


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_api_key_rejects_empty_name(db_session, test_user) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await create_api_key(db_session, user_id=test_user.id, name=" ")


