from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.config.extraction_memory import EXTRACTION_MEMORY_STATUS_ACTIVE
from app.core.database import Base
from app.models.crawl_run import (
    CASCADE,
    CRAWL_RUN_FK,
    SET_NULL,
    CreatedAtMixin,
    UpdatedAtMixin,
)

TEMPLATE_FK = "extraction_templates.id"
RECIPE_FK = "extraction_recipes.id"
COMPILED_RECIPE_FK = "compiled_extraction_recipes.id"
RELEASE_FK = "extraction_release_snapshots.id"


class ExtractionTemplate(UpdatedAtMixin, Base):
    """Structural page template. Values and product identities never belong here."""

    __tablename__ = "extraction_templates"
    __table_args__ = (
        Index(
            "uq_extraction_templates_fingerprint",
            "domain",
            "surface",
            "fingerprint",
            unique=True,
        ),
        Index("ix_extraction_templates_domain_surface", "domain", "surface"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    domain: Mapped[str] = mapped_column(String(255))
    surface: Mapped[str] = mapped_column(String(40))
    fingerprint: Mapped[str] = mapped_column(String(128))
    route_pattern: Mapped[str] = mapped_column(Text, default="")
    tech_signals: Mapped[list] = mapped_column(JSONB, default=list)
    status: Mapped[str] = mapped_column(
        String(24), default=EXTRACTION_MEMORY_STATUS_ACTIVE
    )
    last_seen_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL), nullable=True
    )


class ExtractionRecipe(UpdatedAtMixin, Base):
    """Human-readable recipe layer owned by exactly one structural template."""

    __tablename__ = "extraction_recipes"
    __table_args__ = (
        Index(
            "uq_extraction_recipes_scope", "template_id", "layer", "kind", unique=True
        ),
        Index("ix_extraction_recipes_template_id", "template_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(TEMPLATE_FK, ondelete=CASCADE)
    )
    layer: Mapped[str] = mapped_column(String(24))
    kind: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    locale_policy_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(
        String(24), default=EXTRACTION_MEMORY_STATUS_ACTIVE
    )


class CompiledExtractionRecipe(CreatedAtMixin, Base):
    """Immutable bounded runtime form produced from an ExtractionRecipe."""

    __tablename__ = "compiled_extraction_recipes"
    __table_args__ = (
        Index(
            "uq_compiled_extraction_recipes_checksum",
            "recipe_id",
            "checksum",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    recipe_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey(RECIPE_FK, ondelete=CASCADE), index=True
    )
    compiler_version: Mapped[str] = mapped_column(String(32))
    checksum: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(
        String(24), default=EXTRACTION_MEMORY_STATUS_ACTIVE
    )


class ExtractionReleaseSnapshot(CreatedAtMixin, Base):
    """Immutable recipe release frozen for one crawl run."""

    __tablename__ = "extraction_release_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), nullable=True, unique=True
    )
    domain: Mapped[str] = mapped_column(String(255))
    surface: Mapped[str] = mapped_column(String(40))
    release_version: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class ExtractionManifest(CreatedAtMixin, Base):
    """Resolved recipe/template context for one URL result."""

    __tablename__ = "extraction_manifests"
    __table_args__ = (
        Index("uq_extraction_manifests_url_result", "url_result_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    run_id: Mapped[int] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=CASCADE), index=True
    )
    url_result_id: Mapped[int] = mapped_column(
        ForeignKey("crawl_url_results.id", ondelete=CASCADE)
    )
    release_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(RELEASE_FK, ondelete=SET_NULL), nullable=True
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(TEMPLATE_FK, ondelete=SET_NULL), nullable=True
    )
    compiled_recipe_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(COMPILED_RECIPE_FK, ondelete=SET_NULL), nullable=True
    )
    manifest_version: Mapped[str] = mapped_column(String(32))
    locale_policy_ref: Mapped[str | None] = mapped_column(String(128), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class ExtractionOperatorLabel(CreatedAtMixin, Base):
    """Operator decision. Covers review promotion and grounded field feedback."""

    __tablename__ = "extraction_operator_labels"
    __table_args__ = (
        Index("ix_extraction_operator_labels_scope", "domain", "surface", "label_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label_kind: Mapped[str] = mapped_column(String(32))
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(TEMPLATE_FK, ondelete=SET_NULL), nullable=True
    )
    source_run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    domain: Mapped[str] = mapped_column(String(255), index=True)
    surface: Mapped[str] = mapped_column(String(40), index=True)
    field_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)
    source_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    approved_schema: Mapped[dict] = mapped_column(JSONB, default=dict)
    field_mapping: Mapped[dict] = mapped_column(JSONB, default=dict)
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)


class ExtractionObservation(CreatedAtMixin, Base):
    """Bounded extraction outcome used for evaluation and recipe learning."""

    __tablename__ = "extraction_observations"
    __table_args__ = (
        Index("ix_extraction_observations_template_run", "template_id", "run_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    template_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey(TEMPLATE_FK, ondelete=SET_NULL), nullable=True
    )
    run_id: Mapped[int | None] = mapped_column(
        ForeignKey(CRAWL_RUN_FK, ondelete=SET_NULL), nullable=True
    )
    url_result_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_url_results.id", ondelete=SET_NULL), nullable=True
    )
    verdict: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
