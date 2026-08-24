from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Collection, Iterable, Mapping

from cryptography.fernet import InvalidToken

from app.core.database import SessionLocal
from app.core.config import settings
from app.models.domain_memory import DomainCookieMemory
from app.models.crawl_run import CrawlRun
from app.core.config.block_signatures import BLOCK_SIGNATURES
from app.core.config.cookie_settings import (
    COOKIE_FIELDS,
    DEFAULT_STORAGE_STATE_ENGINE,
    DOMAIN_STORAGE_SCOPE_SEPARATOR,
    INCLUDE_ORIGIN_STATE_IN_STORAGE,
    STORAGE_STATE_BROWSER_ENGINE_KEY,
    STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY,
    STORAGE_STATE_ENVELOPE_VERSION,
    STORAGE_STATE_ENVELOPE_VERSION_KEY,
    STORAGE_STATE_META_KEY,
    SUPPORTED_STORAGE_STATE_ENGINES,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.core.domain_utils import normalize_domain
from app.core.shared.field_coerce import object_list as _object_list
from app.core.shared.coerce_primitives import positive_int
from app.acquisition.cookie_http_export import http_cookie_pairs_for_url
from app.acquisition.run_cookie_storage import (
    clear_run_storage_state_cache,
    load_run_storage_state,
    persist_run_storage_state,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


logger = logging.getLogger(__name__)


def validate_cookie_policy_config() -> None:
    if settings.cookie_store_dir.exists() and not settings.cookie_store_dir.is_dir():
        raise ValueError(
            f"cookie_store_dir must be a directory: {settings.cookie_store_dir}"
        )
    settings.cookie_store_dir.mkdir(parents=True, exist_ok=True)
    if not settings.cookie_store_dir.is_dir():
        raise ValueError(
            f"cookie_store_dir must be a directory: {settings.cookie_store_dir}"
        )
    settings.cookie_store_dir.chmod(0o700)


_CHALLENGE_ELEMENT_CONFIG = BLOCK_SIGNATURES.get("challenge_elements")
if not isinstance(_CHALLENGE_ELEMENT_CONFIG, Mapping):
    _CHALLENGE_ELEMENT_CONFIG = {}
_STORAGE_STATE_SIGNATURES = _CHALLENGE_ELEMENT_CONFIG.get("storage_state")
if not isinstance(_STORAGE_STATE_SIGNATURES, Mapping):
    _STORAGE_STATE_SIGNATURES = {}
_CHALLENGE_COOKIE_NAME_PREFIXES = tuple(
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("cookie_name_prefixes", [])
    if str(value or "").strip()
)
_CHALLENGE_COOKIE_NAME_EXACT = {
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("cookie_name_exact", [])
    if str(value or "").strip()
}
_CHALLENGE_COOKIE_VALUE_TOKENS = tuple(
    str(value or "").strip().lower()
    for value in _STORAGE_STATE_SIGNATURES.get("cookie_value_tokens", [])
    if str(value or "").strip()
)


async def clear_cookie_store_cache() -> None:
    await clear_run_storage_state_cache()


def _encrypt_storage_state(storage_state: Mapping[str, object]) -> dict[str, object]:
    """Wrap a normalized storage state in the at-rest encryption envelope."""
    return {
        STORAGE_STATE_ENVELOPE_VERSION_KEY: STORAGE_STATE_ENVELOPE_VERSION,
        STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY: encrypt_secret(
            json.dumps(storage_state, separators=(",", ":"))
        ),
    }


def _decrypt_storage_state(
    storage_state: Mapping[str, object] | object,
    *,
    domain: str = "",
) -> dict[str, object] | None:
    """Decrypt a valid envelope; skip invalid or legacy rows for re-learning."""
    if not isinstance(storage_state, Mapping):
        return None
    if STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY not in storage_state:
        logger.warning(
            "Skipping plaintext domain cookie memory row",
            extra={"domain": domain},
        )
        return None
    if storage_state.get(STORAGE_STATE_ENVELOPE_VERSION_KEY) != (
        STORAGE_STATE_ENVELOPE_VERSION
    ):
        logger.warning(
            "Skipping domain cookie memory row with unknown envelope version",
            extra={"domain": domain},
        )
        return None
    try:
        decoded = json.loads(
            decrypt_secret(str(storage_state[STORAGE_STATE_ENVELOPE_CIPHERTEXT_KEY]))
        )
    except (InvalidToken, ValueError, TypeError):
        logger.warning(
            "Skipping undecryptable domain cookie memory row",
            extra={"domain": domain},
        )
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded


async def load_storage_state_for_run(
    run_id: int | None,
    *,
    browser_engine: str | None = None,
    user_id: int | None = None,
) -> dict[str, object] | None:
    normalized_run_id = positive_int(run_id)
    if normalized_run_id is None:
        return None
    normalized_user_id = positive_int(user_id)
    if normalized_user_id is None:
        normalized_user_id = await user_id_for_run(normalized_run_id)
    if normalized_user_id is None:
        return None
    validate_cookie_policy_config()
    normalized_engine = _normalized_browser_engine(browser_engine)
    state = await load_run_storage_state(
        normalized_run_id,
        user_id=normalized_user_id,
        browser_engine=normalized_engine,
    )
    if state is None:
        return None
    normalized_state = _normalize_storage_state_payload(
        state,
        browser_engine=_storage_state_browser_engine(state),
    )
    if not _storage_state_matches_browser_engine(
        normalized_state,
        browser_engine=normalized_engine,
    ):
        return None
    return _clone_storage_state(normalized_state)


async def load_storage_state_for_domain(
    domain: str | None,
    *,
    session: AsyncSession | None = None,
    browser_engine: str | None = None,
    user_id: int | None = None,
) -> dict[str, object] | None:
    normalized_user_id = positive_int(user_id)
    if normalized_user_id is None:
        return None
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain:
        return None
    normalized_engine = _normalized_browser_engine(browser_engine)
    if session is None:
        async with SessionLocal() as owned_session:
            return await load_storage_state_for_domain(
                normalized_domain,
                session=owned_session,
                browser_engine=normalized_engine,
                user_id=normalized_user_id,
            )
    result = await session.execute(
        select(DomainCookieMemory)
        .where(
            DomainCookieMemory.user_id == normalized_user_id,
            DomainCookieMemory.domain.in_(
                _domain_storage_lookup_keys(
                    normalized_domain,
                    browser_engine=normalized_engine,
                )
            ),
        )
        .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
    )
    rows = list(result.scalars().all())
    for row in rows:
        raw_state = _decrypt_storage_state(row.storage_state, domain=row.domain)
        if raw_state is None:
            continue
        if not _storage_state_matches_browser_engine(
            raw_state,
            browser_engine=normalized_engine,
        ):
            continue
        normalized_state = _normalize_storage_state(raw_state)
        if not _has_reusable_storage_state(normalized_state):
            continue
        return _clone_storage_state(normalized_state)
    return None


async def export_cookie_header_for_domain(
    url: str | None,
    *,
    browser_engine: str | None = None,
    session: AsyncSession | None = None,
    run_id: int | None = None,
    user_id: int | None = None,
) -> str | None:
    state = await export_cookie_storage_state_for_domain(
        url,
        browser_engine=browser_engine,
        session=session,
        run_id=run_id,
        user_id=user_id,
    )
    if not state:
        return None
    cookie_pairs = http_cookie_pairs_for_url(url, state)
    if not cookie_pairs:
        return None
    return "; ".join(f"{name}={value}" for name, value in cookie_pairs)


async def export_cookie_storage_state_for_domain(
    url: str | None,
    *,
    browser_engine: str | None = None,
    session: AsyncSession | None = None,
    run_id: int | None = None,
    user_id: int | None = None,
) -> dict[str, object] | None:
    normalized_user_id = positive_int(user_id)
    if normalized_user_id is None:
        normalized_user_id = await user_id_for_run(run_id, session=session)
    return await load_storage_state_for_domain(
        url,
        browser_engine=browser_engine,
        session=session,
        user_id=normalized_user_id,
    )


async def persist_storage_state_for_run(
    run_id: int | None,
    storage_state: Mapping[str, object] | object,
    *,
    browser_engine: str | None = None,
    user_id: int | None = None,
) -> None:
    normalized_run_id = positive_int(run_id)
    if normalized_run_id is None or not isinstance(storage_state, Mapping):
        return
    normalized_user_id = positive_int(user_id)
    if normalized_user_id is None:
        normalized_user_id = await user_id_for_run(normalized_run_id)
    if normalized_user_id is None:
        return
    validate_cookie_policy_config()
    normalized_engine = _normalized_browser_engine(browser_engine)
    normalized_state = _normalize_storage_state_payload(
        storage_state,
        browser_engine=normalized_engine,
    )
    if not _has_reusable_storage_state(normalized_state):
        return
    await persist_run_storage_state(
        normalized_run_id,
        normalized_state,
        user_id=normalized_user_id,
        browser_engine=normalized_engine,
    )


async def persist_storage_state_for_domain(
    domain: str | None,
    storage_state: Mapping[str, object] | object,
    *,
    session: AsyncSession | None = None,
    browser_engine: str | None = None,
    user_id: int | None = None,
) -> bool:
    normalized_user_id = positive_int(user_id)
    if normalized_user_id is None:
        return False
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain or not isinstance(storage_state, Mapping):
        return False
    normalized_engine = _normalized_browser_engine(browser_engine)
    storage_key = _domain_storage_key(
        normalized_domain,
        browser_engine=normalized_engine,
    )
    normalized_state = _normalize_storage_state_payload(
        storage_state,
        browser_engine=normalized_engine,
    )
    if not _has_reusable_storage_state(normalized_state):
        return False
    fingerprint = _storage_state_fingerprint(
        normalized_state,
        browser_engine=normalized_engine,
    )
    if session is None:
        async with SessionLocal() as owned_session:
            changed = await _upsert_domain_storage_state(
                owned_session,
                storage_key=storage_key,
                normalized_state=normalized_state,
                fingerprint=fingerprint,
                user_id=normalized_user_id,
            )
            if not changed:
                return False
            await owned_session.commit()
            return True
    changed = await _upsert_domain_storage_state(
        session,
        storage_key=storage_key,
        normalized_state=normalized_state,
        fingerprint=fingerprint,
        user_id=normalized_user_id,
    )
    if not changed:
        return False
    await session.flush()
    return True


async def _upsert_domain_storage_state(
    session: AsyncSession,
    *,
    storage_key: str,
    normalized_state: dict[str, object],
    fingerprint: str,
    user_id: int,
) -> bool:
    result = await session.execute(
        select(DomainCookieMemory)
        .where(
            DomainCookieMemory.user_id == user_id,
            DomainCookieMemory.domain == storage_key,
        )
        .order_by(DomainCookieMemory.updated_at.desc(), DomainCookieMemory.id.desc())
        .limit(1)
    )
    row = result.scalars().first()
    if row is not None and str(row.state_fingerprint or "") == fingerprint:
        return False
    encrypted_state = _encrypt_storage_state(normalized_state)
    if row is None:
        row = DomainCookieMemory(
            user_id=user_id,
            domain=storage_key,
            storage_state=encrypted_state,
            state_fingerprint=fingerprint,
        )
        session.add(row)
    else:
        row.storage_state = encrypted_state
        row.state_fingerprint = fingerprint
    return True


async def list_domain_cookie_memory(
    domain: str | None = None,
    *,
    session: AsyncSession | None = None,
    user_id: int | None = None,
) -> list[dict[str, object]]:
    normalized_user_id = positive_int(user_id)
    if normalized_user_id is None:
        return []
    normalized_domain = normalize_domain(domain or "") if domain else ""
    if session is None:
        async with SessionLocal() as owned_session:
            return await list_domain_cookie_memory(
                domain,
                session=owned_session,
                user_id=normalized_user_id,
            )
    statement = (
        select(DomainCookieMemory)
        .where(DomainCookieMemory.user_id == normalized_user_id)
        .order_by(
            DomainCookieMemory.domain.asc(),
            DomainCookieMemory.updated_at.desc(),
            DomainCookieMemory.id.desc(),
        )
    )
    if normalized_domain:
        statement = statement.where(
            DomainCookieMemory.domain.in_(
                _domain_storage_lookup_keys(normalized_domain)
            )
        )
    rows = list((await session.execute(statement)).scalars().all())
    payload: list[dict[str, object]] = []
    for row in rows:
        storage_state = _decrypt_storage_state(row.storage_state, domain=row.domain)
        if storage_state is None:
            continue
        payload.append(
            {
                "id": row.id,
                "domain": _domain_from_storage_key(row.domain),
                "browser_engine": _storage_row_browser_engine(row),
                "cookie_count": _storage_state_entry_count(
                    (storage_state or {}).get("cookies")
                ),
                "origin_count": _storage_state_entry_count(
                    (storage_state or {}).get("origins")
                ),
                "updated_at": row.updated_at,
            }
        )
    return payload


async def user_id_for_run(
    run_id: int | None,
    *,
    session: AsyncSession | None = None,
) -> int | None:
    normalized_run_id = positive_int(run_id)
    if normalized_run_id is None:
        return None
    if session is None:
        async with SessionLocal() as owned_session:
            return await user_id_for_run(normalized_run_id, session=owned_session)
    return positive_int(
        await session.scalar(
            select(CrawlRun.user_id).where(CrawlRun.id == normalized_run_id)
        )
    )


def _storage_state_fingerprint(
    storage_state: Mapping[str, object],
    *,
    browser_engine: str | None = None,
) -> str:
    payload = json.dumps(
        _normalize_storage_state_payload(
            storage_state,
            browser_engine=browser_engine
            or _storage_state_browser_engine(storage_state),
        ),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _domain_storage_key(
    domain: str,
    *,
    browser_engine: str | None = None,
) -> str:
    normalized_domain = normalize_domain(domain or "")
    normalized_engine = _normalized_browser_engine(browser_engine)
    if not normalized_domain:
        return ""
    if normalized_engine and normalized_engine != DEFAULT_STORAGE_STATE_ENGINE:
        return f"{normalized_engine}{DOMAIN_STORAGE_SCOPE_SEPARATOR}{normalized_domain}"
    return normalized_domain


def _domain_storage_lookup_keys(
    domain: str,
    *,
    browser_engine: str | None = None,
) -> tuple[str, ...]:
    normalized_domain = normalize_domain(domain or "")
    if not normalized_domain:
        return ()
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine == DEFAULT_STORAGE_STATE_ENGINE:
        return (normalized_domain,)
    if normalized_engine:
        return (
            _domain_storage_key(normalized_domain, browser_engine=normalized_engine),
        )
    return (
        normalized_domain,
        *(
            _domain_storage_key(normalized_domain, browser_engine=engine)
            for engine in sorted(SUPPORTED_STORAGE_STATE_ENGINES)
            if engine != DEFAULT_STORAGE_STATE_ENGINE
        ),
    )


def _normalize_storage_state(storage_state: Mapping[str, object]) -> dict[str, object]:
    return {
        "cookies": _normalize_cookies(storage_state.get("cookies")),
        # Replaying origin-scoped state causes headful Chrome to wake stale site state
        # before the requested URL. Keep reusable memory cookie-only.
        "origins": (
            _object_list(storage_state.get("origins"))
            if INCLUDE_ORIGIN_STATE_IN_STORAGE
            else []
        ),
    }


def _storage_state_entry_count(value: object) -> int:
    if isinstance(value, Collection) and not isinstance(
        value,
        (str, bytes, bytearray, Mapping),
    ):
        return len(value)
    return len(_object_list(value))


def _normalize_storage_state_payload(
    storage_state: Mapping[str, object],
    *,
    browser_engine: str | None = None,
) -> dict[str, object]:
    payload = _normalize_storage_state(storage_state)
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine is None:
        normalized_engine = _storage_state_browser_engine(storage_state)
    if normalized_engine is not None:
        payload[STORAGE_STATE_META_KEY] = {
            STORAGE_STATE_BROWSER_ENGINE_KEY: normalized_engine,
        }
    return payload


def _has_reusable_storage_state(storage_state: Mapping[str, object]) -> bool:
    return bool(_object_list(storage_state.get("cookies")))


def _normalize_cookies(value: object) -> list[dict[str, object]]:
    now = time.time()
    cookies_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    rows = (
        list(value)
        if isinstance(value, Iterable)
        and not isinstance(value, (str, bytes, bytearray, Mapping))
        else _object_list(value)
    )
    for item in rows:
        cookie = _normalized_cookie(item, now=now)
        if cookie is None:
            continue
        key = (
            str(cookie.get("name") or "").strip().lower(),
            str(cookie.get("domain") or cookie.get("url") or "").strip().lower(),
            str(cookie.get("path") or "/").strip() or "/",
        )
        cookies_by_key[key] = cookie
    return list(cookies_by_key.values())


def _normalized_cookie(item: object, *, now: float) -> dict[str, object] | None:
    if not isinstance(item, Mapping):
        return None
    cookie = {
        field_name: _sanitize_storage_state_scalar(item[field_name])
        for field_name in COOKIE_FIELDS
        if item.get(field_name) not in (None, "")
    }
    if not cookie.get("name") or not cookie.get("value"):
        return None
    if _cookie_is_challenge_state(cookie):
        return None
    expires = cookie.get("expires")
    if isinstance(expires, (int, float)) and 0 < float(expires) <= now:
        return None
    return cookie


def _normalized_browser_engine(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in SUPPORTED_STORAGE_STATE_ENGINES:
        return normalized
    return None


def _storage_state_browser_engine(
    storage_state: Mapping[str, object] | object,
) -> str | None:
    if not isinstance(storage_state, Mapping):
        return None
    metadata = storage_state.get(STORAGE_STATE_META_KEY)
    if not isinstance(metadata, Mapping):
        return None
    return _normalized_browser_engine(metadata.get(STORAGE_STATE_BROWSER_ENGINE_KEY))


def _storage_state_matches_browser_engine(
    storage_state: Mapping[str, object] | object,
    *,
    browser_engine: str | None,
) -> bool:
    normalized_engine = _normalized_browser_engine(browser_engine)
    if normalized_engine is None:
        return True
    stored_engine = _storage_state_browser_engine(storage_state)
    if stored_engine is None:
        return normalized_engine == DEFAULT_STORAGE_STATE_ENGINE
    return stored_engine == normalized_engine


def _domain_from_storage_key(value: object) -> str:
    normalized = str(value or "").strip()
    if DOMAIN_STORAGE_SCOPE_SEPARATOR not in normalized:
        return normalized
    engine, domain = normalized.split(DOMAIN_STORAGE_SCOPE_SEPARATOR, 1)
    if _normalized_browser_engine(engine) is None:
        return normalized
    return domain


def _storage_key_browser_engine(value: object) -> str | None:
    normalized = str(value or "").strip()
    if DOMAIN_STORAGE_SCOPE_SEPARATOR not in normalized:
        return None
    engine, _domain = normalized.split(DOMAIN_STORAGE_SCOPE_SEPARATOR, 1)
    return _normalized_browser_engine(engine)


def _storage_row_browser_engine(row: DomainCookieMemory) -> str:
    return (
        _storage_state_browser_engine(row.storage_state)
        or _storage_key_browser_engine(row.domain)
        or DEFAULT_STORAGE_STATE_ENGINE
    )


def _sanitize_storage_state_scalar(value: object) -> object:
    if isinstance(value, str):
        return value.replace("\x00", "")
    return value


def _cookie_name_is_challenge_state(value: object) -> bool:
    lowered = str(value or "").strip().lower()
    if not lowered:
        return False
    if lowered in _CHALLENGE_COOKIE_NAME_EXACT:
        return True
    return any(lowered.startswith(prefix) for prefix in _CHALLENGE_COOKIE_NAME_PREFIXES)


def _cookie_is_challenge_state(cookie: Mapping[str, object]) -> bool:
    if _cookie_name_is_challenge_state(cookie.get("name")):
        return True
    value = str(cookie.get("value") or "").strip().lower()
    if not value:
        return False
    return any(token in value for token in _CHALLENGE_COOKIE_VALUE_TOKENS)


def _clone_storage_state(
    storage_state: Mapping[str, object] | None,
) -> dict[str, object] | None:
    if storage_state is None:
        return None
    cookies = _object_list(storage_state.get("cookies"))
    origins = _object_list(storage_state.get("origins"))
    return {
        "cookies": [dict(cookie) for cookie in cookies if isinstance(cookie, Mapping)],
        "origins": [
            {
                "origin": str(origin.get("origin") or ""),
                "localStorage": [
                    {
                        "name": str(entry.get("name") or ""),
                        "value": str(entry.get("value") or ""),
                    }
                    for entry in _object_list(origin.get("localStorage"))
                    if isinstance(entry, Mapping)
                ],
            }
            for origin in origins
            if isinstance(origin, Mapping)
        ],
    }
