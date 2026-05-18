from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from app.services.ucp_audit.discovery import discover_ucp_manifest


@dataclass(slots=True)
class DummyPage:
    status_code: int
    html: str


@pytest.mark.asyncio
async def test_manifest_404_returns_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_page(*args, **kwargs):
        return DummyPage(status_code=404, html="")

    monkeypatch.setattr(
        "app.services.ucp_audit.discovery._fetch_manifest_page",
        fake_fetch_page,
    )

    result = await discover_ucp_manifest("example.com")

    assert result.manifest_found is False
    assert result.manifest_valid is False
    assert result.raw_manifest is None
    assert result.errors == ["/.well-known/ucp returned 404"]


@pytest.mark.asyncio
async def test_valid_manifest_parses_capabilities(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_page(*args, **kwargs):
        return DummyPage(
            status_code=200,
            html=json.dumps(
                {
                    "capabilities": {
                        "product_discovery": {},
                        "checkout": {},
                        "orders": {},
                    }
                }
            ),
        )

    monkeypatch.setattr(
        "app.services.ucp_audit.discovery._fetch_manifest_page",
        fake_fetch_page,
    )

    result = await discover_ucp_manifest("https://example.com")

    assert result.manifest_found is True
    assert result.manifest_valid is True
    assert result.capabilities_declared == ["checkout", "orders", "product_discovery"]
    assert result.missing_required_capabilities == []


@pytest.mark.asyncio
async def test_valid_manifest_accepts_ucp_services(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_page(*args, **kwargs):
        return DummyPage(
            status_code=200,
            html=json.dumps(
                {
                    "ucp": {
                        "services": {
                            "dev.ucp.shopping": [
                                {
                                    "version": "2026-04-08",
                                    "transport": "mcp",
                                }
                            ]
                        }
                    }
                }
            ),
        )

    monkeypatch.setattr(
        "app.services.ucp_audit.discovery._fetch_manifest_page",
        fake_fetch_page,
    )

    result = await discover_ucp_manifest("https://example.com")

    assert result.manifest_found is True
    assert result.manifest_valid is True
    assert result.capabilities_declared == ["dev.ucp.shopping"]
    assert result.missing_required_capabilities == []


@pytest.mark.asyncio
async def test_invalid_manifest_json_reports_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch_page(*args, **kwargs):
        return DummyPage(status_code=200, html="{not-json")

    monkeypatch.setattr(
        "app.services.ucp_audit.discovery._fetch_manifest_page",
        fake_fetch_page,
    )

    result = await discover_ucp_manifest("example.com")

    assert result.manifest_found is True
    assert result.manifest_valid is False
    assert result.raw_manifest is None
    assert result.errors
