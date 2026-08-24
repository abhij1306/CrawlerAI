from __future__ import annotations

import pytest

from app.core.public_auth import hash_api_key
from app.core.api_key_service import create_api_key, delete_api_key, list_api_keys
from app.models.api_key import ApiKey


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
async def test_list_and_delete_api_keys_are_user_scoped(db_session, test_user) -> None:
    row, _ = await create_api_key(
        db_session,
        user_id=test_user.id,
        name="Console key",
    )
    key_id = row.id

    listed = await list_api_keys(db_session, user_id=test_user.id)
    assert [item.id for item in listed] == [key_id]

    # Scoping is checked while the row still exists — otherwise this would
    # pass on the row simply being absent.
    with pytest.raises(LookupError):
        await delete_api_key(db_session, user_id=test_user.id + 999, key_id=key_id)
    assert await db_session.get(ApiKey, key_id) is not None

    await delete_api_key(db_session, user_id=test_user.id, key_id=key_id)

    # Deletion is permanent: no row is left behind for any caller to see.
    assert await db_session.get(ApiKey, key_id) is None
    assert await list_api_keys(db_session, user_id=test_user.id) == []
    with pytest.raises(LookupError):
        await delete_api_key(db_session, user_id=test_user.id, key_id=key_id)


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_api_key_rejects_empty_name(db_session, test_user) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await create_api_key(db_session, user_id=test_user.id, name=" ")
