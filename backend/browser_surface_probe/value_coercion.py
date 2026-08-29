from __future__ import annotations

import re
from collections.abc import Sequence

from app.core.config.browser_surface_probe import (
    BROWSER_SURFACE_PROBE_COUNTRY_NAMES,
    BROWSER_SURFACE_PROBE_COUNTRY_TIMEZONES,
    BROWSER_SURFACE_PROBE_RISK_TOKENS,
    BROWSER_SURFACE_PROBE_SAFE_TOKENS,
    BROWSER_SURFACE_PROBE_TIMEZONE_ALIASES,
)

BROWSER_VERSION_RE = re.compile(
    r"\b(?:Chrome|Chromium|Edg|Firefox|HeadlessChrome)/(\d+)",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")
_COUNTRY_CODE_BY_NAME = {
    _NON_ALNUM_RE.sub(" ", name.lower()).strip(): code
    for code, name in BROWSER_SURFACE_PROBE_COUNTRY_NAMES.items()
}
_COUNTRY_CODE_BY_NAME.update(
    {
        "uk": "GB",
        "united kingdom": "GB",
        "usa": "US",
        "u s a": "US",
        "united states": "US",
        "united states of america": "US",
    }
)


def object_dict(value: object) -> dict[str, object]:
    return dict(value) if isinstance(value, dict) else {}


def object_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def string_list(value: object) -> list[str]:
    return [str(item) for item in object_list(value)]


def normalize_space(value: object) -> str:
    return _WHITESPACE_RE.sub(" ", str(value or "")).strip()


def normalize_key(value: object) -> str:
    return _NON_ALNUM_RE.sub(" ", normalize_space(value).lower()).strip()


def int_list(value: object) -> list[int]:
    return [int(item) for item in object_list(value) if isinstance(item, int)]


def extract_versions(values: list[str]) -> list[int]:
    versions: list[int] = []
    for value in values:
        for match in BROWSER_VERSION_RE.findall(str(value or "")):
            try:
                versions.append(int(match))
            except ValueError:
                continue
    return sorted(set(versions))


def looks_like_truthy_risk(value: str) -> bool:
    lowered = normalize_space(value).lower()
    if not lowered:
        return False
    if any(token in lowered for token in BROWSER_SURFACE_PROBE_SAFE_TOKENS):
        return False
    if any(token in lowered for token in BROWSER_SURFACE_PROBE_RISK_TOKENS):
        return True
    for match in re.findall(r"(\d+(?:\.\d+)?)%", lowered):
        try:
            if float(match) > 0:
                return True
        except ValueError:
            continue
    return False


def percent_value(value: object) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)%", str(value or ""))
    if match is None:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def dedupe(values: list[str]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = normalize_space(value)
        key = normalized.casefold()
        if normalized and key not in seen:
            seen.add(key)
            found.append(normalized)
    return found


def country_code_from_value(value: str | None) -> str | None:
    normalized = normalize_key(value)
    if not normalized:
        return None
    if normalized in _COUNTRY_CODE_BY_NAME:
        return _COUNTRY_CODE_BY_NAME[normalized]
    if len(normalized) == 2 and normalized.isalpha():
        return normalized.upper()
    for country_name, country_code in _COUNTRY_CODE_BY_NAME.items():
        if country_name and re.search(
            rf"(?<![a-z0-9]){re.escape(country_name)}(?![a-z0-9])", normalized
        ):
            return country_code
    return None


def timezone_matches_country(
    timezone_name: str | None, country_code: str | None
) -> bool | None:
    normalized_timezone = normalize_space(timezone_name)
    normalized_timezone = str(
        BROWSER_SURFACE_PROBE_TIMEZONE_ALIASES.get(
            normalized_timezone, normalized_timezone
        )
    )
    normalized_country = normalize_space(country_code).upper()
    if not normalized_timezone or not normalized_country:
        return None
    expected = BROWSER_SURFACE_PROBE_COUNTRY_TIMEZONES.get(normalized_country, ())
    if not expected:
        return None
    return normalized_timezone in expected


def locale_region(locale_value: str | None) -> str | None:
    normalized = normalize_space(locale_value).replace("_", "-")
    if "-" not in normalized:
        return None
    region = normalized.rsplit("-", 1)[-1].upper()
    return region if len(region) == 2 and region.isalpha() else None


def coalesce(values: Sequence[object]) -> object | None:
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return None


__all__ = [
    "BROWSER_VERSION_RE",
    "coalesce",
    "country_code_from_value",
    "dedupe",
    "extract_versions",
    "int_list",
    "locale_region",
    "looks_like_truthy_risk",
    "normalize_key",
    "normalize_space",
    "object_dict",
    "object_list",
    "percent_value",
    "string_list",
    "timezone_matches_country",
]
