from __future__ import annotations

# ruff: noqa: F403, F405
from .public_api_test_support import *


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_batch_extract_is_deferred(db_session, test_user) -> None:
    raw_key = "crawlerai_batch_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="batch",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/extract/batch",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"urls": ["https://example.com/p/1"], "surface": "ecommerce"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 501
    assert response.json()["error"]["code"] == "WORKER_REQUIRED"


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_domain_info_reads_domain_memory(db_session, test_user) -> None:
    raw_key = "crawlerai_domain_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="domain",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {
                    "id": 1,
                    "field_name": "title",
                    "css_selector": "h1",
                    "is_active": True,
                }
            ]
        },
    )
    db_session.add(
        DomainRunProfile(
            domain="example.com",
            surface="ecommerce_detail",
            profile={"fetch_profile": {"fetch_mode": "http_only"}},
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/api/v1/domains/example.com",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["known"] is True
    assert data["has_cached_selectors"] is True
    assert data["acquisition_profile"] == "http_preferred"


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_extract_runs_http_only_and_shapes_record(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_extract_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="extract",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()
    seen: dict[str, object] = {}

    async def _fake_process_single_url(*, session, run, url, config):
        seen["surface"] = run.surface
        seen["fetch_mode"] = run.settings["fetch_profile"]["fetch_mode"]
        seen["llm_enabled"] = run.settings.get("llm_enabled")
        session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={
                    "title": "Example Shoe",
                    "price": 129.99,
                    "availability": "in_stock",
                },
                raw_data={},
                discovered_data={"acquisition_method": "httpx"},
                source_trace={"fetch_method": "http"},
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()

        class _Result:
            verdict = "success"
            url_metrics = {"record_count": 1}
            records = []

        return _Result()

    async def _override_db():
        yield db_session

    monkeypatch.setattr(
        "app.connectors.public_api.extraction_service.process_single_url",
        _fake_process_single_url,
    )
    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/extract",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={
                    "url": "https://example.com/product/1",
                    "surface": "ecommerce",
                    "fields": ["product_name", "price"],
                    "options": {"use_cache": True},
                },
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["data"]["surface"] == "ecommerce"
    assert payload["data"]["fields"] == {"title": "Example Shoe", "price": 129.99}
    assert seen == {
        "surface": PUBLIC_API_INTERNAL_ECOMMERCE_SURFACE,
        "fetch_mode": "http_only",
        "llm_enabled": False,
    }


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_extract_rejects_unsupported_surface(
    db_session, test_user
) -> None:
    raw_key = "crawlerai_extract_surface_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="extract",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/extract",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"url": "https://example.com/product/1", "surface": "jobs"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_SURFACE"


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_extract_rejects_auto_surface(
    db_session,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_key = "crawlerai_extract_auto_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="extract",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()
    seen: dict[str, object] = {}

    async def _fake_process_single_url(*, session, run, url, config):
        seen["surface"] = run.surface
        seen["surface_resolution"] = run.settings.get("surface_resolution")
        session.add(
            CrawlRecord(
                run_id=run.id,
                source_url=url,
                data={"title": "Codeforces", "url": url},
                raw_data={},
                discovered_data={"acquisition_method": "httpx"},
                source_trace={"fetch_method": "http"},
                created_at=datetime.now(UTC),
            )
        )
        await session.flush()

        class _Result:
            verdict = "success"
            url_metrics = {"record_count": 1}
            records = []

        return _Result()

    async def _override_db():
        yield db_session

    monkeypatch.setattr(
        "app.connectors.public_api.extraction_service.process_single_url",
        _fake_process_single_url,
    )
    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.post(
                "/api/v1/extract",
                headers={"Authorization": f"Bearer {raw_key}"},
                json={"url": "https://codeforces.com/", "surface": "auto"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert seen == {}


@pytest.mark.asyncio
@pytest.mark.component
async def test_public_watches_route_is_not_registered_after_alert_rename(
    db_session, test_user
) -> None:
    raw_key = "crawlerai_watch_key"
    db_session.add(
        ApiKey(
            user_id=test_user.id,
            name="watch",
            key_prefix="crawlerai",
            key_hash=hash_api_key(raw_key),
            is_active=True,
        )
    )
    await db_session.commit()

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_db
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            response = await client.get(
                "/api/v1/watches",
                headers={"Authorization": f"Bearer {raw_key}"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
