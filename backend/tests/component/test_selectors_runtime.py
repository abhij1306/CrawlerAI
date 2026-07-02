from __future__ import annotations

import pytest

from app.crawl.domain_memory_service import save_domain_memory
from app.core.records.selectors_runtime import (
    fetch_selector_document,
    list_selector_records,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_fetch_selector_document_rejects_private_targets() -> None:
    with pytest.raises(ValueError):
        await fetch_selector_document("http://localhost/internal")


@pytest.mark.asyncio
@pytest.mark.component
async def test_list_selector_records_without_surface_returns_all_domain_surfaces(
    db_session,
) -> None:
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="ecommerce_detail",
        selectors={
            "rules": [
                {"id": 1, "field_name": "title", "css_selector": "h1"},
            ]
        },
    )
    await save_domain_memory(
        db_session,
        domain="example.com",
        surface="job_detail",
        selectors={
            "rules": [
                {"id": 2, "field_name": "title", "css_selector": ".job-title"},
            ]
        },
    )
    await db_session.commit()

    rows = await list_selector_records(db_session, domain="example.com")

    assert {(row["surface"], row["field_name"]) for row in rows} == {
        ("ecommerce_detail", "title"),
        ("job_detail", "title"),
    }
