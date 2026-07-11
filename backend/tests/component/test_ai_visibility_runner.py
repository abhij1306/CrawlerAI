"""Runner drives every execution to completion without corrupting sessions.

Regression guard for the shared-``AsyncSession`` bug: ``run_benchmark`` used to
fan out concurrent executions over one session, so overlapping commits raised
``sqlalchemy.exc.IllegalStateChangeError`` and executions were left ``pending``
forever. The runner now opens a private session per task; this test proves the
fan-out completes and the run finalizes.
"""

from __future__ import annotations

import pytest

from app.ai_visibility import runner, service
from app.ai_visibility.constants import BEST_AND_LESS_PROJECT, BEST_AND_LESS_PROMPTS
from app.ai_visibility.contracts import (
    AnswerEngineRequest,
    AnswerEngineResponse,
    CitationResult,
    SearchEventResult,
)
from app.core.config.ai_visibility import (
    AI_VISIBILITY_PROVIDER_GEMINI,
    ai_visibility_settings,
)


pytestmark = [pytest.mark.component, pytest.mark.asyncio]


class _StubAdapter:
    """In-memory stand-in for ``GeminiAnswerEngineAdapter`` (no network)."""

    provider_id = AI_VISIBILITY_PROVIDER_GEMINI

    def __init__(self, *, api_key: str) -> None:  # match real signature
        self._api_key = api_key

    async def execute(self, request: AnswerEngineRequest) -> AnswerEngineResponse:
        return AnswerEngineResponse(
            provider=self.provider_id,
            model=request.model,
            answer_text=f"Best&Less is a great option for {request.prompt}.",
            search_used=True,
            search_events=(SearchEventResult(sequence=0, query=request.prompt),),
            citations=(
                CitationResult(
                    ordinal=0,
                    url="https://www.bestandless.com.au/",
                    title="Best&Less",
                    domain="bestandless.com.au",
                    start_index=0,
                    end_index=10,
                    cited_text="Best&Less",
                ),
            ),
            latency_ms=5,
        )


@pytest.fixture
def _stub_runner(monkeypatch, db_session, existing_session_local_factory):
    """Point the runner at the test session + stubbed adapter, serialized.

    ``run_concurrency=1`` keeps the workers from overlapping on the single
    shared test session (the real code path still opens a session per task);
    that is enough to exercise the fan-out and finalize without a live DB pool.
    """
    monkeypatch.setattr(
        runner, "SessionLocal", existing_session_local_factory(db_session)
    )
    monkeypatch.setattr(runner, "GeminiAnswerEngineAdapter", _StubAdapter)
    monkeypatch.setattr(ai_visibility_settings, "run_concurrency", 1)
    monkeypatch.setattr(
        ai_visibility_settings, "gemini_min_request_interval_seconds", 0
    )
    monkeypatch.setattr(ai_visibility_settings, "resolve_citation_urls", False)
    monkeypatch.setattr(ai_visibility_settings, "gemini_api_key", "test-key")


async def _make_run(db_session, test_user, *, repetitions):
    payload = {**BEST_AND_LESS_PROJECT, "prompts": BEST_AND_LESS_PROMPTS[:3]}
    project = await service.create_project(db_session, user=test_user, payload=payload)
    return await service.create_run(
        db_session, user=test_user, project_id=project.id, repetitions=repetitions
    )


async def test_run_benchmark_completes_all_executions(
    _stub_runner, db_session, test_user
) -> None:
    run = await _make_run(db_session, test_user, repetitions=3)  # 3 prompts x 3 = 9

    await runner.run_benchmark(run.id)

    refreshed = await service.get_run(db_session, user=test_user, run_id=run.id)
    executions = await service.list_executions(db_session, run=refreshed)

    assert refreshed.status == "completed"
    assert refreshed.completed_count == 9
    assert refreshed.failed_count == 0
    # The bug left executions stuck in 'pending'; none should remain.
    assert {e.status for e in executions} == {"completed"}
    assert all(e.answer_text for e in executions)
    assert refreshed.summary  # aggregate populated


async def test_run_benchmark_ignores_non_pending_run(
    _stub_runner, db_session, test_user
) -> None:
    run = await _make_run(db_session, test_user, repetitions=1)
    run.status = "completed"
    await db_session.commit()

    await runner.run_benchmark(run.id)  # must no-op, not crash

    refreshed = await service.get_run(db_session, user=test_user, run_id=run.id)
    assert refreshed.status == "completed"


async def test_cancel_run_terminalizes_and_finalize_preserves_cancelled(
    _stub_runner, db_session, test_user
) -> None:
    """cancel_run flips the run + unfinished executions; finalize won't override.

    Mirrors the kill flow: an active run is cancelled (as the API/worker would
    see it), then ``_finalize_run`` must leave the status ``cancelled`` rather
    than deriving completed/degraded/failed from execution counts.
    """
    run = await _make_run(db_session, test_user, repetitions=1)  # 3 executions
    run.status = "running"
    await db_session.commit()

    cancelled = await service.cancel_run(db_session, user=test_user, run_id=run.id)
    assert cancelled.status == "cancelled"

    executions = await service.list_executions(db_session, run=cancelled)
    assert {e.status for e in executions} == {"cancelled"}

    # Finalize (as run_benchmark would after the fan-out) must not override it.
    await runner._finalize_run(db_session, cancelled)
    refreshed = await service.get_run(db_session, user=test_user, run_id=run.id)
    assert refreshed.status == "cancelled"


async def test_execute_one_skips_when_run_cancelled(
    _stub_runner, db_session, test_user
) -> None:
    """A worker started before the kill stops at the next execution boundary."""
    import asyncio

    run = await _make_run(db_session, test_user, repetitions=1)
    run.status = "running"
    await db_session.commit()
    execution = (await service.list_executions(db_session, run=run))[0]

    # Kill the run before the worker picks up this execution.
    await service.cancel_run(db_session, user=test_user, run_id=run.id)

    await runner._execute_one(
        execution_id=execution.id,
        adapter=_StubAdapter(api_key="test-key"),
        system_instruction="",
        model="gemini-flash-latest",
        scoring_config=runner.ScoringConfig.from_project(run.configuration or {}),
        semaphore=asyncio.Semaphore(1),
    )

    refreshed = (await service.list_executions(db_session, run=run))[0]
    # Left cancelled by cancel_run; the worker did not run it or mark completed.
    assert refreshed.status == "cancelled"
    assert not refreshed.answer_text
