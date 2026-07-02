from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import UpdatedAtMixin

DOMAIN_RUN_PROFILE_UNIQUE_CONSTRAINT = "uq_domain_run_profiles_domain_surface"


class DomainRunProfile(UpdatedAtMixin, Base):
    __tablename__ = "domain_run_profiles"
    __table_args__ = (
        Index(
            DOMAIN_RUN_PROFILE_UNIQUE_CONSTRAINT,
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
