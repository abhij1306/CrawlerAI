"""End-to-end proof that a learned recipe replays on a genuine subsequent run.

CRITICAL 1 regression guard: a recipe learned on the first crawl must be picked
up by the NEXT run through the real ``create_crawl_run`` /
``create_release_snapshot`` path (no detached snapshot), loaded exactly as the
pipeline loads it (``load_release_payload``), and replayed by ``extract`` with
ZERO model calls.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.extraction_memory.contract_runtime import select_active_recipe
from app.core.extraction_memory.recipe_compiler import compile_recipe
from app.core.extraction_memory.templates import normalize_route
from app.core.shared.ids import stable_id
from app.crawl.crud import create_crawl_run
from app.extraction.engine import extract
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface, listing_schema, surface_spec
from app.persistence.extraction_memory import (
    load_release_payload,
    persist_learned_recipe,
)

pytestmark = [pytest.mark.component, pytest.mark.asyncio]

_DETAIL_HTML = (
    "<html><body><main>"
    "<h1>Trail Shoe Red</h1>"
    '<a href="/products/trail-shoe-red" rel="canonical">self</a>'
    '<span class="price">129.99</span>'
    '<span class="cur">USD</span>'
    "</main></body></html>"
)
_DETAIL_URL = "https://prod-replay.example.invalid/products/trail-shoe-red"
_SURFACE_VALUE = "ecommerce_detail"
_RESPONSE = (
    '{"record_root": "", "fields": {'
    '"title": "/html[1]/body[1]/main[1]/h1[1]", '
    '"price": "/html[1]/body[1]/main[1]/span[1]", '
    '"currency": "/html[1]/body[1]/main[1]/span[2]"}}'
)


def _detail_request():
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        _DETAIL_HTML,
        _DETAIL_URL,
        requested_fields=("title", "price"),
    )


async def _learn_recipe(calls: list[int]):
    async def _client(system_prompt: str, user_prompt: str) -> str:
        calls.append(1)
        return _RESPONSE

    discovery = await compile_recipe(
        _detail_request(),
        surface_spec=surface_spec(Surface.ECOMMERCE_DETAIL),
        listing_schema=listing_schema(Surface.ECOMMERCE_DETAIL),
        model_client=_client,
    )
    assert discovery.candidate is not None
    return discovery.candidate.recipe


async def test_subsequent_run_replays_learned_recipe_with_zero_model_calls(
    db_session: AsyncSession, test_user
) -> None:
    # First crawl: compiler learns from the DOM with exactly one model call.
    calls: list[int] = []
    recipe = await _learn_recipe(calls)
    assert len(calls) == 1

    domain = "prod-replay.example.invalid"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=recipe.model_dump(mode="json"),
        confidence=0.75,
    )
    await db_session.commit()

    # A genuine subsequent run: create_crawl_run builds the release snapshot via
    # the production create_release_snapshot/build_release_payload path.
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": _DETAIL_URL,
            "surface": _SURFACE_VALUE,
        },
    )
    assert run.extraction_release_snapshot_id is not None

    # Load the snapshot exactly as the pipeline does.
    snapshot = await load_release_payload(
        db_session, run.extraction_release_snapshot_id
    )

    # The unified release payload activates the learned recipe for this run.
    assert (
        select_active_recipe(snapshot, surface=_SURFACE_VALUE, url=_DETAIL_URL)
        is not None
    )

    # Replay: pure/synchronous, zero model calls, recipe-tier records.
    calls.clear()
    request = _detail_request().model_copy(update={"runtime_snapshot": snapshot})
    result = extract(request)

    assert calls == []
    assert result.diagnostics.extractor_tier == "recipe"
    assert len(result.records) == 1
    assert result.records[0].get("title") == "Trail Shoe Red"


async def test_recipe_tier_replay_resets_drift_counter(
    db_session: AsyncSession, test_user
) -> None:
    # HIGH 12: after a genuine recipe-tier replay, the production reset seam
    # clears the recipe payload's consecutive drift counter to zero.
    from app.crawl.pipeline.learn_once import (
        reset_recipe_drift_after_successful_replay,
    )
    from app.persistence.extraction_memory import note_recipe_drift_failure

    calls: list[int] = []
    recipe = await _learn_recipe(calls)

    domain = "prod-replay.example.invalid"
    route_pattern = normalize_route(_DETAIL_URL, _SURFACE_VALUE)
    fingerprint = stable_id(
        "learn-once-template", domain, _SURFACE_VALUE, route_pattern
    )
    await persist_learned_recipe(
        db_session,
        domain=domain,
        surface=_SURFACE_VALUE,
        route_pattern=route_pattern,
        fingerprint=fingerprint,
        recipe_payload=recipe.model_dump(mode="json"),
        confidence=0.75,
    )
    await db_session.commit()

    # Seed a couple of consecutive drift misses so the counter is non-zero.
    for _ in range(2):
        await note_recipe_drift_failure(
            db_session,
            domain=domain,
            surface=_SURFACE_VALUE,
            route_pattern=route_pattern,
            threshold=3,
        )
    await db_session.commit()

    # A genuine subsequent run replays the recipe with zero model calls.
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {"run_type": "crawl", "url": _DETAIL_URL, "surface": _SURFACE_VALUE},
    )
    snapshot = await load_release_payload(
        db_session, run.extraction_release_snapshot_id
    )
    calls.clear()
    request = _detail_request().model_copy(update={"runtime_snapshot": snapshot})
    result = extract(request)
    assert calls == []
    assert result.diagnostics.extractor_tier == "recipe"
    assert len(result.records) == 1

    # The production reset seam runs on the grounded replay and zeroes the counter.
    await reset_recipe_drift_after_successful_replay(
        db_session,
        url=_DETAIL_URL,
        surface=_SURFACE_VALUE,
        result=result,
    )
    await db_session.commit()

    from sqlalchemy import select

    from app.models.extraction_memory import ExtractionRecipe

    stored = (
        await db_session.execute(select(ExtractionRecipe))
    ).scalars().all()
    payloads = [r.payload.get("_stale_after_failures") for r in stored]
    assert any(
        isinstance(p, dict) and p.get("failure_count") == 0 for p in payloads
    ), payloads
