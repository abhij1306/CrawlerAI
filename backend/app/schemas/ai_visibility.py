from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------
# Shared value objects
# --------------------------------------------------------------------------
class CompetitorInput(BaseModel):
    name: str
    aliases: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)


class PromptInput(BaseModel):
    text: str
    theme: str = ""
    intent: str = ""


# --------------------------------------------------------------------------
# Project requests
# --------------------------------------------------------------------------
class AiVisibilityProjectCreate(BaseModel):
    name: str
    brand_name: str
    brand_aliases: list[str] = Field(default_factory=list)
    owned_domains: list[str] = Field(default_factory=list)
    unintended_domains: list[str] = Field(default_factory=list)
    competitors: list[CompetitorInput] = Field(default_factory=list)
    country_code: str = ""
    language_code: str = ""
    benchmark_mode: Literal[
        "consumer_like", "controlled_localized", "forced_grounded"
    ] = "controlled_localized"
    prompts: list[PromptInput] = Field(default_factory=list)
    default_repetitions: int = Field(default=3, ge=1, le=10)


class AiVisibilityProjectUpdate(BaseModel):
    name: str | None = None
    brand_name: str | None = None
    brand_aliases: list[str] | None = None
    owned_domains: list[str] | None = None
    unintended_domains: list[str] | None = None
    competitors: list[CompetitorInput] | None = None
    country_code: str | None = None
    language_code: str | None = None
    benchmark_mode: (
        Literal["consumer_like", "controlled_localized", "forced_grounded"] | None
    ) = None
    prompts: list[PromptInput] | None = None
    default_repetitions: int | None = Field(default=None, ge=1, le=10)


# --------------------------------------------------------------------------
# Responses
# --------------------------------------------------------------------------
class AiVisibilityProjectResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    user_id: int | None = None
    name: str
    brand_name: str
    brand_aliases: list = Field(default_factory=list)
    owned_domains: list = Field(default_factory=list)
    unintended_domains: list = Field(default_factory=list)
    competitors: list = Field(default_factory=list)
    country_code: str
    language_code: str
    benchmark_mode: str
    prompts: list = Field(default_factory=list)
    default_repetitions: int
    created_at: datetime
    updated_at: datetime


class AiVisibilityRunCreate(BaseModel):
    project_id: int
    provider: Literal[
        "gemini", "anthropic", "openrouter_openai", "openrouter_anthropic"
    ] = "gemini"
    repetitions: int | None = Field(default=None, ge=1, le=10)
    prompt_indices: list[int] | None = None


class AiVisibilityRunResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    user_id: int | None = None
    status: str
    provider: str
    model: str
    repetitions: int
    random_seed: str
    configuration: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)
    requested_count: int
    completed_count: int
    failed_count: int
    error_message: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None


class AiVisibilityExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    run_id: int
    prompt_index: int
    prompt_text_snapshot: str
    prompt_theme_snapshot: str
    prompt_intent_snapshot: str
    repetition: int
    randomized_position: int
    status: str
    answer_text: str
    search_used: bool
    search_events: list = Field(default_factory=list)
    citations: list = Field(default_factory=list)
    score: dict = Field(default_factory=dict)
    request_snapshot: dict = Field(default_factory=dict)
    provider_metadata: dict = Field(default_factory=dict)
    error_code: str
    error_message: str
    latency_ms: int


class AiVisibilityRunDetailResponse(BaseModel):
    run: AiVisibilityRunResponse
    executions: list[AiVisibilityExecutionResponse] = Field(default_factory=list)


class AiVisibilityProviderStatus(BaseModel):
    provider: str
    label: str
    surface: str
    configured: bool
    model: str
    supports_search_fanout: bool
    supports_citations: bool
