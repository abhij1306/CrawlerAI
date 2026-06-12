"""Fetch proxy shaping and browser escalation policy helpers."""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import quote, unquote, urlparse, urlunparse

from app.services.acquisition.host_protection_memory import HostProtectionPolicy
from app.services.acquisition.runtime import classify_block_from_headers
from app.services.config.runtime_settings import crawler_runtime_settings

logger = logging.getLogger(__name__)

_VENDOR_BLOCK_REASON_PREFIX = "vendor-block:"
_SUPPORTED_FORCED_ENGINES = {"patchright", "real_chrome"}


def resolve_proxy_attempts(
    proxy_list: list[str] | None,
    run_id: int | None = None,
    proxy_profile: dict[str, object] | None = None,
) -> list[str | None]:
    seen: set[str] = set()
    proxies: list[str] = []
    session_rewrite_enabled = proxy_session_rewrite_enabled(proxy_profile)
    for proxy in list(proxy_list or []):
        value = str(proxy or "").strip()
        if not value:
            continue
        if session_rewrite_enabled:
            value = attach_proxy_run_session(value, run_id=run_id)
        if value in seen:
            continue
        seen.add(value)
        proxies.append(value)
    return [*proxies] if proxies else [None]


def attach_proxy_run_session(proxy_url: str, *, run_id: int | None) -> str:
    if run_id is None:
        return proxy_url
    raw_proxy = str(proxy_url or "").strip()
    if not raw_proxy:
        return raw_proxy
    parsed = urlparse(raw_proxy)
    username = str(parsed.username or "").strip()
    if not username:
        return raw_proxy
    decoded_username = unquote(username)
    if "-session-" in decoded_username:
        session_username = re.sub(
            r"-session-[^:]+",
            f"-session-r{run_id}",
            decoded_username,
        )
    else:
        session_username = f"{decoded_username}-session-r{run_id}"
    auth = quote(session_username, safe="")
    if parsed.password is not None:
        auth = f"{auth}:{quote(unquote(str(parsed.password)), safe='')}"
    host = str(parsed.hostname or "").strip()
    if not host:
        return raw_proxy
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    netloc = auth + "@"
    netloc += f"{host}:{parsed.port}" if parsed.port is not None else host
    return urlunparse(parsed._replace(netloc=netloc))


def normalize_proxy_profile(value: dict[str, object] | None) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def proxy_session_rewrite_enabled(proxy_profile: dict[str, object] | None) -> bool:
    if not isinstance(proxy_profile, dict):
        return False
    for key in tuple(crawler_runtime_settings.proxy_session_rewrite_enabled_keys or ()):
        if bool(proxy_profile.get(str(key))):
            return True
    return False


def normalize_fetch_mode(value: object) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"auto", "http_only", "browser_only", "http_then_browser"}:
        return normalized
    return "auto"


def attach_exception_browser_diagnostics(
    exc: Exception | None,
    diagnostics: dict[str, object] | None,
) -> None:
    if exc is None or not diagnostics:
        return
    setattr(exc, "browser_diagnostics", dict(diagnostics))


def attach_browser_attempt_diagnostics(
    result: Any,
    *,
    diagnostics: dict[str, object] | None,
) -> None:
    if not diagnostics:
        return
    merged = dict(getattr(result, "browser_diagnostics", None) or {})
    merged.update(dict(diagnostics))
    result.browser_diagnostics = merged


def vendor_confirmed_block(result: Any) -> str | None:
    if not result.blocked:
        return None
    return classify_block_from_headers(result.headers)


def hard_browser_requirement(
    *,
    context: Any,
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    active_policy = runtime_policy or context.runtime_policy
    return bool(active_policy.get("requires_browser")) or context.traversal_required


def browser_first_decision(
    *,
    context: Any,
    prefer_browser: bool,
    host_preference_enabled: bool,
) -> bool:
    if context.fetch_mode == "browser_only":
        return True
    if context.fetch_mode == "http_then_browser":
        return False
    if context.fetch_mode == "http_only":
        return hard_browser_requirement(context=context)
    return (
        prefer_browser
        or host_preference_enabled
        or hard_browser_requirement(context=context)
    )


def browser_escalation_allowed(
    *,
    context: Any,
    runtime_policy: dict[str, object] | None = None,
) -> bool:
    if context.fetch_mode in {"browser_only", "http_then_browser"}:
        return True
    if context.fetch_mode == "http_only":
        return hard_browser_requirement(context=context, runtime_policy=runtime_policy)
    return True


def browser_first_reason(
    *,
    context: Any,
    prefer_browser: bool,
    host_preference_enabled: bool,
) -> str:
    if context.fetch_mode == "browser_only":
        return "fetch_mode:browser_only"
    if prefer_browser:
        return "prefer_browser"
    if host_preference_enabled:
        return "host-preference"
    if hard_browser_requirement(context=context):
        return "hard_requirement"
    return "auto"


def resolve_browser_reason(
    *,
    browser_reason: str | None,
    requires_browser: bool,
    traversal_required: bool,
    host_preference_enabled: bool,
) -> str:
    if str(browser_reason or "").strip():
        return str(browser_reason).strip().lower()
    if requires_browser:
        return "platform-required"
    if traversal_required:
        return "traversal-required"
    if host_preference_enabled:
        return "host-preference"
    return "http-escalation"


def host_policy_snapshot(policy: HostProtectionPolicy) -> dict[str, object]:
    return {
        "prefer_browser": bool(policy.prefer_browser),
        "last_block_vendor": policy.last_block_vendor,
        "hard_block_count": int(policy.hard_block_count),
        "request_blocked": bool(policy.request_blocked),
        "chromium_blocked": bool(policy.chromium_blocked),
        "patchright_blocked": bool(policy.patchright_blocked),
        "real_chrome_blocked": bool(policy.real_chrome_blocked),
        "patchright_success": bool(policy.patchright_success),
        "real_chrome_success": bool(policy.real_chrome_success),
        "last_block_method": policy.last_block_method,
    }


def is_vendor_block_reason(reason: str) -> bool:
    return str(reason or "").strip().lower().startswith(_VENDOR_BLOCK_REASON_PREFIX)


def extract_vendor_from_reason(reason: str) -> str | None:
    normalized = str(reason or "").strip().lower()
    if not normalized.startswith(_VENDOR_BLOCK_REASON_PREFIX):
        return None
    vendor = normalized[len(_VENDOR_BLOCK_REASON_PREFIX) :].strip()
    return vendor or None


def browser_escalation_lane(
    *,
    context: Any,
    reason: str,
    host_policy: HostProtectionPolicy,
    proxy: str | None,
) -> str:
    if context.fetch_mode == "browser_only":
        base = "browser_only"
    elif context.fetch_mode == "http_then_browser":
        base = "http_then_browser"
    elif reason.startswith("vendor-block:"):
        base = "vendor_block"
    elif host_policy.prefer_browser:
        base = "host_memory"
    else:
        base = "http_escalation"
    if proxy:
        return f"{base}_proxy"
    return base


def browser_engine_attempts(
    *,
    context: Any,
    host_policy: HostProtectionPolicy,
    real_chrome_available: bool,
) -> list[str]:
    forced_engine = str(context.forced_browser_engine or "").strip().lower()
    if forced_engine:
        if forced_engine in _SUPPORTED_FORCED_ENGINES:
            return [forced_engine]
        logger.warning(
            "Unsupported forced_browser_engine=%r for %s; ignoring and using default engine selection",
            forced_engine,
            context.url,
        )
    engines = ["patchright"]
    if (
        not bool(crawler_runtime_settings.browser_real_chrome_enabled)
        or not real_chrome_available
    ):
        return engines
    if host_policy.patchright_blocked and host_policy.prefer_browser:
        return _prefer_engine_first(_append_engine_once(engines, "real_chrome"), "real_chrome")
    if host_policy.real_chrome_success and host_policy.prefer_browser:
        return _prefer_engine_first(_append_engine_once(engines, "real_chrome"), "real_chrome")
    if (
        host_policy.request_blocked
        or host_policy.prefer_browser
        or host_policy.last_block_vendor
    ):
        return _append_engine_once(engines, "real_chrome")
    return engines


def extend_browser_engine_attempts_after_block(
    *,
    engine_attempts: list[str],
    attempted_engine: str,
    context: Any,
    host_policy: HostProtectionPolicy,
    real_chrome_available: bool,
) -> list[str]:
    refreshed_attempts = browser_engine_attempts(
        context=context,
        host_policy=host_policy,
        real_chrome_available=real_chrome_available,
    )
    appended = list(engine_attempts)
    for engine in refreshed_attempts:
        if engine == attempted_engine or engine in appended:
            continue
        appended.append(engine)
    return appended


def durable_vendor_block_engine_attempts(
    *,
    engine_attempts: list[str],
    host_policy: HostProtectionPolicy,
    forced_engine: str | None,
) -> list[str]:
    if (
        forced_engine
        or not host_policy.prefer_browser
        or not host_policy.last_block_vendor
    ):
        return list(engine_attempts)
    prioritized = list(engine_attempts)
    last_block_method = str(host_policy.last_block_method or "").strip().lower()
    blocked_engine = (
        last_block_method.split(":", 1)[1]
        if last_block_method.startswith("browser:")
        else None
    )
    if not blocked_engine:
        return prioritized
    if blocked_engine and blocked_engine in prioritized and len(prioritized) > 1:
        prioritized = [
            candidate for candidate in prioritized if candidate != blocked_engine
        ] + [blocked_engine]
    return prioritized[:1]


def browser_escalation_proxies(
    *,
    context: Any,
    current_proxy: str | None,
    vendor_blocked: bool,
) -> list[str | None]:
    attempts = list(context.proxies)
    if not vendor_blocked:
        return attempts
    remaining = [candidate for candidate in attempts if candidate != current_proxy]
    return remaining or attempts


def _append_engine_once(engine_attempts: list[str], engine: str) -> list[str]:
    if engine not in engine_attempts:
        return [*engine_attempts, engine]
    return list(engine_attempts)


def _prefer_engine_first(engine_attempts: list[str], engine: str) -> list[str]:
    remaining = [candidate for candidate in engine_attempts if candidate != engine]
    return [engine, *remaining]
