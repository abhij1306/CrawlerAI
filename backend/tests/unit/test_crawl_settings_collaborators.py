"""CrawlRunSettings god-class split: derived-view collaborators keep the public
call surface behavior-identical."""
from __future__ import annotations

import pytest

from app.models.crawl_settings import CrawlRunSettings
from app.models.crawl_settings_views import (
    AcquisitionContractView,
    ProxySettingsView,
    RunExecutionView,
    RunProfileView,
)

pytestmark = pytest.mark.unit


def _settings(data: dict) -> CrawlRunSettings:
    return CrawlRunSettings.from_value(data)


def test_execution_view_matches_delegated_accessors() -> None:
    data = {
        "urls": [" https://example.com/a "],
        "max_records": "25",
        "fetch_profile": {
            "max_pages": 4,
            "request_delay_ms": 120,
            "traversal_mode": "paginate",
        },
        "respect_robots_txt": True,
        "advanced_enabled": True,
        "advanced_mode": "paginate",
    }
    settings_view = _settings(data)
    execution = RunExecutionView(dict(data))
    assert settings_view.urls() == execution.urls() == ["https://example.com/a"]
    assert settings_view.max_records() == execution.max_records() == 25
    assert settings_view.max_pages() == execution.max_pages() == 4
    assert settings_view.sleep_ms() == execution.sleep_ms() == 120
    assert settings_view.respect_robots_txt() is execution.respect_robots_txt() is True
    assert settings_view.advanced_enabled() is execution.advanced_enabled() is True
    assert settings_view.traversal_mode() == execution.traversal_mode() == "paginate"
    assert settings_view.fetch_profile() == execution.fetch_profile()


def test_proxy_view_infers_sticky_rotation_and_honors_flag() -> None:
    data = {
        "proxy_profile": {
            "enabled": True,
            "proxy_list": ["http://user-session-abc:pw@proxy.example:8080"],
        }
    }
    settings_view = _settings(data)
    proxy = ProxySettingsView(dict(data))
    inferred = settings_view.proxy_profile()
    assert inferred["enabled"] is True
    assert inferred["proxy_list"] == ["http://user-session-abc:pw@proxy.example:8080"]
    # Default sticky username markers ("-session-", "session-") mark the rotation.
    assert inferred["rotation"] == "sticky"
    # Rotation inference is skipped when disabled, and delegates match the view.
    without_inference = settings_view.proxy_profile(infer_rotation=False)
    assert "rotation" not in without_inference
    assert without_inference == proxy.proxy_profile(infer_rotation=False)


def test_proxy_view_keeps_stored_rotation() -> None:
    settings_view = _settings(
        {"proxy_profile": {"enabled": True, "rotation": "round_robin"}}
    )
    assert settings_view.proxy_profile()["rotation"] == "round_robin"


def test_acquisition_contract_view_browser_only_disables_handoff() -> None:
    data = {
        "fetch_profile": {"fetch_mode": "browser_only"},
        "acquisition_contract": {"prefer_curl_handoff": True, "prefer_browser": False},
    }
    settings_view = _settings(data)
    contract = settings_view.acquisition_contract()
    assert contract == AcquisitionContractView(dict(data)).acquisition_contract()
    assert contract["handoff_eligible"] is False
    assert contract["prefer_browser"] is True
    assert contract["handoff_cookie_engine"] == "auto"


def test_run_profile_view_composes_storage_payload() -> None:
    data = {
        "urls": ["https://example.com/p/1"],
        "advanced_enabled": False,
        "advanced_mode": "scroll",
        "locality_profile": {"geo_country": "us"},
        "diagnostics_profile": {"capture_screenshot": True},
    }
    settings_view = _settings(data)
    profile = RunProfileView(dict(data))
    assert settings_view.locality_profile() == profile.locality_profile()
    assert settings_view.diagnostics_profile() == profile.diagnostics_profile()
    assert settings_view.acquisition_profile() == profile.acquisition_profile()
    normalized = settings_view.normalized_for_storage()
    assert normalized == profile.normalized_for_storage()
    assert normalized["urls"] == ["https://example.com/p/1"]
    # Advanced mode is cleared when advanced settings are disabled.
    assert normalized["advanced_mode"] is None
    assert normalized["locality_profile"]["geo_country"] == "us"
    assert normalized["diagnostics_profile"]["capture_screenshot"] is True


def test_acquisition_plan_surface_validation_and_defaults() -> None:
    settings_view = _settings({"max_records": 10, "proxy_list": "http://u:p@h:1"})
    plan = settings_view.acquisition_plan(surface=" ECOMMERCE_DETAIL ")
    assert plan.surface == "ecommerce_detail"
    assert plan.max_records == 10
    assert plan.proxy_list == ("http://u:p@h:1",)
    override = settings_view.acquisition_plan(surface="job_detail", max_records=1)
    assert override.max_records == 1
    with pytest.raises(ValueError, match="surface must be one of"):
        settings_view.acquisition_plan(surface="bogus")
