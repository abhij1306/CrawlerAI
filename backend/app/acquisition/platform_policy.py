from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from app.core.config import CONFIG_DIR
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.domain_utils import normalize_domain
from app.extraction.surfaces import Surface, parse_surface

logger = logging.getLogger(__name__)


class PlatformConfig(BaseModel):
    family: str
    domain_patterns: list[str] = Field(default_factory=list)
    url_contains: list[str] = Field(default_factory=list)
    html_contains: list[str] = Field(default_factory=list)
    html_regex: list[str] = Field(default_factory=list)
    adapter_names: list[str] = Field(default_factory=list)
    job_platform: bool = False
    requires_browser: bool = False
    proxy_policy: str | None = None
    readiness_domains: list[str] = Field(default_factory=list)
    readiness_path_patterns: list[str] = Field(default_factory=list)
    readiness_selectors: list[str] = Field(default_factory=list)
    readiness_max_wait_ms: int = 0
    network_signature_patterns: list[str] = Field(default_factory=list)
    path_tenant_boundary: bool = False
    locality_profile: dict[str, object] = Field(default_factory=dict)
    browser_context_profile: dict[str, object] = Field(default_factory=dict)
    js_state_extractors: list["JSStateExtractorConfig"] = Field(default_factory=list)


class JSStateExtractorConfig(BaseModel):
    surface: str
    state_keys: list[str] = Field(default_factory=list)
    root_paths: dict[str, list[list[str]]] = Field(default_factory=dict)
    field_paths: dict[str, list[list[str]]] = Field(default_factory=dict)
    configured_field_paths: dict[str, str | list[str]] = Field(default_factory=dict)


class PlatformRegistryDocument(BaseModel):
    platforms: list[PlatformConfig] = Field(default_factory=list)


def _platforms_path() -> Path:
    return CONFIG_DIR / "platforms.json"


@lru_cache(maxsize=1)
def _load_platform_registry() -> PlatformRegistryDocument:
    payload = json.loads(_platforms_path().read_text(encoding="utf-8"))
    return PlatformRegistryDocument.model_validate(payload)


def platform_configs() -> list[PlatformConfig]:
    return list(_load_platform_registry().platforms)


def _normalize_patterns(values: list[str]) -> list[str]:
    return [value.strip().lower() for value in values if value and value.strip()]


def _matches_domain(host: str, pattern: str) -> bool:
    normalized_host = normalize_domain(host)
    normalized_pattern = normalize_domain(pattern)
    if not normalized_host or not normalized_pattern:
        return False
    return normalized_host == normalized_pattern or normalized_host.endswith(
        f".{normalized_pattern}"
    )


def known_job_adapter_names() -> set[str]:
    names: set[str] = set()
    for config in platform_configs():
        if not config.job_platform:
            continue
        if config.family:
            normalized_family = str(config.family).strip().lower()
            if normalized_family:
                names.add(normalized_family)
        for name in config.adapter_names:
            normalized = str(name or "").strip().lower()
            if normalized:
                names.add(normalized)
    return names


def configured_adapter_names() -> tuple[str, ...]:
    ordered_names: list[str] = []
    for config in platform_configs():
        for adapter_name in config.adapter_names:
            normalized = str(adapter_name or "").strip().lower()
            if normalized and normalized not in ordered_names:
                ordered_names.append(normalized)
    return tuple(ordered_names)


def platform_config_for_family(
    family: str | None,
) -> PlatformConfig | None:
    normalized = str(family or "").strip().lower()
    if not normalized:
        return None
    for config in platform_configs():
        if str(config.family or "").strip().lower() == normalized:
            return config
    return None


def classify_network_endpoint_family(response_url: str) -> str:
    lowered_url = str(response_url or "").strip().lower()
    if not lowered_url:
        return "generic"
    for config in platform_configs():
        for pattern in _normalize_patterns(config.network_signature_patterns):
            if pattern and pattern in lowered_url:
                return config.family
    return "generic"


def is_job_platform_signal(
    platform_family: str | None = None,
    adapter_hint: str | None = None,
) -> bool:
    job_signals = known_job_adapter_names()
    normalized_family = str(platform_family or "").strip().lower()
    normalized_hint = str(adapter_hint or "").strip().lower()
    return normalized_family in job_signals or normalized_hint in job_signals


def detect_platform_family(url: str, html: str = "") -> str | None:
    normalized_url = str(url or "").strip().lower()
    normalized_html = str(html or "").lower()[: _platform_detection_html_search_limit()]
    domain = normalize_domain(urlparse(normalized_url).netloc)

    for config in platform_configs():
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if any(_matches_domain(domain, pattern) for pattern in domain_patterns):
            return config.family

    for config in platform_configs():
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if domain_patterns and not any(
            _matches_domain(domain, pattern) for pattern in domain_patterns
        ):
            continue
        html_patterns = _normalize_patterns(config.html_contains)
        if any(pattern in normalized_html for pattern in html_patterns):
            return config.family
        for pattern in config.html_regex:
            raw_pattern = str(pattern or "").strip()
            if not raw_pattern:
                continue
            try:
                if re.search(raw_pattern, normalized_html, re.IGNORECASE):
                    return config.family
            except re.error as exc:
                logger.warning(
                    "Skipping invalid platform html_regex for family=%s pattern=%r: %s",
                    config.family,
                    raw_pattern,
                    exc,
                )

    for config in platform_configs():
        url_patterns = _normalize_patterns(config.url_contains)
        if not url_patterns:
            continue
        domain_patterns = _normalize_patterns(config.domain_patterns)
        if domain_patterns and not any(
            _matches_domain(domain, pattern) for pattern in domain_patterns
        ):
            continue
        if any(pattern in normalized_url for pattern in url_patterns):
            return config.family

    return None


def resolve_listing_readiness_platform(url: str) -> str | None:
    normalized_url = str(url or "").strip().lower()
    if not normalized_url:
        return None
    parsed = urlparse(normalized_url)
    host = normalize_domain(parsed.netloc)
    path = str(parsed.path or "").strip().lower()
    if not host or not path:
        return None

    for config in platform_configs():
        readiness_domains = _normalize_patterns(config.readiness_domains)
        readiness_patterns = [
            str(pattern or "").strip().lower()
            for pattern in config.readiness_path_patterns
            if str(pattern or "").strip()
        ]
        if not readiness_domains or not readiness_patterns:
            continue
        if not any(_matches_domain(host, pattern) for pattern in readiness_domains):
            continue
        for pattern in readiness_patterns:
            try:
                if re.search(pattern, path, re.IGNORECASE):
                    return config.family
            except re.error as exc:
                logger.warning(
                    "Skipping invalid readiness path regex for family=%s pattern=%r: %s",
                    config.family,
                    pattern,
                    exc,
                )
    return None


def _platform_detection_html_search_limit() -> int:
    return max(1, int(crawler_runtime_settings.platform_detection_html_search_limit))


def platform_domain_patterns(family: str | None) -> tuple[str, ...]:
    config = platform_config_for_family(family)
    if config is None:
        return ()
    return tuple(_normalize_patterns(config.domain_patterns))


def url_host_matches_platform_family(url: str | None, family: str | None) -> bool:
    host = normalize_domain(urlparse(str(url or "")).netloc)
    if not host:
        return False
    return any(
        _matches_domain(host, pattern) for pattern in platform_domain_patterns(family)
    )


def requires_path_tenant_boundary_for_family(family: str | None) -> bool:
    config = platform_config_for_family(family)
    return bool(config.path_tenant_boundary) if config is not None else False


def requires_path_tenant_boundary(url: str | None) -> bool:
    family = detect_platform_family(str(url or ""))
    return requires_path_tenant_boundary_for_family(family)


def path_tenant_boundary_family(url: str | None) -> str | None:
    family = detect_platform_family(str(url or ""))
    if not requires_path_tenant_boundary_for_family(family):
        return None
    return family


def resolve_listing_readiness_override(url: str) -> dict[str, Any] | None:
    family = resolve_listing_readiness_platform(url)
    config = platform_config_for_family(family)
    if config is None:
        return None
    selectors = [
        str(selector or "").strip()
        for selector in list(config.readiness_selectors or [])
        if str(selector or "").strip()
    ]
    if not selectors:
        return None
    parsed = urlparse(str(url or "").strip().lower())
    return {
        "platform": family,
        "domain": str(parsed.netloc or "").strip(),
        "selectors": selectors,
        "max_wait_ms": int(config.readiness_max_wait_ms or 0),
    }


def resolve_browser_readiness_policy(
    url: str,
    *,
    surface: str | None = None,
    traversal_active: bool = False,
) -> dict[str, Any]:
    listing_override = resolve_listing_readiness_override(url)
    normalized_surface = str(surface or "").strip().lower()
    detail_surface = normalized_surface.endswith("_detail")
    if traversal_active:
        networkidle_reason = "traversal"
    elif listing_override is not None:
        networkidle_reason = "platform-readiness"
    elif detail_surface:
        networkidle_reason = "detail-surface"
    else:
        networkidle_reason = None
    require_networkidle = bool(
        listing_override is not None or traversal_active or detail_surface
    )
    return {
        "listing_override": listing_override,
        "require_networkidle": require_networkidle,
        "networkidle_reason": networkidle_reason,
        "navigation_wait_until": "domcontentloaded",
    }


def _resolve_http_browser_escalation_policy(surface: str | None) -> dict[str, bool]:
    try:
        selected = parse_surface(surface)
    except ValueError:
        selected = None
    return {
        "js_shell_without_detail_signals": True,
        "missing_detail_signals": selected
        in {Surface.ECOMMERCE_DETAIL, Surface.JOB_DETAIL},
        "listing_shell_without_listing_signals": selected
        in {Surface.ECOMMERCE_LISTING, Surface.JOB_LISTING},
    }


def resolve_platform_runtime_policy(
    url: str,
    html: str = "",
    *,
    surface: str | None = None,
) -> dict[str, Any]:
    family = detect_platform_family(url, html)
    config = platform_config_for_family(family)
    return {
        "family": family,
        "requires_browser": bool(config.requires_browser) if config else False,
        "proxy_policy": config.proxy_policy if config else None,
        "locality_profile": dict(config.locality_profile or {}) if config else {},
        "browser_context_profile": dict(config.browser_context_profile or {})
        if config
        else {},
        "http_browser_escalation": _resolve_http_browser_escalation_policy(surface),
    }
