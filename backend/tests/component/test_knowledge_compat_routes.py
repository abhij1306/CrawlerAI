"""Knowledge compat-route contracts (audit 4.6 + dead-route removals).

The live surface is exactly ``GET /sites``, ``GET /contracts`` and
``PUT /contracts/{contract_id}/selection``; their response shapes are pinned
here. Every removed route must answer 404.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.extraction_memory import (
    EXTRACTION_RECIPE_KIND_CONTRACTS,
    EXTRACTION_RECIPE_KIND_SELECTORS,
    EXTRACTION_RECIPE_LAYER_DOMAIN,
    EXTRACTION_RECIPE_LAYER_TEMPLATE,
)
from app.core.dependencies import get_current_user, get_db, require_admin
from app.main import app
from app.models.crawl_run import CrawlRun
from app.persistence.extraction_memory import ensure_template, upsert_recipe
from app.persistence.extraction_memory_knowledge import (
    find_contract_location,
    list_knowledge_site_projections,
    list_template_contracts,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.component]


@pytest.fixture
async def knowledge_client(db_session: AsyncSession, test_user):
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


def _contract_payload(
    template_id: uuid.UUID,
    *,
    canonical_field: str,
    selection_origin: str,
    contract_id: uuid.UUID | None = None,
) -> dict:
    selected = f"json_ld:{canonical_field}"
    return {
        "id": str(contract_id or uuid.uuid4()),
        "template_id": str(template_id),
        "surface": "ecommerce_detail",
        "canonical_field": canonical_field,
        "candidates": [
            {"source": selected, "value_preview": "10.00"},
            {"source": f"dom:.{canonical_field}", "value_preview": "10.00"},
        ],
        "latest_values": [],
        "success_count": 0,
        "rejection_count": 0,
        "resolver_rule": "resolver_observed",
        "selected_source": selected,
        "selection_origin": selection_origin,
        "selection_history": [{"selected_source": selected, "source": "observation"}],
        "status": "active",
    }


async def test_sites_shape_preserved(
    db_session: AsyncSession, knowledge_client: AsyncClient, test_user
) -> None:
    run = CrawlRun(
        user_id=test_user.id,
        run_type="crawl",
        url="https://example.com/products/widget",
        status="running",
        surface="ecommerce_detail",
    )
    db_session.add(run)
    await db_session.flush()
    template = await ensure_template(
        db_session,
        domain="Example.COM",
        surface="ecommerce_detail",
        fingerprint="structural-product-template",
        route_pattern="/products/{slug}",
        run_id=run.id,
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

    response = await knowledge_client.get("/api/knowledge/sites")

    assert response.status_code == 200
    sites = response.json()["sites"]
    assert len(sites) == 1
    site = sites[0]
    assert set(site) == {
        "id",
        "domain",
        "current_version",
        "projection_status",
        "last_projected_run_id",
        "last_projected_at",
    }
    assert site["id"] == str(template.id)
    assert site["domain"] == "example.com"
    assert site["current_version"] == 1
    assert site["projection_status"] == "active"
    assert site["last_projected_run_id"] == run.id


async def test_site_projection_uses_deterministic_template_identity(
    db_session: AsyncSession,
) -> None:
    templates = [
        await ensure_template(
            db_session,
            domain="stable.example",
            surface="ecommerce_detail",
            fingerprint=f"stable-fingerprint-{index}",
            route_pattern=f"/products/{index}/{{slug}}",
        )
        for index in range(2)
    ]
    await db_session.commit()

    sites = await list_knowledge_site_projections(db_session)
    site = next(row for row in sites if row.domain == "stable.example")

    assert site.id == sorted(template.id for template in templates)[0]


async def test_template_contract_reader_ignores_non_template_layers(
    db_session: AsyncSession,
) -> None:
    template = await ensure_template(
        db_session,
        domain="layered.example",
        surface="ecommerce_detail",
        fingerprint="layered-contracts",
        route_pattern="/products/{slug}",
    )
    template_contract = _contract_payload(
        template.id, canonical_field="price", selection_origin="operator"
    )
    domain_contract = _contract_payload(
        template.id, canonical_field="brand", selection_origin="generic"
    )
    for layer, contract in (
        (EXTRACTION_RECIPE_LAYER_DOMAIN, domain_contract),
        (EXTRACTION_RECIPE_LAYER_TEMPLATE, template_contract),
    ):
        await upsert_recipe(
            db_session,
            template=template,
            layer=layer,
            kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
            payload={"contracts": [contract]},
        )
    await db_session.commit()

    contracts = await list_template_contracts(db_session, template)

    assert [row["canonical_field"] for row in contracts] == ["price"]


async def test_domain_contracts_shape_and_operator_first_sort(
    db_session: AsyncSession, knowledge_client: AsyncClient
) -> None:
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="fp-contracts",
        route_pattern="/products/{slug}",
    )
    generic = _contract_payload(
        template.id, canonical_field="price", selection_origin="generic"
    )
    operator = _contract_payload(
        template.id, canonical_field="brand", selection_origin="operator"
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": [generic, operator]},
    )
    await db_session.commit()

    response = await knowledge_client.get(
        "/api/knowledge/contracts", params={"domain": "EXAMPLE.com"}
    )

    assert response.status_code == 200
    assert set(response.json()) == {"contracts"}
    contracts = response.json()["contracts"]
    assert [row["canonical_field"] for row in contracts] == ["brand", "price"]
    assert contracts[0]["selection_origin"] == "operator"
    assert contracts[1]["selected_source"] == "json_ld:price"

    empty = await knowledge_client.get(
        "/api/knowledge/contracts", params={"domain": "other.example"}
    )
    assert empty.status_code == 200
    assert empty.json() == {"contracts": []}


async def test_contract_selection_updates_stored_contract(
    db_session: AsyncSession, knowledge_client: AsyncClient
) -> None:
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="fp-selection",
        route_pattern="/products/{slug}",
    )
    contract_id = uuid.uuid4()
    contract = _contract_payload(
        template.id,
        canonical_field="price",
        selection_origin="generic",
        contract_id=contract_id,
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": [contract]},
    )
    await db_session.commit()

    response = await knowledge_client.put(
        f"/api/knowledge/contracts/{contract_id}/selection",
        json={
            "selected_source": "dom:.price",
            "template_id": str(template.id),
            "surface": "ecommerce_detail",
            "canonical_field": "price",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["updated_contract_count"] == 1
    assert body["contract"]["selected_source"] == "dom:.price"
    assert body["contract"]["selection_origin"] == "operator"
    assert body["contract"]["selection_history"][-1] == {
        "selected_source": "dom:.price",
        "scope": "template",
    }

    # Selection persisted: a fresh read sees the operator choice.
    reread = await knowledge_client.get(
        "/api/knowledge/contracts", params={"domain": "example.com"}
    )
    assert reread.json()["contracts"][0]["selected_source"] == "dom:.price"


async def test_find_contract_location_uses_single_query(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2.15: JSONB containment replaces the template scan + per-template queries."""
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="fp-single-query-lookup",
        route_pattern="/products/{slug}",
    )
    contract_id = uuid.uuid4()
    contract = _contract_payload(
        template.id,
        canonical_field="price",
        selection_origin="generic",
        contract_id=contract_id,
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": [contract]},
    )
    await db_session.commit()

    real_execute = db_session.execute
    execute_count = 0

    async def _counting_execute(*args, **kwargs):
        nonlocal execute_count
        execute_count += 1
        return await real_execute(*args, **kwargs)

    monkeypatch.setattr(db_session, "execute", _counting_execute)

    location = await find_contract_location(db_session, str(contract_id))

    assert location is not None
    assert location.template.id == template.id
    assert location.contract["id"] == str(contract_id)
    assert execute_count == 1


async def test_contract_selection_error_contracts(
    db_session: AsyncSession, knowledge_client: AsyncClient
) -> None:
    template = await ensure_template(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        fingerprint="fp-selection-errors",
        route_pattern="/products/{slug}",
    )
    contract_id = uuid.uuid4()
    contract = _contract_payload(
        template.id,
        canonical_field="price",
        selection_origin="generic",
        contract_id=contract_id,
    )
    await upsert_recipe(
        db_session,
        template=template,
        layer=EXTRACTION_RECIPE_LAYER_TEMPLATE,
        kind=EXTRACTION_RECIPE_KIND_CONTRACTS,
        payload={"contracts": [contract]},
    )
    await db_session.commit()

    missing = await knowledge_client.put(
        f"/api/knowledge/contracts/{uuid.uuid4()}/selection",
        json={"selected_source": "dom:.price"},
    )
    assert missing.status_code == 404

    not_candidate = await knowledge_client.put(
        f"/api/knowledge/contracts/{contract_id}/selection",
        json={"selected_source": "llm:generated"},
    )
    assert not_candidate.status_code == 422

    scope_mismatch = await knowledge_client.put(
        f"/api/knowledge/contracts/{contract_id}/selection",
        json={
            "selected_source": "dom:.price",
            "surface": "ecommerce_listing",
        },
    )
    assert scope_mismatch.status_code == 409


async def test_deleted_routes_answer_404(knowledge_client: AsyncClient) -> None:
    deleted = [
        ("GET", "/api/knowledge/graph"),
        ("GET", "/api/knowledge/memory"),
        ("DELETE", "/api/knowledge/purge"),
        ("POST", "/api/knowledge/contracts/selector"),
        ("GET", f"/api/knowledge/entities/{uuid.uuid4()}"),
        ("DELETE", "/api/knowledge/sites/example.com"),
        ("GET", f"/api/knowledge/contracts/{uuid.uuid4()}"),
    ]
    for method, path in deleted:
        response = await knowledge_client.request(method, path)
        assert response.status_code == 404, f"{method} {path}"
