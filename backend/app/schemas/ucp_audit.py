from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.config import ucp_audit as config


class UCPAuditOptions(BaseModel):
    sample_size: int = Field(
        default=config.UCP_AUDIT_DEFAULT_SAMPLE_SIZE,
        ge=1,
        le=config.UCP_AUDIT_MAX_SAMPLE_SIZE,
    )
    include_agent_delta: bool = config.UCP_AUDIT_DEFAULT_INCLUDE_AGENT_DELTA
    llm_enabled: bool = False
    report_formats: list[str] = Field(
        default_factory=lambda: list(config.UCP_AUDIT_DEFAULT_REPORT_FORMATS)
    )


class UCPAuditJobCreate(BaseModel):
    domain: str = Field(min_length=1, max_length=255)
    options: UCPAuditOptions = Field(default_factory=UCPAuditOptions)

    @field_validator("domain")
    @classmethod
    def domain_must_have_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("domain is required")
        return text


class UCPAuditJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    domain: str
    status: str
    options: dict
    summary: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class UCPAuditPageResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    url: str
    acquisition_mode: str
    dimension_payloads: dict
    findings: list[dict[str, Any]]
    created_at: datetime


class UCPAuditReportResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    overall_score: int
    dimension_scores: list
    findings: list[dict[str, Any]]
    report_json: dict
    markdown_report: str
    created_at: datetime
    updated_at: datetime


class UCPAuditJobDetailResponse(BaseModel):
    job: UCPAuditJobResponse
    page_results: list[UCPAuditPageResultResponse] = Field(default_factory=list)
    report: UCPAuditReportResponse | None = None
