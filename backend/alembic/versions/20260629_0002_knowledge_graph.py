"""Knowledge Graph foundation tables (Slice 5).

Adds the six extraction-owned graph tables described in the feature spec §4.2:
`kg_site_versions`, `kg_entities`, `kg_relationships`, `kg_claims`,
`kg_assertion_evidence`, `kg_extraction_contracts`. UUID primary keys, JSONB
properties, and `ON DELETE SET NULL` evidence references so bounded provenance
survives a crawl reset while the graph is preserved across application and
Domain Memory resets.

Revision ID: 20260629_0002
Revises: 20260509_0001
Create Date: 2026-06-29 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260629_0002"
down_revision: str | None = "20260509_0001"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]


_UPGRADE_SQL: tuple[str, ...] = (
    """
    CREATE TABLE kg_site_versions (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        domain VARCHAR(255) NOT NULL,
        current_version INTEGER NOT NULL DEFAULT 1,
        projection_status VARCHAR(20) NOT NULL DEFAULT 'pending',
        last_projected_run_id INTEGER,
        last_projected_at TIMESTAMP WITH TIME ZONE,
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(last_projected_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL
    )
    """,
    "CREATE UNIQUE INDEX uq_kg_site_versions_domain ON kg_site_versions (domain)",
    "CREATE INDEX ix_kg_site_versions_last_projected_run_id ON kg_site_versions (last_projected_run_id)",
    """
    CREATE TABLE kg_entities (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        entity_type VARCHAR(40) NOT NULL,
        canonical_key TEXT NOT NULL,
        canonical_name TEXT NOT NULL DEFAULT '',
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        first_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
        last_seen_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id)
    )
    """,
    "CREATE UNIQUE INDEX uq_kg_entities_type_key ON kg_entities (entity_type, canonical_key)",
    "CREATE INDEX ix_kg_entities_entity_type ON kg_entities (entity_type)",
    """
    CREATE TABLE kg_relationships (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        source_entity_id UUID NOT NULL,
        target_entity_id UUID NOT NULL,
        relationship_type VARCHAR(40) NOT NULL,
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        valid_from TIMESTAMP WITH TIME ZONE,
        valid_to TIMESTAMP WITH TIME ZONE,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(source_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE,
        FOREIGN KEY(target_entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX uq_kg_relationships_triple ON kg_relationships (source_entity_id, target_entity_id, relationship_type)",
    "CREATE INDEX ix_kg_relationships_source ON kg_relationships (source_entity_id)",
    "CREATE INDEX ix_kg_relationships_target ON kg_relationships (target_entity_id)",
    """
    CREATE TABLE kg_claims (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        entity_id UUID NOT NULL,
        fact_type VARCHAR(60) NOT NULL,
        value JSONB NOT NULL DEFAULT '{}'::jsonb,
        value_hash VARCHAR(64) NOT NULL,
        confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        selection_origin VARCHAR(20) NOT NULL DEFAULT 'generic',
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(entity_id) REFERENCES kg_entities (id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX uq_kg_claims_entity_fact_hash ON kg_claims (entity_id, fact_type, value_hash)",
    "CREATE INDEX ix_kg_claims_entity_id ON kg_claims (entity_id)",
    """
    CREATE TABLE kg_assertion_evidence (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        claim_id UUID,
        relationship_id UUID,
        source_run_id INTEGER,
        collector VARCHAR(64) NOT NULL DEFAULT '',
        locator TEXT NOT NULL DEFAULT '',
        value_preview TEXT NOT NULL DEFAULT '',
        directness VARCHAR(24) NOT NULL DEFAULT '',
        confidence DOUBLE PRECISION NOT NULL DEFAULT 1.0,
        rejected BOOLEAN NOT NULL DEFAULT FALSE,
        rejection_reason TEXT,
        properties JSONB NOT NULL DEFAULT '{}'::jsonb,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        CONSTRAINT ck_kg_evidence_single_target
            CHECK ((claim_id IS NULL) <> (relationship_id IS NULL)),
        FOREIGN KEY(claim_id) REFERENCES kg_claims (id) ON DELETE CASCADE,
        FOREIGN KEY(relationship_id) REFERENCES kg_relationships (id) ON DELETE CASCADE,
        FOREIGN KEY(source_run_id) REFERENCES crawl_runs (id) ON DELETE SET NULL
    )
    """,
    "CREATE INDEX ix_kg_assertion_evidence_claim_id ON kg_assertion_evidence (claim_id)",
    "CREATE INDEX ix_kg_assertion_evidence_relationship_id ON kg_assertion_evidence (relationship_id)",
    "CREATE INDEX ix_kg_assertion_evidence_source_run_id ON kg_assertion_evidence (source_run_id)",
    """
    CREATE TABLE kg_extraction_contracts (
        id UUID NOT NULL DEFAULT gen_random_uuid(),
        template_id UUID NOT NULL,
        surface VARCHAR(40) NOT NULL,
        canonical_field VARCHAR(128) NOT NULL,
        candidates JSONB NOT NULL DEFAULT '[]'::jsonb,
        latest_values JSONB NOT NULL DEFAULT '[]'::jsonb,
        success_count INTEGER NOT NULL DEFAULT 0,
        rejection_count INTEGER NOT NULL DEFAULT 0,
        resolver_rule TEXT NOT NULL DEFAULT '',
        selected_source TEXT NOT NULL DEFAULT '',
        selection_origin VARCHAR(20) NOT NULL DEFAULT 'generic',
        status VARCHAR(20) NOT NULL DEFAULT 'active',
        updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
        created_at TIMESTAMP WITH TIME ZONE NOT NULL,
        PRIMARY KEY (id),
        FOREIGN KEY(template_id) REFERENCES kg_entities (id) ON DELETE CASCADE
    )
    """,
    "CREATE UNIQUE INDEX uq_kg_extraction_contracts_scope ON kg_extraction_contracts (template_id, surface, canonical_field)",
    "CREATE INDEX ix_kg_extraction_contracts_template_id ON kg_extraction_contracts (template_id)",
)

# Drop order: children before parents.
_DOWNGRADE_TABLES: tuple[str, ...] = (
    "kg_extraction_contracts",
    "kg_assertion_evidence",
    "kg_claims",
    "kg_relationships",
    "kg_entities",
    "kg_site_versions",
)


def upgrade() -> None:
    for statement in _UPGRADE_SQL:
        op.execute(statement)


def downgrade() -> None:
    for table_name in _DOWNGRADE_TABLES:
        op.drop_table(table_name)
