from __future__ import annotations

import json
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from app.core.config.evaluation import (
    GENERALIZED_EXTRACTION_LLM_TASK,
    GENERALIZED_EXTRACTION_RESPONSE_SCHEMA_VERSION,
    GROUNDED_REPAIR_LLM_TASK,
)
from app.extraction.contracts import FACT_TYPES


class _ProductIntelligenceEnrichmentPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    normalized_title: str = ""
    style_name: str = ""
    model_name: str = ""
    inferred_attributes: dict[str, Any] = Field(default_factory=dict)
    suggested_score: float = Field(default=0.0, ge=0.0, le=1.0)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    match_explanation: str = ""
    mismatch_risks: list[str] = Field(default_factory=list)
    reason_updates: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("reason_updates")
    @classmethod
    def _validate_reason_updates(
        cls, value: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        allowed = {
            "reason_name",
            "reason_code",
            "description",
            "source",
            "timestamp",
            "conflicting_value",
            "resolution_action",
        }
        for item in value:
            unknown = set(item) - allowed
            if unknown:
                raise ValueError(
                    f"unknown reason_updates keys: {', '.join(sorted(unknown))}"
                )
        return value


class _ProductIntelligenceBrandInferencePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    brand: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class _DataEnrichmentSemanticPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category_path: str | None = None
    color_family: str | None = None
    size_normalized: list[str] | None = None
    size_system: str | None = None
    gender_normalized: str | None = None
    materials_normalized: list[str] | None = None
    availability_normalized: str | None = None
    intent_attributes: list[str] | None = None
    audience: list[str] | None = None
    style_tags: list[str] | None = None
    ai_discovery_tags: list[str] | None = None
    suggested_bundles: list[str] | None = None


class _GeneralizedExtractionPredictionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prediction_id: str = Field(min_length=1)
    source_path: str = Field(min_length=1)
    fact_type: str = Field(min_length=1)
    raw_value: str | int | float | bool | None
    value: str | int | float | bool | None
    subject_id: str = Field(default="generalized-product-1", min_length=1)
    subject_scope: str = "product"
    confidence: float = Field(ge=0.0, le=1.0)
    group_id: str | None = None
    parent_subject_id: str | None = None
    relation_type: str | None = None

    @field_validator("fact_type")
    @classmethod
    def _validate_fact_type(cls, value: str) -> str:
        if value not in FACT_TYPES:
            raise ValueError(f"unsupported fact_type: {value}")
        return value

    @field_validator("subject_scope")
    @classmethod
    def _validate_subject_scope(cls, value: str) -> str:
        allowed = {"document", "product", "variant", "offer", "asset", "job", "unknown"}
        if value not in allowed:
            raise ValueError(f"unsupported subject_scope: {value}")
        return value

    @field_validator("relation_type")
    @classmethod
    def _validate_relation_type(cls, value: str | None) -> str | None:
        if value is None:
            return None
        allowed = {
            "product_variant",
            "product_offer",
            "variant_offer",
            "product_asset",
            "variant_asset",
            "job_asset",
        }
        if value not in allowed:
            raise ValueError(f"unsupported relation_type: {value}")
        return value


class _GeneralizedExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = GENERALIZED_EXTRACTION_RESPONSE_SCHEMA_VERSION
    predictions: list[_GeneralizedExtractionPredictionPayload] = Field(
        default_factory=list
    )

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: str) -> str:
        if value != GENERALIZED_EXTRACTION_RESPONSE_SCHEMA_VERSION:
            raise ValueError("unsupported generalized extraction schema version")
        return value


_PAYLOAD_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "product_intelligence_enrichment": TypeAdapter(
        _ProductIntelligenceEnrichmentPayload
    ),
    "product_intelligence_brand_inference": TypeAdapter(
        _ProductIntelligenceBrandInferencePayload
    ),
    "data_enrichment_semantic": TypeAdapter(_DataEnrichmentSemanticPayload),
    GENERALIZED_EXTRACTION_LLM_TASK: TypeAdapter(_GeneralizedExtractionPayload),
}
SUPPORTED_TASK_TYPES = (*_PAYLOAD_ADAPTERS.keys(), GROUNDED_REPAIR_LLM_TASK)


def parse_payload(raw_text: str, *, response_type: str) -> dict | list | None:
    if response_type == "array":
        return _parse_json_array(raw_text)
    return _parse_json_object(raw_text)


def validate_task_payload(
    task_type: str,
    payload: object,
) -> tuple[object, str | None]:
    adapter = _PAYLOAD_ADAPTERS.get(str(task_type or "").strip())
    if adapter is None:
        return payload, None
    try:
        validated = adapter.validate_python(payload)
    except ValidationError as exc:
        return payload, _format_validation_error(task_type, exc)
    return validated.model_dump() if isinstance(
        validated, BaseModel
    ) else validated, None


def _format_validation_error(task_type: str, exc: ValidationError) -> str:
    error = exc.errors()[0]
    location = ".".join(str(part) for part in error.get("loc", ()) if part != "root")
    detail = str(error.get("msg") or "invalid payload")
    suffix = f" at {location}" if location else ""
    return f"{task_type} payload validation failed{suffix}: {detail}"


def _parse_json_object(raw_text: str) -> dict | None:
    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end < start:
        return None
    try:
        payload = json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _parse_json_array(raw_text: str) -> list | None:
    start = raw_text.find("[")
    end = raw_text.rfind("]")
    if start == -1 or end < start:
        return None
    try:
        payload = json.loads(raw_text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, list) else None
