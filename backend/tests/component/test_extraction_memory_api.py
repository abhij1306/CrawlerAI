from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db, require_admin
from app.main import app
from app.models.extraction_memory import (
    CompiledExtractionRecipe,
    ExtractionRecipe,
    ExtractionTemplate,
)


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
