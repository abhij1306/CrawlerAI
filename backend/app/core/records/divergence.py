"""Precision backstop: the public record never diverges from resolution.

Diagnostic and blocking comparison between an authorized publication projection
and its deterministic serialized record. Persistence never repairs or rechecks
extraction semantics.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
import re
from typing import Any

from app.extraction.contracts import (
    CommerceDetailProjection,
    CommerceListingProjection,
    Finding,
    JobDetailProjection,
    JobListingProjection,
    PublicationEntry,
)
from app.core.shared.ids import stable_id

_EMPTY: tuple[object, ...] = (None, "", [], {}, ())


def compare_public_record_to_projection(
    record: Mapping[str, Any],
    projection: CommerceDetailProjection,
    *,
    blocking: bool,
    detect_extras: bool = False,
) -> tuple[Finding, ...]:
    """Compare legacy serialization to an authorized scalar projection."""

    entries = {
        entry.path.removeprefix("record."): entry
        for entry in projection.entries
        if entry.path.startswith("record.")
    }
    findings = list(_scalar_findings(record, entries, blocking=blocking))
    if detect_extras:
        findings.extend(_extra_scalar_findings(record, entries, blocking=blocking))
    findings.extend(
        _compare_variants(
            record, projection, blocking=blocking, detect_extras=detect_extras
        )
    )
    findings.extend(
        _compare_assets(
            record, projection, blocking=blocking, detect_extras=detect_extras
        )
    )
    return tuple(findings)


def _scalar_findings(
    record: Mapping[str, Any],
    entries: Mapping[str, PublicationEntry],
    *,
    blocking: bool,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    for field, entry in entries.items():
        actual_present = field in record and record.get(field) not in _EMPTY
        expected_present = entry.disposition == "publish"
        reason: str | None = None
        if expected_present and not actual_present:
            reason = "authorized_value_missing"
        elif not expected_present and actual_present:
            reason = f"{entry.disposition}_value_published"
        elif expected_present and not _values_equal(record.get(field), entry):
            reason = "semantic_value_mismatch"
        if reason is not None:
            findings.append(
                _projection_divergence_finding(
                    path=f"record.{field}",
                    reason=reason,
                    expected=entry.value,
                    actual=record.get(field),
                    blocking=blocking,
                    selected_fact_id=entry.selected_fact_id,
                    derived_fact_id=entry.derived_fact_id,
                )
            )
    return tuple(findings)


def _extra_scalar_findings(
    record: Mapping[str, Any],
    entries: Mapping[str, PublicationEntry],
    *,
    blocking: bool,
) -> tuple[Finding, ...]:
    structural = {"additional_images", "image_url", "variant_count", "variants"}
    return tuple(
        _projection_divergence_finding(
            path=f"record.{field}",
            reason="unauthorized_public_field",
            expected=None,
            actual=value,
            blocking=blocking,
        )
        for field, value in record.items()
        if not str(field).startswith("_")
        and value not in _EMPTY
        and field not in entries
        and field not in structural
    )


def compare_records_to_projection(
    records: Sequence[Mapping[str, Any]],
    projection: CommerceListingProjection | JobDetailProjection | JobListingProjection,
    *,
    blocking: bool,
) -> tuple[Finding, ...]:
    """Exact atomic comparison for non-commerce-detail surface projections."""

    expected_ids, actual_by_id, pattern = _record_projection_index(records, projection)
    findings = list(
        _entity_findings(
            expected_ids,
            set(actual_by_id),
            kind="record",
            missing_reason="authorized_record_missing",
            extra_reason="unauthorized_record_published",
            blocking=blocking,
        )
    )
    expected_fields: dict[str, set[str]] = {}
    for entry in projection.entries:
        identity = _projection_entry_identity(entry.path, projection, pattern)
        if identity is None:
            continue
        entity_id, field = identity
        expected_fields.setdefault(entity_id, set()).add(field)
        row = actual_by_id.get(entity_id)
        finding = _projected_field_finding(entry, row, field=field, blocking=blocking)
        if finding is not None:
            findings.append(finding)
    findings.extend(
        _unexpected_record_field_findings(
            actual_by_id, expected_fields, blocking=blocking
        )
    )
    return tuple(findings)


def _projection_entry_identity(path, projection, pattern) -> tuple[str, str] | None:
    match = pattern.match(path)
    if match is None:
        return None
    if isinstance(projection, JobDetailProjection):
        return projection.record_entity_id, match.group(1)
    return match.groups()


def _projected_field_finding(
    entry, row, *, field: str, blocking: bool
) -> Finding | None:
    if row is None:
        return None
    actual = row.get(field)
    if field in row and _values_equal(actual, entry):
        return None
    return _projection_divergence_finding(
        path=entry.path,
        reason="authorized_field_missing"
        if field not in row
        else "semantic_value_mismatch",
        expected=entry.value,
        actual=actual,
        blocking=blocking,
        selected_fact_id=entry.selected_fact_id,
        derived_fact_id=entry.derived_fact_id,
    )


def _unexpected_record_field_findings(
    actual_by_id: Mapping[str, Mapping[str, Any]],
    expected_fields: Mapping[str, set[str]],
    *,
    blocking: bool,
) -> tuple[Finding, ...]:
    return tuple(
        _projection_divergence_finding(
            path=f"record[{entity_id}].{field}",
            reason="unauthorized_public_field",
            expected=None,
            actual=value,
            blocking=blocking,
        )
        for entity_id, row in actual_by_id.items()
        for field, value in row.items()
        if not field.startswith("_")
        and value not in _EMPTY
        and field not in expected_fields.get(entity_id, set())
    )


def _record_projection_index(
    records: Sequence[Mapping[str, Any]],
    projection: CommerceListingProjection | JobDetailProjection | JobListingProjection,
) -> tuple[set[str], dict[str, Mapping[str, Any]], re.Pattern[str]]:
    if isinstance(projection, JobDetailProjection):
        expected = {projection.record_entity_id} if projection.entries else set()
        actual = {projection.record_entity_id: records[0]} if len(records) == 1 else {}
        return expected, actual, re.compile(r"^record\.(.+)$")
    actual = {
        str(row.get("_subject_id")): row for row in records if row.get("_subject_id")
    }
    return (
        set(projection.record_entity_ids),
        actual,
        re.compile(r"^record\[([^]]+)]\.(.+)$"),
    )


def _compare_variants(
    record: Mapping[str, Any],
    projection: CommerceDetailProjection,
    *,
    blocking: bool,
    detect_extras: bool,
) -> tuple[Finding, ...]:
    rows, lineage_rows, actual_by_id = _variant_index(record)
    expected_ids = set(projection.variant_entity_ids)
    findings: list[Finding] = []
    if detect_extras:
        findings.extend(_orphan_variant_findings(rows, lineage_rows, blocking=blocking))
    findings.extend(
        _entity_findings(
            expected_ids,
            set(actual_by_id),
            kind="variant",
            missing_reason="authorized_variant_missing",
            extra_reason="unauthorized_variant_published",
            blocking=blocking,
        )
    )
    pattern = re.compile(r"^variant\[([^]]+)]\.(.+)$")
    for entry in projection.entries:
        match = pattern.match(entry.path)
        if match is None:
            continue
        entity_id, field = match.groups()
        row = actual_by_id.get(entity_id)
        actual = row.get(field) if row is not None else None
        if row is None:
            continue
        if field not in row or not _values_equal(actual, entry):
            findings.append(
                _projection_divergence_finding(
                    path=entry.path,
                    reason=(
                        "authorized_variant_field_missing"
                        if field not in row
                        else "variant_field_mismatch"
                    ),
                    expected=entry.value,
                    actual=actual,
                    blocking=blocking,
                    selected_fact_id=entry.selected_fact_id,
                    derived_fact_id=entry.derived_fact_id,
                )
            )
    return tuple(findings)


def _variant_index(
    record: Mapping[str, Any],
) -> tuple[tuple[object, ...], tuple[object, ...], dict[str, Mapping[str, Any]]]:
    raw_rows = record.get("variants")
    rows = tuple(raw_rows) if isinstance(raw_rows, (list, tuple)) else ()
    raw_lineage = record.get("_lineage")
    lineage = raw_lineage.get("variants") if isinstance(raw_lineage, Mapping) else ()
    lineage_rows = tuple(lineage) if isinstance(lineage, (list, tuple)) else ()
    actual = {
        str(lineage_row.get("variant_entity_id")): row
        for row, lineage_row in zip(rows, lineage_rows, strict=False)
        if isinstance(row, Mapping)
        and isinstance(lineage_row, Mapping)
        and lineage_row.get("variant_entity_id")
    }
    return rows, lineage_rows, actual


def _orphan_variant_findings(
    rows: tuple[object, ...],
    lineage_rows: tuple[object, ...],
    *,
    blocking: bool,
) -> tuple[Finding, ...]:
    return tuple(
        _projection_divergence_finding(
            path=f"record.variants[{index}]",
            reason="variant_without_authorized_entity",
            expected=None,
            actual=row,
            blocking=blocking,
        )
        for index, row in enumerate(rows)
        if isinstance(row, Mapping) and _variant_lineage_missing(lineage_rows, index)
    )


def _variant_lineage_missing(lineage_rows: tuple[object, ...], index: int) -> bool:
    if index >= len(lineage_rows):
        return True
    lineage = lineage_rows[index]
    return not isinstance(lineage, Mapping) or not lineage.get("variant_entity_id")


def _compare_assets(
    record: Mapping[str, Any],
    projection: CommerceDetailProjection,
    *,
    blocking: bool,
    detect_extras: bool,
) -> tuple[Finding, ...]:
    actual_by_id, primary_lineage, additional_urls, additional_lineage = _asset_index(
        record
    )
    expected_ids = set(projection.asset_entity_ids)
    findings: list[Finding] = []
    if detect_extras:
        findings.extend(
            _orphan_asset_findings(
                record,
                primary_lineage,
                additional_urls,
                additional_lineage,
                blocking=blocking,
            )
        )
    findings.extend(
        _entity_findings(
            expected_ids,
            set(actual_by_id),
            kind="asset",
            missing_reason="authorized_asset_missing",
            extra_reason="unauthorized_asset_published",
            blocking=blocking,
        )
    )
    if projection.primary_asset_entity_id is not None:
        actual_primary = next(
            (
                entity_id
                for entity_id, values in actual_by_id.items()
                if values.get("role") == "primary"
            ),
            None,
        )
        if actual_primary != projection.primary_asset_entity_id:
            findings.append(
                _projection_divergence_finding(
                    path="record.image_url",
                    reason="primary_asset_role_mismatch",
                    expected=projection.primary_asset_entity_id,
                    actual=actual_primary,
                    blocking=blocking,
                )
            )
    pattern = re.compile(r"^asset\[([^]]+)]\.(url|role)$")
    for entry in projection.entries:
        match = pattern.match(entry.path)
        if match is None:
            continue
        entity_id, field = match.groups()
        actual = actual_by_id.get(entity_id, {}).get(field)
        if entity_id in actual_by_id and not _values_equal(actual, entry):
            findings.append(
                _projection_divergence_finding(
                    path=entry.path,
                    reason="asset_field_mismatch",
                    expected=entry.value,
                    actual=actual,
                    blocking=blocking,
                    selected_fact_id=entry.selected_fact_id,
                    derived_fact_id=entry.derived_fact_id,
                )
            )
    if projection.ordered_additional_asset_ids is not None:
        actual_order = tuple(
            entity_id
            for entity_id, values in actual_by_id.items()
            if values.get("role") == "additional"
        )
        if actual_order != projection.ordered_additional_asset_ids:
            findings.append(
                _projection_divergence_finding(
                    path="record.additional_images",
                    reason="asset_order_mismatch",
                    expected=projection.ordered_additional_asset_ids,
                    actual=actual_order,
                    blocking=blocking,
                )
            )
    return tuple(findings)


def _orphan_asset_findings(
    record: Mapping[str, Any],
    primary_lineage: object,
    additional_urls: object,
    additional_lineage: object,
    *,
    blocking: bool,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    if record.get("image_url") not in _EMPTY and not (
        isinstance(primary_lineage, Mapping) and primary_lineage.get("asset_entity_id")
    ):
        findings.append(
            _projection_divergence_finding(
                path="record.image_url",
                reason="asset_without_authorized_entity",
                expected=None,
                actual=record.get("image_url"),
                blocking=blocking,
            )
        )
    if not isinstance(additional_urls, (list, tuple)):
        return tuple(findings)
    lineages = (
        tuple(additional_lineage)
        if isinstance(additional_lineage, (list, tuple))
        else ()
    )
    findings.extend(
        _projection_divergence_finding(
            path=f"record.additional_images[{index}]",
            reason="asset_without_authorized_entity",
            expected=None,
            actual=url,
            blocking=blocking,
        )
        for index, url in enumerate(additional_urls)
        if url not in _EMPTY
        and not (
            index < len(lineages)
            and isinstance(lineages[index], Mapping)
            and lineages[index].get("asset_entity_id")
        )
    )
    return tuple(findings)


def _asset_index(
    record: Mapping[str, Any],
) -> tuple[dict[str, dict[str, object]], object, object, object]:
    raw_lineage = record.get("_lineage")
    lineages = raw_lineage if isinstance(raw_lineage, Mapping) else {}
    actual: dict[str, dict[str, object]] = {}
    primary_lineage = lineages.get("image_url")
    if isinstance(primary_lineage, Mapping) and primary_lineage.get("asset_entity_id"):
        actual[str(primary_lineage["asset_entity_id"])] = {
            "url": record.get("image_url"),
            "role": "primary",
        }
    additional_urls = record.get("additional_images")
    additional_lineage = lineages.get("additional_images")
    if isinstance(additional_urls, (list, tuple)) and isinstance(
        additional_lineage, (list, tuple)
    ):
        for url, lineage in zip(additional_urls, additional_lineage, strict=False):
            if isinstance(lineage, Mapping) and lineage.get("asset_entity_id"):
                actual[str(lineage["asset_entity_id"])] = {
                    "url": url,
                    "role": "additional",
                }
    return actual, primary_lineage, additional_urls, additional_lineage


def _entity_findings(
    expected_ids: set[str],
    actual_ids: set[str],
    *,
    kind: str,
    missing_reason: str,
    extra_reason: str,
    blocking: bool,
) -> tuple[Finding, ...]:
    missing = (
        _projection_divergence_finding(
            path=f"{kind}[{entity_id}]",
            reason=missing_reason,
            expected=entity_id,
            actual=None,
            blocking=blocking,
        )
        for entity_id in sorted(expected_ids - actual_ids)
    )
    extra = (
        _projection_divergence_finding(
            path=f"{kind}[{entity_id}]",
            reason=extra_reason,
            expected=None,
            actual=entity_id,
            blocking=blocking,
        )
        for entity_id in sorted(actual_ids - expected_ids)
    )
    return (*missing, *extra)


def _values_equal(actual: object, entry: PublicationEntry) -> bool:
    expected = (
        entry.canonicalization.canonical_value
        if entry.canonicalization is not None
        else entry.value
    )
    if isinstance(actual, (list, tuple)) and isinstance(expected, (list, tuple)):
        return tuple(actual) == tuple(expected)
    if _decimal_value(actual) is not None and _decimal_value(expected) is not None:
        return _decimal_value(actual) == _decimal_value(expected)
    return actual == expected


def _decimal_value(value: object) -> Decimal | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _projection_divergence_finding(
    *,
    path: str,
    reason: str,
    expected: object,
    actual: object,
    blocking: bool,
    selected_fact_id: str | None = None,
    derived_fact_id: str | None = None,
) -> Finding:
    return Finding(
        finding_id=stable_id("finding", "PUBLIC_RESOLUTION_DIVERGENCE", path, reason),
        rule_id="PUBLIC_RESOLUTION_DIVERGENCE",
        severity="critical" if blocking else "medium",
        scope="selected_public_value",
        entity_ids=(),
        evidence_ids=(),
        message=f"Public path '{path}' diverges from its authorized projection ({reason}).",
        blocking=blocking,
        metadata={
            "path": path,
            "reason": reason,
            "expected": _json_value(expected),
            "actual": _json_value(actual),
            "selected_fact_id": selected_fact_id,
            "derived_fact_id": derived_fact_id,
        },
    )


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    return str(value)
