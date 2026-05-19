from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import CreatedAtMixin, SET_NULL, USERS_FK
from app.models.monitor import MONITOR_JOB_FK


class InAppNotification(CreatedAtMixin, Base):
    __tablename__ = "in_app_notifications"
    __table_args__ = (
        Index("ix_in_app_notifications_user_read_created", "user_id", "read", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(USERS_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    monitor_id: Mapped[int] = mapped_column(
        ForeignKey(MONITOR_JOB_FK, ondelete="CASCADE"), index=True
    )
    event_count: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text)
    read: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
