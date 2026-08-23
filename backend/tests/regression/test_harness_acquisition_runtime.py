from __future__ import annotations

# ruff: noqa: F403, F405
from .harness_runtime_test_support import *


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_site_harness_supports_acquisition_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    class _FakeSettingsView:
        def acquisition_plan(self, *, surface: str):
            return AcquisitionIntent(surface=surface)

    async def _fake_create_crawl_run(session, user_id, payload):
        del session, user_id
        return SimpleNamespace(
            id=11,
            status="queued",
            url=payload["url"],
            settings_view=_FakeSettingsView(),
        )

    async def _fake_ensure_harness_user_id(session):
        del session
        return 7

    async def _fake_process_single_url(*, session, run, url, config):
        del session, run, url, config
        return SimpleNamespace(
            verdict="success",
            url_metrics={
                "method": "curl_cffi",
                "platform_family": "generic",
                "status_code": 200,
                "blocked": False,
                "record_count": 0,
                "browser_diagnostics": {},
            },
        )

    monkeypatch.setattr(harness_support, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        harness_support,
        "_ensure_harness_user_id",
        _fake_ensure_harness_user_id,
    )
    monkeypatch.setattr(harness_support, "create_crawl_run", _fake_create_crawl_run)
    monkeypatch.setattr(harness_support, "process_single_url", _fake_process_single_url)

    result = await harness_support.run_site_harness(
        url="https://example.com/catalog",
        surface="ecommerce_listing",
        mode=harness_support.HARNESS_MODE_ACQUISITION_ONLY,
    )

    assert result["verdict"] == "success"
    assert result["method"] == "curl_cffi"
    assert result["status_code"] == 200
    assert result["records"] == 0


@pytest.mark.asyncio
@pytest.mark.regression
async def test_run_site_harness_surfaces_challenge_summary_in_acquisition_only_mode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            del exc_type, exc, tb
            return False

    class _FakeSettingsView:
        def acquisition_plan(self, *, surface: str):
            return AcquisitionIntent(surface=surface)

    async def _fake_create_crawl_run(session, user_id, payload):
        del session, user_id
        return SimpleNamespace(
            id=12,
            status="queued",
            url=payload["url"],
            settings_view=_FakeSettingsView(),
        )

    async def _fake_ensure_harness_user_id(session):
        del session
        return 7

    async def _fake_process_single_url(*, session, run, url, config):
        del session, run, url, config
        return SimpleNamespace(
            verdict="blocked",
            url_metrics={
                "method": "browser",
                "platform_family": "generic",
                "status_code": 429,
                "blocked": True,
                "record_count": 0,
                "browser_diagnostics": {
                    "browser_outcome": "challenge_page",
                    "challenge_provider_hits": ["DataDome"],
                    "challenge_evidence": [
                        "http_status:429",
                        "title:Verifying your connection...",
                    ],
                },
            },
        )

    monkeypatch.setattr(harness_support, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(
        harness_support,
        "_ensure_harness_user_id",
        _fake_ensure_harness_user_id,
    )
    monkeypatch.setattr(harness_support, "create_crawl_run", _fake_create_crawl_run)
    monkeypatch.setattr(harness_support, "process_single_url", _fake_process_single_url)

    result = await harness_support.run_site_harness(
        url="https://example.com/catalog",
        surface="ecommerce_listing",
        mode=harness_support.HARNESS_MODE_ACQUISITION_ONLY,
    )

    assert result["verdict"] == "blocked"
    assert result["challenge_summary"] == {
        "browser_outcome": "challenge_page",
        "provider": "datadome",
        "providers": ["datadome"],
        "elements": [],
        "evidence": [
            "http_status:429",
            "title:Verifying your connection...",
        ],
    }
