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
    empty = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL, records=(), verdict="empty"
    )
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
    empty = ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL, records=(), verdict="empty"
    )
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


def _recipe_tier_result(*, records: tuple = ({"title": "x"},)):
    from app.extraction.contracts import DiagnosticSummary, ExtractionResult
    from app.extraction.surfaces import Surface

    return ExtractionResult(
        surface=Surface.ECOMMERCE_DETAIL,
        records=records,
        verdict="success" if records else "empty",
        diagnostics=DiagnosticSummary(extractor_tier="recipe"),
    )


__all__ = [
    "_CLAIM_URL",
    "_DETAIL_HTML",
    "_DETAIL_URL",
    "_LATCH_URL",
    "_NO_CANDIDATE_RESPONSE",
    "_RESPONSE",
    "_SURFACE_VALUE",
    "AsyncSession",
    "ExtractionOperatorLabel",
    "Surface",
    "_empty_result_with_retry",
    "_latch_acquisition_result",
    "_learned_recipe",
    "_persist_recipe",
    "_recipe_tier_result",
    "_run_learn",
    "_run_learn_no_candidate",
    "build_release_payload",
    "compile_recipe",
    "fixture_request_from_inputs",
    "listing_schema",
    "normalize_route",
    "note_recipe_drift_failure",
    "persist_learned_recipe",
    "pytest",
    "pytestmark",
    "reset_recipe_drift",
    "select_active_recipe",
    "stable_id",
    "surface_spec",
]
