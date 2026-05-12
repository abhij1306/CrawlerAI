from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import CASCADE, CRAWL_RUN_FK, UpdatedAtMixin


class ReviewPromotion(UpdatedAtMixin, Base):
    __tablename__ = "review_promotions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), index=True
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)
    surface: Mapped[str] = mapped_column(String(40))
    approved_schema: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
    field_mapping: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSONB), default=dict)
