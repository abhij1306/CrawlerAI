"""Slice 4 / Task B4: verdict Literal coverage (verify-only).

Phase 0 already renamed the empty-listing verdict from ``listing_failed`` to
``listing_detection_failed`` and added it to the ``UrlVerdict`` Literal. These
tests lock that contract in: the Literal carries the new member (and not the
old one), the ``verdict`` module constant matches it, and ``compute_verdict``
returns it for an empty listing. No production code is modified.
"""

from __future__ import annotations

import pytest

from app.crawl.pipeline.extraction_loop import UrlVerdict
from app.persistence.publish.verdict import (
    VERDICT_LISTING_FAILED,
    compute_verdict,
)

pytestmark = pytest.mark.unit


def test_url_verdict_contains_listing_detection_failed() -> None:
    assert "listing_detection_failed" in UrlVerdict.__args__
    assert "listing_failed" not in UrlVerdict.__args__


def test_verdict_constant_matches_url_verdict() -> None:
    assert VERDICT_LISTING_FAILED == "listing_detection_failed"
    assert VERDICT_LISTING_FAILED in UrlVerdict.__args__


def test_compute_verdict_returns_listing_detection_failed_for_empty_listing() -> None:
    assert (
        compute_verdict(is_listing=True, blocked=False, record_count=0)
        == VERDICT_LISTING_FAILED
    )
