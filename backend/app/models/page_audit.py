from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CompletedAtMixin,
    UpdatedAtMixin,
    USERS_FK,
)
from app.services.config.page_audit import PAGE_AUDIT_JOB_STATUS_QUEUED

PAGE_AUDIT_JOB_FK = "page_audit_jobs.id"


class PageAuditJob(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "page_audit_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey(USERS_FK, ondelete=CASCADE),
        index=True,
    )
    url: Mapped[str] = mapped_column(Text)
    context: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(
        String(32),
        default=PAGE_AUDIT_JOB_STATUS_QUEUED,
        index=True,
    )
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class PageAuditResult(UpdatedAtMixin, Base):
    __tablename__ = "page_audit_results"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(PAGE_AUDIT_JOB_FK, ondelete=CASCADE),
        unique=True,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text)
    report_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    markdown_report: Mapped[str] = mapped_column(Text, default="")
