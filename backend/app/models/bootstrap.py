"""Durable one-shot bootstrap markers."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class BootstrapRecord(Base):
    __tablename__ = "bootstrap_records"

    name: Mapped[str] = mapped_column(String(64), primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC), nullable=False
    )
