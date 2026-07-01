from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.knowledge_graph import (
    KGEntity,
    KGExtractionContract,
    KGRelationship,
    KGSiteVersion,
)


@pytest.fixture
async def knowledge_api_client(db_session: AsyncSession, test_user):
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
async def test_knowledge_api_requires_auth() -> None:
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        response = await client.get("/api/knowledge/sites")
    assert response.status_code == 401


@pytest.mark.asyncio
@pytest.mark.component
async def test_knowledge_graph_endpoint_applies_bounds(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    product_id = uuid.uuid4()
    brand_id = uuid.uuid4()
    db_session.add_all(
        [
            KGEntity(
                id=product_id,
                entity_type="product",
                canonical_key="example.com:prod-1",
                canonical_name="Widget",
            ),
            KGEntity(
                id=brand_id,
                entity_type="brand",
                canonical_key="example.com:brand:acme",
                canonical_name="ACME",
            ),
            KGRelationship(
                source_entity_id=product_id,
                target_entity_id=brand_id,
                relationship_type="PRODUCT_MADE_BY",
            ),
        ]
    )
    await db_session.commit()

    response = await knowledge_api_client.get(
        f"/api/knowledge/graph?root_entity_id={product_id}&depth=99&limit=9999"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["bounds"] == {"depth": 4, "limit": 500}
    assert {node["entity_type"] for node in payload["nodes"]} == {"product", "brand"}
    assert payload["relationships"][0]["relationship_type"] == "PRODUCT_MADE_BY"


@pytest.mark.asyncio
@pytest.mark.component
async def test_knowledge_graph_endpoint_filters_by_domain(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    db_session.add_all(
        [
            KGEntity(
                entity_type="product",
                canonical_key="example.com:prod-1",
                canonical_name="Example Widget",
            ),
            KGEntity(
                entity_type="product",
                canonical_key="other.com:prod-1",
                canonical_name="Other Widget",
            ),
        ]
    )
    await db_session.commit()

    response = await knowledge_api_client.get("/api/knowledge/graph?domain=example.com")

    assert response.status_code == 200
    nodes = response.json()["nodes"]
    assert [node["canonical_key"] for node in nodes] == ["example.com:prod-1"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_knowledge_selector_contract_wires_generated_selector(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    selector = "[data-field='brand'][data-context='product-detail-primary-brand-value']"
    response = await knowledge_api_client.post(
        "/api/knowledge/contracts/selector",
        json={
            "domain": "Example.COM",
            "url": "https://example.com/products/widget-1",
            "surface": "ecommerce_detail",
            "field_name": "brand",
            "css_selector": selector,
            "sample_value": "ACME",
            "source": "selector_suggestion",
        },
    )

    assert response.status_code == 200
    contract = response.json()["contract"]
    assert contract["canonical_field"] == "product.brand"
    assert contract["selected_source"] == f"css_recipe:{selector}"
    assert contract["selection_origin"] == "operator"
    assert len(contract["selection_history"]) == 1
    assert contract["selection_history"][0]["source"] == "selector_suggestion"

    saved = (
        await db_session.execute(
            select(KGExtractionContract).where(
                KGExtractionContract.canonical_field == "product.brand"
            )
        )
    ).scalar_one()
    template = await db_session.get(KGEntity, saved.template_id)
    assert template is not None
    assert template.properties["route_pattern"] == "/products/{id}"


@pytest.mark.asyncio
@pytest.mark.component
async def test_knowledge_selector_contract_rejects_cross_domain_url(
    knowledge_api_client: AsyncClient,
) -> None:
    response = await knowledge_api_client.post(
        "/api/knowledge/contracts/selector",
        json={
            "domain": "example.com",
            "url": "https://other.example/products/widget",
            "surface": "ecommerce_detail",
            "field_name": "brand",
            "css_selector": ".brand",
        },
    )

    assert response.status_code == 422


@pytest.mark.asyncio
@pytest.mark.component
async def test_knowledge_contract_selection_validates_scope_and_candidate(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    template_id = uuid.uuid4()
    contract_id = uuid.uuid4()
    db_session.add(KGSiteVersion(domain="example.com", current_version=3))
    db_session.add(
        KGEntity(
            id=template_id,
            entity_type="page_template",
            canonical_key="example.com:ecommerce_detail:abc",
            canonical_name="Template",
            properties={"domain": "example.com"},
        )
    )
    db_session.add(
        KGExtractionContract(
            id=contract_id,
            template_id=template_id,
            surface="ecommerce_detail",
            canonical_field="product.title",
            candidates=[{"source": "jsonld:/name"}, {"source": "dom:h1"}],
            selected_source="jsonld:/name",
            selection_origin="generic",
        )
    )
    await db_session.commit()

    invalid = await knowledge_api_client.put(
        f"/api/knowledge/contracts/{contract_id}/selection",
        json={
            "selected_source": "dom:h1",
            "template_id": str(template_id),
            "surface": "ecommerce_listing",
            "canonical_field": "product.title",
            "expected_version": 3,
        },
    )
    assert invalid.status_code == 409

    missing_candidate = await knowledge_api_client.put(
        f"/api/knowledge/contracts/{contract_id}/selection",
        json={
            "selected_source": "network:/product/name",
            "template_id": str(template_id),
            "surface": "ecommerce_detail",
            "canonical_field": "product.title",
            "expected_version": 3,
        },
    )
    assert missing_candidate.status_code == 422

    accepted = await knowledge_api_client.put(
        f"/api/knowledge/contracts/{contract_id}/selection",
        json={
            "selected_source": "dom:h1",
            "template_id": str(template_id),
            "surface": "ecommerce_detail",
            "canonical_field": "product.title",
            "expected_version": 3,
        },
    )
    assert accepted.status_code == 200
    contract = accepted.json()["contract"]
    assert contract["selected_source"] == "dom:h1"
    assert contract["selection_origin"] == "operator"
    assert contract["selection_history"][0]["selected_source"] == "dom:h1"


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_contract_listing_and_selection_are_surface_scoped(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    db_session.add(KGSiteVersion(domain="example.com", current_version=1))
    template_ids = [uuid.uuid4(), uuid.uuid4()]
    contract_ids = [uuid.uuid4(), uuid.uuid4()]
    for index, (template_id, contract_id) in enumerate(zip(template_ids, contract_ids)):
        db_session.add(
            KGEntity(
                id=template_id,
                entity_type="page_template",
                canonical_key=f"example.com:ecommerce_detail:template-{index}",
                canonical_name=f"Template {index}",
                properties={"domain": "example.com", "surface": "ecommerce_detail"},
            )
        )
        db_session.add(
            KGExtractionContract(
                id=contract_id,
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.brand",
                candidates=[
                    {"source": "jsonld:/brand"},
                    {"source": "css_recipe:.brand"},
                ],
                selected_source=(
                    "css_recipe:.brand" if index == 1 else "jsonld:/brand"
                ),
                selection_origin="operator" if index == 1 else "generic",
            )
        )
    await db_session.commit()

    listed = await knowledge_api_client.get(
        "/api/knowledge/contracts", params={"domain": "Example.COM"}
    )
    assert listed.status_code == 200
    assert len(listed.json()["contracts"]) == 2
    assert listed.json()["contracts"][0]["selection_origin"] == "operator"

    selected = await knowledge_api_client.put(
        f"/api/knowledge/contracts/{contract_ids[0]}/selection",
        json={
            "selected_source": "css_recipe:.brand",
            "template_id": str(template_ids[0]),
            "surface": "ecommerce_detail",
            "canonical_field": "product.brand",
            "expected_version": 1,
        },
    )
    assert selected.status_code == 200
    assert selected.json()["updated_contract_count"] == 2

    for contract_id in contract_ids:
        contract = await db_session.get(KGExtractionContract, contract_id)
        assert contract is not None
        await db_session.refresh(contract)
        assert contract.selected_source == "css_recipe:.brand"
        assert contract.selection_origin == "operator"
        assert contract.selection_history[-1]["scope"] == "domain_surface"


@pytest.mark.asyncio
@pytest.mark.component
async def test_domain_contract_selection_skips_templates_missing_candidate(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    db_session.add(KGSiteVersion(domain="example.com", current_version=1))
    template_ids = [uuid.uuid4(), uuid.uuid4()]
    contract_ids = [uuid.uuid4(), uuid.uuid4()]
    candidate_sets = [
        [{"source": "jsonld:/brand"}, {"source": "css_recipe:.brand"}],
        [{"source": "jsonld:/brand"}, {"source": "dom:.pdp-brand"}],
    ]
    for index, (template_id, contract_id) in enumerate(zip(template_ids, contract_ids)):
        db_session.add(
            KGEntity(
                id=template_id,
                entity_type="page_template",
                canonical_key=f"example.com:ecommerce_detail:template-diverge-{index}",
                canonical_name=f"Template {index}",
                properties={"domain": "example.com", "surface": "ecommerce_detail"},
            )
        )
        db_session.add(
            KGExtractionContract(
                id=contract_id,
                template_id=template_id,
                surface="ecommerce_detail",
                canonical_field="product.brand",
                candidates=candidate_sets[index],
                selected_source="jsonld:/brand",
                selection_origin="generic",
            )
        )
    await db_session.commit()

    selected = await knowledge_api_client.put(
        f"/api/knowledge/contracts/{contract_ids[0]}/selection",
        json={
            "selected_source": "css_recipe:.brand",
            "template_id": str(template_ids[0]),
            "surface": "ecommerce_detail",
            "canonical_field": "product.brand",
            "expected_version": 1,
        },
    )

    assert selected.status_code == 200
    assert selected.json()["updated_contract_count"] == 1
    first = await db_session.get(KGExtractionContract, contract_ids[0])
    second = await db_session.get(KGExtractionContract, contract_ids[1])
    assert first is not None
    assert second is not None
    await db_session.refresh(first)
    await db_session.refresh(second)
    assert first.selected_source == "css_recipe:.brand"
    assert first.selection_origin == "operator"
    assert second.selected_source == "jsonld:/brand"
    assert second.selection_origin == "generic"
    assert second.selection_history == []


@pytest.mark.asyncio
@pytest.mark.component
async def test_knowledge_rebuild_conflict_and_purge(
    db_session: AsyncSession,
    knowledge_api_client: AsyncClient,
) -> None:
    db_session.add(KGSiteVersion(domain="example.com", current_version=2))
    db_session.add(
        KGEntity(
            entity_type="site",
            canonical_key="example.com",
            canonical_name="example.com",
        )
    )
    await db_session.commit()

    conflict = await knowledge_api_client.post(
        "/api/knowledge/rebuild",
        json={"domain": "example.com", "expected_version": 1},
    )
    assert conflict.status_code == 409

    rebuilt = await knowledge_api_client.post(
        "/api/knowledge/rebuild",
        json={"domain": "https://Example.COM/catalog", "expected_version": 2},
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["current_version"] == 3
    assert rebuilt.json()["status"] == "pending"

    purged = await knowledge_api_client.delete("/api/knowledge/purge")
    assert purged.status_code == 200
    assert not (await db_session.execute(select(KGEntity))).scalars().all()
