from __future__ import annotations

from sqlalchemy import Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CRAWL_RUN_FK,
    CompletedAtMixin,
    CreatedAtMixin,
    SET_NULL,
    USERS_FK,
    UpdatedAtMixin,
)
from app.services.config.product_intelligence import (
    PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_DISCOVERED,
    PRODUCT_INTELLIGENCE_JOB_STATUS_QUEUED,
    PRODUCT_INTELLIGENCE_REVIEW_PENDING,
)

PRODUCT_INTELLIGENCE_JOB_FK = "product_intelligence_jobs.id"
PRODUCT_INTELLIGENCE_SOURCE_PRODUCTS_FK = "product_intelligence_source_products.id"
PRODUCT_INTELLIGENCE_CANDIDATES_FK = "product_intelligence_candidates.id"
CRAWL_RECORD_FK = "crawl_records.id"


class ProductIntelligenceJob(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "product_intelligence_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(USERS_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    status: Mapped[str] = mapped_column(
        String(32),
        default=PRODUCT_INTELLIGENCE_JOB_STATUS_QUEUED,
        index=True,
    )
    options: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProductIntelligenceSourceProduct(CreatedAtMixin, Base):
    __tablename__ = "product_intelligence_source_products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(PRODUCT_INTELLIGENCE_JOB_FK, ondelete=CASCADE),
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
    brand: Mapped[str] = mapped_column(String(255), default="", index=True)
    normalized_brand: Mapped[str] = mapped_column(String(255), default="", index=True)
    title: Mapped[str] = mapped_column(Text, default="")
    sku: Mapped[str] = mapped_column(String(255), default="")
    mpn: Mapped[str] = mapped_column(String(255), default="")
    gtin: Mapped[str] = mapped_column(String(255), default="")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="")
    image_url: Mapped[str] = mapped_column(Text, default="")
    is_private_label: Mapped[bool] = mapped_column(default=False)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProductIntelligenceCandidate(UpdatedAtMixin, Base):
    __tablename__ = "product_intelligence_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(PRODUCT_INTELLIGENCE_JOB_FK, ondelete=CASCADE),
        index=True,
    )
    source_product_id: Mapped[int] = mapped_column(
        ForeignKey(PRODUCT_INTELLIGENCE_SOURCE_PRODUCTS_FK, ondelete=CASCADE),
        index=True,
    )
    candidate_crawl_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    source_type: Mapped[str] = mapped_column(String(64), default="")
    query_used: Mapped[str] = mapped_column(Text, default="")
    search_rank: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(
        String(32),
        default=PRODUCT_INTELLIGENCE_CANDIDATE_STATUS_DISCOVERED,
        index=True,
    )
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class ProductIntelligenceMatch(UpdatedAtMixin, Base):
    __tablename__ = "product_intelligence_matches"
    __table_args__ = (
        Index(
            "ix_product_intelligence_matches_job_source",
            "job_id",
            "source_product_id",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey(PRODUCT_INTELLIGENCE_JOB_FK, ondelete=CASCADE),
    )
    source_product_id: Mapped[int] = mapped_column(
        ForeignKey(PRODUCT_INTELLIGENCE_SOURCE_PRODUCTS_FK, ondelete=CASCADE),
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey(PRODUCT_INTELLIGENCE_CANDIDATES_FK, ondelete=CASCADE),
        index=True,
    )
    candidate_record_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RECORD_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    score: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    score_label: Mapped[str] = mapped_column(String(32), default="")
    review_status: Mapped[str] = mapped_column(
        String(32),
        default=PRODUCT_INTELLIGENCE_REVIEW_PENDING,
        index=True,
    )
    source_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    candidate_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(16), default="")
    availability: Mapped[str] = mapped_column(Text, default="")
    candidate_url: Mapped[str] = mapped_column(Text, default="")
    candidate_domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    score_reasons: Mapped[dict] = mapped_column(JSONB, default=dict)
    llm_enrichment: Mapped[dict] = mapped_column(JSONB, default=dict)
