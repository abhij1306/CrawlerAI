from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)
from app.core.dependencies import get_current_user, get_db, require_admin
from app.main import app
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionRecipe,
    ExtractionTemplate,
)
from app.persistence.extraction_memory import ensure_template, upsert_recipe


@pytest.fixture
async def memory_api_client(db_session: AsyncSession, test_user):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    app.dependency_overrides[require_admin] = _override_user
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_extraction_memory_api_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        response = await client.get("/api/knowledge/sites")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_memory_api_requires_admin(
    db_session: AsyncSession, test_user
) -> None:
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    test_user.role = "user"
    await db_session.commit()
    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/api/knowledge/memory", params={"domain": "example.com"}
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
@pytest.mark.component
async def test_selector_contract_compiles_into_single_recipe_store(
    db_session: AsyncSession, memory_api_client: AsyncClient
) -> None:
    selector = "[data-field='brand']"
    response = await memory_api_client.post(
        "/api/knowledge/contracts/selector",
        json={
            "domain": "Example.COM",
            "url": "https://example.com/products/widget-1",
            "surface": "ecommerce_detail",
            "field_name": "brand",
            "css_selector": selector,
            "sample_value": "ACME",
        },
    )

    assert response.status_code == 200
    contract = response.json()["contract"]
    assert contract["canonical_field"] == "product.brand"
    assert contract["selected_source"] == f"css_recipe:{selector}"
    assert (
        len((await db_session.execute(select(ExtractionTemplate))).scalars().all()) == 1
    )
    assert (
        len((await db_session.execute(select(ExtractionRecipe))).scalars().all()) == 1
    )
    assert (
        len(
            (await db_session.execute(select(CompiledExtractionRecipe))).scalars().all()
        )
        == 1
    )

    sites = await memory_api_client.get("/api/knowledge/sites")
    assert sites.json()["sites"][0]["domain"] == "example.com"


@pytest.mark.asyncio
@pytest.mark.component
async def test_extraction_memory_purge_removes_recipe_hierarchy(
    db_session: AsyncSession, memory_api_client: AsyncClient
) -> None:
    await memory_api_client.post(
        "/api/knowledge/contracts/selector",
        json={
            "domain": "example.com",
            "url": "https://example.com/products/widget-1",
            "surface": "ecommerce_detail",
            "field_name": "title",
            "css_selector": "h1",
        },
    )

    response = await memory_api_client.delete("/api/knowledge/purge")

    assert response.status_code == 200
    assert not (await db_session.execute(select(ExtractionTemplate))).scalars().all()


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_memory_read_model_exposes_selector_recipe_runtime_state(
    db_session: AsyncSession, memory_api_client: AsyncClient
) -> None:
    template = await ensure_template(
        db_session,
        domain="Example.COM",
        surface="ecommerce_detail",
        fingerprint="structural-product-template",
        route_pattern="/products/{slug}",
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_SELECTORS,
        payload={
            "rules": [
                {
                    "id": 1,
                    "field_name": "price",
                    "css_selector": "[data-price]",
                    "status": "validated",
                    "is_active": True,
                }
            ]
        },
    )
    await db_session.commit()

    response = await memory_api_client.get(
        "/api/knowledge/memory", params={"domain": "EXAMPLE.com"}
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["domain"] == "example.com"
    assert payload["summary"]["template_count"] == 1
    assert payload["summary"]["selector_count"] == 1
    assert payload["templates"][0]["surface"] == "ecommerce_detail"
    assert payload["templates"][0]["recipes"][0]["kind"] == "selectors"
    assert payload["templates"][0]["recipes"][0]["rule_count"] == 1
    assert payload["templates"][0]["recipes"][0]["rules"][0]["field_name"] == "price"
    assert payload["templates"][0]["recipes"][0]["compiled"] is not None
