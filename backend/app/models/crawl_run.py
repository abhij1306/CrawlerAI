from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, cast
import uuid

from sqlalchemy import (
    CheckConstraint,
    CursorResult,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    or_,
    text,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config import settings
from app.core.config.runtime_settings import (
    CELERY_TASK_ID_KEY,
    crawler_runtime_settings,
)
from app.core.database import Base
from app.models.crawl_domain import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    CrawlStatus,
    normalize_status,
)
from app.models.crawl_settings import CrawlRunSettings
from app.core.config.data_enrichment import DATA_ENRICHMENT_STATUS_UNENRICHED
from app.core.db_utils import mapping_or_empty
from app.core.shared.run_summary import merge_run_summary_patch

CRAWL_RUN_FK = "crawl_runs.id"
CRAWL_URL_RESULT_FK = "crawl_url_results.id"
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
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'paused', 'completed', 'killed', "
            "'failed', 'proxy_exhausted')",
            name="ck_crawl_runs_status",
        ),
        Index("ix_crawl_runs_user_created_at", "user_id", text("created_at DESC")),
        Index("ix_crawl_runs_status_created_at", "status", "created_at"),
        Index(
            "ix_crawl_runs_active_created_at",
            "created_at",
            postgresql_where=text("status IN ('pending', 'running', 'paused')"),
        ),
    )

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
    extraction_release_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    last_claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    run_event_sequence: Mapped[int] = mapped_column(
        Integer,
        default=0,
        server_default=text("0"),
        nullable=False,
    )

    @property
    def status_value(self) -> CrawlStatus:
        return normalize_status(self.status)

    @property
    def settings_view(self) -> CrawlRunSettings:
        return CrawlRunSettings.from_value(self.settings)

    def is_active(self) -> bool:
        return self.status_value in ACTIVE_STATUSES

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


_CLAIMABLE_STATUS_VALUES = (CrawlStatus.PENDING.value, CrawlStatus.RUNNING.value)
TERMINAL_STATUS_VALUES = tuple(sorted(status.value for status in TERMINAL_STATUSES))


class RunClaimLostError(Exception):
    """The current executor lost the run's queue claim to a newer owner."""


def checkpoint_status_stops_run(status_value: str | None) -> bool:
    # Run deleted or externally terminated/paused: stop without writing further
    # state; the owning writer of that status finalizes it.
    return (
        status_value is None
        or status_value in TERMINAL_STATUS_VALUES
        or status_value == CrawlStatus.PAUSED.value
    )


def _run_lease_seconds() -> float:
    configured = max(0.0, float(settings.run_claim_lease_seconds or 0))
    # A lease must outlive the slowest allowed single-URL processing window,
    # otherwise a healthy executor looks dead mid-URL.
    url_window = 2 * max(
        0.0, float(crawler_runtime_settings.max_url_process_timeout_seconds)
    )
    return max(configured, url_window, 60.0)


def run_dispatch_token(run: CrawlRun) -> str:
    """Owner identity for claiming: the dispatch token written by the dispatcher.

    Redelivered Celery tasks keep the same task id, so a redelivery is refused
    while the original execution holds a live lease; a fresh dispatch (resume,
    retry) writes a new token and may take over from a stale or dead owner.
    """
    token = str(run.get_summary(CELERY_TASK_ID_KEY) or "").strip()
    return token or f"manual-{uuid.uuid4().hex}"


async def claim_run(session: AsyncSession, *, run_id: int, owner: str) -> bool:
    """Atomically claim a run for this owner; False when a live same-token owner exists."""
    now = datetime.now(UTC)
    stmt = (
        update(CrawlRun)
        .where(CrawlRun.id == run_id)
        .where(CrawlRun.status.in_(_CLAIMABLE_STATUS_VALUES))
        .where(
            or_(
                CrawlRun.queue_owner.is_(None),
                CrawlRun.queue_owner != owner,
                CrawlRun.lease_expires_at.is_(None),
                CrawlRun.lease_expires_at <= now,
            )
        )
        .values(
            queue_owner=owner,
            lease_expires_at=now + timedelta(seconds=_run_lease_seconds()),
            last_claimed_at=now,
            last_heartbeat_at=now,
            claim_count=CrawlRun.claim_count + 1,
        )
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(stmt))
    return result.rowcount == 1


async def renew_run_lease(session: AsyncSession, *, run_id: int, owner: str) -> None:
    """Refresh the lease/heartbeat, but only while this owner still holds the claim."""
    now = datetime.now(UTC)
    stmt = (
        update(CrawlRun)
        .where(CrawlRun.id == run_id)
        .where(CrawlRun.queue_owner == owner)
        .values(
            lease_expires_at=now + timedelta(seconds=_run_lease_seconds()),
            last_heartbeat_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(stmt))
    if result.rowcount != 1:
        raise RunClaimLostError(f"Run {run_id} queue claim lost to a newer owner")


async def release_run_lease(session: AsyncSession, *, run_id: int, owner: str) -> bool:
    """Release the claim on run stop; False when the claim is no longer ours."""
    stmt = (
        update(CrawlRun)
        .where(CrawlRun.id == run_id)
        .where(CrawlRun.queue_owner == owner)
        .values(
            queue_owner=None,
            lease_expires_at=None,
            last_heartbeat_at=datetime.now(UTC),
        )
        .execution_options(synchronize_session=False)
    )
    result = cast(CursorResult[Any], await session.execute(stmt))
    return result.rowcount == 1


class CrawlUrlResult(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "crawl_url_results"
    __table_args__ = (
        Index(
            "uq_crawl_url_results_identity",
            "run_id",
            "normalized_url",
            "surface",
            "generation",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), index=True
    )
    requested_url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text)
    final_url: Mapped[str] = mapped_column(Text, default="")
    surface: Mapped[str] = mapped_column(String(40))
    generation: Mapped[int] = mapped_column(Integer, default=1)
    acquisition_outcome: Mapped[str] = mapped_column(String(24), default="empty")
    verdict: Mapped[str] = mapped_column(String(24), default="empty", index=True)
    extraction_version: Mapped[str] = mapped_column(String(32), default="extraction.v2")
    bundle_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manifest_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    extraction_manifest_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True, index=True
    )
    record_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class CrawlRecord(CreatedAtMixin, Base):
    __tablename__ = "crawl_records"
    __table_args__ = (
        CheckConstraint(
            "enrichment_status IN ('unenriched', 'pending', 'running', "
            "'enriched', 'degraded', 'failed')",
            name="ck_crawl_records_enrichment_status",
        ),
        Index("ix_crawl_records_run_created_id", "run_id", "created_at", "id"),
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
    url_result_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_URL_RESULT_FK, ondelete=CASCADE),
        nullable=True,
        index=True,
    )
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


class RunEvent(CreatedAtMixin, Base):
    __tablename__ = "run_events"
    __table_args__ = (
        CheckConstraint("sequence > 0", name="ck_run_events_sequence_positive"),
        CheckConstraint(
            "stage IS NULL OR stage IN ('acquisition', 'extraction', 'normalization', 'persistence')",
            name="ck_run_events_stage",
        ),
        CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_run_events_severity",
        ),
        CheckConstraint(
            "outcome IN ('progress', 'succeeded', 'partial', 'failed', 'blocked', "
            "'skipped', 'cancelled', 'requested', 'limited')",
            name="ck_run_events_outcome",
        ),
        CheckConstraint(
            "(url IS NULL) = (url_scope_id IS NULL)",
            name="ck_run_events_url_scope",
        ),
        UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
        Index(
            "ix_run_events_run_url_scope_sequence",
            "run_id",
            "url_scope_id",
            "sequence",
            postgresql_where=text("url_scope_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE))
    sequence: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(64))
    stage: Mapped[str | None] = mapped_column(String(64), nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    url_scope_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    severity: Mapped[str] = mapped_column(String(20))
    outcome: Mapped[str] = mapped_column(String(64))
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    facts: Mapped[dict] = mapped_column(JSONB, default=dict)
