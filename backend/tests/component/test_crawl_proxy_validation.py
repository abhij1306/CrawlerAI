"""test_crawl_service cases split by public behavior."""

from __future__ import annotations

import json
import logging

from tests.component.crawl_service_test_support import (
    AsyncSession,
    crawler_runtime_settings,
    create_crawl_run,
    pytest,
)
from app.acquisition.browser_proxy_config import display_proxy
from app.acquisition.browser_diagnostics import build_failed_browser_diagnostics
from app.core.logfire_integration import safe_logfire_attributes
from app.core.proxy_secrets import redact_secret_text
from app.core.telemetry import _SecretRedactionFilter
from app.schemas.crawl import CrawlRunResponse


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


@pytest.mark.asyncio
@pytest.mark.component
async def test_proxy_secret_never_persists_or_serializes_in_plaintext(
    db_session: AsyncSession,
    test_user,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = "proxy-password-sentinel"
    raw_proxy = f"http://proxy-user:{sentinel}@10.0.0.8:8080"
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
            "settings": {"proxy_enabled": True, "proxy_list": [raw_proxy]},
        },
    )

    persisted = json.dumps(run.settings)
    response = CrawlRunResponse.model_validate(run, from_attributes=True).model_dump(
        mode="json"
    )
    assert sentinel not in persisted
    assert sentinel not in json.dumps(response)
    assert "proxy_secret_refs" not in response["settings"]
    assert run.settings_view.proxy_list() == [raw_proxy]
    assert sentinel not in display_proxy(raw_proxy)
    assert sentinel not in json.dumps(safe_logfire_attributes({"proxy_url": raw_proxy}))


@pytest.mark.asyncio
@pytest.mark.component
async def test_proxy_validation_error_does_not_echo_credentials(
    db_session: AsyncSession,
    test_user,
) -> None:
    sentinel = "proxy-password-sentinel"

    with pytest.raises(ValueError) as exc_info:
        await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "crawl",
                "url": "https://example.com/product/widget",
                "surface": "ecommerce_detail",
                "settings": {
                    "proxy_list": [f"ftp://proxy-user:{sentinel}@proxy.internal:21"]
                },
            },
        )

    assert sentinel not in str(exc_info.value)


def test_proxy_secret_redactor_covers_diagnostics_logs_and_exceptions() -> None:
    sentinel = "proxy-password-sentinel"
    raw_proxy = f"http://proxy-user:{sentinel}@proxy.internal:8080"
    exc = RuntimeError(f"transport failed through {raw_proxy}/route?token={sentinel}")

    diagnostics = build_failed_browser_diagnostics(
        browser_reason="http-escalation",
        exc=exc,
        proxy=raw_proxy,
    )
    record = logging.LogRecord(
        name="proxy-test",
        level=logging.ERROR,
        pathname=__file__,
        lineno=1,
        msg="failed via %s",
        args=(raw_proxy,),
        exc_info=(type(exc), exc, exc.__traceback__),
    )
    assert _SecretRedactionFilter().filter(record) is True

    assert sentinel not in redact_secret_text(str(exc))
    assert sentinel not in json.dumps(diagnostics)
    assert sentinel not in record.getMessage()
    assert sentinel not in str(record.exc_text)
