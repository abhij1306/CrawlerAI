"""Causal verdict, field-state, shell, coverage, and metric policy."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from app.core.config import field_mappings
from app.core.config.extraction_rules import (
    DETAIL_NOT_FOUND_HTTP_STATUS_CODES,
    DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS,
    DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS,
    DETAIL_REVIEW_RISK_FINDING_RULE_IDS,
    DETAIL_SHELL_TITLE_FLAG,
)
from app.extraction.contracts import (
    Evidence,
    ExtractionRequest,
    FieldEvidenceState,
    Finding,
    PublicRecord,
    RetryRequest,
    TargetSelection,
    Verdict,
)
from app.extraction.listing_records import accepted_network_listing_subject_count
from app.extraction.surfaces import Surface, listing_schema
from app.observability.extraction_diagnostics import (
    is_semantic_detail_shell,
    is_shell_record,
)

_PUBLISHED_STATES = {"captured_published", "captured_and_resolved"}
_EMPTY_VALUES: tuple[object, ...] = (None, "", [], {}, ())


def assess(
    request: ExtractionRequest,
    target: TargetSelection,
    records: tuple[PublicRecord, ...],
    findings: tuple[Finding, ...],
) -> Verdict:
    if _terminal_detail_failure(request, records, findings):
        return "error"
    if request.capture.acquisition_outcome in {"blocked", "error"}:
        return cast(Verdict, request.capture.acquisition_outcome)
    if any(row.rule_id == "PUBLIC_RESOLUTION_DIVERGENCE" for row in findings):
        return "invalid"
    if any(row.blocking for row in findings):
        return "error" if request.surface is Surface.JOB_DETAIL else "invalid"
    if target.status == "ambiguous":
        return "review"
    if not records:
        return "empty"
    if _detail_is_partial(request, records, findings):
        return "partial"
    return "success"


def review_required(
    request: ExtractionRequest,
    *,
    verdict: Verdict,
    findings: tuple[Finding, ...],
    field_states: tuple[FieldEvidenceState, ...],
    retry: RetryRequest | None,
) -> bool:
    if verdict == "review":
        return True
    if retry is not None and retry.required:
        return False
    if any(
        row.rule_id in DETAIL_REVIEW_RISK_FINDING_RULE_IDS and row.scope != "candidate"
        for row in findings
    ):
        return True
    states = {row.field: row.state for row in field_states}
    if _parent_child_diverges(states):
        return True
    requested = {
        "image_url" if field == "image" else field for field in request.requested_fields
    } & DETAIL_REVIEW_HIGH_VALUE_REQUESTED_FIELDS
    return any(states.get(field) not in _PUBLISHED_STATES for field in requested)


def _terminal_detail_failure(request, records, findings) -> bool:
    return request.surface is Surface.ECOMMERCE_DETAIL and (
        request.capture.http_status in DETAIL_NOT_FOUND_HTTP_STATUS_CODES
        or is_semantic_detail_shell(request, records, findings)
    )


def _detail_is_partial(request, records, findings) -> bool:
    if request.surface is not Surface.ECOMMERCE_DETAIL:
        return False
    missing = {
        "image_url" if field == "image" else field
        for field in request.requested_fields
        if records[0].get("image_url" if field == "image" else field) in _EMPTY_VALUES
    }
    incomplete = {"MISSING_CONTRACT_FIELD", "VARIANT_AVAILABILITY_MISSING"}
    return bool(missing or any(row.rule_id in incomplete for row in findings))


def _parent_child_diverges(states: Mapping[str, str]) -> bool:
    return any(
        states.get(f"variants.{field}") == "captured_published"
        and states.get(field) not in _PUBLISHED_STATES
        for field in DETAIL_REVIEW_PARENT_CHILD_DIVERGENCE_FIELDS
    )


def retry_request(
    verdict: str,
    records: tuple[PublicRecord, ...],
    request: ExtractionRequest,
    evidence: tuple[Evidence, ...] = (),
) -> RetryRequest | None:
    shell_detected = any(is_shell_record(record) for record in records) or any(
        DETAIL_SHELL_TITLE_FLAG in row.flags for row in evidence
    )
    if verdict == "error" and shell_detected:
        return RetryRequest(
            required=not request.capture.browser_attempted,
            reason="http_shell",
            required_artifacts=("rendered_html",),
        )
    listing_retry: tuple[
        Literal["empty_extraction", "listing_network_missing"], tuple[str, ...]
    ] = (
        ("empty_extraction", ("rendered_html",)),
        ("listing_network_missing", ("rendered_html", "network_payloads")),
    )[request.capture.browser_attempted]
    if (
        listing_schema(request.surface) is not None
        and verdict == "empty"
        and not records
        and any(
            (
                not request.capture.browser_attempted,
                accepted_network_listing_subject_count(evidence) < 2,
            )
        )
    ):
        return RetryRequest(
            required=True,
            reason=listing_retry[0],
            required_artifacts=listing_retry[1],
        )
    if _needs_variant_retry(request, records, evidence):
        return RetryRequest(
            required=True,
            reason="explicit_variants_missing",
            required_artifacts=("rendered_html", "network_payloads"),
        )
    requested_core_fields = {
        "image_url" if field == "image" else field
        for field in request.requested_fields
        if field in field_mappings.ECOMMERCE_DETAIL_REQUESTED_CORE_FIELDS
    }
    if (
        request.surface.value == "ecommerce_detail"
        and verdict in {"error", "partial", "review"}
        and not request.capture.browser_attempted
        and (not request.requested_fields or requested_core_fields or not records)
    ):
        record = records[0] if records else PublicRecord()
        target_core_fields = requested_core_fields or set(
            field_mappings.SURFACE_BROWSER_RETRY_TARGETS.get("ecommerce_detail", ())
        )
        missing_core_fields = tuple(
            field
            for field in target_core_fields
            if record.get(field) in (None, "", [], {}, ())
        )
        if missing_core_fields or not records:
            return RetryRequest(
                required=True,
                reason="dynamic_content_missing",
                required_artifacts=("rendered_html", "network_payloads"),
            )
    return None


def _needs_variant_retry(request, records, evidence) -> bool:
    if request.surface.value != "ecommerce_detail" or request.capture.browser_attempted:
        return False
    explicit_cues = _explicit_variant_dom_cues(evidence) or _captured_variant_dom_cues(
        request
    )
    return (explicit_cues and _variant_controls_incomplete(records, evidence)) or (
        "variants" in request.requested_fields
        and _variants_missing_or_incomplete(records)
    )


def _explicit_variant_dom_cues(evidence: tuple[Evidence, ...]) -> bool:
    return any(
        row.collector_id == "dom" and row.fact_type.startswith("option.")
        for row in evidence
    )


def _captured_variant_dom_cues(request: ExtractionRequest) -> bool:
    artifact = next(
        (
            row
            for row in request.capture.artifacts
            if row.artifact_type in {"rendered_html", "http_html"}
        ),
        None,
    )
    if artifact is None:
        return False
    try:
        document = request.artifact_reader.document_store.html(artifact.artifact_id)
    except (LookupError, ValueError):
        return False
    if document is None:
        return False
    for select in document.css("select"):
        parent = select.parent()
        context = " ".join(
            (
                select.attribute("name") or "",
                select.attribute("id") or "",
                parent.content_text()[:200] if parent is not None else "",
            )
        ).casefold()
        if len(select.css("option")) > 1 and any(
            token in context for token in ("size", "color", "colour")
        ):
            return True
    return False


def _variants_missing_or_incomplete(records: tuple[PublicRecord, ...]) -> bool:
    variants = tuple(records[0].get("variants") or ()) if records else ()
    return not variants or any(
        not isinstance(variant, dict)
        or all(
            variant.get(field) in (None, "", [], {}, ())
            for field in ("variant_id", "sku", "size", "color", "style")
        )
        for variant in variants
    )


def _variant_controls_incomplete(
    records: tuple[PublicRecord, ...], evidence: tuple[Evidence, ...]
) -> bool:
    variants = tuple(records[0].get("variants") or ()) if records else ()
    axes = {
        row.fact_type.removeprefix("option.")
        for row in evidence
        if row.collector_id == "dom" and row.fact_type.startswith("option.")
    }
    if not variants:
        return True
    return any(
        any(variant.get(axis) in (None, "", [], {}, ()) for variant in variants)
        for axis in axes
    )
