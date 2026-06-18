from __future__ import annotations

import pytest

from app.core.security import encrypt_secret
from app.api.llm import llm_configs
from app.models.llm import LLMConfig
from app.services.llm.config_service import (
    get_prompt_task,
    llm_provider_catalog,
    resolve_active_config,
    resolve_provider_api_key,
    resolve_run_config,
    serialize_config_snapshot,
)
from app.services.config.data_enrichment import DATA_ENRICHMENT_PROMPT_REGISTRY
from app.services.config.field_mappings import PROMPT_REGISTRY


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_active_config_prefers_task_then_general(db_session) -> None:
    db_session.add_all(
        [
            LLMConfig(
                provider="groq",
                model="general-model",
                api_key_encrypted="enc-general",
                task_type="general",
                is_active=True,
            ),
            LLMConfig(
                provider="groq",
                model="task-model",
                api_key_encrypted="enc-task",
                task_type="missing_field_extraction",
                is_active=True,
            ),
        ]
    )
    await db_session.commit()

    task_config = await resolve_active_config(db_session, "missing_field_extraction")
    fallback_config = await resolve_active_config(db_session, "direct_record_extraction")

    assert task_config is not None
    assert task_config.model == "task-model"
    assert fallback_config is not None
    assert fallback_config.model == "general-model"


@pytest.mark.component
def test_resolve_provider_api_key_prefers_encrypted_value(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.config_service.settings.groq_api_key",
        "env-secret",
    )
    encrypted = encrypt_secret("stored-secret")

    assert (
        resolve_provider_api_key(provider="groq", encrypted_value=encrypted)
        == "stored-secret"
    )
    assert resolve_provider_api_key(provider="groq", encrypted_value="") == "env-secret"


@pytest.mark.component
def test_serialize_config_snapshot_keeps_encrypted_key() -> None:
    config = LLMConfig(
        id=7,
        provider="groq",
        model="llama",
        api_key_encrypted="encrypted",
        task_type="general",
    )

    assert serialize_config_snapshot(config) == {
        "id": 7,
        "provider": "groq",
        "model": "llama",
        "api_key_encrypted": "encrypted",
        "task_type": "general",
    }


@pytest.mark.component
def test_get_prompt_task_uses_registry_priority_for_duplicate_entries(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    task = {
        "response_type": "object",
        "system_file": "data_enrichment_semantic.system.txt",
        "user_file": "data_enrichment_semantic.user.txt",
    }
    monkeypatch.setitem(DATA_ENRICHMENT_PROMPT_REGISTRY, "collision_task", task)
    monkeypatch.setitem(PROMPT_REGISTRY, "collision_task", {"system_file": "other.txt"})

    with caplog.at_level("WARNING"):
        resolved = get_prompt_task("collision_task")

    assert resolved == task
    assert "multiple registries" in caplog.text


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_run_config_accepts_complete_snapshot(
    db_session,
) -> None:
    resolved = await resolve_run_config(
        db_session,
        run_id=None,
        task_type="data_enrichment_semantic",
        config_snapshot={
            "data_enrichment_semantic": {
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
                "api_key_encrypted": "",
                "task_type": "data_enrichment_semantic",
            }
        },
    )

    assert resolved == {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
        "api_key_encrypted": "",
        "task_type": "data_enrichment_semantic",
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_resolve_run_config_accepts_legacy_snapshot(db_session) -> None:
    resolved = await resolve_run_config(
        db_session,
        run_id=None,
        task_type="data_enrichment_semantic",
        config_snapshot={
            "data_enrichment_semantic": {
                "provider": "groq",
                "model": "llama-3.3-70b-versatile",
            }
        },
    )

    assert resolved == {
        "provider": "groq",
        "model": "llama-3.3-70b-versatile",
    }


@pytest.mark.component
def test_llm_provider_catalog_exposes_expected_provider_anchors() -> None:
    catalog = {item["provider"]: item for item in llm_provider_catalog()}

    assert "llama-3.3-70b-versatile" in catalog["groq"]["recommended_models"]
    assert "mistral-small-latest" in catalog["mistral"]["recommended_models"]
    assert "meta/llama-3.1-70b-instruct" in catalog["nvidia"]["recommended_models"]
    assert "openrouter/free" in catalog["openrouter"]["recommended_models"]
    assert catalog["groq"]["recommended_models"]
    assert catalog["mistral"]["recommended_models"]
    assert catalog["nvidia"]["recommended_models"]
    assert catalog["openrouter"]["recommended_models"]


@pytest.mark.component
def test_resolve_provider_api_key_supports_mistral_env_alias(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.llm.config_service.settings.mistral_api_key",
        "mistral-env-secret",
    )

    assert (
        resolve_provider_api_key(provider="mistral", encrypted_value="")
        == "mistral-env-secret"
    )


@pytest.mark.asyncio
@pytest.mark.component
async def test_llm_configs_can_include_unsupported_records(db_session, caplog) -> None:
    db_session.add_all(
        [
            LLMConfig(
                provider="groq",
                model="supported-model",
                api_key_encrypted="enc-supported",
                task_type="general",
                is_active=True,
            ),
            LLMConfig(
                provider="legacy-provider",
                model="legacy-model",
                api_key_encrypted="enc-legacy",
                task_type="general",
                is_active=False,
            ),
        ]
    )
    await db_session.commit()

    caplog.clear()
    filtered = await llm_configs(db_session, object(), include_unsupported=False)
    included = await llm_configs(db_session, object(), include_unsupported=True)

    assert [row.provider for row in filtered] == ["groq"]
    assert sorted(row.provider for row in included) == ["groq", "legacy-provider"]
    assert "excluded 1 unsupported provider records" in caplog.text
