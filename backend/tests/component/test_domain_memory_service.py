from __future__ import annotations

import pytest
from sqlalchemy import select

from app.acquisition.cookie_store import (
    list_domain_cookie_memory,
    load_storage_state_for_domain,
    persist_storage_state_for_domain,
)
from app.core.config import settings
from app.crawl.domain_memory_service import load_domain_memory, save_domain_memory
from app.models.domain_memory import DomainCookieMemory


@pytest.fixture(autouse=True)
async def _default_cookie_owner(monkeypatch: pytest.MonkeyPatch, test_user):
    for name in (
        "persist_storage_state_for_domain",
        "load_storage_state_for_domain",
        "list_domain_cookie_memory",
    ):
        original = globals()[name]

        async def _owned(*args, __original=original, **kwargs):
            kwargs.setdefault("user_id", test_user.id)
            return await __original(*args, **kwargs)

        monkeypatch.setitem(globals(), name, _owned)
    return test_user.id


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_memory_round_trip(db_session) -> None:
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        platform="shopify",
        selectors={"title": {"css": "h1[data-test='product-title']"}},
    )
    await db_session.commit()

    loaded = await load_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )

    assert loaded is not None
    assert loaded.platform == "shopify"
    assert loaded.selectors["title"]["css"] == "h1[data-test='product-title']"


_STORAGE_STATE = {
    "cookies": [
        {
            "name": "sid",
            "value": "abc123",
            "domain": "example.com",
            "path": "/",
        }
    ],
    "origins": [],
}


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_cookie_memory_encrypts_storage_state_at_rest(db_session) -> None:
    changed = await persist_storage_state_for_domain(
        "example.com",
        _STORAGE_STATE,
        session=db_session,
    )
    await db_session.commit()

    assert changed is True
    row = (await db_session.execute(select(DomainCookieMemory))).scalar_one()
    assert "ct" in row.storage_state
    assert row.storage_state["v"] == 1
    assert "cookies" not in row.storage_state

    loaded = await load_storage_state_for_domain("example.com", session=db_session)

    assert loaded is not None
    assert loaded["cookies"][0]["name"] == "sid"
    assert loaded["cookies"][0]["value"] == "abc123"


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_cookie_memory_rejects_legacy_plaintext_rows(
    db_session,
    _default_cookie_owner,
) -> None:
    db_session.add(
        DomainCookieMemory(
            user_id=_default_cookie_owner,
            domain="legacy.example",
            storage_state={
                "cookies": [
                    {
                        "name": "legacy",
                        "value": "token",
                        "domain": "legacy.example",
                        "path": "/",
                    }
                ],
                "origins": [],
            },
            state_fingerprint="fp-legacy",
        )
    )
    await db_session.commit()

    loaded = await load_storage_state_for_domain("legacy.example", session=db_session)

    assert loaded is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_cookie_memory_wrong_key_skips_row_without_crashing(
    db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    await persist_storage_state_for_domain(
        "example.com",
        _STORAGE_STATE,
        session=db_session,
    )
    await db_session.commit()

    monkeypatch.setattr(settings, "encryption_key", "a-different-encryption-key-000")

    loaded = await load_storage_state_for_domain("example.com", session=db_session)

    assert loaded is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_list_domain_cookie_memory_counts_encrypted_rows(db_session) -> None:
    state = {
        "cookies": [
            {"name": "a", "value": "1", "domain": "example.com", "path": "/"},
            {"name": "b", "value": "2", "domain": "example.com", "path": "/"},
        ],
        "origins": [{"origin": "https://example.com", "localStorage": []}],
    }
    await persist_storage_state_for_domain("example.com", state, session=db_session)
    await db_session.commit()

    rows = await list_domain_cookie_memory("example.com", session=db_session)

    assert len(rows) == 1
    assert rows[0]["cookie_count"] == 2
    assert rows[0]["origin_count"] == 0  # origin state is filtered by policy
    assert rows[0]["domain"] == "example.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_cookie_memory_fingerprint_dedupes_unchanged_state(
    db_session,
) -> None:
    first = await persist_storage_state_for_domain(
        "example.com", _STORAGE_STATE, session=db_session
    )
    second = await persist_storage_state_for_domain(
        "example.com", _STORAGE_STATE, session=db_session
    )

    changed_state = {
        "cookies": [
            {
                "name": "sid",
                "value": "rotated",
                "domain": "example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    third = await persist_storage_state_for_domain(
        "example.com", changed_state, session=db_session
    )
    await db_session.commit()

    assert first is True
    assert second is False
    assert third is True
    rows = list((await db_session.execute(select(DomainCookieMemory))).scalars())
    assert len(rows) == 1
