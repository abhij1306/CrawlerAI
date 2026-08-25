from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.acquisition.internal_api_replay import learned_internal_api_endpoints
from app.core.config.domain_profiles import INTERNAL_API_ENDPOINTS_PROFILE_KEY
from app.core.config.runtime_settings import crawler_runtime_settings
from app.core.db_utils import mapping_or_empty
from app.core.records.field_policy import acquisition_contract_fields_for_surface
from app.core.shared.field_coerce import safe_int
from app.persistence.publish import (
    VERDICT_BLOCKED,
    VERDICT_EMPTY,
    VERDICT_LISTING_FAILED,
)

from .normalization import (
    _BROWSER_ENGINE_VALUES,
    _coerce_optional_choice,
    normalize_acquisition_contract,
    normalize_domain_run_profile,
    normalize_internal_api_endpoints,
)
from .repository import load_domain_run_profile, save_domain_run_profile


def acquisition_contract_is_stale(profile: object) -> bool:
    payload = dict(profile or {}) if isinstance(profile, Mapping) else {}
    contract = normalize_acquisition_contract(payload.get("acquisition_contract"))
    stale_value = contract.get("stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    return bool(stale.get("stale"))


def apply_acquisition_contract_to_profile(
    acquisition_profile: object,
    contract: object,
) -> dict[str, object]:
    profile = (
        dict(acquisition_profile or {})
        if isinstance(acquisition_profile, Mapping)
        else {}
    )
    normalized = normalize_acquisition_contract(contract)
    fetch_mode = str(profile.get("fetch_mode") or "").strip().lower()
    browser_only = fetch_mode == "browser_only"
    stale_value = normalized.get("stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    if bool(stale.get("stale")):
        profile["acquisition_contract_stale"] = True
        return profile
    engine = str(normalized.get("preferred_browser_engine") or "auto").strip().lower()
    cookie_engine = (
        str(normalized.get("handoff_cookie_engine") or "auto").strip().lower()
    )
    _apply_browser_contract_preferences(
        profile,
        normalized=normalized,
        engine=engine,
        browser_only=browser_only,
    )
    _apply_handoff_contract_preferences(
        profile,
        normalized=normalized,
        engine=engine,
        cookie_engine=cookie_engine,
        browser_only=browser_only,
    )
    return profile


def _apply_browser_contract_preferences(
    profile: dict[str, object],
    *,
    normalized: dict[str, object],
    engine: str,
    browser_only: bool,
) -> None:
    if bool(normalized.get("prefer_browser")) or browser_only:
        profile["prefer_browser"] = True
        profile.setdefault("browser_reason", "acquisition-contract")
    if engine in {"patchright", "real_chrome"} and not profile.get(
        "forced_browser_engine"
    ):
        profile["forced_browser_engine"] = engine


def _apply_handoff_contract_preferences(
    profile: dict[str, object],
    *,
    normalized: dict[str, object],
    engine: str,
    cookie_engine: str,
    browser_only: bool,
) -> None:
    if bool(normalized.get("handoff_eligible")) and not browser_only:
        profile["prefer_curl_handoff"] = True
        profile["handoff_eligible"] = True
    if browser_only:
        profile.pop("prefer_curl_handoff", None)
        profile.pop("handoff_eligible", None)
        profile.pop("handoff_cookie_engine", None)
    elif cookie_engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = cookie_engine
    elif engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = engine


def build_success_acquisition_contract(
    *,
    method: object,
    browser_engine: object,
    browser_diagnostics: dict[str, object] | None = None,
    record_count: int,
    requested_fields: list[str],
    found_fields: list[str],
    source_run_id: int,
    timestamp: str | None = None,
) -> dict[str, object]:
    diagnostics = dict(browser_diagnostics or {})
    normalized_method = str(method or "").strip().lower()
    normalized_engine = _coerce_optional_choice(browser_engine, _BROWSER_ENGINE_VALUES)
    preferred_engine = (
        normalized_engine
        if normalized_engine in {"patchright", "real_chrome"}
        else "auto"
    )
    requirements = _contract_requirements(diagnostics)
    handoff_eligible = _handoff_is_eligible(
        method=normalized_method,
        preferred_engine=preferred_engine,
        requirements=requirements,
    )
    handoff_engine = preferred_engine if handoff_eligible else "auto"
    return normalize_acquisition_contract(
        {
            "preferred_browser_engine": preferred_engine,
            "prefer_browser": normalized_method == "browser",
            "handoff_eligible": handoff_eligible,
            "handoff_cookie_engine": handoff_engine,
            **requirements,
            "last_quality_success": _last_quality_success(
                method=normalized_method,
                browser_engine=normalized_engine,
                record_count=record_count,
                requested_fields=requested_fields,
                found_fields=found_fields,
                source_run_id=source_run_id,
                timestamp=timestamp,
            ),
            "stale_after_failures": {"failure_count": 0, "stale": False},
        }
    )


def _contract_requirements(diagnostics: dict[str, object]) -> dict[str, bool]:
    extraction_source = str(diagnostics.get("extraction_source") or "").strip().lower()
    return {
        "required_rendering": extraction_source
        in {"rendered_dom", "rendered_dom_visual"},
        "required_traversal": bool(diagnostics.get("traversal_activated")),
        "required_network_payloads": _positive_network_payload_count(diagnostics),
    }


def _handoff_is_eligible(
    *, method: str, preferred_engine: str, requirements: dict[str, bool]
) -> bool:
    return (
        method == "browser"
        and preferred_engine != "auto"
        and not any(requirements.values())
    )


def _last_quality_success(
    *,
    method: str,
    browser_engine: str | None,
    record_count: int,
    requested_fields: list[str],
    found_fields: list[str],
    source_run_id: int,
    timestamp: str | None,
) -> dict[str, object]:
    requested = list(requested_fields or [])
    requested_set = set(requested)
    covered_fields = [field for field in found_fields if field in requested_set]
    covered_set = set(covered_fields)
    return {
        "method": method or None,
        "browser_engine": browser_engine,
        "record_count": int(record_count or 0),
        "field_coverage": {
            "requested": requested,
            "found": covered_fields,
            "missing": [field for field in requested if field not in covered_set],
        },
        "source_run_id": int(source_run_id or 0),
        "timestamp": timestamp or datetime.now(UTC).isoformat(),
    }


def _positive_network_payload_count(diagnostics: dict[str, object]) -> bool:
    raw_count = diagnostics.get("network_payload_count")
    if not isinstance(raw_count, (int, float, str)):
        return False
    try:
        return float(raw_count) > 0
    except (TypeError, ValueError):
        return False


def _contract_without_volatile_stamps(contract: object) -> dict[str, object]:
    """Contract comparison view minus per-call stamps.

    ``last_quality_success.timestamp`` is refreshed on every recorded success;
    it is display metadata, not a contract change, so it must not defeat the
    no-change debounce on the per-URL hot path.
    """

    normalized = normalize_acquisition_contract(contract)
    success = normalized.get("last_quality_success")
    if isinstance(success, Mapping):
        normalized["last_quality_success"] = {
            key: value for key, value in success.items() if key != "timestamp"
        }
    return normalized


def _profile_write_is_unchanged(
    base_profile: dict[str, object],
    *,
    acquisition_contract: dict[str, object],
    internal_api_endpoints: list[dict[str, object]] | None,
) -> bool:
    existing_contract = _contract_without_volatile_stamps(
        base_profile.get("acquisition_contract")
    )
    if existing_contract != _contract_without_volatile_stamps(acquisition_contract):
        return False
    if internal_api_endpoints is None:
        return True
    existing_endpoints = normalize_internal_api_endpoints(
        base_profile.get(INTERNAL_API_ENDPOINTS_PROFILE_KEY)
    )
    return existing_endpoints == internal_api_endpoints


async def save_learned_acquisition_contract(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    contract: dict[str, object],
    internal_api_endpoints: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    existing = await load_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
    )
    base_profile = dict(existing.profile or {}) if existing is not None else {}
    if not base_profile:
        base_profile = normalize_domain_run_profile(
            {},
            source_run_id=source_run_id,
        )
    normalized_contract = normalize_acquisition_contract(contract)
    normalized_endpoints = (
        normalize_internal_api_endpoints(internal_api_endpoints)
        if internal_api_endpoints
        else None
    )
    # Per-URL DB budget: consecutive URLs of one run usually relearn the same
    # contract. Skip the upsert when nothing meaningful changed instead of
    # rewriting the same DomainRunProfile row once or twice per URL.
    if existing is not None and _profile_write_is_unchanged(
        base_profile,
        acquisition_contract=normalized_contract,
        internal_api_endpoints=normalized_endpoints,
    ):
        return dict(existing.profile or {})
    base_profile["acquisition_contract"] = normalized_contract
    if normalized_endpoints is not None:
        base_profile[INTERNAL_API_ENDPOINTS_PROFILE_KEY] = normalized_endpoints
    return await save_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
        profile=base_profile,
        source_run_id=source_run_id,
        existing_record=existing,
    )


async def note_acquisition_contract_failure(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    threshold: int,
) -> dict[str, object] | None:
    existing = await load_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
    )
    if existing is None:
        return None
    profile = dict(existing.profile or {})
    contract = normalize_acquisition_contract(profile.get("acquisition_contract"))
    if contract.get("last_quality_success") is None:
        return profile
    stale_value = contract.get("stale_after_failures")
    stale_payload = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    failure_count = int(stale_payload.get("failure_count") or 0) + 1
    contract["stale_after_failures"] = {
        "failure_count": failure_count,
        "stale": failure_count >= max(1, int(threshold or 1)),
    }
    profile["acquisition_contract"] = contract
    raw_source_run_id = profile.get("source_run_id")
    source_run_id = _coerce_source_run_id(raw_source_run_id)
    return await save_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
        profile=profile,
        source_run_id=source_run_id,
        existing_record=existing,
    )


async def record_acquisition_contract_outcome(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    acquisition_result: object,
    url_result: object,
) -> None:
    records = list(getattr(url_result, "records", []) or [])
    metrics = mapping_or_empty(getattr(url_result, "url_metrics", {}))
    metric_count = safe_int(metrics.get("record_count"), default=None)
    persisted_count = len(records) if metric_count is None else metric_count
    verdict = str(getattr(url_result, "verdict", "") or "")
    blocked = bool(metrics.get("blocked"))
    quality_success = (
        persisted_count > 0
        and not blocked
        and verdict not in {VERDICT_BLOCKED, VERDICT_EMPTY, VERDICT_LISTING_FAILED}
    )
    count_failure = _counts_as_contract_failure(
        blocked=blocked,
        verdict=verdict,
        surface=surface,
        persisted_count=persisted_count,
    )
    if quality_success:
        await _save_successful_acquisition_contract(
            session,
            domain=domain,
            surface=surface,
            source_run_id=source_run_id,
            acquisition_result=acquisition_result,
            records=records,
            persisted_count=persisted_count,
        )
        return
    if not count_failure:
        return
    await note_acquisition_contract_failure(
        session,
        domain=domain,
        surface=surface,
        threshold=int(
            crawler_runtime_settings.acquisition_contract_stale_failure_threshold
        ),
    )


async def _save_successful_acquisition_contract(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    acquisition_result: object,
    records: list[object],
    persisted_count: int,
) -> None:
    diagnostics = mapping_or_empty(
        getattr(acquisition_result, "browser_diagnostics", {})
    )
    request = getattr(acquisition_result, "request", None)
    requested_fields = acquisition_contract_fields_for_surface(
        surface, list(getattr(request, "requested_fields", []) or [])
    )
    found_fields = sorted(
        {
            str(field_name)
            for record in records
            if isinstance(record, dict)
            for field_name, value in record.items()
            if not str(field_name).startswith("_") and value not in (None, "", [], {})
        }
    )
    endpoints = learned_internal_api_endpoints(
        network_payloads=list(
            getattr(acquisition_result, "network_payloads", []) or []
        ),
        surface=surface,
        page_url=str(getattr(acquisition_result, "final_url", "") or ""),
        requested_fields=requested_fields,
        source_run_id=source_run_id,
    )
    await save_learned_acquisition_contract(
        session,
        domain=domain,
        surface=surface,
        source_run_id=source_run_id,
        contract=build_success_acquisition_contract(
            method=getattr(acquisition_result, "method", None),
            browser_engine=str(diagnostics.get("browser_engine") or "").strip().lower(),
            browser_diagnostics=dict(diagnostics),
            record_count=persisted_count,
            requested_fields=requested_fields,
            found_fields=found_fields,
            source_run_id=source_run_id,
        ),
        internal_api_endpoints=endpoints or None,
    )


def _counts_as_contract_failure(
    *, blocked: bool, verdict: str, surface: str, persisted_count: int
) -> bool:
    if blocked:
        return False
    if verdict == VERDICT_LISTING_FAILED:
        return True
    return (
        verdict == VERDICT_EMPTY
        and "detail" in str(surface or "")
        and persisted_count == 0
    )


def _coerce_source_run_id(value: object) -> int:
    if value in (None, ""):
        return 1
    try:
        return int(value) if isinstance(value, (int, float, str)) else 1
    except (TypeError, ValueError):
        try:
            return int(float(str(value)))
        except (TypeError, ValueError):
            return 1
