from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.crawl_settings import normalize_crawl_settings
from app.services.domain_utils import normalize_domain

from .normalization import (
    _empty_acquisition_contract,
    normalize_acquisition_contract,
)
from .repository import load_domain_run_profile


def _default_run_settings() -> dict[str, object]:
    return normalize_crawl_settings({})


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
    legacy_keys: set[str],
    legacy_aliases: dict[str, str],
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
    for legacy_key in legacy_keys:
        if legacy_key not in explicit_settings:
            continue
        if not _should_apply_explicit_override(
            explicit_settings[legacy_key],
            default_value=default_settings.get(legacy_key),
            ignore_default_equivalent_values=ignore_default_equivalent_values,
        ):
            continue
        target_key = legacy_aliases.get(legacy_key, legacy_key)
        merged[target_key] = explicit_settings[legacy_key]
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
    merged["fetch_profile"] = _merge_profile_section(
        merged,
        "fetch_profile",
        dict(saved.get("fetch_profile") or {}),
        legacy_keys={
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
        },
        legacy_aliases={
            "advanced_mode": "traversal_mode",
            "sleep_ms": "request_delay_ms",
            "request_delay_ms": "request_delay_ms",
            "max_pages": "max_pages",
            "max_scrolls": "max_scrolls",
        },
        default_settings=default_settings,
        ignore_default_equivalent_values=ignore_default_equivalent_values,
    )
    merged["locality_profile"] = _merge_profile_section(
        merged,
        "locality_profile",
        dict(saved.get("locality_profile") or {}),
        legacy_keys={"geo_country", "language_hint", "currency_hint"},
        legacy_aliases={},
        default_settings=default_settings,
        ignore_default_equivalent_values=ignore_default_equivalent_values,
    )
    merged["diagnostics_profile"] = _merge_profile_section(
        merged,
        "diagnostics_profile",
        dict(saved.get("diagnostics_profile") or {}),
        legacy_keys={
            "capture_html",
            "capture_screenshot",
            "capture_network",
            "capture_response_headers",
            "capture_browser_diagnostics",
        },
        legacy_aliases={},
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
