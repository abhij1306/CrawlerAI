"""Public facade for LLM runtime calls and exported LLM contracts."""

from __future__ import annotations

from app.connectors.llm.circuit_breaker import circuit_breaker_snapshot
from app.connectors.llm.config_service import llm_provider_catalog
from app.connectors.llm.errors import ERROR_PREFIX, LLMErrorCategory, classify_error
from app.connectors.llm.provider_client import test_provider_connection
from app.connectors.llm.tasks import run_prompt_task
from app.connectors.llm.types import LLMTaskResult

__all__ = [
    "ERROR_PREFIX",
    "LLMErrorCategory",
    "LLMTaskResult",
    "classify_error",
    "circuit_breaker_snapshot",
    "llm_provider_catalog",
    "run_prompt_task",
    "test_provider_connection",
]
