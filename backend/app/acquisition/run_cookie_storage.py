"""Encrypted, tenant-bound filesystem storage for per-run browser cookies."""

from __future__ import annotations

import asyncio
import json
import os
import time
from collections.abc import Mapping
from pathlib import Path

from cryptography.fernet import InvalidToken

from app.core.config import settings
from app.core.config.cookie_settings import (
    DEFAULT_STORAGE_STATE_ENGINE,
    RUN_STORAGE_STATE_BROWSER_ENGINE_KEY,
    RUN_STORAGE_STATE_ENVELOPE_VERSION,
    RUN_STORAGE_STATE_RUN_ID_KEY,
    RUN_STORAGE_STATE_USER_ID_KEY,
    STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY,
    STORAGE_STATE_ENVELOPE_VERSION_KEY,
    STORAGE_STATE_REPLACE_ATTEMPTS,
    STORAGE_STATE_REPLACE_RETRY_SECONDS,
    SUPPORTED_STORAGE_STATE_ENGINES,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.core.shared.coerce_primitives import positive_int

_RUN_STORAGE_STATE_CACHE: dict[str, dict[str, object]] = {}
_RUN_STORAGE_STATE_LOCK = asyncio.Lock()


def _normalized_browser_engine(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in SUPPORTED_STORAGE_STATE_ENGINES else None


def storage_state_path(run_id: int, *, browser_engine: str | None = None) -> Path:
    normalized_engine = _normalized_browser_engine(browser_engine)
    suffix = f"__{normalized_engine}" if normalized_engine else ""
    return settings.cookie_store_dir / f"run_{run_id}{suffix}.json"


def storage_state_candidate_paths(
    run_id: int,
    *,
    browser_engine: str | None = None,
) -> tuple[Path, ...]:
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine == DEFAULT_STORAGE_STATE_ENGINE:
        return (
            storage_state_path(run_id, browser_engine=normalized_engine),
            storage_state_path(run_id),
        )
    if normalized_engine:
        return (storage_state_path(run_id, browser_engine=normalized_engine),)
    return (storage_state_path(run_id),)


async def clear_run_storage_state_cache() -> None:
    async with _RUN_STORAGE_STATE_LOCK:
        _RUN_STORAGE_STATE_CACHE.clear()


async def load_run_storage_state(
    run_id: int,
    *,
    user_id: int,
    browser_engine: str | None,
) -> dict[str, object] | None:
    normalized_engine = _normalized_browser_engine(browser_engine)
    for path in storage_state_candidate_paths(run_id, browser_engine=normalized_engine):
        cache_key = f"{path}:{user_id}"
        async with _RUN_STORAGE_STATE_LOCK:
            state = _RUN_STORAGE_STATE_CACHE.get(cache_key)
            if state is None:
                state = await asyncio.to_thread(
                    _read_storage_state_file,
                    path,
                    run_id=run_id,
                    user_id=user_id,
                    browser_engine=normalized_engine,
                )
                if state is not None:
                    _RUN_STORAGE_STATE_CACHE[cache_key] = state
        if state is not None:
            return dict(state)
    return None


async def persist_run_storage_state(
    run_id: int,
    storage_state: Mapping[str, object],
    *,
    user_id: int,
    browser_engine: str | None,
) -> None:
    normalized_engine = _normalized_browser_engine(browser_engine)
    path = storage_state_path(run_id, browser_engine=normalized_engine)
    encrypted_state = _encrypt_run_storage_state(
        storage_state,
        run_id=run_id,
        user_id=user_id,
        browser_engine=normalized_engine,
    )
    async with _RUN_STORAGE_STATE_LOCK:
        await asyncio.to_thread(_write_storage_state_file, path, encrypted_state)
        _RUN_STORAGE_STATE_CACHE[f"{path}:{user_id}"] = dict(storage_state)


def _encrypt_run_storage_state(
    storage_state: Mapping[str, object],
    *,
    run_id: int,
    user_id: int,
    browser_engine: str | None,
) -> dict[str, object]:
    return {
        STORAGE_STATE_ENVELOPE_VERSION_KEY: RUN_STORAGE_STATE_ENVELOPE_VERSION,
        RUN_STORAGE_STATE_RUN_ID_KEY: run_id,
        RUN_STORAGE_STATE_USER_ID_KEY: user_id,
        RUN_STORAGE_STATE_BROWSER_ENGINE_KEY: (
            _normalized_browser_engine(browser_engine) or DEFAULT_STORAGE_STATE_ENGINE
        ),
        STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY: encrypt_secret(
            json.dumps(storage_state, separators=(",", ":"))
        ),
    }


def _read_storage_state_file(
    path: Path,
    *,
    run_id: int,
    user_id: int,
    browser_engine: str | None,
) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        envelope = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    expected_engine = (
        _normalized_browser_engine(browser_engine) or DEFAULT_STORAGE_STATE_ENGINE
    )
    if (
        not isinstance(envelope, dict)
        or envelope.get(STORAGE_STATE_ENVELOPE_VERSION_KEY)
        != RUN_STORAGE_STATE_ENVELOPE_VERSION
        or positive_int(envelope.get(RUN_STORAGE_STATE_RUN_ID_KEY)) != run_id
        or positive_int(envelope.get(RUN_STORAGE_STATE_USER_ID_KEY)) != user_id
        or envelope.get(RUN_STORAGE_STATE_BROWSER_ENGINE_KEY) != expected_engine
    ):
        return None
    try:
        payload = json.loads(
            decrypt_secret(
                str(envelope.get(STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY) or "")
            )
        )
    except (InvalidToken, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _write_storage_state_file(path: Path, storage_state: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp_path = path.with_name(f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp")
    payload = json.dumps(storage_state, ensure_ascii=True, indent=2, sort_keys=True)
    try:
        descriptor = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        last_error: OSError | None = None
        for attempt in range(STORAGE_STATE_REPLACE_ATTEMPTS):
            try:
                tmp_path.replace(path)
                last_error = None
                break
            except PermissionError as exc:
                last_error = exc
                if attempt + 1 >= STORAGE_STATE_REPLACE_ATTEMPTS:
                    raise
                time.sleep(STORAGE_STATE_REPLACE_RETRY_SECONDS)
        if last_error is not None:
            raise last_error
        path.chmod(0o600)
    except OSError:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


async def delete_run_storage_states(run_id: int | None) -> int:
    normalized_run_id = positive_int(run_id)
    if normalized_run_id is None or not settings.cookie_store_dir.is_dir():
        return 0
    prefix = f"run_{normalized_run_id}"
    paths = [
        child
        for child in settings.cookie_store_dir.iterdir()
        if child.is_file()
        and (
            child.name == f"{prefix}.json"
            or (child.name.startswith(f"{prefix}__") and child.name.endswith(".json"))
            or (
                (
                    child.name.startswith(f".{prefix}.")
                    or child.name.startswith(f".{prefix}__")
                )
                and child.name.endswith(".tmp")
            )
        )
    ]
    async with _RUN_STORAGE_STATE_LOCK:
        deleted = 0
        for path in paths:
            try:
                await asyncio.to_thread(path.unlink)
            except FileNotFoundError:
                continue
            for cache_key in tuple(_RUN_STORAGE_STATE_CACHE):
                if cache_key.startswith(f"{path}:"):
                    _RUN_STORAGE_STATE_CACHE.pop(cache_key, None)
            deleted += 1
    return deleted
