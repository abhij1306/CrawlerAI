from __future__ import annotations

import platform
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from app.services.config.browser_fingerprint_profiles import (
    CHROME_CLIENT_HINT_GREASE_BRAND,
    CHROME_CLIENT_HINT_GREASE_VERSION,
    CHROME_CLIENT_HINT_PLATFORM_BY_HOST_OS,
    DEHEADLESS_HOST_OS_FALLBACK,
    DEHEADLESS_UA_FALLBACK_MAJOR,
    DEHEADLESS_UA_TEMPLATE_BY_HOST_OS,
    NATIVE_REAL_CHROME_CONTEXT_OPTIONS,
)
from app.services.config.runtime_settings import crawler_runtime_settings


@dataclass(frozen=True, slots=True)
class PlaywrightContextSpec:
    context_options: dict[str, Any]
    init_script: str | None = None


def _host_os_key() -> str:
    """Classify the host OS the browser engine runs on.

    The UA platform, sec-ch-ua-platform, and the engine's native
    navigator.platform must all agree, so identity is keyed off the real host
    (Windows dev box vs Linux Docker in prod), never a fixed value.
    """
    system = platform.system().lower()
    if system.startswith("win"):
        return "windows"
    if system == "darwin":
        return "macos"
    if system == "linux":
        return "linux"
    return DEHEADLESS_HOST_OS_FALLBACK


def _deheadless_user_agent(browser_major_version: int | None) -> str:
    """Return a non-headless, host-OS-coherent Chrome UA for the given version.

    Headless bundled Chromium reports a "HeadlessChrome" UA token, which
    bot-defense vendors block on sight. We normalize that token to plain
    "Chrome" so the headless engine presents as the same-version headful
    Chrome it actually is. This is UA normalization, not fingerprint forgery.
    """
    major = browser_major_version or DEHEADLESS_UA_FALLBACK_MAJOR
    template = DEHEADLESS_UA_TEMPLATE_BY_HOST_OS.get(
        _host_os_key(), DEHEADLESS_UA_TEMPLATE_BY_HOST_OS[DEHEADLESS_HOST_OS_FALLBACK]
    )
    return template.format(major=int(major))


def _coherent_chrome_client_hint_headers(browser_major_version: int | None) -> dict[str, str]:
    """Build sec-ch-ua headers consistent with the de-headlessified UA + host OS."""
    major = int(browser_major_version or DEHEADLESS_UA_FALLBACK_MAJOR)
    platform_label = CHROME_CLIENT_HINT_PLATFORM_BY_HOST_OS.get(
        _host_os_key(),
        CHROME_CLIENT_HINT_PLATFORM_BY_HOST_OS[DEHEADLESS_HOST_OS_FALLBACK],
    )
    brands = (
        f'"{CHROME_CLIENT_HINT_GREASE_BRAND}";v="{CHROME_CLIENT_HINT_GREASE_VERSION}", '
        f'"Chromium";v="{major}", '
        f'"Google Chrome";v="{major}"'
    )
    return {
        "sec-ch-ua": brands,
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": f'"{platform_label}"',
    }


def build_playwright_context_spec(
    *,
    run_id: int | None = None,
    browser_major_version: int | None = None,
    locality_profile: Mapping[str, object] | None = None,
) -> PlaywrightContextSpec:
    _ = run_id  # reserved for future fingerprint keying
    context_options: dict[str, Any] = dict(NATIVE_REAL_CHROME_CONTEXT_OPTIONS)

    # De-headlessify the engine UA + emit coherent client hints. Headless Chromium
    # otherwise leaks a "HeadlessChrome" token with no sec-ch-ua hints, which
    # PerimeterX/Akamai/DataDome block instantly. A locality browser_context_profile
    # may still override user_agent below (explicit locality wins).
    context_options["user_agent"] = _deheadless_user_agent(browser_major_version)
    context_options["extra_http_headers"] = _coherent_chrome_client_hint_headers(
        browser_major_version
    )

    default_permissions = [
        str(value).strip()
        for value in crawler_runtime_settings.browser_context_permissions
        if str(value).strip()
    ]
    if default_permissions and "permissions" not in context_options:
        context_options["permissions"] = default_permissions

    if locality_profile is not None:
        locale = locality_profile.get("locale")
        if isinstance(locale, str) and locale.strip():
            context_options["locale"] = locale.strip()

        timezone_id = locality_profile.get("timezone_id")
        if isinstance(timezone_id, str) and timezone_id.strip():
            context_options["timezone_id"] = timezone_id.strip()

        geolocation = locality_profile.get("geolocation")
        if isinstance(geolocation, dict):
            lat = geolocation.get("latitude")
            lon = geolocation.get("longitude")
            if lat is not None and lon is not None:
                geo: dict[str, Any] = {
                    "latitude": float(lat),
                    "longitude": float(lon),
                }
                accuracy = geolocation.get("accuracy")
                if accuracy is not None:
                    geo["accuracy"] = float(accuracy)
                context_options["geolocation"] = geo
                context_options.setdefault("permissions", [])
                if "geolocation" not in context_options["permissions"]:
                    context_options["permissions"].append("geolocation")

        browser_context_profile = locality_profile.get("browser_context_profile")
        if isinstance(browser_context_profile, dict):
            for key, value in browser_context_profile.items():
                normalized_key = str(key)
                if value is None:
                    continue
                if normalized_key == "extra_http_headers" and isinstance(value, Mapping):
                    context_options["extra_http_headers"] = {
                        **dict(context_options.get("extra_http_headers") or {}),
                        **{str(header): str(header_value) for header, header_value in value.items()},
                    }
                    continue
                context_options[normalized_key] = value

    return PlaywrightContextSpec(
        context_options=context_options,
        init_script=None,
    )


def build_playwright_context_options(
    *,
    run_id: int | None = None,
    browser_major_version: int | None = None,
    locality_profile: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    return dict(
        build_playwright_context_spec(
            run_id=run_id,
            browser_major_version=browser_major_version,
            locality_profile=locality_profile,
        ).context_options
    )


def clear_browser_identity_cache() -> None:
    return None
