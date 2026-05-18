from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CompletedAtMixin,
    CreatedAtMixin,
    SET_NULL,
    USERS_FK,
    UpdatedAtMixin,
)
from app.services.config.ucp_audit import UCP_AUDIT_JOB_STATUS_QUEUED

UCP_AUDIT_JOB_FK = "ucp_audit_jobs.id"


class UCPAuditJob(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "ucp_audit_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(USERS_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        String(32),
        default=UCP_AUDIT_JOB_STATUS_QUEUED,
        index=True,
    )
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class UCPAuditPageResult(CreatedAtMixin, Base):
    __tablename__ = "ucp_audit_page_results"
    __table_args__ = (
        UniqueConstraint("job_id", "url", name="uq_ucp_audit_page_results_job_url"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(UCP_AUDIT_JOB_FK, ondelete=CASCADE),
        index=True,
    )
    url: Mapped[str] = mapped_column(Text)
    acquisition_mode: Mapped[str] = mapped_column(String(32))
    dimension_payloads: Mapped[dict] = mapped_column(JSONB, default=dict)
    findings: Mapped[list] = mapped_column(JSONB, default=list)


class UCPAuditReport(UpdatedAtMixin, Base):
    __tablename__ = "ucp_audit_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(UCP_AUDIT_JOB_FK, ondelete=CASCADE),
        unique=True,
        index=True,
    )
    overall_score: Mapped[int] = mapped_column(Integer, default=0)
    dimension_scores: Mapped[list] = mapped_column(JSONB, default=list)
    findings: Mapped[list] = mapped_column(JSONB, default=list)
    report_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    markdown_report: Mapped[str] = mapped_column(Text, default="")
