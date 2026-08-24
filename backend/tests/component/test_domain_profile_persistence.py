"""test_crawl_service cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_service_test_support import (
    AsyncSession,
    DomainRunProfile,
    ProgrammingError,
    async_sessionmaker,
    asyncio,
    load_domain_run_profile,
    normalize_domain_run_profile,
    pytest,
    save_domain_run_profile,
    select,
)
from app.core.security import hash_password
from app.models.crawl_run import CrawlRun
from app.models.user import User


@pytest.mark.asyncio
@pytest.mark.component
async def test_ordinary_user_run_cannot_persist_global_profile(
    db_session: AsyncSession,
) -> None:
    ordinary = User(
        email="ordinary-profile@example.com",
        hashed_password=hash_password("password123"),
        role="user",
    )
    db_session.add(ordinary)
    await db_session.flush()
    run = CrawlRun(
        user_id=ordinary.id,
        run_type="crawl",
        url="https://ordinary.example/products/1",
        status="running",
        surface="ecommerce_detail",
    )
    db_session.add(run)
    await db_session.flush()

    returned = await save_domain_run_profile(
        db_session,
        domain="ordinary.example",
        surface="ecommerce_detail",
        profile={"fetch_profile": {"fetch_mode": "browser_only"}},
        source_run_id=run.id,
    )
    persisted = await load_domain_run_profile(
        db_session,
        domain="ordinary.example",
        surface="ecommerce_detail",
    )

    assert returned["fetch_profile"]["fetch_mode"] == "browser_only"
    assert persisted is None


@pytest.mark.parametrize(
    ("legacy_value", "expected"),
    [
        ("pagination", "paginate"),
        ("infinite_scroll", "scroll"),
    ],
)
@pytest.mark.component
def test_normalize_domain_run_profile_translates_legacy_traversal_mode(
    legacy_value: str,
    expected: str,
) -> None:
    normalized = normalize_domain_run_profile(
        {
            "fetch_profile": {
                "traversal_mode": legacy_value,
            }
        },
        source_run_id=91,
    )

    assert normalized["fetch_profile"]["traversal_mode"] == expected


@pytest.mark.asyncio
@pytest.mark.component
async def test_save_domain_run_profile_propagates_programming_error_from_profile_load(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_load_domain_run_profile(*args, **kwargs):
        del args, kwargs
        raise ProgrammingError("select 1", {}, Exception("missing table"))

    monkeypatch.setattr(
        "app.crawl.profile.repository.load_domain_run_profile",
        _fake_load_domain_run_profile,
    )

    with pytest.raises(ProgrammingError):
        await save_domain_run_profile(
            db_session,
            domain="example.com",
            surface="ecommerce_detail",
            profile={},
            source_run_id=91,
            allow_global_promotion=True,
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_save_domain_run_profile_commit_persists_changes(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    commit_calls = 0
    refresh_calls = 0

    original_commit = db_session.commit
    original_refresh = db_session.refresh

    async def _tracked_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1
        await original_commit()

    async def _tracked_refresh(instance, *args, **kwargs) -> None:
        nonlocal refresh_calls
        refresh_calls += 1
        await original_refresh(instance, *args, **kwargs)

    monkeypatch.setattr(db_session, "commit", _tracked_commit)
    monkeypatch.setattr(db_session, "refresh", _tracked_refresh)

    saved = await save_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        profile={
            "fetch_profile": {
                "fetch_mode": "browser_only",
            }
        },
        source_run_id=91,
        commit=True,
        allow_global_promotion=True,
    )

    assert saved["fetch_profile"]["fetch_mode"] == "browser_only"
    assert commit_calls == 1
    assert refresh_calls == 1

    loaded = await load_domain_run_profile(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
    )
    assert loaded is not None
    assert dict(loaded.profile or {})["fetch_profile"]["fetch_mode"] == "browser_only"


@pytest.mark.asyncio
@pytest.mark.component
async def test_save_domain_run_profile_recovers_from_concurrent_create(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.crawl.profile import repository

    original_load = repository.load_domain_run_profile
    first_reads = 0
    both_read_missing = asyncio.Event()

    async def _synchronized_load(*args, **kwargs):
        nonlocal first_reads
        existing = await original_load(*args, **kwargs)
        if existing is not None or first_reads >= 2:
            return existing
        first_reads += 1
        if first_reads == 2:
            both_read_missing.set()
        await both_read_missing.wait()
        return None

    monkeypatch.setattr(repository, "load_domain_run_profile", _synchronized_load)
    session_factory = async_sessionmaker(
        db_session.bind,
        expire_on_commit=False,
        class_=AsyncSession,
    )

    async def _save(source_run_id: int) -> dict[str, object]:
        async with session_factory() as session:
            return await save_domain_run_profile(
                session,
                domain="victoriassecret.in",
                surface="ecommerce_detail",
                profile={"fetch_profile": {"fetch_mode": "auto"}},
                source_run_id=source_run_id,
                commit=True,
                allow_global_promotion=True,
            )

    async with asyncio.timeout(5):
        saved = await asyncio.gather(_save(91), _save(92))

    assert len(saved) == 2
    async with session_factory() as verification_session:
        profiles = (
            (
                await verification_session.execute(
                    select(DomainRunProfile).where(
                        DomainRunProfile.domain == "victoriassecret.in",
                        DomainRunProfile.surface == "ecommerce_detail",
                    )
                )
            )
            .scalars()
            .all()
        )
        assert len(profiles) == 1
