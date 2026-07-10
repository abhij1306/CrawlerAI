from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import review as review_api
from app.core.dependencies import get_current_user, get_db
from app.main import app


@pytest.mark.asyncio
@pytest.mark.component
async def test_review_artifact_html_is_sandboxed(
    monkeypatch: pytest.MonkeyPatch,
    test_user,
) -> None:
    async def _override_db():
        yield object()

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = lambda: test_user
    monkeypatch.setattr(
        review_api,
        "_get_accessible_run_or_404",
        AsyncMock(return_value=SimpleNamespace(id=42)),
    )
    monkeypatch.setattr(
        review_api,
        "load_review_html",
        AsyncMock(return_value="<script>alert('xss')</script>"),
    )

    try:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/api/review/42/artifact-html")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.text == "<script>alert('xss')</script>"
    assert response.headers["content-security-policy"] == (
        "sandbox; default-src 'none'; base-uri 'none'; form-action 'none'; "
        "img-src data: http: https:; style-src 'unsafe-inline'"
    )
