from __future__ import annotations

import pytest

from app.core.config.extraction_memory import EXTRACTION_EXECUTABLE_RELEASE_VERSION
from app.core.extraction_memory.recipe_compiler import compile_recipe
from app.core.extraction_memory.templates import normalize_route
from app.crawl.pipeline.learn_once import should_attempt_learn_once
from app.extraction.engine import extract
from app.extraction.replay import fixture_request_from_inputs
from app.extraction.surfaces import Surface, listing_schema, surface_spec

pytestmark = pytest.mark.unit

_DETAIL_HTML = (
    "<html><body><main>"
    "<h1>Trail Shoe Red</h1>"
    '<a href="/products/trail-shoe-red" rel="canonical">self</a>'
    '<span class="price">$129.99</span>'
    '<img src="/img/red.jpg">'
    "</main></body></html>"
)
_DETAIL_URL = "https://shop.test/products/trail-shoe-red"
_DETAIL_RESPONSE = (
    '{"record_root": "", "fields": {'
    '"title": "/html[1]/body[1]/main[1]/h1[1]", '
    '"price": "/html[1]/body[1]/main[1]/span[1]"}}'
)


def _detail_request(html: str = _DETAIL_HTML):
    return fixture_request_from_inputs(
        Surface.ECOMMERCE_DETAIL,
        html,
        _DETAIL_URL,
        requested_fields=("title", "price", "image"),
    )


def _stub(response: str, calls: list[int]):
    async def _client(system_prompt: str, user_prompt: str) -> str:
        calls.append(1)
        return response

    return _client


async def _learn_recipe(request, response, calls):
    discovery = await compile_recipe(
        request,
        surface_spec=surface_spec(Surface.ECOMMERCE_DETAIL),
        listing_schema=listing_schema(Surface.ECOMMERCE_DETAIL),
        model_client=_stub(response, calls),
    )
    return discovery.candidate.recipe


def _release_snapshot(recipe, *, surface: str, url: str) -> dict[str, object]:
    return {
        "schema_version": EXTRACTION_EXECUTABLE_RELEASE_VERSION,
        "surface": surface,
        "templates": [
            {
                "template_id": 1,
                "route_pattern": normalize_route(url, surface),
                "status": "active",
                "compiled_recipe": recipe.model_dump(mode="json"),
            }
        ],
    }


@pytest.mark.asyncio
async def test_first_crawl_learns_once_then_replays_with_zero_model_calls() -> None:
    # First crawl: the compiler learns from the DOM with exactly one model call.
    calls: list[int] = []
    recipe = await _learn_recipe(_detail_request(), _DETAIL_RESPONSE, calls)
    assert len(calls) == 1

    # A subsequent crawl of the same route replays the stored recipe. Replay is
    # pure/synchronous and must not consult the model at all.
    calls.clear()
    snapshot = _release_snapshot(recipe, surface="ecommerce_detail", url=_DETAIL_URL)
    request = _detail_request().model_copy(update={"runtime_snapshot": snapshot})
    result = extract(request)

    assert calls == []
    assert result.diagnostics.extractor_tier == "recipe"
    assert len(result.records) == 1
    assert result.records[0].get("title") == "Trail Shoe Red"
    assert result.recipe_execution is not None


@pytest.mark.asyncio
async def test_drift_falls_through_to_deterministic_floors() -> None:
    # Learn a recipe against the canonical page, then replay it against a page
    # whose DOM has drifted so the stored xpaths no longer ground.
    recipe = await _learn_recipe(_detail_request(), _DETAIL_RESPONSE, [])
    snapshot = _release_snapshot(recipe, surface="ecommerce_detail", url=_DETAIL_URL)
    drifted_html = "<html><body><section><div><p>Nothing here</p></div></section></body></html>"
    request = _detail_request(html=drifted_html).model_copy(
        update={"runtime_snapshot": snapshot}
    )

    result = extract(request)

    # Drift never yields a recipe-tier result; the engine falls through.
    assert result.diagnostics.extractor_tier != "recipe"


def test_no_snapshot_never_replays() -> None:
    result = extract(_detail_request())
    assert result.diagnostics.extractor_tier != "recipe"


def test_learn_gate_requires_all_conditions() -> None:
    base = dict(
        surface="ecommerce_detail",
        llm_enabled=True,
        floors_empty=True,
        is_new_template=True,
    )
    assert should_attempt_learn_once(**base) is True
    assert should_attempt_learn_once(**{**base, "llm_enabled": False}) is False
    assert should_attempt_learn_once(**{**base, "floors_empty": False}) is False
    assert should_attempt_learn_once(**{**base, "is_new_template": False}) is False


def test_learn_gate_respects_surface_allow_list() -> None:
    # job_detail is intentionally excluded from the LEARN-ONCE allow-list.
    assert (
        should_attempt_learn_once(
            surface="job_detail",
            llm_enabled=True,
            floors_empty=True,
            is_new_template=True,
        )
        is False
    )
