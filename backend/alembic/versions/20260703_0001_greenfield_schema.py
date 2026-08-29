"""Greenfield schema for CrawlerAI.

Revision ID: 20260703_0001
Revises:

This is the single squashed baseline. The development-only migration chain was
intentionally replaced after resetting local data. Existing databases stamped on
removed revisions must use the staged reset path, not an in-place upgrade:

1. Back up anything important.
2. Drop and recreate the target schema/database.
3. Run `alembic upgrade head` to apply this greenfield baseline.

"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "20260703_0001"
down_revision: str | None = None
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "revision"]

_RUN_EVENTS_APPEND_ONLY_FUNCTION_SQL = """
CREATE FUNCTION enforce_run_events_append_only()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF TG_OP = 'DELETE' AND NOT EXISTS (
        SELECT 1 FROM crawl_runs WHERE id = OLD.run_id
    ) THEN
        RETURN OLD;
    END IF;
    RAISE EXCEPTION 'run_events are append-only'
        USING ERRCODE = '55000';
END;
$$
"""

_RUN_EVENTS_APPEND_ONLY_TRIGGER_SQL = """
CREATE TRIGGER run_events_append_only
BEFORE UPDATE OR DELETE ON run_events
FOR EACH ROW EXECUTE FUNCTION enforce_run_events_append_only()
"""


def upgrade() -> None:
    op.create_table(
        "domain_cookie_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column(
            "storage_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("state_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "domain_run_profiles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("profile", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_domain_run_profiles_domain_surface",
        "domain_run_profiles",
        ["domain", "surface"],
        unique=True,
    )
    op.create_table(
        "host_protection_memory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host", sa.String(length=255), nullable=False),
        sa.Column("hard_block_count", sa.Integer(), nullable=False),
        sa.Column("browser_first_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("proxy_required_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_block_vendor", sa.String(length=64), nullable=True),
        sa.Column("last_block_status_code", sa.Integer(), nullable=True),
        sa.Column("last_block_method", sa.String(length=32), nullable=True),
        sa.Column("last_blocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_success_method", sa.String(length=32), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_host_protection_memory_host",
        "host_protection_memory",
        ["host"],
        unique=True,
    )
    op.create_table(
        "llm_configs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("api_key_encrypted", sa.Text(), nullable=False),
        sa.Column("task_type", sa.String(length=60), nullable=False),
        sa.Column(
            "per_domain_daily_budget_usd",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column(
            "global_session_budget_usd",
            sa.Numeric(precision=10, scale=2),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("token_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"], unique=True)
    op.create_foreign_key(
        "fk_domain_cookie_memory_user_id_users",
        "domain_cookie_memory",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        op.f("ix_domain_cookie_memory_user_id"),
        "domain_cookie_memory",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_domain_cookie_memory_user_domain",
        "domain_cookie_memory",
        ["user_id", "domain"],
        unique=True,
    )
    op.create_table(
        "bootstrap_records",
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("name"),
    )
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_api_keys_is_active"), "api_keys", ["is_active"], unique=False
    )
    op.create_index(op.f("ix_api_keys_key_hash"), "api_keys", ["key_hash"], unique=True)
    op.create_index(
        op.f("ix_api_keys_key_prefix"), "api_keys", ["key_prefix"], unique=False
    )
    op.create_index(op.f("ix_api_keys_user_id"), "api_keys", ["user_id"], unique=False)
    op.create_table(
        "crawl_runs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("run_type", sa.String(length=20), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "requested_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "result_summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("queue_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claim_count", sa.Integer(), nullable=False),
        sa.Column("extraction_release_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("last_claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "run_event_sequence",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'paused', 'completed', 'killed', 'failed', 'proxy_exhausted')",
            name="ck_crawl_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_crawl_runs_active_created_at",
        "crawl_runs",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("status IN ('pending', 'running', 'paused')"),
    )
    op.create_index(
        op.f("ix_crawl_runs_extraction_release_snapshot_id"),
        "crawl_runs",
        ["extraction_release_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_crawl_runs_status"), "crawl_runs", ["status"], unique=False
    )
    op.create_index(
        "ix_crawl_runs_status_created_at",
        "crawl_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_runs_user_created_at",
        "crawl_runs",
        ["user_id", sa.literal_column("created_at DESC")],
        unique=False,
    )
    op.create_index(
        op.f("ix_crawl_runs_user_id"), "crawl_runs", ["user_id"], unique=False
    )
    op.create_table(
        "crawl_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(length=20), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_crawl_logs_run_id"), "crawl_logs", ["run_id"], unique=False
    )
    op.create_table(
        "run_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=64), nullable=False),
        sa.Column("stage", sa.String(length=64), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("url_scope_id", sa.String(length=128), nullable=True),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("outcome", sa.String(length=64), nullable=False),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column(
            "facts",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("sequence > 0", name="ck_run_events_sequence_positive"),
        sa.CheckConstraint(
            "stage IS NULL OR stage IN ('acquisition', 'extraction', 'normalization', 'persistence')",
            name="ck_run_events_stage",
        ),
        sa.CheckConstraint(
            "severity IN ('info', 'warning', 'error')",
            name="ck_run_events_severity",
        ),
        sa.CheckConstraint(
            "outcome IN ('progress', 'succeeded', 'partial', 'failed', 'blocked', "
            "'skipped', 'cancelled', 'requested', 'limited')",
            name="ck_run_events_outcome",
        ),
        sa.CheckConstraint(
            "(url IS NULL) = (url_scope_id IS NULL)",
            name="ck_run_events_url_scope",
        ),
        sa.UniqueConstraint("run_id", "sequence", name="uq_run_events_run_sequence"),
    )
    op.create_index(
        "ix_run_events_run_url_scope_sequence",
        "run_events",
        ["run_id", "url_scope_id", "sequence"],
        unique=False,
        postgresql_where=sa.text("url_scope_id IS NOT NULL"),
    )
    op.execute(_RUN_EVENTS_APPEND_ONLY_FUNCTION_SQL)
    op.execute(_RUN_EVENTS_APPEND_ONLY_TRIGGER_SQL)
    op.create_table(
        "crawl_url_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("requested_url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("generation", sa.Integer(), nullable=False),
        sa.Column("acquisition_outcome", sa.String(length=24), nullable=False),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("extraction_version", sa.String(length=32), nullable=False),
        sa.Column("bundle_id", sa.String(length=128), nullable=True),
        sa.Column("manifest_uri", sa.Text(), nullable=True),
        sa.Column("extraction_manifest_id", sa.UUID(), nullable=True),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_crawl_url_results_extraction_manifest_id"),
        "crawl_url_results",
        ["extraction_manifest_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_crawl_url_results_run_id"),
        "crawl_url_results",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_crawl_url_results_verdict"),
        "crawl_url_results",
        ["verdict"],
        unique=False,
    )
    op.create_index(
        "uq_crawl_url_results_identity",
        "crawl_url_results",
        ["run_id", "normalized_url", "surface", "generation"],
        unique=True,
    )
    op.create_table(
        "data_enrichment_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'enriched', 'degraded', 'failed')",
            name="ck_data_enrichment_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_data_enrichment_jobs_source_run_id"),
        "data_enrichment_jobs",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_enrichment_jobs_status"),
        "data_enrichment_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_data_enrichment_jobs_user_id"),
        "data_enrichment_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "extraction_release_snapshots",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("release_version", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id"),
    )
    op.create_table(
        "extraction_templates",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("fingerprint", sa.String(length=128), nullable=False),
        sa.Column("route_pattern", sa.Text(), nullable=False),
        sa.Column(
            "tech_signals", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("last_seen_run_id", sa.Integer(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["last_seen_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_templates_domain_surface",
        "extraction_templates",
        ["domain", "surface"],
        unique=False,
    )
    op.create_index(
        "uq_extraction_templates_fingerprint",
        "extraction_templates",
        ["domain", "surface", "fingerprint"],
        unique=True,
    )
    op.create_table(
        "llm_cost_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("model", sa.String(length=255), nullable=False),
        sa.Column("task_type", sa.String(length=60), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("cost_usd", sa.Numeric(precision=10, scale=4), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("error_category", sa.String(length=60), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "outcome in ('success', 'error')", name="ck_llm_cost_log_outcome"
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["crawl_runs.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_llm_cost_log_run_id"), "llm_cost_log", ["run_id"], unique=False
    )
    op.create_table(
        "product_intelligence_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("options", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("summary", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_intelligence_jobs_source_run_id"),
        "product_intelligence_jobs",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_jobs_status"),
        "product_intelligence_jobs",
        ["status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_jobs_user_id"),
        "product_intelligence_jobs",
        ["user_id"],
        unique=False,
    )
    op.create_table(
        "crawl_records",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("url_result_id", sa.Integer(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("url_identity_key", sa.String(length=64), nullable=True),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("raw_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "discovered_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "source_trace", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("raw_html_path", sa.Text(), nullable=True),
        sa.Column(
            "enrichment_status",
            sa.String(length=32),
            server_default="unenriched",
            nullable=False,
        ),
        sa.Column("enriched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "enrichment_status IN ('unenriched', 'pending', 'running', 'enriched', 'degraded', 'failed')",
            name="ck_crawl_records_enrichment_status",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["url_result_id"], ["crawl_url_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_crawl_records_enrichment_status"),
        "crawl_records",
        ["enrichment_status"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_records_run_content_fp",
        "crawl_records",
        ["run_id", "content_fingerprint"],
        unique=False,
    )
    op.create_index(
        "ix_crawl_records_run_created_id",
        "crawl_records",
        ["run_id", "created_at", "id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_crawl_records_run_id"), "crawl_records", ["run_id"], unique=False
    )
    op.create_index(
        op.f("ix_crawl_records_url_result_id"),
        "crawl_records",
        ["url_result_id"],
        unique=False,
    )
    op.create_index(
        "uq_crawl_records_run_identity",
        "crawl_records",
        ["run_id", "url_identity_key"],
        unique=True,
        postgresql_where=sa.text("url_identity_key IS NOT NULL"),
    )
    op.create_table(
        "extraction_observations",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("run_id", sa.Integer(), nullable=True),
        sa.Column("url_result_id", sa.Integer(), nullable=True),
        sa.Column("verdict", sa.String(length=24), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["extraction_templates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["url_result_id"], ["crawl_url_results.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_observations_run_id",
        "extraction_observations",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_observations_sentinel_critical",
        "extraction_observations",
        ["template_id"],
        unique=False,
        postgresql_where=sa.text(
            "verdict = 'critical_drift' AND payload->>'kind' = 'sentinel_challenger'"
        ),
    )
    op.create_index(
        "ix_extraction_observations_template_run",
        "extraction_observations",
        ["template_id", "run_id"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_observations_url_result_id",
        "extraction_observations",
        ["url_result_id"],
        unique=False,
    )
    op.create_table(
        "extraction_operator_labels",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("label_kind", sa.String(length=32), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("surface", sa.String(length=40), nullable=False),
        sa.Column("field_name", sa.String(length=128), nullable=True),
        sa.Column("action", sa.String(length=32), nullable=True),
        sa.Column("source_kind", sa.String(length=32), nullable=True),
        sa.Column("source_value", sa.Text(), nullable=True),
        sa.Column(
            "approved_schema", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "field_mapping", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["extraction_templates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_extraction_operator_labels_domain"),
        "extraction_operator_labels",
        ["domain"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_operator_labels_scope",
        "extraction_operator_labels",
        ["domain", "surface", "label_kind"],
        unique=False,
    )
    op.create_index(
        op.f("ix_extraction_operator_labels_source_run_id"),
        "extraction_operator_labels",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_extraction_operator_labels_surface"),
        "extraction_operator_labels",
        ["surface"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_operator_labels_template_id",
        "extraction_operator_labels",
        ["template_id"],
        unique=False,
    )
    op.create_table(
        "extraction_recipes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("template_id", sa.UUID(), nullable=False),
        sa.Column("layer", sa.String(length=24), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("locale_policy_ref", sa.String(length=128), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["template_id"], ["extraction_templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_recipes_template_id",
        "extraction_recipes",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        "uq_extraction_recipes_scope",
        "extraction_recipes",
        ["template_id", "layer", "kind"],
        unique=True,
    )
    op.create_table(
        "compiled_extraction_recipes",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("recipe_id", sa.UUID(), nullable=False),
        sa.Column("compiler_version", sa.String(length=32), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["recipe_id"], ["extraction_recipes.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_compiled_extraction_recipes_recipe_id"),
        "compiled_extraction_recipes",
        ["recipe_id"],
        unique=False,
    )
    op.create_index(
        "uq_compiled_extraction_recipes_checksum",
        "compiled_extraction_recipes",
        ["recipe_id", "checksum"],
        unique=True,
    )
    op.create_table(
        "enriched_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "price_normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("color_family", sa.Text(), nullable=True),
        sa.Column(
            "size_normalized", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("size_system", sa.String(length=32), nullable=True),
        sa.Column("gender_normalized", sa.String(length=32), nullable=True),
        sa.Column(
            "materials_normalized",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("availability_normalized", sa.String(length=32), nullable=True),
        sa.Column(
            "seo_keywords", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("category_path", sa.Text(), nullable=True),
        sa.Column("taxonomy_version", sa.String(length=32), nullable=True),
        sa.Column(
            "intent_attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("audience", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("style_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "ai_discovery_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "suggested_bundles", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "diagnostics", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'enriched', 'degraded', 'failed')",
            name="ck_enriched_products_status",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["data_enrichment_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["crawl_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_enriched_products_job_id"),
        "enriched_products",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_enriched_products_source_record_id"),
        "enriched_products",
        ["source_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_enriched_products_source_run_id"),
        "enriched_products",
        ["source_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_enriched_products_status"),
        "enriched_products",
        ["status"],
        unique=False,
    )
    op.create_index(
        "uq_enriched_products_source_record",
        "enriched_products",
        ["source_record_id"],
        unique=True,
        postgresql_where=sa.text("source_record_id IS NOT NULL"),
    )
    op.create_table(
        "product_intelligence_source_products",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("source_run_id", sa.Integer(), nullable=True),
        sa.Column("source_record_id", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("brand", sa.String(length=255), nullable=False),
        sa.Column("normalized_brand", sa.String(length=255), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("sku", sa.String(length=255), nullable=False),
        sa.Column("mpn", sa.String(length=255), nullable=False),
        sa.Column("gtin", sa.String(length=255), nullable=False),
        sa.Column(
            "price", sa.Numeric(precision=12, scale=2, asdecimal=False), nullable=True
        ),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("is_private_label", sa.Boolean(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"], ["product_intelligence_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_record_id"], ["crawl_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["source_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_intelligence_source_products_brand"),
        "product_intelligence_source_products",
        ["brand"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_source_products_job_id"),
        "product_intelligence_source_products",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_source_products_normalized_brand"),
        "product_intelligence_source_products",
        ["normalized_brand"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_source_products_source_record_id"),
        "product_intelligence_source_products",
        ["source_record_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_source_products_source_run_id"),
        "product_intelligence_source_products",
        ["source_run_id"],
        unique=False,
    )
    op.create_table(
        "extraction_manifests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("url_result_id", sa.Integer(), nullable=False),
        sa.Column("release_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("template_id", sa.UUID(), nullable=True),
        sa.Column("compiled_recipe_id", sa.UUID(), nullable=True),
        sa.Column("manifest_version", sa.String(length=32), nullable=False),
        sa.Column("locale_policy_ref", sa.String(length=128), nullable=True),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["compiled_recipe_id"],
            ["compiled_extraction_recipes.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["release_snapshot_id"],
            ["extraction_release_snapshots.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["crawl_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["template_id"], ["extraction_templates.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["url_result_id"], ["crawl_url_results.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_extraction_manifests_compiled_recipe_id",
        "extraction_manifests",
        ["compiled_recipe_id"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_manifests_release_snapshot_id",
        "extraction_manifests",
        ["release_snapshot_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_extraction_manifests_run_id"),
        "extraction_manifests",
        ["run_id"],
        unique=False,
    )
    op.create_index(
        "ix_extraction_manifests_template_id",
        "extraction_manifests",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        "uq_extraction_manifests_url_result",
        "extraction_manifests",
        ["url_result_id"],
        unique=True,
    )
    op.create_table(
        "product_intelligence_candidates",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("source_product_id", sa.Integer(), nullable=False),
        sa.Column("candidate_crawl_run_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("query_used", sa.Text(), nullable=False),
        sa.Column("search_rank", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_crawl_run_id"], ["crawl_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["product_intelligence_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["product_intelligence_source_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_intelligence_candidates_candidate_crawl_run_id"),
        "product_intelligence_candidates",
        ["candidate_crawl_run_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_candidates_domain"),
        "product_intelligence_candidates",
        ["domain"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_candidates_job_id"),
        "product_intelligence_candidates",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_candidates_source_product_id"),
        "product_intelligence_candidates",
        ["source_product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_candidates_status"),
        "product_intelligence_candidates",
        ["status"],
        unique=False,
    )
    op.create_table(
        "product_intelligence_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("source_product_id", sa.Integer(), nullable=False),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("candidate_record_id", sa.Integer(), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("score_label", sa.String(length=32), nullable=False),
        sa.Column("review_status", sa.String(length=32), nullable=False),
        sa.Column(
            "source_price",
            sa.Numeric(precision=12, scale=2, asdecimal=False),
            nullable=True,
        ),
        sa.Column(
            "candidate_price",
            sa.Numeric(precision=12, scale=2, asdecimal=False),
            nullable=True,
        ),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("availability", sa.Text(), nullable=False),
        sa.Column("candidate_url", sa.Text(), nullable=False),
        sa.Column("candidate_domain", sa.String(length=255), nullable=False),
        sa.Column(
            "score_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column(
            "llm_enrichment", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["candidate_id"], ["product_intelligence_candidates.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["candidate_record_id"], ["crawl_records.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"], ["product_intelligence_jobs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["source_product_id"],
            ["product_intelligence_source_products.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_intelligence_matches_candidate_domain"),
        "product_intelligence_matches",
        ["candidate_domain"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_matches_candidate_id"),
        "product_intelligence_matches",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_matches_candidate_record_id"),
        "product_intelligence_matches",
        ["candidate_record_id"],
        unique=False,
    )
    op.create_index(
        "ix_product_intelligence_matches_job_source",
        "product_intelligence_matches",
        ["job_id", "source_product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_matches_review_status"),
        "product_intelligence_matches",
        ["review_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_matches_score"),
        "product_intelligence_matches",
        ["score"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_intelligence_matches_source_product_id"),
        "product_intelligence_matches",
        ["source_product_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_product_intelligence_matches_source_product_id"),
        table_name="product_intelligence_matches",
    )
    op.drop_index(
        op.f("ix_product_intelligence_matches_score"),
        table_name="product_intelligence_matches",
    )
    op.drop_index(
        op.f("ix_product_intelligence_matches_review_status"),
        table_name="product_intelligence_matches",
    )
    op.drop_index(
        "ix_product_intelligence_matches_job_source",
        table_name="product_intelligence_matches",
    )
    op.drop_index(
        op.f("ix_product_intelligence_matches_candidate_record_id"),
        table_name="product_intelligence_matches",
    )
    op.drop_index(
        op.f("ix_product_intelligence_matches_candidate_id"),
        table_name="product_intelligence_matches",
    )
    op.drop_index(
        op.f("ix_product_intelligence_matches_candidate_domain"),
        table_name="product_intelligence_matches",
    )
    op.drop_table("product_intelligence_matches")
    op.drop_index(
        op.f("ix_product_intelligence_candidates_status"),
        table_name="product_intelligence_candidates",
    )
    op.drop_index(
        op.f("ix_product_intelligence_candidates_source_product_id"),
        table_name="product_intelligence_candidates",
    )
    op.drop_index(
        op.f("ix_product_intelligence_candidates_job_id"),
        table_name="product_intelligence_candidates",
    )
    op.drop_index(
        op.f("ix_product_intelligence_candidates_domain"),
        table_name="product_intelligence_candidates",
    )
    op.drop_index(
        op.f("ix_product_intelligence_candidates_candidate_crawl_run_id"),
        table_name="product_intelligence_candidates",
    )
    op.drop_table("product_intelligence_candidates")
    op.drop_index(
        "uq_extraction_manifests_url_result", table_name="extraction_manifests"
    )
    op.drop_index(
        "ix_extraction_manifests_template_id", table_name="extraction_manifests"
    )
    op.drop_index(
        op.f("ix_extraction_manifests_run_id"), table_name="extraction_manifests"
    )
    op.drop_index(
        "ix_extraction_manifests_release_snapshot_id", table_name="extraction_manifests"
    )
    op.drop_index(
        "ix_extraction_manifests_compiled_recipe_id", table_name="extraction_manifests"
    )
    op.drop_table("extraction_manifests")
    op.drop_index(
        op.f("ix_product_intelligence_source_products_source_run_id"),
        table_name="product_intelligence_source_products",
    )
    op.drop_index(
        op.f("ix_product_intelligence_source_products_source_record_id"),
        table_name="product_intelligence_source_products",
    )
    op.drop_index(
        op.f("ix_product_intelligence_source_products_normalized_brand"),
        table_name="product_intelligence_source_products",
    )
    op.drop_index(
        op.f("ix_product_intelligence_source_products_job_id"),
        table_name="product_intelligence_source_products",
    )
    op.drop_index(
        op.f("ix_product_intelligence_source_products_brand"),
        table_name="product_intelligence_source_products",
    )
    op.drop_table("product_intelligence_source_products")
    op.drop_index(
        "uq_enriched_products_source_record",
        table_name="enriched_products",
        postgresql_where=sa.text("source_record_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_enriched_products_status"), table_name="enriched_products")
    op.drop_index(
        op.f("ix_enriched_products_source_run_id"), table_name="enriched_products"
    )
    op.drop_index(
        op.f("ix_enriched_products_source_record_id"), table_name="enriched_products"
    )
    op.drop_index(op.f("ix_enriched_products_job_id"), table_name="enriched_products")
    op.drop_table("enriched_products")
    op.drop_index(
        "uq_compiled_extraction_recipes_checksum",
        table_name="compiled_extraction_recipes",
    )
    op.drop_index(
        op.f("ix_compiled_extraction_recipes_recipe_id"),
        table_name="compiled_extraction_recipes",
    )
    op.drop_table("compiled_extraction_recipes")
    op.drop_index("uq_extraction_recipes_scope", table_name="extraction_recipes")
    op.drop_index("ix_extraction_recipes_template_id", table_name="extraction_recipes")
    op.drop_table("extraction_recipes")
    op.drop_index(
        "ix_extraction_operator_labels_template_id",
        table_name="extraction_operator_labels",
    )
    op.drop_index(
        op.f("ix_extraction_operator_labels_surface"),
        table_name="extraction_operator_labels",
    )
    op.drop_index(
        op.f("ix_extraction_operator_labels_source_run_id"),
        table_name="extraction_operator_labels",
    )
    op.drop_index(
        "ix_extraction_operator_labels_scope", table_name="extraction_operator_labels"
    )
    op.drop_index(
        op.f("ix_extraction_operator_labels_domain"),
        table_name="extraction_operator_labels",
    )
    op.drop_table("extraction_operator_labels")
    op.drop_index(
        "ix_extraction_observations_url_result_id", table_name="extraction_observations"
    )
    op.drop_index(
        "ix_extraction_observations_template_run", table_name="extraction_observations"
    )
    op.drop_index(
        "ix_extraction_observations_sentinel_critical",
        table_name="extraction_observations",
        postgresql_where=sa.text(
            "verdict = 'critical_drift' AND payload->>'kind' = 'sentinel_challenger'"
        ),
    )
    op.drop_index(
        "ix_extraction_observations_run_id", table_name="extraction_observations"
    )
    op.drop_table("extraction_observations")
    op.drop_index(
        "uq_crawl_records_run_identity",
        table_name="crawl_records",
        postgresql_where=sa.text("url_identity_key IS NOT NULL"),
    )
    op.drop_index(op.f("ix_crawl_records_url_result_id"), table_name="crawl_records")
    op.drop_index(op.f("ix_crawl_records_run_id"), table_name="crawl_records")
    op.drop_index("ix_crawl_records_run_created_id", table_name="crawl_records")
    op.drop_index("ix_crawl_records_run_content_fp", table_name="crawl_records")
    op.drop_index(
        op.f("ix_crawl_records_enrichment_status"), table_name="crawl_records"
    )
    op.drop_table("crawl_records")
    op.drop_index(
        op.f("ix_product_intelligence_jobs_user_id"),
        table_name="product_intelligence_jobs",
    )
    op.drop_index(
        op.f("ix_product_intelligence_jobs_status"),
        table_name="product_intelligence_jobs",
    )
    op.drop_index(
        op.f("ix_product_intelligence_jobs_source_run_id"),
        table_name="product_intelligence_jobs",
    )
    op.drop_table("product_intelligence_jobs")
    op.drop_index(op.f("ix_llm_cost_log_run_id"), table_name="llm_cost_log")
    op.drop_table("llm_cost_log")
    op.drop_index(
        "uq_extraction_templates_fingerprint", table_name="extraction_templates"
    )
    op.drop_index(
        "ix_extraction_templates_domain_surface", table_name="extraction_templates"
    )
    op.drop_table("extraction_templates")
    op.drop_table("extraction_release_snapshots")
    op.drop_index(
        op.f("ix_data_enrichment_jobs_user_id"), table_name="data_enrichment_jobs"
    )
    op.drop_index(
        op.f("ix_data_enrichment_jobs_status"), table_name="data_enrichment_jobs"
    )
    op.drop_index(
        op.f("ix_data_enrichment_jobs_source_run_id"), table_name="data_enrichment_jobs"
    )
    op.drop_table("data_enrichment_jobs")
    op.drop_index("uq_crawl_url_results_identity", table_name="crawl_url_results")
    op.drop_index(op.f("ix_crawl_url_results_verdict"), table_name="crawl_url_results")
    op.drop_index(op.f("ix_crawl_url_results_run_id"), table_name="crawl_url_results")
    op.drop_index(
        op.f("ix_crawl_url_results_extraction_manifest_id"),
        table_name="crawl_url_results",
    )
    op.drop_table("crawl_url_results")
    op.execute("DROP TRIGGER run_events_append_only ON run_events")
    op.execute("DROP FUNCTION enforce_run_events_append_only()")
    op.drop_index("ix_run_events_run_url_scope_sequence", table_name="run_events")
    op.drop_table("run_events")
    op.drop_index(op.f("ix_crawl_logs_run_id"), table_name="crawl_logs")
    op.drop_table("crawl_logs")
    op.drop_index(op.f("ix_crawl_runs_user_id"), table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_user_created_at", table_name="crawl_runs")
    op.drop_index("ix_crawl_runs_status_created_at", table_name="crawl_runs")
    op.drop_index(op.f("ix_crawl_runs_status"), table_name="crawl_runs")
    op.drop_index(
        op.f("ix_crawl_runs_extraction_release_snapshot_id"), table_name="crawl_runs"
    )
    op.drop_index(
        "ix_crawl_runs_active_created_at",
        table_name="crawl_runs",
        postgresql_where=sa.text("status IN ('pending', 'running', 'paused')"),
    )
    op.drop_table("crawl_runs")
    op.drop_index(op.f("ix_api_keys_user_id"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_prefix"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_key_hash"), table_name="api_keys")
    op.drop_index(op.f("ix_api_keys_is_active"), table_name="api_keys")
    op.drop_table("api_keys")
    op.drop_table("bootstrap_records")
    op.drop_index(
        "uq_domain_cookie_memory_user_domain",
        table_name="domain_cookie_memory",
    )
    op.drop_index(
        op.f("ix_domain_cookie_memory_user_id"),
        table_name="domain_cookie_memory",
    )
    op.drop_constraint(
        "fk_domain_cookie_memory_user_id_users",
        "domain_cookie_memory",
        type_="foreignkey",
    )
    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
    op.drop_table("llm_configs")
    op.drop_index("uq_host_protection_memory_host", table_name="host_protection_memory")
    op.drop_table("host_protection_memory")
    op.drop_index(
        "uq_domain_run_profiles_domain_surface", table_name="domain_run_profiles"
    )
    op.drop_table("domain_run_profiles")
    op.drop_table("domain_cookie_memory")
