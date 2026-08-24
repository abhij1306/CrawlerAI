"""test_browser_context cases split by public behavior."""

from __future__ import annotations

import asyncio
import json
import os
import threading

from tests.component.browser_context_test_support import (
    Path,
    acquisition_browser_runtime,
    cookie_store,
    pytest,
)
from app.acquisition import run_cookie_storage


@pytest.fixture(autouse=True)
def _run_storage_owner(monkeypatch: pytest.MonkeyPatch):
    async def _owner(_run_id, **_kwargs):
        return 11

    monkeypatch.setattr(cookie_store, "user_id_for_run", _owner)


@pytest.mark.component
def test_browser_storage_state_persist_policy_rejects_challenge_shell_without_ready_probe() -> (
    None
):
    assert (
        acquisition_browser_runtime._browser_storage_state_is_persistable(
            blocked=False,
            finalized_diagnostics={
                "browser_outcome": "usable_content",
                "challenge_provider_hits": ["perimeterx"],
                "readiness_probes": [
                    {
                        "is_ready": False,
                    }
                ],
            },
        )
        is False
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_run_ignores_invalid_run_id() -> None:
    assert await cookie_store.load_storage_state_for_run("invalid") is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_load_storage_state_for_run_scopes_by_browser_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "chromium-session",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="chromium",
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "real-chrome-session",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="real_chrome",
    )

    chromium_state = await cookie_store.load_storage_state_for_run(
        77,
        browser_engine="chromium",
    )
    real_chrome_state = await cookie_store.load_storage_state_for_run(
        77,
        browser_engine="real_chrome",
    )

    assert chromium_state == {
        "cookies": [
            {
                "name": "chromium-session",
                "value": "1",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }
    assert real_chrome_state == {
        "cookies": [
            {
                "name": "real-chrome-session",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_run_replaces_existing_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "stale",
                    "value": "1",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "old", "value": "1"}],
                }
            ],
        },
    )
    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "fresh",
                    "value": "2",
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [
                {
                    "origin": "https://example.com",
                    "localStorage": [{"name": "new", "value": "2"}],
                }
            ],
        },
    )

    assert await cookie_store.load_storage_state_for_run(77) == {
        "cookies": [
            {
                "name": "fresh",
                "value": "2",
                "domain": ".example.com",
                "path": "/",
            }
        ],
        "origins": [],
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_run_storage_state_file_is_encrypted_and_owner_bound(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()
    sentinel = "cookie-secret-sentinel"

    await cookie_store.persist_storage_state_for_run(
        77,
        {
            "cookies": [
                {
                    "name": "session",
                    "value": sentinel,
                    "domain": ".example.com",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        browser_engine="chromium",
        user_id=11,
    )

    path = tmp_path / "run_77__chromium.json"
    raw = path.read_text(encoding="utf-8")
    envelope = json.loads(raw)
    assert sentinel not in raw
    assert envelope["run_id"] == 77
    assert envelope["user_id"] == 11
    assert envelope["browser_engine"] == "chromium"
    assert envelope["ct"]
    assert (
        await cookie_store.load_storage_state_for_run(
            77, browser_engine="chromium", user_id=12
        )
        is None
    )
    loaded = await cookie_store.load_storage_state_for_run(
        77, browser_engine="chromium", user_id=11
    )
    assert loaded is not None
    assert loaded["cookies"][0]["value"] == sentinel
    if os.name != "nt":
        assert path.stat().st_mode & 0o077 == 0


@pytest.mark.asyncio
@pytest.mark.component
async def test_persist_storage_state_for_run_keeps_cache_clean_when_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    def _raise_write(path, storage_state) -> None:
        del path, storage_state
        raise OSError("write failed")

    monkeypatch.setattr(run_cookie_storage, "_write_storage_state_file", _raise_write)

    with pytest.raises(OSError, match="write failed"):
        await cookie_store.persist_storage_state_for_run(
            77,
            {
                "cookies": [
                    {
                        "name": "fresh",
                        "value": "2",
                        "domain": ".example.com",
                        "path": "/",
                    }
                ],
                "origins": [],
            },
        )

    assert await cookie_store.load_storage_state_for_run(77) is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_delete_run_storage_states_respects_run_id_boundary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    own_paths = [
        tmp_path / "run_1.json",
        tmp_path / "run_1__chromium.json",
        tmp_path / ".run_1.json.10.20.tmp",
        tmp_path / ".run_1__chromium.json.10.20.tmp",
    ]
    other_path = tmp_path / ".run_12__chromium.json.10.20.tmp"
    for path in [*own_paths, other_path]:
        path.write_text("state", encoding="utf-8")

    deleted = await run_cookie_storage.delete_run_storage_states(1)

    assert deleted == len(own_paths)
    assert all(not path.exists() for path in own_paths)
    assert other_path.exists()


@pytest.mark.asyncio
@pytest.mark.component
async def test_cache_clear_does_not_restore_an_inflight_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await run_cookie_storage.clear_run_storage_state_cache()
    read_started = threading.Event()
    release_read = threading.Event()
    loaded_state = {"cookies": [], "origins": []}

    def _read(*_args, **_kwargs):
        read_started.set()
        release_read.wait(timeout=2)
        return loaded_state

    monkeypatch.setattr(run_cookie_storage, "_read_storage_state_file", _read)
    load_task = asyncio.create_task(
        run_cookie_storage.load_run_storage_state(
            1,
            user_id=11,
            browser_engine="firefox",
        )
    )
    assert await asyncio.to_thread(read_started.wait, 1)

    await run_cookie_storage.clear_run_storage_state_cache()
    release_read.set()

    assert await load_task is None
    assert (
        await run_cookie_storage.load_run_storage_state(
            1,
            user_id=11,
            browser_engine="firefox",
        )
        == loaded_state
    )


@pytest.mark.component
def test_write_storage_state_file_retries_permission_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    path = tmp_path / "state.json"
    attempts: list[int] = []
    original_replace = Path.replace

    def _flaky_replace(self: Path, target: Path) -> Path:
        attempts.append(1)
        if len(attempts) == 1:
            raise PermissionError("busy")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", _flaky_replace)
    monkeypatch.setattr(run_cookie_storage.time, "sleep", lambda _seconds: None)

    run_cookie_storage._write_storage_state_file(
        path,
        {"cookies": [], "origins": []},
    )

    assert path.exists()
    assert len(attempts) == 2
