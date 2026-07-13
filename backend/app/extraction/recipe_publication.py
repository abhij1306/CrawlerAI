"""Public-record projection for validated recipe execution values."""

from __future__ import annotations

from typing import Any
from app.core.extraction_memory.recipe_contracts import (
    ExtractionRecipe,
    RecipeExecutionResult,
)
from app.core.shared.ids import stable_id
from app.extraction.contracts import (
    CommerceDetailRecord,
    CommerceListingRecord,
    CommerceVariantRecord,
    ExtractionRequest,
    Finding,
    JobDetailRecord,
    JobListingRecord,
    PublicRecord,
)
from app.extraction.surfaces import Surface
from app.extraction.validation import validate_selected_contract_fields

_MODEL_BY_SURFACE = {
    Surface.ECOMMERCE_DETAIL: CommerceDetailRecord,
    Surface.ECOMMERCE_LISTING: CommerceListingRecord,
    Surface.JOB_DETAIL: JobDetailRecord,
    Surface.JOB_LISTING: JobListingRecord,
}


def publish_recipe_execution(
    request: ExtractionRequest,
    recipe: ExtractionRecipe,
    execution: RecipeExecutionResult,
) -> tuple[tuple[PublicRecord, ...], tuple[Finding, ...]]:
    """Project authorized executor values. No discovery or semantic repair."""

    model: Any = _MODEL_BY_SURFACE[request.surface]
    field_sources = _field_sources(recipe, execution)
    records: list[PublicRecord] = []
    for index, raw in enumerate(execution.records[: request.max_records]):
        lineage = _lineage(recipe, execution, record_index=index)
        payload = _public_payload(model, raw)
        variant_lineage: list[dict[str, object]] = []
        if model is CommerceDetailRecord:
            variant_rows = sorted(
                (dict(row) for row in raw.get("variants", ()) if isinstance(row, dict)),
                key=lambda row: tuple(
                    str(row.get(field) or "")
                    for field in ("variant_id", "sku", "color", "size")
                ),
            )
            variant_records: list[CommerceVariantRecord] = []
            for row in variant_rows:
                row_lineage = row.pop("_binding_lineage", {})
                variant_records.append(CommerceVariantRecord.model_validate(row))
                variant_lineage.append(dict(row_lineage))
            variants = tuple(variant_records)
            payload["variants"] = variants
            payload["variant_count"] = len(variants)
            if isinstance(raw.get("additional_images"), (list, tuple)):
                payload["additional_images"] = tuple(raw["additional_images"])
        subject_id = stable_id(
            "recipe-record", request.capture.bundle_id, execution.recipe_id, index
        )
        if variant_lineage:
            lineage["variants"] = variant_lineage
        payload.update(
            {
                "_subject_id": subject_id,
                "_record_key": subject_id,
                "_lineage": lineage,
                "_field_sources": field_sources,
            }
        )
        records.append(model.model_validate(payload))
    result = tuple(records)
    findings = (
        validate_selected_contract_fields(
            result,
            request.requested_fields,
        )
        if request.surface is Surface.ECOMMERCE_DETAIL
        else ()
    )
    return result, findings


def _public_payload(model, raw: dict[str, object]) -> dict[str, object]:
    allowed = set(model.model_fields)
    return {key: value for key, value in raw.items() if key in allowed}


def _lineage(
    recipe: ExtractionRecipe,
    execution: RecipeExecutionResult,
    *,
    record_index: int = 0,
) -> dict[str, object]:
    bindings = {
        binding.binding_id: binding
        for binding in (
            recipe.record_root,
            *recipe.identity,
            *sum(recipe.fields.values(), ()),
        )
    }
    public_fields = {
        binding.field for binding in sum(recipe.fields.values(), ()) if binding.field
    }
    grouped: dict[str, list[dict[str, object]]] = {}
    for outcome in execution.outcomes:
        if outcome.status != "resolved" or not outcome.source_path:
            continue
        binding = bindings.get(outcome.binding_id)
        field = binding.field if binding is not None else None
        if outcome.binding_id.startswith("record.identity."):
            field = outcome.binding_id.rsplit(".", 1)[-1]
            if field in public_fields:
                continue
        if not field or ("." in field and not outcome.binding_id.startswith("field.")):
            continue
        grouped.setdefault(field, []).append(
            {
                "recipe_id": execution.recipe_id,
                "binding_id": outcome.binding_id,
                "source_path": outcome.source_path,
                "rule_id": binding.rule_id if binding else None,
                "derived_fact_id": stable_id(
                    "recipe-fact", execution.recipe_id, outcome.binding_id
                ),
            }
        )
    listing = recipe.scope.surface.endswith("_listing")
    return {
        field: rows[min(record_index, len(rows) - 1)]
        if listing or len(rows) == 1
        else rows
        for field, rows in grouped.items()
    }


def _field_sources(
    recipe: ExtractionRecipe, execution: RecipeExecutionResult
) -> dict[str, list[str]]:
    bindings = {
        binding.binding_id: binding
        for binding in (
            *recipe.identity,
            *sum(recipe.fields.values(), ()),
        )
    }
    sources: dict[str, set[str]] = {}
    for outcome in execution.outcomes:
        if outcome.status != "resolved":
            continue
        binding = bindings.get(outcome.binding_id)
        if binding is None or not binding.collector_id:
            continue
        field = binding.field
        if field is None and outcome.binding_id.startswith("record.identity."):
            field = outcome.binding_id.rsplit(".", 1)[-1]
        if field:
            sources.setdefault(field, set()).add(binding.collector_id)
    return {field: sorted(values) for field, values in sources.items()}
