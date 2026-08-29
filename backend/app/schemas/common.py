# Shared API schemas.
from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel

from app.core.config.run_events import (
    RunEventKind,
    RunEventOutcome,
    RunEventSeverity,
    RunEventStage,
)

T = TypeVar("T")


class PaginationMeta(BaseModel):
    page: int
    limit: int
    total: int


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    meta: PaginationMeta


class RunEventResponse(BaseModel):
    id: int
    run_id: int
    sequence: int
    kind: RunEventKind
    stage: RunEventStage | None
    url: str | None
    url_scope_id: str | None
    severity: RunEventSeverity
    outcome: RunEventOutcome
    reason_code: str | None
    facts: dict[str, Any]
    created_at: datetime
