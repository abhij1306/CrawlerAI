from __future__ import annotations

from pydantic_settings import BaseSettings

from app.core.config import settings
from app.core.config.runtime_settings import settings_config

# Provider identity
AI_VISIBILITY_PROVIDER_GEMINI = "gemini"
AI_VISIBILITY_PROVIDER_ANTHROPIC = "anthropic"
AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI = "openrouter_openai"
AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC = "openrouter_anthropic"
AI_VISIBILITY_PROVIDERS = frozenset(
    {
        AI_VISIBILITY_PROVIDER_GEMINI,
        AI_VISIBILITY_PROVIDER_ANTHROPIC,
        AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI,
        AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC,
    }
)
AI_VISIBILITY_PROVIDER_MODELS = {
    AI_VISIBILITY_PROVIDER_GEMINI: "gemini-flash-latest",
    AI_VISIBILITY_PROVIDER_ANTHROPIC: "claude-sonnet-4-6",
    AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI: "openai/gpt-5.4",
    AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC: "anthropic/claude-sonnet-4.6",
}

# Run statuses
AI_VISIBILITY_RUN_STATUS_PENDING = "pending"
AI_VISIBILITY_RUN_STATUS_RUNNING = "running"
AI_VISIBILITY_RUN_STATUS_COMPLETED = "completed"
AI_VISIBILITY_RUN_STATUS_DEGRADED = "degraded"
AI_VISIBILITY_RUN_STATUS_FAILED = "failed"
AI_VISIBILITY_RUN_STATUS_CANCELLED = "cancelled"

AI_VISIBILITY_RUN_ACTIVE_STATUSES = frozenset(
    {AI_VISIBILITY_RUN_STATUS_PENDING, AI_VISIBILITY_RUN_STATUS_RUNNING}
)
AI_VISIBILITY_RUN_FINAL_STATUSES = frozenset(
    {
        AI_VISIBILITY_RUN_STATUS_COMPLETED,
        AI_VISIBILITY_RUN_STATUS_DEGRADED,
        AI_VISIBILITY_RUN_STATUS_FAILED,
        AI_VISIBILITY_RUN_STATUS_CANCELLED,
    }
)

# Execution statuses
AI_VISIBILITY_EXECUTION_STATUS_PENDING = "pending"
AI_VISIBILITY_EXECUTION_STATUS_RUNNING = "running"
AI_VISIBILITY_EXECUTION_STATUS_COMPLETED = "completed"
AI_VISIBILITY_EXECUTION_STATUS_FAILED = "failed"
AI_VISIBILITY_EXECUTION_STATUS_CANCELLED = "cancelled"

# Accepted prompt intents
AI_VISIBILITY_PROMPT_INTENTS = frozenset(
    {"discovery", "comparison", "purchase", "service", "local"}
)

AI_VISIBILITY_MODE_CONSUMER_LIKE = "consumer_like"
AI_VISIBILITY_MODE_CONTROLLED_LOCALIZED = "controlled_localized"
AI_VISIBILITY_MODE_FORCED_GROUNDED = "forced_grounded"
AI_VISIBILITY_BENCHMARK_MODES = frozenset(
    {
        AI_VISIBILITY_MODE_CONSUMER_LIKE,
        AI_VISIBILITY_MODE_CONTROLLED_LOCALIZED,
        AI_VISIBILITY_MODE_FORCED_GROUNDED,
    }
)
AI_VISIBILITY_DEFAULT_BENCHMARK_MODE = AI_VISIBILITY_MODE_CONTROLLED_LOCALIZED

AI_VISIBILITY_LOCALIZED_INSTRUCTION = (
    "Answer for a shopper in the market identified by ISO country code "
    "{country_code}, using language {language_code}. Prioritize retailers that "
    "serve that market and sources relevant to that market."
)
AI_VISIBILITY_FORCED_GROUNDED_INSTRUCTION = (
    "Answer the shopping question using current web information. "
    "Cite the sources supporting your recommendations."
)

# Backward-compatible import for callers outside this feature branch.
AI_VISIBILITY_SYSTEM_INSTRUCTION = AI_VISIBILITY_FORCED_GROUNDED_INSTRUCTION

# Single-token aliases that are also ordinary English words. They require
# stronger text evidence than normalized whole-token matching.
AI_VISIBILITY_AMBIGUOUS_ALIASES = frozenset({"target"})

# Public paid-tier list prices, checked 2026-07-11. Actual invoices can be lower
# because provider free allowances and account-specific tiers are not exposed in
# API responses. Values are USD.
AI_VISIBILITY_GEMINI_25_FLASH_INPUT_PER_MILLION_USD = 0.30
AI_VISIBILITY_GEMINI_25_FLASH_OUTPUT_PER_MILLION_USD = 2.50
AI_VISIBILITY_GEMINI_25_GROUNDED_PROMPT_USD = 0.035

# Retry classification tokens (recorded on failed executions).
AI_VISIBILITY_ERROR_TIMEOUT = "timeout"
AI_VISIBILITY_ERROR_CONNECTION = "connection"
AI_VISIBILITY_ERROR_RATE_LIMIT = "rate_limit"
AI_VISIBILITY_ERROR_SERVER = "server_error"
AI_VISIBILITY_ERROR_CLIENT = "client_error"
AI_VISIBILITY_ERROR_AUTH = "auth_failure"
AI_VISIBILITY_ERROR_PARSE = "parse_error"
AI_VISIBILITY_ERROR_UNKNOWN = "unknown"
AI_VISIBILITY_ERROR_INVALID_SURFACE = "invalid_surface"
# Run exceeded its wall-clock deadline; remaining executions are cut off.
AI_VISIBILITY_ERROR_RUN_DEADLINE = "run_deadline_exceeded"

AI_VISIBILITY_RETRYABLE_ERRORS = frozenset(
    {
        AI_VISIBILITY_ERROR_TIMEOUT,
        AI_VISIBILITY_ERROR_CONNECTION,
        AI_VISIBILITY_ERROR_RATE_LIMIT,
        AI_VISIBILITY_ERROR_SERVER,
    }
)


class AiVisibilitySettings(BaseSettings):
    model_config = settings_config(env_prefix="AI_VISIBILITY_")

    # Optional override; the resolver falls back to the top-level GEMINI_API_KEY.
    gemini_api_key: str = ""
    gemini_model: str = "gemini-flash-latest"
    interactions_url: str = (
        "https://generativelanguage.googleapis.com/v1beta/interactions"
    )
    openrouter_chat_completions_url: str = (
        "https://openrouter.ai/api/v1/chat/completions"
    )
    anthropic_messages_url: str = "https://api.anthropic.com/v1/messages"
    anthropic_version: str = "2023-06-01"
    anthropic_model: str = AI_VISIBILITY_PROVIDER_MODELS[AI_VISIBILITY_PROVIDER_ANTHROPIC]
    # Caps server-side web_search invocations per request (Anthropic-only knob).
    # Each search loads its result pages into context as input tokens, so this is
    # the main input-token lever. These benchmark prompts are single shopping
    # questions (1-3 searches suffice), not research agents; 3 bounds cost while
    # rarely truncating.
    anthropic_max_uses: int = 3

    # --- Global guardrails (provider-agnostic) --------------------------------
    # One set of knobs for all providers, so a stray or misused call cannot run
    # away in tokens, time, or duration. Kept here (not per-provider) to avoid
    # duplicate config and to guarantee a uniform ceiling regardless of provider.
    #
    # Per-call output-token cap. Sent to every provider payload so a single
    # generation cannot balloon output tokens/cost. Grounded shopping answers are
    # short; 4096 is generous headroom.
    max_output_tokens: int = 4096
    # Hard per-call ceiling enforced with asyncio.wait_for around the provider
    # call, independent of the HTTP client timeout. >= request_timeout_seconds so
    # the HTTP timeout normally fires first; this only catches a call that stalls
    # past what the client itself detects (hung socket, redirect loop, etc.).
    max_call_seconds: float = 90.0
    # Per-run wall-clock deadline. Once exceeded, remaining executions stop at
    # their boundary and are terminalized, so a run can never sit live forever
    # (e.g. a provider throttling every request into the retry ceiling).
    max_run_seconds: float = 1800.0
    openrouter_openai_model: str = AI_VISIBILITY_PROVIDER_MODELS[
        AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI
    ]
    openrouter_anthropic_model: str = AI_VISIBILITY_PROVIDER_MODELS[
        AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC
    ]
    request_timeout_seconds: float = 60.0
    # Speed is not a priority; a single serial stream is the most quota-friendly
    # against Gemini's per-minute limit (parallel workers multiply RPM).
    run_concurrency: int = 1
    # Gemini project quotas can be as low as three requests per rolling minute.
    # Serialize starts across all runs in this process, not just within one run.
    gemini_min_request_interval_seconds: float = 21.0
    openrouter_min_request_interval_seconds: float = 1.0
    # 5 retries -> backoff waits of ~2,4,8,16,32s (~62s total), enough to outlast
    # a per-minute (429) quota reset that a smaller budget could never clear.
    max_retries: int = 5
    retry_base_delay_seconds: float = 2.0
    # Cap for a single exponential-backoff sleep, and jitter fraction added on top
    # so serial retries don't align to the exact quota-reset boundary.
    retry_max_delay_seconds: float = 45.0
    retry_jitter_seconds: float = 1.5
    resolve_citation_urls: bool = True
    resolve_timeout_seconds: float = 8.0
    max_executions_per_run: int = 250
    daily_request_soft_cap: int = 400

    def resolved_gemini_api_key(self) -> str:
        """Prefer the feature-scoped override, else the shared GEMINI_API_KEY."""
        return (self.gemini_api_key or settings.gemini_api_key or "").strip()

    def resolved_openrouter_api_key(self) -> str:
        return str(settings.openrouter_api_key or "").strip()

    def resolved_anthropic_api_key(self) -> str:
        return str(settings.anthropic_api_key or "").strip()

    def model_for_provider(self, provider: str) -> str:
        if provider == AI_VISIBILITY_PROVIDER_GEMINI:
            return self.gemini_model
        if provider == AI_VISIBILITY_PROVIDER_ANTHROPIC:
            return self.anthropic_model
        if provider == AI_VISIBILITY_PROVIDER_OPENROUTER_OPENAI:
            return self.openrouter_openai_model
        if provider == AI_VISIBILITY_PROVIDER_OPENROUTER_ANTHROPIC:
            return self.openrouter_anthropic_model
        raise ValueError(f"Unsupported AI visibility provider: {provider}")


ai_visibility_settings = AiVisibilitySettings()
