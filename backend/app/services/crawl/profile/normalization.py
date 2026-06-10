from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from app.services.config.domain_profiles import (
    INTERNAL_API_ENDPOINT_ALLOWED_METHODS,
    INTERNAL_API_ENDPOINT_FAMILY_KEY,
    INTERNAL_API_ENDPOINT_METHOD_KEY,
    INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY,
    INTERNAL_API_ENDPOINT_TYPE_KEY,
    INTERNAL_API_ENDPOINT_URL_KEY,
    INTERNAL_API_ENDPOINTS_PROFILE_KEY,
    TRAVERSAL_MODE_VALUES,
)
from app.services.config.runtime_settings import crawler_runtime_settings

_FETCH_MODE_VALUES = {
    "auto",
    "http_only",
    "browser_only",
    "http_then_browser",
}
_EXTRACTION_SOURCE_VALUES = {
    "raw_html",
    "rendered_dom",
    "rendered_dom_visual",
    "network_payload_first",
}
_JS_MODE_VALUES = {"auto", "enabled", "disabled"}
_CAPTURE_NETWORK_VALUES = {"off", "matched_only", "all_small_json"}
_BROWSER_ENGINE_VALUES = {"auto", "patchright", "real_chrome"}
_LEGACY_HANDOFF_ELIGIBLE_KEY = "prefer_curl_handoff"


def _coerce_int_clamped(
    value: object, default: int, minimum: int, maximum: int | None = None
) -> int:
    try:
        result = max(minimum, int(float(str(value))))
        if maximum is not None:
            result = min(result, maximum)
        return result
    except (TypeError, ValueError):
        return default


def _empty_acquisition_contract() -> dict[str, object]:
    return {
        "preferred_browser_engine": "auto",
        "prefer_browser": False,
        "handoff_eligible": False,
        "handoff_cookie_engine": "auto",
        "required_rendering": False,
        "required_traversal": False,
        "required_network_payloads": False,
        "last_quality_success": None,
        "stale_after_failures": {
            "failure_count": 0,
            "stale": False,
        },
    }


def _clean_str(value: object) -> str | None:
    text = str(value or "").strip()
    return text or None


def _coerce_choice(value: object, allowed: set[str], *, default: str) -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else default


def _coerce_optional_choice(value: object, allowed: set[str]) -> str | None:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in allowed else None


def _normalize_traversal_mode(value: object) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in {"", "none", "auto"}:
        return None
    if normalized == "pagination":
        return "paginate"
    if normalized == "infinite_scroll":
        return "scroll"
    return normalized if normalized in TRAVERSAL_MODE_VALUES else None


def _coerce_nullable_text(value: object) -> str | None:
    text = _clean_str(value)
    return text or None


def _coerce_optional_int(
    value: object,
    *,
    minimum: int = 0,
    maximum: int | None = None,
    reject_non_positive: bool = False,
) -> int | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        result = int(text)
    except (TypeError, ValueError):
        return None
    if reject_non_positive and result <= 0:
        return None
    result = max(result, minimum)
    if maximum is not None:
        result = min(result, maximum)
    return result


def _coerce_proxy_list(value: object) -> list[str]:
    if value is None:
        return []
    raw_values = value if isinstance(value, list) else [value]
    seen: set[str] = set()
    proxies: list[str] = []
    for item in raw_values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        proxies.append(text)
    return proxies


def normalize_internal_api_endpoints(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list):
        return []
    endpoints: list[dict[str, object]] = []
    seen: set[tuple[str, str]] = set()
    max_endpoints = max(
        1,
        int(crawler_runtime_settings.internal_api_replay_max_endpoints),
    )
    for item in value:
        if not isinstance(item, Mapping):
            continue
        url = _clean_str(item.get(INTERNAL_API_ENDPOINT_URL_KEY))
        method = str(item.get(INTERNAL_API_ENDPOINT_METHOD_KEY) or "GET").strip().upper()
        if not url or method not in INTERNAL_API_ENDPOINT_ALLOWED_METHODS:
            continue
        key = (method, url)
        if key in seen:
            continue
        seen.add(key)
        endpoint: dict[str, object] = {
            INTERNAL_API_ENDPOINT_URL_KEY: url,
            INTERNAL_API_ENDPOINT_METHOD_KEY: method,
        }
        endpoint_type = _clean_str(item.get(INTERNAL_API_ENDPOINT_TYPE_KEY))
        if endpoint_type:
            endpoint[INTERNAL_API_ENDPOINT_TYPE_KEY] = endpoint_type
        endpoint_family = _clean_str(item.get(INTERNAL_API_ENDPOINT_FAMILY_KEY))
        if endpoint_family:
            endpoint[INTERNAL_API_ENDPOINT_FAMILY_KEY] = endpoint_family
        source_run_id = _coerce_int_clamped(
            item.get(INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY),
            default=0,
            minimum=0,
        )
        if source_run_id > 0:
            endpoint[INTERNAL_API_ENDPOINT_SOURCE_RUN_ID_KEY] = source_run_id
        endpoints.append(endpoint)
        if len(endpoints) >= max_endpoints:
            break
    return endpoints


def _coerce_country(value: object) -> str:
    text = str(value or "").strip()
    return text or "auto"


def normalize_acquisition_contract(value: object) -> dict[str, object]:
    payload = dict(value or {}) if isinstance(value, Mapping) else {}
    handoff_eligible = bool(
        payload.get("handoff_eligible", payload.get(_LEGACY_HANDOFF_ELIGIBLE_KEY, False))
    )
    last_quality_success = payload.get("last_quality_success")
    if isinstance(last_quality_success, Mapping):
        normalized_success: dict[str, object] | None = {
            "method": _clean_str(last_quality_success.get("method")),
            "browser_engine": _coerce_optional_choice(
                last_quality_success.get("browser_engine"),
                _BROWSER_ENGINE_VALUES,
            ),
            "record_count": _coerce_int_clamped(
                last_quality_success.get("record_count"),
                default=0,
                minimum=0,
            ),
            "field_coverage": dict(last_quality_success.get("field_coverage") or {})
            if isinstance(last_quality_success.get("field_coverage"), Mapping)
            else {},
            "source_run_id": _coerce_int_clamped(
                last_quality_success.get("source_run_id"),
                default=0,
                minimum=0,
            )
            or None,
            "timestamp": _clean_str(last_quality_success.get("timestamp")),
        }
    else:
        normalized_success = None
    stale_payload = (
        dict(payload.get("stale_after_failures") or {})
        if isinstance(payload.get("stale_after_failures"), Mapping)
        else {}
    )
    return {
        "preferred_browser_engine": _coerce_choice(
            payload.get("preferred_browser_engine"),
            _BROWSER_ENGINE_VALUES,
            default="auto",
        ),
        "prefer_browser": bool(payload.get("prefer_browser", False)),
        "handoff_eligible": handoff_eligible,
        "handoff_cookie_engine": _coerce_choice(
            payload.get("handoff_cookie_engine"),
            _BROWSER_ENGINE_VALUES,
            default="auto",
        ),
        "required_rendering": bool(payload.get("required_rendering", False)),
        "required_traversal": bool(payload.get("required_traversal", False)),
        "required_network_payloads": bool(payload.get("required_network_payloads", False)),
        "last_quality_success": normalized_success,
        "stale_after_failures": {
            "failure_count": _coerce_int_clamped(
                stale_payload.get("failure_count"),
                default=0,
                minimum=0,
            ),
            "stale": bool(stale_payload.get("stale", False)),
        },
    }


def normalize_domain_run_profile(
    profile: object,
    *,
    source_run_id: int,
    saved_at: str | None = None,
) -> dict[str, object]:
    payload = dict(profile or {}) if isinstance(profile, Mapping) else {}
    fetch_profile = dict(payload.get("fetch_profile") or {})
    locality_profile = dict(payload.get("locality_profile") or {})
    diagnostics_profile = dict(payload.get("diagnostics_profile") or {})
    normalized_saved_at = saved_at or datetime.now(UTC).isoformat()
    normalized_source_run_id = _coerce_int_clamped(
        source_run_id,
        default=0,
        minimum=0,
    )
    if normalized_source_run_id <= 0:
        raise ValueError("source_run_id must be a positive integer")
    return {
        "version": 1,
        "fetch_profile": {
            "fetch_mode": _coerce_choice(
                fetch_profile.get("fetch_mode"),
                _FETCH_MODE_VALUES,
                default="auto",
            ),
            "extraction_source": _coerce_choice(
                fetch_profile.get("extraction_source"),
                _EXTRACTION_SOURCE_VALUES,
                default="raw_html",
            ),
            "js_mode": _coerce_choice(
                fetch_profile.get("js_mode"),
                _JS_MODE_VALUES,
                default="auto",
            ),
            "include_iframes": bool(fetch_profile.get("include_iframes", False)),
            "traversal_mode": _normalize_traversal_mode(
                fetch_profile.get("traversal_mode"),
            ),
            "request_delay_ms": _coerce_int_clamped(
                fetch_profile.get("request_delay_ms"),
                default=crawler_runtime_settings.min_request_delay_ms,
                minimum=crawler_runtime_settings.min_request_delay_ms,
            ),
            "max_pages": _coerce_int_clamped(
                fetch_profile.get("max_pages"),
                default=crawler_runtime_settings.default_max_pages,
                minimum=crawler_runtime_settings.min_max_pages,
                maximum=crawler_runtime_settings.max_max_pages,
            ),
            "max_scrolls": _coerce_int_clamped(
                fetch_profile.get("max_scrolls"),
                default=crawler_runtime_settings.default_max_scrolls,
                minimum=1,
            ),
            "host_memory_ttl_seconds": _coerce_optional_int(
                fetch_profile.get("host_memory_ttl_seconds"),
                minimum=crawler_runtime_settings.host_memory_ttl_min_seconds,
                maximum=crawler_runtime_settings.host_memory_ttl_max_seconds,
            ),
        },
        "locality_profile": {
            "geo_country": _coerce_country(locality_profile.get("geo_country")),
            "language_hint": _coerce_nullable_text(locality_profile.get("language_hint")),
            "currency_hint": _coerce_nullable_text(locality_profile.get("currency_hint")),
        },
        "diagnostics_profile": {
            "capture_html": bool(diagnostics_profile.get("capture_html", True)),
            "capture_screenshot": bool(
                diagnostics_profile.get("capture_screenshot", False)
            ),
            "capture_network": _coerce_choice(
                diagnostics_profile.get("capture_network"),
                _CAPTURE_NETWORK_VALUES,
                default="off",
            ),
            "capture_response_headers": bool(
                diagnostics_profile.get("capture_response_headers", True)
            ),
            "capture_browser_diagnostics": bool(
                diagnostics_profile.get("capture_browser_diagnostics", True)
            ),
        },
        "acquisition_contract": normalize_acquisition_contract(
            payload.get("acquisition_contract")
        ),
        INTERNAL_API_ENDPOINTS_PROFILE_KEY: normalize_internal_api_endpoints(
            payload.get(INTERNAL_API_ENDPOINTS_PROFILE_KEY)
        ),
        "source_run_id": normalized_source_run_id,
        "saved_at": normalized_saved_at,
    }
