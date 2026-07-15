"""Provider-neutral contracts for answer-engine adapters.

The Gemini adapter is the only implementation in the MVP, but every field here is
provider-agnostic so OpenAI/Anthropic adapters can be added later without any
change to persistence, scoring, or the UI.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AnswerEngineRequest:
    prompt: str
    system_instruction: str
    model: str
    timeout_seconds: float


@dataclass(frozen=True, slots=True)
class SearchEventResult:
    sequence: int
    query: str
    call_id: str = ""
    call_sequence: int = 0
    query_sequence: int = 0


@dataclass(frozen=True, slots=True)
class CitationResult:
    ordinal: int
    url: str
    title: str
    domain: str
    start_index: int | None
    end_index: int | None
    cited_text: str


@dataclass(frozen=True, slots=True)
class AnswerEngineResponse:
    provider: str
    model: str
    answer_text: str
    search_used: bool
    search_events: tuple[SearchEventResult, ...]
    citations: tuple[CitationResult, ...]
    provider_metadata: dict = field(default_factory=dict)
    usage: dict = field(default_factory=dict)
    latency_ms: int = 0
