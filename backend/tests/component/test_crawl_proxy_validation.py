"""test_crawl_service cases split by public behavior."""

from __future__ import annotations

from tests.component.crawl_service_test_support import (
    AsyncSession,
    crawler_runtime_settings,
    create_crawl_run,
    pytest,
)


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_rejects_malformed_proxy_endpoints(
    db_session: AsyncSession,
    test_user,
) -> None:
    with pytest.raises(ValueError, match="proxy endpoints are allowed"):
        await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/product/widget",
                "surface": "ecommerce_detail",
                "settings": {"proxy_list": ["ftp://proxy.internal:21"]},
            },
        )

    with pytest.raises(ValueError, match="must include a hostname"):
        await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/product/widget",
                "surface": "ecommerce_detail",
                "settings": {"proxy_list": ["http://:8080"]},
            },
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_rejects_private_ip_proxy_when_validation_enabled(
    db_session: AsyncSession,
    test_user,
) -> None:
    with pytest.raises(ValueError, match="Proxy host resolves to a non-public IP"):
        await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/product/widget",
                "surface": "ecommerce_detail",
                "settings": {"proxy_list": ["http://10.0.0.8:8080"]},
            },
        )


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_accepts_private_ip_proxy_when_validation_disabled(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        crawler_runtime_settings, "proxy_endpoint_validation_enabled", False
    )

    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "settings": {"proxy_list": ["http://10.0.0.8:8080"]},
        },
    )

    assert run.id is not None


@pytest.mark.asyncio
@pytest.mark.component
async def test_create_crawl_run_accepts_public_proxy_when_validation_enabled(
    db_session: AsyncSession,
    test_user,
) -> None:
    run = await create_crawl_run(
        db_session,
        test_user.id,
        {
            "run_type": "crawl",
            "url": "https://example.com/product/widget",
            "surface": "ecommerce_detail",
            "settings": {"proxy_list": ["http://93.184.216.34:8080"]},
        },
    )

    assert run.id is not None
