"""Replace generic knowledge graph and selector stores with extraction memory.

Revision ID: 20260702_0004
Revises: 20260629_0003
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "20260702_0004"
down_revision: str | None = "20260629_0003"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]


def upgrade() -> None:
    for statement in _CREATE:
        op.execute(statement)
    for statement in _MIGRATE:
        op.execute(statement)
    for table in _DROP:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")


def downgrade() -> None:
    raise RuntimeError(
        "20260702_0004 is an intentional wholesale replacement; restore from backup "
        "instead of fabricating discarded generic graph claims."
    )


_CREATE = (
    """CREATE TABLE extraction_templates (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), domain VARCHAR(255) NOT NULL,
        surface VARCHAR(40) NOT NULL, fingerprint VARCHAR(128) NOT NULL,
        route_pattern TEXT NOT NULL DEFAULT '', tech_signals JSONB NOT NULL DEFAULT '[]',
        status VARCHAR(24) NOT NULL DEFAULT 'active', last_seen_run_id INTEGER REFERENCES crawl_runs(id) ON DELETE SET NULL,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE UNIQUE INDEX uq_extraction_templates_fingerprint ON extraction_templates(domain, surface, fingerprint)",
    "CREATE INDEX ix_extraction_templates_domain_surface ON extraction_templates(domain, surface)",
    """CREATE TABLE extraction_recipes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), template_id UUID NOT NULL REFERENCES extraction_templates(id) ON DELETE CASCADE,
        layer VARCHAR(24) NOT NULL, kind VARCHAR(32) NOT NULL, payload JSONB NOT NULL DEFAULT '{}',
        locale_policy_ref VARCHAR(128), version INTEGER NOT NULL DEFAULT 1, status VARCHAR(24) NOT NULL DEFAULT 'active',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(), updated_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE UNIQUE INDEX uq_extraction_recipes_scope ON extraction_recipes(template_id, layer, kind)",
    "CREATE INDEX ix_extraction_recipes_template_id ON extraction_recipes(template_id)",
    """CREATE TABLE compiled_extraction_recipes (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), recipe_id UUID NOT NULL REFERENCES extraction_recipes(id) ON DELETE CASCADE,
        compiler_version VARCHAR(32) NOT NULL, checksum VARCHAR(64) NOT NULL, payload JSONB NOT NULL DEFAULT '{}',
        status VARCHAR(24) NOT NULL DEFAULT 'active', created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE UNIQUE INDEX uq_compiled_extraction_recipes_checksum ON compiled_extraction_recipes(recipe_id, checksum)",
    """CREATE TABLE extraction_release_snapshots (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), run_id INTEGER UNIQUE REFERENCES crawl_runs(id) ON DELETE CASCADE,
        domain VARCHAR(255) NOT NULL, surface VARCHAR(40) NOT NULL, release_version VARCHAR(32) NOT NULL,
        payload JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "ALTER TABLE crawl_runs ADD COLUMN extraction_release_snapshot_id UUID",
    "CREATE INDEX ix_crawl_runs_extraction_release_snapshot_id ON crawl_runs(extraction_release_snapshot_id)",
    "ALTER TABLE crawl_url_results ADD COLUMN extraction_manifest_id UUID",
    "CREATE INDEX ix_crawl_url_results_extraction_manifest_id ON crawl_url_results(extraction_manifest_id)",
    """CREATE TABLE extraction_manifests (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), run_id INTEGER NOT NULL REFERENCES crawl_runs(id) ON DELETE CASCADE,
        url_result_id INTEGER NOT NULL UNIQUE REFERENCES crawl_url_results(id) ON DELETE CASCADE,
        release_snapshot_id UUID REFERENCES extraction_release_snapshots(id) ON DELETE SET NULL,
        template_id UUID REFERENCES extraction_templates(id) ON DELETE SET NULL,
        compiled_recipe_id UUID REFERENCES compiled_extraction_recipes(id) ON DELETE SET NULL,
        manifest_version VARCHAR(32) NOT NULL, locale_policy_ref VARCHAR(128), payload JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    """CREATE TABLE extraction_operator_labels (
        id SERIAL PRIMARY KEY, label_kind VARCHAR(32) NOT NULL, template_id UUID REFERENCES extraction_templates(id) ON DELETE SET NULL,
        source_run_id INTEGER REFERENCES crawl_runs(id) ON DELETE SET NULL, domain VARCHAR(255) NOT NULL, surface VARCHAR(40) NOT NULL,
        field_name VARCHAR(128), action VARCHAR(32), source_kind VARCHAR(32), source_value TEXT,
        approved_schema JSONB NOT NULL DEFAULT '{}', field_mapping JSONB NOT NULL DEFAULT '{}', payload JSONB NOT NULL DEFAULT '{}',
        created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
    "CREATE INDEX ix_extraction_operator_labels_scope ON extraction_operator_labels(domain, surface, label_kind)",
    """CREATE TABLE extraction_observations (
        id UUID PRIMARY KEY DEFAULT gen_random_uuid(), template_id UUID REFERENCES extraction_templates(id) ON DELETE SET NULL,
        run_id INTEGER REFERENCES crawl_runs(id) ON DELETE SET NULL, url_result_id INTEGER REFERENCES crawl_url_results(id) ON DELETE SET NULL,
        verdict VARCHAR(24) NOT NULL, payload JSONB NOT NULL DEFAULT '{}', created_at TIMESTAMPTZ NOT NULL DEFAULT now())""",
)

_MIGRATE = (
    """INSERT INTO extraction_templates(id, domain, surface, fingerprint, route_pattern, tech_signals, status, created_at, updated_at)
       SELECT id, COALESCE(properties->>'domain', split_part(canonical_key, ':', 1)),
              COALESCE(properties->>'surface', split_part(canonical_key, ':', 2)),
              COALESCE(properties->>'fingerprint', split_part(canonical_key, ':', 3)),
              COALESCE(properties->>'route_pattern', ''), COALESCE(properties->'tech_signals', '[]'), status, created_at, last_seen_at
       FROM kg_entities WHERE entity_type = 'page_template' ON CONFLICT DO NOTHING""",
    """INSERT INTO extraction_recipes(template_id, layer, kind, payload, version, created_at, updated_at)
       SELECT template_id, 'template', 'contracts', jsonb_build_object('contracts', jsonb_agg(jsonb_build_object(
         'id', id, 'template_id', template_id, 'surface', surface, 'canonical_field', canonical_field,
         'candidates', candidates, 'latest_values', latest_values, 'success_count', success_count,
         'rejection_count', rejection_count, 'resolver_rule', resolver_rule, 'selected_source', selected_source,
         'selection_origin', selection_origin, 'selection_history', selection_history, 'status', status))),
         1, min(created_at), max(updated_at) FROM kg_extraction_contracts
       WHERE template_id IN (SELECT id FROM extraction_templates) GROUP BY template_id""",
    """INSERT INTO extraction_templates(domain, surface, fingerprint, route_pattern, tech_signals, created_at, updated_at)
       SELECT domain, surface, 'domain-default', '/', CASE WHEN platform IS NULL THEN '[]'::jsonb ELSE jsonb_build_array(platform) END,
              created_at, updated_at FROM domain_memory ON CONFLICT DO NOTHING""",
    """INSERT INTO extraction_recipes(template_id, layer, kind, payload, created_at, updated_at)
       SELECT t.id, 'domain', 'selectors', d.selectors, d.created_at, d.updated_at
       FROM domain_memory d JOIN extraction_templates t ON t.domain=d.domain AND t.surface=d.surface AND t.fingerprint='domain-default'
       ON CONFLICT (template_id, layer, kind) DO UPDATE SET payload=excluded.payload""",
    """INSERT INTO compiled_extraction_recipes(recipe_id, compiler_version, checksum, payload)
       SELECT id, 'recipe.v1', md5(payload::text), payload FROM extraction_recipes""",
    """INSERT INTO extraction_operator_labels(label_kind, source_run_id, domain, surface, approved_schema, field_mapping, created_at)
       SELECT 'review_promotion', run_id, domain, surface, approved_schema, field_mapping, created_at FROM review_promotions""",
    """INSERT INTO extraction_operator_labels(label_kind, source_run_id, domain, surface, field_name, action, source_kind, source_value, payload, created_at)
       SELECT 'field_feedback', source_run_id, domain, surface, field_name, action, source_kind, source_value, payload, created_at FROM domain_field_feedback""",
    """INSERT INTO extraction_release_snapshots(run_id, domain, surface, release_version, payload, created_at)
       SELECT id, lower(split_part(split_part(url, '://', 2), '/', 1)), surface, 'release.v1', settings->'extraction_runtime_snapshot', created_at
       FROM crawl_runs WHERE settings ? 'extraction_runtime_snapshot'""",
    """UPDATE crawl_runs r SET extraction_release_snapshot_id=s.id,
       settings=r.settings-'extraction_runtime_snapshot' FROM extraction_release_snapshots s WHERE s.run_id=r.id""",
)

_DROP = (
    "kg_assertion_evidence",
    "kg_relationships",
    "kg_claims",
    "kg_extraction_contracts",
    "kg_entities",
    "kg_site_versions",
    "review_promotions",
    "domain_field_feedback",
    "domain_memory",
)
