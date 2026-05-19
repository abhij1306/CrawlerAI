from __future__ import annotations

from decimal import Decimal
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.config.orchestration_templates import ORCHESTRATION_DEFAULT_TRACKED_FIELDS


class OrchestrationProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    description: str = ""
    competitors: list[str] = Field(default_factory=list)
    category: str = ""
    tracked_fields: list[str] = Field(
        default_factory=lambda: list(ORCHESTRATION_DEFAULT_TRACKED_FIELDS)
    )

    @field_validator("competitors", "tracked_fields")
    @classmethod
    def _clean_list(cls, value: list[str]) -> list[str]:
        items: list[str] = []
        seen: set[str] = set()
        for item in value:
            text = str(item or "").strip()
            if text and text not in seen:
                items.append(text)
                seen.add(text)
        return items


class OrchestrationProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    name: str
    description: str
    competitors: list[str]
    category: str
    tracked_fields: list[str]
    archived: bool
    created_at: datetime
    updated_at: datetime


class OrchestrationTemplateResponse(BaseModel):
    id: str
    display_name: str
    description: str
    version: str
    intent_inputs: list[dict[str, Any]]
    pipeline_defaults: dict[str, Any]
    advanced_overrides: list[str]
    steps: list[dict[str, Any]]
    continuations: list[dict[str, Any]] = Field(default_factory=list)


class OrchestrationWorkflowCreate(BaseModel):
    template_id: str
    project_id: int
    label: str = Field(min_length=1, max_length=180)
    intent_inputs: dict[str, Any] = Field(default_factory=dict)
    advanced_overrides: dict[str, Any] = Field(default_factory=dict)


class OrchestrationStepRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    workflow_id: int
    step_id: str
    step_type: str
    status: str
    run_id: int | None = None
    inputs: dict[str, Any]
    outputs: dict[str, Any]
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class OrchestrationWorkflowResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    project_id: int
    template_id: str
    template_version: str
    label: str
    status: str
    intent_inputs: dict[str, Any]
    advanced_overrides: dict[str, Any]
    pipeline_config: dict[str, Any]
    summary: dict[str, Any]
    monitor_id: int | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    steps: list[OrchestrationStepRunResponse] = Field(default_factory=list)


class OrchestrationPromoteRequest(BaseModel):
    schedule_interval_hours: int = Field(default=168, ge=1)
    retention_days: int = Field(default=30, ge=1, le=90)
    priority: Literal["on_demand", "priority", "background"] = "background"


class OrchestrationPromoteResponse(BaseModel):
    workflow_id: int
    monitor_id: int
    url_count: int
    tracked_fields: list[str]


class PriceComparisonRow(BaseModel):
    record_id: int
    run_id: int
    product: str
    brand: str
    domain: str
    price: Decimal | None = None
    was_price: Decimal | None = None
    currency: str | None = None
    availability: str | None = None
    source_url: str


class PriceComparisonResponse(BaseModel):
    workflow_id: int
    project_id: int
    detail_run_id: int | None = None
    rows: list[PriceComparisonRow]
    export_csv_url: str | None = None
    export_json_url: str | None = None
    crawl_studio_url: str | None = None
