"""test_learn_once_persistence cases split by public behavior."""

from __future__ import annotations

from tests.component.learn_once_persistence_test_support import (
    AsyncSession,
    _LATCH_URL,
    _RESPONSE,
    _SURFACE_VALUE,
    _empty_result_with_retry,
    _latch_acquisition_result,
    _run_learn,
    _run_learn_no_candidate,
    pytest,
    pytestmark as _component_pytestmark,
)

pytestmark = _component_pytestmark


@pytest.mark.asyncio
async def test_retry_cycle_persists_exactly_one_recipe(
    db_session: AsyncSession, test_user, monkeypatch
) -> None:
    # Finding 5: the HTTP pass (browser retry pending) must defer learning and
    # the post-browser pass must be the single learn attempt, so a full retry
    # cycle for one URL leaves exactly ONE persisted executable recipe — never
    # two.
    from sqlalchemy import func, select

    from app.crawl.crud import create_crawl_run
    from app.crawl.pipeline import learn_once, record_extraction_stage as stage
    from app.crawl.pipeline.types import URLProcessingConfig
    from app.crawl.pipeline.url_processing_context import URLProcessingContext
    from app.models.extraction_memory import ExtractionRecipe

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": _LATCH_URL,
            "surface": _SURFACE_VALUE,
            "settings": {"respect_robots_txt": False, "llm_enabled": True},
            "requested_fields": ["title", "price"],
        },
    )

    calls: list[int] = []

    async def _client(system_prompt: str, user_prompt: str) -> str:
        calls.append(1)
        return _RESPONSE

    # Bind the compiler to a counting stub so a second learn attempt would be
    # observable as a second model call and a second persisted recipe.
    monkeypatch.setattr(
        learn_once, "_model_client_for_run", lambda session, *, run_id: _client
    )

    context = URLProcessingContext(
        session=db_session,
        run=run,
        url=_LATCH_URL,
        config=URLProcessingConfig(max_records=10),
        url_timeout_seconds=120.0,
        started_at_monotonic=0.0,
        requested_fields=["title", "price"],
        surface=_SURFACE_VALUE,
    )

    # Pass 1 — HTTP acquisition, empty floors, browser retry still pending:
    # learning is deferred (only the final attempt learns).
    await stage._maybe_learn_once(
        context,
        acquisition_result=_latch_acquisition_result(method="curl_cffi"),
        selector_rules=[],
        result=_empty_result_with_retry(retry_required=True),
    )
    assert calls == []
    assert context.learn_once_attempted is False

    # Pass 2 — post-browser final attempt: the single learn attempt fires.
    await stage._maybe_learn_once(
        context,
        acquisition_result=_latch_acquisition_result(method="browser"),
        selector_rules=[],
        result=_empty_result_with_retry(retry_required=False),
    )
    assert calls == [1]
    assert context.learn_once_attempted is True

    # Pass 3 — a repeat call threaded through the retry is latched off.
    await stage._maybe_learn_once(
        context,
        acquisition_result=_latch_acquisition_result(method="browser"),
        selector_rules=[],
        result=_empty_result_with_retry(retry_required=False),
    )
    assert calls == [1]

    # Exactly ONE executable recipe persisted for the whole retry cycle.
    recipe_count = await db_session.scalar(
        select(func.count()).select_from(ExtractionRecipe)
    )
    assert recipe_count == 1


@pytest.mark.asyncio
async def test_sequential_second_claim_returns_none_without_compiling(
    db_session: AsyncSession,
) -> None:
    # Finding 10 (sequential): once a recipe is learned, a second learn attempt
    # for the same scope claims nothing and never compiles.
    from sqlalchemy import func, select

    from app.models.extraction_memory import ExtractionRecipe

    calls: list[int] = []
    assert await _run_learn(db_session, calls) is True
    assert await _run_learn(db_session, calls) is False
    assert calls == [1]

    recipe_count = await db_session.scalar(
        select(func.count()).select_from(ExtractionRecipe)
    )
    assert recipe_count == 1


@pytest.mark.asyncio
async def test_concurrent_claims_compile_exactly_once(
    db_session: AsyncSession,
) -> None:
    # Finding 10 (true concurrency): two learn attempts for the SAME scope race
    # the durable claim on two independent sessions/connections bound to the
    # same schema. The template row lock serializes them so the compiler stub is
    # invoked EXACTLY ONCE and exactly one active recipe exists.
    import asyncio

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.extraction_memory import ExtractionRecipe

    session_factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    calls: list[int] = []

    async def _worker() -> bool:
        async with session_factory() as session:
            return await _run_learn(session, calls, delay=0.05)

    results = await asyncio.gather(_worker(), _worker())

    # Exactly one worker learned; the other failed closed (no model call raced).
    assert sorted(results) == [False, True]
    assert calls == [1]

    recipe_count = await db_session.scalar(
        select(func.count()).select_from(ExtractionRecipe)
    )
    assert recipe_count == 1


@pytest.mark.asyncio
async def test_no_candidate_compile_stays_exactly_once_sequential(
    db_session: AsyncSession,
) -> None:
    # Finding 6 (sequential): the first attempt compiles but the model grounds
    # nothing, so no executable recipe is persisted. A durable PROVISIONAL
    # attempt marker is written under the lock, so a second attempt for the same
    # scope (within the TTL) fails closed WITHOUT calling the model again.
    from sqlalchemy import func, select

    from app.models.extraction_memory import ExtractionRecipe

    calls: list[int] = []
    assert await _run_learn_no_candidate(db_session, calls) is False
    assert await _run_learn_no_candidate(db_session, calls) is False
    # The model was invoked exactly once even though nothing was learned.
    assert calls == [1]

    # Exactly one (PROVISIONAL marker) row exists; none is ACTIVE.
    recipe_count = await db_session.scalar(
        select(func.count()).select_from(ExtractionRecipe)
    )
    assert recipe_count == 1
    active_count = await db_session.scalar(
        select(func.count())
        .select_from(ExtractionRecipe)
        .where(ExtractionRecipe.status == "active")
    )
    assert active_count == 0


@pytest.mark.asyncio
async def test_no_candidate_compile_stays_exactly_once_concurrent(
    db_session: AsyncSession,
) -> None:
    # Finding 6 (true concurrency): two workers race the claim on independent
    # sessions; the winner's compile yields NO recipe. Because the durable
    # attempt marker is committed under the lock BEFORE the model call, the
    # loser sees it and fails closed — the compiler runs EXACTLY ONCE.
    import asyncio

    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    from app.models.extraction_memory import ExtractionRecipe

    session_factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, class_=AsyncSession
    )
    calls: list[int] = []

    async def _worker() -> bool:
        async with session_factory() as session:
            return await _run_learn_no_candidate(session, calls, delay=0.05)

    results = await asyncio.gather(_worker(), _worker())

    # Neither worker learned (no grounded recipe), but the model was called once.
    assert results == [False, False]
    assert calls == [1]

    # Exactly one PROVISIONAL marker row; nothing ACTIVE leaked into the release.
    recipe_count = await db_session.scalar(
        select(func.count()).select_from(ExtractionRecipe)
    )
    assert recipe_count == 1
    active_count = await db_session.scalar(
        select(func.count())
        .select_from(ExtractionRecipe)
        .where(ExtractionRecipe.status == "active")
    )
    assert active_count == 0


@pytest.mark.asyncio
async def test_stale_attempt_marker_is_reclaimable(
    db_session: AsyncSession,
) -> None:
    # Finding 6 (TTL): a crashed first attempt leaves a marker that ages out. A
    # later attempt past the TTL re-claims the scope and can learn — an
    # abandoned attempt never permanently blocks a template.
    from datetime import UTC, datetime, timedelta

    from sqlalchemy import func, select

    from app.core.config.cascade import CASCADE_LEARN_ONCE_ATTEMPT_TTL_SECONDS
    from app.models.extraction_memory import ExtractionRecipe

    calls: list[int] = []
    # First attempt grounds nothing -> leaves a PROVISIONAL marker.
    assert await _run_learn_no_candidate(db_session, calls) is False
    assert calls == [1]

    # Backdate the marker beyond the TTL to simulate an abandoned attempt.
    marker = await db_session.scalar(select(ExtractionRecipe))
    assert marker is not None
    stale_at = datetime.now(UTC) - timedelta(
        seconds=CASCADE_LEARN_ONCE_ATTEMPT_TTL_SECONDS + 60
    )
    payload = dict(marker.payload or {})
    payload["_learn_attempt"] = {"run_id": None, "claimed_at": stale_at.isoformat()}
    marker.payload = payload
    await db_session.commit()

    # A grounded second attempt now re-claims and learns.
    grounded_calls: list[int] = []
    assert await _run_learn(db_session, grounded_calls) is True
    assert grounded_calls == [1]

    active_count = await db_session.scalar(
        select(func.count())
        .select_from(ExtractionRecipe)
        .where(ExtractionRecipe.status == "active")
    )
    assert active_count == 1
