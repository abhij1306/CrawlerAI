from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from app.models.crawl_run import CrawlRecord
from app.core.config.public_record_policy import (
    PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

EXPORT_RECORD_VERSION = "1"


class FieldProvenance(BaseModel):
    status: str = "found"
    value: Any = None
    sources: list[str] = Field(default_factory=list)
    selector_trace: dict[str, Any] | None = None
    winning_evidence_ids: list[str] = Field(default_factory=list)
    candidate_count: int = 0
    rejected_candidate_count: int = 0
    conflict_count: int = 0
    validation_finding_ids: list[str] = Field(default_factory=list)
    resolver_rule: str | None = None
    llm_used: bool = False

    @field_validator("sources", mode="before")
    @classmethod
    def _sources(cls, value: object) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("field provenance sources must be a list")
        return [str(item) for item in value if str(item or "").strip()]


class AcquisitionTrace(BaseModel):
    method: str = ""
    status_code: int | None = None
    final_url: str = ""
    blocked: bool = False
    adapter_name: str | None = None
    adapter_source_type: str | None = None
    network_payload_count: int = 0
    browser_diagnostics: dict[str, Any] = Field(default_factory=dict)


class ExtractionTrace(BaseModel):
    source: str = "extraction"
    confidence: dict[str, Any] = Field(default_factory=dict)
    self_heal: dict[str, Any] = Field(default_factory=dict)
    field_repair: dict[str, Any] = Field(default_factory=dict)
    manifest_trace: dict[str, Any] = Field(default_factory=dict)
    review_bucket: list[dict[str, Any]] = Field(default_factory=list)
    semantic: dict[str, Any] = Field(default_factory=dict)
    rejected_public_fields: dict[str, Any] = Field(default_factory=dict)
    dom_skip: dict[str, Any] = Field(default_factory=dict)
    completed_tiers: list[str] = Field(default_factory=list)
    validation_findings: list[dict[str, Any]] = Field(default_factory=list)
    transforms: list[dict[str, Any]] = Field(default_factory=list)


class ExportRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: str = EXPORT_RECORD_VERSION
    source_url: str
    data: dict[str, Any] = Field(default_factory=dict)
    acquisition: AcquisitionTrace = Field(default_factory=AcquisitionTrace)
    extraction: ExtractionTrace = Field(default_factory=ExtractionTrace)
    field_discovery: dict[str, FieldProvenance] = Field(default_factory=dict)

    @field_validator("source_url")
    @classmethod
    def _source_url(cls, value: str) -> str:
        text = str(value or "").strip()
        parsed = urlparse(text)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("source_url must be an absolute http(s) URL")
        return text

    def model_post_init(self, __context: Any) -> None:
        record_url = self.data.get("url")
        # Missing record URLs are intentional: skip URL parsing for partial records.
        if record_url in (None, ""):
            return
        parsed = urlparse(str(record_url))
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("record url must be an absolute http(s) URL")


def export_record_from_row(
    row: CrawlRecord,
    *,
    data: dict[str, object],
    source_trace: dict[str, object],
) -> ExportRecord:
    return ExportRecord.model_validate(
        {
            "source_url": row.source_url,
            "data": clean_export_data(data),
            "acquisition": source_trace.get("acquisition") or {},
            "extraction": source_trace.get("extraction") or {},
            "field_discovery": source_trace.get("field_discovery") or {},
        }
    )


def clean_export_data(data: dict) -> dict:
    """Strip empty/null values and internal keys from export data."""
    return {
        k: v
        for k, v in data.items()
        if (
            v not in (None, "", [], {})
            and not str(k).strip().startswith("_")
            and str(k).strip().lower() not in PUBLIC_RECORD_FALLBACK_INTERNAL_FIELDS
        )
    }
