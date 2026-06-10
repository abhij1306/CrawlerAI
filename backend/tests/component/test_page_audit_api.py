from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.page_audit import PageAuditResult
from app.services.config.page_audit import PAGE_AUDIT_JOB_STATUS_QUEUED


@pytest_asyncio.fixture
async def page_audit_api_client(db_session, test_user, monkeypatch: pytest.MonkeyPatch):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    async def _noop_run(job_id: int) -> None:
        _ = job_id

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    monkeypatch.setattr("app.api.page_audit.run_page_audit_job", _noop_run)
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_page_audit_api_creates_and_reads_job(
    page_audit_api_client: AsyncClient,
) -> None:
    response = await page_audit_api_client.post(
        "/api/page-audit/jobs",
        json={"url": "example.com/page", "context": "generic"},
    )

    assert response.status_code == 202
    created = response.json()
    assert created["url"] == "https://example.com/page"
    assert created["context"] == "generic"
    assert created["status"] == PAGE_AUDIT_JOB_STATUS_QUEUED

    detail_response = await page_audit_api_client.get(
        f"/api/page-audit/jobs/{created['id']}"
    )
    assert detail_response.status_code == 200
    assert detail_response.json()["job"]["id"] == created["id"]
    assert detail_response.json()["result"] is None


@pytest.mark.asyncio
@pytest.mark.component
async def test_page_audit_api_rejects_non_http_target(
    page_audit_api_client: AsyncClient,
) -> None:
    response = await page_audit_api_client.post(
        "/api/page-audit/jobs",
        json={"url": "ftp://example.com/file"},
    )

    assert response.status_code == 400
    assert "http" in response.json()["detail"].lower()


@pytest.mark.asyncio
@pytest.mark.component
async def test_page_audit_api_exports_completed_report(
    page_audit_api_client: AsyncClient,
    db_session,
) -> None:
    response = await page_audit_api_client.post(
        "/api/page-audit/jobs",
        json={"url": "https://example.com/page"},
    )
    job_id = response.json()["id"]
    report = {
        "url": "https://example.com/page",
        "source_checks": [],
        "dom_checks": [],
        "diff_checks": [],
        "scores": {"seo": 100},
        "critical_failures": [],
        "render_summary": {},
    }
    db_session.add(
        PageAuditResult(
            job_id=job_id,
            url="https://example.com/page",
            report_json=report,
            markdown_report="# Page Technical Audit\n",
        )
    )
    await db_session.commit()

    json_response = await page_audit_api_client.get(
        f"/api/page-audit/jobs/{job_id}/export.json"
    )
    markdown_response = await page_audit_api_client.get(
        f"/api/page-audit/jobs/{job_id}/export.md"
    )

    assert json_response.status_code == 200
    assert json_response.json()["url"] == "https://example.com/page"
    assert markdown_response.status_code == 200
    assert markdown_response.text.startswith("# Page Technical Audit")
