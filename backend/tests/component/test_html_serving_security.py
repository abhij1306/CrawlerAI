"""Security headers for endpoints serving untrusted (crawled/fetched) HTML.

Audit 1.2: crawled page HTML served as text/html from the API origin must be
sandboxed so embedded scripts cannot execute in the origin's security context.
"""
from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app

_SANDBOX_CSP = "sandbox"
_BASELINE_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"


@pytest.fixture
async def html_api_client(db_session, test_user):
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
async def test_selector_preview_html_is_csp_sandboxed(
    html_api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _fake_preview(url: str):
        return {
            "url": url,
            "html": "<html><body><script>alert(1)</script></body></html>",
        }

    monkeypatch.setattr("app.api.selectors.fetch_selector_document", _fake_preview)

    response = await html_api_client.get(
        "/api/selectors/preview-html",
        params={"url": "https://example.com/products/widget"},
    )

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == _SANDBOX_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Type"].startswith("text/html")


@pytest.mark.asyncio
@pytest.mark.component
async def test_review_artifact_html_is_csp_sandboxed(
    html_api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeRun:
        id = 1

    async def _fake_run(session, *, run_id, user, detail):
        return _FakeRun()

    async def _fake_html(session, run_id) -> str:
        return "<html><body><script>alert(1)</script></body></html>"

    monkeypatch.setattr("app.api.review._get_accessible_run_or_404", _fake_run)
    monkeypatch.setattr("app.api.review.load_review_html", _fake_html)

    response = await html_api_client.get("/api/review/1/artifact-html")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == _SANDBOX_CSP
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Content-Type"].startswith("text/html")


@pytest.mark.asyncio
@pytest.mark.component
async def test_api_responses_carry_baseline_csp(html_api_client: AsyncClient) -> None:
    response = await html_api_client.get("/api/health")

    assert response.status_code == 200
    assert response.headers["Content-Security-Policy"] == _BASELINE_CSP


@pytest.mark.asyncio
@pytest.mark.component
async def test_docs_pages_exempt_from_baseline_csp(
    html_api_client: AsyncClient,
) -> None:
    response = await html_api_client.get("/docs")

    assert response.status_code == 200
    assert "Content-Security-Policy" not in response.headers
