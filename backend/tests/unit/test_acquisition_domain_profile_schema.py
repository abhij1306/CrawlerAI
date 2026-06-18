from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.services.acquisition.domain_profile_schema import (
    DomainProfileV2,
    SelectorRule,
    parse_domain_profile_v2,
)
from app.services.config.domain_profiles import DOMAIN_PROFILE_SCHEMA_VERSION


@pytest.mark.unit
def test_parse_v2_profile_round_trips() -> None:
    profile = DomainProfileV2(domain="example.com")
    payload = profile.model_dump(mode="json")

    assert parse_domain_profile_v2(payload).model_dump(mode="json") == payload


@pytest.mark.unit
def test_parse_profile_rejects_invalid_traversal_mode() -> None:
    with pytest.raises(ValidationError, match="traversal_mode"):
        parse_domain_profile_v2(
            {
                "schema_version": DOMAIN_PROFILE_SCHEMA_VERSION,
                "domain": "example.com",
                "fetch_profile": {
                    "fetch_mode": "browser_only",
                    "traversal_mode": "unsupported_mode",
                },
            }
        )


@pytest.mark.unit
def test_v2_valid_traversal_mode_round_trips() -> None:
    profile = parse_domain_profile_v2(
        {
            "schema_version": DOMAIN_PROFILE_SCHEMA_VERSION,
            "domain": "example.com",
            "fetch_profile": {
                "fetch_mode": "browser_only",
                "traversal_mode": "paginate",
            },
        }
    )

    assert profile.fetch_profile.traversal_mode == "paginate"


@pytest.mark.unit
def test_invalid_profile_data_has_explicit_validation_errors() -> None:
    with pytest.raises(ValidationError) as exc:
        SelectorRule(field_name="", selector="", hit_count=-1)

    text = str(exc.value)
    assert "field_name" in text
    assert "selector" in text
    assert "hit_count" in text


@pytest.mark.unit
def test_parse_profile_falls_back_for_non_mapping_payload() -> None:
    profile = parse_domain_profile_v2("not a profile")

    assert profile.domain == ""
    assert profile.surface == DomainProfileV2().surface
    assert profile.selector_rules == []
