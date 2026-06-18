from __future__ import annotations

import pytest

from app.models.crawl_run import CrawlRecord
from app.services.auth_service import create_user
from app.services.crawl.access_service import (
    AccessDeniedError,
    require_accessible_record,
    require_accessible_run,
    user_can_access_run,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_require_accessible_run_allows_owner_and_admin(
    db_session,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/1",
        surface="ecommerce_detail",
    )
    other = await create_user(
        db_session,
        "other@example.com",
        "VeryStrongPassword123!",
    )

    owner_run = await require_accessible_run(
        db_session,
        run_id=run.id,
        user=test_user,
    )
    test_user.role = "admin"
    await db_session.commit()
    admin_can_access = user_can_access_run(user=test_user, run=run)

    assert owner_run.id == run.id
    assert admin_can_access is True
    with pytest.raises(AccessDeniedError, match="Run not found"):
        await require_accessible_run(db_session, run_id=run.id, user=other)


@pytest.mark.asyncio
@pytest.mark.component
async def test_require_accessible_record_checks_parent_run_owner(
    db_session,
    test_user,
    create_test_run,
) -> None:
    run = await create_test_run(
        url="https://example.com/products/1",
        surface="ecommerce_detail",
    )
    record = CrawlRecord(
        run_id=run.id,
        source_url=run.url,
        data={"title": "Widget"},
    )
    db_session.add(record)
    await db_session.commit()
    await db_session.refresh(record)
    other = await create_user(
        db_session,
        "other-record@example.com",
        "VeryStrongPassword123!",
    )

    accessible = await require_accessible_record(
        db_session,
        record_id=record.id,
        user=test_user,
    )

    assert accessible.id == record.id
    with pytest.raises(AccessDeniedError, match="Run not found"):
        await require_accessible_record(db_session, record_id=record.id, user=other)
    with pytest.raises(AccessDeniedError, match="Record not found"):
        await require_accessible_record(db_session, record_id=record.id + 999, user=test_user)


