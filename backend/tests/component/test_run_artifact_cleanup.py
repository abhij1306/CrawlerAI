"""2.14: artifact cleanup on run delete + retention sweeper."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import tasks as app_tasks
from app.core.config import settings
from app.core.dependencies import get_current_user, get_db
from app.crawl.crud import create_crawl_run
from app.crawl.state import CrawlStatus, update_run_status
from app.main import app
from app.models.crawl_run import CrawlRun
from app.tasks import (
    _sweep_run_artifacts,
    _sweep_run_cookie_states,
    sweep_run_artifacts_task,
)


def _write_run_tree(root: Path, run_id: int) -> Path:
    tree = root / "runs" / str(run_id) / "results" / "1"
    tree.mkdir(parents=True)
    (tree / "diagnose.json").write_text("{}", encoding="utf-8")
    return root / "runs" / str(run_id)


async def _make_run(
    db_session: AsyncSession, test_user, status: CrawlStatus
) -> CrawlRun:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
        },
    )
    if status is not CrawlStatus.PENDING:
        update_run_status(run, CrawlStatus.RUNNING)
        if status is not CrawlStatus.RUNNING:
            update_run_status(run, status)
        await db_session.commit()
    return run


async def _backdate_updated_at(
    db_session: AsyncSession, run_id: int, days: int
) -> None:
    await db_session.execute(
        update(CrawlRun)
        .where(CrawlRun.id == run_id)
        .values(updated_at=datetime.now(UTC) - timedelta(days=days))
    )
    await db_session.commit()


@pytest.mark.asyncio
@pytest.mark.component
async def test_delete_run_removes_artifact_tree(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    run = await _make_run(db_session, test_user, CrawlStatus.COMPLETED)
    tree = _write_run_tree(tmp_path, run.id)
    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir()
    monkeypatch.setattr(settings, "cookie_store_dir", cookie_dir)
    cookie_files = [
        cookie_dir / f"run_{run.id}.json",
        cookie_dir / f"run_{run.id}__chromium.json",
        cookie_dir / f"run_{run.id}__real_chrome.json",
    ]
    for path in cookie_files:
        path.write_text("encrypted", encoding="utf-8")

    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.delete(f"/api/crawls/{run.id}")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 204
    assert await db_session.get(CrawlRun, run.id) is None
    assert not tree.exists()
    assert not any(path.exists() for path in cookie_files)


@pytest.mark.asyncio
@pytest.mark.component
async def test_sweep_run_artifacts_deletes_missing_and_old_terminal_trees(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    monkeypatch.setattr(settings, "run_artifacts_retention_days", 30)
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(app_tasks, "SessionLocal", session_factory)

    missing_tree = _write_run_tree(tmp_path, 999_001)

    old_terminal = await _make_run(db_session, test_user, CrawlStatus.COMPLETED)
    await _backdate_updated_at(db_session, old_terminal.id, 45)
    old_terminal_tree = _write_run_tree(tmp_path, old_terminal.id)

    young_terminal = await _make_run(db_session, test_user, CrawlStatus.COMPLETED)
    young_terminal_tree = _write_run_tree(tmp_path, young_terminal.id)

    old_active = await _make_run(db_session, test_user, CrawlStatus.RUNNING)
    await _backdate_updated_at(db_session, old_active.id, 45)
    old_active_tree = _write_run_tree(tmp_path, old_active.id)

    await _sweep_run_artifacts()

    assert not missing_tree.exists()
    assert not old_terminal_tree.exists()
    assert young_terminal_tree.exists()
    assert old_active_tree.exists()


@pytest.mark.asyncio
@pytest.mark.component
async def test_sweep_run_artifacts_disabled_at_zero_retention(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    monkeypatch.setattr(settings, "run_artifacts_retention_days", 0)
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(app_tasks, "SessionLocal", session_factory)
    missing_tree = _write_run_tree(tmp_path, 999_002)

    await _sweep_run_artifacts()

    assert missing_tree.exists()


@pytest.mark.asyncio
@pytest.mark.component
async def test_sweep_run_cookie_states_deletes_missing_and_old_terminal_files(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cookie_dir = tmp_path / "cookies"
    cookie_dir.mkdir()
    monkeypatch.setattr(settings, "cookie_store_dir", cookie_dir)
    monkeypatch.setattr(settings, "run_artifacts_retention_days", 30)
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(app_tasks, "SessionLocal", session_factory)

    missing = cookie_dir / "run_999001__chromium.json"
    missing.write_text("encrypted", encoding="utf-8")
    old_terminal = await _make_run(db_session, test_user, CrawlStatus.COMPLETED)
    await _backdate_updated_at(db_session, old_terminal.id, 45)
    old_file = cookie_dir / f"run_{old_terminal.id}__chromium.json"
    old_file.write_text("encrypted", encoding="utf-8")
    active = await _make_run(db_session, test_user, CrawlStatus.RUNNING)
    active_file = cookie_dir / f"run_{active.id}__chromium.json"
    active_file.write_text("encrypted", encoding="utf-8")

    await _sweep_run_cookie_states()

    assert not missing.exists()
    assert not old_file.exists()
    assert active_file.exists()


@pytest.mark.asyncio
@pytest.mark.component
async def test_sweep_run_artifacts_task_invokes_worker_loop(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """The Celery task delegates to the async sweep on the worker loop."""
    monkeypatch.setattr(settings, "artifacts_dir", tmp_path)
    monkeypatch.setattr(settings, "run_artifacts_retention_days", 30)
    session_factory = async_sessionmaker(bind=db_session.bind, expire_on_commit=False)
    monkeypatch.setattr(app_tasks, "SessionLocal", session_factory)
    missing_tree = _write_run_tree(tmp_path, 999_003)
    captured: dict[str, object] = {}

    def _fake_worker_loop(task_name: str, coro_factory) -> None:
        captured["task_name"] = task_name
        captured["coro_factory"] = coro_factory

    monkeypatch.setattr(app_tasks, "_run_coro_in_worker_loop", _fake_worker_loop)

    sweep_run_artifacts_task()

    assert captured["task_name"] == "sweep-run-artifacts"
    await captured["coro_factory"]()
    assert not missing_tree.exists()
