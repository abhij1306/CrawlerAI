"""Playground session schemas."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.services.config.sitemap import (
    PLAYGROUND_CATEGORY_DEFAULT_LIMIT,
    PLAYGROUND_CATEGORY_MAX_LIMIT,
)


def _normalize_selected_urls(url: str | None, urls: list[str]) -> list[str]:
    selected = [item.strip() for item in urls if item and item.strip()]
    if url and url.strip():
        selected.insert(0, url.strip())
    return list(dict.fromkeys(selected))


class PlaygroundSessionCreate(BaseModel):
    url: str | None = None
    urls: list[str] = Field(default_factory=list, max_length=50)
    category_limit: int = Field(
        default=PLAYGROUND_CATEGORY_DEFAULT_LIMIT,
        ge=1,
        le=PLAYGROUND_CATEGORY_MAX_LIMIT,
    )

    @model_validator(mode="after")
    def _validate_input_urls(self) -> "PlaygroundSessionCreate":
        if not self.selected_urls():
            raise ValueError("URL is required")
        return self

    def selected_urls(self) -> list[str]:
        return _normalize_selected_urls(self.url, self.urls)


class PlaygroundSelectRequest(BaseModel):
    """User selects which discovered product URLs to extract (max 50)."""
    urls: list[str] = Field(..., max_length=50)


class PlaygroundPipelineRequest(BaseModel):
    """User selects which downstream operations to run."""
    enrich: bool = False
    compare: bool = False
    monitor: bool = False
    audit: bool = False


class PlaygroundStepResult(BaseModel):
    status: str  # pending | running | completed | failed
    run_id: int | None = None
    job_id: int | None = None
    error: str | None = None
    data: dict = Field(default_factory=dict)


class PlaygroundSessionResponse(BaseModel):
    id: int
    input_url: str
    state: str
    step_data: dict
    created_at: datetime
    updated_at: datetime


class PlaygroundDiscoverResponse(BaseModel):
    session_id: int
    state: str
    stage: str  # "sitemap" | "listing" | "detail"
    run_id: int | None = None
    sitemap_url_count: int | None = None
    message: str


class PlaygroundSelectCategoryRequest(BaseModel):
    """User picks one or more category URLs from the sitemap result."""
    url: str | None = None
    urls: list[str] = Field(default_factory=list, max_length=50)

    @model_validator(mode="after")
    def _validate_selected_urls(self) -> "PlaygroundSelectCategoryRequest":
        selected = self.selected_urls()
        if not selected:
            raise ValueError("category URL is required")
        if len(selected) > 50:
            raise ValueError("Maximum 50 category URLs per session")
        return self

    def selected_urls(self) -> list[str]:
        return _normalize_selected_urls(self.url, self.urls)


class PlaygroundExtractResponse(BaseModel):
    session_id: int
    state: str
    run_ids: list[int]
    url_count: int


class PlaygroundPipelineResponse(BaseModel):
    session_id: int
    state: str
    launched: dict  # which ops were launched with their job/run IDs
