"""Hard input caps for run creation: urls per run, max_records, CSV persistence."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.crawl.ingestion_service import build_csv_crawl_payload
from app.models.crawl_settings import CrawlRunSettings
from app.schemas.crawl import CrawlCreate, enforce_run_url_limit


def _batch_payload(urls: list[str]) -> dict:
    return {"run_type": "batch", "surface": "ecommerce_detail", "urls": urls}


@pytest.mark.unit
def test_crawl_create_rejects_urls_beyond_configured_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_run_urls", 3)
    with pytest.raises(ValidationError):
        CrawlCreate(
            **_batch_payload([f"https://example.com/p/{idx}" for idx in range(4)])
        )


@pytest.mark.unit
def test_crawl_create_accepts_urls_at_configured_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_run_urls", 3)
    payload = CrawlCreate(
        **_batch_payload([f"https://example.com/p/{idx}" for idx in range(3)])
    )
    assert len(payload.urls) == 3


@pytest.mark.unit
def test_enforce_run_url_limit_message_includes_configured_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_run_urls", 7)
    with pytest.raises(ValueError, match="at most 7"):
        enforce_run_url_limit(["https://example.com"] * 8)


@pytest.mark.component
async def test_create_crawl_run_enforces_cap_on_settings_payload_urls(
    db_session, test_user, monkeypatch
) -> None:
    """settings.urls must not bypass the run URL cap.

    The CrawlCreate schema validator only sees the top-level urls field, so a
    batch payload carrying urls inside settings previously skipped the cap.
    """
    from app.crawl.crud import create_crawl_run

    monkeypatch.setattr(settings, "max_run_urls", 2)
    with pytest.raises(ValueError, match="at most 2"):
        await create_crawl_run(
            db_session,
            test_user.id,
            {
                "run_type": "batch",
                "surface": "ecommerce_detail",
                "settings": {
                    "urls": [
                        "https://example.com/a",
                        "https://example.com/b",
                        "https://example.com/c",
                    ]
                },
            },
        )


@pytest.mark.unit
def test_max_records_is_bounded_by_configured_maximum(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_run_records", 500)
    assert CrawlRunSettings.from_value({"max_records": 10_000}).max_records() == 500
    assert CrawlRunSettings.from_value({"max_records": 50}).max_records() == 50
    assert CrawlRunSettings.from_value({}).max_records() > 0


@pytest.mark.unit
def test_csv_payload_persists_parsed_urls_without_raw_csv_content() -> None:
    data, url_count = build_csv_crawl_payload(
        csv_content="https://example.com/a\nhttps://example.com/b\n",
        surface="ecommerce_detail",
    )
    assert url_count == 2
    assert "csv_content" not in data["settings"]
    assert data["settings"]["urls"] == [
        "https://example.com/a",
        "https://example.com/b",
    ]
    assert data["urls"] == data["settings"]["urls"]


@pytest.mark.unit
def test_csv_payload_rejects_urls_beyond_configured_cap(monkeypatch) -> None:
    monkeypatch.setattr(settings, "max_run_urls", 1)
    with pytest.raises(ValueError, match="at most 1"):
        build_csv_crawl_payload(
            csv_content="https://example.com/a\nhttps://example.com/b\n",
            surface="ecommerce_detail",
        )
