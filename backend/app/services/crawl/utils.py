# Shared utility functions for crawl operations.
# Extracted to break circular dependencies between crawl_crud, pipeline, and _batch_runtime.
from __future__ import annotations

import csv
import io
import logging
import re
import asyncio
from html import unescape
from typing import Any, Protocol, cast
from urllib.parse import urlparse

import regex as regex_lib
from app.services.config.crawl_inputs import (
    ENCODED_TRAILING_PASTED_URL_DELIMITERS,
    HTTP_URL_PREFIXES,
    TRAILING_PASTED_URL_DELIMITERS,
    WRAPPED_URL_DELIMITER_PAIRS,
)
from app.services.exceptions import CrawlerConfigurationError
from app.services.dom.xpath_service import validate_xpath_syntax

logger = logging.getLogger(__name__)


class _SettingsViewLike(Protocol):
    def urls(self) -> list[str]:
        raise NotImplementedError

    def get(self, key: str, default: Any = None) -> Any:
        raise NotImplementedError

    def has(self, key: str) -> bool:
        raise NotImplementedError

    def advanced_enabled(self) -> bool:
        raise NotImplementedError


# CSV parsing


def parse_csv_urls(csv_content: str) -> list[str]:
    """Parse URLs from CSV content (first column, skip header if present)."""
    urls: list[str] = []
    reader = csv.reader(io.StringIO(csv_content))
    for i, row in enumerate(reader):
        if not row:
            continue
        cell = row[0].strip()
        if i == 0 and not _has_http_url_prefix(cell):
            continue  # skip header
        if _has_http_url_prefix(cell):
            urls.append(cell)
    return urls


async def parse_csv_urls_async(csv_content: str) -> list[str]:
    return await asyncio.to_thread(parse_csv_urls, csv_content)


# URL normalization and collection


def normalize_target_url(value: object) -> str:
    """Normalize a target URL while rejecting pasted multi-value inputs."""
    text = _strip_pasted_url_delimiters(unescape(str(value or "")).strip())
    if not text:
        return ""
    if re.search(r"\s", text):
        logger.warning("Rejected target URL containing internal whitespace")
        return ""
    from app.services.shared.field_coerce import strip_tracking_query_params

    normalized = strip_tracking_query_params(text)
    if normalized:
        return normalized
    return text


def _strip_pasted_url_delimiters(text: str) -> str:
    candidate = str(text or "").strip()
    for opener, closer in WRAPPED_URL_DELIMITER_PAIRS:
        if candidate.startswith(opener) and candidate.endswith(closer):
            candidate = candidate[len(opener) : -len(closer)].strip()
            break
    trimmed = _rstrip_pasted_url_delimiters(candidate)
    if trimmed != candidate and _looks_like_absolute_http_url(trimmed):
        return trimmed
    return candidate


def _rstrip_pasted_url_delimiters(text: str) -> str:
    candidate = str(text or "")
    while candidate:
        previous = candidate
        candidate = candidate.rstrip(TRAILING_PASTED_URL_DELIMITERS)
        lowered = candidate.lower()
        for suffix in ENCODED_TRAILING_PASTED_URL_DELIMITERS:
            if lowered.endswith(suffix):
                candidate = candidate[: -len(suffix)]
                break
        if candidate == previous:
            return candidate
    return candidate


def _looks_like_absolute_http_url(text: str) -> bool:
    if not _has_http_url_prefix(text):
        return False
    parsed = urlparse(text)
    return bool(parsed.scheme and parsed.netloc)


def _has_http_url_prefix(text: str) -> bool:
    return str(text or "").lower().startswith(HTTP_URL_PREFIXES)


def text_has_token(text: str, token: str) -> bool:
    cleaned_text = str(text or "").strip().lower()
    cleaned_token = str(token or "").strip().lower()
    if not cleaned_text or not cleaned_token:
        return False
    if " " in cleaned_token:
        return cleaned_token in cleaned_text
    words = {
        word
        for word in cleaned_text.replace("-", " ").replace("_", " ").split()
        if word
    }
    return cleaned_token in words


def _settings_view(settings: object) -> _SettingsViewLike | dict:
    if (
        hasattr(settings, "urls")
        and hasattr(settings, "get")
        and hasattr(settings, "has")
        and hasattr(settings, "advanced_enabled")
    ):
        return cast(_SettingsViewLike, settings)
    return settings if isinstance(settings, dict) else {}


def collect_target_urls(
    payload: dict,
    settings: object,
) -> list[str]:
    """Collect and deduplicate all target URLs from payload and settings."""
    settings_view = _settings_view(settings)
    candidates: list[str] = []

    # Direct URL from payload
    direct_url = normalize_target_url(payload.get("url"))
    if direct_url:
        candidates.append(direct_url)

    # URLs array from payload
    for value in payload.get("urls") or []:
        candidate = normalize_target_url(value)
        if candidate:
            candidates.append(candidate)

    # URLs array from settings
    setting_urls = (
        settings_view.urls()
        if hasattr(settings_view, "urls")
        else (settings_view.get("urls") or [])
    )
    for value in setting_urls:
        candidate = normalize_target_url(value)
        if candidate:
            candidates.append(candidate)

    # CSV content from settings
    csv_content = str(settings_view.get("csv_content") or "")
    if csv_content:
        for value in parse_csv_urls(csv_content):
            candidate = normalize_target_url(value)
            if candidate and candidate not in candidates:
                candidates.append(candidate)

    # Deduplicate while preserving order
    return list(dict.fromkeys(candidates))


# Traversal mode resolution

_TRAVERSAL_MODES = {"paginate", "scroll", "load_more", "single", "sitemap", "crawl"}


def _normalize_traversal_mode_value(value: object) -> str | None:
    mode = str(value or "").strip().lower()
    if mode in {"", "none"}:
        return None
    if mode == "pagination":
        return "paginate"
    if mode == "infinite_scroll":
        return "scroll"
    if mode == "view_all":
        return "load_more"
    return mode


def resolve_traversal_mode(settings: object) -> str | None:
    """Resolve and validate the traversal mode from settings."""
    settings_view = _settings_view(settings)
    advanced_enabled_value = settings_view.get("advanced_enabled")
    advanced_enabled = (
        settings_view.advanced_enabled()
        if hasattr(settings_view, "advanced_enabled")
        else bool(advanced_enabled_value)
    )
    advanced_flag_present = (
        settings_view.has("advanced_enabled")
        if hasattr(settings_view, "has")
        else advanced_enabled_value is not None
    )
    fetch_profile = settings_view.get("fetch_profile")
    if isinstance(fetch_profile, dict) and fetch_profile:
        fetch_profile_mode = _normalize_traversal_mode_value(
            fetch_profile.get("traversal_mode")
        )
        if fetch_profile_mode is None:
            return None
        if fetch_profile_mode in _TRAVERSAL_MODES:
            return fetch_profile_mode
        logger.error("Unrecognized traversal_mode")
        raise CrawlerConfigurationError("Unsupported traversal_mode")
    if advanced_flag_present and not advanced_enabled:
        return None
    mode = _normalize_traversal_mode_value(
        settings_view.get("traversal_mode") or settings_view.get("advanced_mode")
    )
    if mode is None:
        return None
    if mode in _TRAVERSAL_MODES:
        return mode
    logger.error("Unrecognized traversal_mode")
    raise CrawlerConfigurationError("Unsupported traversal_mode")


# Extraction contract validation


def validate_extraction_contract(contract_rows: list[dict]) -> None:
    """Validate extraction contract rows for field names, XPath, and regex syntax.

    Raises ValueError if any validation errors are found.
    """
    errors: list[str] = []
    for index, row in enumerate(contract_rows, start=1):
        field_name = str(row.get("field_name") or "").strip()
        xpath = str(row.get("xpath") or "").strip()
        regex = str(row.get("regex") or "").strip()

        if not field_name:
            errors.append(f"Row {index}: field_name is required")

        if xpath:
            valid_xpath, xpath_error = validate_xpath_syntax(xpath)
            if not valid_xpath:
                errors.append(
                    f"Row {index} ({field_name or 'unnamed'}): invalid XPath ({xpath_error})"
                )

        if regex:
            try:
                regex_lib.compile(regex)
            except regex_lib.error as exc:
                errors.append(
                    f"Row {index} ({field_name or 'unnamed'}): invalid regex ({exc})"
                )

    if errors:
        raise ValueError("; ".join(errors))
