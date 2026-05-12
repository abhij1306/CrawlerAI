from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_domain import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    CrawlStatus,
    normalize_status,
    transition_status,
)
from app.models.crawl_settings import CrawlRunSettings
from app.services.config.data_enrichment import DATA_ENRICHMENT_STATUS_UNENRICHED
from app.services.db_utils import mapping_or_empty
from app.services.run_summary import merge_run_summary_patch

CRAWL_RUN_FK = "crawl_runs.id"
USERS_FK = "users.id"
CASCADE = "CASCADE"
SET_NULL = "SET NULL"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class UpdatedAtMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
    )


class CompletedAtMixin:
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )


class CrawlRun(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "crawl_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey(USERS_FK), index=True)
    run_type: Mapped[str] = mapped_column(String(20))
    url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    surface: Mapped[str] = mapped_column(String(40))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_fields: Mapped[list] = mapped_column(JSONB, default=list)
    result_summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    queue_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claim_count: Mapped[int] = mapped_column(Integer, default=0)
    last_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    @property
    def status_value(self) -> CrawlStatus:
        return normalize_status(self.status)

    @property
    def settings_view(self) -> CrawlRunSettings:
        return CrawlRunSettings.from_value(self.settings)

    def is_active(self) -> bool:
        return self.status_value in ACTIVE_STATUSES

    def is_terminal(self) -> bool:
        return self.status_value in TERMINAL_STATUSES

    def can_transition_to(self, target: str | CrawlStatus) -> bool:
        try:
            transition_status(self.status, target)
        except ValueError:
            return False
        return True

    def set_status(self, target: str | CrawlStatus) -> CrawlStatus:
        next_status = transition_status(self.status, target)
        self.status = next_status.value
        return next_status

    def get_setting(self, key: str, default: object = None) -> object:
        settings = self.settings if isinstance(self.settings, Mapping) else {}
        return settings.get(key, default)

    def update_settings(self, **updates: object) -> dict[str, object]:
        merged = dict(self.settings if isinstance(self.settings, Mapping) else {})
        merged.update(updates)
        self.settings = merged
        return merged

    def summary_dict(self) -> dict[str, object]:
        return mapping_or_empty(self.result_summary)

    def get_summary(self, key: str, default: object = None) -> object:
        return self.summary_dict().get(key, default)

    def update_summary(self, **updates: object) -> dict[str, object]:
        merged = self.summary_dict()
        merged.update(updates)
        self.result_summary = merged
        return merged

    def remove_summary_keys(self, *keys: str) -> dict[str, object]:
        merged = self.summary_dict()
        for key in keys:
            merged.pop(key, None)
        self.result_summary = merged
        return merged

    def merge_summary_patch(self, patch: Mapping[str, object]) -> dict[str, object]:
        merged = merge_run_summary_patch(self.summary_dict(), dict(patch))
        self.result_summary = merged
        return merged

    def apply_batch_progress_patch(
        self, patch: Mapping[str, object]
    ) -> dict[str, object]:
        return self.merge_summary_patch(patch)


class CrawlRecord(CreatedAtMixin, Base):
    __tablename__ = "crawl_records"
    __table_args__ = (
        Index(
            "uq_crawl_records_run_identity",
            "run_id",
            "url_identity_key",
            unique=True,
            postgresql_where=text("url_identity_key IS NOT NULL"),
        ),
        Index("ix_crawl_records_run_content_fp", "run_id", "content_fingerprint"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), index=True
    )
    source_url: Mapped[str] = mapped_column(Text)
    url_identity_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    data: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    discovered_data: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_trace: Mapped[dict] = mapped_column(JSONB, default=dict)
    raw_html_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    enrichment_status: Mapped[str] = mapped_column(
        String(32),
        default=DATA_ENRICHMENT_STATUS_UNENRICHED,
        server_default=DATA_ENRICHMENT_STATUS_UNENRICHED,
        nullable=False,
        index=True,
    )
    enriched_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )


class CrawlLog(CreatedAtMixin, Base):
    __tablename__ = "crawl_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), index=True
    )
    level: Mapped[str] = mapped_column(String(20), default="info")
    message: Mapped[str] = mapped_column(Text)
