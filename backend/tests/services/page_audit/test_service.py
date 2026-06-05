from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.page_audit.service import build_page_audit_report

pytestmark = pytest.mark.component


@pytest.mark.asyncio
async def test_build_page_audit_report_fetches_source_and_rendered_dom(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    source_html = "<html><body><p>Server content</p></body></html>"
    rendered_html = (
        "<html><body><h1>Rendered heading</h1>"
        "<p>Server content</p><p>Client rendered content block.</p></body></html>"
    )

    async def fake_fetch_page(url: str, **kwargs):
        calls.append({"url": url, **kwargs})
        if kwargs["fetch_mode"] == "http_only":
            return SimpleNamespace(
                html=source_html,
                final_url=url,
                status_code=200,
                method="http",
                artifacts={},
                browser_diagnostics={},
            )
        return SimpleNamespace(
            html="<html><body>fallback</body></html>",
            final_url=url,
            status_code=200,
            method="browser",
            artifacts={"full_rendered_html": rendered_html},
            browser_diagnostics={"browser_engine": "patchright"},
        )

    async def fake_validate_public_target(url: str):
        return SimpleNamespace(hostname="example.com")

    monkeypatch.setattr("app.services.page_audit.service.fetch_page", fake_fetch_page)
    monkeypatch.setattr(
        "app.services.page_audit.service.validate_public_target",
        fake_validate_public_target,
    )

    report = await build_page_audit_report("example.com/page")

    assert [call["fetch_mode"] for call in calls] == ["http_only", "browser_only"]
    assert calls[1]["prefer_browser"] is True
    assert report["url"] == "https://example.com/page"
    assert report["render_summary"]["browser_engine"] == "patchright"
    assert report["render_summary"]["source_status_code"] == 200
    assert report["render_summary"]["dom_status_code"] == 200
    assert report["render_summary"]["dom_only_text_count"] == 1
