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
