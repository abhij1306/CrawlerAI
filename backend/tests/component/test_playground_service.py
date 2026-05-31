from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user, get_db
from app.main import app
from app.models.crawl_run import CrawlRecord
from app.models.playground import PlaygroundSession
from app.services.playground_service import (
    _classify_input_url,
    _merge_seed_detail_products,
    get_session,
    get_results,
    select_category,
    start_discover,
    start_pipeline,
)


async def _seed_extract_run(
    db_session: AsyncSession,
    create_test_run,
    *,
    url: str,
    title: str,
    price: str,
) -> tuple[int, int]:
    run = await create_test_run(url=url, surface="ecommerce_detail")
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    record = CrawlRecord(
        run_id=run.id,
        source_url=url,
        data={"title": title, "price": price, "url": url},
        raw_data={},
        discovered_data={},
        source_trace={},
    )
    db_session.add(record)
    await db_session.flush()
    return int(run.id), int(record.id)


def _playground_session(
    test_user,
    *,
    selected_urls: list[str],
    run_ids: list[int],
) -> PlaygroundSession:
    return PlaygroundSession(
        user_id=test_user.id,
        input_url="https://www.wrangler.com/",
        state="extracted",
        step_data={
            "selected_urls": selected_urls,
            "extract": {
                "run_id": run_ids[0],
                "run_ids": run_ids,
                "status": "completed",
                "url_count": len(selected_urls),
            },
        },
    )


@pytest_asyncio.fixture
async def playground_api_client(db_session: AsyncSession, test_user):
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
async def test_playground_pipeline_uses_all_extracted_records_and_urls(
    db_session: AsyncSession,
    test_user,
    create_test_run,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    run_1_id, record_1_id = await _seed_extract_run(
        db_session,
        create_test_run,
        url="https://www.wrangler.com/p/jean-1",
        title="Jean 1",
        price="99.00",
    )
    run_2_id, record_2_id = await _seed_extract_run(
        db_session,
        create_test_run,
        url="https://www.wrangler.com/p/jean-2",
        title="Jean 2",
        price="109.00",
    )
    playground = _playground_session(
        test_user,
        selected_urls=[
            "https://www.wrangler.com/p/jean-1",
            "https://www.wrangler.com/p/jean-2",
        ],
        run_ids=[run_1_id, run_2_id],
    )
    db_session.add(playground)
    await db_session.flush()

    enrich_calls: list[dict[str, object]] = []
    compare_calls: list[dict[str, object]] = []
    monitor_calls: list[dict[str, object]] = []

    async def _fake_create_data_enrichment_job(session, *, user, payload):
        del session, user
        enrich_calls.append(dict(payload))
        return SimpleNamespace(id=101)

    async def _fake_run_data_enrichment_job(_job_id: int) -> None:
        return None

    async def _fake_create_product_intelligence_job(session, *, user, payload):
        del session, user
        compare_calls.append(dict(payload))
        return SimpleNamespace(id=202)

    async def _fake_run_product_intelligence_job(_job_id: int) -> None:
        return None

    async def _fake_create_monitor(session, *, user, payload):
        del session, user
        monitor_calls.append(dict(payload))
        return SimpleNamespace(id=303)

    monkeypatch.setattr(
        "app.services.data_enrichment.service.create_data_enrichment_job",
        _fake_create_data_enrichment_job,
    )
    monkeypatch.setattr(
        "app.services.data_enrichment.service.run_data_enrichment_job",
        _fake_run_data_enrichment_job,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.service.create_product_intelligence_job",
        _fake_create_product_intelligence_job,
    )
    monkeypatch.setattr(
        "app.services.product_intelligence.service.run_product_intelligence_job",
        _fake_run_product_intelligence_job,
    )
    monkeypatch.setattr(
        "app.services.monitor_service.create_monitor",
        _fake_create_monitor,
    )

    launched, dispatch_specs = await start_pipeline(
        db_session,
        playground=playground,
        user=test_user,
        enrich=True,
        compare=True,
        monitor=True,
    )

    assert playground.state == "running_pipeline"
    assert enrich_calls == [{"source_record_ids": [record_1_id, record_2_id]}]
    assert compare_calls == [{"source_record_ids": [record_1_id, record_2_id]}]
    assert monitor_calls == [
        {
            "name": "Playground monitor for www.wrangler.com",
            "urls": [
                "https://www.wrangler.com/p/jean-1",
                "https://www.wrangler.com/p/jean-2",
            ],
            "surface": "ecommerce_detail",
            "tracked_fields": ["price", "availability"],
            "requested_fields": ["price", "availability"],
            "schedule_interval_hours": 24,
            "priority": "background",
        }
    ]
    assert launched == {
        "enrich": {"job_id": 101, "status": "running"},
        "compare": {"job_id": 202, "status": "running"},
        "monitor": {"monitor_id": 303, "status": "created", "url_count": 2},
    }
    assert [(runner.__name__, job_id) for runner, job_id in dispatch_specs] == [
        ("_fake_run_data_enrichment_job", 101),
        ("_fake_run_product_intelligence_job", 202),
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_playground_results_aggregate_all_extract_runs(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    run_1_id, _record_1_id = await _seed_extract_run(
        db_session,
        create_test_run,
        url="https://www.wrangler.com/p/jean-1",
        title="Jean 1",
        price="99.00",
    )
    run_2_id, _record_2_id = await _seed_extract_run(
        db_session,
        create_test_run,
        url="https://www.wrangler.com/p/jean-2",
        title="Jean 2",
        price="109.00",
    )
    playground = _playground_session(
        test_user,
        selected_urls=[
            "https://www.wrangler.com/p/jean-1",
            "https://www.wrangler.com/p/jean-2",
        ],
        run_ids=[run_1_id, run_2_id],
    )
    db_session.add(playground)
    await db_session.flush()

    results = await get_results(db_session, playground=playground)

    assert results["steps"]["selected_urls"] == [
        "https://www.wrangler.com/p/jean-1",
        "https://www.wrangler.com/p/jean-2",
    ]
    assert results["steps"]["extract"]["run_ids"] == [run_1_id, run_2_id]
    assert results["steps"]["extract"]["record_count"] == 2
    assert [row["source_url"] for row in results["steps"]["extract"]["records"]] == [
        "https://www.wrangler.com/p/jean-1",
        "https://www.wrangler.com/p/jean-2",
    ]
    assert [row["data"]["title"] for row in results["steps"]["extract"]["records"]] == [
        "Jean 1",
        "Jean 2",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_session_auto_advance_recovers_untracked_extract_run_ids(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    playground = PlaygroundSession(
        user_id=test_user.id,
        input_url="https://www.wrangler.com/",
        state="extracting",
        step_data={
            "selected_urls": [
                "https://www.wrangler.com/p/jean-1",
                "https://www.wrangler.com/p/jean-2",
            ],
            "extract": {
                "run_id": 501,
                "run_ids": [501],
                "status": "running",
                "url_count": 2,
            },
        },
    )
    db_session.add(playground)
    await db_session.flush()

    run_1 = await create_test_run(
        url="https://www.wrangler.com/p/jean-1",
        surface="ecommerce_detail",
        settings={"playground_session_id": playground.id},
    )
    run_2 = await create_test_run(
        url="https://www.wrangler.com/p/jean-2",
        surface="ecommerce_detail",
        settings={"playground_session_id": playground.id},
    )
    run_1.status = "completed"
    run_1.completed_at = datetime.now(UTC)
    run_2.status = "completed"
    run_2.completed_at = datetime.now(UTC)
    await db_session.flush()

    refreshed = await get_session(
        db_session,
        session_id=int(playground.id),
        user=test_user,
    )

    assert refreshed.state == "extracted"
    assert refreshed.step_data["extract"]["status"] == "completed"
    assert refreshed.step_data["extract"]["run_id"] == run_1.id
    assert refreshed.step_data["extract"]["run_ids"] == [run_1.id, run_2.id]


@pytest.mark.asyncio
@pytest.mark.component
async def test_get_session_auto_advance_drops_missing_extract_run_ids(
    db_session: AsyncSession,
    test_user,
    create_test_run,
) -> None:
    playground = PlaygroundSession(
        user_id=test_user.id,
        input_url="https://www.wrangler.com/",
        state="extracting",
        step_data={
            "selected_urls": ["https://www.wrangler.com/p/jean-1"],
            "extract": {
                "run_id": 999999,
                "run_ids": [999999],
                "status": "running",
                "url_count": 1,
            },
        },
    )
    db_session.add(playground)
    await db_session.flush()

    run = await create_test_run(
        url="https://www.wrangler.com/p/jean-1",
        surface="ecommerce_detail",
        settings={"playground_session_id": playground.id},
    )
    run.status = "completed"
    run.completed_at = datetime.now(UTC)
    await db_session.flush()

    refreshed = await get_session(
        db_session,
        session_id=int(playground.id),
        user=test_user,
    )

    assert refreshed.state == "extracted"
    assert refreshed.step_data["extract"]["status"] == "completed"
    assert refreshed.step_data["extract"]["run_id"] == run.id
    assert refreshed.step_data["extract"]["run_ids"] == [run.id]


@pytest.mark.asyncio
@pytest.mark.component
async def test_select_category_uses_existing_batch_crawl_for_multiple_urls(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured_payloads: list[dict[str, object]] = []
    playground = PlaygroundSession(
        user_id=test_user.id,
        input_url="https://www.wrangler.com/",
        state="sitemap_listed",
        step_data={},
    )
    db_session.add(playground)
    await db_session.flush()

    async def _fake_create_crawl_run_from_payload(session, user_id, payload):
        del session, user_id
        captured_payloads.append(dict(payload))
        return SimpleNamespace(id=777)

    monkeypatch.setattr(
        "app.services.playground_service.create_crawl_run_from_payload",
        _fake_create_crawl_run_from_payload,
    )

    run_id = await select_category(
        db_session,
        playground=playground,
        user=test_user,
        urls=[
            "https://www.wrangler.com/collections/men",
            "https://www.wrangler.com/collections/women",
        ],
    )

    assert run_id == 777
    assert captured_payloads == [
        {
            "run_type": "batch",
            "url": "https://www.wrangler.com/collections/men",
            "urls": [
                "https://www.wrangler.com/collections/men",
                "https://www.wrangler.com/collections/women",
            ],
            "surface": "auto",
            "settings": {"playground_session_id": playground.id},
        }
    ]
    assert playground.step_data["selected_category_urls"] == [
        "https://www.wrangler.com/collections/men",
        "https://www.wrangler.com/collections/women",
    ]


@pytest.mark.asyncio
@pytest.mark.component
async def test_playground_select_category_api_accepts_batch_urls_without_missing_greenlet(
    db_session: AsyncSession,
    test_user,
    playground_api_client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playground = PlaygroundSession(
        user_id=test_user.id,
        input_url="https://www.wrangler.com/",
        state="sitemap_listed",
        step_data={},
    )
    db_session.add(playground)
    await db_session.commit()
    await db_session.refresh(playground)

    async def _fake_create_crawl_run_from_payload(session, user_id, payload):
        del session, user_id, payload
        return SimpleNamespace(id=888)

    monkeypatch.setattr(
        "app.services.playground_service.create_crawl_run_from_payload",
        _fake_create_crawl_run_from_payload,
    )

    response = await playground_api_client.post(
        f"/api/playground/sessions/{playground.id}/select-category",
        json={
            "urls": [
                "https://www.wrangler.com/collections/men",
                "https://www.wrangler.com/collections/women",
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["state"] == "discovering"
    assert payload["step_data"]["selected_category_urls"] == [
        "https://www.wrangler.com/collections/men",
        "https://www.wrangler.com/collections/women",
    ]
    assert payload["updated_at"]


@pytest.mark.asyncio
@pytest.mark.component
async def test_select_category_skips_discover_when_sitemap_urls_are_all_pdps(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    created_payloads: list[dict[str, object]] = []
    playground = PlaygroundSession(
        user_id=test_user.id,
        input_url="https://www.wrangler.com/",
        state="sitemap_listed",
        step_data={},
    )
    db_session.add(playground)
    await db_session.flush()

    async def _fake_create_crawl_run_from_payload(session, user_id, payload):
        del session, user_id
        created_payloads.append(dict(payload))
        return SimpleNamespace(id=900 + len(created_payloads))

    monkeypatch.setattr(
        "app.services.playground_service.create_crawl_run_from_payload",
        _fake_create_crawl_run_from_payload,
    )
    monkeypatch.setattr(
        "app.services.playground_service._classify_input_url",
        lambda _url: "detail",
    )

    first_run_id = await select_category(
        db_session,
        playground=playground,
        user=test_user,
        urls=[
            "https://www.wrangler.com/p/jean-1",
            "https://www.wrangler.com/p/jean-2",
        ],
    )

    assert first_run_id == 901
    assert playground.state == "extracting"
    assert playground.step_data["selected_urls"] == [
        "https://www.wrangler.com/p/jean-1",
        "https://www.wrangler.com/p/jean-2",
    ]
    assert playground.step_data["extract"]["run_ids"] == [901, 902]
    assert "discover" not in playground.step_data
    assert created_payloads == [
        {
            "run_type": "crawl",
            "url": "https://www.wrangler.com/p/jean-1",
            "surface": "auto",
            "settings": {"playground_session_id": playground.id},
        },
        {
            "run_type": "crawl",
            "url": "https://www.wrangler.com/p/jean-2",
            "surface": "auto",
            "settings": {"playground_session_id": playground.id},
        },
    ]


@pytest.mark.component
def test_merge_seed_detail_products_keeps_seed_pdps_without_duplicate_discovery() -> None:
    merged = _merge_seed_detail_products(
        {
            "seed_detail_urls": [
                "https://www.wrangler.com/p/jean-1",
                "https://www.wrangler.com/p/jean-2",
            ]
        },
        [
            {"url": "https://www.wrangler.com/p/jean-2", "title": "Jean 2"},
            {"url": "https://www.wrangler.com/c/men", "title": "Men"},
        ],
    )

    assert [row["url"] for row in merged] == [
        "https://www.wrangler.com/p/jean-1",
        "https://www.wrangler.com/p/jean-2",
        "https://www.wrangler.com/c/men",
    ]


@pytest.mark.component
def test_classify_input_url_treats_shallow_locale_root_as_sitemap() -> None:
    assert _classify_input_url("https://usa.tommy.com/en") == "sitemap"


@pytest.mark.asyncio
@pytest.mark.component
async def test_start_discover_uses_sitemap_stage_for_shallow_locale_root(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    playground = PlaygroundSession(
        user_id=test_user.id,
        input_url="https://usa.tommy.com/en",
        state="created",
        step_data={},
    )
    db_session.add(playground)
    await db_session.flush()

    async def _fake_resolve_category_urls_from_sitemap_result(
        *, domain: str, allow_homepage_fallback: bool = False
    ):
        assert domain == "https://usa.tommy.com/en"
        assert allow_homepage_fallback is True
        return SimpleNamespace(
            urls=["https://usa.tommy.com/en/women/clothing"],
            source="homepage",
        )

    monkeypatch.setattr(
        "app.services.playground_service.resolve_category_urls_from_sitemap_result",
        _fake_resolve_category_urls_from_sitemap_result,
    )

    result = await start_discover(
        db_session,
        playground=playground,
        user=test_user,
    )

    assert result == {"stage": "sitemap", "url_count": 1}
    assert playground.state == "sitemap_listed"
    assert playground.step_data["sitemap"]["source"] == "homepage"
    assert playground.step_data["sitemap"]["urls"] == [
        "https://usa.tommy.com/en/women/clothing"
    ]
