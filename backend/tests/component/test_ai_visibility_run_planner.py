"""Slice 2: run planner materializes a deterministic, correctly-sized run."""

from __future__ import annotations

import pytest

from app.ai_visibility import service
from app.ai_visibility.constants import (
    BEST_AND_LESS_PROJECT,
    BEST_AND_LESS_PROMPTS,
)

pytestmark = [pytest.mark.component, pytest.mark.asyncio]


async def _make_project(db_session, test_user, *, prompts=None):
    resolved = BEST_AND_LESS_PROMPTS if prompts is None else prompts
    payload = {**BEST_AND_LESS_PROJECT, "prompts": resolved}
    return await service.create_project(db_session, user=test_user, payload=payload)


async def test_run_creates_exact_execution_count(db_session, test_user) -> None:
    project = await _make_project(
        db_session, test_user, prompts=BEST_AND_LESS_PROMPTS[:5]
    )
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=3
    )
    executions = await service.list_executions(db_session, run=run)
    assert run.requested_count == 15
    assert len(executions) == 15
    # No duplicate (prompt_index, repetition) slots.
    slots = {(e.prompt_index, e.repetition) for e in executions}
    assert len(slots) == 15
    assert run.random_seed  # seed persisted


async def test_run_shuffle_is_seeded_and_positions_unique(
    db_session, test_user
) -> None:
    project = await _make_project(
        db_session, test_user, prompts=BEST_AND_LESS_PROMPTS[:5]
    )
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=2
    )
    executions = await service.list_executions(db_session, run=run)
    positions = sorted(e.randomized_position for e in executions)
    assert positions == list(range(10))  # contiguous, unique


async def test_prompt_indices_subset(db_session, test_user) -> None:
    project = await _make_project(db_session, test_user)
    run = await service.create_run(
        db_session,
        user=test_user,
        project_id=project.id,
        repetitions=3,
        prompt_indices=[0, 6, 10, 14, 17],
    )
    executions = await service.list_executions(db_session, run=run)
    assert run.requested_count == 15
    assert {e.prompt_index for e in executions} == {0, 6, 10, 14, 17}


async def test_configuration_snapshot_frozen_on_run(db_session, test_user) -> None:
    project = await _make_project(db_session, test_user)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )
    config = run.configuration
    assert config["brand_name"] == "Best&Less"
    assert config["owned_domains"] == ["bestandless.com.au"]
    assert len(config["competitors"]) == 3
    assert config["benchmark_mode"] == "controlled_localized"
    assert config["country_code"] == "AU"
    assert config["panel_id"]
    assert len(config["prompt_hashes"]) == len(BEST_AND_LESS_PROMPTS)
    assert "ISO country code AU" in run.system_instruction


async def test_consumer_like_run_has_no_hidden_instruction(
    db_session, test_user
) -> None:
    payload = {
        **BEST_AND_LESS_PROJECT,
        "benchmark_mode": "consumer_like",
        "prompts": BEST_AND_LESS_PROMPTS[:1],
    }
    project = await service.create_project(db_session, user=test_user, payload=payload)
    run = await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=1
    )
    assert run.system_instruction == ""
    assert run.configuration["benchmark_mode"] == "consumer_like"


async def test_openrouter_provider_and_model_are_frozen_on_run(
    db_session, test_user
) -> None:
    project = await _make_project(
        db_session, test_user, prompts=BEST_AND_LESS_PROMPTS[:1]
    )
    run = await service.create_run(
        db_session,
        user=test_user,
        project_id=project.id,
        repetitions=1,
        provider="openrouter_anthropic",
    )
    assert run.provider == "openrouter_anthropic"
    assert run.model == "anthropic/claude-sonnet-4.6"


async def test_empty_prompts_rejected(db_session, test_user) -> None:
    project = await _make_project(db_session, test_user, prompts=[])
    with pytest.raises(ValueError, match="no prompts"):
        await service.create_run(
            db_session, user=test_user, project_id=project.id, repetitions=1
        )
