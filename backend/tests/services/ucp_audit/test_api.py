from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.services.config.ucp_audit import UCP_AUDIT_JOB_STATUS_QUEUED


@pytest.fixture
async def ucp_audit_api_client(db_session, test_user, monkeypatch: pytest.MonkeyPatch):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    async def _noop_run(job_id: int) -> None:
        del job_id

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    monkeypatch.setattr("app.api.ucp_audit.run_ucp_audit_job", _noop_run)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_ucp_audit_api_creates_and_reads_job(
    ucp_audit_api_client: AsyncClient,
) -> None:
    response = await ucp_audit_api_client.post(
        "/api/ucp-audit/jobs",
        json={"domain": "https://example.com", "options": {"sample_size": 2}},
    )

    assert response.status_code == 202
    created = response.json()
    assert created["domain"] == "example.com"
    assert created["status"] == UCP_AUDIT_JOB_STATUS_QUEUED

    list_response = await ucp_audit_api_client.get("/api/ucp-audit/jobs")
    assert list_response.status_code == 200
    assert [row["id"] for row in list_response.json()] == [created["id"]]

    detail_response = await ucp_audit_api_client.get(
        f"/api/ucp-audit/jobs/{created['id']}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["job"]["id"] == created["id"]


@pytest.mark.asyncio
async def test_ucp_audit_api_rejects_bad_domain(
    ucp_audit_api_client: AsyncClient,
) -> None:
    response = await ucp_audit_api_client.post(
        "/api/ucp-audit/jobs",
        json={"domain": ""},
    )

    assert response.status_code == 422
