from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.security import decrypt_secret
from app.models.crawl_run import CrawlRun
from app.models.llm import LLMConfig
from app.core.config.field_mappings import PROMPT_REGISTRY
from app.core.config.llm_runtime import SUPPORTED_LLM_PROVIDERS
from app.core.config.data_enrichment import DATA_ENRICHMENT_PROMPT_REGISTRY
from app.core.config.product_intelligence import PRODUCT_INTELLIGENCE_PROMPT_REGISTRY
from app.connectors.llm.payloads import SUPPORTED_TASK_TYPES
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parents[2] / "data" / "prompts"
_CONFIG_SNAPSHOT_REQUIRED_KEYS = frozenset(
    {"provider", "model"}
)
_LLM_PROVIDER_DEFINITIONS = (
    {
        "provider": "mistral",
        "label": "Mistral",
        "settings_attr": "mistral_api_key",
        "recommended_models": [
            "mistral-small-latest",
            "mistral-small-2603",
            "ministral-8b-2512",
        ],
    },
    {
        "provider": "groq",
        "label": "Groq",
        "settings_attr": "groq_api_key",
        "recommended_models": [
            "llama-3.3-70b-versatile",
            "llama-3.1-8b-instant",
            "openai/gpt-oss-20b",
            "openai/gpt-oss-120b",
        ],
    },
    {
        "provider": "nvidia",
        "label": "NVIDIA",
        "settings_attr": "nvidia_api_key",
        "recommended_models": [
            "meta/llama-3.3-70b-instruct",
            "meta/llama-3.1-70b-instruct",
            "meta/llama-3.1-8b-instruct",
            "nvidia/llama-3.3-nemotron-super-49b-v1.5",
            "nvidia/nemotron-3-nano-30b-a3b",
        ],
    },
    {
        "provider": "openrouter",
        "label": "OpenRouter Free",
        "settings_attr": "openrouter_api_key",
        "recommended_models": [
            "openrouter/free",
        ],
    },
    {
        "provider": "anthropic",
        "label": "Anthropic",
        "settings_attr": "anthropic_api_key",
        "recommended_models": [
            "claude-3-5-haiku-latest",
            "claude-sonnet-4-20250514",
        ],
    },
)


def get_prompt_task(task_type: str) -> dict | None:
    normalized = str(task_type or "").strip()
    matches = [
        (name, registry.get(normalized))
        for name, registry in (
            ("DATA_ENRICHMENT_PROMPT_REGISTRY", DATA_ENRICHMENT_PROMPT_REGISTRY),
            ("PRODUCT_INTELLIGENCE_PROMPT_REGISTRY", PRODUCT_INTELLIGENCE_PROMPT_REGISTRY),
            ("PROMPT_REGISTRY", PROMPT_REGISTRY),
        )
        if normalized in registry
    ]
    if len(matches) > 1:
        logger.warning(
            "Prompt task %s exists in multiple registries: %s",
            normalized,
            [name for name, _task in matches],
        )
    task = matches[0][1] if matches else None
    return dict(task) if isinstance(task, dict) else None


def load_prompt_file(relative_path: str) -> str:
    text = str(relative_path or "").strip()
    if not text:
        return ""
    candidate = _PROMPTS_DIR / text
    prompts_dir_resolved = _PROMPTS_DIR.resolve(strict=False)
    candidate_resolved = candidate.resolve(strict=False)
    try:
        candidate_resolved.relative_to(prompts_dir_resolved)
    except ValueError:
        return ""
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return ""


def serialize_config_snapshot(config: LLMConfig) -> dict[str, Any]:
    return {
        "id": config.id,
        "provider": config.provider,
        "model": config.model,
        "api_key_encrypted": config.api_key_encrypted,
        "task_type": config.task_type,
    }


def validate_config_snapshot(value: dict[str, Any]) -> bool:
    return _CONFIG_SNAPSHOT_REQUIRED_KEYS <= set(value)


async def resolve_active_config(
    session: AsyncSession,
    task_type: str,
) -> LLMConfig | None:
    for candidate in [task_type, "general"]:
        result = await session.execute(
            select(LLMConfig)
            .where(LLMConfig.is_active.is_(True), LLMConfig.task_type == candidate)
            .order_by(LLMConfig.created_at.desc())
            .limit(1)
        )
        config = result.scalar_one_or_none()
        if (
            config is not None
            and str(config.provider or "").strip().lower() in SUPPORTED_LLM_PROVIDERS
        ):
            return config
    return None


async def snapshot_active_configs(
    session: AsyncSession,
    task_types: list[str] | None = None,
) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for task_type in task_types or ("general", *SUPPORTED_TASK_TYPES):
        config = await resolve_active_config(session, task_type)
        if config is not None:
            snapshot[task_type] = serialize_config_snapshot(config)
    return snapshot


async def resolve_run_config(
    session: AsyncSession,
    *,
    run_id: int | None,
    task_type: str,
    config_snapshot: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    if isinstance(config_snapshot, dict):
        for candidate in [task_type, "general"]:
            config_value = config_snapshot.get(candidate)
            if isinstance(config_value, dict) and validate_config_snapshot(config_value):
                return config_value
            if isinstance(config_value, dict):
                logger.warning("Ignoring malformed LLM config snapshot for %s", candidate)
    if run_id is not None:
        run = await session.get(CrawlRun, run_id)
        if run is not None:
            snapshot = run.settings_view.llm_config_snapshot()
            for candidate in [task_type, "general"]:
                config_snapshot = snapshot.get(candidate)
                if isinstance(config_snapshot, dict) and validate_config_snapshot(config_snapshot):
                    return config_snapshot
                if isinstance(config_snapshot, dict):
                    logger.warning("Ignoring malformed run LLM config snapshot for %s", candidate)
    config = await resolve_active_config(session, task_type)
    if config is None:
        return None
    return serialize_config_snapshot(config)


def provider_env_key(provider: str) -> str:
    normalized = str(provider or "").strip().lower()
    for definition in _LLM_PROVIDER_DEFINITIONS:
        if definition["provider"] != normalized:
            continue
        settings_attr = definition.get("settings_attr")
        if settings_attr:
            return str(getattr(settings, str(settings_attr), "") or "")
    return ""


def resolve_provider_api_key(*, provider: str, encrypted_value: str) -> str:
    decrypted = decrypt_secret(encrypted_value) if encrypted_value else ""
    if decrypted:
        return decrypted
    return provider_env_key(provider)


def llm_provider_catalog() -> list[dict[str, Any]]:
    return [
        _provider_catalog_entry(definition)
        for definition in _LLM_PROVIDER_DEFINITIONS
    ]


def _provider_catalog_entry(definition: dict[str, Any]) -> dict[str, Any]:
    settings_attr = definition.get("settings_attr")
    entry = {
        "provider": definition["provider"],
        "label": definition["label"],
        "api_key_set": bool(
            getattr(settings, str(settings_attr), "") if settings_attr else False
        ),
        "recommended_models": list(definition["recommended_models"]),
    }
    return entry
