from __future__ import annotations

# ruff: noqa: F403, F405
from .harness_runtime_test_support import *


@pytest.mark.asyncio
@pytest.mark.regression
async def test_ensure_harness_user_id_reuses_user_by_configured_email(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HARNESS_EMAIL", "harness@example.invalid")
    monkeypatch.setenv("HARNESS_PASSWORD", "HarnessSecret123!")
    monkeypatch.setenv("HARNESS_ROLE", "harness")

    first_user_id = await harness_support._ensure_harness_user_id(db_session)
    second_user_id = await harness_support._ensure_harness_user_id(db_session)
    user = (
        await db_session.execute(
            select(harness_support.User).where(
                harness_support.User.email == "harness@example.invalid"
            )
        )
    ).scalar_one()

    assert first_user_id == second_user_id == user.id
    assert user.role == "harness"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_ensure_harness_user_id_uses_local_default_credentials_without_env(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.delenv("HARNESS_EMAIL", raising=False)
    monkeypatch.delenv("HARNESS_PASSWORD", raising=False)
    monkeypatch.delenv("HARNESS_ROLE", raising=False)

    user_id = await harness_support._ensure_harness_user_id(db_session)
    user = (
        await db_session.execute(
            select(harness_support.User).where(
                harness_support.User.email == harness_support.DEFAULT_HARNESS_EMAIL
            )
        )
    ).scalar_one()

    assert user_id == user.id
    assert user.role == "harness"


@pytest.mark.asyncio
@pytest.mark.regression
async def test_ensure_harness_user_id_rejects_production_environment(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("HARNESS_EMAIL", "harness@example.invalid")
    monkeypatch.setenv("HARNESS_PASSWORD", "HarnessSecret123!")

    with pytest.raises(
        RuntimeError,
        match="Harness user access is disabled outside local/test environments",
    ):
        await harness_support._ensure_harness_user_id(db_session)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_ensure_harness_user_id_rejects_password_sync_without_flag(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HARNESS_EMAIL", "harness@example.invalid")
    monkeypatch.setenv("HARNESS_PASSWORD", "NewHarnessSecret123!")
    monkeypatch.delenv("ENABLE_HARNESS_PASSWORD_SYNC", raising=False)

    user = harness_support.User(
        email="harness@example.invalid",
        hashed_password=hash_password("OldHarnessSecret123!"),
        role="harness",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    with pytest.raises(RuntimeError, match="ENABLE_HARNESS_PASSWORD_SYNC=true"):
        await harness_support._ensure_harness_user_id(db_session)

    persisted = (
        await db_session.execute(
            select(harness_support.User).where(
                harness_support.User.email == "harness@example.invalid"
            )
        )
    ).scalar_one()
    assert verify_password("OldHarnessSecret123!", persisted.hashed_password)
    assert not verify_password("NewHarnessSecret123!", persisted.hashed_password)


@pytest.mark.asyncio
@pytest.mark.regression
async def test_ensure_harness_user_id_allows_password_sync_with_flag(
    db_session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("HARNESS_EMAIL", "harness@example.invalid")
    monkeypatch.setenv("HARNESS_PASSWORD", "NewHarnessSecret123!")
    monkeypatch.setenv("ENABLE_HARNESS_PASSWORD_SYNC", "true")

    user = harness_support.User(
        email="harness@example.invalid",
        hashed_password=hash_password("OldHarnessSecret123!"),
        role="harness",
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()

    user_id = await harness_support._ensure_harness_user_id(db_session)
    persisted = (
        await db_session.execute(
            select(harness_support.User).where(
                harness_support.User.email == "harness@example.invalid"
            )
        )
    ).scalar_one()

    assert user_id == persisted.id
    assert verify_password("NewHarnessSecret123!", persisted.hashed_password)


@pytest.mark.regression
def test_harness_user_module_does_not_export_private_ensure_helper() -> None:
    from harness import harness_user

    assert harness_user.__all__ == ["DEFAULT_HARNESS_EMAIL"]
