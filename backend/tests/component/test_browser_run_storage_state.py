"""test_browser_context cases split by public behavior."""

from __future__ import annotations

from tests.component.browser_context_test_support import (
    Path,
    acquisition_browser_runtime,
    cookie_store,
    pytest,
)


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
async def test_persist_storage_state_for_run_keeps_cache_clean_when_write_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr(cookie_store.settings, "cookie_store_dir", tmp_path)
    await cookie_store.clear_cookie_store_cache()

    def _raise_write(path, storage_state) -> None:
        del path, storage_state
        raise OSError("write failed")

    monkeypatch.setattr(cookie_store, "_write_storage_state_file", _raise_write)

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
    monkeypatch.setattr(cookie_store.time, "sleep", lambda _seconds: None)

    cookie_store._write_storage_state_file(
        path,
        {"cookies": [], "origins": []},
    )

    assert path.exists()
    assert len(attempts) == 2
