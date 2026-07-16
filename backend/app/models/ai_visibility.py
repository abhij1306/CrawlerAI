from __future__ import annotations
# pylint: disable=duplicate-code

from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.core.config.ai_visibility import (
    AI_VISIBILITY_DEFAULT_BENCHMARK_MODE,
    AI_VISIBILITY_EXECUTION_STATUS_PENDING,
    AI_VISIBILITY_PROVIDER_GEMINI,
    AI_VISIBILITY_RUN_STATUS_PENDING,
)
from app.models.crawl_run import (
    CASCADE,
    SET_NULL,
    USERS_FK,
    CompletedAtMixin,
    UpdatedAtMixin,
)

AI_VISIBILITY_PROJECT_FK = "ai_visibility_projects.id"
AI_VISIBILITY_RUN_FK = "ai_visibility_runs.id"


class AiVisibilityProject(UpdatedAtMixin, Base):
    __tablename__ = "ai_visibility_projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(USERS_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    name: Mapped[str] = mapped_column(String(255), default="")
    brand_name: Mapped[str] = mapped_column(String(255), default="")
    brand_aliases: Mapped[list] = mapped_column(JSONB, default=list)
    owned_domains: Mapped[list] = mapped_column(JSONB, default=list)
    unintended_domains: Mapped[list] = mapped_column(JSONB, default=list)
    competitors: Mapped[list] = mapped_column(JSONB, default=list)
    country_code: Mapped[str] = mapped_column(String(8), default="")
    language_code: Mapped[str] = mapped_column(String(16), default="")
    benchmark_mode: Mapped[str] = mapped_column(
        String(32), default=AI_VISIBILITY_DEFAULT_BENCHMARK_MODE
    )
    prompts: Mapped[list] = mapped_column(JSONB, default=list)
    default_repetitions: Mapped[int] = mapped_column(Integer, default=3)


class AiVisibilityRun(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "ai_visibility_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey(AI_VISIBILITY_PROJECT_FK, ondelete=CASCADE), index=True
    )
    user_id: Mapped[int | None] = mapped_column(
        ForeignKey(USERS_FK, ondelete=SET_NULL), nullable=True, index=True
    )
    status: Mapped[str] = mapped_column(
        String(32), default=AI_VISIBILITY_RUN_STATUS_PENDING, index=True
    )
    provider: Mapped[str] = mapped_column(
        String(32), default=AI_VISIBILITY_PROVIDER_GEMINI
    )
    model: Mapped[str] = mapped_column(String(128), default="")
    repetitions: Mapped[int] = mapped_column(Integer, default=1)
    random_seed: Mapped[str] = mapped_column(String(64), default="")
    system_instruction: Mapped[str] = mapped_column(Text, default="")
    configuration: Mapped[dict] = mapped_column(JSONB, default=dict)
    summary: Mapped[dict] = mapped_column(JSONB, default=dict)
    requested_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")


class AiVisibilityExecution(UpdatedAtMixin, CompletedAtMixin, Base):
    __tablename__ = "ai_visibility_executions"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "prompt_index",
            "repetition",
            name="uq_ai_visibility_execution_slot",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey(AI_VISIBILITY_RUN_FK, ondelete=CASCADE), index=True
    )
    prompt_index: Mapped[int] = mapped_column(Integer, default=0, index=True)
    prompt_text_snapshot: Mapped[str] = mapped_column(Text, default="")
    prompt_theme_snapshot: Mapped[str] = mapped_column(String(128), default="")
    prompt_intent_snapshot: Mapped[str] = mapped_column(String(64), default="")
    repetition: Mapped[int] = mapped_column(Integer, default=0)
    randomized_position: Mapped[int] = mapped_column(Integer, default=0, index=True)
    status: Mapped[str] = mapped_column(
        String(32), default=AI_VISIBILITY_EXECUTION_STATUS_PENDING, index=True
    )
    answer_text: Mapped[str] = mapped_column(Text, default="")
    search_used: Mapped[bool] = mapped_column(default=False)
    search_events: Mapped[list] = mapped_column(JSONB, default=list)
    citations: Mapped[list] = mapped_column(JSONB, default=list)
    score: Mapped[dict] = mapped_column(JSONB, default=dict)
    request_snapshot: Mapped[dict] = mapped_column(JSONB, default=dict)
    provider_metadata: Mapped[dict] = mapped_column(JSONB, default=dict)
    error_code: Mapped[str] = mapped_column(String(32), default="")
    error_message: Mapped[str] = mapped_column(Text, default="")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
