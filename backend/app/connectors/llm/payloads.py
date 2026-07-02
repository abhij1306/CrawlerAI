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

from app.core.config.evaluation import GROUNDED_REPAIR_LLM_TASK


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


_PAYLOAD_ADAPTERS: dict[str, TypeAdapter[Any]] = {
    "product_intelligence_enrichment": TypeAdapter(
        _ProductIntelligenceEnrichmentPayload
    ),
    "product_intelligence_brand_inference": TypeAdapter(
        _ProductIntelligenceBrandInferencePayload
    ),
    "data_enrichment_semantic": TypeAdapter(_DataEnrichmentSemanticPayload),
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
