"""Project CRUD and run planning for AI-visibility benchmarks.

Scoping mirrors ``app.intelligence.service``: non-admins see only their own
projects/runs; admins see everything.
"""

from __future__ import annotations

import random
import secrets
import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.ai_visibility import (
    AI_VISIBILITY_EXECUTION_STATUS_CANCELLED,
    AI_VISIBILITY_EXECUTION_STATUS_PENDING,
    AI_VISIBILITY_EXECUTION_STATUS_RUNNING,
    AI_VISIBILITY_PROMPT_INTENTS,
    AI_VISIBILITY_PROVIDER_GEMINI,
    AI_VISIBILITY_PROVIDERS,
    AI_VISIBILITY_RUN_STATUS_CANCELLED,
    AI_VISIBILITY_RUN_STATUS_PENDING,
    AI_VISIBILITY_RUN_ACTIVE_STATUSES,
    AI_VISIBILITY_BENCHMARK_MODES,
    AI_VISIBILITY_DEFAULT_BENCHMARK_MODE,
    AI_VISIBILITY_FORCED_GROUNDED_INSTRUCTION,
    AI_VISIBILITY_LOCALIZED_INSTRUCTION,
    AI_VISIBILITY_MODE_CONSUMER_LIKE,
    AI_VISIBILITY_MODE_CONTROLLED_LOCALIZED,
    ai_visibility_settings,
)
from app.core.config.product_intelligence import ADMIN_ROLE
from app.models.ai_visibility import (
    AiVisibilityExecution,
    AiVisibilityProject,
    AiVisibilityRun,
)
from app.models.user import User

_PROJECT_FIELDS = (
    "name",
    "brand_name",
    "brand_aliases",
    "owned_domains",
    "unintended_domains",
    "competitors",
    "country_code",
    "language_code",
    "benchmark_mode",
    "prompts",
    "default_repetitions",
)


def _normalize_prompts(prompts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for prompt in prompts or []:
        text = str(prompt.get("text") or "").strip()
        if not text:
            continue
        intent = str(prompt.get("intent") or "").strip().lower()
        if intent and intent not in AI_VISIBILITY_PROMPT_INTENTS:
            intent = ""
        normalized.append(
            {
                "text": text,
                "theme": str(prompt.get("theme") or "").strip(),
                "intent": intent,
            }
        )
    return normalized


def _normalize_benchmark_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if not mode:
        return AI_VISIBILITY_DEFAULT_BENCHMARK_MODE
    if mode not in AI_VISIBILITY_BENCHMARK_MODES:
        raise ValueError(f"Unsupported benchmark_mode: {mode}")
    return mode


def _system_instruction(*, mode: str, country_code: str, language_code: str) -> str:
    if mode == AI_VISIBILITY_MODE_CONSUMER_LIKE:
        return ""
    localized = AI_VISIBILITY_LOCALIZED_INSTRUCTION.format(
        country_code=(country_code or "unspecified"),
        language_code=(language_code or "unspecified"),
    )
    if mode == AI_VISIBILITY_MODE_CONTROLLED_LOCALIZED:
        return localized
    return f"{localized} {AI_VISIBILITY_FORCED_GROUNDED_INSTRUCTION}"


def _prompt_panel_snapshot(prompts: list[dict[str, Any]]) -> dict[str, Any]:
    prompt_rows = [
        {
            "text": str(prompt.get("text") or ""),
            "theme": str(prompt.get("theme") or ""),
            "intent": str(prompt.get("intent") or ""),
        }
        for prompt in prompts
    ]
    encoded = json.dumps(prompt_rows, sort_keys=True, ensure_ascii=False).encode(
        "utf-8"
    )
    return {
        "panel_id": hashlib.sha256(encoded).hexdigest()[:16],
        "panel_hash": hashlib.sha256(encoded).hexdigest(),
        "prompt_hashes": [
            hashlib.sha256(row["text"].encode("utf-8")).hexdigest()
            for row in prompt_rows
        ],
    }


# --------------------------------------------------------------------------
# Project CRUD
# --------------------------------------------------------------------------
async def create_project(
    session: AsyncSession, *, user: User, payload: dict[str, Any]
) -> AiVisibilityProject:
    data = {key: payload.get(key) for key in _PROJECT_FIELDS if key in payload}
    if "prompts" in data:
        data["prompts"] = _normalize_prompts(data.get("prompts") or [])
    data["benchmark_mode"] = _normalize_benchmark_mode(data.get("benchmark_mode"))
    project = AiVisibilityProject(user_id=user.id, **data)
    session.add(project)
    await session.commit()
    await session.refresh(project)
    return project


async def list_projects(
    session: AsyncSession, *, user: User, limit: int = 50
) -> list[AiVisibilityProject]:
    statement = (
        select(AiVisibilityProject).order_by(AiVisibilityProject.id.desc()).limit(limit)
    )
    if user.role != ADMIN_ROLE:
        statement = statement.where(AiVisibilityProject.user_id == user.id)
    return list((await session.scalars(statement)).all())


async def get_project(
    session: AsyncSession, *, user: User, project_id: int
) -> AiVisibilityProject:
    project = await session.get(AiVisibilityProject, project_id)
    if project is None or (user.role != ADMIN_ROLE and project.user_id != user.id):
        raise LookupError("AI visibility project not found")
    return project


async def update_project(
    session: AsyncSession, *, user: User, project_id: int, payload: dict[str, Any]
) -> AiVisibilityProject:
    project = await get_project(session, user=user, project_id=project_id)
    for key in _PROJECT_FIELDS:
        if key in payload and payload[key] is not None:
            value = payload[key]
            if key == "prompts":
                value = _normalize_prompts(value)
            elif key == "benchmark_mode":
                value = _normalize_benchmark_mode(value)
            setattr(project, key, value)
    await session.commit()
    await session.refresh(project)
    return project


async def delete_project(session: AsyncSession, *, user: User, project_id: int) -> None:
    project = await get_project(session, user=user, project_id=project_id)
    await session.delete(project)
    await session.commit()


# --------------------------------------------------------------------------
# Run planning
# --------------------------------------------------------------------------
def _scoring_configuration(
    project: AiVisibilityProject,
    prompts: list[dict[str, Any]],
    *,
    provider: str,
    model: str,
) -> dict[str, Any]:
    """Freeze the brand/competitor/domain config used for scoring this run."""
    return {
        "brand_name": project.brand_name,
        "brand_aliases": list(project.brand_aliases or []),
        "owned_domains": list(project.owned_domains or []),
        "unintended_domains": list(project.unintended_domains or []),
        "competitors": list(project.competitors or []),
        "country_code": project.country_code,
        "language_code": project.language_code,
        "benchmark_mode": project.benchmark_mode,
        "provider": provider,
        "model": model,
        **_prompt_panel_snapshot(prompts),
    }


async def create_run(
    session: AsyncSession,
    *,
    user: User,
    project_id: int,
    repetitions: int | None = None,
    prompt_indices: list[int] | None = None,
    provider: str = AI_VISIBILITY_PROVIDER_GEMINI,
) -> AiVisibilityRun:
    project = await get_project(session, user=user, project_id=project_id)
    prompts = list(project.prompts or [])
    if provider not in AI_VISIBILITY_PROVIDERS:
        raise ValueError(f"Unsupported provider: {provider}")
    if not prompts:
        raise ValueError("Project has no prompts to benchmark")

    reps = int(repetitions or project.default_repetitions or 1)
    if reps < 1:
        raise ValueError("repetitions must be >= 1")

    if prompt_indices:
        selected = [i for i in prompt_indices if 0 <= i < len(prompts)]
        if not selected:
            raise ValueError("prompt_indices did not match any prompt")
    else:
        selected = list(range(len(prompts)))

    total = len(selected) * reps
    if total > ai_visibility_settings.max_executions_per_run:
        raise ValueError(
            f"Run would create {total} executions, exceeding the limit of "
            f"{ai_visibility_settings.max_executions_per_run}"
        )

    seed = secrets.randbits(64)
    mode = _normalize_benchmark_mode(project.benchmark_mode)
    system_instruction = _system_instruction(
        mode=mode,
        country_code=project.country_code,
        language_code=project.language_code,
    )
    model = ai_visibility_settings.model_for_provider(provider)
    run = AiVisibilityRun(
        project_id=project.id,
        user_id=user.id,
        status=AI_VISIBILITY_RUN_STATUS_PENDING,
        provider=provider,
        model=model,
        repetitions=reps,
        random_seed=str(seed),
        system_instruction=system_instruction,
        configuration=_scoring_configuration(
            project,
            [prompts[i] for i in selected],
            provider=provider,
            model=model,
        ),
        requested_count=total,
    )
    session.add(run)
    await session.flush()  # assign run.id

    # Build the full (prompt, repetition) slot list, then shuffle deterministically
    # so any account-side ordering effects are averaged out across the run.
    slots = [(index, rep) for index in selected for rep in range(reps)]
    random.Random(seed).shuffle(slots)

    for position, (prompt_index, repetition) in enumerate(slots):
        prompt = prompts[prompt_index]
        session.add(
            AiVisibilityExecution(
                run_id=run.id,
                prompt_index=prompt_index,
                prompt_text_snapshot=str(prompt.get("text") or ""),
                prompt_theme_snapshot=str(prompt.get("theme") or ""),
                prompt_intent_snapshot=str(prompt.get("intent") or ""),
                repetition=repetition,
                randomized_position=position,
                status=AI_VISIBILITY_EXECUTION_STATUS_PENDING,
            )
        )

    await session.commit()
    await session.refresh(run)
    return run


async def list_runs(
    session: AsyncSession,
    *,
    user: User,
    project_id: int | None = None,
    limit: int = 50,
) -> list[AiVisibilityRun]:
    statement = select(AiVisibilityRun).order_by(AiVisibilityRun.id.desc()).limit(limit)
    if project_id is not None:
        statement = statement.where(AiVisibilityRun.project_id == project_id)
    if user.role != ADMIN_ROLE:
        statement = statement.where(AiVisibilityRun.user_id == user.id)
    return list((await session.scalars(statement)).all())


async def get_run(session: AsyncSession, *, user: User, run_id: int) -> AiVisibilityRun:
    run = await session.get(AiVisibilityRun, run_id)
    if run is None or (user.role != ADMIN_ROLE and run.user_id != user.id):
        raise LookupError("AI visibility run not found")
    return run


async def delete_run(session: AsyncSession, *, user: User, run_id: int) -> None:
    """Delete one terminal benchmark and its executions."""
    run = await get_run(session, user=user, run_id=run_id)
    if run.status in AI_VISIBILITY_RUN_ACTIVE_STATUSES:
        raise ValueError("Active AI visibility runs cannot be deleted")
    await session.delete(run)
    await session.commit()


async def cancel_run(
    session: AsyncSession, *, user: User, run_id: int
) -> AiVisibilityRun:
    """Cancel an active run and terminalize its unfinished executions.

    Flips the run to ``cancelled`` so a live worker stops cooperatively at the
    next execution boundary (see ``runner._execute_one``), and marks any
    pending/running executions ``cancelled`` so counts and the UI stay
    consistent. This is also how zombie runs (worker died mid-run) are cleaned
    out of the ``running`` state.
    """
    run = await get_run(session, user=user, run_id=run_id)
    if run.status not in AI_VISIBILITY_RUN_ACTIVE_STATUSES:
        raise ValueError("Only active AI visibility runs can be cancelled")
    now = datetime.now(UTC)
    run.status = AI_VISIBILITY_RUN_STATUS_CANCELLED
    run.completed_at = now
    await session.execute(
        update(AiVisibilityExecution)
        .where(AiVisibilityExecution.run_id == run.id)
        .where(
            AiVisibilityExecution.status.in_(
                [
                    AI_VISIBILITY_EXECUTION_STATUS_PENDING,
                    AI_VISIBILITY_EXECUTION_STATUS_RUNNING,
                ]
            )
        )
        .values(status=AI_VISIBILITY_EXECUTION_STATUS_CANCELLED, completed_at=now)
    )
    await session.commit()
    await session.refresh(run)
    return run


async def list_executions(
    session: AsyncSession, *, run: AiVisibilityRun
) -> list[AiVisibilityExecution]:
    statement = (
        select(AiVisibilityExecution)
        .where(AiVisibilityExecution.run_id == run.id)
        .order_by(AiVisibilityExecution.prompt_index, AiVisibilityExecution.repetition)
    )
    return list((await session.scalars(statement)).all())


async def get_execution(
    session: AsyncSession, *, user: User, execution_id: int
) -> AiVisibilityExecution:
    execution = await session.get(AiVisibilityExecution, execution_id)
    if execution is None:
        raise LookupError("AI visibility execution not found")
    # Authorize via the parent run.
    await get_run(session, user=user, run_id=execution.run_id)
    return execution
