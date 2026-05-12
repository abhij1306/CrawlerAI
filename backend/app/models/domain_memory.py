from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CRAWL_RUN_FK,
    SET_NULL,
    CreatedAtMixin,
    UpdatedAtMixin,
)


class DomainMemory(UpdatedAtMixin, Base):
    __tablename__ = "domain_memory"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255), index=True)
    surface: Mapped[str] = mapped_column(String(40), index=True)
    platform: Mapped[str | None] = mapped_column(String(40), nullable=True)
    selectors: Mapped[dict] = mapped_column(JSONB, default=dict)


class DomainRunProfile(UpdatedAtMixin, Base):
    __tablename__ = "domain_run_profiles"
    __table_args__ = (
        Index(
            "uq_domain_run_profiles_domain_surface",
            "domain",
            "surface",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255))
    surface: Mapped[str] = mapped_column(String(40))
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)


class DomainCookieMemory(UpdatedAtMixin, Base):
    __tablename__ = "domain_cookie_memory"
    __table_args__ = (
        Index(
            "uq_domain_cookie_memory_domain",
            "domain",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255))
    storage_state: Mapped[dict] = mapped_column(JSONB, default=dict)
    state_fingerprint: Mapped[str] = mapped_column(String(128), default="")


class DomainFieldFeedback(CreatedAtMixin, Base):
    __tablename__ = "domain_field_feedback"
    __table_args__ = (
        Index(
            "ix_domain_field_feedback_domain_surface",
            "domain",
            "surface",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    domain: Mapped[str] = mapped_column(String(255))
    surface: Mapped[str] = mapped_column(String(40), index=True)
    field_name: Mapped[str] = mapped_column(String(128), index=True)
    action: Mapped[str] = mapped_column(String(32))
    source_kind: Mapped[str] = mapped_column(String(32))
    source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class HostProtectionMemory(UpdatedAtMixin, Base):
    __tablename__ = "host_protection_memory"
    __table_args__ = (
        Index(
            "uq_host_protection_memory_host",
            "host",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    host: Mapped[str] = mapped_column(String(255))
    hard_block_count: Mapped[int] = mapped_column(Integer, default=0)
    browser_first_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    proxy_required_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_block_vendor: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_block_status_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_block_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_blocked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    last_success_method: Mapped[str | None] = mapped_column(String(32), nullable=True)
