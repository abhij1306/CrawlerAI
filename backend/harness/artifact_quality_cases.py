from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.acquisition.acquirer import PageEvidence
from app.acquisition.source_capabilities import build_source_capability_diagnostics
from app.extraction import Surface, extract
from app.extraction.contracts import ExtractionResult
from app.extraction.replay import fixture_request_from_inputs

EMPTY_VALUES: tuple[object, ...] = (None, "", [], {}, ())
OFFER_FIELDS = frozenset({"price", "currency", "availability"})
__all__ = [
    "audit_artifact_quality_cases",
    "load_artifact_quality_cases",
    "validate_artifact_quality_cases",
]

ALLOWED_FIELD_STATES = frozenset(
    {
        "captured_and_resolved",
        "captured_but_rejected",
        "captured_conflicting",
        "not_present_in_captured_sources",
        "source_unavailable",
        "interaction_required_not_captured",
        "not_applicable",
        "not_requested",
    }
)


def load_artifact_quality_cases(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit_artifact_quality_cases(
    manifest: dict[str, Any], *, backend_root: str | Path
) -> dict[str, Any]:
    root = Path(backend_root) / str(manifest.get("artifact_root") or "")
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        raise ValueError("artifact quality manifest must contain a cases list")

    audited_cases: list[dict[str, Any]] = []
    unresolved_issue_ids: set[str] = set()
    for case in cases:
        audited = _audit_case(case, root=root)
        audited_cases.append(audited)
        unresolved_issue_ids.update(audited["unresolved_issue_ids"])

    return {
        "quality_clean": not unresolved_issue_ids
        and all(
            case["classification"] != "integrity_failure" for case in audited_cases
        ),
        "case_count": len(audited_cases),
        "unresolved_issue_ids": tuple(sorted(unresolved_issue_ids)),
        "cases": tuple(audited_cases),
    }


def validate_artifact_quality_cases(
    manifest: dict[str, Any], *, backend_root: str | Path
) -> list[str]:
    errors: list[str] = []
    cases = manifest.get("cases")
    if not isinstance(cases, list):
        return ["cases must be a list"]
    if not cases:
        errors.append("cases must not be empty")
    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            errors.append(f"case {index} must be an object")
            continue
        case_id = str(case.get("case_id") or "")
        if not case_id:
            errors.append(f"case {index} has no case_id")
        elif case_id in seen_ids:
            errors.append(f"duplicate case_id: {case_id}")
        seen_ids.add(case_id)
        expected_states = case.get("expected_field_states")
        if not isinstance(expected_states, dict) or not expected_states:
            errors.append(f"{case_id or index} has no expected_field_states")
        else:
            invalid_states = sorted(
                {
                    str(state)
                    for state in expected_states.values()
                    if state not in ALLOWED_FIELD_STATES
                }
            )
            if invalid_states:
                errors.append(
                    f"{case_id or index} has invalid field states: {', '.join(invalid_states)}"
                )
    if errors:
        return errors
    try:
        report = audit_artifact_quality_cases(manifest, backend_root=backend_root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        errors.append(str(exc))
    else:
        for case in report["cases"]:
            for mismatch in case["field_state_mismatches"]:
                errors.append(
                    f"{case['case_id']} field state mismatch: "
                    f"{mismatch['field']} expected={mismatch['expected']} "
                    f"actual={mismatch['actual']}"
                )
            for invariant in case["invariant_failures"]:
                errors.append(f"{case['case_id']} invariant failure: {invariant}")
    return errors


def _audit_case(case: dict[str, Any], *, root: Path) -> dict[str, Any]:
    case_id = str(case.get("case_id") or "")
    result_root = root / str(case.get("url_result_id") or "")
    artifact_files = tuple(str(value) for value in case.get("artifact_files") or ())
    missing_artifacts = tuple(
        name for name in artifact_files if not (result_root / name).is_file()
    )
    if missing_artifacts:
        raise ValueError(f"{case_id} missing artifacts: {', '.join(missing_artifacts)}")

    result = _replay_case(case, result_root=result_root)
    field_states = {row.field: row.state for row in result.field_states}
    expected_states = {
        str(field): str(state)
        for field, state in (case.get("expected_field_states") or {}).items()
    }
    mismatches = tuple(
        {
            "field": field,
            "expected": expected,
            "actual": field_states.get(field, "not_requested"),
        }
        for field, expected in expected_states.items()
        if field_states.get(field, "not_requested") != expected
    )
    signals = _case_signals(case, result=result)
    invariant_failures = _invariant_failures(signals)
    integrity_failure = bool(
        signals["cross_entity_lineage"]
        or signals["enum_leaks"]
        or signals["identifier_conflicts"]
        or signals["public_evidence_divergence"]
        or signals["selected_product_title_matches"] is False
        or invariant_failures
        or mismatches
    )
    source_unavailable = bool(signals["source_unavailable"])
    unresolved = tuple(
        str(value) for value in case.get("issue_ids") or () if integrity_failure
    )
    classification = (
        "integrity_failure"
        if integrity_failure
        else "source_unavailable"
        if source_unavailable
        else "artifact_consistent"
    )
    return {
        "case_id": case_id,
        "url_result_id": int(case.get("url_result_id") or 0),
        "classification": classification,
        "verdict": result.verdict,
        "data_integrity": result.data_integrity,
        "field_states": field_states,
        "field_state_mismatches": mismatches,
        "signals": signals,
        "invariant_failures": invariant_failures,
        "findings": tuple(finding.rule_id for finding in result.findings),
        "unresolved_issue_ids": unresolved,
        "artifact_paths": tuple(str(result_root / name) for name in artifact_files),
    }


def _replay_case(case: dict[str, Any], *, result_root: Path) -> ExtractionResult:
    summary = _read_json(result_root / "summary.json")
    debug_path = result_root / "debug.json"
    debug = _read_json(debug_path) if debug_path.is_file() else summary
    summary_acquisition = summary.get("acquisition")
    debug_acquisition = debug.get("acquisition")
    acquisition = _deep_merge_mappings(
        summary_acquisition if isinstance(summary_acquisition, dict) else {},
        debug_acquisition if isinstance(debug_acquisition, dict) else {},
    )
    html = (result_root / "page.html").read_text(encoding="utf-8")
    source_url = str(case.get("source_url") or "") or str(
        (debug.get("acquisition") or {}).get("final_url") or ""
    )
    final_url = str(acquisition.get("final_url") or "") or source_url
    expected_states_value = case.get("expected_field_states")
    expected_states = (
        expected_states_value if isinstance(expected_states_value, dict) else {}
    )
    requested_fields = tuple(str(field) for field in expected_states)
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        final_url,
        requested_url=source_url,
        requested_fields=requested_fields,
        network_payloads=list(acquisition.get("network_payloads") or []),
    )
    diagnostics = dict(acquisition.get("acquisition_diagnostics") or {})
    blocked = _acquisition_blocked(acquisition)
    source_capabilities = build_source_capability_diagnostics(
        html=html,
        network_payloads=list(acquisition.get("network_payloads") or []),
        browser_diagnostics=dict(acquisition.get("browser_diagnostics") or {}),
        status_code=_acquisition_status_code(acquisition),
        browser_outcome=_browser_outcome(acquisition),
        blocked=blocked,
    )
    diagnostics["source_capabilities"] = source_capabilities
    invariants = case.get("expected_invariants")
    invariants = invariants if isinstance(invariants, dict) else {}
    blocked_source = _has_blocked_product_source(
        debug,
        expected_status=invariants.get("blocked_product_api_status"),
        marker=invariants.get("blocked_product_api_marker"),
    )
    if blocked_source:
        current_capabilities = dict(diagnostics.get("source_capabilities") or {})
        affected = tuple(
            dict.fromkeys(
                (
                    *tuple(current_capabilities.get("affected_field_families", ())),
                    "price",
                    "currency",
                    "availability",
                    "variants",
                )
            )
        )
        diagnostics["source_capabilities"] = {
            **current_capabilities,
            "product_data_source_unavailable": True,
            "affected_field_families": affected,
        }
    request = request.model_copy(
        update={
            "capture": request.capture.model_copy(
                update={
                    "acquisition_diagnostics": diagnostics,
                    "http_status": _acquisition_status_code(acquisition),
                    "acquisition_outcome": "blocked"
                    if blocked
                    else "error"
                    if bool(source_capabilities.get("terminal_shell"))
                    else request.capture.acquisition_outcome,
                    "blocked": blocked,
                    "browser_attempted": bool(
                        (acquisition.get("browser_diagnostics") or {}).get(
                            "browser_attempted"
                        )
                    ),
                }
            )
        }
    )
    return extract(request)


def _case_signals(case: dict[str, Any], *, result: ExtractionResult) -> dict[str, Any]:
    invariants_value = case.get("expected_invariants")
    invariants: dict[str, Any] = (
        invariants_value if isinstance(invariants_value, dict) else {}
    )
    public = (
        result.records[0].model_dump(mode="python", exclude_none=True)
        if result.records
        else {}
    )
    variants_value = public.get("variants")
    variants = list(variants_value) if isinstance(variants_value, (list, tuple)) else []
    variant_skus = {
        str(row.get("sku"))
        for row in variants
        if isinstance(row, dict) and row.get("sku") not in EMPTY_VALUES
    }
    expected_cross_product = {
        str(value) for value in invariants.get("cross_product_variant_skus", ())
    }
    leaked_skus = tuple(sorted(variant_skus & expected_cross_product))
    expected_title = invariants.get("selected_product_title")
    title_matches = (
        public.get("title") == expected_title if expected_title is not None else None
    )
    field_states = {row.field: row.state for row in result.field_states}
    source_unavailable = any(
        state == "source_unavailable" for state in field_states.values()
    )
    enum_leaks = _enum_leaks(public)
    identifier_conflicts = _identifier_conflicts(public)
    divergence = _public_evidence_divergence(result, public)
    duplicate_variant_ids = _duplicate_variant_ids(variants)
    forbidden_variant_materials = _forbidden_variant_field(
        variants,
        "material",
        invariants.get("forbidden_variant_materials", ()),
    )
    forbidden_variant_ids = _forbidden_variant_field(
        variants,
        "variant_id",
        invariants.get("forbidden_variant_ids", ()),
    )
    forbidden_variant_fragments = _forbidden_variant_fragments(
        variants, invariants.get("forbidden_variant_fragments", ())
    )
    forbidden_image_fragments = _forbidden_fragments(
        public.get("image_url"), invariants.get("forbidden_image_fragments", ())
    )
    description_forbidden_fragments = _forbidden_fragments(
        public.get("description"),
        invariants.get("forbidden_description_fragments", ()),
    )
    required_description_fragments_missing = _missing_required_fragments(
        public.get("description"),
        invariants.get("required_description_fragments", ()),
    )
    expected_brand = invariants.get("expected_brand")
    brand_matches = (
        public.get("brand") == expected_brand if expected_brand is not None else None
    )
    expected_currency = invariants.get("expected_currency")
    currency_matches = (
        public.get("currency") == expected_currency
        if expected_currency is not None
        else None
    )
    no_public_record_expected = bool(invariants.get("no_public_record"))
    sparse_public_record = bool(
        no_public_record_expected
        and public
        and {
            key
            for key, value in public.items()
            if not key.startswith("_") and value not in EMPTY_VALUES
        }
        <= {"title", "url"}
    )
    return {
        "selected_product_title_matches": title_matches,
        "cross_product_variant_skus": leaked_skus,
        "cross_entity_lineage": leaked_skus,
        "enum_leaks": enum_leaks,
        "identifier_conflicts": identifier_conflicts,
        "duplicate_variant_ids": duplicate_variant_ids,
        "forbidden_variant_materials": forbidden_variant_materials,
        "forbidden_variant_ids": forbidden_variant_ids,
        "forbidden_variant_fragments": forbidden_variant_fragments,
        "forbidden_image_fragments": forbidden_image_fragments,
        "description_forbidden_fragments": description_forbidden_fragments,
        "required_description_fragments_missing": required_description_fragments_missing,
        "brand_matches": brand_matches,
        "currency_matches": currency_matches,
        "sparse_public_record": sparse_public_record,
        "public_evidence_divergence": divergence,
        "source_unavailable": source_unavailable,
    }


def _invariant_failures(signals: dict[str, Any]) -> tuple[str, ...]:
    failures: list[str] = []
    for key in (
        "duplicate_variant_ids",
        "forbidden_variant_materials",
        "forbidden_variant_ids",
        "forbidden_variant_fragments",
        "forbidden_image_fragments",
        "description_forbidden_fragments",
        "required_description_fragments_missing",
    ):
        if signals.get(key):
            failures.append(key)
    if signals.get("brand_matches") is False:
        failures.append("brand_matches")
    if signals.get("currency_matches") is False:
        failures.append("currency_matches")
    if signals.get("sparse_public_record") is True:
        failures.append("sparse_public_record")
    return tuple(failures)


def _duplicate_variant_ids(variants: list[object]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for row in variants:
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip()
        if not variant_id:
            continue
        if variant_id in seen:
            duplicates.add(variant_id)
        seen.add(variant_id)
    return tuple(sorted(duplicates))


def _forbidden_variant_field(
    variants: list[object], field: str, forbidden: object
) -> tuple[str, ...]:
    forbidden_values = set(_string_sequence(forbidden))
    found: set[str] = set()
    for row in variants:
        if isinstance(row, dict) and str(row.get(field) or "") in forbidden_values:
            found.add(str(row.get(field)))
    return tuple(sorted(found))


def _forbidden_variant_fragments(
    variants: list[object], forbidden: object
) -> tuple[str, ...]:
    fragments = set(_string_sequence(forbidden))
    found: set[str] = set()
    for row in variants:
        if not isinstance(row, dict):
            continue
        for value in row.values():
            text = str(value or "")
            for fragment in fragments:
                if fragment and fragment in text:
                    found.add(fragment)
    return tuple(sorted(found))


def _forbidden_fragments(value: object, forbidden: object) -> tuple[str, ...]:
    text = str(value or "")
    return tuple(
        fragment for fragment in _string_sequence(forbidden) if fragment in text
    )


def _missing_required_fragments(value: object, required: object) -> tuple[str, ...]:
    text = str(value or "")
    return tuple(
        fragment for fragment in _string_sequence(required) if fragment not in text
    )


def _string_sequence(value: object) -> tuple[str, ...]:
    if isinstance(value, (set, frozenset)):
        return tuple(sorted(str(item) for item in value))
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value)
    if value in EMPTY_VALUES:
        return ()
    return (str(value),)


def _enum_leaks(public: dict[str, Any]) -> tuple[str, ...]:
    allowed = {
        "in_stock",
        "out_of_stock",
        "limited_stock",
        "preorder",
        "backorder",
        "discontinued",
    }
    leaks: list[str] = []
    availability = public.get("availability")
    if availability not in EMPTY_VALUES and availability not in allowed:
        leaks.append("availability")
    variants = public.get("variants")
    for index, row in enumerate(
        variants if isinstance(variants, (list, tuple)) else ()
    ):
        if not isinstance(row, dict):
            continue
        value = row.get("availability")
        if value not in EMPTY_VALUES and value not in allowed:
            leaks.append(f"variants[{index}].availability")
    return tuple(leaks)


def _identifier_conflicts(public: dict[str, Any]) -> tuple[str, ...]:
    conflicts: list[str] = []
    parent_sku = str(public.get("sku") or "").strip()
    variants = public.get("variants")
    for index, row in enumerate(
        variants if isinstance(variants, (list, tuple)) else ()
    ):
        if not isinstance(row, dict):
            continue
        variant_id = str(row.get("variant_id") or "").strip()
        sku = str(row.get("sku") or "").strip()
        if variant_id and sku and variant_id != sku and parent_sku == variant_id:
            conflicts.append(f"variants[{index}].sku")
    return tuple(conflicts)


def _public_evidence_divergence(
    result: ExtractionResult, public: dict[str, Any]
) -> tuple[str, ...]:
    evidence_ids = {row.evidence_id for row in result.evidence}
    lineage = public.get("_lineage")
    lineage = lineage if isinstance(lineage, dict) else {}
    divergent: list[str] = []
    for field, value in public.items():
        if (
            field.startswith("_")
            or value in EMPTY_VALUES
            or field
            in {
                "variant_count",
                "variants",
                "additional_images",
            }
        ):
            continue
        if field == "url" and field not in lineage:
            continue
        raw = lineage.get(field)
        if not isinstance(raw, dict):
            divergent.append(field)
            continue
        ids = raw.get("evidence_ids")
        if not isinstance(ids, list):
            divergent.append(field)
            continue
        missing = [str(value) for value in ids if str(value) not in evidence_ids]
        if missing:
            divergent.append(field)
    return tuple(divergent)


def _has_blocked_product_source(
    debug: dict[str, Any], *, expected_status: object = None, marker: object = None
) -> bool:
    acquisition = debug.get("acquisition")
    if isinstance(acquisition, dict):
        acquisition_diagnostics = acquisition.get("acquisition_diagnostics")
        if isinstance(acquisition_diagnostics, dict):
            source_capabilities = acquisition_diagnostics.get("source_capabilities")
            if isinstance(source_capabilities, dict):
                unavailable = source_capabilities.get("product_data_source_unavailable")
                if unavailable is True:
                    return True
        payloads = acquisition.get("network_payloads")
    else:
        payloads = []
    for payload in payloads if isinstance(payloads, list) else []:
        if not isinstance(payload, dict):
            continue
        endpoint_type = str(payload.get("endpoint_type") or "")
        status = payload.get("status")
        if (
            endpoint_type != "product_api"
            or not isinstance(status, int)
            or status < 400
        ):
            continue
        if expected_status is not None and status != expected_status:
            continue
        if marker is not None and str(marker) not in json.dumps(
            payload.get("body"), sort_keys=True
        ):
            continue
        return True
    return False


def _acquisition_blocked(acquisition: dict[str, Any]) -> bool:
    return _page_evidence(acquisition).indicates_block


def _acquisition_status_code(acquisition: dict[str, Any]) -> int | None:
    status = acquisition.get("status_code")
    if isinstance(status, int):
        return status
    diagnostics = acquisition.get("acquisition_diagnostics")
    if not isinstance(diagnostics, dict):
        return None
    result = diagnostics.get("result")
    if not isinstance(result, dict):
        return None
    attempts = result.get("attempts")
    if not isinstance(attempts, list):
        return None
    selected = str(result.get("selected_attempt_id") or "")
    fallback_status: int | None = None
    first_status: int | None = None
    selected_status: int | None = None
    selected_found = False
    for attempt in attempts:
        if not isinstance(attempt, dict):
            continue
        attempt_status = attempt.get("status_code")
        attempt_id = str(attempt.get("attempt_id") or "")
        if first_status is None and isinstance(attempt_status, int):
            first_status = attempt_status
        if selected and attempt_id == selected:
            selected_found = True
            selected_status = (
                attempt_status if isinstance(attempt_status, int) else None
            )
        if selected:
            attempt_diagnostics = attempt.get("diagnostics")
            details = (
                attempt_diagnostics if isinstance(attempt_diagnostics, dict) else {}
            )
            transport = str(details.get("transport") or "").strip().casefold()
            if transport in {"curl", "curl_cffi", "httpx"} and isinstance(
                attempt_status, int
            ):
                fallback_status = attempt_status
            continue
    if selected_found:
        return selected_status if selected_status is not None else fallback_status
    return fallback_status if fallback_status is not None else first_status


def _browser_outcome(acquisition: dict[str, Any]) -> str | None:
    outcome = acquisition.get("browser_outcome")
    if isinstance(outcome, str) and outcome:
        return outcome
    return _page_evidence(acquisition).browser_outcome or None


def _page_evidence(acquisition: dict[str, Any]) -> PageEvidence:
    browser = acquisition.get("browser_diagnostics")
    return PageEvidence(
        blocked=bool(acquisition.get("blocked")),
        method=str(acquisition.get("method") or ""),
        diagnostics=dict(browser or {}) if isinstance(browser, dict) else {},
    )


def _deep_merge_mappings(
    base: dict[str, Any], override: dict[str, Any]
) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        current = merged.get(key)
        merged[key] = (
            _deep_merge_mappings(current, value)
            if isinstance(current, dict) and isinstance(value, dict)
            else value
        )
    return merged


def _first_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value
