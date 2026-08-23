"""test_learn_once_persistence cases split by public behavior."""

from __future__ import annotations

from tests.component.learn_once_persistence_test_support import (
    AsyncSession,
    ExtractionOperatorLabel,
    _DETAIL_URL,
    _SURFACE_VALUE,
    _learned_recipe,
    _persist_recipe,
    _recipe_tier_result,
    build_release_payload,
    normalize_route,
    note_recipe_drift_failure,
    persist_learned_recipe,
    pytest,
    pytestmark as _component_pytestmark,
    stable_id,
)

pytestmark = _component_pytestmark


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
                db_session,
                domain=domain,
                surface=_SURFACE_VALUE,
                route_pattern=route_pattern,
                threshold=3,
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
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )

    # An empty recipe-tier result and a non-recipe result must NOT reset.
    await reset_recipe_drift_after_successful_replay(
        db_session,
        url=_DETAIL_URL,
        surface=_SURFACE_VALUE,
        result=_recipe_tier_result(records=()),
    )
    await reset_recipe_drift_after_successful_replay(
        db_session,
        url=_DETAIL_URL,
        surface=_SURFACE_VALUE,
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
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
        is True
    )


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
    sibling_route = normalize_route("https://shop.test/category/shoes", _SURFACE_VALUE)
    assert sibling_route != route_pattern
    sibling_fp = stable_id("learn-once-template", domain, _SURFACE_VALUE, sibling_route)
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


@pytest.mark.asyncio
async def test_persist_lock_wait_is_bounded_and_fails_closed(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Finding 7: a persist racing a writer that HOLDS the template row must not
    # wait indefinitely. With the bound shrunk to 200ms, the blocked persist
    # must exit within the configured bound (not hang), roll back, and raise
    # the typed error the learn seam maps to an honest no-learn.
    import asyncio
    import time

    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import async_sessionmaker

    import app.persistence.extraction_memory as extraction_memory
    from app.models.extraction_memory import ExtractionTemplate

    LearnOncePersistLockTimeout = extraction_memory.LearnOncePersistLockTimeout
    ensure_template = extraction_memory.ensure_template

    monkeypatch.setattr(
        extraction_memory, "CASCADE_LEARN_ONCE_CLAIM_LOCK_TIMEOUT_MS", 200
    )

    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    # Create the template up front so the contending holder has a row to lock.
    template = await ensure_template(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        fingerprint=fingerprint,
        route_pattern=route_pattern,
    )
    await db_session.commit()

    session_factory = async_sessionmaker(
        bind=db_session.bind, expire_on_commit=False, class_=AsyncSession
    )

    holder_acquired = asyncio.Event()
    release_holder = asyncio.Event()

    async def _hold_template_lock() -> None:
        # A peer writer holding the template row lock across its transaction —
        # the exact contention persist_learned_recipe must bound against.
        async with session_factory() as holder:
            await holder.execute(
                select(ExtractionTemplate.id)
                .where(ExtractionTemplate.id == template.id)
                .with_for_update()
            )
            holder_acquired.set()
            await release_holder.wait()
            await holder.rollback()

    holder_task = asyncio.create_task(_hold_template_lock())
    try:
        await asyncio.wait_for(holder_acquired.wait(), timeout=5)
        recipe = await _learned_recipe()
        started = time.monotonic()
        async with session_factory() as blocked:
            with pytest.raises(LearnOncePersistLockTimeout):
                await persist_learned_recipe(
                    blocked,
                    domain=domain,
                    surface=_SURFACE_VALUE,
                    route_pattern=route_pattern,
                    fingerprint=fingerprint,
                    recipe_payload=recipe.model_dump(mode="json"),
                    confidence=0.75,
                )
            elapsed = time.monotonic() - started
            # Exited within the configured bound (200ms) plus slack — it did
            # NOT wait for the holder, which is still holding the lock.
            assert elapsed < 3.0
            # Fail-closed rollback left the session clean and usable.
            assert (await blocked.execute(text("SELECT 1"))).scalar_one() == 1
    finally:
        release_holder.set()
        await asyncio.gather(holder_task, return_exceptions=True)

    # Once the holder releases, the same scope persists normally: the timeout
    # is a bounded wait, not a permanent failure.
    template_after, stored = await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=recipe.model_dump(mode="json"),
        confidence=0.75,
    )
    await db_session.commit()
    assert template_after.id == template.id
    assert stored.status == "active"
