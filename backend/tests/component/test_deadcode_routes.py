"""Regression tests for dead-route removal (audit 3.2) and the CSV upload cap
(audit 2.6)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app


@pytest.fixture
async def deadcode_client(db_session, test_user):
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
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/crawls/1/llm-commit"),
        ("POST", "/api/crawls/1/cancel"),
        ("GET", "/api/crawls/domain-run-profiles"),
        ("GET", "/api/dashboard/metrics"),
        ("POST", "/api/dashboard/reset-data-enrichment"),
        ("DELETE", "/api/api-keys/1"),
        # 3.14: test-only routes removed with no frontend/external caller.
        ("GET", "/api/selectors/summary"),
        ("GET", "/api/ai-visibility/runs/1/executions"),
        ("POST", "/api/dashboard/reset-crawl-data"),
        ("POST", "/api/dashboard/reset-product-intelligence"),
        ("GET", "/api/crawls/1/export/tables.csv"),
        ("GET", "/api/crawls/1/export/artifacts.json"),
    ],
)
async def test_removed_zero_caller_routes_return_404(
    deadcode_client: AsyncClient, method: str, path: str
) -> None:
    response = await deadcode_client.request(method, path)
    assert response.status_code == 404


@pytest.mark.asyncio
@pytest.mark.component
async def test_csv_upload_over_size_limit_rejected_with_413(
    deadcode_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("app.api.crawls.CSV_UPLOAD_MAX_BYTES", 16)

    response = await deadcode_client.post(
        "/api/crawls/csv",
        files={"file": ("urls.csv", b"url\nhttps://example.com/a\n", "text/csv")},
        data={"surface": "ecommerce_detail"},
    )

    assert response.status_code == 413
    assert "size limit" in response.json()["detail"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_csv_upload_within_size_limit_accepted(
    deadcode_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRun:
        id = 7

    async def _fake_ingest(session, user_id, **kwargs):
        return _FakeRun(), 1

    monkeypatch.setattr("app.api.crawls.CSV_UPLOAD_MAX_BYTES", 1024)
    monkeypatch.setattr("app.api.crawls.create_crawl_run_from_csv", _fake_ingest)

    response = await deadcode_client.post(
        "/api/crawls/csv",
        files={"file": ("urls.csv", b"url\nhttps://example.com/a\n", "text/csv")},
        data={"surface": "ecommerce_detail"},
    )

    assert response.status_code == 200
    assert response.json() == {"run_id": 7, "url_count": 1}
