from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.api import crawl_domain as crawl_domain_api
from app.models.extraction_memory import ExtractionOperatorLabel as DomainFieldFeedback
from app.crawl.batch_runtime import process_run
from app.acquisition.cookie_store import persist_storage_state_for_domain
from app.acquisition.acquirer import PageAcquisitionResult
from app.crawl.crud import create_crawl_run
from app.crawl.domain_memory_service import save_domain_memory
from app.evaluation.grounded_corrections import GroundedCorrectionScopeMismatch
from app.core.security import hash_password
from app.models.user import User


def _authenticated_proxy_url() -> str:
    return "http://user:" + "secret" + "@example-proxy.local:8080"


@pytest.fixture
async def crawls_api_client(db_session, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_logs_query_params_are_validated(
    crawls_api_client: AsyncClient,
) -> None:
    response = await crawls_api_client.get(
        "/api/crawls/1/logs",
        params={"after_id": -1, "limit": 2001},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.component
async def test_ordinary_user_cannot_promote_global_run_memory(
    crawls_api_client: AsyncClient,
    db_session,
) -> None:
    ordinary = User(
        email="ordinary-memory@example.com",
        hashed_password=hash_password("password123"),
        role="user",
    )
    db_session.add(ordinary)
    await db_session.commit()

    async def _ordinary_user():
        return ordinary

    app.dependency_overrides[get_current_user] = _ordinary_user
    save_response = await crawls_api_client.post(
        "/api/crawls/1/domain-recipe/save-run-profile",
        json={"profile": {}},
    )
    correction_response = await crawls_api_client.post(
        "/api/crawls/1/corrections",
        json={"labels": []},
    )

    assert save_response.status_code == 403
    assert correction_response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_recipe_does_not_mark_browser_required_from_summary_usage_only(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://domain-recipe.example.invalid/products/summary-only-widget",
            "surface": "ecommerce_detail",
        },
    )
    run.result_summary = {"acquisition_summary": {"methods": {"browser": 1}}}
    await db_session.commit()

    response = await crawls_api_client.get(f"/api/crawls/{run.id}/domain-recipe")

    assert response.status_code == 200
    recipe = response.json()
    assert recipe["acquisition_evidence"]["actual_fetch_method"] == "browser"
    assert recipe["acquisition_evidence"]["browser_used"] is True
    assert recipe["affordance_candidates"]["browser_required"] is False


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_domain_recipe_routes_round_trip(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lookup_before_run = await crawls_api_client.get(
        "/api/crawls/domain-run-profile",
        params={
            "url": "https://domain-recipe.example.invalid/products/domain-recipe-widget",
            "surface": "ecommerce_detail",
        },
    )
    assert (lookup_before_run.status_code, lookup_before_run.json()) == (
        200,
        {
            "domain": "domain-recipe.example.invalid",
            "surface": "ecommerce_detail",
            "saved_run_profile": None,
        },
    )

    await save_domain_memory(
        db_session,
        domain="domain-recipe.example.invalid",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {
                    "id": 1,
                    "field_name": "title",
                    "css_selector": ".saved-title",
                    "sample_value": "Saved Selector Widget",
                    "source": "domain_memory",
                    "status": "validated",
                    "is_active": True,
                    "source_run_id": 41,
                }
            ]
        },
    )
    await db_session.commit()

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://domain-recipe.example.invalid/products/domain-recipe-widget",
            "surface": "ecommerce_detail",
            "additional_fields": ["brand"],
            "settings": {
                "extraction_contract": [
                    {
                        "field_name": "price",
                        "css_selector": ".run-price",
                    }
                ]
            },
        },
    )

    async def _fake_acquire(request):
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html="""
            <html>
              <body>
                <div class="saved-title">Saved Selector Widget</div>
                <div class="run-price">$19.99</div>
                <div class="brand">Example Brand</div>
              </body>
            </html>
            """,
            method="browser",
            status_code=200,
            browser_diagnostics={"browser_reason": "http-escalation"},
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    recipe_response = await crawls_api_client.get(f"/api/crawls/{run.id}/domain-recipe")
    recipe = recipe_response.json()
    assert (
        recipe_response.status_code,
        recipe["requested_field_coverage"],
        recipe["affordance_candidates"]["browser_required"],
        recipe["acquisition_evidence"]["actual_fetch_method"],
        recipe["acquisition_evidence"]["browser_reason"],
    ) == (
        200,
        {"requested": ["brand"], "found": ["brand"], "missing": []},
        True,
        "browser",
        "http-escalation",
    )
    assert {row["field_name"] for row in recipe["selector_candidates"]} == {
        "brand",
        "price",
        "title",
    }
    if recipe["saved_run_profile"] is not None:
        assert "proxy_profile" not in recipe["saved_run_profile"]

    save_profile_response = await crawls_api_client.post(
        f"/api/crawls/{run.id}/domain-recipe/save-run-profile",
        json={
            "profile": {
                "fetch_profile": {
                    "fetch_mode": "http_then_browser",
                    "extraction_source": "rendered_dom",
                    "js_mode": "enabled",
                    "include_iframes": False,
                    "traversal_mode": "paginate",
                    "request_delay_ms": 1200,
                    "max_pages": 8,
                    "max_scrolls": 12,
                },
                "locality_profile": {
                    "geo_country": "IN",
                    "language_hint": "en-IN",
                    "currency_hint": "INR",
                },
                "diagnostics_profile": {
                    "capture_html": True,
                    "capture_screenshot": False,
                    "capture_network": "matched_only",
                    "capture_response_headers": True,
                    "capture_browser_diagnostics": True,
                },
                "acquisition_contract": {
                    "preferred_browser_engine": "real_chrome",
                    "prefer_browser": True,
                    "handoff_eligible": True,
                    "handoff_cookie_engine": "real_chrome",
                    "last_quality_success": None,
                    "required_rendering": False,
                    "required_traversal": False,
                    "required_network_payloads": False,
                    "stale_after_failures": {"failure_count": 0, "stale": False},
                },
                "proxy_profile": {
                    "enabled": True,
                    "proxy_list": [
                        _authenticated_proxy_url(),
                        "https://clean-proxy.example:8443",
                    ],
                },
            }
        },
    )
    saved_profile = save_profile_response.json()
    assert (
        save_profile_response.status_code,
        saved_profile["fetch_profile"]["fetch_mode"],
        saved_profile["acquisition_contract"]["preferred_browser_engine"],
        saved_profile["acquisition_contract"]["handoff_eligible"],
        saved_profile["locality_profile"]["geo_country"],
        saved_profile["source_run_id"],
        "proxy_profile" in saved_profile,
    ) == (
        200,
        "http_then_browser",
        "real_chrome",
        True,
        "IN",
        run.id,
        False,
    )

    lookup_after_save = await crawls_api_client.get(
        "/api/crawls/domain-run-profile",
        params={
            "url": "https://domain-recipe.example.invalid/products/domain-recipe-widget",
            "surface": "ecommerce_detail",
        },
    )
    assert (
        lookup_after_save.status_code,
        lookup_after_save.json()["saved_run_profile"]["fetch_profile"]["fetch_mode"],
        "proxy_profile" in lookup_after_save.json()["saved_run_profile"],
    ) == (
        200,
        "http_then_browser",
        False,
    )

    list_profiles_response = await crawls_api_client.get(
        "/api/crawls/domain-memory/run-profiles",
        params={"domain": "domain-recipe.example.invalid"},
    )
    listed_profile = list_profiles_response.json()[0]
    assert (
        list_profiles_response.status_code,
        listed_profile["domain"],
        listed_profile["surface"],
        listed_profile["profile"]["fetch_profile"]["fetch_mode"],
    ) == (
        200,
        "domain-recipe.example.invalid",
        "ecommerce_detail",
        "http_then_browser",
    )

    normalized_profiles_response = await crawls_api_client.get(
        "/api/crawls/domain-memory/run-profiles",
        params={
            "domain": "HTTPS://domain-recipe.example.invalid/products/domain-recipe-widget",
            "surface": " ECOMMERCE_DETAIL ",
        },
    )
    assert (
        normalized_profiles_response.status_code,
        len(normalized_profiles_response.json()),
    ) == (200, 1)

    recipe_after_save = await crawls_api_client.get(
        f"/api/crawls/{run.id}/domain-recipe"
    )
    saved_recipe = recipe_after_save.json()
    assert (
        recipe_after_save.status_code,
        saved_recipe["saved_run_profile"]["fetch_profile"]["fetch_mode"],
        "proxy_profile" in saved_recipe["saved_run_profile"],
    ) == (
        200,
        "http_then_browser",
        False,
    )

    await persist_storage_state_for_domain(
        "domain-recipe.example.invalid",
        {
            "cookies": [
                {
                    "name": "session",
                    "value": "abc",
                    "domain": ".domain-recipe.example.invalid",
                    "path": "/",
                }
            ],
            "origins": [],
        },
        session=db_session,
        user_id=test_user.id,
    )
    cookies_response = await crawls_api_client.get(
        "/api/crawls/domain-memory/cookies",
        params={"domain": "domain-recipe.example.invalid"},
    )
    assert (
        cookies_response.status_code,
        cookies_response.json()[0]["domain"],
        cookies_response.json()[0]["cookie_count"],
    ) == (200, "domain-recipe.example.invalid", 1)

    feedback_response = await crawls_api_client.get(
        "/api/crawls/domain-memory/field-feedback",
        params={
            "domain": "domain-recipe.example.invalid",
            "surface": "ecommerce_detail",
        },
    )
    assert (feedback_response.status_code, feedback_response.json()) == (200, [])


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_grounded_correction_route_enforces_replay_gate(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://domain-recipe.example.invalid/products/correction-widget",
            "surface": "ecommerce_detail",
        },
    )
    run_id = run.id

    accepted_response = await crawls_api_client.post(
        f"/api/crawls/{run_id}/corrections",
        json={
            "activate": True,
            "representative_url_result_ids": [101],
            "labels": [
                {
                    "target_kind": "field",
                    "subject_id": "product:1",
                    "field_name": "price",
                    "canonical_value": "19.99",
                    "semantic_role": "primary_price",
                    "locale_interpretation": "USD",
                    "grounding": [
                        {
                            "kind": "node",
                            "artifact_id": "url-result:1:html",
                            "locator": "css:.price",
                        }
                    ],
                }
            ],
        },
    )

    assert accepted_response.status_code == 200
    payload = accepted_response.json()
    assert payload["activation_status"] == "replay_failed"
    assert payload["replay"]["passed"] is False
    assert payload["replay"]["reason"] == "representative_results_not_owned_by_run"
    label = (
        await db_session.execute(
            select(DomainFieldFeedback)
            .where(DomainFieldFeedback.id == payload["correction_id"])
            .limit(1)
        )
    ).scalar_one()
    assert label.label_kind == "grounded_correction"
    assert label.payload["labels"][0]["grounding"][0]["locator"] == "css:.price"


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_grounded_correction_route_maps_scope_mismatch_to_conflict(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://domain-recipe.example.invalid/products/correction-widget",
            "surface": "ecommerce_detail",
        },
    )

    async def _raise_scope_mismatch(*args, **kwargs):
        raise GroundedCorrectionScopeMismatch("template scope mismatch")

    monkeypatch.setattr(
        crawl_domain_api,
        "save_grounded_correction",
        _raise_scope_mismatch,
    )
    response = await crawls_api_client.post(
        f"/api/crawls/{run.id}/corrections",
        json={
            "activate": True,
            "representative_url_result_ids": [1],
            "labels": [
                {
                    "target_kind": "field",
                    "subject_id": "product:1",
                    "field_name": "price",
                    "canonical_value": "19.99",
                    "semantic_role": "primary_price",
                    "locale_interpretation": "USD",
                    "grounding": [
                        {
                            "kind": "node",
                            "artifact_id": "url-result:1:html",
                            "locator": "css:.price",
                        }
                    ],
                }
            ],
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "template scope mismatch"


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_run_profile_contract_autosaves_real_chrome_success(
    crawls_api_client: AsyncClient,
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://domain-recipe.example.invalid/products/real-chrome-widget",
            "surface": "ecommerce_detail",
            "requested_fields": ["title"],
            "settings": {},
        },
    )

    async def _fake_acquire(request):
        return PageAcquisitionResult(
            request=request,
            final_url=request.url,
            html="<html><body><h1>Real Chrome Widget</h1></body></html>",
            method="browser",
            status_code=200,
            browser_diagnostics={
                "browser_reason": "acquisition-contract",
                "browser_engine": "real_chrome",
            },
        )

    monkeypatch.setattr("app.crawl.pipeline.extraction_loop.acquire", _fake_acquire)

    await process_run(db_session, run.id)

    lookup = await crawls_api_client.get(
        "/api/crawls/domain-run-profile",
        params={
            "url": "https://domain-recipe.example.invalid/products/real-chrome-widget",
            "surface": "ecommerce_detail",
        },
    )
    assert lookup.status_code == 200
    contract = lookup.json()["saved_run_profile"]["acquisition_contract"]
    assert contract["preferred_browser_engine"] == "real_chrome"
    assert contract["prefer_browser"] is True
    assert contract["handoff_eligible"] is True
    assert contract["handoff_cookie_engine"] == "real_chrome"
    assert contract["required_rendering"] is False
    assert contract["required_traversal"] is False
    assert contract["required_network_payloads"] is False
    assert contract["last_quality_success"]["field_coverage"] == {
        "requested": ["title", "price", "image_url"],
        "found": ["title"],
        "missing": ["price", "image_url"],
    }
    assert contract["stale_after_failures"] == {"failure_count": 0, "stale": False}
