from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.config import page_audit as config


class PageAuditJobCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    context: Literal["auto", "generic", "ecommerce"] = cast(
        Literal["auto", "generic", "ecommerce"],
        config.PAGE_AUDIT_CONTEXT_AUTO,
    )

    @field_validator("url")
    @classmethod
    def url_must_have_text(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("url is required")
        return text


class PageAuditJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int
    url: str
    context: str
    status: str
    options: dict
    summary: dict
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class PageAuditResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    url: str
    report_json: dict[str, Any]
    markdown_report: str
    created_at: datetime
    updated_at: datetime


class PageAuditJobDetailResponse(BaseModel):
    job: PageAuditJobResponse
    result: PageAuditResultResponse | None = None
