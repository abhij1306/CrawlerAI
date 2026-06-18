from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_settings import normalize_crawl_settings
from app.services.config.domain_profiles import INTERNAL_API_ENDPOINTS_PROFILE_KEY
from app.services.domain_utils import normalize_domain

from .normalization import (
    _empty_acquisition_contract,
    normalize_acquisition_contract,
    normalize_internal_api_endpoints,
)
from .repository import load_domain_run_profile

_CACHED_DEFAULT_RUN_SETTINGS = normalize_crawl_settings({})


def _default_run_settings() -> dict[str, object]:
    return dict(_CACHED_DEFAULT_RUN_SETTINGS)


def _should_apply_explicit_override(
    explicit_value: object,
    *,
    default_value: object,
    ignore_default_equivalent_values: bool,
) -> bool:
    if not ignore_default_equivalent_values:
        return True
    return explicit_value != default_value


def _merge_profile_section(
    explicit_settings: dict[str, object],
    key: str,
    saved_section: dict[str, object],
    *,
    root_override_keys: set[str],
    root_override_aliases: dict[str, str],
    default_settings: dict[str, object],
    ignore_default_equivalent_values: bool,
) -> dict[str, object]:
    explicit_section_raw = explicit_settings.get(key)
    explicit_section = (
        dict(explicit_section_raw)
        if isinstance(explicit_section_raw, dict)
        else {}
    )
    default_section_raw = default_settings.get(key)
    default_section = (
        dict(default_section_raw)
        if isinstance(default_section_raw, dict)
        else {}
    )
    merged = dict(saved_section)
    if not saved_section and explicit_section:
        return explicit_section
    for field_name, explicit_value in explicit_section.items():
        if _should_apply_explicit_override(
            explicit_value,
            default_value=default_section.get(field_name),
            ignore_default_equivalent_values=ignore_default_equivalent_values,
        ):
            merged[field_name] = explicit_value
    for root_override_key in root_override_keys:
        if root_override_key not in explicit_settings:
            continue
        if not _should_apply_explicit_override(
            explicit_settings[root_override_key],
            default_value=default_settings.get(root_override_key),
            ignore_default_equivalent_values=ignore_default_equivalent_values,
        ):
            continue
        target_key = root_override_aliases.get(root_override_key, root_override_key)
        merged[target_key] = explicit_settings[root_override_key]
    return merged or explicit_section


def _merge_acquisition_contract(
    explicit_contract: object,
    saved_contract: object,
    *,
    ignore_default_equivalent_values: bool,
) -> dict[str, object]:
    normalized_saved = normalize_acquisition_contract(saved_contract)
    normalized_explicit = normalize_acquisition_contract(explicit_contract)
    default_contract = _empty_acquisition_contract()
    if not normalized_saved:
        return normalized_explicit
    merged = dict(normalized_saved)
    for key, explicit_value in normalized_explicit.items():
        default_value = default_contract.get(key)
        if _should_apply_explicit_override(
            explicit_value,
            default_value=default_value,
            ignore_default_equivalent_values=ignore_default_equivalent_values,
        ):
            merged[key] = explicit_value
    return normalize_acquisition_contract(merged)


def _section_with_saved_root_aliases(
    saved: dict[str, object],
    section_key: str,
    *,
    root_keys: set[str],
    root_aliases: dict[str, str],
) -> dict[str, object]:
    raw_section = saved.get(section_key)
    section = dict(raw_section) if isinstance(raw_section, dict) else {}
    for root_key in root_keys:
        if root_key not in saved:
            continue
        target_key = root_aliases.get(root_key, root_key)
        section.setdefault(target_key, saved[root_key])
    return section


def merge_saved_run_profile(
    explicit_settings: object,
    saved_profile: object,
    *,
    ignore_default_equivalent_values: bool,
) -> dict[str, object]:
    merged = (
        dict(explicit_settings or {})
        if isinstance(explicit_settings, dict)
        else {}
    )
    saved = dict(saved_profile or {}) if isinstance(saved_profile, dict) else {}
    if not saved:
        return merged
    default_settings = _default_run_settings()
    fetch_root_keys = {
        "fetch_mode",
        "extraction_source",
        "js_mode",
        "include_iframes",
        "traversal_mode",
        "advanced_mode",
        "request_delay_ms",
        "sleep_ms",
        "max_pages",
        "max_scrolls",
    }
    fetch_root_aliases = {
        "advanced_mode": "traversal_mode",
        "sleep_ms": "request_delay_ms",
    }
    merged["fetch_profile"] = _merge_profile_section(
        merged,
        "fetch_profile",
        _section_with_saved_root_aliases(
            saved,
            "fetch_profile",
            root_keys=fetch_root_keys,
            root_aliases=fetch_root_aliases,
        ),
        root_override_keys=fetch_root_keys,
        root_override_aliases=fetch_root_aliases,
        default_settings=default_settings,
        ignore_default_equivalent_values=ignore_default_equivalent_values,
    )
    merged["locality_profile"] = _merge_profile_section(
        merged,
        "locality_profile",
        dict(saved.get("locality_profile") or {}),
        root_override_keys={"geo_country", "language_hint", "currency_hint"},
        root_override_aliases={},
        default_settings=default_settings,
        ignore_default_equivalent_values=ignore_default_equivalent_values,
    )
    merged["diagnostics_profile"] = _merge_profile_section(
        merged,
        "diagnostics_profile",
        dict(saved.get("diagnostics_profile") or {}),
        root_override_keys={
            "capture_html",
            "capture_screenshot",
            "capture_network",
            "capture_response_headers",
            "capture_browser_diagnostics",
        },
        root_override_aliases={},
        default_settings=default_settings,
        ignore_default_equivalent_values=ignore_default_equivalent_values,
    )
    saved_contract = dict(saved.get("acquisition_contract") or {})
    explicit_contract = dict(merged.get("acquisition_contract") or {})
    if saved_contract or explicit_contract:
        merged["acquisition_contract"] = _merge_acquisition_contract(
            explicit_contract,
            saved_contract,
            ignore_default_equivalent_values=ignore_default_equivalent_values,
        )
    saved_endpoints = normalize_internal_api_endpoints(
        saved.get(INTERNAL_API_ENDPOINTS_PROFILE_KEY)
    )
    explicit_endpoints = normalize_internal_api_endpoints(
        merged.get(INTERNAL_API_ENDPOINTS_PROFILE_KEY)
    )
    if saved_endpoints or explicit_endpoints:
        endpoints_by_key = {
            (str(endpoint.get("method") or ""), str(endpoint.get("url") or "")): endpoint
            for endpoint in saved_endpoints
        }
        endpoints_by_key.update(
            {
                (str(endpoint.get("method") or ""), str(endpoint.get("url") or "")): endpoint
                for endpoint in explicit_endpoints
            }
        )
        merged[INTERNAL_API_ENDPOINTS_PROFILE_KEY] = list(endpoints_by_key.values())
    return merged


async def resolve_url_acquisition_recipe(
    session: AsyncSession,
    *,
    url: str,
    surface: str,
    explicit_settings: dict[str, object],
) -> dict[str, object]:
    normalized_domain = normalize_domain(url)
    saved_profile = await load_domain_run_profile(
        session,
        domain=normalized_domain,
        surface=surface,
    )
    if saved_profile is None:
        return dict(explicit_settings)
    return merge_saved_run_profile(
        dict(explicit_settings),
        saved_profile.profile,
        ignore_default_equivalent_values=True,
    )
