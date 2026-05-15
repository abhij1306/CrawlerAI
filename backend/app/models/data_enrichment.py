from __future__ import annotations

from sqlalchemy import ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CRAWL_RUN_FK,
    CompletedAtMixin,
    SET_NULL,
    USERS_FK,
    UpdatedAtMixin,
)
from app.services.config.data_enrichment import DATA_ENRICHMENT_STATUS_PENDING

DATA_ENRICHMENT_JOBS_FK = "data_enrichment_jobs.id"
CRAWL_RECORD_FK = "crawl_records.id"


class DataEnrichmentJob(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "data_enrichment_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey(USERS_FK, ondelete=CASCADE), index=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=DATA_ENRICHMENT_STATUS_PENDING,
        index=True,
    )
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class EnrichedProduct(UpdatedAtMixin, Base):
    __tablename__ = "enriched_products"
    __table_args__ = (
        Index(
            "uq_enriched_products_source_record",
            "source_record_id",
            unique=True,
            postgresql_where=text("source_record_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(DATA_ENRICHMENT_JOBS_FK, ondelete=CASCADE),
        index=True,
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    source_record_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RECORD_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    source_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(
        String(32),
        default=DATA_ENRICHMENT_STATUS_PENDING,
        index=True,
    )
    price_normalized: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    color_family: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_normalized: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    size_system: Mapped[str | None] = mapped_column(String(32), nullable=True)
    gender_normalized: Mapped[str | None] = mapped_column(String(32), nullable=True)
    materials_normalized: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    availability_normalized: Mapped[str | None] = mapped_column(
        String(32), nullable=True
    )
    seo_keywords: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    category_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    taxonomy_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    intent_attributes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    audience: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    style_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    ai_discovery_tags: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    suggested_bundles: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    diagnostics: Mapped[dict] = mapped_column(JSONB, default=dict)
