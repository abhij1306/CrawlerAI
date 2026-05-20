from __future__ import annotations

import pytest

import app.services.crawl.crud as crawl_crud
from app.models.crawl_run import CrawlLog


@pytest.mark.asyncio
async def test_get_run_and_logs_returns_run_even_without_logs(
    db_session,
    test_user,
) -> None:
    run = await crawl_crud.create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )

    loaded_run, rows = await crawl_crud.get_run_and_logs(db_session, run.id, limit=500)

    assert loaded_run is not None
    assert loaded_run.id == run.id
    assert rows == []


@pytest.mark.asyncio
async def test_get_run_and_logs_applies_after_id_filter(
    db_session,
    test_user,
) -> None:
    run = await crawl_crud.create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/products/widget",
            "surface": "ecommerce_detail",
            "settings": {},
        },
    )
    first = CrawlLog(run_id=run.id, level="info", message="first")
    second = CrawlLog(run_id=run.id, level="info", message="second")
    db_session.add_all([first, second])
    await db_session.commit()
    await db_session.refresh(first)
    await db_session.refresh(second)

    loaded_run, rows = await crawl_crud.get_run_and_logs(
        db_session,
        run.id,
        after_id=first.id,
        limit=500,
    )

    assert loaded_run is not None
    assert loaded_run.id == run.id
    assert [row.message for row in rows] == ["second"]
