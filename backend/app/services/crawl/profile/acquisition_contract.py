from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.config.runtime_settings import crawler_runtime_settings
from app.services.publish import VERDICT_BLOCKED, VERDICT_EMPTY, VERDICT_LISTING_FAILED

from .normalization import (
    _BROWSER_ENGINE_VALUES,
    _clean_str,
    _coerce_optional_choice,
    normalize_acquisition_contract,
    normalize_domain_run_profile,
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
    stale_value = normalized.get("stale_after_failures")
    stale = dict(stale_value) if isinstance(stale_value, Mapping) else {}
    if bool(stale.get("stale")):
        profile["acquisition_contract_stale"] = True
        return profile
    engine = str(normalized.get("preferred_browser_engine") or "auto").strip().lower()
    cookie_engine = str(normalized.get("handoff_cookie_engine") or "auto").strip().lower()
    if bool(normalized.get("prefer_browser")):
        profile["prefer_browser"] = True
        profile.setdefault("browser_reason", "acquisition-contract")
    if engine in {"patchright", "real_chrome"} and not profile.get("forced_browser_engine"):
        profile["forced_browser_engine"] = engine
    if bool(normalized.get("handoff_eligible")):
        profile["prefer_curl_handoff"] = True
        profile["handoff_eligible"] = True
    if cookie_engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = cookie_engine
    elif engine in {"patchright", "real_chrome"}:
        profile["handoff_cookie_engine"] = engine
    return profile


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
    extraction_source = str(diagnostics.get("extraction_source") or "").strip().lower()
    required_rendering = extraction_source in {"rendered_dom", "rendered_dom_visual"}
    required_traversal = bool(diagnostics.get("traversal_activated"))
    required_network_payloads = int(float(diagnostics.get("network_payload_count") or 0)) > 0
    handoff_eligible = (
        normalized_method == "browser"
        and preferred_engine != "auto"
        and not required_rendering
        and not required_traversal
        and not required_network_payloads
    )
    handoff_engine = preferred_engine if handoff_eligible else "auto"
    requested_set = set(requested_fields or [])
    covered_fields = [field for field in list(found_fields or []) if field in requested_set]
    return normalize_acquisition_contract(
        {
            "preferred_browser_engine": preferred_engine,
            "prefer_browser": normalized_method == "browser",
            "handoff_eligible": handoff_eligible,
            "handoff_cookie_engine": handoff_engine,
            "required_rendering": required_rendering,
            "required_traversal": required_traversal,
            "required_network_payloads": required_network_payloads,
            "last_quality_success": {
                "method": normalized_method or None,
                "browser_engine": normalized_engine,
                "record_count": int(record_count or 0),
                "field_coverage": {
                    "requested": list(requested_fields or []),
                    "found": covered_fields,
                    "missing": [
                        field
                        for field in list(requested_fields or [])
                        if field not in set(covered_fields)
                    ],
                },
                "source_run_id": int(source_run_id or 0),
                "timestamp": timestamp or datetime.now(UTC).isoformat(),
            },
            "stale_after_failures": {"failure_count": 0, "stale": False},
        }
    )


async def save_learned_acquisition_contract(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    contract: dict[str, object],
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
    base_profile["acquisition_contract"] = normalize_acquisition_contract(contract)
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
    return await save_domain_run_profile(
        session,
        domain=domain,
        surface=surface,
        profile=profile,
        source_run_id=int(profile.get("source_run_id") or 0) or 1,
        existing_record=existing,
    )


async def record_acquisition_contract_outcome(
    session: AsyncSession,
    *,
    domain: str,
    surface: str,
    source_run_id: int,
    method: object,
    browser_engine: object,
    browser_diagnostics: dict[str, object] | None = None,
    requested_fields: list[str],
    records: list[dict[str, object]],
    persisted_count: int,
    verdict: str,
    blocked: bool,
) -> None:
    stale_threshold = int(
        crawler_runtime_settings.acquisition_contract_stale_failure_threshold
    )
    quality_success = (
        persisted_count > 0
        and not blocked
        and verdict not in {VERDICT_BLOCKED, VERDICT_EMPTY, VERDICT_LISTING_FAILED}
    )
    count_failure = not blocked and (
        verdict == VERDICT_LISTING_FAILED
        or (
            verdict == VERDICT_EMPTY
            and "detail" in str(surface or "")
            and persisted_count == 0
        )
    )
    if quality_success:
        found_fields = sorted(
            {
                str(field_name)
                for record in records
                if isinstance(record, dict)
                for field_name, value in record.items()
                if not str(field_name).startswith("_") and value not in (None, "", [], {})
            }
        )
        await save_learned_acquisition_contract(
            session,
            domain=domain,
            surface=surface,
            source_run_id=source_run_id,
            contract=build_success_acquisition_contract(
                method=method,
                browser_engine=browser_engine,
                browser_diagnostics=browser_diagnostics,
                record_count=persisted_count,
                requested_fields=requested_fields,
                found_fields=found_fields,
                source_run_id=source_run_id,
            ),
        )
        return
    if not count_failure:
        return
    await note_acquisition_contract_failure(
        session,
        domain=domain,
        surface=surface,
        threshold=stale_threshold,
    )
