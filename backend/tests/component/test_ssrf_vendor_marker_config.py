from __future__ import annotations

import pytest

from app.acquisition import browser_block_detection, browser_recovery
from app.acquisition import runtime as acquisition_runtime
from app.core.config import block_signatures


@pytest.mark.component
def test_bot_vendor_header_markers_live_in_config() -> None:
    assert (
        acquisition_runtime.BOT_VENDOR_HEADER_MARKERS
        is block_signatures.BOT_VENDOR_HEADER_MARKERS
    )
    assert ("x-datadome", "", "datadome") in block_signatures.BOT_VENDOR_HEADER_MARKERS
    assert (
        "cf-mitigated",
        "challenge",
        "cloudflare",
    ) in block_signatures.BOT_VENDOR_HEADER_MARKERS


@pytest.mark.component
@pytest.mark.parametrize(
    ("headers", "expected"),
    [
        ({"x-datadome": "abc"}, "datadome"),
        ({"X-Datadome-Cid": "abc"}, "datadome"),
        ({"server": "DataDome"}, "datadome"),
        ({"cf-mitigated": "challenge"}, "cloudflare"),
        ({"cf-mitigated": "managed"}, None),
        ({"x-sucuri-id": "1"}, "sucuri"),
        ({"x-akamai-transformed": "1"}, "akamai"),
        ({"akamai-grn": "1"}, "akamai"),
        ({"x-px-block": "1"}, "perimeterx"),
        ({"content-type": "text/html"}, None),
    ],
)
def test_classify_block_from_headers_uses_config_markers(headers, expected) -> None:
    assert acquisition_runtime.classify_block_from_headers(headers) == expected


@pytest.mark.component
def test_cloudflare_provider_tokens_live_in_config() -> None:
    assert (
        browser_recovery.CLOUDFLARE_PROVIDER_TOKENS
        is block_signatures.CLOUDFLARE_PROVIDER_TOKENS
    )
    assert (
        browser_block_detection.CLOUDFLARE_PROVIDER_TOKENS
        is block_signatures.CLOUDFLARE_PROVIDER_TOKENS
    )
    assert block_signatures.CLOUDFLARE_PROVIDER_TOKENS == frozenset(
        {"cloudflare", "cf-challenge", "cf-browser-verification"}
    )


def _evidence(**overrides) -> browser_block_detection._BlockEvidence:
    values = {
        "forced_blocked": False,
        "forced_outcome": "",
        "base_evidence": [],
        "has_extractable_content": False,
        "has_listing_content": False,
        "has_product_identity": False,
        "shell_title": "",
        "title_matches": [],
        "strong_hits": {"just a moment"},
        "weak_hits": set(),
        "provider_hits": set(),
        "active_provider_hits": set(),
        "challenge_element_hits": set(),
        "hard_strong_hits": set(),
    }
    values.update(overrides)
    return browser_block_detection._BlockEvidence(**values)


@pytest.mark.component
@pytest.mark.parametrize(
    "provider_token",
    ["cloudflare", "cf-challenge", "cf-browser-verification"],
)
def test_just_a_moment_cloudflare_gate_matches_config_tokens(
    provider_token: str,
) -> None:
    assert (
        browser_block_detection._block_policy_matches(
            _evidence(provider_hits={provider_token})
        )
        is True
    )


@pytest.mark.component
def test_just_a_moment_without_cloudflare_evidence_does_not_match_gate() -> None:
    assert (
        browser_block_detection._block_policy_matches(_evidence(provider_hits=set()))
        is False
    )
