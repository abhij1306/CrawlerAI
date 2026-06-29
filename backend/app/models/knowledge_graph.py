"""Knowledge Graph ORM models — the PostgreSQL graph foundation (Slice 5).

These six tables are the extraction-owned, cross-crawl knowledge store described
in `docs/feature specs/site-product-knowledge-graph.md` §4.2. They are written
*only* by the run-complete projector (Slices 6-8); extraction never touches
them. The vocabulary and bounds they consume live in
`app.core.config.knowledge_graph` — this module adds storage, not policy.

Identity is UUID throughout (entities are globally typed nodes; §4.2). Evidence
references the originating crawl run via `ON DELETE SET NULL` so bounded
provenance survives a crawl reset while the graph itself is preserved across the
application and Domain Memory resets and removed only by an explicit graph purge
(feature spec §8).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CRAWL_RUN_FK,
    SET_NULL,
    CreatedAtMixin,
    UpdatedAtMixin,
)

KG_ENTITY_FK = "kg_entities.id"
KG_CLAIM_FK = "kg_claims.id"
KG_RELATIONSHIP_FK = "kg_relationships.id"


def _utcnow() -> datetime:
    return datetime.now(UTC)


class KGSiteVersion(UpdatedAtMixin, Base):
    """Per-domain freeze anchor: current graph version and projection state."""

    __tablename__ = "kg_site_versions"
    __table_args__ = (Index("uq_kg_site_versions_domain", "domain", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    domain: Mapped[str] = mapped_column(String(255))
    current_version: Mapped[int] = mapped_column(Integer, default=1)
    projection_status: Mapped[str] = mapped_column(String(20), default="pending")
    last_projected_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
        index=True,
    )
    last_projected_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)


class KGEntity(CreatedAtMixin, Base):
    """Globally typed UUID node, unique on (entity_type, canonical_key)."""

    __tablename__ = "kg_entities"
    __table_args__ = (
        Index(
            "uq_kg_entities_type_key",
            "entity_type",
            "canonical_key",
            unique=True,
        ),
        Index("ix_kg_entities_entity_type", "entity_type"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_type: Mapped[str] = mapped_column(String(40))
    canonical_key: Mapped[str] = mapped_column(Text)
    canonical_name: Mapped[str] = mapped_column(Text, default="")
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="active")
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )


class KGRelationship(UpdatedAtMixin, Base):
    """Typed edge between two entities; indexed by source and by target."""

    __tablename__ = "kg_relationships"
    __table_args__ = (
        Index(
            "uq_kg_relationships_triple",
            "source_entity_id",
            "target_entity_id",
            "relationship_type",
            unique=True,
        ),
        Index("ix_kg_relationships_source", "source_entity_id"),
        Index("ix_kg_relationships_target", "target_entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(KG_ENTITY_FK, ondelete=CASCADE)
    )
    target_entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(KG_ENTITY_FK, ondelete=CASCADE)
    )
    relationship_type: Mapped[str] = mapped_column(String(40))
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, default=None
    )
    status: Mapped[str] = mapped_column(String(20), default="active")


class KGClaim(UpdatedAtMixin, Base):
    """Versioned fact preserving what was observed, not only the winning edge."""

    __tablename__ = "kg_claims"
    __table_args__ = (
        Index(
            "uq_kg_claims_entity_fact_hash",
            "entity_id",
            "fact_type",
            "value_hash",
            unique=True,
        ),
        Index("ix_kg_claims_entity_id", "entity_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    entity_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(KG_ENTITY_FK, ondelete=CASCADE)
    )
    fact_type: Mapped[str] = mapped_column(String(60))
    value: Mapped[dict] = mapped_column(JSONB, default=dict)
    value_hash: Mapped[str] = mapped_column(String(64))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    selection_origin: Mapped[str] = mapped_column(String(20), default="generic")


class KGAssertionEvidence(CreatedAtMixin, Base):
    """Bounded provenance for exactly one claim or relationship.

    `source_run_id` is `ON DELETE SET NULL` so retained evidence survives a
    crawl reset; the within-graph references cascade so an explicit purge is
    complete.
    """

    __tablename__ = "kg_assertion_evidence"
    __table_args__ = (
        CheckConstraint(
            "(claim_id IS NULL) <> (relationship_id IS NULL)",
            name="ck_kg_evidence_single_target",
        ),
        Index("ix_kg_assertion_evidence_claim_id", "claim_id"),
        Index("ix_kg_assertion_evidence_relationship_id", "relationship_id"),
        Index("ix_kg_assertion_evidence_source_run_id", "source_run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(KG_CLAIM_FK, ondelete=CASCADE),
        nullable=True,
    )
    relationship_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(KG_RELATIONSHIP_FK, ondelete=CASCADE),
        nullable=True,
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL),
        nullable=True,
    )
    collector: Mapped[str] = mapped_column(String(64), default="")
    locator: Mapped[str] = mapped_column(Text, default="")
    value_preview: Mapped[str] = mapped_column(Text, default="")
    directness: Mapped[str] = mapped_column(String(24), default="")
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    rejected: Mapped[bool] = mapped_column(default=False)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    properties: Mapped[dict] = mapped_column(JSONB, default=dict)


class KGExtractionContract(UpdatedAtMixin, Base):
    """One executable selection per (template, surface, canonical field)."""

    __tablename__ = "kg_extraction_contracts"
    __table_args__ = (
        Index(
            "uq_kg_extraction_contracts_scope",
            "template_id",
            "surface",
            "canonical_field",
            unique=True,
        ),
        Index("ix_kg_extraction_contracts_template_id", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(KG_ENTITY_FK, ondelete=CASCADE)
    )
    surface: Mapped[str] = mapped_column(String(40))
    canonical_field: Mapped[str] = mapped_column(String(128))
    candidates: Mapped[list] = mapped_column(JSONB, default=list)
    latest_values: Mapped[list] = mapped_column(JSONB, default=list)
    success_count: Mapped[int] = mapped_column(Integer, default=0)
    rejection_count: Mapped[int] = mapped_column(Integer, default=0)
    resolver_rule: Mapped[str] = mapped_column(Text, default="")
    selected_source: Mapped[str] = mapped_column(Text, default="")
    selection_origin: Mapped[str] = mapped_column(String(20), default="generic")
    selection_history: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(String(20), default="active")
