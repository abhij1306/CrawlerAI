from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class AttemptSpec(FrozenModel):
    attempt_id: str = Field(min_length=1)
    transport: Literal["curl", "httpx", "patchright", "real_chrome"]
    proxy: str | None = None
    warmup: bool = False
    interaction: bool = False
    traversal_mode: str | None = None
    required_artifacts: tuple[str, ...] = ()
    timeout_seconds: float = Field(gt=0)
    reason: str = Field(min_length=1)


class AcquisitionPlan(FrozenModel):
    schema_version: Literal["acquisition-plan.v1"] = "acquisition-plan.v1"
    plan_id: str = Field(min_length=1)
    attempts: tuple[AttemptSpec, ...]
    created_at: datetime
    deadline: datetime
    policy_version: str = "1"

    @model_validator(mode="after")
    def validate_plan(self) -> "AcquisitionPlan":
        attempt_ids = [attempt.attempt_id for attempt in self.attempts]
        if len(attempt_ids) != len(set(attempt_ids)):
            raise ValueError("attempt_id values must be unique")
        if self.deadline <= self.created_at:
            raise ValueError("deadline must be after created_at")
        return self


class AttemptResult(FrozenModel):
    schema_version: Literal["attempt-result.v1"] = "attempt-result.v1"
    attempt_id: str = Field(min_length=1)
    outcome: Literal["success", "blocked", "empty", "error", "skipped"]
    final_url: str = ""
    status_code: int | None = None
    started_at: datetime
    completed_at: datetime
    artifact_refs: tuple[str, ...] = ()
    diagnostics: dict[str, object] = Field(default_factory=dict)
    error: str | None = None

    @model_validator(mode="after")
    def validate_timing(self) -> "AttemptResult":
        if self.completed_at < self.started_at:
            raise ValueError("completed_at cannot precede started_at")
        return self


class AcquisitionResult(FrozenModel):
    schema_version: Literal["acquisition-result.v1"] = "acquisition-result.v1"
    plan_id: str = Field(min_length=1)
    attempts: tuple[AttemptResult, ...]
    selected_attempt_id: str | None = None
    capture_bundle_id: str | None = None
    outcome: Literal["success", "blocked", "empty", "error"]

    @model_validator(mode="after")
    def validate_selected_attempt(self) -> "AcquisitionResult":
        attempt_ids = {attempt.attempt_id for attempt in self.attempts}
        if self.selected_attempt_id is not None and self.selected_attempt_id not in attempt_ids:
            raise ValueError("selected_attempt_id must identify an attempt result")
        return self
