import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.dependencies import get_current_user, get_db
from app.main import app


@pytest_asyncio.fixture
async def crawls_api_client(db_session, test_user, monkeypatch: pytest.MonkeyPatch):
    async def _override_db():
        yield db_session

    async def _override_user():
        return test_user

    async def _fake_discover_category_urls(urls: list[str], **kwargs: object) -> dict:
        assert urls == ["https://example.com"]
        assert kwargs["strategy"] == "static_then_rendered"
        return {
            "status": "completed",
            "source": "rendered_site_links",
            "sources": {"https://example.com": "rendered_site_links"},
            "urls": ["https://example.com/collections/bags"],
            "groups": {"https://example.com": ["https://example.com/collections/bags"]},
            "trees": {
                "https://example.com": [
                    {
                        "label": "Collections",
                        "children": [
                            {
                                "label": "Bags",
                                "url": "https://example.com/collections/bags",
                                "children": [],
                            }
                        ],
                    }
                ]
            },
            "errors": {},
            "diagnostics": {"https://example.com": {"candidates_seen": 1}},
            "total_found": 1,
            "limit": 10,
        }

    app.dependency_overrides[get_db] = _override_db
    app.dependency_overrides[get_current_user] = _override_user
    monkeypatch.setattr(
        "app.api.crawls.discover_category_urls",
        _fake_discover_category_urls,
    )
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
    ) as client:
        yield client
    app.dependency_overrides.clear()


@pytest.mark.asyncio
@pytest.mark.component
async def test_crawls_category_discovery_api(crawls_api_client: AsyncClient) -> None:
    response = await crawls_api_client.post(
        "/api/crawls/category-discovery",
        json={"url": "https://example.com", "limit": 10},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["source"] == "rendered_site_links"
    assert payload["urls"] == ["https://example.com/collections/bags"]
    assert payload["groups"] == {
        "https://example.com": ["https://example.com/collections/bags"]
    }
