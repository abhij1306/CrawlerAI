from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .support import evaluate_quality

MISSING_FIELDS = (
    "availability",
    "brand",
    "price",
    "currency",
    "image_url",
    "description",
    "title",
)

EXPECTED_ISSUE_IDS = tuple(f"QD-{index:02d}" for index in range(1, 14))
RESOLVED_CLASSIFICATIONS = frozenset(
    {"fixed_offline", "source_unavailable", "blocked"}
)

__all__ = [
    "audit_catalog_quality_manifest",
    "build_catalog_quality_report",
    "evaluate_quality",
    "load_catalog_quality_manifest",
    "validate_catalog_quality_manifest",
]


def load_catalog_quality_manifest(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def audit_catalog_quality_manifest(manifest: dict[str, Any]) -> dict[str, int]:
    records = manifest.get("records")
    field_order = manifest.get("field_order")
    if not isinstance(records, list):
        raise ValueError("catalog quality manifest must contain a records list")
    if field_order != list(MISSING_FIELDS):
        raise ValueError("catalog quality field_order does not match the auditor contract")

    counts = {f"missing_{field}": 0 for field in MISSING_FIELDS}
    counts.update(
        {
            "description_length_320": 0,
            "parent_variant_price_mismatch": 0,
            "primary_gallery_duplicate": 0,
        }
    )
    for row in records:
        if not isinstance(row, list) or len(row) != 4:
            raise ValueError("catalog quality records must be [mask, description_length, price_mismatch, image_duplicate]")
        missing_mask, description_length, price_mismatch, image_duplicate = row
        for index, field in enumerate(MISSING_FIELDS):
            counts[f"missing_{field}"] += int(bool(int(missing_mask) & (1 << index)))
        counts["description_length_320"] += int(description_length == 320)
        counts["parent_variant_price_mismatch"] += int(bool(price_mismatch))
        counts["primary_gallery_duplicate"] += int(bool(image_duplicate))
    return counts


def build_catalog_quality_report(manifest: dict[str, Any]) -> dict[str, Any]:
    issue_examples = manifest.get("issue_examples") or {}
    issue_resolutions = manifest.get("issue_resolutions") or {}
    issues: list[dict[str, Any]] = []
    records_by_url: dict[str, dict[str, Any]] = {}
    for issue_id in EXPECTED_ISSUE_IDS:
        resolution = issue_resolutions.get(issue_id) or {}
        classification = str(resolution.get("classification") or "unresolved")
        findings = tuple(str(value) for value in resolution.get("findings") or ())
        verification = tuple(
            str(value) for value in resolution.get("verification") or ()
        )
        affected_urls = tuple(str(value) for value in issue_examples.get(issue_id) or ())
        unresolved = (
            classification not in RESOLVED_CLASSIFICATIONS
            or not findings
            or (classification == "fixed_offline" and not verification)
        )
        lineage_pointers = tuple(
            dict.fromkeys(
                (
                    f"manifest:issue_examples:{issue_id}",
                    *verification,
                )
            )
        )
        issues.append(
            {
                "issue_id": issue_id,
                "classification": classification,
                "unresolved": unresolved,
                "affected_urls": affected_urls,
                "findings": findings,
                "lineage_pointers": lineage_pointers,
            }
        )
        for url in affected_urls:
            row = records_by_url.setdefault(
                url,
                {"url": url, "issue_ids": [], "lineage_pointers": []},
            )
            row["issue_ids"].append(issue_id)
            row["lineage_pointers"].extend(lineage_pointers)
    unresolved_ids = tuple(
        issue["issue_id"] for issue in issues if issue["unresolved"]
    )
    baseline_counts = audit_catalog_quality_manifest(manifest)
    return {
        "quality_clean": not unresolved_ids,
        "unresolved_blocker_count": len(unresolved_ids),
        "unresolved_issue_ids": unresolved_ids,
        "baseline_signal_counts": baseline_counts,
        "baseline_signal_count": sum(baseline_counts.values()),
        "affected_url_count": len(records_by_url),
        "issues": tuple(issues),
        "records": tuple(
            {
                "url": row["url"],
                "issue_ids": tuple(dict.fromkeys(row["issue_ids"])),
                "lineage_pointers": tuple(
                    dict.fromkeys(row["lineage_pointers"])
                ),
            }
            for row in records_by_url.values()
        ),
    }


def validate_catalog_quality_manifest(manifest: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    records = manifest.get("records")
    if not isinstance(records, list):
        return ["records must be a list"]
    if manifest.get("record_count") != len(records):
        errors.append("record_count does not match records")
    issue_examples = manifest.get("issue_examples")
    expected_issue_ids = set(EXPECTED_ISSUE_IDS)
    if not isinstance(issue_examples, dict):
        errors.append("issue_examples must be an object")
    else:
        missing_ids = expected_issue_ids - set(issue_examples)
        if missing_ids:
            errors.append(f"missing issue IDs: {', '.join(sorted(missing_ids))}")
        empty_ids = [
            issue_id
            for issue_id in EXPECTED_ISSUE_IDS
            if not issue_examples.get(issue_id)
        ]
        if empty_ids:
            errors.append(f"issue IDs without examples: {', '.join(empty_ids)}")
    issue_resolutions = manifest.get("issue_resolutions")
    if not isinstance(issue_resolutions, dict):
        errors.append("issue_resolutions must be an object")
    else:
        missing_resolutions = expected_issue_ids - set(issue_resolutions)
        if missing_resolutions:
            errors.append(
                "missing issue resolutions: "
                + ", ".join(sorted(missing_resolutions))
            )
        for issue_id in EXPECTED_ISSUE_IDS:
            resolution = issue_resolutions.get(issue_id)
            if not isinstance(resolution, dict):
                continue
            classification = resolution.get("classification")
            if classification not in RESOLVED_CLASSIFICATIONS:
                errors.append(f"{issue_id} has unresolved classification")
            if not resolution.get("findings"):
                errors.append(f"{issue_id} has no finding evidence")
            if classification == "fixed_offline" and not resolution.get("verification"):
                errors.append(f"{issue_id} has no offline verification pointer")
    try:
        actual_counts = audit_catalog_quality_manifest(manifest)
    except ValueError as exc:
        errors.append(str(exc))
    else:
        expected_counts = manifest.get("expected_counts")
        if expected_counts != actual_counts:
            errors.append(
                f"expected_counts mismatch: expected={expected_counts!r} actual={actual_counts!r}"
            )
    return errors
