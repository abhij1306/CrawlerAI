"""test_learn_once_persistence cases split by public behavior."""

from __future__ import annotations

from tests.component.learn_once_persistence_test_support import (
    AsyncSession,
    ExtractionOperatorLabel,
    _DETAIL_URL,
    _SURFACE_VALUE,
    _learned_recipe,
    _persist_recipe,
    build_release_payload,
    normalize_route,
    note_recipe_drift_failure,
    persist_learned_recipe,
    pytest,
    pytestmark as _component_pytestmark,
    reset_recipe_drift,
    select_active_recipe,
    stable_id,
)

pytestmark = _component_pytestmark


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


@pytest.mark.asyncio
async def test_drift_suspends_recipe_after_threshold(db_session: AsyncSession) -> None:
    domain = "shop.test"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await _persist_recipe(
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
    await reset_recipe_drift(
        db_session, domain=domain, surface=_SURFACE_VALUE, route_pattern=route_pattern
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
        is False
    )
    await db_session.commit()

    # Still active because the counter was reset mid-way.
    payload = await build_release_payload(
        db_session, domain=domain, surface=_SURFACE_VALUE
    )
    assert len(payload["templates"]) == 1
