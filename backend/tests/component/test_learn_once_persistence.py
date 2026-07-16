from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.extraction_memory.contract_runtime import select_active_recipe
from app.core.extraction_memory.recipe_compiler import compile_recipe
from app.core.extraction_memory.templates import normalize_route
from app.core.shared.ids import stable_id
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface, listing_schema, surface_spec
from app.models.extraction_memory import ExtractionOperatorLabel
from app.persistence.extraction_memory import (
    build_release_payload,
    note_recipe_drift_failure,
    persist_learned_recipe,
    reset_recipe_drift,
)

pytestmark = pytest.mark.component

_DETAIL_HTML = (
    "<html><body><main>"
    "<h1>Trail Shoe Red</h1>"
    '<a href="/products/trail-shoe-red" rel="canonical">self</a>'
    '<span class="price">$129.99</span>'
    "</main></body></html>"
)
_DETAIL_URL = "https://shop.test/products/trail-shoe-red"
_SURFACE_VALUE = "ecommerce_detail"
_RESPONSE = (
    '{"record_root": "", "fields": {'
    '"title": "/html[1]/body[1]/main[1]/h1[1]", '
    '"price": "/html[1]/body[1]/main[1]/span[1]"}}'
)


async def _learned_recipe():
    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        _DETAIL_HTML,
        _DETAIL_URL,
        requested_fields=("title", "price"),
    )

    async def _client(system_prompt: str, user_prompt: str) -> str:
        return _RESPONSE

    discovery = await compile_recipe(
        request,
        surface_spec=surface_spec(Surface.ECOMMERCE_DETAIL),
        listing_schema=listing_schema(Surface.ECOMMERCE_DETAIL),
        model_client=_client,
    )
    assert discovery.candidate is not None
    return discovery.candidate.recipe


@pytest.mark.asyncio
async def test_persisted_recipe_builds_release_that_select_active_recipe_matches(
    db_session: AsyncSession,
) -> None:
    recipe = await _learned_recipe()
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )

    template, stored = await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=recipe.model_dump(mode="json"),
        confidence=0.75,
    )
    await db_session.commit()

    assert template.route_pattern == route_pattern
    assert stored.kind == "executable_recipe"

    payload = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    # release.v2 shape carries the top-level discriminators select_active_recipe
    # requires.
    assert payload["schema_version"] == "release.v2"
    assert payload["surface"] == _SURFACE_VALUE
    assert len(payload["templates"]) == 1
    assert payload["templates"][0]["executable_recipe"]["schema_version"] == (
        "extraction_recipe.v2"
    )

    selected = select_active_recipe(
        payload,
        surface=_SURFACE_VALUE,
        url=_DETAIL_URL,
    )
    assert selected is not None
    assert selected["route_pattern"] == route_pattern


@pytest.mark.asyncio
async def test_persist_keeps_most_confident_recipe(db_session: AsyncSession) -> None:
    recipe = await _learned_recipe()
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    payload = recipe.model_dump(mode="json")

    await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=payload,
        confidence=0.9,
    )
    # A less-confident later proposal must not overwrite the stored recipe.
    await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=payload,
        confidence=0.2,
    )
    await db_session.commit()

    release = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    assert release["templates"][0]["confidence"] == 0.9


async def _persist_recipe(db_session, *, domain, route_pattern, fingerprint):
    recipe = await _learned_recipe()
    return await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=recipe.model_dump(mode="json"),
        confidence=0.75,
    )


@pytest.mark.asyncio
async def test_drift_suspends_recipe_after_threshold(db_session: AsyncSession) -> None:
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    template, _recipe = await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    await db_session.commit()

    # Threshold is 3: the first two drift notes accumulate, the third suspends.
    assert (
        await note_recipe_drift_failure(
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
        is False
    )
    assert (
        await note_recipe_drift_failure(
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
        is False
    )
    assert (
        await note_recipe_drift_failure(
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
        is True
    )
    await db_session.commit()

    # Once suspended, the executable release no longer offers the recipe.
    payload = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    assert payload["templates"] == []


@pytest.mark.asyncio
async def test_operator_owned_scope_is_never_auto_suspended(
    db_session: AsyncSession,
) -> None:
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    template, _recipe = await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    # Ownership is scoped to the EXACT template with an explicit ownership label
    # kind (MEDIUM 13): a generic domain/surface label would not exempt.
    db_session.add(
        ExtractionOperatorLabel(
            label_kind="review_promotion",
            domain=domain,
            surface=_SURFACE_VALUE,
            template_id=template.id,
        )
    )
    await db_session.commit()

    # Even far past the threshold, an operator-owned scope stays active.
    for _ in range(5):
        assert (
            await note_recipe_drift_failure(
                db_session,
                domain=domain,
                surface=_SURFACE_VALUE,
                route_pattern=route_pattern,
                threshold=3,
            )
            is False
        )
    await db_session.commit()

    payload = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    assert len(payload["templates"]) == 1


@pytest.mark.asyncio
async def test_unrelated_operator_label_does_not_exempt(
    db_session: AsyncSession,
) -> None:
    # A label attached to a DIFFERENT template (or none) must not exempt this
    # recipe from drift self-heal (MEDIUM 13 — exact-template scoping).
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    db_session.add(
        ExtractionOperatorLabel(
            label_kind="review_promotion",
            domain=domain,
            surface=_SURFACE_VALUE,
            template_id=None,
        )
    )
    await db_session.commit()

    outcomes = [
        await note_recipe_drift_failure(
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
        for _ in range(3)
    ]
    await db_session.commit()
    assert outcomes == [False, False, True]


@pytest.mark.asyncio
async def test_successful_replay_resets_consecutive_drift(
    db_session: AsyncSession,
) -> None:
    # HIGH 12: drift is CONSECUTIVE — a successful replay resets the counter so
    # scattered, non-consecutive misses never suspend a mostly-working recipe.
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    await db_session.commit()

    # fail, fail, success (reset), fail, fail — never reaches 3 consecutive.
    assert (
        await note_recipe_drift_failure(
            db_session, domain=domain, surface=_SURFACE_VALUE,
            route_pattern=route_pattern, threshold=3,
        )
        is False
    )
    assert (
        await note_recipe_drift_failure(
            db_session, domain=domain, surface=_SURFACE_VALUE,
            route_pattern=route_pattern, threshold=3,
        )
        is False
    )
    await reset_recipe_drift(
        db_session, domain=domain, surface=_SURFACE_VALUE, route_pattern=route_pattern
    )
    assert (
        await note_recipe_drift_failure(
            db_session, domain=domain, surface=_SURFACE_VALUE,
            route_pattern=route_pattern, threshold=3,
        )
        is False
    )
    assert (
        await note_recipe_drift_failure(
            db_session, domain=domain, surface=_SURFACE_VALUE,
            route_pattern=route_pattern, threshold=3,
        )
        is False
    )
    await db_session.commit()

    # Still active because the counter was reset mid-way.
    payload = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    assert len(payload["templates"]) == 1


# --- Finding 5: one persisted recipe (not two) after a retry cycle -----------

_LATCH_URL = "https://latch.example.invalid/products/trail-shoe-red"


def _latch_acquisition_result(*, method: str):
    from app.acquisition.acquirer import AcquisitionRequest, PageAcquisitionResult
    from app.acquisition.runtime_plan import AcquisitionIntent

    return PageAcquisitionResult(
        request=AcquisitionRequest(
            run_id=0,
            url=_LATCH_URL,
            plan=AcquisitionIntent(surface=_SURFACE_VALUE),
        ),
        final_url=_LATCH_URL,
        html=_DETAIL_HTML,
        method=method,
        status_code=200,
        browser_diagnostics={"browser_attempted": method == "browser"},
    )


def _empty_result_with_retry(*, retry_required: bool):
    from app.extraction.contracts import CapabilityRequest, ExtractionResult
    from app.extraction.surfaces import Surface

    retry = (
        CapabilityRequest(
            required=True,
            reason="empty_extraction",
            required_artifacts=("rendered_html",),
        )
        if retry_required
        else None
    )
    return ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        records=(),
        verdict="empty",
        retry_request=retry,
    )


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


# --- Finding 10: durable transactional claim guarantees exactly one compile ---

_CLAIM_URL = "https://claim.example.invalid/products/trail-shoe-red"


async def _run_learn(session, calls, *, delay: float = 0.0):
    import asyncio

    from app.crawl.pipeline.learn_once import learn_recipe_after_extraction
    from app.extraction.contracts import ExtractionResult
    from app.extraction.surfaces import Surface

    async def _client(system_prompt: str, user_prompt: str) -> str:
        calls.append(1)
        if delay:
            await asyncio.sleep(delay)
        return _RESPONSE

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        _DETAIL_HTML,
        _CLAIM_URL,
        requested_fields=("title", "price"),
    )
    empty = ExtractionResult(surface=Surface.ECOMMERCE_DETAIL, records=(), verdict="empty")
    learned = await learn_recipe_after_extraction(
        session,
        request=request,
        result=empty,
        run_id=None,
        llm_enabled=True,
        is_new_template=True,
        model_client=_client,
    )
    if learned:
        await session.commit()
    else:
        await session.rollback()
    return learned


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


# --- Finding 6: exactly-once holds even when the compile yields NO recipe -----

# Grounds to a DOM path that does not exist, so the compiler abstains
# (``candidate is None``) and NOTHING executable is persisted.
_NO_CANDIDATE_RESPONSE = (
    '{"record_root": "", "fields": {'
    '"title": "/html[1]/body[1]/main[1]/h9[7]", '
    '"price": "/html[1]/body[1]/main[1]/span[9]"}}'
)


async def _run_learn_no_candidate(session, calls, *, delay: float = 0.0):
    import asyncio

    from app.crawl.pipeline.learn_once import learn_recipe_after_extraction
    from app.extraction.contracts import ExtractionResult
    from app.extraction.surfaces import Surface

    async def _client(system_prompt: str, user_prompt: str) -> str:
        calls.append(1)
        if delay:
            await asyncio.sleep(delay)
        return _NO_CANDIDATE_RESPONSE

    request = fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        _DETAIL_HTML,
        _CLAIM_URL,
        requested_fields=("title", "price"),
    )
    empty = ExtractionResult(surface=Surface.ECOMMERCE_DETAIL, records=(), verdict="empty")
    learned = await learn_recipe_after_extraction(
        session,
        request=request,
        result=empty,
        run_id=None,
        llm_enabled=True,
        is_new_template=True,
        model_client=_client,
    )
    if learned:
        await session.commit()
    else:
        await session.rollback()
    return learned


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


# --- Finding 12: production reset caller clears drift on a grounded replay ----


def _recipe_tier_result(*, records: tuple = ({"title": "x"},)):
    from app.extraction.contracts import DiagnosticSummary, ExtractionResult
    from app.extraction.surfaces import Surface

    return ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        records=records,
        verdict="success" if records else "empty",
        diagnostics=DiagnosticSummary(extractor_tier="recipe"),
    )


@pytest.mark.asyncio
async def test_reset_caller_clears_drift_between_scattered_misses(
    db_session: AsyncSession,
) -> None:
    # HIGH 12: the production reset seam
    # (``reset_recipe_drift_after_successful_replay``) resets the CONSECUTIVE
    # drift counter on a grounded recipe-tier replay, so drift -> success ->
    # drift never suspends a mostly-working recipe.
    from app.crawl.pipeline.learn_once import (
        reset_recipe_drift_after_successful_replay,
    )

    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    await db_session.commit()

    # Two misses accumulate (threshold 3).
    for _ in range(2):
        assert (
            await note_recipe_drift_failure(
                db_session, domain=domain, surface=_SURFACE_VALUE,
                route_pattern=route_pattern, threshold=3,
            )
            is False
        )

    # A grounded recipe-tier replay resets the counter through the production seam.
    await reset_recipe_drift_after_successful_replay(
        db_session,
        url=_DETAIL_URL,
        surface=_SURFACE_VALUE,
        result=_recipe_tier_result(),
    )

    # Two more misses still never reach 3 CONSECUTIVE — recipe stays active.
    for _ in range(2):
        assert (
            await note_recipe_drift_failure(
                db_session, domain=domain, surface=_SURFACE_VALUE,
                route_pattern=route_pattern, threshold=3,
            )
            is False
        )
    await db_session.commit()

    payload = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    assert len(payload["templates"]) == 1


@pytest.mark.asyncio
async def test_reset_caller_ignores_non_recipe_and_empty_results(
    db_session: AsyncSession,
) -> None:
    # Finding 12: only a real grounded recipe-tier replay WITH records resets the
    # counter — a deterministic/empty result must leave drift untouched so a
    # genuinely broken recipe still self-heals.
    from app.crawl.pipeline.learn_once import (
        reset_recipe_drift_after_successful_replay,
    )
    from app.extraction.contracts import DiagnosticSummary, ExtractionResult
    from app.extraction.surfaces import Surface

    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    await db_session.commit()

    for _ in range(2):
        await note_recipe_drift_failure(
            db_session, domain=domain, surface=_SURFACE_VALUE,
            route_pattern=route_pattern, threshold=3,
        )

    # An empty recipe-tier result and a non-recipe result must NOT reset.
    await reset_recipe_drift_after_successful_replay(
        db_session, url=_DETAIL_URL, surface=_SURFACE_VALUE,
        result=_recipe_tier_result(records=()),
    )
    await reset_recipe_drift_after_successful_replay(
        db_session, url=_DETAIL_URL, surface=_SURFACE_VALUE,
        result=ExtractionResult(
            surface=Surface.ECOMMERCE_DETAIL,
            records=({"title": "x"},),
            verdict="success",
            diagnostics=DiagnosticSummary(extractor_tier="deterministic"),
        ),
    )

    # The counter was never reset, so the third consecutive miss suspends.
    assert (
        await note_recipe_drift_failure(
            db_session, domain=domain, surface=_SURFACE_VALUE,
            route_pattern=route_pattern, threshold=3,
        )
        is True
    )


# --- Finding 13: operator-scope exemption is EXACT-template only --------------


@pytest.mark.asyncio
async def test_operator_label_on_sibling_template_does_not_exempt(
    db_session: AsyncSession,
) -> None:
    # MEDIUM 13 (hardening): an ownership label attached to a DIFFERENT template
    # of the SAME domain/surface must not exempt this recipe from drift
    # self-heal. Exemption is scoped to the exact template_id, never domain or
    # surface, so the target recipe still auto-suspends at threshold.
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    target_template, _recipe = await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )

    # A SIBLING template (same domain + surface, different route/fingerprint)
    # that carries the operator ownership label.
    sibling_route = normalize_route(
        "https://shop.test/category/shoes", _SURFACE_VALUE
    )
    assert sibling_route != route_pattern
    sibling_fp = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, sibling_route
    )
    sibling_template, _sib_recipe = await _persist_recipe(
        db_session,
        domain=domain,
        route_pattern=sibling_route,
        fingerprint=sibling_fp,
    )
    assert sibling_template.id != target_template.id
    db_session.add(
        ExtractionOperatorLabel(
            label_kind="review_promotion",
            domain=domain,
            surface=_SURFACE_VALUE,
            template_id=sibling_template.id,
        )
    )
    await db_session.commit()

    # The target template's recipe self-heals at threshold despite the sibling
    # ownership label — the exemption never leaks across templates.
    outcomes = [
        await note_recipe_drift_failure(
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
        for _ in range(3)
    ]
    await db_session.commit()
    assert outcomes == [False, False, True]
# --- Finding 15: LEARN-ONCE never accumulates detached (run_id NULL) snapshots


@pytest.mark.asyncio
async def test_learn_cycle_creates_no_detached_release_snapshot(
    db_session: AsyncSession, test_user
) -> None:
    # MEDIUM 15: persisting a learned recipe (and building the next run's release)
    # must add ZERO ``ExtractionReleaseSnapshot`` rows with ``run_id IS NULL``.
    # Detached candidate snapshots only come from grounded_corrections (which
    # activates them immediately for a run); the learn path must never mint one.
    from sqlalchemy import func, select

    from app.crawl.crud import create_crawl_run
    from app.models.extraction_memory import ExtractionReleaseSnapshot

    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await _persist_recipe(
        db_session, domain=domain, route_pattern=route_pattern, fingerprint=fingerprint
    )
    await db_session.commit()

    # A genuine subsequent run builds the unified release through create_crawl_run.
    await create_crawl_run(
        db_session,
        test_user.id,
        {"run_type": "crawl", "url": _DETAIL_URL, "surface": _SURFACE_VALUE},
    )

    detached = await db_session.scalar(
        select(func.count())
        .select_from(ExtractionReleaseSnapshot)
        .where(ExtractionReleaseSnapshot.run_id.is_(None))
    )
    assert detached == 0
