from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
        "quality_clean": not unresolved_issue_ids,
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

    records = _read_json(result_root / "records.json")
    summary = _read_json(result_root / "summary.json")
    debug = _read_json(result_root / "debug.json")
    field_states = _field_states(records, summary, debug)
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
    signals = _case_signals(case, records=records, debug=debug)
    unresolved = tuple(
        str(value)
        for value in case.get("issue_ids") or ()
        if signals.get("integrity_failure")
    )
    classification = (
        "integrity_failure"
        if signals.get("integrity_failure")
        else "source_unavailable"
        if signals.get("source_unavailable")
        else "artifact_consistent"
    )
    return {
        "case_id": case_id,
        "url_result_id": int(case.get("url_result_id") or 0),
        "classification": classification,
        "field_states": field_states,
        "field_state_mismatches": mismatches,
        "signals": signals,
        "unresolved_issue_ids": unresolved,
        "artifact_paths": tuple(str(result_root / name) for name in artifact_files),
    }


def _field_states(
    records: dict[str, Any], summary: dict[str, Any], debug: dict[str, Any]
) -> dict[str, str]:
    public = _first_mapping(records.get("records"))
    provenance = _first_mapping(records.get("provenance"))
    raw = provenance.get("raw_data") if isinstance(provenance, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    discovered = (
        provenance.get("discovered_data") if isinstance(provenance, dict) else {}
    )
    rejected = (
        discovered.get("rejected_public_fields") if isinstance(discovered, dict) else {}
    )
    rejected = rejected if isinstance(rejected, dict) else {}
    decisions = _decisions_by_field(summary)
    source_unavailable = _has_blocked_product_source(debug)

    fields = set(public) | set(raw) | set(rejected) | set(decisions)
    states: dict[str, str] = {}
    for field in fields:
        if field.startswith("_") or field in {
            "variants",
            "variant_count",
            "additional_images",
        }:
            continue
        if field in rejected:
            states[field] = "captured_but_rejected"
            continue
        if public.get(field) not in EMPTY_VALUES:
            states[field] = "captured_and_resolved"
            continue
        decision = decisions.get(field)
        if decision and decision.get("status") == "unresolved":
            states[field] = (
                "captured_conflicting"
                if decision.get("accepted_evidence_ids")
                else "captured_but_rejected"
            )
            continue
        if raw.get(field) not in EMPTY_VALUES:
            states[field] = "captured_but_rejected"
            continue
        if source_unavailable and field in OFFER_FIELDS:
            states[field] = "source_unavailable"
            continue
        states[field] = "not_present_in_captured_sources"
    for field in OFFER_FIELDS:
        if field not in states and source_unavailable:
            states[field] = "source_unavailable"
    return states


def _decisions_by_field(summary: dict[str, Any]) -> dict[str, dict[str, Any]]:
    extraction = summary.get("extraction")
    decisions = extraction.get("decisions") if isinstance(extraction, dict) else []
    output: dict[str, dict[str, Any]] = {}
    for row in decisions if isinstance(decisions, list) else []:
        if not isinstance(row, dict):
            continue
        fact_type = str(row.get("fact_type") or "")
        if not fact_type.startswith("product.") and not fact_type.startswith("offer."):
            continue
        field = fact_type.rsplit(".", 1)[-1]
        current = output.get(field)
        if current is None or row.get("status") == "unresolved":
            output[field] = row
    return output


def _case_signals(
    case: dict[str, Any], *, records: dict[str, Any], debug: dict[str, Any]
) -> dict[str, Any]:
    invariants_value = case.get("expected_invariants")
    invariants: dict[str, Any] = (
        invariants_value if isinstance(invariants_value, dict) else {}
    )
    public = _first_mapping(records.get("records"))
    provenance = _first_mapping(records.get("provenance"))
    raw = provenance.get("raw_data") if isinstance(provenance, dict) else {}
    raw = raw if isinstance(raw, dict) else {}
    variants_value = raw.get("variants")
    variants: list[Any] = variants_value if isinstance(variants_value, list) else []
    variant_skus = {
        str(row.get("sku"))
        for row in variants
        if isinstance(row, dict) and row.get("sku") not in EMPTY_VALUES
    }
    cross_product_values = invariants.get("cross_product_variant_skus")
    expected_cross_product = {
        str(value)
        for value in (
            cross_product_values
            if isinstance(cross_product_values, (list, tuple))
            else ()
        )
    }
    leaked_skus = tuple(sorted(variant_skus & expected_cross_product))
    raw_availability = str(raw.get("availability") or "")
    availability_prefix = str(invariants.get("raw_availability_prefix") or "")
    blocked_source = _has_blocked_product_source(
        debug,
        expected_status=invariants.get("blocked_product_api_status"),
        marker=invariants.get("blocked_product_api_marker"),
    )
    expected_title = invariants.get("selected_product_title")
    title_matches = public.get("title") == expected_title
    integrity_failure = (
        bool(expected_title is not None and not title_matches)
        or bool(leaked_skus)
        or bool(availability_prefix and raw_availability.startswith(availability_prefix))
    )
    return {
        "selected_product_title_matches": title_matches,
        "cross_product_variant_skus": leaked_skus,
        "raw_availability": raw_availability or None,
        "source_unavailable": blocked_source,
        "integrity_failure": integrity_failure,
    }


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


def _first_mapping(value: object) -> dict[str, Any]:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value
